"""The card's rows in card-printing.csv: showing, editing, adding and deleting them."""

import bisect
import re

from csv_io import PRINTING_CSV, Record, files_mentioning, read_rows
from fields import EDIT_KEYS
from lists import Vocabulary
from screen import Cursor, Row, bold, dim
from text import excerpts

# Where several printings share a set number the CSV lists the plain one first, then its foils.
FOILING_ORDER = {"S": 0, "R": 1, "C": 2, "G": 3}

# The columns that tell one printing from another, for the list under a card.
PRINTING_SUMMARY = (
    "Card ID",
    "Edition",
    "Rarity",
    "Foiling",
    "Art Variations",
    "Artists",
    "TCGPlayer ID",
    "Image URL",
)

NO_UNIQUE_ID = (
    "This card has no Unique ID yet, so its printings can't be matched to it.",
    "Run generate-unique-ids, then open it again.",
)

PRINTING_KEYS = (
    "↑↓ move · Enter edit · t type it instead · e edit in $EDITOR · q back to card",
)
PRINTING_HELP = "<n> edit field · e<n> edit it in $EDITOR · b back to card · Enter show again"


def load_set_printings():
    """Every set-printing.csv row, with its set's identifier and name folded in."""

    sets = {row["Unique ID"]: row for row in read_rows("set.csv")}
    set_printings = read_rows("set-printing.csv")
    for set_printing in set_printings:
        owner = sets.get(set_printing["Set Unique ID"], {})
        set_printing["Set ID"] = owner.get("Identifier", "")
        set_printing["Set Name"] = owner.get("Name", "")
    return set_printings


def describe_set_printing(set_printing):
    return "{Set Name}, {Edition}, {Start Card Id}-{End Card Id}".format(**set_printing)


def set_printing_vocabulary(set_printings):
    """The set printings as a closed list, each standing for its set, edition and range."""

    return Vocabulary(
        "set-printing.csv",
        closed=True,
        options={
            set_printing["Unique ID"]: describe_set_printing(set_printing)
            for set_printing in set_printings
        },
    )


def printing_label(printing):
    parts = (
        printing["Card ID"] or "(no Card ID)",
        printing["Edition"],
        printing["Foiling"],
        printing["Art Variations"],
    )
    return " ".join(part for part in parts if part)


