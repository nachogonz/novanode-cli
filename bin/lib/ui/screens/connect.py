"""NovaNode Connect — Textual port of the `usage connect` hub.

Replaces the legacy orange tuimenu UI (bin/lib/usage_connect.py:interactive_hub)
with the same black NovaNode look used by the Secrets and Usage screens. All
provider flows (add, reconnect, delete) share the same mini-CLI panel the
nn-op env flows use, so you never leave this UI.
"""

import os
import re
import subprocess
import sys

from textual import work
from textual.app import ComposeResult
from textual.containers import VerticalScroll
from textual.screen import Screen
from textual.widgets import Input, Static

import usage_accounts
import usage_connect
from ..components import NovaAction, NovaFooter, NovaHeader


ANSI = re.compile(r"\033\[[0-9;]*m")


class ConnectScreen(Screen):
    """Provider connection hub (OpenAI / Codex, Anthropic / Claude)."""

    BINDINGS = [
        ("up", "previous", "Previous"), ("down", "next", "Next"),
        ("tab", "next", "Next"), ("shift+tab", "previous", "Previous"),
        ("enter", "activate", "Select"), ("space", "activate", "Select"),
        ("r", "refresh", "Refresh"), ("s", "sessions", "Sessions"),
        ("q", "quit", "Quit"), ("escape", "quit", "Quit"),
    ]
    DEFAULT_CSS = """
    ConnectScreen { layout: vertical; }
    #connect-content { height: 1fr; padding: 1 2; }
    #connect-content Static { height: auto; }
    #connect-content NovaAction {
        width: 100%;
        min-height: 3;
        padding: 1 2;
        margin: 0 0 1 0;
        background: #0D110E;
        border-left: heavy #242A25;
    }
    #connect-content NovaAction:hover {
        background: #121713;
        border-left: heavy #50C900;
    }
    #connect-content NovaAction:focus {
        background: #121713;
        border-left: heavy #75FF00;
    }
    #connect-content NovaActionLabel { text-style: bold; }
    .section-title { color: #50C900; text-style: bold; margin: 1 0 1 0; }
    .provider-sub { color: #9AA39C; margin-bottom: 1; }
    .tagline { color: #626A64; margin-bottom: 1; }
    .message { color: #75FF00; margin-bottom: 1; }
    .message-error { color: #FF3B30; margin-bottom: 1; }
    """

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._choices = {}
        self._rows = []
        self._message = ""
        self._message_ok = True
        self._generation = 0

    def compose(self) -> ComposeResult:
        yield NovaHeader("NOVANODE", "/ CONNECT")
        yield VerticalScroll(id="connect-content")
        yield NovaFooter([("↑↓", "Navigate"), ("Enter", "Open"),
                          ("S", "Sessions"), ("R", "Refresh"), ("Q", "Back")])

    def on_mount(self) -> None:
        self.refresh_menu()

    def _add(self, container, label, action_id, description="", shortcut=""):
        key = f"row-{self._generation}-{len(self._rows)}"
        self._choices[key] = action_id
        row = NovaAction(label, key, shortcut=shortcut, description=description)
        self._rows.append(row)
        container.mount(row)

    def _heading(self, container, text):
        container.mount(Static(text, classes="section-title"))

    def refresh_menu(self, message: str = "", ok: bool = True) -> None:
        container = self.query_one("#connect-content", VerticalScroll)
        self._generation += 1
        container.remove_children()
        self._choices, self._rows = {}, []
        container.mount(Static("Provider-owned credentials · live plan windows",
                               classes="tagline"))
        if message:
            container.mount(Static(message, classes="message" if ok else "message-error"))

        accounts = usage_accounts.all_accounts()
        shadowed = usage_accounts.shadowed_claude_ids(accounts)
        state = usage_connect.statuses(accounts)
        try:
            usage_accounts.record_statuses(accounts, state)
        except OSError:
            pass

        provider_blurbs = {
            "openai": "ChatGPT browser sign-in · Codex rate windows",
            "claude": "Claude browser sign-in · Pro / Max plan windows",
        }
        for provider in ("openai", "claude"):
            title = usage_accounts.PROVIDERS[provider]["title"]
            provider_accounts = [a for a in accounts if a["provider"] == provider]
            connected = sum(1 for a in provider_accounts
                            if state[a["id"]]["connected"])
            badge = (f"{connected} CONNECTED" if connected
                     else "READY TO CONNECT")
            self._heading(container, f"{title}   ·   {badge}")
            container.mount(Static(provider_blurbs[provider],
                                   classes="provider-sub"))
            if not provider_accounts:
                container.mount(Static("No profiles yet · add one below",
                                       classes="provider-sub"))
            for account in provider_accounts:
                current = state[account["id"]]
                is_shadowed = account["id"] in shadowed
                dot = "◌" if is_shadowed else ("●" if current["connected"] else "○")
                if is_shadowed:
                    detail = "shadowed — remove from Sessions"
                else:
                    detail = current["detail"]
                    version = current.get("version") or account.get("cli_version")
                    if version:
                        detail = f"{detail} · v{version}"
                self._add(container, f"{dot} {account['label']}",
                          ("profile", account["id"]), detail)
            self._add(container, f"+ Add {title.split(' /')[0].strip()} profile",
                      ("add", provider), "Browser sign-in · new isolated profile")

        self._heading(container, "SESSIONS")
        self._add(container, "Review and remove profiles",
                  ("sessions", None),
                  "Last-seen versions, cleanups, forced sign-out",
                  shortcut="S")
        self._add(container, "Refresh", ("refresh", None),
                  "Re-read status from Codex and Claude CLIs", shortcut="R")

        self._heading(container, "SESSION")
        self._add(container, "Back to usage", ("quit", None), shortcut="Q")

        if self._rows:
            self.call_after_refresh(self._rows[0].focus)

    # ── events ────────────────────────────────────────────────────────

    def on_nova_action_activated(self, event: NovaAction.Activated) -> None:
        choice = self._choices.get(event.action_id)
        if not choice:
            return
        kind, payload = choice
        if kind == "quit":
            self._pop_or_exit()
        elif kind == "refresh":
            self.refresh_menu()
        elif kind == "sessions":
            self.app.push_screen(SessionsScreen(self))
        elif kind == "add":
            self.app.push_screen(ConnectActionScreen(self, ("add", payload)))
        elif kind == "profile":
            account = next((a for a in usage_accounts.all_accounts()
                            if a["id"] == payload), None)
            if account:
                self.app.push_screen(ProfileScreen(self, account))

    def action_previous(self) -> None:
        if not self._rows:
            return
        focused = self.app.focused
        index = self._rows.index(focused) if focused in self._rows else 0
        self._rows[(index - 1) % len(self._rows)].focus()

    def action_next(self) -> None:
        if not self._rows:
            return
        focused = self.app.focused
        index = self._rows.index(focused) if focused in self._rows else -1
        self._rows[(index + 1) % len(self._rows)].focus()

    def action_activate(self) -> None:
        focused = self.app.focused
        if isinstance(focused, NovaAction):
            focused.press()

    def action_refresh(self) -> None:
        self.refresh_menu()

    def action_sessions(self) -> None:
        self.app.push_screen(SessionsScreen(self))

    def action_quit(self) -> None:
        self._pop_or_exit()

    def _pop_or_exit(self) -> None:
        target = getattr(self.app, "_initial_target", "hub")
        if target == "hub" and len(self.app.screen_stack) > 1:
            self.app.pop_screen()
        else:
            self.app.exit()


