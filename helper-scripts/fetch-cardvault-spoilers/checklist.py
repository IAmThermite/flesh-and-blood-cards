#!/usr/bin/env python3
"""
Turn a run's findings into a data entry checklist for the pull request body.

A spoiler set arrives over weeks, so the branch and its PR stay open while run after run
adds more cards. This keeps one checklist in the PR body and grows it: new items get
appended, and anything already there keeps whatever state it had, so a ticked box survives
the next run.

The fetch pass writes the items file; turning that into a PR body is a separate step:

    python main.py --sets MPW AOL
    gh pr view 123 --json body -q .body > body.md
    python checklist.py --items checklist-aol-mpw.json --body body.md --output body.md
    gh pr edit 123 --body-file body.md

Reading and writing plain files rather than calling `gh` keeps this testable and means the
workflow decides how the PR is found.
"""

import argparse
import json
import re
import sys
from pathlib import Path

# The checklist owns the text between these markers and nothing else, so whatever a human
# writes above or below it in the PR body survives.
START = "<!-- cardvault-checklist:start -->"
END = "<!-- cardvault-checklist:end -->"

# GitHub rejects a pull request body over 65536 characters. Leave room for the prose around
# the block rather than spending the whole allowance on checkboxes.
CHECKLIST_LIMIT = 55000

# section id -> (heading, what the section is for)
SECTIONS = [
    (
        "cards",
        "Cards needing the hand-entered columns",
        "Card keywords, abilities and effects, ability and effect keywords, granted "
        "keywords, removed keywords, interacts with keywords, and arcane.",
    ),
    (
        "art_variation",
        "Printings to check the art variation on",
        "CardVault only distinguishes regular, extended art and full art, so anything that "
        "should be AA, AB, AT or HS will have come through wrong. Blanks on marvels and "
        "cold foils are listed too, because those treatments usually carry a variation and "
        "a blank one is more likely to be missing than right. Manually check the card.",
    ),
    (
        "artist",
        "Printings missing an artist",
        "CardVault returned no artist for these faces, and every printing has one. Fill the "
        "Artists column in on card-printing.csv - a blank one leaves the printing with "
        "no credit, and the artist missing from artist.csv.",
    ),
    (
        "pitch",
        "Cards to check the pitch on",
        "The name is already in card.csv at a different pitch, so this is either a new "
        "variant or a duplicate.",
    ),
    (
        "manual",
        "Printings needing manual entry",
        "The script wouldn't guess at these.",
    ),
    (
        "range",
        "Set ranges to update",
        "Cards fall outside the range recorded in set-printing.csv.",
    ),
    (
        "blocked",
        "Sets that need adding first",
        "Nothing was imported for these.",
    ),
]

HEADINGS = {heading: key for key, heading, _ in SECTIONS}

# Sections holding one standing statement per set rather than one job per card. Their
# wording moves as more of the set arrives - "38 of the set's cards are outside that"
# becomes "44" - so matching on the text would leave a trail of superseded lines, each of
# them now wrong. They're matched on the set code they start with instead, and the newest
# wording replaces the old line in place.
RESTATED = {"range", "blocked"}

ITEM = re.compile(r"^- \[([ xX])\]\s+(.*?)\s*$")
HEADING = re.compile(r"^### (.+?)\s*$")

PREAMBLE = (
    "Added to as cards are pulled from CardVault. All cards need manual review and data "
    "entry for the fields listed below as CardVault does not supply the information we need."
)


def item_key(section, text):
    """What makes two items the same item, for deciding whether one is already listed."""

    if section in RESTATED:
        return text.split(":", 1)[0].strip()
    return text


def items_from_report(report):
    """
    The actionable part of a run, as checklist items.

    Only things a person has to do end up here. What the run added is already in the diff,
    and errors are a property of the run rather than of the data, so both stay in the report
    file instead.
    """

    items = []

    for entry in report.new_cards:
        items.append({"section": "cards", "text": entry})
    for entry in report.check_art_variation:
        items.append({"section": "art_variation", "text": entry})
    for entry in report.missing_artist:
        items.append({"section": "artist", "text": entry})
    for entry in report.check_pitch:
        items.append({"section": "pitch", "text": entry})
    for entry in report.skipped:
        items.append({"section": "manual", "text": entry})
    for entry in report.check_set_range:
        items.append({"section": "range", "text": entry})
    for entry in report.blocked:
        items.append({"section": "blocked", "text": entry})

    return items


