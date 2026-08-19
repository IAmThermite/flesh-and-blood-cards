#!/usr/bin/env python3
"""
Pull newly published cards for the sets currently being spoiled out of the CardVault API
and append them to the English CSVs.

This runs in two passes:

    python main.py --sets MPW AOL     # append rows with blank Unique IDs
    ../generate-unique-ids.sh         # add the Unique IDs
    python main.py --link             # fill in the references that needed those IDs

Double faced printings - a Marvel with the card on both sides, or a flip card like Viserai -
take a card-printing.csv row per face plus a card-face-association.csv row tying the two
together. That association row references printing Unique IDs, so the fetch pass stashes it
in pending-face-associations-<slug>.json and --link writes it out.

Everything the API states outright is filled in. The keyword columns, arcane, expansion
slot and the exact art variation are left blank and listed in the report, because they're a
reading of the card rather than something the API knows.
"""

import argparse
import json
import os
import re
import sys
from pathlib import Path

import cardvault
import checklist
import csv_io
import mapping
from csv_io import CSV_DIR, build_row, column_index, read_csv, write_csv
from report import Report

RUN_DIR = Path(__file__).parent
PENDING_PREFIX = "pending-face-associations"

# A print_id wraps the set number in a language prefix (JA_), an edition prefix (U- for
# Unlimited, R- for Unlimited Revised) and a treatment suffix (-RF, -MV), in any combination.
# Rather than peel those off one at a time, pull the set number straight out of the middle.
SET_NUMBER = "{}[0-9]+"


def base_print_code(print_id, set_code):
    """
    MPW024-RF -> MPW024, JA_IAR159-RF -> IAR159, R-WTR006-RF -> WTR006.

    The CSVs record the set number as printed on the card and describe the treatment in the
    Foiling and Art Variations columns instead. Only used for the cheap "have we seen this
    set number before" filter, so an unrecognisable print_id just means the card gets looked
    at properly rather than skipped.
    """

    match = re.search(SET_NUMBER.format(re.escape(set_code)), print_id or "")
    return match.group(0) if match else ""


def load_set_group(args):
    """
    The group of set codes this run covers, from --sets or $SPOILER_SETS.

    One run is one group is one branch. Sets that share a release date belong together -
    Mastery Pack Warrior and Armory Deck Olympia land at the same time and share printings,
    so putting them on one branch keeps a card that appears in both out of two branches at
    once. Sets on different release dates should be separate runs.

    Both "--sets MPW AOL" and "--sets MPW,AOL" work, as does SPOILER_SETS="MPW,AOL".
    """

    raw = args.sets or ([os.environ["SPOILER_SETS"]] if os.environ.get("SPOILER_SETS") else [])
    if not raw:
        raise SystemExit(
            "no sets given - pass --sets MPW AOL (or set SPOILER_SETS=MPW,AOL)"
        )

    codes = []
    for value in raw:
        for code in str(value).replace(",", " ").split():
            code = code.strip().upper()
            if code and code not in codes:
                codes.append(code)

    if not codes:
        raise SystemExit("no set codes to check")

    return codes


def group_slug(set_codes):
    """
    A stable name for a group of sets, used for the branch and this run's files.

    Sorted so that "MPW AOL" and "AOL MPW" are the same group and don't produce two branches
    for the same work.
    """

    return "-".join(sorted(code.lower() for code in set_codes))


def report_path(args, set_codes):
    return args.report_file or RUN_DIR / f"report-{group_slug(set_codes)}.md"


def pending_path(args, set_codes):
    return args.pending_file or RUN_DIR / f"{PENDING_PREFIX}-{group_slug(set_codes)}.json"


def checklist_path(args, set_codes):
    return args.checklist_file or RUN_DIR / f"checklist-{group_slug(set_codes)}.json"


