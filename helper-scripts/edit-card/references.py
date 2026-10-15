"""The cards the open card references, in card-reference.csv."""

import bisect
import collections

from csv_io import REFERENCE_CSV, Record
from screen import Cursor, Row, bold
from text import squash

# The row under a card's references that opens the list of cards to reference.
ADD_REFERENCE = object()

PICK_REFERENCE_KEYS = ("type a name or code · ↑↓ move · Enter add or remove · Esc done",)


class References:
    """
    Adding and removing the open card's references. Part of the Editor.

    Needs self.card, self.card_csv, self.printing_csv, self.reference_csv, self.screen and the
    Editor's say, terminal, card_title, kin, cards_by_id and find.
    """

    def load_references(self):
        """card-reference.csv rows from this card, and from its other pitches which share them."""

        sources = {self.card["Unique ID"]} | {row[0] for row in self.kin()}
        owner = self.reference_csv.index["Card Unique ID"]
        self.references = [
            Record(self.reference_csv, row)
            for row in self.reference_csv.rows
            if self.card["Unique ID"] and row[owner] in sources
        ]

    def group_key(self, row):
        """
        What a reference points at: a card name, together with its type line.

        A card names another card, not one pitch of it, so a reference to Snatch is to every
        pitch of it. The type line keeps apart things that share a name - the Hyper Driver
        token isn't the Hyper Driver attack.
        """

        return row[self.card_csv.index["Name"]], row[self.card_csv.index["Type Text"]]

    def group_label(self, rows):
        """'Snatch (Red, Yellow, Blue)   Generic Action - Attack' for a group's card rows."""

        name, colour, pitch, type_text = (
            self.card_csv.index[column] for column in ("Name", "Color", "Pitch", "Type Text")
        )
        colours = []
        for row in sorted(rows, key=lambda row: row[pitch]):
            if row[colour] and row[colour] not in colours:
                colours.append(row[colour])
        shown = f" ({', '.join(colours)})" if colours else ""
        return f"{rows[0][name]}{shown}   {rows[0][type_text]}".rstrip()

    def referenced(self):
        """
        What the open card references, as (group, label, marker) - one entry per name, sorted.

        The marker is + for a reference that's new, - for one that's being removed.
        """

        cards = self.cards_by_id()
        groups = {}
        for reference in self.references:
            target = cards.get(reference["Referenced Card Unique ID"])
            if reference["Card Unique ID"] == self.card["Unique ID"] and target:
                groups.setdefault(self.group_key(target), []).append((reference, target))

        entries = []
        for key, members in sorted(groups.items()):
            live = [(reference, target) for reference, target in members if not reference.deleted]
            marker = "-" if not live else "+" if any(r.original is None for r, _ in live) else " "
            entries.append((key, self.group_label([t for _, t in live or members]), marker))
        return entries

    # Showing them

    def reference_rows(self):
        """The cards the open card references, as screen rows pickable by their group."""

        rows = [Row(""), Row("References", style=bold)]
        if not self.card["Unique ID"]:
            return rows + [Row("This card needs a Unique ID before it can reference others.")]
        rows += [
            Row(f"{marker}  {label}", target=key) for key, label, marker in self.referenced()
        ]
        return rows + [Row("   Add reference…", target=ADD_REFERENCE)]

    def show_references(self):
        referenced = self.referenced() if self.card["Unique ID"] else []
        print(f"\n{bold('References')}")
        if not referenced:
            print("None yet - r adds one.")
        for number, (_, label, marker) in enumerate(referenced, 1):
            print(f"{marker}r{number}  {label}")

    # Changing them

    def pick_references(self):
        """Tick and untick the cards this card references, from a list of every card."""

        if not self.card["Unique ID"]:
            self.say("! this card needs a Unique ID before it can reference others")
            return

        groups = {}
        for row in self.card_csv.rows:
            if row[0]:
                groups.setdefault(self.group_key(row), []).append(row)
        labels = {key: self.group_label(rows) for key, rows in groups.items()}

        # Print codes are searchable too, so IAR056 finds what's printed as IAR056.
        codes = collections.defaultdict(set)
        card_id = self.printing_csv.index["Card ID"]
        owner = self.printing_csv.index["Card Unique ID"]
        for row in self.printing_csv.rows:
            codes[row[owner]].add(squash(row[card_id]))
        search = {
            key: " ".join([squash(key[0])] + sorted(code for row in rows for code in codes[row[0]]))
            for key, rows in groups.items()
        }

        before = [key for key, _, marker in self.referenced() if marker != "-"]
        chosen, cursor, text = list(before), Cursor(), ""
        while True:
            needle = squash(text)
            ticked = [key for key in chosen if needle in search.get(key, squash(key[0]))]
            others = [key for key in sorted(groups) if key not in chosen and needle in search[key]]
            if needle:
                others.sort(key=lambda key: not squash(key[0]).startswith(needle))
            rows = [Row(f"✓ {labels.get(key, key[0])}", key) for key in ticked]
            rows += [Row(f"  {labels[key]}", key) for key in others]

            names = ", ".join(key[0] for key in chosen) or "(none)"
            title = f"References of {self.card_title(self.card)}: {names}"
            prompt = f"Showing: {text}_" if text else "Type a name or print code."
            key = self.screen.choose(
                title, rows or [Row("Nothing matches.")], cursor, PICK_REFERENCE_KEYS, [prompt],
                typing=True,
            )

            if key == "interrupt":
                return
            if key == "escape":
                break
            if key == "enter" and cursor.at is not None and rows:
                picked = rows[cursor.at].target
                chosen.remove(picked) if picked in chosen else chosen.append(picked)
                text = ""
            elif key == "backspace":
                text = text[:-1]
            elif key == "clear":
                text = ""
            elif len(key) == 1 and key.isprintable():
                text += key
            else:
                continue
            cursor.at, cursor.top = None, 0

        added = [key for key in chosen if key not in before]
        self.change_references(added, [key for key in before if key not in chosen])

    def add_reference_by_name(self):
        """--plain's way in: find the card by name or print code, the way a card is opened."""

        if not self.card["Unique ID"]:
            self.say("! this card needs a Unique ID before it can reference others")
            return
        query = self.searches.ask("Card it references (name or print code, Enter to cancel): ")
        target = self.find(query) if query else None
        if target is None:
            return
        key = self.group_key(target.values)
        if any(entry[0] == key and entry[2] != "-" for entry in self.referenced()):
            self.say(f"already references {key[0]}")
            return
        self.change_references([key], [])

    def change_references(self, added, removed):
        """
        Make the open card reference the `added` groups and stop referencing the `removed` ones.

        The pitches of a card nearly always reference the same things, so the same change is
        offered for the card's other pitches - Enter takes it.
        """

        if not added and not removed:
            return

        sources = [self.card["Unique ID"]]
        kin = self.kin()
        if kin:
            others = ", ".join(self.card_title(Record(self.card_csv, row)) for row in kin)
            with self.terminal(3):
                try:
                    answer = input(
                        f"Make the same change to {others}? (Enter does, n for just this one): "
                    )
                except (EOFError, KeyboardInterrupt):
                    print()
                    self.say("references left as they were")
                    return
            if answer.strip().lower() not in ("n", "no"):
                sources += [row[0] for row in kin]

        groups = collections.defaultdict(list)
        for row in self.cards_by_id().values():
            groups[self.group_key(row)].append(row)
        for key in added:
            self.set_reference(sources, groups[key], True)
            self.say(f"references {key[0]}")
        for key in removed:
            self.set_reference(sources, groups[key], False)
            self.say(f"no longer references {key[0]}")

    def set_reference(self, sources, targets, present):
        """Have every source card reference every target card (`present`), or none of them."""

        cards = self.cards_by_id()
        for source in sources:
            for target in targets:
                rows = [
                    reference
                    for reference in self.references
                    if reference["Card Unique ID"] == source
                    and reference["Referenced Card Unique ID"] == target[0]
                ]
                if not present:
                    for reference in rows:
                        if reference.original is None:
                            self.references.remove(reference)
                        else:
                            reference.deleted = True
                elif rows and not any(not reference.deleted for reference in rows):
                    rows[0].deleted = False
                elif not rows:
                    reference = Record(
                        self.reference_csv, values=[""] * len(self.reference_csv.header)
                    )
                    for side, card in (("Card", cards[source]), ("Referenced Card", target)):
                        reference[f"{side} Unique ID"] = card[0]
                        reference[f"{side} Name"] = card[self.card_csv.index["Name"]]
                        reference[f"{side} Pitch"] = card[self.card_csv.index["Pitch"]]
                    self.references.append(reference)

    # Saving them

    def reference_changes(self):
        """The unsaved reference changes, a line per card and name referenced."""

        cards = self.cards_by_id()
        changed = {}
        for reference in self.references:
            if reference.marker == " ":
                continue
            source = Record(self.card_csv, cards.get(reference["Card Unique ID"]))
            target = cards.get(reference["Referenced Card Unique ID"])
            what = "added" if reference.marker == "+" else "removed"
            key = (self.card_title(source), self.group_key(target), what)
            changed.setdefault(key, []).append(target)
        return [
            f"{REFERENCE_CSV}: {source} -> {self.group_label(targets).split('   ')[0]}: {what}"
            for (source, _, what), targets in changed.items()
        ]

    def position_for_reference(self, new):
        """
        Where a new card-reference.csv row belongs.

        The file runs in card name order. A card's own rows run by the name it references, then
        its pitch, then the referenced card's pitch.
        """

        rows = self.reference_csv.rows
        columns = ("Card Name", "Card Pitch", "Referenced Card Name", "Referenced Card Pitch")
        name, card_pitch, referenced, referenced_pitch = (
            self.reference_csv.index[column] for column in columns
        )

        def rank(row):
            return row[referenced], row[card_pitch], row[referenced_pitch]

        block = [position for position, row in enumerate(rows) if row[name] == new[name]]
        if not block:
            return bisect.bisect_right([row[name] for row in rows], new[name])
        ahead = [position for position in block if rank(rows[position]) <= rank(new)]
        return ahead[-1] + 1 if ahead else block[0]

    def apply_references(self):
        """Put the reference changes into card-reference.csv's rows, ready to be written."""

        rows = self.reference_csv.rows
        for reference in self.references:
            if reference.deleted:
                del rows[next(i for i, row in enumerate(rows) if row is reference.original)]
            elif reference.original is None:
                rows.insert(self.position_for_reference(reference.values), reference.values)