# ─── Action screen (add / reconnect) ──────────────────────────────────


class ConnectActionScreen(Screen):
    """Collect a profile name and run the browser sign-in inline."""

    BINDINGS = [("escape", "back", "Back"),
                ("enter", "activate", "Submit"), ("space", "activate", "Submit")]
    DEFAULT_CSS = """
    ConnectActionScreen { layout: vertical; }
    #ca-content { height: 1fr; padding: 1 2; }
    #ca-content Static { height: auto; }
    #ca-content NovaAction {
        width: 100%; min-height: 3; padding: 1 2; margin: 1 0 0 0;
        background: #0D110E; border-left: heavy #242A25;
    }
    #ca-content NovaAction:hover {
        background: #121713; border-left: heavy #50C900;
    }
    #ca-content NovaAction:focus {
        background: #121713; border-left: heavy #75FF00;
    }
    #ca-content NovaActionLabel { text-style: bold; }
    #ca-content Input {
        margin: 1 0 0 0; background: #0D110E;
        border: tall #242A25; color: #E7ECE8;
    }
    #ca-content Input:focus { border: tall #75FF00; }
    .ca-title { color: #75FF00; text-style: bold; margin-top: 1; }
    .ca-note { color: #9AA39C; }
    .ca-output { margin-top: 1; padding: 1 2; background: #0D110E;
                 border: tall #242A25; }
    """

    def __init__(self, hub, choice, preset_account=None):
        super().__init__()
        self.hub = hub
        self.choice = choice
        self.preset_account = preset_account

    def compose(self) -> ComposeResult:
        yield NovaHeader("NOVANODE", "/ CONNECT")
        with VerticalScroll(id="ca-content"):
            kind, payload = self.choice
            if kind == "add":
                provider = payload
                title = usage_accounts.PROVIDERS[provider]["title"]
                yield Static(f"Add {title} profile", classes="ca-title")
                yield Static("A new browser sign-in opens in its own isolated profile.",
                             classes="ca-note")
                if provider == "claude" and sys.platform == "darwin":
                    existing = [row for row in usage_accounts.load_accounts()
                                if row["provider"] == "claude"]
                    if existing:
                        names = ", ".join(row["label"] for row in existing)
                        yield Static(
                            "Heads up: Claude Code on macOS keeps one system-wide "
                            "Keychain entry per user. Signing in here replaces the "
                            f"current credential for existing profile(s): {names}. "
                            "They stop reporting live usage until you sign back in.",
                            classes="ca-note")
                default_name = usage_connect.next_label(provider)
                yield Static("Profile name:", classes="ca-note")
                yield Input(value=default_name, id="input-profile",
                            placeholder="Personal / Work / …")
            elif kind == "reconnect":
                title = usage_accounts.PROVIDERS[self.preset_account["provider"]]["title"]
                yield Static(f"Reconnect {title} · {self.preset_account['label']}",
                             classes="ca-title")
                yield Static("Re-runs the official browser sign-in for this profile.",
                             classes="ca-note")
            yield NovaAction("Open browser & sign in", "ca-start",
                             shortcut="Enter")
            yield NovaAction("Back", "ca-back", shortcut="Esc")
        yield NovaFooter([("Enter", "Start"), ("Esc", "Back")])

    def on_mount(self) -> None:
        if self.choice[0] == "add":
            self.query_one("#input-profile", Input).focus()
        else:
            self.query_one("#action-ca-start", NovaAction).focus()

    def on_nova_action_activated(self, event: NovaAction.Activated) -> None:
        event.stop()
        if event.action_id == "ca-back":
            self.action_back()
        elif event.action_id == "ca-start":
            self.start()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        if event.input.id == "input-profile":
            self.start()

    def action_activate(self) -> None:
        focused = self.app.focused
        if isinstance(focused, NovaAction):
            focused.press()

    def action_back(self) -> None:
        self.app.pop_screen()

    def start(self) -> None:
        kind, payload = self.choice
        if kind == "add":
            try:
                name = (self.query_one("#input-profile", Input).value or "").strip()
            except Exception:
                name = ""
            if not name:
                name = usage_connect.next_label(payload)
            account = usage_accounts.account_for(payload, name)
        else:
            account = self.preset_account
        self._launch(account)

    def _launch(self, account) -> None:
        title = usage_accounts.PROVIDERS[account["provider"]]["title"]
        content = self.query_one("#ca-content", VerticalScroll)
        content.mount(Static(f"Opening browser for {title} · {account['label']} …",
                             classes="ca-output"))
        try:
            self.query_one("#action-ca-start", NovaAction).remove()
        except Exception:
            pass
        self._connect_worker(account)

    @work(thread=True, exclusive=True)
    def _connect_worker(self, account) -> None:
        try:
            with self.app.suspend():
                print()
                title = usage_accounts.PROVIDERS[account["provider"]]["title"]
                print(f"  NovaNode  /  Connect  ·  {title} · {account['label']}")
                print("  Your provider is opening a browser window — complete the sign-in there.")
                print()
                ok, detail = usage_accounts.connect_account(account)
                if ok:
                    print(f"\n  ✓ Connected {title} · {account['label']}")
                else:
                    print(f"\n  × {detail}")
                try:
                    input("  Press Enter to return to NovaNode… ")
                except (EOFError, KeyboardInterrupt):
                    pass
        except (KeyboardInterrupt, SystemExit):
            ok, detail = False, "cancelled"
        message = (f"Connected {title} · {account['label']}"
                   if ok else f"Error: {detail}")
        self.app.call_from_thread(self._finish, message, ok)

    def _finish(self, message: str, ok: bool) -> None:
        try:
            self.hub.refresh_menu(message=message, ok=ok)
        except Exception:
            pass
        self.app.pop_screen()


