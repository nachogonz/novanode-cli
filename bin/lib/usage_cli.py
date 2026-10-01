#!/usr/bin/env python3
import json
import os
import re
import shutil
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import usage
import usage_connect


VERSION = "1.3.0"
GREEN = "\033[38;5;82m"
ORANGE = "\033[38;5;208m"
RED = "\033[38;5;196m"
DIM = "\033[38;5;245m"
BOLD = "\033[1m"
RESET = "\033[0m"


def help_text():
    print(f"""nn-usage {VERSION}

AI plan-usage dashboard for Claude Code and Codex CLI.

Usage:
  usage                    Textual dashboard (unified NovaNode UI)
  usage --classic          Legacy plain-text dashboard
  usage connect            Manage provider connections
  usage connect manage
  usage connect openai [profile-name]
  usage connect claude [profile-name]
  usage --summary-tsv      Tab-separated snapshot
  usage --json             JSON snapshot
  nn-usage                 Same as `usage`
  nn-usage --help
  nn-usage --version

`usage` is the fast alias; `nn-usage` remains supported.
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
    name = row.get("name") or ("Claude Code" if row["key"].startswith("claude") else "Codex CLI")
    inner = width - 4
    lines = [f"{BOLD}{name}{RESET}", f"{DIM}{row['version']}{RESET}", ""]
    if row.get("usage_status") == "unavailable":
        lines.extend([
            f"{DIM}Usage data temporarily unavailable{RESET}",
            f"{DIM}Retry `usage`; your other profiles are unaffected.{RESET}",
            "",
            "",
        ])
        return lines
    for index in (1, 2):
        if usage.pct_num(row[f"used{index}"]) is None:
            bar_width = max(10, inner - 14)
            lines.append(f"{row[f'p{index}']:<8}{DIM}{'·' * bar_width} {'—':>6}{RESET}")
            lines.append(f"{DIM}{'':8}not included in this plan{RESET}")
            continue
        bar, label, color = meter(row[f"used{index}"], max(10, inner - 14))
        lines.append(f"{row[f'p{index}']:<8}{bar} {color}{label:>6}{RESET}")
        lines.append(f"{DIM}{'':8}resets {row[f'reset{index}']}{RESET}")
    return lines


def dashboard(rows):
    terminal = shutil.get_terminal_size((100, 28)).columns
    width = max(48, min(118, terminal - 2))
    gap = 3
    columns = 2 if width >= 84 and len(rows) > 1 else 1
    card_width = (width - gap * (columns - 1)) // columns
    cards = [card(row, card_width) for row in rows]
    print()
    print(f"  {BOLD}NOVANODE{RESET}  {DIM}usage control center · live plan windows{RESET}")
    print(f"  {ORANGE}{'─' * width}{RESET}")
    print()
    if not rows:
        print(f"  {BOLD}No connected providers{RESET}")
        print(f"  {DIM}Run `usage connect` to add OpenAI or Claude with browser sign-in.{RESET}")
        print(f"  {DIM}Disconnected and removed sessions never appear in usage totals.{RESET}")
        print()
        return
    for offset in range(0, len(cards), columns):
        group = cards[offset:offset + columns]
        height = max(len(item) for item in group)
        for line_index in range(height):
            rendered = []
            for item in group:
                line = item[line_index] if line_index < len(item) else ""
                rendered.append(line + " " * max(0, card_width - visible(line)))
            print("  " + (" " * gap).join(rendered))
        if offset + columns < len(cards):
            print()
    values = [usage.pct_num(row[key]) for row in rows for key in ("used1", "used2")]
    values = [value for value in values if value is not None]
    average = sum(values) / len(values) if values else None
    total_bar, total_label, color = meter(average, max(20, width - 24))
    print()
    print(f"  {BOLD}Combined load{RESET}")
    print(f"  {total_bar} {color}{total_label}{RESET}")
    reporting = sum(
        1 for row in rows
        if any(usage.pct_num(row[key]) is not None for key in ("used1", "used2"))
    )
    count = len(rows)
    reporting_label = f" · {reporting} reporting live usage" if reporting != count else ""
    print(f"  {DIM}{count} connected profile{'s' if count != 1 else ''}{reporting_label}{RESET}")
    print(f"  {DIM}Add another with `usage connect`{RESET}")
    print()


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv and argv[0] in ("-h", "--help"):
        help_text()
        return 0
    if argv and argv[0] in ("-v", "--version"):
        print(VERSION)
        return 0
    if argv and argv[0] == "connect":
        return usage_connect.main(argv[1:])
    if argv and argv[0] not in ("--summary-tsv", "--json", "--classic"):
        print(f"nn-usage: unknown option {argv[0]}", file=sys.stderr)
        return 2
    classic = argv == ["--classic"]
    if argv == ["--summary-tsv"]:
        summary_tsv(usage.fetch_usage())
        return 0
    if argv == ["--json"]:
        print(json.dumps(usage.fetch_usage(), indent=2))
        return 0
    if not classic and not argv and sys.stdin.isatty() and sys.stdout.isatty():
        try:
            from ui.app_hub import NovaHubApp
        except ImportError:
            dashboard(usage.fetch_usage())
            return 0
        app = NovaHubApp()
        app._initial_target = "usage"
        app.run()
        return 0
    dashboard(usage.fetch_usage())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