def write_github_output(values):
    """
    Hand the workflow what it needs to make a branch, if we're running under Actions.

    Writing to $GITHUB_OUTPUT is how a step exposes values to later steps; outside Actions
    the variable isn't set and this does nothing.
    """

    target = os.environ.get("GITHUB_OUTPUT")
    if not target:
        return

    with open(target, "a", encoding="utf-8") as handle:
        for key, value in values.items():
            handle.write(f"{key}={value}\n")


def face_lookup_key(printing):
    """
    Enough of a printing row to find it again once it has a Unique ID.

    The two rows of a double sided printing share everything except the image, so the image
    URL is what separates the front from the back. It comes from the API in both passes, so
    the match is exact rather than a guess at a naming convention.
    """

    return [
        printing["Set ID"],
        printing["Card ID"],
        printing["Foiling"],
        printing["Image URL"],
    ]


def english_prints_for_set(card, set_code):
    """The English printings of a card that belong to the set we're looking at."""

    selected = []
    for print_data in card.get("card_prints") or []:
        if print_data.get("print_language") != "en":
            continue
        if not print_data.get("is_published"):
            continue
        if (print_data.get("print_set") or {}).get("set_code") != set_code:
            continue
        selected.append(print_data)

    return selected


def collect_set(set_code, existing, report, full_sweep):
    """
    Work out what's new for one set and return the rows to append.

    Returns (card_fields_list, printing_plans), where a printing plan is a
    (fields, card_key) pair - the card key is needed because a printing of a brand new card
    can't be given a Card Unique ID until generate-unique-ids has run.
    """

    existing_cards, existing_codes, existing_printings, existing_pitches = existing

    set_printing = csv_io.resolve_set_printing(set_code)
    if set_printing is None:
        report.blocked.append(
            f"{set_code}: not in set.csv / set-printing.csv yet. Add the set (and its 'N' "
            f"set printing) by hand, run generate-unique-ids, then re-run."
        )
        return [], [], []

    set_printing_unique_id, start_card_id, end_card_id = set_printing

    print(f"Searching CardVault for {set_code}...")
    cards_in_set = cardvault.search_set(set_code)
    print(f"  {len(cards_in_set)} published cards")

    known_codes = existing_codes.get(set_code, set())

    card_ids = []
    for card in cards_in_set:
        card_id = card.get("card_id")
        if not card_id:
            continue
        # Cheap filter: unless we're doing a full sweep, only look at cards whose set number
        # is absent from the CSVs entirely. A full sweep re-checks every card, which also
        # picks up extra treatments added to a card we ingested earlier.
        if full_sweep or base_print_code(card.get("print_id"), set_code) not in known_codes:
            card_ids.append((card_id, card.get("published_at") or ""))

    if not card_ids:
        print(f"  nothing new in {set_code}")
        return [], [], []

    print(f"  fetching {len(card_ids)} card details...")

    new_cards = []
    printing_plans = []
    associations = []
    seen_card_keys = set()
    written_this_run = {}
    out_of_range = set()
    queued_cards = {}

    def ensure_card(core, face, code):
        """
        Queue a card.csv row for a core we haven't seen before, and return its key.

        `code` is the set number of the printing that turned the card up, carried through so
        the report and the checklist can name the card the way it'll be looked up.
        """

        card_key = mapping.card_key(core, face)
        fields = mapping.card_fields(core, face)

        # Not every face repeats the printed stats - Levia's IAR002-MV face leaves off the
        # life and intellect that IAR002 carries - so let a later face fill any blank the
        # first one left. Only blanks are filled, never an existing value.
        if card_key in queued_cards:
            for column, value in fields.items():
                if value and not queued_cards[card_key][column]:
                    queued_cards[card_key][column] = value
            return card_key

        # Newly added cards go straight into existing_cards with a blank Unique ID so that a
        # card printed in two of the watched sets doesn't get a second card.csv row.
        if card_key not in existing_cards and card_key not in seen_card_keys:
            queued_cards[card_key] = fields
            new_cards.append(fields)
            seen_card_keys.add(card_key)
            existing_cards[card_key] = ""
            report.new_cards.append(
                f"{code} {card_key[0]}" + (f" ({card_key[1]})" if card_key[1] else "")
            )

            # A card that's new only because the pitch disagrees is usually a real new pitch
            # variant, but it can also mean CardVault left the pitch off - it does that on
            # the back face of Part the Mistveil's transcend cards, where Inner Chi comes
            # back with no pitch against the CSVs' 3. Writing that blind duplicates the card.
            known_pitches = existing_pitches.get(card_key[0])
            if known_pitches:
                report.check_pitch.append(
                    f"{card_key[0]!r}: added with pitch {card_key[1] or '(none)'}, but "
                    f"card.csv already has pitch {', '.join(sorted(p or '(none)' for p in known_pitches))} "
                    f"- confirm it's a new variant rather than a duplicate"
                )

        return card_key

    for card_id, published_at in card_ids:
        card = cardvault.get_card(card_id)
        if card is None:
            report.errors.append(f"{set_code}: could not fetch card '{card_id}'")
            continue

        cores_by_id = {core["id"]: core for core in card.get("cores") or [] if core.get("id")}
        if not cores_by_id:
            report.errors.append(f"{set_code}: '{card_id}' has no core data")
            continue

        for print_data in english_prints_for_set(card, set_code):
            print_id = print_data.get("print_id")
            faces = mapping.faces_in_order(print_data)

            if not faces:
                report.errors.append(f"{set_code}: {print_id} has no faces")
                continue

            if len(faces) > 2:
                report.skipped.append(
                    f"{set_code}: {print_id} has {len(faces)} faces - add by hand"
                )
                continue

            code = mapping.printed_code(print_data)

            try:
                foiling = mapping.foiling_for(print_data)
                rarity = mapping.rarity_for(print_data)
            except mapping.UnmappedValue as error:
                report.skipped.append(
                    f"{set_code}: {print_id} has an {error} - add by hand and add the value "
                    f"to mapping.py"
                )
                continue

            # A printing takes one CSV row per face, so it's fully entered once the CSV has
            # as many rows for it as CardVault has faces.
            key = (set_code, code, foiling)
            already_entered = existing_printings.get(key, 0)

            if already_entered >= len(faces):
                continue

            if already_entered:
                report.skipped.append(
                    f"{set_code}: {print_id} is half entered - the CSV has {already_entered} "
                    f"of its {len(faces)} faces, so finish it by hand"
                )
                continue

            rows_for_print = []
            unmapped = None
            unresolved_face = None

            for face in faces:
                # A face points at the core holding its card data. That reference is dangling
                # on a handful of printings, and picking a core arbitrarily would attach the
                # wrong name and stats to the row, so bail out and let a human look.
                core = cores_by_id.get(face.get("core"))
                if core is None:
                    unresolved_face = face.get("printed_name") or face.get("face_id") or "?"
                    break

                card_key = ensure_card(core, face, code)

                try:
                    fields = mapping.printing_fields(
                        print_data,
                        face=face,
                        core=core,
                        card_unique_id=existing_cards.get(card_key, ""),
                        set_printing_unique_id=set_printing_unique_id,
                        card_id=code,
                    )
                except mapping.UnmappedValue as error:
                    unmapped = error
                    break

                rows_for_print.append((fields, card_key))

            if unresolved_face is not None:
                report.skipped.append(
                    f"{set_code}: {print_id} has a face ({unresolved_face}) whose card data "
                    f"CardVault doesn't return - add by hand"
                )
                continue

            if unmapped is not None:
                report.skipped.append(
                    f"{set_code}: {print_id} has an {unmapped} - add by hand and add the "
                    f"value to mapping.py"
                )
                continue

            mapping.fill_blank_artists([fields for fields, _ in rows_for_print], print_data)

            existing_printings[key] = len(rows_for_print)
            written_this_run[key] = print_id
            printing_plans.extend(rows_for_print)

            # Both faces of a two faced printing need a card-face-association.csv row, but
            # that row references card printing Unique IDs which don't exist until
            # generate-unique-ids has run. Record it now, write it during --link.
            if len(rows_for_print) == 2:
                descriptor = mapping.printing_descriptor(code, foiling, rarity)
                front, back = rows_for_print[0][0], rows_for_print[1][0]
                associations.append(
                    {
                        "front": face_lookup_key(front),
                        "back": face_lookup_key(back),
                        "front_name": front["Card Name"],
                        "back_name": back["Card Name"],
                        "descriptor": descriptor,
                        "is_dfc": "Yes" if mapping.is_double_faced_card(print_data) else "No",
                    }
                )
                report.face_associations.append(
                    f"{print_id}: {front['Card Name']} / {back['Card Name']} "
                    f"(Is DFC: {associations[-1]['is_dfc']})"
                )
            report.new_printings.append(f"{print_id} ({published_at})")

            if any(
                mapping.art_variation_needs_checking(rarity, foiling, fields["Art Variations"])
                for fields, _ in rows_for_print
            ):
                report.check_art_variation.append(print_id)

            # Every printing has an artist, but CardVault occasionally returns an empty one.
            # A marvel's back face borrows the front's above, because it's the same card;
            # anything still blank here is a face the script has nothing to fill it from.
            for fields, _ in rows_for_print:
                if not fields["Artists"]:
                    image = fields["Image URL"].rsplit("/", 1)[-1] or "no image"
                    report.missing_artist.append(
                        f"{print_id} {fields['Card Name']} ({image})"
                    )

            if start_card_id and end_card_id and not (start_card_id <= code <= end_card_id):
                out_of_range.add(code)

    if out_of_range:
        report.check_set_range.append(
            f"{set_code}'s set-printing.csv range is {start_card_id}-{end_card_id}, but "
            f"{len(out_of_range)} added cards fall outside it "
            f"({min(out_of_range)} to {max(out_of_range)}) - update the range"
        )

    return new_cards, printing_plans, associations


