"""
What a run found, and the markdown it writes out.

The report says what was added, what was left for manual entry, and which columns were deliberately left blank.
"""

import mapping

# Section attribute -> heading, in the order they appear in the file. Sections with nothing
# in them are left out entirely.
SECTIONS = [
    ("new_cards", "Cards added"),
    ("new_printings", "Printings added"),
    ("face_associations", "Double faced printings paired up"),
    ("skipped", "Needs manual entry"),
    ("check_art_variation", "Check the art variation"),
    ("check_pitch", "Check the pitch"),
    ("check_set_range", "Check the set's card range"),
    ("blocked", "Blocked"),
    ("errors", "Errors"),
]


class Report:
    """
    The results from the run and and any information that needs to be fixed post-run.
    """

    def __init__(self):
        self.sets = []
        for name, _ in SECTIONS:
            setattr(self, name, [])

    def section(self, name):
        return getattr(self, name)

    @property
    def needs_attention(self):
        """Whether the run hit something that should fail the job."""

        return bool(self.blocked or self.errors)

    def render(self, dry_run=False):
        lines = ["# CardVault spoiler fetch", ""]

        if dry_run:
            lines.append("_Dry run - no CSVs were written._")
            lines.append("")

        lines.append(f"Sets checked: {', '.join(self.sets) or 'none'}")
        lines.append("")
        lines.append(f"- {len(self.new_cards)} new cards")
        lines.append(f"- {len(self.new_printings)} new printings")
        lines.append("")

        for name, title in SECTIONS:
            entries = self.section(name)
            if not entries:
                continue
            lines.append(f"## {title}")
            lines.append("")
            lines.extend(f"- {entry}" for entry in entries)
            lines.append("")

        if self.new_cards or self.new_printings:
            lines.append("## Columns left blank on purpose")
            lines.append("")
            lines.append("These are a reading of the card rather than something the API states:")
            lines.append("")
            lines.extend(f"- card.csv `{name}`" for name in mapping.UNFILLED_CARD_COLUMNS)
            lines.extend(
                f"- card-printing.csv `{name}`" for name in mapping.UNFILLED_PRINTING_COLUMNS
            )
            lines.append("")
            lines.append(mapping.ART_VARIATION_CAVEAT)
            lines.append("")

        return "\n".join(lines)

    def write(self, path, dry_run=False):
        path.write_text(self.render(dry_run=dry_run), encoding="utf-8")
        print(f"Report written to {path}")
