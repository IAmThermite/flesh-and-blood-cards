import bisect
import csv
from pathlib import Path

CSV_DIR = Path(__file__).parent / "../../csvs/english"

# Some functional text runs well past the default field size limit.
csv.field_size_limit(1024 * 1024)

# Where several printings share a set number the CSVs list the plain one first, then the
# rainbow foil, then the cold foil - 650-odd runs in the recent sets follow that and only two
# don't. Alphabetical order would put them C, R, S, so rank them explicitly.
FOILING_ORDER = {"S": 0, "R": 1, "C": 2, "G": 3}


def read_csv(path):
    """Return (header, rows) for a tab separated CSV, preserving the padded column count."""

    with path.open(newline="", encoding="utf-8") as csvfile:
        reader = csv.reader(csvfile, delimiter="\t", quotechar='"')
        rows = list(reader)

    if not rows:
        raise SystemExit(f"{path} is empty")

    return rows[0], rows[1:]


def write_csv(path, header, rows):
    with path.open("w", newline="", encoding="utf-8") as csvfile:
        writer = csv.writer(csvfile, delimiter="\t", quotechar='"', lineterminator="\n")
        writer.writerow(header)
        writer.writerows(rows)


def column_index(header, name):
    try:
        return header.index(name)
    except ValueError:
        raise SystemExit(f"expected a {name!r} column, got: {header}")


def build_row(header, fields):
    """Lay a {column: value} mapping out against the header, padding to the full width."""

    row = [""] * len(header)
    for name, value in fields.items():
        row[column_index(header, name)] = value
    return row


def row_key(header, columns):
    """A sort key reading the named columns out of a raw row."""

    indexes = [column_index(header, column) for column in columns]
    return lambda row: tuple(row[index] if index < len(row) else "" for index in indexes)


def insert_sorted(existing_rows, new_rows, position_key):
    """
    Slot new rows into their sorted position, leaving every existing row where it is.
    """

    if not new_rows:
        return existing_rows

    keys = [position_key(row) for row in existing_rows]

    buckets = {}
    for row in new_rows:
        position = bisect.bisect_right(keys, position_key(row))
        buckets.setdefault(position, []).append(row)

    merged = []
    for index, row in enumerate(existing_rows):
        merged.extend(buckets.pop(index, ()))
        merged.append(row)

    for position in sorted(buckets):
        merged.extend(buckets[position])

    return merged


def add_cards(header, rows, new_fields):
    """Merge new card.csv rows in, keeping the file in Name order with pitches ascending."""

    position = row_key(header, ("Name", "Pitch"))
    new_rows = sorted((build_row(header, fields) for fields in new_fields), key=position)
    return insert_sorted(rows, new_rows, position)


def add_printings(header, rows, new_fields):
    """
    Merge new card-printing.csv rows in, keeping the file in Card ID order.

    Within one set number the plain printing comes before its foils, and a double sided
    printing's front before its back
    """

    position = row_key(header, ("Card ID",))
    foiling_of = row_key(header, ("Foiling",))
    new_rows = sorted(
        (build_row(header, fields) for fields in new_fields),
        key=lambda row: (
            position(row),
            FOILING_ORDER.get(foiling_of(row)[0], len(FOILING_ORDER)),
        ),
    )
    return insert_sorted(rows, new_rows, position)


def add_associations(header, rows, new_rows):
    """Merge card-face-association.csv rows in, keeping Front Card Printing order."""

    position = row_key(header, ("Front Card Printing",))
    return insert_sorted(rows, sorted(new_rows, key=position), position)


def resolve_set_printing(set_code):
    """
    Find the Set Printing Unique ID for a set's 'N' edition.

    Returns (unique_id, start_card_id, end_card_id), or None if the set hasn't been added to
    set.csv / set-printing.csv yet. That has to happen by hand first, because the set needs a
    release date.
    """

    set_header, set_rows = read_csv(CSV_DIR / "set.csv")
    identifier_index = column_index(set_header, "Identifier")
    set_unique_index = column_index(set_header, "Unique ID")

    set_unique_id = None
    for row in set_rows:
        if len(row) > identifier_index and row[identifier_index] == set_code:
            set_unique_id = row[set_unique_index]
            break

    if not set_unique_id:
        return None

    printing_header, printing_rows = read_csv(CSV_DIR / "set-printing.csv")
    indexes = {
        name: column_index(printing_header, name)
        for name in ("Unique ID", "Set Unique ID", "Edition", "Start Card Id", "End Card Id")
    }

    for row in printing_rows:
        if len(row) <= indexes["Edition"]:
            continue
        if row[indexes["Set Unique ID"]] == set_unique_id and row[indexes["Edition"]] == "N":
            return (
                row[indexes["Unique ID"]],
                row[indexes["Start Card Id"]],
                row[indexes["End Card Id"]],
            )

    return None


def index_existing(card_header, card_rows, printing_header, printing_rows):
    """
    Build the lookups used to decide what's already in the CSVs.

    cards        (Name, Pitch) -> Unique ID
    codes        Set ID -> {Card ID}
    printings    (Set ID, Card ID, Foiling) -> how many rows the CSV already has
    pitches      Name -> {Pitch}, each pitch that has been entered for a card, so we can tell if a new pitch is needed
    """

    name_index = column_index(card_header, "Name")
    pitch_index = column_index(card_header, "Pitch")
    card_unique_index = column_index(card_header, "Unique ID")

    cards = {}
    pitches = {}
    for row in card_rows:
        if len(row) <= pitch_index:
            continue
        key = (row[name_index], row[pitch_index])
        cards.setdefault(key, row[card_unique_index])
        pitches.setdefault(row[name_index], set()).add(row[pitch_index])

    set_index = column_index(printing_header, "Set ID")
    code_index = column_index(printing_header, "Card ID")
    foiling_index = column_index(printing_header, "Foiling")

    codes = {}
    printings = {}
    for row in printing_rows:
        if len(row) <= foiling_index:
            continue
        codes.setdefault(row[set_index], set()).add(row[code_index])
        key = (row[set_index], row[code_index], row[foiling_index])
        printings[key] = printings.get(key, 0) + 1

    return cards, codes, printings, pitches