def run_fetch(args):
    card_header, card_rows = read_csv(CSV_DIR / "card.csv")
    printing_header, printing_rows = read_csv(CSV_DIR / "card-printing.csv")

    existing = csv_io.index_existing(card_header, card_rows, printing_header, printing_rows)

    report = Report()

    all_card_fields = []
    all_printing_plans = []
    all_associations = []

    set_codes = load_set_group(args)
    slug = group_slug(set_codes)
    print(f"Set group: {', '.join(set_codes)}  (branch slug: {slug})\n")

    for set_code in set_codes:
        report.sets.append(set_code)
        try:
            cards, printings, associations = collect_set(set_code, existing, report, args.full)
        except cardvault.CardVaultError as error:
            report.errors.append(f"{set_code}: {error}")
            continue

        all_card_fields.extend(cards)
        all_printing_plans.extend(printings)
        all_associations.extend(associations)

    if args.dry_run:
        print("\n--dry-run, not writing any CSVs")
    else:
        if all_card_fields:
            write_csv(
                CSV_DIR / "card.csv",
                card_header,
                csv_io.add_cards(card_header, card_rows, all_card_fields),
            )

        if all_printing_plans:
            write_csv(
                CSV_DIR / "card-printing.csv",
                printing_header,
                csv_io.add_printings(
                    printing_header, printing_rows, [fields for fields, _ in all_printing_plans]
                ),
            )

        save_pending_associations(pending_path(args, set_codes), all_associations)

    report.write(report_path(args, set_codes), dry_run=args.dry_run)
    if not args.dry_run:
        checklist.save_items(checklist_path(args, set_codes), report)

    print(
        f"\n{len(all_card_fields)} new cards, {len(all_printing_plans)} new printings, "
        f"{len(all_associations)} face associations, "
        f"{len(report.skipped)} needing manual entry"
    )

    write_github_output({
        "sets": ",".join(set_codes),
        "slug": slug,
        "branch": f"spoilers/{slug}",
        "report": str(report_path(args, set_codes)),
        "checklist": str(checklist_path(args, set_codes)),
        "cards": len(all_card_fields),
        "printings": len(all_printing_plans),
        "changed": "true" if (all_card_fields or all_printing_plans) else "false",
    })

    if report.needs_attention:
        for line in report.blocked + report.errors:
            print(f"  ! {line}", file=sys.stderr)
        return 1

    return 0


