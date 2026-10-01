"""NovaNode Icons — Unicode glyphs with ASCII fallbacks."""

import os
import sys


def _supports_unicode() -> bool:
    """Check if terminal likely supports Unicode box drawing."""
    term = os.environ.get("TERM", "").lower()
    if "dumb" in term:
        return False
    if not sys.stdout.isatty():
        return False
    # Heuristic: most modern terminals support Unicode
    return True


_UNICODE = _supports_unicode()


class Icons:
    """Icon set with automatic fallback."""

    # Box drawing
    if _UNICODE:
        TL = "╭"
        TR = "╮"
        BL = "╰"
        BR = "╯"
        H = "─"
        V = "│"
        TL_BOLD = "┏"
        TR_BOLD = "┓"
        BL_BOLD = "┗"
        BR_BOLD = "┛"
        H_BOLD = "━"
        V_BOLD = "┃"
        LEFT_T = "├"
        RIGHT_T = "┤"
        TOP_T = "┬"
        BOTTOM_T = "┴"
        CROSS = "┼"
        LEFT_HALF = "╺"
        RIGHT_HALF = "╸"
        VERT_THIN = "│"
    else:
        TL = "+"
        TR = "+"
        BL = "+"
        BR = "+"
        H = "-"
        V = "|"
        TL_BOLD = "+"
        TR_BOLD = "+"
        BL_BOLD = "+"
        BR_BOLD = "+"
        H_BOLD = "="
        V_BOLD = "|"
        LEFT_T = "+"
        RIGHT_T = "+"
        TOP_T = "+"
        BOTTOM_T = "+"
        CROSS = "+"
        LEFT_HALF = "-"
        RIGHT_HALF = "-"
        VERT_THIN = "|"

    # Status dots
    if _UNICODE:
        DOT_FILLED = "●"
        DOT_EMPTY = "○"
        DOT_SHADOWED = "◌"
        DOT_LOADING = "◐"
        CHECK = "✓"
        CROSS_MARK = "✗"
        ARROW_RIGHT = "▸"
        ARROW_LEFT = "◂"
        ARROW_UP = "▲"
        ARROW_DOWN = "▼"
        DIAMOND = "◆"
        SQUARE = "■"
        CIRCLE = "○"
        TRIANGLE_WARN = "▲"
    else:
        DOT_FILLED = "*"
        DOT_EMPTY = "o"
        DOT_SHADOWED = "o"
        DOT_LOADING = "@"
        CHECK = "+"
        CROSS_MARK = "x"
        ARROW_RIGHT = ">"
        ARROW_LEFT = "<"
        ARROW_UP = "^"
        ARROW_DOWN = "v"
        DIAMOND = "<>"
        SQUARE = "[]"
        CIRCLE = "()"
        TRIANGLE_WARN = "!"

    # UI elements
    if _UNICODE:
        KEY_ENTER = "↵"
        KEY_ESC = "⎋"
        KEY_TAB = "⇥"
        KEY_UP = "↑"
        KEY_DOWN = "↓"
        KEY_LEFT = "←"
        KEY_RIGHT = "→"
        SEPARATOR = "│"
        ELLIPSIS = "…"
        BLOCK_FULL = "█"
        BLOCK_EMPTY = "░"
        BLOCK_PARTIAL = "▓"
    else:
        KEY_ENTER = "ENT"
        KEY_ESC = "ESC"
        KEY_TAB = "TAB"
        KEY_UP = "UP"
        KEY_DOWN = "DN"
        KEY_LEFT = "LT"
        KEY_RIGHT = "RT"
        SEPARATOR = "|"
        ELLIPSIS = "..."
        BLOCK_FULL = "#"
        BLOCK_EMPTY = "."
        BLOCK_PARTIAL = "+"


ICONS = Icons()


def icon(name: str) -> str:
    """Get icon by name with fallback."""
    return getattr(ICONS, name.upper(), "")