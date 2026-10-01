"""Interactive provider connection hub for ``usage connect``.

Interactive TTY sessions use the arrow-key menu framework in tuimenu.py.
Non-interactive callers (pipes, `--status`, direct-connect subcommands) get
a plain text render so scripts and CI still work.
"""

import os
import re
import shutil
import sys
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime

import tuimenu
import usage_accounts
from tuimenu import (
    BOLD, CYAN, DIM, GREEN, ORANGE, RED, RESET, YELLOW, paint, Item, Menu,
    confirm, prompt,
)


ANSI = re.compile(r"\033\[[0-9;]*m")


def visible(value):
    return len(ANSI.sub("", value))


def statuses(accounts):
    if not accounts:
        return {}
    with ThreadPoolExecutor(max_workers=min(6, len(accounts))) as pool:
        futures = {pool.submit(usage_accounts.connection_status, account): account["id"]
                   for account in accounts}
        return {account_id: future.result() for future, account_id in futures.items()}


def compact_date(value):
    if not value:
        return "never"
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00")).astimezone().strftime("%d %b %H:%M")
    except (TypeError, ValueError):
        return "unknown"


# ─────────────────────────────────────────────────────────────────────────────
# Static (non-interactive) render — used by `--status` and non-TTY callers.
# ─────────────────────────────────────────────────────────────────────────────

def static_status(message=""):
    accounts = usage_accounts.all_accounts()
    shadowed = usage_accounts.shadowed_claude_ids(accounts)
    state = statuses(accounts)
    try:
        usage_accounts.record_statuses(accounts, state)
    except OSError:
        pass

    terminal = shutil.get_terminal_size((92, 28)).columns
    width = max(66, min(92, terminal - 2))

    def line(value=""):
        print(f"  {paint('│', ORANGE)} {value.ljust(width - 4)} {paint('│', ORANGE)}")

    def border(left, right):
        print(f"  {paint(left + '─' * (width - 2) + right, ORANGE)}")

    border("╭", "╮")
    line(f"{paint('NOVANODE', BOLD)}  {paint('// CONNECTION HUB', ORANGE)}")
    line(paint("One calm dashboard. Provider-owned credentials. Live plan windows.", DIM))
    border("├", "┤")

    descriptions = {
        "openai": "ChatGPT browser sign-in · Codex rate windows",
        "claude": "Claude browser sign-in · Pro / Max plan windows",
    }
    for provider in ("openai", "claude"):
        title = usage_accounts.PROVIDERS[provider]["title"]
        provider_accounts = [a for a in accounts if a["provider"] == provider]
        connected = sum(1 for a in provider_accounts if state[a["id"]]["connected"])
        badge = paint(f"● {connected} connected", GREEN) if connected else paint("○ ready to connect", DIM)
        line(f"{paint(title.ljust(26), BOLD)}{badge}")
        line(paint(descriptions[provider], DIM))
        if not provider_accounts:
            line(f"  {paint('○ no profiles yet', DIM)}")
        for a in provider_accounts:
            current = state[a["id"]]
            is_shadowed = a["id"] in shadowed
            if is_shadowed:
                dot, detail_color, status_text = paint("◌", DIM), DIM, "shadowed — remove from Sessions"
            else:
                dot = paint("●", GREEN) if current["connected"] else paint("○", DIM)
                detail_color = GREEN if current["connected"] else DIM
                status_text = current["detail"]
            version = current.get("version") or a.get("cli_version")
            version_label = f" · v{version}" if version and not is_shadowed else ""
            line(f"  {dot} {a['label'][:22].ljust(22)} {paint(status_text + version_label, detail_color)}")
        line()
    border("├", "┤")
    line(f"{paint('usage connect', CYAN)}         open the interactive hub")
    line(f"{paint('usage connect manage', CYAN)}  review / remove sessions")
    if message:
        line(message)
    else:
        line(paint("Tokens never enter NovaNode's account registry.", DIM))
    border("╰", "╯")


# ─────────────────────────────────────────────────────────────────────────────
# Interactive TUI — arrow-key hub, sessions, and profile detail.
# ─────────────────────────────────────────────────────────────────────────────