def save_pending_associations(path, associations):
    """
    Stash the face associations found this run until their printings have Unique IDs.

    Anything already waiting is kept, so several fetch runs can pile up before a single
    --link resolves them all.
    """

    pending = load_pending_associations(path)

    seen = {json.dumps([entry["front"], entry["back"]], sort_keys=True) for entry in pending}
    for entry in associations:
        marker = json.dumps([entry["front"], entry["back"]], sort_keys=True)
        if marker not in seen:
            pending.append(entry)
            seen.add(marker)

    if pending:
        path.write_text(json.dumps(pending, indent=4) + "\n", encoding="utf-8")
    elif path.exists():
        path.unlink()


def load_pending_associations(path):
    if not path.exists():
        return []
    return json.loads(path.read_text(encoding="utf-8"))


def pending_files(args):
    """
    Every stash of face associations waiting to be written.

    Each set group writes its own file, so --link picks up whatever the branch happens to
    have rather than needing to be told which group it's finishing.
    """

    if args.pending_file:
        return [args.pending_file] if args.pending_file.exists() else []

    return sorted(RUN_DIR.glob(f"{PENDING_PREFIX}-*.json"))


def link_face_associations(args, printing_header, printing_rows):
    """
    Turn the stashed face associations into card-face-association.csv rows.

    Returns the number left unresolved, which is non-zero when a printing still has no
    Unique ID - that means generate-unique-ids hasn't run yet.
    """

    stashes = {path: load_pending_associations(path) for path in pending_files(args)}
    pending = [entry for entries in stashes.values() for entry in entries]
    if not pending:
        return 0

    unique_index = column_index(printing_header, "Unique ID")
    lookup_indexes = [
        column_index(printing_header, name)
        for name in ("Set ID", "Card ID", "Foiling", "Image URL")
    ]

    printings = {}
    for row in printing_rows:
        if len(row) <= max(lookup_indexes) or not row[unique_index].strip():
            continue
        printings[tuple(row[index] for index in lookup_indexes)] = row[unique_index]

    association_path = CSV_DIR / "card-face-association.csv"
    header, rows = read_csv(association_path)

    front_index = column_index(header, "Front Card Printing Unique ID")
    back_index = column_index(header, "Back Card Printing Unique ID")
    already = {
        (row[front_index], row[back_index]) for row in rows if len(row) > back_index
    }

    added = []
    still_pending = []

    for entry in pending:
        front_id = printings.get(tuple(entry["front"]))
        back_id = printings.get(tuple(entry["back"]))

        if not front_id or not back_id:
            still_pending.append(entry)
            continue

        if (front_id, back_id) in already:
            continue

        added.append(
            build_row(
                header,
                {
                    "Front Card Printing Unique ID": front_id,
                    "Front Card Name": entry["front_name"],
                    "Front Card Printing": entry["descriptor"],
                    "Back Card Printing Unique ID": back_id,
                    "Back Card Name": entry["back_name"],
                    "Back Card Printing": entry["descriptor"],
                    "Is DFC": entry["is_dfc"],
                },
            )
        )
        already.add((front_id, back_id))

    if args.dry_run:
        print(f"--dry-run, would add {len(added)} card-face-association rows")
        return len(still_pending)

    if added:
        # This file reads in Front Card Printing order, which starts with the set number.
        write_csv(association_path, header, csv_io.add_associations(header, rows, added))
        print(f"Added {len(added)} card-face-association rows")

    # Rewrite each stash with only the entries that are still waiting, and drop the file once
    # it's empty, so a finished group leaves nothing behind on the branch.
    unresolved = {json.dumps([e["front"], e["back"]], sort_keys=True) for e in still_pending}
    for path, entries in stashes.items():
        keep = [e for e in entries
                if json.dumps([e["front"], e["back"]], sort_keys=True) in unresolved]
        if keep:
            path.write_text(json.dumps(keep, indent=4) + "\n", encoding="utf-8")
        elif path.exists():
            path.unlink()

    return len(still_pending)


