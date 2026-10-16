"""
Columns whose values are listed in another CSV - keywords, types, foilings and so on - and
the on-screen list that a value is picked from.
"""

import collections
import re

from csv_io import read_rows
from screen import Cursor, Row
from text import split_list, squash

YES_NO = {
    "Card Played Horizontally",
    "Blitz Legal",
    "CC Legal",
    "Silver Age Legal",
    "Commoner Legal",
    "LL Legal",
    "Expansion Slot",
}

# A closed list short enough to spell out in a hint or an error.
SHORT_LIST = 12

PICK_ONE_KEYS = ("type to narrow the list · ↑↓ move · Enter choose · Esc back",)
PICK_SEVERAL_KEYS = ("type to narrow the list · ↑↓ move · Enter add or remove · Esc done",)

# Keys that leave a list for another field when it's part of a form.
FORM_EXITS = ("past top", "past bottom", "left", "right", "tab", "back tab")

# In a form, ← and → (or going off the top or bottom of the list) change field.
PICK_ONE_FORM_KEYS = (
    "type to narrow · ↑↓ move · ←→ previous or next field · Enter choose",
)
PICK_SEVERAL_FORM_KEYS = (
    "type to narrow · ↑↓ move · ←→ previous or next field · Enter add or remove",
)


class Vocabulary:
    """
    The values a column is expected to hold, as listed in the CSV that defines them.

    A closed one is the whole story: a foiling is one of four letters, and anything else is a
    typo. An open one can only suggest. keyword.csv lists Ward X and Fusion where a card says
    Ward 10 and Ice Fusion, and each new set brings types, keywords and artists before anyone
    has added them to their CSV.
    """

    def __init__(
        self, source, values="Name", meaning=None, closed=False, several=False, options=None
    ):
        self.source = source
        self.closed = closed
        self.several = several
        # value -> what it stands for, which is nothing where the value is already a name.
        self.options = {} if options is None else options
        if options is None:
            for row in read_rows(source):
                if row[values]:
                    # set.csv has two sets under 1HP, so one value can stand for several things.
                    known = [self.options.get(row[values]), row[meaning] if meaning else ""]
                    self.options[row[values]] = " / ".join(text for text in known if text)

        self.folded = {value.lower(): value for value in self.options}
        self.stems = {
            value[:-2].lower(): value[:-2] for value in self.options if value.endswith(" X")
        }

    def valued(self, text):
        """'ward 10' as the list would write it, 'Ward 10', if it's a value for a 'Ward X'."""

        stem, _, amount = " ".join(text.split()).rpartition(" ")
        if stem.lower() in self.stems and re.fullmatch(r"\d+|[xX]+", amount):
            return f"{self.stems[stem.lower()]} {amount.upper()}"
        return None

    def base(self, value):
        """The entry a value is an instance of - 'Ward 10' is a 'Ward X' - or None."""

        if value in self.options:
            return value
        return f"{value.rpartition(' ')[0]} X" if self.valued(value) == value else None


def build_vocabularies():
    """The list behind each card and printing column that has one, by column name."""

    keywords = Vocabulary("keyword.csv", several=True)
    vocabularies = {
        # No CSV lists the colours, but there are only these - pitch order, then the one Purple.
        "Color": Vocabulary(
            None, closed=True, options={"Red": "", "Yellow": "", "Blue": "", "Purple": ""}
        ),
        "Types": Vocabulary("type.csv", several=True),
        "Card Keywords": keywords,
        "Abilities and Effects": Vocabulary("ability.csv", several=True),
        "Ability and Effect Keywords": keywords,
        "Granted Keywords": keywords,
        "Removed Keywords": keywords,
        "Interacts with Keywords": keywords,
        "Set ID": Vocabulary("set.csv", "Identifier", "Name", closed=True),
        "Edition": Vocabulary("edition.csv", "Shorthand", "Name", closed=True),
        "Rarity": Vocabulary("rarity.csv", "Shorthand", "Text", closed=True),
        "Foiling": Vocabulary("foiling.csv", "Shorthand", "Name", closed=True),
        "Art Variations": Vocabulary(
            "art-variation.csv", "Shorthand", "Name", closed=True, several=True
        ),
        "Artists": Vocabulary("artist.csv", several=True),
    }
    for column in YES_NO:
        vocabularies[column] = Vocabulary(None, closed=True, options={"Yes": "", "No": ""})
    return vocabularies


