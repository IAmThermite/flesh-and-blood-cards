"""
The Editor: the CSVs, and working copies of the rows belonging to the card that's open.

What can be done to each part of a card lives in its own module, mixed in here - fields.py,
lists.py, printings.py, references.py and search.py. This holds them together: opening a
card, the two ways of showing it, and saving.
"""

import contextlib
import re

from csv_io import CARD_CSV, PRINTING_CSV, REFERENCE_CSV, Record, Table, files_mentioning
from fields import EDIT_KEYS, Fields
from lists import Lists, build_vocabularies
from prompts import History
from printings import Printings, load_set_printings, set_printing_vocabulary
from references import ADD_REFERENCE, References
from screen import Cursor, bold, dim
from search import Search
from text import excerpts

# Key help for the arrow key screens.
CARD_KEYS = (
    "↑↓ move · Enter edit · t type it instead · e edit in $EDITOR · s save · q close card",
    "Enter opens a printing · a add a printing · c copy it · d delete a printing or reference",
)

# Command help for --plain.
CARD_HELP = (
    "<n> edit field · e<n> edit it in $EDITOR · s save · q close card · Enter show again\n"
    "p<n> open printing · a add printing · d<n> delete printing · "
    "r add a reference · dr<n> remove reference n"
)


class Editor(Search, Fields, Lists, Printings, References):
    """
    The CSVs, plus working copies of the rows belonging to the card that's open.

    With a Screen the card is browsed with the arrow keys. Without one - output piped
    somewhere, Windows, --plain - it's printed with numbered fields and driven by typed
    commands. Both go through the same editing and saving below.
    """

    def __init__(self, screen=None):
        self.screen = screen
        self.card_csv = Table(CARD_CSV)
        self.printing_csv = Table(PRINTING_CSV)
        self.reference_csv = Table(REFERENCE_CSV)
        self.set_printings = load_set_printings()
        self.vocabularies = build_vocabularies()
        self.vocabularies["Set Printing Unique ID"] = set_printing_vocabulary(self.set_printings)

        self.card = None
        self.kin_cards = []
        self.printings = []
        self.references = []
        self.messages = []
        self.transcript = []
        # What's been searched for this session, for the up arrow at a search prompt.
        self.searches = History()

    def say(self, text):
        """Report how something went: on the spot, or under the list if there's a screen up."""

        if self.screen:
            self.messages.append(text)
        else:
            print(f"  {text}")

    def terminal(self, rows=0, leave=False):
        """
        A stretch of ordinary terminal to print and prompt on.

        Without a screen that's simply where we already are. With one it's the bottom rows of
        it, or the terminal proper for an $EDITOR that will want the whole window.
        """

        if not self.screen:
            return contextlib.nullcontext()
        return self.screen.suspended() if leave else self.screen.console(rows)

    def card_title(self, card):
        return f"{card['Name']} ({card['Color']})" if card["Color"] else card["Name"]

    def kin(self):
        """
        card.csv rows for the open card's other pitches.

        That's the rows with its name and type line, as they stand on disk, so a rename that
        hasn't been saved doesn't sweep in some other card.
        """

        name, type_text = (self.card_csv.index[column] for column in ("Name", "Type Text"))
        key = (self.card.before("Name"), self.card.before("Type Text"))
        return [
            row
            for row in self.card_csv.rows
            if (row[name], row[type_text]) == key and row[0] and row[0] != self.card["Unique ID"]
        ]

    def cards_by_id(self):
        cards = {row[0]: row for row in self.card_csv.rows if row[0]}
        if self.card["Unique ID"]:
            cards[self.card["Unique ID"]] = self.card.values
        return cards

    def open(self, card):
        # A working copy of its own, so nothing left unsaved last time it was open comes back.
        self.card = Record(self.card_csv, card.original)
        self.kin_cards = [Record(self.card_csv, row) for row in self.kin()]
        self.load_printings()
        self.load_references()

        if self.screen:
            self.messages, self.transcript = [], []
            try:
                with self.screen:
                    self.card_screen()
            finally:
                # The screen takes everything it showed with it, so leave what was saved.
                if self.transcript:
                    print(bold(self.card_title(self.card)))
                for line in self.transcript:
                    print(f"  {line}")
        else:
            self.card_view()

        self.card = None

    # Showing the card

    def card_screen(self):
        cursor, follow = Cursor(), None
        while True:
            title = self.card_title(self.card)
            if self.pending():
                title += "   (unsaved changes)"
            rows = self.record_rows(self.card) + self.reference_rows() + self.printing_rows()
            # Keep the highlight on what it was on, should rows above it have come or gone.
            if follow is not None:
                same = [n for n, row in enumerate(rows) if row.target in (follow,)]
                cursor.at = same[0] if same else cursor.at
            key = self.screen.choose(title, rows, cursor, CARD_KEYS, self.messages)
            target = None if cursor.at is None else rows[cursor.at].target
            follow = target
            self.messages = []

            on_printing = isinstance(target, Record)
            on_reference = isinstance(target, tuple)
            on_field = isinstance(target, str)
            if key in ("enter", "right") and on_printing:
                self.printing_screen(target)
            elif key == "r" or (
                key in ("enter", "right") and (on_reference or target is ADD_REFERENCE)
            ):
                self.pick_references()
            elif key == "d" and on_reference:
                self.change_references([], [target])
            elif key in EDIT_KEYS and on_field:
                self.edit(self.card, target, EDIT_KEYS[key])
            elif key == "a" or (key == "c" and on_printing):
                printing = self.add_printing(target if key == "c" else None)
                if printing:
                    self.printing_screen(printing)
                    # Come back with the highlight on the new printing.
                    follow = printing
            elif key == "d" and on_printing:
                self.delete_printing(target)
            elif key == "s":
                self.save()
            elif key in ("q", "escape"):
                if self.close():
                    return

    def show_card(self):
        self.show_record(self.card, self.card_title(self.card))
        self.show_references()
        self.show_printings()
        print(f"\n{dim(CARD_HELP)}")

    def card_view(self):
        self.show_card()
        while True:
            try:
                command = input("> ").strip().lower()
            except (EOFError, KeyboardInterrupt):
                print()
                command = "q"

            numbered = re.fullmatch(r"([edp]?)\s*(\d+)", command)
            if numbered:
                action, number = numbered.group(1), int(numbered.group(2))
                if action in ("d", "p"):
                    if not 1 <= number <= len(self.printings):
                        print(f"  There's no printing p{number}.")
                    elif action == "d":
                        self.delete_printing(self.printings[number - 1])
                    else:
                        self.printing_view(self.printings[number - 1])
                        self.show_card()
                else:
                    self.edit_numbered(self.card, number, in_editor=action == "e")
            elif re.fullmatch(r"dr\s*\d+", command):
                number, referenced = int(command[2:]), self.referenced()
                if 1 <= number <= len(referenced):
                    self.change_references([], [referenced[number - 1][0]])
                else:
                    print(f"  There's no reference r{number}.")
            elif command == "r":
                self.add_reference_by_name()
            elif command == "a":
                choice, count = "", len(self.printings)
                if count:
                    choice = input(f"Copy which printing? (1-{count}, or Enter for a blank one): ")
                    choice = choice.strip().lower().lstrip("p")
                if choice and not (choice.isdigit() and 1 <= int(choice) <= count):
                    print(f"  There's no printing p{choice}.")
                    continue
                printing = self.add_printing(self.printings[int(choice) - 1] if choice else None)
                if printing:
                    self.printing_view(printing)
                    self.show_card()
            elif command == "s":
                self.save()
            elif command == "q":
                if self.close():
                    return
            elif command:
                print(f"  '{command}' isn't a command.")
            else:
                self.show_card()

    # Saving

    def pending(self):
        """The unsaved changes, a line each."""

        lines = []
        for column, old, new in self.card.changes():
            lines.append("{}: {}: {} -> {}".format(CARD_CSV, column, *excerpts(old, new)))
        for kin in self.kin_cards:
            for column, old, new in kin.changes():
                label = f"{CARD_CSV}: {self.card_title(kin)}"
                lines.append("{}: {}: {} -> {}".format(label, column, *excerpts(old, new)))

        return lines + self.printing_changes() + self.reference_changes()

    def save(self):
        """Write the pending changes out. Returns False if nothing could be written."""

        changes = self.pending()
        if not changes:
            self.say("Nothing to save.")
            return True

        for printing in self.printings:
            if printing.original is None and not printing["Card ID"]:
                self.say("! a new printing needs a Card ID before it can be saved")
                return False

        touched = []
        if self.card.changes() or any(kin.changes() for kin in self.kin_cards):
            touched.append(self.card_csv)
        if any(printing.marker != " " for printing in self.printings):
            touched.append(self.printing_csv)
        if any(reference.marker != " " for reference in self.references):
            touched.append(self.reference_csv)

        # Rows are held from when the script started, so writing them over a file that has
        # since been edited (or swapped out by a branch change) would undo that.
        stale = [table.path.name for table in touched if table.changed_on_disk()]
        if stale:
            self.say(f"! {' and '.join(stale)} changed on disk after this script read it.")
            self.say("  Nothing was written. Restart the script and make these edits again:")
            for line in changes:
                self.say(f"    {line}")
            return False

        renamed = any(column in ("Name", "Pitch") for column, _, _ in self.card.changes())
        added = any(printing.marker == "+" for printing in self.printings)
        renumbered = added or any(printing.deleted for printing in self.printings)

        self.card.original[:] = self.card.values
        for kin in self.kin_cards:
            kin.original[:] = kin.values
        self.apply_printings()
        self.apply_references()

        for table in touched:
            table.write()

        self.card = Record(self.card_csv, self.card.original)
        self.kin_cards = [Record(self.card_csv, row) for row in self.kin()]
        self.load_printings()
        self.load_references()
        if renumbered and not self.screen:
            self.show_printings()

        report = [f"saved {line}" for line in changes]
        if added:
            report.append(
                "New printings have a blank Unique ID - run generate-unique-ids to fill it in."
            )
        if renamed:
            mentions = files_mentioning(self.card["Unique ID"])
            if mentions:
                report.append(
                    f"This card's name and pitch are also written out in {', '.join(mentions)} - "
                    "those copies weren't touched."
                )

        for line in report:
            self.say(line)
        self.transcript += report
        return True

    def close(self):
        """Leave the card, offering to save first. Returns False to carry on editing."""

        changes = self.pending()
        if not changes:
            return True

        with self.terminal(len(changes) + 2):
            for line in changes:
                print(f"  {line}")
            try:
                answer = input("Save these changes? (Enter saves, n discards, c keeps editing): ")
            except KeyboardInterrupt:
                print()
                return False

        answer = answer.strip().lower()
        if answer in ("", "y", "yes"):
            return self.save()
        if answer in ("n", "no"):
            return True
        # Anything else - c, or a typo - goes back to the card rather than guessing.
        return False