def next_label(provider):
    used = {row["slug"] for row in usage_accounts.load_accounts() if row["provider"] == provider}
    for label in ("Personal", "Work", "Account 2", "Account 3"):
        if usage_accounts.slugify(label) not in used:
            return label
    return f"Account {len(used) + 1}"


def build_hub_items(accounts, state, shadowed):
    items = []
    for provider in ("openai", "claude"):
        title = usage_accounts.PROVIDERS[provider]["title"]
        provider_accounts = [a for a in accounts if a["provider"] == provider]
        connected = sum(1 for a in provider_accounts if state[a["id"]]["connected"])
        badge = f"● {connected} connected" if connected else "○ ready to connect"
        items.append(Item(
            label=f"{title:<24}{badge}",
            heading=True,
            subtitle=("ChatGPT browser sign-in · Codex rate windows"
                      if provider == "openai" else
                      "Claude browser sign-in · Pro / Max plan windows"),
        ))
        for a in provider_accounts:
            current = state[a["id"]]
            is_shadowed = a["id"] in shadowed
            if is_shadowed:
                dot, subtitle, badge_color = "◌", "shadowed — remove from Sessions", DIM
            else:
                dot = "●" if current["connected"] else "○"
                subtitle = current["detail"]
                version = current.get("version") or a.get("cli_version")
                if version:
                    subtitle = f"{subtitle} · v{version}"
                badge_color = GREEN if current["connected"] else DIM
            items.append(Item(
                label=f"{dot} {a['label']}",
                value=("profile", a["id"]),
                subtitle=subtitle,
                badge=None,
            ))
        items.append(Item(
            label=f"+ Add {title.split(' /')[0]} profile",
            value=("add", provider),
            subtitle="Browser sign-in · new isolated profile",
        ))
        items.append(Item(divider=True))
    items.append(Item(
        label="Sessions",
        value=("sessions", None),
        subtitle="Review last-seen versions and remove old profiles",
    ))
    items.append(Item(
        label="Refresh",
        value=("refresh", None),
        subtitle="Re-read status from Codex and Claude CLIs",
    ))
    items.append(Item(
        label="Quit",
        value=("quit", None),
    ))
    return items


def interactive_hub():
    """Arrow-key hub. Loops until the user quits."""
    message = ""
    while True:
        accounts = usage_accounts.all_accounts()
        shadowed = usage_accounts.shadowed_claude_ids(accounts)
        state = statuses(accounts)
        try:
            usage_accounts.record_statuses(accounts, state)
        except OSError:
            pass
        items = build_hub_items(accounts, state, shadowed)
        menu = Menu(
            title="NOVANODE  ·  Connection hub",
            subtitle="Provider-owned credentials · live plan windows",
            items=items,
            footer="↑↓ navigate · Enter select · Q quit · R refresh",
            message=message,
            hotkeys={"r": ("refresh", None), "s": ("sessions", None)},
        )
        message = ""
        choice = menu.run()
        if choice is None or (isinstance(choice, tuple) and choice[0] == "quit"):
            return
        kind, payload = choice
        if kind == "refresh":
            continue
        if kind == "add":
            ok, note = flow_add_profile(payload)
            message = paint(note, GREEN if ok else RED)
            continue
        if kind == "profile":
            account = next((a for a in accounts if a["id"] == payload), None)
            if account:
                note = flow_profile_actions(account, state.get(payload, {}), payload in shadowed)
                if note:
                    message = note
            continue
        if kind == "sessions":
            note = interactive_sessions()
            if note:
                message = note
            continue