# ─── Profile screen (reconnect / delete) ──────────────────────────────


class ProfileScreen(Screen):
    BINDINGS = [("escape", "back", "Back"),
                ("enter", "activate", "Select"), ("space", "activate", "Select"),
                ("up", "previous", "Previous"), ("down", "next", "Next"),
                ("r", "reconnect", "Reconnect"), ("d", "delete", "Delete")]
    DEFAULT_CSS = """
    ProfileScreen { layout: vertical; }
    #pf-content { height: 1fr; padding: 1 2; }
    #pf-content Static { height: auto; }
    #pf-content NovaAction {
        width: 100%; min-height: 3; padding: 1 2; margin: 0 0 1 0;
        background: #0D110E; border-left: heavy #242A25;
    }
    #pf-content NovaAction:hover {
        background: #121713; border-left: heavy #50C900;
    }
    #pf-content NovaAction:focus {
        background: #121713; border-left: heavy #75FF00;
    }
    #pf-content NovaActionLabel { text-style: bold; }
    .pf-title { color: #75FF00; text-style: bold; margin-top: 1; }
    .pf-note { color: #9AA39C; }
    .pf-output { margin-top: 1; padding: 1 2; background: #0D110E;
                 border: tall #242A25; }
    """

    def __init__(self, hub, account):
        super().__init__()
        self.hub = hub
        self.account = account

    def compose(self) -> ComposeResult:
        title = usage_accounts.PROVIDERS[self.account["provider"]]["title"]
        yield NovaHeader("NOVANODE", "/ CONNECT")
        with VerticalScroll(id="pf-content"):
            yield Static(f"{title} · {self.account['label']}", classes="pf-title")
            yield Static(
                f"login {usage_connect.compact_date(self.account.get('connected_at'))}"
                f"  ·  last seen {usage_connect.compact_date(self.account.get('last_seen_at'))}",
                classes="pf-note")
            yield NovaAction("Reconnect", "pf-reconnect", shortcut="R",
                             description="Re-run the browser sign-in for this profile")
            yield NovaAction("Delete profile", "pf-delete", shortcut="D",
                             description="Remove this profile and its isolated login")
            yield NovaAction("Back", "pf-back", shortcut="Esc")
        yield NovaFooter([("R", "Reconnect"), ("D", "Delete"), ("Esc", "Back")])

    def on_mount(self) -> None:
        self.query_one("#action-pf-reconnect", NovaAction).focus()

    def on_nova_action_activated(self, event: NovaAction.Activated) -> None:
        event.stop()
        if event.action_id == "pf-back":
            self.action_back()
        elif event.action_id == "pf-reconnect":
            self.action_reconnect()
        elif event.action_id == "pf-delete":
            self.action_delete()

    def action_activate(self) -> None:
        focused = self.app.focused
        if isinstance(focused, NovaAction):
            focused.press()

    def action_previous(self) -> None:
        self.app.action_focus_previous()

    def action_next(self) -> None:
        self.app.action_focus_next()

    def action_reconnect(self) -> None:
        self.app.push_screen(
            ConnectActionScreen(self.hub, ("reconnect", None),
                                preset_account=self.account))
        self.app.pop_screen()

    def action_delete(self) -> None:
        ok, detail = usage_accounts.remove_account(self.account["id"])
        self.hub.refresh_menu(message=detail, ok=ok)
        self.app.pop_screen()

    def action_back(self) -> None:
        self.app.pop_screen()


