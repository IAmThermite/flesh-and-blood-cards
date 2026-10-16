"""
A full-screen list to move through with the arrow keys.

It's drawn on the terminal's alternate screen with plain escape codes rather than curses, so
that the bottom few rows can be handed back to print() and readline - a value gets edited on
an ordinary line, with the list still showing above it.
"""

import contextlib
import os
import select
import shutil
import sys

try:
    import termios
    import tty
except ImportError:  # Windows
    termios = tty = None

COLOUR = sys.stdout.isatty() and "NO_COLOR" not in os.environ

KEYS = {
    b"\x1b[A": "up",
    b"\x1bOA": "up",
    b"\x1b[B": "down",
    b"\x1bOB": "down",
    b"\x1b[C": "right",
    b"\x1bOC": "right",
    b"\x1b[D": "left",
    b"\x1bOD": "left",
    b"\x1b[5~": "page up",
    b"\x1b[6~": "page down",
    b"\x1b[H": "home",
    b"\x1bOH": "home",
    b"\x1b[1~": "home",
    b"\x1b[F": "end",
    b"\x1bOF": "end",
    b"\x1b[4~": "end",
    b"\x1b[3~": "delete",
    b"\x01": "home",  # Ctrl-A
    b"\x05": "end",  # Ctrl-E
    b"\x0b": "kill",  # Ctrl-K
    b"\x17": "kill word",  # Ctrl-W
    b"\r": "enter",
    b"\n": "enter",
    b"\t": "tab",
    b"\x1b[Z": "back tab",  # Shift-Tab
    b"\x7f": "backspace",
    b"\x08": "backspace",
    b"\x15": "clear",  # Ctrl-U
    b"\x04": "interrupt",  # Ctrl-D
    b"\x1b": "escape",
}

# How many pickable rows each movement key shifts the highlight by.
MOVES = {
    "up": -1,
    "k": -1,
    "down": 1,
    "j": 1,
    "page up": -10,
    "page down": 10,
    "home": -sys.maxsize,
    "end": sys.maxsize,
}


def bold(text):
    return f"\033[1m{text}\033[0m" if COLOUR else text


def dim(text):
    return f"\033[2m{text}\033[0m" if COLOUR else text


def can_browse():
    """Whether there's a terminal here to draw on and read a key at a time from."""

    return (
        termios is not None
        and sys.stdin.isatty()
        and sys.stdout.isatty()
        and os.environ.get("TERM") != "dumb"
    )


class Row:
    """An entry in the list: its lines of text, and what it stands for if it can be picked."""

    def __init__(self, lines, target=None, style=None):
        self.lines = [lines] if isinstance(lines, str) else lines
        self.target = target
        self.style = style


class Cursor:
    """Which row is highlighted and how far the list is scrolled, kept between redraws."""

    def __init__(self):
        self.at = None
        self.top = 0


