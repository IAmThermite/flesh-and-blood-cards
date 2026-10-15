"""Finding the card to open, by name or print code."""

from csv_io import Record
from screen import Cursor, Row, dim
from text import squash

MATCH_LIMIT = 30

MATCH_KEYS = ("↑↓ move · Enter open · q new search",)


class Search:
    """Finding cards. Part of the Editor - needs self.card_csv, self.printing_csv, self.screen."""

    def search(self, query):
        """The cards a name or a print code refers to, in name and pitch order."""

        cards = [Record(self.card_csv, row) for row in self.card_csv.rows]
        wanted = squash(query)

        matches = [card for card in cards if squash(card["Name"]) == wanted]
        if not matches and wanted:
            matches = [card for card in cards if wanted in squash(card["Name"])]
        if not matches and wanted:
            matches = self.printed_as(cards, wanted)

        if not matches:
            print(f"No card matches '{query}'.")
        return sorted(matches, key=lambda card: (card["Name"], card["Pitch"]))

    def find(self, query):
        """The card a name or a print code refers to, asking which if several do."""

        matches = self.search(query)
        if len(matches) > 1:
            return self.choose_match(query, matches)
        return matches[0] if matches else None

    def choose_match(self, query, matches, last=None):
        """
        Ask which of several matching cards to open. None to search for something else.

        `last` is the card that was open before, to start on it - the list comes back after
        each card, so a search can be worked through one card at a time.
        """

        # Read the rows afresh, so a card renamed since the search shows its new name.
        matches = [Record(self.card_csv, card.original) for card in matches]
        if self.screen:
            return self.pick_match(query, matches, last)

        shown = matches[:MATCH_LIMIT]
        print()
        for number, card in enumerate(shown, 1):
            print(f"  {number:>2}  {self.card_title(card)}  {dim(card['Type Text'])}")
        if len(matches) > len(shown):
            print(f"      ...and {len(matches) - len(shown)} more - try more of the name")

        choice = input("Which card? (number, or Enter to search again): ").strip()
        if not choice.isdigit() or not 1 <= int(choice) <= len(shown):
            return None
        return shown[int(choice) - 1]

    def printed_as(self, cards, code):
        """
        The cards with a printing under a print code.

        That's a Card ID like IAR056, or a longer code with one inside it - CardVault writes
        the rainbow foil as IAR056-RF and an Unlimited printing as U-ARC159. A double faced
        printing puts two cards under the one code.
        """

        card_id = self.printing_csv.index["Card ID"]
        owner = self.printing_csv.index["Card Unique ID"]
        printed = [
            (squash(row[card_id]), row[owner])
            for row in self.printing_csv.rows
            if row[card_id] and row[owner]
        ]

        owners = {unique_id for card_code, unique_id in printed if card_code == code}
        if not owners:
            owners = {unique_id for card_code, unique_id in printed if card_code in code}
        return [card for card in cards if card["Unique ID"] in owners]

    def pick_match(self, query, matches, last=None):
        width = max(len(self.card_title(card)) for card in matches)
        rows = [
            Row(f"{self.card_title(card):<{width}}  {card['Type Text']}", card)
            for card in matches
        ]
        cursor = Cursor()
        if last is not None:
            cursor.at = next(
                (n for n, card in enumerate(matches) if card.original is last.original), None
            )
        # Coming back from a card, say what was saved on it.
        saved = self.transcript if last is not None else []
        with self.screen:
            key = self.screen.choose(
                f"{len(matches)} cards match '{query}'", rows, cursor, MATCH_KEYS, saved
            )
        return matches[cursor.at] if key in ("enter", "right") else None