class Printings:
    """
    The open card's printings. Part of the Editor.

    Needs self.card, self.printing_csv, self.set_printings, self.vocabularies and the Editor's
    say, card_title and field editing.
    """

    def load_printings(self):
        unique_id = self.card["Unique ID"]
        owner = self.printing_csv.index["Card Unique ID"]
        # A card that hasn't been given its Unique ID yet has nothing to match printings on.
        self.printings = [
            Record(self.printing_csv, row)
            for row in self.printing_csv.rows
            if unique_id and row[owner] == unique_id
        ]

    def printing_table(self, numbered):
        """The card's printings as aligned lines of text, heading first."""

        table = [("",) + PRINTING_SUMMARY[:-1] + ("Image",)]
        for number, printing in enumerate(self.printings, 1):
            cells = [printing[column] for column in PRINTING_SUMMARY]
            cells[-1] = cells[-1].rsplit("/", 1)[-1]
            table.append((printing.marker + (f"p{number}" if numbered else ""), *cells))

        widths = [max(len(row[position]) for row in table) for position in range(len(table[0]))]
        return [
            "  ".join(cell.ljust(width) for cell, width in zip(row, widths)).rstrip()
            for row in table
        ]

    # On the arrow key screen

    def printing_rows(self):
        """The printings under a card as screen rows, each pickable as its Record."""

        rows = [Row(""), Row("Printings", style=bold)]
        if not self.card["Unique ID"]:
            rows.append(Row(list(NO_UNIQUE_ID)))
        elif not self.printings:
            rows.append(Row("None yet."))
        else:
            heading, *lines = self.printing_table(numbered=False)
            rows.append(Row(heading, style=dim))
            rows += [Row(line, target=printing) for line, printing in zip(lines, self.printings)]
        return rows

    def printing_screen(self, printing):
        cursor = Cursor()
        while True:
            title = f"{self.card_title(self.card)} > printing {printing_label(printing)}"
            rows = self.record_rows(printing)
            key = self.screen.choose(title, rows, cursor, PRINTING_KEYS, self.messages)
            self.messages = []

            if key in EDIT_KEYS and cursor.at is not None:
                self.edit(printing, rows[cursor.at].target, EDIT_KEYS[key])
            elif key in ("q", "b", "escape", "left"):
                return

    # Typing commands instead

    def show_printings(self):
        print()
        if not self.card["Unique ID"]:
            print("\n".join(NO_UNIQUE_ID))
        elif not self.printings:
            print("No printings yet.")
        else:
            heading, *lines = self.printing_table(numbered=True)
            print(bold("Printings"))
            print(dim(heading))
            print("\n".join(lines))

    def show_printing(self, printing):
        number = self.printings.index(printing) + 1
        self.show_record(printing, f"Printing p{number} of {self.card_title(self.card)}")
        print(f"\n{dim(PRINTING_HELP)}")

    def printing_view(self, printing):
        self.show_printing(printing)
        while True:
            try:
                command = input(f"p{self.printings.index(printing) + 1}> ").strip().lower()
            except (EOFError, KeyboardInterrupt):
                print()
                return

            numbered = re.fullmatch(r"(e?)\s*(\d+)", command)
            if numbered:
                self.edit_numbered(
                    printing, int(numbered.group(2)), in_editor=bool(numbered.group(1))
                )
            elif command in ("b", "q"):
                return
            elif command:
                print(f"  '{command}' isn't a command.")
            else:
                self.show_printing(printing)

    # Changing them

    def printing_edited(self, printing, column):
        """Carry an edit through to the columns that follow from it."""

        # validate-references expects the Set ID to be the first three characters of the Card ID.
        card_id = printing["Card ID"]
        if column == "Card ID" and card_id and printing["Set ID"] != card_id[:3]:
            printing["Set ID"] = card_id[:3]
            self.say(f"Set ID -> {card_id[:3]}")

        if column in ("Card ID", "Set ID", "Edition"):
            self.link_set_printing(printing)

        # A hash describes the old image, and calculate-phashes skips rows that already have one.
        if column == "Image URL":
            stale = [
                name
                for name in self.printing_csv.index
                if name.startswith("Image Hash") and printing[name]
            ]
            for name in stale:
                printing[name] = ""
            if stale:
                self.say(f"cleared {', '.join(stale)} - run calculate-phashes for the new image")

    def link_set_printing(self, printing):
        """Point a printing at the set printing that its Set ID and Edition describe."""

        matches = [
            set_printing
            for set_printing in self.set_printings
            if set_printing["Set ID"] == printing["Set ID"]
            and set_printing["Edition"] == printing["Edition"]
        ]
        # Two sets can share an identifier (History Pack 1 and its Black Label), so let the
        # card ID ranges decide between them.
        if len(matches) > 1:
            card_id = printing["Card ID"]
            in_range = [
                set_printing
                for set_printing in matches
                if set_printing["Start Card Id"] <= card_id <= set_printing["End Card Id"]
            ]
            matches = in_range or matches

        if len(matches) == 1:
            if printing["Set Printing Unique ID"] != matches[0]["Unique ID"]:
                printing["Set Printing Unique ID"] = matches[0]["Unique ID"]
                self.say(f"Set Printing Unique ID -> {describe_set_printing(matches[0])}")
        elif matches:
            self.say("! several set printings fit - set Set Printing Unique ID to one of:")
            for set_printing in matches:
                description = describe_set_printing(set_printing)
                self.say(f"    {set_printing['Unique ID']}  {description}")
        else:
            self.say(
                f"! set-printing.csv has no '{printing['Edition']}' edition of set "
                f"'{printing['Set ID']}' - Set Printing Unique ID left as it was"
            )

    def add_printing(self, source=None):
        """Start a new printing, blank or as a copy of another. None if the card can't take one."""

        if not self.card["Unique ID"]:
            self.say("! this card needs a Unique ID before it can take printings")
            return None

        values = list(source.values) if source else [""] * len(self.printing_csv.header)
        printing = Record(self.printing_csv, values=values)
        printing["Unique ID"] = ""
        printing["Card Unique ID"] = self.card["Unique ID"]
        self.printings.append(printing)
        self.sync_card_columns()
        return printing

    def delete_printing(self, printing):
        number = self.printings.index(printing) + 1
        label = printing_label(printing)

        # A printing that was never saved has nothing to delete, so it just goes.
        if printing.original is None:
            self.printings.remove(printing)
            if not self.screen:
                self.show_printings()
            self.say(f"dropped the unsaved printing {label}")
            return

        printing.deleted = not printing.deleted
        if not printing.deleted:
            self.say(f"keeping {label}")
            return

        again = "d again" if self.screen else f"d{number} again"
        self.say(f"{label} will be deleted on save - {again} to keep it")
        if printing["Unique ID"]:
            mentions = files_mentioning(printing["Unique ID"])
            if mentions:
                self.say(f"! it's referenced in {', '.join(mentions)} - remove that by hand too")

    # Saving them

    def printing_changes(self):
        """The unsaved printing changes, a line each."""

        lines = []
        for printing in self.printings:
            label = f"{PRINTING_CSV}: {printing_label(printing)}"
            if printing.deleted:
                lines.append(f"{label}: deleted")
            elif printing.original is None:
                lines.append(f"{label}: added")
            else:
                for column, old, new in printing.changes():
                    lines.append("{}: {}: {} -> {}".format(label, column, *excerpts(old, new)))
        return lines

    def position_for_printing(self, new):
        """
        Where a new printing row belongs in card-printing.csv.

        The file runs in Card ID order. Rows sharing a Card ID are grouped by edition, plain
        printing ahead of its foils, so a new row slots in beside its own kind where it can.
        """

        rows = self.printing_csv.rows
        card_id, edition, foiling = (
            self.printing_csv.index[column] for column in ("Card ID", "Edition", "Foiling")
        )

        def rank(row):
            return FOILING_ORDER.get(row[foiling], len(FOILING_ORDER))

        siblings = [position for position, row in enumerate(rows) if row[card_id] == new[card_id]]
        if not siblings:
            return bisect.bisect_right([row[card_id] for row in rows], new[card_id])

        same_edition = [
            position for position in siblings if rows[position][edition] == new[edition]
        ]
        if not same_edition:
            return siblings[-1] + 1

        ahead = [position for position in same_edition if rank(rows[position]) <= rank(new)]
        return ahead[-1] + 1 if ahead else same_edition[0]

    def apply_printings(self):
        """Put the printing changes into card-printing.csv's rows, ready to be written."""

        rows = self.printing_csv.rows
        for printing in self.printings:
            if printing.deleted:
                del rows[next(i for i, row in enumerate(rows) if row is printing.original)]
            elif printing.original is None:
                rows.insert(self.position_for_printing(printing.values), printing.values)
            else:
                printing.original[:] = printing.values