class Screen:
    def __init__(self):
        self.fd = sys.stdin.fileno()
        self.cooked = termios.tcgetattr(self.fd)
        self.view = None
        self.size = None

    def __enter__(self):
        self.write("\033[?1049h")
        self.listen()
        return self

    def __exit__(self, *error):
        self.release()
        self.write("\033[?1049l")

    def write(self, text):
        sys.stdout.write(text)
        sys.stdout.flush()

    def listen(self):
        """Take keys one at a time, unechoed, with the cursor hidden."""

        tty.setcbreak(self.fd)
        self.write("\033[?25l")

    def release(self):
        """Give the terminal back to typing a line at a time."""

        termios.tcsetattr(self.fd, termios.TCSADRAIN, self.cooked)
        self.write("\033[?25h")

    @contextlib.contextmanager
    def console(self, rows):
        """
        Hand the bottom rows back to print() and input(), keeping the list in view above.

        Whatever gets written there is drawn over the next time the list is shown.
        """

        height = shutil.get_terminal_size().lines
        rows = max(3, min(rows, height // 2))
        self.draw(reserve=rows)
        self.write(f"\033[{height - rows + 1};1H\033[J")
        self.release()
        try:
            yield
        finally:
            self.listen()

    @contextlib.contextmanager
    def suspended(self):
        """Step off the alternate screen altogether, for a program that wants the terminal."""

        self.__exit__()
        try:
            yield
        finally:
            self.__enter__()

    def choose(self, title, rows, cursor, keys, messages=(), typing=False, edges=False):
        """
        Show the rows and let the arrow keys move the highlight between the pickable ones.

        Returns the first key pressed that isn't a movement, leaving cursor.at on the row it
        was pressed on (None if nothing can be picked). Letters come back lower case, as
        commands - unless the caller is `typing`, when every character comes back as it was
        typed and only the arrow keys move. With `edges`, ↑ on the first row and ↓ on the
        last come back as "past top" and "past bottom" rather than staying put.
        """

        picks = [index for index, row in enumerate(rows) if row.target is not None]
        if cursor.at not in picks:
            # First showing, or the row that was highlighted has gone: take the nearest.
            near = cursor.at or 0
            cursor.at = min(picks, key=lambda index: abs(index - near), default=None)
        self.view = (title, rows, cursor, keys, list(messages))

        while True:
            self.draw()
            try:
                key = self.read_key()
            except KeyboardInterrupt:
                key = "interrupt"

            if not typing:
                key = "q" if key == "interrupt" else key.lower()
            if edges and key in ("up", "down"):
                place = picks.index(cursor.at) + MOVES[key] if picks else -1
                if not 0 <= place < len(picks):
                    return "past top" if key == "up" else "past bottom"
            if key in MOVES and not (typing and len(key) == 1):
                if picks:
                    place = picks.index(cursor.at) + MOVES[key]
                    cursor.at = picks[max(0, min(place, len(picks) - 1))]
            elif key != "resize":
                return key

    def edit_line(self, prompt, text, hint="", notes=()):
        """
        Edit a line of text at the foot of the screen, with the list still showing above it.

        readline would take ↑ and ↓ for its history, so this edits the line itself, to let
        those keys end it instead. `notes` are shown above it. Returns how it ended - "enter",
        "up", "down", "tab", "back tab", "escape" or "interrupt" - and the text as it was then.
        """

        position = len(text)
        while True:
            self.draw_line(prompt, text, position, hint, notes)
            try:
                key = self.read_key()
            except KeyboardInterrupt:
                key = "interrupt"

            if key in ("enter", "up", "down", "tab", "back tab", "escape", "interrupt"):
                self.write("\033[?25l")
                return key, text
            if key == "left":
                position = max(position - 1, 0)
            elif key == "right":
                position = min(position + 1, len(text))
            elif key == "home":
                position = 0
            elif key == "end":
                position = len(text)
            elif key == "backspace" and position:
                text, position = text[: position - 1] + text[position:], position - 1
            elif key == "delete":
                text = text[:position] + text[position + 1 :]
            elif key == "clear":
                text, position = text[position:], 0
            elif key == "kill":
                text = text[:position]
            elif key == "kill word":
                start = len(text[:position].rstrip().rpartition(" ")[0])
                start = start + 1 if start else 0
                text, position = text[:start] + text[position:], start
            elif len(key) == 1 and key.isprintable():
                text, position = text[:position] + key + text[position:], position + 1

    def draw_line(self, prompt, text, position, hint, notes=()):
        """The line being edited, wrapped onto as many rows as it needs, with its cursor."""

        width = shutil.get_terminal_size().columns - 1
        line = prompt + text
        cursor = len(prompt) + position
        rows = [line[start : start + width] for start in range(0, len(line), width)] or [""]
        # A cursor just past the last character can need a row of its own.
        if cursor // width >= len(rows):
            rows.append("")
        above = [f"  {note}"[:width] for note in notes]
        if hint:
            above.append(dim(f"  {hint}"[:width]))
        rows = above + rows

        self.draw(reserve=len(rows))
        top = self.size.lines - len(rows) + 1
        out = [f"\033[{top};1H\033[J"]
        out += [f"\033[{top + offset};1H{row}" for offset, row in enumerate(rows)]
        offset = len(above) + cursor // width
        out.append(f"\033[{top + offset};{cursor % width + 1}H\033[?25h")
        self.write("".join(out))

    def show(self, title, rows, cursor, keys, messages=()):
        """Draw the rows without waiting for a key - to show where a run of prompts has got to."""

        self.view = (title, rows, cursor, keys, list(messages))
        self.draw()

    def read_key(self):
        """The next key press, by name where it has one - or 'resize' if the window changed."""

        while not select.select([self.fd], [], [], 0.2)[0]:
            if shutil.get_terminal_size() != self.size:
                return "resize"

        data = os.read(self.fd, 1)
        # An arrow key arrives as Escape plus a few more bytes. A bare Escape arrives alone.
        while data[:1] == b"\x1b" and select.select([self.fd], [], [], 0.05)[0]:
            data += os.read(self.fd, 1)
            if len(data) > 2 and (data[-1:].isalpha() or data[-1:] == b"~"):
                break
        # An accented letter is two to four bytes, the first saying how many follow it.
        if data[0] >= 0xC0:
            data += os.read(self.fd, 1 + (data[0] >= 0xE0) + (data[0] >= 0xF0))

        return KEYS.get(data, data.decode("utf-8", "ignore"))

    def draw(self, reserve=0):
        """
        Paint the list, scrolled so the highlighted row is in view.

        The foot of the screen holds the messages and key help, unless `reserve` rows are
        being kept clear there for a console.
        """

        title, rows, cursor, keys, messages = self.view
        self.size = shutil.get_terminal_size()
        # The last column is left alone: writing into it makes some terminals wrap.
        width, height = self.size.columns - 1, self.size.lines
        messages = messages[-max(height // 3, 1) :]
        body = max(height - 1 - (reserve or 1 + len(messages) + len(keys)), 1)

        lines = [
            (index, offset, text)
            for index, row in enumerate(rows)
            for offset, text in enumerate(row.lines)
        ]
        picks = [index for index, row in enumerate(rows) if row.target is not None]
        if cursor.at is not None:
            mine = [n for n, line in enumerate(lines) if line[0] == cursor.at]
            # On the first or last pickable row, bring whatever lies beyond it into view too.
            first = 0 if cursor.at == picks[0] else mine[0]
            last = len(lines) - 1 if cursor.at == picks[-1] else mine[-1]
            cursor.top = min(max(cursor.top, last - body + 1), first)
        cursor.top = max(0, min(cursor.top, len(lines) - body))

        out = [f"\033[1;1H\033[K{bold(title[:width])}"]
        for y in range(body):
            out.append(f"\033[{y + 2};1H\033[K")
            if cursor.top + y >= len(lines):
                continue
            index, offset, text = lines[cursor.top + y]
            if index == cursor.at:
                text = f"{'>' if offset == 0 else ' '} {text}"[:width]
                out.append(f"\033[7m{text.ljust(width)}\033[0m" if COLOUR else text)
            else:
                text = f"  {text}"[:width]
                out.append(rows[index].style(text) if rows[index].style else text)

        if not reserve:
            above, below = cursor.top, max(len(lines) - cursor.top - body, 0)
            more = [f"↑ {above} more" if above else "", f"↓ {below} more" if below else ""]
            foot = [dim("  " + "   ".join(part for part in more if part))]
            foot += [f"  {message}"[:width] for message in messages]
            foot += [dim(line[:width]) for line in keys]
            for y, text in enumerate(foot, body + 2):
                out.append(f"\033[{y};1H\033[K{text}")

        self.write("".join(out))