def flow_add_profile(provider):
    title = usage_accounts.PROVIDERS[provider]["title"]
    if provider == "claude" and sys.platform == "darwin":
        existing = [row for row in usage_accounts.load_accounts() if row["provider"] == "claude"]
        if existing:
            tuimenu.clear_screen()
            print()
            print(f"  {paint('Heads up:', YELLOW)} Claude Code on macOS keeps one system-wide")
            print(f"  Keychain entry per user, so a new sign-in replaces the previous")
            print(f"  Claude credential. Existing profile(s): "
                  f"{paint(', '.join(row['label'] for row in existing), BOLD)}")
            print(f"  will stop reporting live usage until you sign in as that account again.")
            print()
            try:
                if input("  Continue? [y/N] ").strip().lower() not in ("y", "yes"):
                    return False, f"Skipped {title} sign-in"
            except (EOFError, KeyboardInterrupt):
                return False, f"Skipped {title} sign-in"
    suggested = next_label(provider)
    label = prompt("Profile name", default=suggested)
    if not label:
        return False, f"Skipped {title} sign-in"
    account = usage_accounts.account_for(provider, label)
    tuimenu.clear_screen()
    print()
    print(f"  {paint(f'Connecting {title} · {account['label']}', BOLD)}")
    print(f"  {paint('Your provider will open the browser and keep the credential.', DIM)}")
    print()
    ok, detail = usage_accounts.connect_account(account)
    if ok:
        return True, f"Connected {title} · {account['label']}"
    return False, f"Error: {detail}"


def flow_profile_actions(account, current, is_shadowed):
    title = usage_accounts.PROVIDERS[account["provider"]]["title"]
    connected_at = compact_date(account.get("connected_at"))
    last_seen = compact_date(account.get("last_seen_at"))
    cli_version = account.get("cli_version") or "unknown"
    last_version = account.get("last_seen_version") or cli_version
    dot = "◌" if is_shadowed else ("●" if current.get("connected") else "○")
    detail = current.get("detail") or "unknown"
    if is_shadowed:
        detail = "shadowed by newer Claude profile"
    items = [
        Item(label=f"{dot} {title} · {account['label']}", heading=True,
             subtitle=detail),
        Item(divider=True),
        Item(label="Reconnect", value="reconnect",
             subtitle="Re-run browser sign-in for this profile"),
        Item(label="Delete", value="delete",
             subtitle="Remove this profile and its isolated login"),
        Item(divider=True),
        Item(label="Back", value="back"),
    ]
    menu = Menu(
        title=f"Profile · {account['label']}",
        subtitle=(f"login {connected_at} on v{cli_version}  ·  "
                  f"last seen {last_seen} on v{last_version}"),
        items=items,
        footer="↑↓ navigate · Enter select · Esc back",
    )
    choice = menu.run()
    if choice == "reconnect":
        tuimenu.clear_screen()
        print()
        print(f"  {paint(f'Reconnecting {title} · {account['label']}', BOLD)}")
        print()
        ok, detail = usage_accounts.connect_account(account)
        return paint(f"Connected {title} · {account['label']}" if ok else f"Error: {detail}",
                     GREEN if ok else RED)
    if choice == "delete":
        if not confirm(f"Remove {title} · {account['label']}?", danger_word="delete"):
            return paint("No sessions changed", DIM)
        ok, detail = usage_accounts.remove_account(account["id"])
        return paint(detail if ok else f"Error: {detail}", GREEN if ok else RED)
    return None


def interactive_sessions():
    """Arrow-key sessions list; D deletes the highlighted profile."""
    while True:
        accounts = usage_accounts.load_accounts()
        if not accounts:
            tuimenu.clear_screen()
            print()
            print(f"  {paint('No profiles yet', BOLD)}")
            print(f"  {paint('Return to the hub and press Add to sign in.', DIM)}")
            print()
            try:
                input("  Press Enter to return… ")
            except (EOFError, KeyboardInterrupt):
                pass
            return None
        shadowed = usage_accounts.shadowed_claude_ids(accounts)
        state = statuses(accounts)
        try:
            usage_accounts.record_statuses(accounts, state)
        except OSError:
            pass
        items = []
        for a in accounts:
            current = state[a["id"]]
            title = usage_accounts.PROVIDERS[a["provider"]]["title"]
            is_shadowed = a["id"] in shadowed
            if is_shadowed:
                dot, detail = "◌", "shadowed by newer Claude profile"
            else:
                dot = "●" if current["connected"] else "○"
                detail = current["detail"]
            version = current.get("version") or a.get("cli_version") or "?"
            last_seen = compact_date(a.get("last_seen_at"))
            items.append(Item(
                label=f"{dot} {title} · {a['label']}",
                value=a["id"],
                subtitle=f"{detail} · v{version}  ·  last seen {last_seen}",
            ))
        items.append(Item(divider=True))
        items.append(Item(label="Back to hub", value="__back__"))
        menu = Menu(
            title="Sessions",
            subtitle="Enter opens actions · D deletes the selected profile",
            items=items,
            footer="↑↓ navigate · Enter actions · D delete · Esc back",
            hotkeys={"d": "__delete__"},
        )
        choice = menu.run()
        if choice is None or choice == "__back__":
            return None
        if choice == "__delete__":
            account_id = items[menu.selected].value
            account = next((a for a in accounts if a["id"] == account_id), None)
            if not account:
                continue
            title = usage_accounts.PROVIDERS[account["provider"]]["title"]
            if not confirm(f"Remove {title} · {account['label']}?", danger_word="delete"):
                continue
            ok, detail = usage_accounts.remove_account(account_id)
            if not ok:
                return paint(f"Error: {detail}", RED)
            continue
        account = next((a for a in accounts if a["id"] == choice), None)
        if not account:
            continue
        flow_profile_actions(account, state.get(choice, {}), choice in shadowed)


