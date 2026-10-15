"""Asking for a value on a line of the terminal, or in $EDITOR."""

import os
import shlex
import subprocess
import sys
import tempfile
from pathlib import Path

from screen import dim

try:
    import readline
except ImportError:  # Windows ships Python without it
    readline = None

# input() only goes through readline when it's talking to a terminal at both ends.
CAN_PREFILL = readline is not None and sys.stdin.isatty() and sys.stdout.isatty()


class History:
    """
    The answers given to one kind of prompt this session, for its up and down arrows.

    readline keeps one history for every prompt, so this is swapped in only while its own
    prompt is open - searches don't turn up when editing a field, nor field values when
    searching. Nothing is kept once the script ends.
    """

    def __init__(self):
        self.entries = []

    def ask(self, prompt):
        if not CAN_PREFILL:
            return self.remember(input(prompt))

        # GNU readline counts history from 1 and libedit from 0, so take whatever is there.
        everything_else = [
            item
            for position in range(readline.get_current_history_length() + 1)
            if (item := readline.get_history_item(position)) is not None
        ]
        readline.clear_history()
        for entry in self.entries:
            readline.add_history(entry)
        try:
            answer = input(prompt)
        finally:
            readline.clear_history()
            for item in everything_else:
                readline.add_history(item)
        return self.remember(answer)

    def remember(self, answer):
        """Note an answer as the most recent, once - asking again moves it to the end."""

        answer = answer.strip()
        if answer:
            if answer in self.entries:
                self.entries.remove(answer)
            self.entries.append(answer)
        return answer


def ask_value(column, current, draft):
    """
    Ask for a field's new value, with line breaks typed and shown as \\n.

    Where readline is available the line starts out holding the value, ready to be edited in
    place. Elsewhere there's nothing to edit, so Enter keeps the value and a lone - clears it.
    """

    shown = draft.replace("\n", "\\n")

    if CAN_PREFILL:
        readline.set_startup_hook(lambda: readline.insert_text(shown))
        try:
            entered = input(f"{column}: ")
        finally:
            readline.set_startup_hook(None)
    else:
        entered = input(f"{column} [{shown}] (Enter keeps it, - clears it): ").strip()
        if not entered:
            return current
        if entered == "-":
            return ""

    return entered.strip().replace("\\n", "\n")


def edit_in_editor(value):
    """
    Hand a value to $VISUAL / $EDITOR in a scratch file, for text too long to edit on one line.

    RuntimeError if there's no editor to hand it to, or it didn't come back cleanly.
    """

    command = os.environ.get("VISUAL") or os.environ.get("EDITOR")
    if not command:
        raise RuntimeError("set $EDITOR first, e.g. EDITOR=nano or EDITOR='code --wait'")

    with tempfile.NamedTemporaryFile(
        "w", suffix=".md", encoding="utf-8", delete=False
    ) as scratch:
        scratch.write(value)

    try:
        print(dim(f"  editing in {command} - save and close the file to carry on"))
        subprocess.run(shlex.split(command) + [scratch.name], check=True)
        return Path(scratch.name).read_text(encoding="utf-8").strip()
    except (OSError, subprocess.CalledProcessError) as error:
        raise RuntimeError(f"{command} didn't finish cleanly, nothing changed ({error})")
    finally:
        os.unlink(scratch.name)
