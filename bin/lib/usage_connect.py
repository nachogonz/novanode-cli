"""Interactive provider connection hub for ``usage connect``."""

import os
import re
import shutil
import sys
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime

import usage_accounts


GREEN = "\033[38;5;82m"
ORANGE = "\033[38;5;208m"
CYAN = "\033[38;5;51m"
RED = "\033[38;5;196m"
DIM = "\033[38;5;245m"
BOLD = "\033[1m"
RESET = "\033[0m"
ANSI = re.compile(r"\033\[[0-9;]*m")


def color(value):
    if not sys.stdout.isatty() or os.environ.get("NO_COLOR") is not None:
        return ""
    return value


def visible(value):
    return len(ANSI.sub("", value))


def clip(value, width):
    if visible(value) <= width:
        return value
    output = []
    shown = 0
    index = 0
    while index < len(value) and shown < max(0, width - 1):
        match = ANSI.match(value, index)
        if match:
            output.append(match.group(0))
            index = match.end()
            continue
        output.append(value[index])
        shown += 1
        index += 1
    output.append("…")
    output.append(color(RESET))
    return "".join(output)


def pad(value, width):
    value = clip(value, width)
    return value + " " * max(0, width - visible(value))


def statuses(accounts):
    if not accounts:
        return {}
    with ThreadPoolExecutor(max_workers=min(6, len(accounts))) as pool:
        futures = {pool.submit(usage_accounts.connection_status, account): account["id"] for account in accounts}
        return {account_id: future.result() for future, account_id in futures.items()}


def render(clear=False, message=""):
    accounts = usage_accounts.all_accounts()
    state = statuses(accounts)
    try:
        usage_accounts.record_statuses(accounts, state)
    except OSError:
        pass
    terminal = shutil.get_terminal_size((92, 28)).columns
    width = max(66, min(92, terminal - 2))
    inner = width - 4
    orange, green, cyan, red, dim, bold, reset = map(
        color, (ORANGE, GREEN, CYAN, RED, DIM, BOLD, RESET)
    )
    if clear and sys.stdout.isatty():
        print("\033[2J\033[H", end="")

    def border(left, fill, right):
        print(f"  {orange}{left}{fill * (width - 2)}{right}{reset}")

    def line(value=""):
        print(f"  {orange}│{reset} {pad(value, inner)} {orange}│{reset}")

    border("╭", "─", "╮")
    line(f"{bold}NOVANODE{reset}  {orange}// CONNECTION HUB{reset}")
    line(f"{dim}One calm dashboard. Provider-owned credentials. Live plan windows.{reset}")
    border("├", "─", "┤")

    descriptions = {
        "openai": "ChatGPT browser sign-in · Codex rate windows",
        "claude": "Claude browser sign-in · Pro / Max plan windows",
    }
    for provider in ("openai", "claude"):
        title = usage_accounts.PROVIDERS[provider]["title"]
        provider_accounts = [account for account in accounts if account["provider"] == provider]
        connected = sum(1 for account in provider_accounts if state[account["id"]]["connected"])
        badge = f"{green}● {connected} connected{reset}" if connected else f"{dim}○ ready to connect{reset}"
        line(f"{bold}{title:<26}{reset}{badge}")
        line(f"{dim}{descriptions[provider]}{reset}")
        for account in provider_accounts:
            current = state[account["id"]]
            dot = f"{green}●{reset}" if current["connected"] else f"{dim}○{reset}"
            kind = "system" if not account.get("managed") else "profile"
            detail_color = green if current["connected"] else dim
            label = account["label"][:18]
            version = current.get("version") or account.get("cli_version")
            version_label = f" · v{version}" if version else ""
            line(
                f"  {dot} {label:<18} {dim}{kind:<8}{reset} "
                f"{detail_color}{current['detail']}{version_label}{reset}"
            )
        line()

    border("├", "─", "┤")
    line(
        f"{cyan}[O]{reset} OpenAI  {cyan}[C]{reset} Claude  {cyan}[M]{reset} Sessions  "
        f"{cyan}[R]{reset} Refresh  {cyan}[Q]{reset} Done"
    )
    if message:
        line(f"{green if not message.lower().startswith('error') else red}{message}{reset}")
    else:
        line(f"{dim}Tokens never enter NovaNode's account registry.{reset}")
    border("╰", "─", "╯")
    return state


def compact_date(value):
    if not value:
        return "never"
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00")).astimezone().strftime("%d %b %H:%M")
    except (TypeError, ValueError):
        return "unknown"


