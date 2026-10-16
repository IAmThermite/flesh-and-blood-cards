"""
Editing a field - of the card, or of one of its printings: on a line, in $EDITOR, or from its
column's list - and carrying an edit through to the card's other pitches.
"""

import shutil

from lists import SHORT_LIST, YES_NO
from prompts import ask_value, edit_in_editor
from screen import Row, bold, dim
from text import excerpts, split_list, wrap

# Columns that are never typed in. Unique IDs come from generate-unique-ids, and a printing's
# Card Name and Card Pitch are a readable copy of the card's own.
LOCKED = {"Unique ID", "Card Unique ID", "Card Name", "Card Pitch"}

# Columns a card's pitches nearly always share, so a change to one is offered to the others.
SHARED_COLUMNS = (
    "Traits",
    "Card Keywords",
    "Abilities and Effects",
    "Ability and Effect Keywords",
    "Granted Keywords",
    "Removed Keywords",
    "Interacts with Keywords",
)

# Text that runs over several lines.
MULTILINE = {"Functional Text", "Flavor Text"}

# How each key on a field edits it: from the column's list, typed on a line, or in $EDITOR.
EDIT_KEYS = {"enter": "pick", "right": "pick", "t": "type", "e": "editor"}


def editable(record):
    """The columns of a row that can be edited, in the order they're listed on screen."""

    return [column for column in record.table.index if column not in LOCKED]


def form(record, leave_out=()):
    """
    The columns a form asks for, in the order they're listed on screen - the CSV's own - less
    any starting with one of `leave_out`.
    """

    return [column for column in editable(record) if not column.startswith(tuple(leave_out))]


