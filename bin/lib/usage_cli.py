#!/usr/bin/env python3
import json
import os
import re
import shutil
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import usage


VERSION = "1.1.0"
GREEN = "\033[38;5;82m"
ORANGE = "\033[38;5;208m"
RED = "\033[38;5;196m"
DIM = "\033[38;5;245m"
BOLD = "\033[1m"
RESET = "\033[0m"


def help_text():
    print(f"""nn-usage {VERSION}

Clean AI plan-usage dashboard for Claude Code and Codex CLI.

Usage:
  nn-usage
  nn-usage --summary-tsv
  nn-usage --json
  nn-usage --help
  nn-usage --version
""")


def summary_tsv(rows):
    fields = ("key", "command", "version", "p1", "used1", "left1", "reset1", "p2", "used2", "left2", "reset2")
    for row in rows:
        print("\t".join(str(row.get(field, "n/a")) for field in fields))


def meter(value, width):
    number = usage.pct_num(value)
    if number is None:
        return DIM + "░" * width + RESET, "n/a", DIM
    filled = round(number / 100 * width)
    color = RED if number >= 90 else ORANGE if number >= 70 else GREEN
    return color + "█" * filled + DIM + "░" * (width - filled) + RESET, f"{number:g}%", color


def visible(text):
    return len(re.sub(r"\033\[[0-9;]*m", "", text))


def card(row, width):
    name = "Claude Code" if row["key"] == "claude" else "Codex CLI"
    inner = width - 4
    lines = [f"{BOLD}{name}{RESET}", f"{DIM}{row['version']}{RESET}", ""]
    for index in (1, 2):
        bar, label, color = meter(row[f"used{index}"], max(10, inner - 14))
        lines.append(f"{row[f'p{index}']:<8}{bar} {color}{label:>6}{RESET}")
        lines.append(f"{DIM}{'':8}resets {row[f'reset{index}']}{RESET}")
    return lines


def dashboard(rows):
    terminal = shutil.get_terminal_size((100, 28)).columns
    width = max(76, min(118, terminal - 2))
    gap = 3
    card_width = (width - gap) // 2
    cards = [card(row, card_width) for row in rows]
    height = max(len(item) for item in cards)
    print()
    print(f"  {BOLD}NOVANODE{RESET}  {DIM}usage control center · live plan windows{RESET}")
    print(f"  {ORANGE}{'─' * width}{RESET}")
    print()
    for line_index in range(height):
        rendered = []
        for item in cards:
            line = item[line_index] if line_index < len(item) else ""
            rendered.append(line + " " * max(0, card_width - visible(line)))
        print("  " + (" " * gap).join(rendered))
    values = [usage.pct_num(row[key]) for row in rows for key in ("used1", "used2")]
    values = [value for value in values if value is not None]
    average = sum(values) / len(values) if values else None
    total_bar, total_label, color = meter(average, max(20, width - 24))
    print()
    print(f"  {BOLD}Combined load{RESET}")
    print(f"  {total_bar} {color}{total_label}{RESET}")
    print(f"  {DIM}Claude Code + Codex CLI{RESET}")
    print()


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv and argv[0] in ("-h", "--help"):
        help_text()
        return 0
    if argv and argv[0] in ("-v", "--version"):
        print(VERSION)
        return 0
    if argv and argv[0] not in ("--summary-tsv", "--json"):
        print(f"nn-usage: unknown option {argv[0]}", file=sys.stderr)
        return 2
    rows = usage.fetch_usage()
    if argv == ["--summary-tsv"]:
        summary_tsv(rows)
    elif argv == ["--json"]:
        print(json.dumps(rows, indent=2))
    else:
        dashboard(rows)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