# ─────────────────────────────────────────────────────────────────────────────
# Direct sub-commands (non-interactive) kept for scripts and shortcuts.
# ─────────────────────────────────────────────────────────────────────────────

def connect(provider, label=None):
    title = usage_accounts.PROVIDERS[provider]["title"]
    if provider == "claude" and sys.platform == "darwin":
        existing = [row for row in usage_accounts.load_accounts() if row["provider"] == "claude"]
        if existing:
            print()
            print(f"  {paint('Heads up:', YELLOW)} Claude Code on macOS keeps one system-wide")
            print(f"  Keychain entry per user, so a new sign-in replaces the previous")
            print(f"  Claude credential. Existing profile(s): "
                  f"{', '.join(row['label'] for row in existing)}")
            print(f"  will stop reporting live usage until you sign in as that account again.")
    if label is None:
        suggested = next_label(provider)
        try:
            entered = input(f"\n  Profile name [{suggested}]: ").strip()
        except EOFError:
            return False, "Error: profile name was not provided"
        label = entered or suggested
    account = usage_accounts.account_for(provider, label)
    print()
    print(f"  {paint(f'Connecting {title} · {account['label']}', BOLD)}")
    print(f"  {paint('Your provider will open the browser and keep the credential.', DIM)}")
    print()
    ok, detail = usage_accounts.connect_account(account)
    if ok:
        return True, f"Connected {title} · {account['label']}"
    return False, f"Error: {detail}"


def help_text():
    print("""usage connect

Connect plan accounts through the official provider login flows.

Usage:
  usage connect
  usage connect --status
  usage connect manage
  usage connect openai [profile-name]
  usage connect claude [profile-name]

Named accounts use isolated CODEX_HOME or CLAUDE_CONFIG_DIR directories.
NovaNode stores profile metadata only, never passwords or OAuth tokens.
Use Sessions to sign out and remove a named profile and its local data.
""")


def main(argv=None):
    argv = list(argv or [])
    if argv and argv[0] in ("-h", "--help", "help"):
        help_text()
        return 0
    if argv and argv[0] == "--status":
        static_status()
        return 0
    if argv and argv[0] == "manage":
        if not tuimenu.is_tty():
            static_status("Run `usage connect manage` in an interactive terminal.")
            return 2
        interactive_sessions()
        return 0
    if argv and argv[0] in ("openai", "claude"):
        provider = argv[0]
        label = " ".join(argv[1:]).strip() or None
        ok, message = connect(provider, label)
        print()
        print(f"  {paint(message, GREEN if ok else RED)}")
        return 0 if ok else 1
    if argv:
        print(f"usage connect: unknown option {' '.join(argv)}", file=sys.stderr)
        return 2

    if not tuimenu.is_tty():
        static_status()
        print()
        print("Run `usage connect openai personal` or `usage connect claude personal` to sign in.")
        return 0
    try:
        from ui.app_hub import NovaHubApp
        from ui.screens.connect import ConnectScreen
    except ImportError:
        interactive_hub()
        return 0
    app = NovaHubApp()
    app._initial_target = "connect"
    app.run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