def manage_profiles():
    accounts = usage_accounts.all_accounts()
    state = statuses(accounts)
    accounts = [
        account for account in accounts
        if account.get("managed") or state[account["id"]]["connected"]
    ]
    if not accounts:
        return "No connected or managed sessions"
    try:
        usage_accounts.record_statuses(accounts, state)
    except OSError:
        pass

    orange, green, cyan, red, dim, bold, reset = map(
        color, (ORANGE, GREEN, CYAN, RED, DIM, BOLD, RESET)
    )
    terminal = shutil.get_terminal_size((88, 28)).columns
    width = max(44, min(88, terminal - 4))

    def manage_line(value=""):
        print(f"  {pad(value, width)}")

    if sys.stdout.isatty():
        print("\033[2J\033[H", end="")
    manage_line(f"{bold}NOVANODE{reset}  {orange}// SESSIONS{reset}")
    manage_line(f"{orange}{'─' * width}{reset}")
    manage_line(f"{dim}Log out system accounts or delete isolated profiles.{reset}")
    print()
    for index, account in enumerate(accounts, 1):
        current = state[account["id"]]
        dot = f"{green}● connected{reset}" if current["connected"] else f"{dim}○ disconnected{reset}"
        title = usage_accounts.PROVIDERS[account["provider"]]["title"]
        live_version = current.get("version") or "not detected"
        saved_version = account.get("cli_version")
        login_version = f"v{saved_version}" if saved_version else "version unknown"
        seen_version = account.get("last_seen_version")
        seen_label = compact_date(account.get("last_seen_at"))
        if seen_version:
            seen_label += f" on v{seen_version}"
        kind = "isolated profile" if account.get("managed") else "system account"
        manage_line(f"{cyan}[{index}]{reset} {bold}{title} · {account['label']}{reset}")
        manage_line(f"    {dot} · {kind} · now v{live_version}")
        if account.get("managed"):
            manage_line(
                f"    {dim}login {compact_date(account.get('connected_at'))} with {login_version}{reset}"
            )
            manage_line(f"    {dim}last seen {seen_label}{reset}")
        else:
            manage_line(f"    {dim}logout keeps provider settings and local history{reset}")
        print()
    manage_line(f"{cyan}[B]{reset} Back without changes")

    try:
        choice = input("\n  Session to manage: ").strip().lower()
    except (EOFError, KeyboardInterrupt):
        return "No sessions changed"
    if choice in ("", "b", "back", "q"):
        return "No sessions changed"
    try:
        account = accounts[int(choice) - 1]
    except (ValueError, IndexError):
        return "Error: choose a session number or B"

    title = usage_accounts.PROVIDERS[account["provider"]]["title"]
    if not account.get("managed"):
        print(f"\n  {red}{bold}Log out {title} · Default?{reset}")
        print(f"  {dim}Credentials are cleared; local settings and conversation history remain.{reset}")
        try:
            confirmed = input("  Type logout to confirm: ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            return "No sessions changed"
        if confirmed != "logout":
            return "No sessions changed"
        ok, detail = usage_accounts.logout_default_account(account["id"])
        return detail if ok else f"Error: {detail}"

    print(f"\n  {red}{bold}Remove {title} · {account['label']}?{reset}")
    print(f"  {dim}This signs out and deletes only this NovaNode-managed profile directory.{reset}")
    try:
        confirmed = input("  Type delete to confirm: ").strip().lower()
    except (EOFError, KeyboardInterrupt):
        return "No sessions changed"
    if confirmed != "delete":
        return "No sessions changed"
    ok, detail = usage_accounts.remove_account(account["id"])
    return detail if ok else f"Error: {detail}"


def next_label(provider):
    used = {row["slug"] for row in usage_accounts.load_accounts() if row["provider"] == provider}
    for label in ("Personal", "Work", "Account 2", "Account 3"):
        if usage_accounts.slugify(label) not in used:
            return label
    return f"Account {len(used) + 1}"


def connect(provider, label=None):
    title = usage_accounts.PROVIDERS[provider]["title"]
    if label is None:
        suggested = next_label(provider)
        try:
            entered = input(f"\n  Profile name [{suggested}]: ").strip()
        except EOFError:
            return False, "Error: profile name was not provided"
        label = entered or suggested
    account = usage_accounts.account_for(provider, label)
    print()
    print(f"  {color(BOLD)}Connecting {title} · {account['label']}{color(RESET)}")
    print(f"  {color(DIM)}Your provider will open the browser and keep the credential.{color(RESET)}")
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
Use Manage sessions to sign out and remove a named profile and its local data.
""")


def main(argv=None):
    argv = list(argv or [])
    if argv and argv[0] in ("-h", "--help", "help"):
        help_text()
        return 0
    if argv and argv[0] == "--status":
        render()
        return 0
    if argv and argv[0] == "manage":
        if not sys.stdin.isatty() or not sys.stdout.isatty():
            print("usage connect manage requires an interactive terminal", file=sys.stderr)
            return 2
        message = manage_profiles()
        render(clear=True, message=message)
        return 1 if message.startswith("Error") else 0
    if argv and argv[0] in ("openai", "claude"):
        provider = argv[0]
        label = " ".join(argv[1:]).strip() or None
        ok, message = connect(provider, label)
        render(message=message)
        return 0 if ok else 1
    if argv:
        print(f"usage connect: unknown option {' '.join(argv)}", file=sys.stderr)
        return 2
    if not sys.stdin.isatty() or not sys.stdout.isatty():
        render()
        print("\nRun `usage connect openai personal` or `usage connect claude personal` to sign in.")
        return 0

    message = ""
    while True:
        render(clear=True, message=message)
        message = ""
        try:
            choice = input("\n  Choose a provider: ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            print()
            return 0
        if choice in ("q", "quit", "done", ""):
            return 0
        if choice in ("r", "refresh"):
            continue
        if choice in ("m", "manage", "sessions"):
            message = manage_profiles()
            continue
        if choice in ("o", "openai", "1"):
            _, message = connect("openai")
        elif choice in ("c", "claude", "2"):
            _, message = connect("claude")
        else:
            message = "Error: choose O, C, M, R, or Q"
        try:
            input("\n  Press Enter to continue…")
        except (EOFError, KeyboardInterrupt):
            return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