def run_link(args):
    """
    Fill in Card Unique ID for any printing row that's missing it, then write out any face
    associations that were waiting on those Unique IDs.

    Run this after generate-unique-ids, which is what actually mints the Unique IDs that
    both of those steps need.
    """

    card_header, card_rows = read_csv(CSV_DIR / "card.csv")
    printing_header, printing_rows = read_csv(CSV_DIR / "card-printing.csv")

    cards, _, _, _ = csv_io.index_existing(card_header, card_rows, printing_header, printing_rows)

    card_unique_index = column_index(printing_header, "Card Unique ID")
    name_index = column_index(printing_header, "Card Name")
    pitch_index = column_index(printing_header, "Card Pitch")
    code_index = column_index(printing_header, "Card ID")

    linked = 0
    unresolved = []

    for row in printing_rows:
        if len(row) <= pitch_index or row[card_unique_index].strip():
            continue

        unique_id = cards.get((row[name_index], row[pitch_index]))
        if unique_id:
            row[card_unique_index] = unique_id
            linked += 1
        else:
            unresolved.append(row[code_index])

    if args.dry_run:
        print(f"--dry-run, would link {linked} printing rows")
    else:
        write_csv(CSV_DIR / "card-printing.csv", printing_header, printing_rows)
        print(f"Linked {linked} printing rows to their cards")

    still_pending = link_face_associations(args, printing_header, printing_rows)

    if unresolved:
        print(
            f"Could not resolve {len(unresolved)} rows: {', '.join(unresolved[:20])}",
            file=sys.stderr,
        )
        return 1

    if still_pending:
        print(
            f"{still_pending} face associations are still waiting on printing Unique IDs - "
            f"run generate-unique-ids and try again",
            file=sys.stderr,
        )
        return 1

    return 0


