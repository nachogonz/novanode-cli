"""Keyboard-driven menu primitives.

Raw termios reads with arrow-key navigation. No external dependencies. Falls
back to a plain text list when stdin/stdout is not a TTY, so subprocesses and
pipes still work.
"""

import os
import sys
import termios
import tty

CSI = "\033["
RESET = "\033[0m"
BOLD = "\033[1m"
DIM = "\033[38;5;245m"
ORANGE = "\033[38;5;208m"
GREEN = "\033[38;5;82m"
CYAN = "\033[38;5;51m"
RED = "\033[38;5;196m"
YELLOW = "\033[38;5;220m"


def color_on():
    return sys.stdout.isatty() and os.environ.get("NO_COLOR") is None


def paint(value, code):
    return f"{code}{value}{RESET}" if color_on() else value


def is_tty():
    return sys.stdin.isatty() and sys.stdout.isatty()


ARROWS = {"A": "up", "B": "down", "C": "right", "D": "left"}


def read_key():
    """Read one keypress. Returns 'up'/'down'/'left'/'right'/'enter'/'esc'/
    'backspace'/'tab' or the raw character (single lowercase letter etc.)."""
    fd = sys.stdin.fileno()
    old = termios.tcgetattr(fd)
    try:
        tty.setraw(fd)
        ch = sys.stdin.read(1)
        if ch == "\x1b":
            second = sys.stdin.read(1)
            if second != "[":
                return "esc"
            third = sys.stdin.read(1)
            return ARROWS.get(third, "esc")
        if ch in ("\r", "\n"):
            return "enter"
        if ch == "\x7f":
            return "backspace"
        if ch == "\t":
            return "tab"
        if ch == "\x03":
            raise KeyboardInterrupt
        return ch.lower() if ch.isalpha() else ch
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, old)


def clear_screen():
    if sys.stdout.isatty():
        sys.stdout.write(f"{CSI}2J{CSI}H")
        sys.stdout.flush()


def hide_cursor():
    if sys.stdout.isatty():
        sys.stdout.write(f"{CSI}?25l")
        sys.stdout.flush()


def show_cursor():
    if sys.stdout.isatty():
        sys.stdout.write(f"{CSI}?25h")
        sys.stdout.flush()


class Item:
    """A selectable row. Use ``divider=True`` for a non-selectable spacer or
    heading. ``value`` is returned to the caller; ``label`` is what shows."""

    __slots__ = ("label", "value", "subtitle", "badge", "badge_color",
                 "disabled", "divider", "heading")

    def __init__(self, label="", value=None, subtitle=None, badge=None,
                 badge_color=None, disabled=False, divider=False,
                 heading=False):
        self.label = label
        self.value = value
        self.subtitle = subtitle
        self.badge = badge
        self.badge_color = badge_color or DIM
        self.disabled = disabled or divider or heading
        self.divider = divider
        self.heading = heading


class Menu:
    """Arrow-key menu. Use ``run()`` inside a TTY session. Non-TTY callers
    should render items with ``static_render()`` for informational display."""

    def __init__(self, title, items, footer="", subtitle="",
                 message="", hotkeys=None):
        self.title = title
        self.subtitle = subtitle
        self.items = items
        self.footer = footer
        self.message = message
        # hotkeys: dict of char -> return value; short-circuits selection.
        self.hotkeys = hotkeys or {}
        self.selected = self._first_selectable(0, +1)

    def _first_selectable(self, start, step):
        n = len(self.items)
        for offset in range(n):
            index = (start + offset * step) % n
            if not self.items[index].disabled:
                return index
        return start

    def _move(self, step):
        n = len(self.items)
        for _ in range(n):
            self.selected = (self.selected + step) % n
            if not self.items[self.selected].disabled:
                return

    def _render(self):
        clear_screen()
        print()
        print(f"  {paint(self.title, BOLD)}")
        if self.subtitle:
            print(f"  {paint(self.subtitle, DIM)}")
        print(f"  {paint('─' * max(48, len(self.title) + 20), ORANGE)}")
        print()
        for index, item in enumerate(self.items):
            if item.divider:
                print()
                continue
            if item.heading:
                print(f"  {paint(item.label, BOLD)}")
                if item.subtitle:
                    print(f"  {paint(item.subtitle, DIM)}")
                continue
            selected = index == self.selected
            arrow = paint("▸", ORANGE) if selected else " "
            label = paint(item.label, BOLD) if selected else item.label
            badge = f"  {paint(item.badge, item.badge_color)}" if item.badge else ""
            print(f"  {arrow} {label}{badge}")
            if item.subtitle:
                print(f"     {paint(item.subtitle, DIM)}")
        print()
        if self.footer:
            print(f"  {paint(self.footer, DIM)}")
        if self.message:
            print()
            print(f"  {self.message}")

    def run(self):
        """Run the menu loop. Returns the selected item's value, or None on
        Esc/Q. Hotkeys short-circuit and return their mapped value."""
        if not is_tty():
            self.static_render()
            return None
        hide_cursor()
        try:
            while True:
                self._render()
                try:
                    key = read_key()
                except KeyboardInterrupt:
                    return None
                if key in ("q", "esc"):
                    return None
                if key == "up":
                    self._move(-1)
                    continue
                if key == "down":
                    self._move(+1)
                    continue
                if key == "enter":
                    return self.items[self.selected].value
                if key in self.hotkeys:
                    return self.hotkeys[key]
        finally:
            show_cursor()
            clear_screen()

    def static_render(self):
        """Non-interactive rendering — plain list, no highlight."""
        print()
        print(f"  {paint(self.title, BOLD)}")
        if self.subtitle:
            print(f"  {paint(self.subtitle, DIM)}")
        print(f"  {paint('─' * max(48, len(self.title) + 20), ORANGE)}")
        print()
        for item in self.items:
            if item.divider:
                print()
                continue
            if item.heading:
                print(f"  {paint(item.label, BOLD)}")
                continue
            badge = f"  {paint(item.badge, item.badge_color)}" if item.badge else ""
            print(f"    {item.label}{badge}")
            if item.subtitle:
                print(f"     {paint(item.subtitle, DIM)}")
        print()
        if self.footer:
            print(f"  {paint(self.footer, DIM)}")


def confirm(question, danger_word="delete"):
    """Ask the user to type an exact word to confirm. Returns True on match."""
    print()
    print(f"  {paint(question, YELLOW)}")
    try:
        answer = input(f"  Type {paint(danger_word, BOLD)} to confirm: ").strip().lower()
    except (EOFError, KeyboardInterrupt):
        return False
    return answer == danger_word


def prompt(label, default=None, mask=False):
    """Read a single line of input, echoing what the user typed."""
    print()
    suffix = f" [{default}]" if default else ""
    try:
        if mask:
            import getpass
            value = getpass.getpass(f"  {label}{suffix}: ")
        else:
            value = input(f"  {label}{suffix}: ").strip()
    except (EOFError, KeyboardInterrupt):
        return None
    return value or default
