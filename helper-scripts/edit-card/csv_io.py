"""
Reading and writing the CSVs.

Rows are kept exactly as read, so a row nobody edited is written back byte for byte, and a
Record is a working copy of one row that can be compared with what's on disk.
"""

import csv
import secrets
from pathlib import Path

CSV_DIR = Path(__file__).parent / "../../csvs/english"
CARD_CSV = "card.csv"
PRINTING_CSV = "card-printing.csv"
REFERENCE_CSV = "card-reference.csv"

# generate-unique-ids mints IDs with nanoid's "nolookalikesSafe" alphabet, 21 characters long.
ID_ALPHABET = "6789BCDFGHJKLMNPQRTWbcdfghjkmnpqrtwz"


class Table:
    """A CSV held as raw rows, so a row nobody edited is written back byte for byte."""

    def __init__(self, name):
        self.path = CSV_DIR / name
        with self.path.open(newline="", encoding="utf-8") as csvfile:
            rows = list(csv.reader(csvfile, delimiter="\t", quotechar='"'))

        if not rows:
            raise SystemExit(f"{self.path} is empty")

        self.header, self.rows = rows[0], rows[1:]
        # card-printing.csv is padded out with unnamed columns. They're kept, just not shown.
        self.index = {column: position for position, column in enumerate(self.header) if column}
        self.read_at = self.stamp()

    def stamp(self):
        stat = self.path.stat()
        return stat.st_mtime_ns, stat.st_size

    def changed_on_disk(self):
        return self.stamp() != self.read_at

    def write(self):
        with self.path.open("w", newline="", encoding="utf-8") as csvfile:
            writer = csv.writer(csvfile, delimiter="\t", quotechar='"', lineterminator="\n")
            writer.writerow(self.header)
            writer.writerows(self.rows)
        self.read_at = self.stamp()


class Record:
    """A working copy of one row. `original` is the row inside its Table, or None if it's new."""

    def __init__(self, table, original=None, values=None):
        self.table = table
        self.original = original
        self.values = list(original if values is None else values)
        self.deleted = False

    def __getitem__(self, column):
        return self.values[self.table.index[column]]

    def __setitem__(self, column, value):
        self.values[self.table.index[column]] = value

    def before(self, column):
        return self.original[self.table.index[column]]

    def changes(self):
        """(column, old, new) for each column that no longer matches what's on disk."""

        if self.original is None:
            return []
        return [
            (column, self.original[position], self.values[position])
            for column, position in self.table.index.items()
            if self.original[position] != self.values[position]
        ]

    @property
    def marker(self):
        if self.deleted:
            return "-"
        if self.original is None:
            return "+"
        return "*" if self.values != self.original else " "


def read_rows(name):
    with (CSV_DIR / name).open(newline="", encoding="utf-8") as csvfile:
        return list(csv.DictReader(csvfile, delimiter="\t", quotechar='"'))


def mint_unique_id(taken):
    """A new Unique ID of the kind generate-unique-ids gives, and not one of `taken`."""

    while True:
        unique_id = "".join(secrets.choice(ID_ALPHABET) for _ in range(21))
        if unique_id not in taken:
            return unique_id


def files_mentioning(unique_id):
    """The other English CSVs that reference a Unique ID."""

    return [
        path.name
        for path in sorted(CSV_DIR.glob("*.csv"))
        if path.name not in (CARD_CSV, PRINTING_CSV)
        and unique_id in path.read_text(encoding="utf-8")
    ]