def main():
    parser = argparse.ArgumentParser(description=__doc__.strip().splitlines()[0])
    parser.add_argument(
        "--sets",
        nargs="+",
        metavar="CODE",
        help="the group of set codes this run covers, e.g. --sets MPW AOL. One group is one "
        "branch, so group sets that share a release date. Falls back to $SPOILER_SETS.",
    )
    parser.add_argument(
        "--report-file",
        type=Path,
        help="where to write the run report (default: report-<slug>.md, e.g. report-aol-mpw.md)",
    )
    parser.add_argument(
        "--pending-file",
        type=Path,
        help=f"where face associations wait between the fetch and --link passes (default: "
        f"{PENDING_PREFIX}-<slug>.json). --link reads every stash in the folder unless "
        f"this names one.",
    )
    parser.add_argument(
        "--checklist-file",
        type=Path,
        help="where to write the data entry items for checklist.py to fold into the pull "
        "request body (default: checklist-<slug>.json)",
    )
    parser.add_argument(
        "--full",
        action="store_true",
        help="fetch details for every card in the set, not just ones with an unseen set "
        "number. Slower, but picks up extra treatments added to a card already in the CSVs.",
    )
    parser.add_argument(
        "--link",
        action="store_true",
        help="fill in Card Unique ID on printing rows that are missing it, then exit. Run "
        "this after generate-unique-ids.",
    )
    parser.add_argument("--dry-run", action="store_true", help="report only, write no CSVs")

    args = parser.parse_args()

    if args.link:
        return run_link(args)

    return run_fetch(args)


if __name__ == "__main__":
    sys.exit(main())
