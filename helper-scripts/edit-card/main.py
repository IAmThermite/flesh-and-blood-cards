#!/usr/bin/env python3
"""
Look a card up by name and edit its card.csv row, its card-printing.csv rows and the
cards it references in card-reference.csv.

    python main.py                        # asks for a card name or print code
    python main.py command and conquer    # opens the card straight away
    python main.py IAR056                 # so does a print code

In a terminal the card opens as a list to move through with the arrow keys. Anywhere that
can't be done (or with --plain) the fields are numbered and edited by typing commands.

Edits are held in memory until you save. Saving rewrites only the rows that changed - every
other row goes back to disk exactly as it was read, so the diff is just your edits.
"""

import argparse

from editor import Editor
from screen import Screen, can_browse


def main():
    parser = argparse.ArgumentParser(
        description="Edit a card's card.csv row, printings and references."
    )
    parser.add_argument(
        "name",
        nargs="*",
        help="the card to open - its name, part of its name, or a print code like IAR056",
    )
    parser.add_argument(
        "--plain",
        action="store_true",
        help="number the fields and type commands, rather than moving about with the arrow keys",
    )
    arguments = parser.parse_args()
    query = " ".join(arguments.name)

    editor = Editor(Screen() if can_browse() and not arguments.plain else None)
    editor.searches.remember(query)
    try:
        while True:
            if not query:
                print()
                query = editor.searches.ask("Card name or print code (Enter to quit): ")
            if not query:
                break
            matches = editor.search(query)
            if len(matches) == 1:
                editor.open(matches[0])

            # With several, come back to the list after each card, ready to open the next.
            card = None
            while len(matches) > 1:
                card = editor.choose_match(query, matches, card)
                if card is None:
                    break
                editor.open(card)
            query = ""
    except (EOFError, KeyboardInterrupt):
        print()
        if editor.card and editor.pending():
            print("Unsaved changes discarded.")


if __name__ == "__main__":
    main()