class Fields:
    """
    Showing and editing the fields of a row. Part of the Editor.

    Needs self.card, self.kin_cards, self.vocabularies and the Editor's say and terminal.
    """

    # Showing them

    def field_lines(self, record, column, room):
        """A field's value as display lines, followed by what a shorthand in it stands for."""

        lines = wrap(record[column], room)
        note = self.note(column, record[column])
        if note:
            lines[-1] = f"{lines[-1]}  ({note})"
        return lines

    def note(self, column, value):
        """What a shorthand, a set or a set printing ID stands for, to show beside it."""

        vocabulary = self.vocabularies.get(column)
        if not value or not vocabulary or not vocabulary.closed or not vocabulary.source:
            return ""
        parts = split_list(value) if vocabulary.several else [value]
        return ", ".join(
            vocabulary.options.get(part, f"not in {vocabulary.source}") for part in parts
        )

    def record_rows(self, record):
        """A row's fields as screen rows, the editable ones pickable by their column name."""

        columns = list(record.table.index)
        width = max(len(column) for column in columns)
        room = max(shutil.get_terminal_size().columns - width - 8, 30)
        changed = {column for column, _, _ in record.changes()}

        rows = []
        for column in columns:
            lines = self.field_lines(record, column, room)
            marker = "*" if column in changed else " "
            text = [f"{marker} {column:<{width}}  {lines[0]}"]
            text += [" " * (width + 4) + line for line in lines[1:]]
            if column in LOCKED:
                rows.append(Row(text, style=dim))
            else:
                rows.append(Row(text, target=column))
        return rows

    def show_record(self, record, title):
        """Print a row one field per line, numbering the fields that can be edited."""

        columns = list(record.table.index)
        fields = editable(record)
        width = max(len(column) for column in columns)
        room = max(shutil.get_terminal_size().columns - width - 7, 30)
        changed = {column for column, _, _ in record.changes()}

        print(f"\n{bold(title)}")
        for column in columns:
            number = "  " if column in LOCKED else f"{fields.index(column) + 1:>2}"
            lines = self.field_lines(record, column, room)
            marker = "*" if column in changed else " "
            first = f"{number}{marker} {column:<{width}}  {lines[0]}"
            print(dim(first) if column in LOCKED else first)
            for line in lines[1:]:
                print(" " * (width + 6) + line)

    # Editing them

    def edit_numbered(self, record, number, in_editor):
        fields = editable(record)
        if 1 <= number <= len(fields):
            self.edit(record, fields[number - 1], "editor" if in_editor else "type")
        else:
            print(f"  There's no field {number}.")

    def edit(self, record, column, how="type", quiet=False):
        """
        Change one field - by picking from its column's list, typing on a line, or in $EDITOR.

        Picking needs a screen and a column that has a list. Without both, it's typed.
        Returns False if it was abandoned with Ctrl-C, True otherwise - changed or not.
        """

        old = record[column]
        if how == "pick" and self.screen and column in self.vocabularies:
            try:
                value, _ = self.pick(record, column)
            except KeyboardInterrupt:
                return False
            if value is None:
                return True
        else:
            # Room for the hint, the prompt and however many lines the value wraps onto.
            rows = 4 + (len(column) + len(old)) // shutil.get_terminal_size().columns
            with self.terminal(rows, leave=how == "editor"):
                value = self.ask(record, column, in_editor=how == "editor")
            if value is None:
                return False

        self.store(record, column, value, quiet)
        return True

    def store(self, record, column, value, quiet=False):
        """Put a field's new value in, and carry it through to whatever follows from it."""

        old = record[column]
        if value == old:
            if not quiet:
                self.say("unchanged")
            return

        record[column] = value
        self.say("{}: {} -> {}".format(column, *excerpts(old, value)))
        self.flag_unfamiliar(record, column, old)
        if record is self.card:
            self.sync_card_columns()
            if column in SHARED_COLUMNS and self.kin_cards:
                self.share_with_kin(column, old, value)
        else:
            self.printing_edited(record, column)

    def fill_in(self, record, columns, show=None, skip=lambda column: False, prepare=None):
        """
        Ask for each of `columns` in turn, as a form - a new card's or printing's fields.

        Enter keeps what a field holds and moves on to the next. On the screen ↑ and ↓ move to
        the previous and next fields too, so a field can be gone back to and changed. Ctrl-C
        stops, leaving what's been filled in so far to carry on with field by field.

        `show(column, number, count)` draws the screen with that field highlighted, behind it.
        `skip(column)` passes over a field that's been filled in along the way, and
        `prepare(column)` can fill one in, ready to keep, the first time it comes up.
        Returns False if the form was stopped.
        """

        position, step, seen = 0, 1, set()
        while position < len(columns):
            if position < 0:
                # Back past the first field: start again from the top.
                position, step = 0, 1
            column = columns[position]
            if skip(column):
                position += step
                continue
            if prepare and column not in seen:
                prepare(column)
            seen.add(column)
            # What the last field filled in along the way stays in view while this one's asked.
            notes, self.messages = self.messages, []
            if show:
                show(column, position + 1, len(columns))

            if self.screen:
                move = self.form_field(record, column, notes)
            else:
                move = "next" if self.edit(record, column, "pick", quiet=True) else "stop"
            if move == "stop":
                self.say("stopped - the rest can be filled in field by field")
                return False
            step = -1 if move == "back" else 1
            position += step
        return True

    def form_field(self, record, column, notes=()):
        """
        Ask for one field of a form on the screen. Returns where to go: "next", "back" or "stop".

        A field with a list is picked from it, where ← and → change field. A field without is
        typed on a line, where ↑ and ↓ keep what's typed and change field. Shift-Tab and Tab
        go back and on from either.
        """

        if column in self.vocabularies:
            try:
                value, ending = self.pick(record, column, edges=True, notes=notes)
            except KeyboardInterrupt:
                return "stop"
            if value is not None:
                self.store(record, column, value, quiet=True)
            return "back" if ending == "back" else "next"

        old = record[column]
        draft, problem = old.replace("\n", "\\n"), ""
        while True:
            hint = problem or self.hint(column, in_editor=False)
            how, draft = self.screen.edit_line(f"{column}: ", draft, hint, notes)
            if how == "interrupt":
                return "stop"
            if how == "escape":
                return "next"
            entered = draft.strip().replace("\\n", "\n")
            try:
                value = old if entered == old else self.normalise(record, column, entered)
            except ValueError as error:
                problem = f"! {error}"
                continue
            self.store(record, column, value, quiet=True)
            return "back" if how in ("up", "back tab") else "next"

    def ask(self, record, column, in_editor):
        """Prompt for a column's value until it's one that passes. None if it's abandoned."""

        old = record[column]
        hint = self.hint(column, in_editor)
        if hint:
            print(dim(f"  {hint}"))

        draft = old
        while True:
            try:
                draft = edit_in_editor(draft) if in_editor else ask_value(column, old, draft)
            except (EOFError, KeyboardInterrupt):
                # Ctrl-C backs out of the edit rather than out of the script.
                print()
                return None
            except RuntimeError as problem:
                self.say(f"! {problem}")
                return None

            try:
                return old if draft == old else self.normalise(record, column, draft)
            except ValueError as problem:
                print(f"  ! {problem}")

    def hint(self, column, in_editor):
        vocabulary = self.vocabularies.get(column)
        if column in YES_NO:
            return "Yes, No or blank"
        if vocabulary and vocabulary.closed and len(vocabulary.options) <= SHORT_LIST:
            return self.spell_out(vocabulary)
        if vocabulary and vocabulary.closed:
            return f"one of the values in {vocabulary.source}"
        if vocabulary:
            return f"comma separated - {vocabulary.source} lists the usual ones"
        if column in MULTILINE and not in_editor:
            return "\\n is a line break"
        return ""

    def normalise(self, record, column, value):
        """Tidy a typed value into the form the CSVs use. ValueError if it can't be right."""

        # A stray Tab keypress would otherwise put the file's own delimiter inside a cell.
        value = value.replace("\t", " ").strip()

        if column in YES_NO:
            answers = {"": "", "y": "Yes", "yes": "Yes", "n": "No", "no": "No"}
            if value.lower() not in answers:
                raise ValueError(f"{column} is Yes, No or blank")
            return answers[value.lower()]

        vocabulary = self.vocabularies.get(column)
        if not vocabulary:
            return value

        parts = split_list(value) if vocabulary.several else [value] if value else []
        if vocabulary.closed:
            unknown = [part for part in parts if part.lower() not in vocabulary.folded]
            if unknown and len(vocabulary.options) <= SHORT_LIST:
                raise ValueError(f"{column} is {self.spell_out(vocabulary)}")
            if unknown:
                raise ValueError(f"'{unknown[0]}' isn't in {vocabulary.source}")
            parts = [vocabulary.folded[part.lower()] for part in parts]
        else:
            parts = self.respell(record, column, parts)
        return ", ".join(parts)

    def flag_unfamiliar(self, record, column, old):
        """Point out a value nothing vouches for. A typo looks just like a new keyword."""

        vocabulary = self.vocabularies.get(column)
        if not vocabulary or vocabulary.closed:
            return

        known = {value for value, _, _ in self.choices(record, column)}
        for part in split_list(record[column]):
            if part not in split_list(old) and part not in known and not vocabulary.base(part):
                self.say(
                    f"note: '{part}' is new - it isn't in {vocabulary.source} or on any other row"
                )

    # Keeping copies in step

    def share_with_kin(self, column, old, new):
        """
        Offer the change just made to the card's other pitches - Enter makes it.

        It's the change that's copied, not the value: what was added is added to each, what was
        removed is removed. A keyword with a number - Opt 2, Ward 3 - is left alone on a pitch
        that has its own number for it, since that often goes down with the pitch.
        """

        added = [part for part in split_list(new) if part not in split_list(old)]
        removed = [part for part in split_list(old) if part not in split_list(new)]
        if not added and not removed:
            return

        others = ", ".join(self.card_title(kin) for kin in self.kin_cards)
        with self.terminal(3):
            try:
                answer = input(
                    f"Make the same change to {others}? (Enter does, n for just this one): "
                )
            except (EOFError, KeyboardInterrupt):
                print()
                return
        if answer.strip().lower() in ("n", "no"):
            return

        vocabulary = self.vocabularies.get(column)

        def numbered(part):
            base = vocabulary.base(part) if vocabulary else None
            return base if base and base != part and base.endswith(" X") else None

        copied = set()
        for kin in self.kin_cards:
            parts = [part for part in split_list(kin[column]) if part not in removed]
            for part in added:
                has_own = numbered(part) and any(numbered(p) == numbered(part) for p in parts)
                if part not in parts and not has_own:
                    parts.append(part)
                    if numbered(part):
                        copied.add(part)
            if ", ".join(parts) != kin[column]:
                was, kin[column] = kin[column], ", ".join(parts)
                change = excerpts(was, kin[column])
                self.say("{}: {}: {} -> {}".format(self.card_title(kin), column, *change))
        for part in sorted(copied):
            self.say(f"note: copied {part} as it is - check the number on each pitch")

    def sync_card_columns(self):
        """
        Keep each printing's readable Card Name / Card Pitch in step with a renamed card.

        Only a rename moves them. Plenty of existing printings carry a slightly different
        spelling of their card's name, and opening a card shouldn't quietly rewrite those.
        """

        for copy, source in (("Card Name", "Name"), ("Card Pitch", "Pitch")):
            # A new card has nothing on disk to have been renamed from, so its copies follow it.
            new = self.card.original is None
            renamed = new or self.card[source] != self.card.before(source)
            for printing in self.printings:
                if renamed or printing.original is None:
                    printing[copy] = self.card[source]
                else:
                    printing[copy] = printing.before(copy)