class Lists:
    """
    Picking a field's value from its column's list. Part of the Editor.

    Needs self.vocabularies, self.set_printings and self.screen.
    """

    def spell_out(self, vocabulary):
        choices = ", ".join(
            f"{value} ({meaning})" if meaning else value
            for value, meaning in vocabulary.options.items()
        )
        return f"{choices} - comma separated" if vocabulary.several else choices

    def respell(self, record, column, parts):
        """
        Typed values in the spelling they're known by: 'go again' is 'Go again'.

        Where a value has been written more than one way, the way most rows write it wins, since
        a lookup CSV can be the odd one out. Anything not known under any spelling is left
        exactly as typed.
        """

        vocabulary = self.vocabularies[column]
        choices = self.choices(record, column)
        exact = {value for value, _, _ in choices}
        spellings = {}
        for value, _, uses in choices:
            best = spellings.get(value.lower())
            if best is None or uses > best[1]:
                spellings[value.lower()] = (value, uses)

        return [
            part
            if part in exact
            else vocabulary.valued(part) or spellings.get(part.lower(), (part,))[0]
            for part in parts
        ]

    def choices(self, record, column):
        """
        What a column's list offers, as (value, note, rows using it) triples.

        The values in its CSV come first, in the CSV's order. Where the list is open, whatever
        else the column's rows already hold follows, most used first - so an established
        "Ice Fusion", or a type nobody has added to type.csv yet, can be picked as well.
        """

        vocabulary = self.vocabularies[column]
        if vocabulary.closed:
            choices = [(value, meaning, 0) for value, meaning in vocabulary.options.items()]
            if column == "Set Printing Unique ID":
                # Lead with the set printings of this printing's own set.
                mine = {
                    set_printing["Unique ID"]
                    for set_printing in self.set_printings
                    if set_printing["Set ID"] == record["Set ID"]
                }
                choices.sort(key=lambda choice: choice[0] not in mine)
            return choices

        uses = collections.Counter()
        position = record.table.index[column]
        for row in record.table.rows:
            for part in split_list(row[position]):
                # Every "Ward 3" and "Ward 10" counts towards "Ward X".
                uses[vocabulary.base(part) or part] += 1

        noun = "card" if record.table is self.card_csv else "printing"

        def used(value):
            return f"on {uses[value]} {noun}{'' if uses[value] == 1 else 's'}"

        others = sorted(
            (value for value in uses if value not in vocabulary.options),
            key=lambda value: (-uses[value], value),
        )
        return [
            (value, used(value) if uses[value] else "", uses[value])
            for value in vocabulary.options
        ] + [(value, f"{used(value)}, not in {vocabulary.source}", uses[value]) for value in others]

    def choice_rows(self, vocabulary, choices, chosen, text):
        """The list as screen rows, narrowed to what's been typed."""

        needle = squash(text)
        matching = [
            choice
            for choice in choices
            if needle in squash(choice[0] + (choice[1] if vocabulary.closed else ""))
        ]
        if needle:
            # Best guess first: what starts with the typed text, then what's used the most.
            def rank(choice):
                starts = [squash(text).startswith(needle) for text in choice[:2] if text]
                return not any(starts), -choice[2]

            matching.sort(key=rank)
        if vocabulary.several:
            # What the field holds now leads, in its own order, whatever list it came from.
            notes = {value: note for value, note, _ in choices}
            held = [(value, notes.get(value, ""), 0) for value in chosen if needle in squash(value)]
            matching = held + [choice for choice in matching if choice[0] not in chosen]

        width = max((len(value) for value, _, _ in matching), default=0)
        rows = [
            Row(f"{'✓' if value in chosen else ' '} {value:<{width}}  {note}".rstrip(), value)
            for value, note, _ in matching
        ]

        # Last, so that Enter straight after typing takes the best match and not the typing.
        typed = vocabulary.valued(text) or " ".join(text.split())
        if typed and not vocabulary.closed:
            if typed.lower() not in {value.lower() for value, _, _ in matching}:
                rows.append(Row(f'+ add "{typed}"', typed))
        if not vocabulary.several and not needle:
            rows.append(Row("  (blank)", ""))
        return rows or [Row("Nothing matches.")]

    def pick(self, record, column, edges=False, notes=()):
        """
        Choose a column's value from its list.

        Returns the value - None if it was left as it was - and how the list was left: "chosen",
        "done", or with `edges` (in a form), "back" for ←, Shift-Tab or ↑ off its top - →,
        Tab and ↓ off its bottom being "done". `notes` are shown under the list. Ctrl-C
        raises KeyboardInterrupt.
        """

        vocabulary = self.vocabularies[column]
        choices = self.choices(record, column)
        chosen = split_list(record[column]) if vocabulary.several else [record[column]]
        if edges:
            keys = PICK_SEVERAL_FORM_KEYS if vocabulary.several else PICK_ONE_FORM_KEYS
        else:
            keys = PICK_SEVERAL_KEYS if vocabulary.several else PICK_ONE_KEYS
        cursor, text = Cursor(), ""

        # Start a single choice on the value it has now.
        rows = self.choice_rows(vocabulary, choices, chosen, text)
        if not vocabulary.several:
            cursor.at = next((n for n, row in enumerate(rows) if row.target == chosen[0]), None)

        while True:
            title = f"{column}: {', '.join(chosen) or '(blank)'}"
            prompt = f"Showing: {text}_" if text else "Type to narrow the list."
            key = self.screen.choose(
                title, rows, cursor, keys, [*notes, prompt], typing=True, edges=edges
            )

            if key == "interrupt":
                raise KeyboardInterrupt
            leaving = ("escape",) + (FORM_EXITS if edges else ())
            if key in leaving:
                value = ", ".join(chosen) if vocabulary.several else None
                return value, "back" if key in ("past top", "left", "back tab") else "done"
            if key == "enter" and cursor.at is not None:
                if not vocabulary.several:
                    return rows[cursor.at].target, "chosen"
                self.toggle(vocabulary, chosen, rows[cursor.at].target)
                text = ""
            elif key == "backspace":
                text = text[:-1]
            elif key == "clear":
                text = ""
            elif len(key) == 1 and key.isprintable():
                text += key
            else:
                continue

            rows = self.choice_rows(vocabulary, choices, chosen, text)
            cursor.at, cursor.top = None, 0

    def toggle(self, vocabulary, chosen, value):
        """Add a value to a field that holds several, or take it out if it's already there."""

        if value in chosen:
            chosen.remove(value)
            return

        # "Ward X" is the keyword. What goes on the card is "Ward 3" - so the number is typed
        # straight after the name, on the screen's own line, where Esc goes back to the list.
        if value.endswith(" X") and value in vocabulary.options:
            stem, amount, problem = value[:-2], "", ""
            while True:
                hint = problem or "its number, or X · Enter adds it · Esc back to the list"
                how, amount = self.screen.edit_line(f"{stem} ", amount, hint)
                if how != "enter" or not amount.strip():
                    return
                if vocabulary.valued(f"{stem} {amount}"):
                    value = vocabulary.valued(f"{stem} {amount}")
                    break
                problem = f"! {stem} takes a number, or X"

        if value not in chosen:
            chosen.append(value)