# ─── Sessions list ───────────────────────────────────────────────────


class SessionsScreen(Screen):
    BINDINGS = [("escape", "back", "Back"),
                ("enter", "activate", "Select"), ("space", "activate", "Select"),
                ("up", "previous", "Previous"), ("down", "next", "Next"),
                ("d", "delete", "Delete")]
    DEFAULT_CSS = """
    SessionsScreen { layout: vertical; }
    #sess-content { height: 1fr; padding: 1 2; }
    #sess-content Static { height: auto; }
    #sess-content NovaAction {
        width: 100%; min-height: 3; padding: 1 2; margin: 0 0 1 0;
        background: #0D110E; border-left: heavy #242A25;
    }
    #sess-content NovaAction:hover {
        background: #121713; border-left: heavy #50C900;
    }
    #sess-content NovaAction:focus {
        background: #121713; border-left: heavy #75FF00;
    }
    #sess-content NovaActionLabel { text-style: bold; }
    .sess-title { color: #75FF00; text-style: bold; margin-top: 1; }
    .sess-note { color: #9AA39C; }
    """

    def __init__(self, hub):
        super().__init__()
        self.hub = hub
        self._rows = []
        self._choices = {}
        self._generation = 0

    def compose(self) -> ComposeResult:
        yield NovaHeader("NOVANODE", "/ SESSIONS")
        yield VerticalScroll(id="sess-content")
        yield NovaFooter([("↑↓", "Navigate"), ("Enter", "Actions"),
                          ("D", "Delete"), ("Esc", "Back")])

    def on_mount(self) -> None:
        self.render_rows()

    def render_rows(self) -> None:
        container = self.query_one("#sess-content", VerticalScroll)
        self._generation += 1
        container.remove_children()
        self._rows, self._choices = [], {}
        container.mount(Static("Review profiles, cleanups, forced sign-out.",
                               classes="sess-note"))
        accounts = usage_accounts.load_accounts()
        if not accounts:
            container.mount(Static("No profiles yet.", classes="sess-note"))
            self._add(container, "Back to hub", "back", shortcut="Esc")
            self.call_after_refresh(self._rows[0].focus)
            return
        shadowed = usage_accounts.shadowed_claude_ids(accounts)
        state = usage_connect.statuses(accounts)
        try:
            usage_accounts.record_statuses(accounts, state)
        except OSError:
            pass
        container.mount(Static("ACTIVE SESSIONS", classes="sess-title"))
        for account in accounts:
            current = state[account["id"]]
            is_shadowed = account["id"] in shadowed
            dot = "◌" if is_shadowed else ("●" if current["connected"] else "○")
            title = usage_accounts.PROVIDERS[account["provider"]]["title"]
            detail = "shadowed by newer Claude profile" if is_shadowed else current["detail"]
            version = current.get("version") or account.get("cli_version") or "?"
            last_seen = usage_connect.compact_date(account.get("last_seen_at"))
            description = f"{detail} · v{version} · last seen {last_seen}"
            self._add(container, f"{dot} {title} · {account['label']}",
                      ("profile", account["id"]), description)
        self._add(container, "Back to hub", "back", shortcut="Esc")
        if self._rows:
            self.call_after_refresh(self._rows[0].focus)

    def _add(self, container, label, action_id, shortcut="", description=""):
        key = f"srow-{self._generation}-{len(self._rows)}"
        self._choices[key] = action_id
        row = NovaAction(label, key, shortcut=shortcut, description=description)
        self._rows.append(row)
        container.mount(row)

    def on_nova_action_activated(self, event: NovaAction.Activated) -> None:
        choice = self._choices.get(event.action_id)
        if choice == "back":
            self.action_back()
        elif isinstance(choice, tuple) and choice[0] == "profile":
            account = next((a for a in usage_accounts.load_accounts()
                            if a["id"] == choice[1]), None)
            if account:
                self.app.push_screen(ProfileScreen(self.hub, account))

    def action_activate(self) -> None:
        focused = self.app.focused
        if isinstance(focused, NovaAction):
            focused.press()

    def action_previous(self) -> None:
        if not self._rows:
            return
        focused = self.app.focused
        index = self._rows.index(focused) if focused in self._rows else 0
        self._rows[(index - 1) % len(self._rows)].focus()

    def action_next(self) -> None:
        if not self._rows:
            return
        focused = self.app.focused
        index = self._rows.index(focused) if focused in self._rows else -1
        self._rows[(index + 1) % len(self._rows)].focus()

    def action_delete(self) -> None:
        focused = self.app.focused
        if focused not in self._rows:
            return
        choice = self._choices.get(focused._action_id)
        if not (isinstance(choice, tuple) and choice[0] == "profile"):
            return
        ok, detail = usage_accounts.remove_account(choice[1])
        self.render_rows()
        if ok:
            self.hub.refresh_menu(message=detail, ok=True)

    def action_back(self) -> None:
        self.app.pop_screen()