def save_items(path, report):
    """Write this run's items for the PR step to pick up."""

    items = items_from_report(report)
    path.write_text(json.dumps(items, indent=4) + "\n", encoding="utf-8")
    print(f"Checklist items written to {path} ({len(items)} items)")
    return items


def parse(body):
    """
    Pull the existing checklist out of a PR body.

    Returns (before, entries, after). Entries are (section, text, done) in the order they
    appear, so a re-render keeps them where the reader last saw them.
    """

    body = body or ""
    if START not in body or END not in body:
        return body.rstrip(), [], ""

    before, rest = body.split(START, 1)
    block, after = rest.split(END, 1)

    entries = []
    section = None
    for line in block.splitlines():
        heading = HEADING.match(line)
        if heading:
            section = HEADINGS.get(heading.group(1).strip())
            continue

        item = ITEM.match(line)
        if item and section:
            entries.append((section, item.group(2), item.group(1).lower() == "x"))

    return before.rstrip(), entries, after.lstrip()


def merge(entries, new_items):
    """
    Add items the checklist doesn't have yet, leaving the ones it does alone.

    Matching is on the item's key, which for most sections is the text itself, so re-running
    over the same cards adds nothing. Items are never removed - a box someone already ticked
    is a record of work done, and dropping it because a later run didn't mention the card
    would throw that away.

    A RESTATED item is the exception, because it isn't a record of work: it's what the CSVs
    look like right now. The newest wording replaces the old one where it stands, unticked,
    since what it says has changed. Older copies of the same statement are dropped, which
    also tidies up the trail left by runs before this was keyed.
    """

    latest = {
        (item["section"], item_key(item["section"], item["text"])): item["text"]
        for item in new_items
    }

    merged = []
    seen = set()

    for section, text, ticked in entries:
        key = (section, item_key(section, text))
        if section in RESTATED and key in seen:
            continue
        seen.add(key)
        current = latest.get(key, text)
        merged.append((section, current, ticked and current == text))

    added = 0
    for item in new_items:
        key = (item["section"], item_key(item["section"], item["text"]))
        if key in seen:
            continue
        seen.add(key)
        merged.append((item["section"], item["text"], False))
        added += 1

    return merged, added


def render(entries):
    """Lay the entries out under their headings, dropping any section with nothing in it."""

    lines = [
        START,
        "## Data entry checklist",
        "",
    ]

    omitted = 0
    for key, heading, blurb in SECTIONS:
        section_entries = [e for e in entries if e[0] == key]
        if not section_entries:
            continue

        lines.append(f"### {heading}")
        lines.append("")
        lines.append(f"_{blurb}_")
        lines.append("")
        for _, text, ticked in section_entries:
            lines.append(f"- [{'x' if ticked else ' '}] {text}")
        lines.append("")

    # A full set is a few hundred cards; trim rather than let GitHub reject the body, and say
    # so rather than letting it look like the list is complete.
    while len("\n".join(lines)) > CHECKLIST_LIMIT and lines:
        for index in range(len(lines) - 1, -1, -1):
            if lines[index].startswith("- ["):
                del lines[index]
                omitted += 1
                break
        else:
            break

    if omitted:
        lines.append("")
        lines.append(
            f"_{omitted} more items didn't fit in the pull request body - see the run "
            f"report for the full list._"
        )

    lines.append(END)
    return "\n".join(lines)


def apply_to_body(body, new_items):
    """Return the PR body with the checklist merged in, and how many items were added."""

    before, entries, after = parse(body)
    merged, added = merge(entries, new_items)

    if not merged:
        return body, 0

    parts = [part for part in (before, render(merged), after) if part]
    return "\n\n".join(parts) + "\n", added


def main():
    parser = argparse.ArgumentParser(description=__doc__.strip().splitlines()[0])
    parser.add_argument(
        "--items",
        type=Path,
        required=True,
        help="the items file a fetch run wrote, e.g. checklist-aol-mpw.json",
    )
    parser.add_argument(
        "--body",
        type=Path,
        help="the pull request's current body. Omit for a new pull request.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        help="where to write the merged body (default: stdout)",
    )

    args = parser.parse_args()

    new_items = json.loads(args.items.read_text(encoding="utf-8"))
    body = args.body.read_text(encoding="utf-8") if args.body and args.body.exists() else ""

    merged, added = apply_to_body(body, new_items)

    if args.output:
        args.output.write_text(merged, encoding="utf-8")
        print(f"{added} new items added to {args.output}", file=sys.stderr)
    else:
        sys.stdout.write(merged)

    return 0


if __name__ == "__main__":
    sys.exit(main())
