"""Small helpers for matching and laying out text."""

import os
import re
import textwrap


def squash(text):
    """Lower case letters and digits only, so "argh smash" finds "Argh... Smash!"."""

    return re.sub(r"[^a-z0-9]", "", text.lower())


def split_list(value):
    return [part.strip() for part in value.split(",") if part.strip()]


def wrap(value, width):
    """A value as display lines, keeping its own line breaks and never splitting a URL."""

    lines = []
    for line in value.split("\n"):
        lines += textwrap.wrap(line, width, break_long_words=False, break_on_hyphens=False) or [""]
    return lines


def excerpts(old, new, limit=60):
    """
    Both sides of a change cut down to a line each.

    Functional text mostly gets edited somewhere in the middle, so start the excerpt just
    before the first difference rather than showing two identical opening sentences.
    """

    old, new = (text.replace("\n", "\\n") for text in (old, new))
    shared = len(os.path.commonprefix([old, new]))
    start = shared - 15 if shared > 30 else 0

    def cut(text):
        piece = ("…" if start else "") + text[start:]
        return (piece if len(piece) <= limit else piece[: limit - 1] + "…") or "(blank)"

    return cut(old), cut(new)
