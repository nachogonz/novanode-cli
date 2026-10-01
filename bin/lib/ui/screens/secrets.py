"""Textual controls over the existing nn-op menus and command dispatcher."""

import re
import subprocess
import sys

from textual.app import ComposeResult
from textual.containers import VerticalScroll
from textual.screen import Screen
from textual.widgets import Input, Static
from textual import work

import op
import op_cli
from ..components import NovaAction, NovaFooter, NovaHeader


class SecretsScreen(Screen):
    BINDINGS = [
        ("up", "previous", "Previous"), ("down", "next", "Next"),
        ("tab", "next", "Next"), ("shift+tab", "previous", "Previous"),
        ("enter", "activate", "Select"), ("space", "activate", "Select"),
        ("a", "add", "Add"), ("l", "login", "Sign in"),
        ("g", "init", "Initialize"), ("u", "use", "Switch"),
        ("p", "pull", "Pull"), ("i", "import_env", "Import"),
        ("t", "template", "Template"), ("c", "copy", "Copy"),
        ("o", "op_cli", "op CLI"), ("r", "refresh", "Refresh"),
        ("q", "quit", "Quit"), ("escape", "quit", "Quit"),
    ]
    DEFAULT_CSS = """
    SecretsScreen { layout: vertical; }
    #secrets-content { height: 1fr; padding: 1 2; }
    #secrets-content Static { height: auto; }
    #secrets-content NovaAction {
        width: 100%;
        min-height: 3;
        padding: 1 2;
        margin: 0 0 1 0;
        background: #0D110E;
        border-left: heavy #242A25;
    }
    #secrets-content NovaAction:hover {
        background: #121713;
        border-left: heavy #50C900;
    }
    #secrets-content NovaAction:focus {
        background: #121713;
        border-left: heavy #75FF00;
    }
    #secrets-content NovaActionLabel { text-style: bold; }
    .section-title { color: #50C900; text-style: bold; margin: 1 0 1 0; }
    .context { color: #9AA39C; }
    .dev-banner {
        color: #050706; background: #FFB000;
        text-style: bold; padding: 0 1; margin-bottom: 1;
    }
    """

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._choices = {}
        self._rows = []
        self._revealed = set()
        self._secrets = []
        self._generation = 0

    def compose(self) -> ComposeResult:
        import os as _os
        subtitle = "/ SECRETS · DEV" if _os.environ.get("NNOP_DEV") else "/ SECRETS"
        yield NovaHeader("NOVANODE", subtitle)
        yield VerticalScroll(id="secrets-content")
        yield NovaFooter([("↑↓", "Navigate"), ("Enter", "Select"),
                          ("A", "Add"), ("O", "op CLI"), ("Q", "Quit")])

    def on_mount(self) -> None:
        self.refresh_menu()

    def _add(self, container, label, choice, description="", shortcut=""):
        key = f"row-{self._generation}-{len(self._rows)}"
        self._choices[key] = choice
        row = NovaAction(label, key, shortcut=shortcut, description=description)
        self._rows.append(row)
        container.mount(row)

    def _heading(self, container, title):
        container.mount(Static(title, classes="section-title"))

    def refresh_menu(self, message=""):
        import os as _os
        container = self.query_one("#secrets-content", VerticalScroll)
        self._generation += 1
        container.remove_children()
        self._choices, self._rows, self._secrets = {}, [], []
        installed = op.installed()
        identity = op.whoami() if installed else None
        ctx = op_cli._context()
        if _os.environ.get("NNOP_DEV"):
            container.mount(Static(
                "DEV MODE · mock vault, no real 1Password · tmp folder "
                + _os.environ.get("NNOP_DEV_HOME", "/tmp/novanode-dev-op"),
                classes="dev-banner"))
        if message:
            container.mount(Static(message, classes="context"))
        if not identity:
            accounts = op.account_list() if installed else []
            container.mount(Static("○ SIGNED OUT" if installed else "× 1Password CLI not installed"))
            container.mount(Static("Provider-owned credentials · nothing stored by NovaNode",
                                   classes="context"))
            self._heading(container, "AUTHENTICATION")
            for item in op_cli._signed_out_items(accounts, installed):
                if not item.disabled:
                    kind, payload = item.value
                    shortcut = "A" if kind == "account-add" else ""
                    self._add(container, item.label, (kind, payload),
                              item.subtitle or "", shortcut)
        else:
            container.mount(Static(f"● CONNECTED  {identity.get('email') or identity.get('url') or '1Password'}"))
            if not ctx.project:
                self._heading(container, "WORKSPACE SETUP")
                for item in op_cli._workspace_setup_items():
                    if item.heading:
                        self._heading(container, item.label)
                    elif not item.disabled:
                        self._add(container, item.label, item.value, item.subtitle or "")
            else:
                location = f"{ctx.project} / {ctx.default_app or '?'} / {ctx.default_env or '?'}"
                container.mount(Static(location, classes="context"))
                title, env_rows = op_cli._envs_snapshot(ctx)
                self._heading(container, f"CURRENT ENVIRONMENT · {title or 'not selected'}")
                if env_rows is None:
                    container.mount(Static("No secrets yet · A adds the first one"))
                elif env_rows:
                    self._secrets = env_rows
                    for index, (name, value, concealed) in enumerate(env_rows):
                        display = "••••••••" if concealed and name not in self._revealed else value
                        self._add(container, name, ("secret", index), display)
                else:
                    container.mount(Static("No app/env selected or no variables yet"))
                sections = [
                    ("SECRETS", [("Add secret", ("add", None), "A"),
                                 ("Import a .env file", ("cmd", ["env", "import"]), "I"),
                                 ("Pull to .env", ("cmd", ["env", "pull", "--materialize"]), "P"),
                                 ("Write .env.template", ("cmd", ["env", "template", "--out", ".env.template"]), "T")]),
                    ("WORKSPACE", [("Switch app / environment", ("cmd", ["env", "use"]), "U"),
                                   ("Browse environments", ("cmd", ["env", "envs"]), ""),
                                   ("Run with secrets", ("cmd", ["env", "run"]), ""),
                                   ("Copy secrets between apps", ("cmd", ["env", "copy"]), "")]),
                    ("ACCESS & SHARING", [("Browse access items", ("cmd", ["access", "list"]), ""),
                                          ("Add access credentials", ("cmd", ["access", "add"]), ""),
                                          ("Share with client", ("cmd", ["share", "create"]), "")]),
                    ("SETTINGS", [("Project context", ("cmd", ["where"]), ""),
                                  ("Configured accounts", ("cmd", ["accounts"]), ""),
                                  ("Add another account", ("account-add", None), ""),
                                  ("Diagnostics", ("cmd", ["doctor"]), ""),
                                  ("Open op CLI session", ("op-cli", None), "O"),
                                  ("Sign out", ("cmd", ["logout"]), "")]),
                ]
                for heading, actions in sections:
                    self._heading(container, heading)
                    for label, choice, shortcut in actions:
                        self._add(container, label, choice, shortcut=shortcut)
            self._add(container, "Quit", ("quit", None), shortcut="Q")
        if self._rows:
            focus = next((row for row in self._rows
                          if self._choices[row._action_id][0] == "account-add"), self._rows[0]) if not identity and not accounts else self._rows[0]
            self.call_after_refresh(focus.focus)

    def on_nova_action_activated(self, event: NovaAction.Activated) -> None:
        self._run_choice(self._choices[event.action_id])

    def _run_choice(self, choice):
        kind, payload = choice
        if kind == "quit":
            self._exit_or_pop()
        elif kind == "op-cli":
            self._launch_op_cli()
        elif kind == "secret":
            name = self._secrets[payload][0]
            if name in self._revealed:
                self._revealed.remove(name)
            else:
                self._revealed.add(name)
            self.refresh_menu()
        elif kind in ("signin", "account-add", "cmd", "add", "install-help"):
            source = next((row for row in self._rows
                           if self._choices.get(row._action_id) == choice), None)
            label = source._label if source else "NovaNode action"
            description = source._description if source else ""
            self.app.push_screen(OpActionScreen(self, choice, label, description))

    def action_previous(self):
        if self._rows:
            current = self.app.focused
            index = self._rows.index(current) if current in self._rows else 0
            self._rows[(index - 1) % len(self._rows)].focus()

    def action_next(self):
        if self._rows:
            current = self.app.focused
            index = self._rows.index(current) if current in self._rows else -1
            self._rows[(index + 1) % len(self._rows)].focus()

    def action_activate(self):
        focused = self.app.focused
        if isinstance(focused, NovaAction):
            focused.press()

    def action_add(self):
        self._run_choice(("add", None) if op.whoami() and op_cli._context().project
                         else ("account-add", None))

    def action_login(self):
        if not op.whoami():
            self._run_choice(("signin", None))

    def action_init(self):
        if op.whoami():
            self._run_choice(("cmd", ["project", "init"]))

    def action_use(self):
        self._run_choice(("cmd", ["env", "use"]))

    def action_pull(self):
        self._run_choice(("cmd", ["env", "pull", "--materialize"]))

    def action_import_env(self):
        self._run_choice(("cmd", ["env", "import"]))

    def action_template(self):
        self._run_choice(("cmd", ["env", "template", "--out", ".env.template"]))

    def action_copy(self):
        focused = self.app.focused
        if focused in self._rows:
            choice = self._choices[focused._action_id]
            if choice[0] == "secret":
                name, value, _ = self._secrets[choice[1]]
                self.refresh_menu(f"Copied {name}" if op_cli._copy_to_clipboard(value)
                                  else "Clipboard unavailable")

    def action_refresh(self):
        self._revealed.clear()
        self.refresh_menu()

    def action_op_cli(self):
        self._launch_op_cli()

    def _launch_op_cli(self) -> None:
        """Suspend Textual and drop into the real `op` CLI — no helper screen."""
        import os as _os
        if _os.environ.get("NNOP_DEV"):
            self.refresh_menu("op CLI handoff is disabled in dev mode.")
            return
        try:
            with self.app.suspend():
                print()
                print("  NovaNode  /  op CLI")
                print("  Running the official 1Password CLI. Ctrl-D to return.")
                print()
                try:
                    subprocess.call(["op"])
                except FileNotFoundError:
                    print("  op CLI not found. Install with:")
                    print("    brew install --cask 1password-cli")
                try:
                    input("  Press Enter to return to NovaNode… ")
                except (EOFError, KeyboardInterrupt):
                    pass
        except (KeyboardInterrupt, SystemExit):
            pass
        self.refresh_menu()

    def action_quit(self):
        self._exit_or_pop()

    def _exit_or_pop(self) -> None:
        target = getattr(self.app, "_initial_target", "hub")
        if target == "hub" and len(self.app.screen_stack) > 1:
            self.app.pop_screen()
        else:
            self.app.exit()


READ_ONLY = {
    ("status",), ("doctor",), ("where",), ("accounts",),
    ("project", "list"), ("env", "envs"), ("access", "list"),
}
ANSI = re.compile(r"\033\[[0-9;]*m")


class OpActionScreen(Screen):
    """Consistent NovaNode presentation around legacy command output/prompts.

    Commands requiring input retain the terminal and process environment; only
    read-only commands are captured for display in Textual.
    """

    BINDINGS = [("escape", "back", "Back"),
                ("enter", "activate", "Select"), ("space", "activate", "Select"),
                ("up", "previous", "Previous"), ("down", "next", "Next")]
    DEFAULT_CSS = """
    OpActionScreen { layout: vertical; }
    #action-content { height: 1fr; padding: 1 2; }
    #action-content Static { height: auto; }
    #action-content NovaAction {
        width: 100%;
        min-height: 3;
        padding: 1 2;
        margin: 1 0 0 0;
        background: #0D110E;
        border-left: heavy #242A25;
    }
    #action-content NovaAction:hover {
        background: #121713;
        border-left: heavy #50C900;
    }
    #action-content NovaAction:focus {
        background: #121713;
        border-left: heavy #75FF00;
    }
    #action-content NovaActionLabel { text-style: bold; }
    #action-content Input { margin: 1 0 0 0; background: #0D110E;
                            border: tall #242A25; color: #E7ECE8; }
    #action-content Input:focus { border: tall #75FF00; }
    .action-title { color: #75FF00; text-style: bold; margin-top: 1; }
    .action-note { color: #9AA39C; }
    .action-output { margin-top: 1; padding: 1 2; background: #0D110E;
                     border: tall #242A25; }
    """

    def __init__(self, dashboard, choice, label, description=""):
        super().__init__()
        self.dashboard = dashboard
        self.choice = choice
        self.label = label
        self.description = description
        self.read_only = choice[0] == "cmd" and tuple(choice[1]) in READ_ONLY

    def compose(self) -> ComposeResult:
        yield NovaHeader("NOVANODE", "/ SECRETS")
        with VerticalScroll(id="action-content"):
            yield Static(self.label, classes="action-title")
            if self.description:
                yield Static(self.description, classes="action-note")
            if self.choice[0] == "account-add":
                yield Static("NovaNode will pass the sign-in address and email to 1Password.",
                             classes="action-note")
                yield Static("The official op CLI then prompts for your Secret Key and account password only — those never pass through NovaNode.",
                             classes="action-note")
                yield Input(placeholder="Sign-in address (e.g. example.1password.com)",
                            id="input-address")
                yield Input(placeholder="Email", id="input-email")
            elif self.choice[0] == "signin":
                yield Static("NovaNode selects your configured account, then 1Password handles the sign-in prompt.",
                             classes="action-note")
            elif self.read_only:
                yield Static("Loading…", id="action-output", classes="action-output")
            elif self.choice[0] != "install-help":
                yield Static("The existing nn-op command will take over the terminal for its prompts, then return here.",
                             classes="action-note")
            if self.choice[0] == "install-help":
                yield Static("Install the official 1Password CLI: brew install --cask 1password-cli\n"
                             "https://developer.1password.com/docs/cli/get-started/",
                             classes="action-output")
            elif not self.read_only:
                yield NovaAction("Continue", "flow-start", shortcut="Enter")
            yield NovaAction("Back to secrets", "flow-back", shortcut="Esc")
        yield NovaFooter([("Enter", "Continue" if not self.read_only else "View"),
                          ("Esc", "Back")])

    def on_mount(self) -> None:
        if self.choice[0] == "account-add":
            self.query_one("#input-address", Input).focus()
        else:
            target = "#action-flow-back" if self.read_only or self.choice[0] == "install-help" else "#action-flow-start"
            self.query_one(target, NovaAction).focus()
        if self.read_only:
            self.load_output()

    @work(thread=True, exclusive=True)
    def load_output(self) -> None:
        try:
            result = subprocess.run(
                [sys.executable, op_cli.__file__, *self.choice[1]],
                capture_output=True, text=True, timeout=60, check=False,
            )
            output = ANSI.sub("", (result.stdout or "") + (result.stderr or "")).strip()
        except (OSError, subprocess.SubprocessError) as error:
            output = f"Unable to load: {error}"
        self.app.call_from_thread(self.query_one("#action-output", Static).update,
                                  output or "No entries found.")

    def on_nova_action_activated(self, event: NovaAction.Activated) -> None:
        event.stop()
        if event.action_id == "flow-back":
            self.action_back()
        elif event.action_id == "flow-start":
            self.execute()

    def execute(self) -> None:
        kind, payload = self.choice
        address = email = None
        if kind == "account-add":
            try:
                address = (self.query_one("#input-address", Input).value or "").strip() or None
                email = (self.query_one("#input-email", Input).value or "").strip() or None
            except Exception:
                address = email = None
        ok, note = False, ""
        try:
            with self.app.suspend():
                if kind == "signin":
                    ok, note = op_cli._interactive_sign_in(op.account_list())
                elif kind == "account-add":
                    ok, note = op_cli._interactive_add_account(address=address, email=email)
                elif kind == "add":
                    ok, note = op_cli._quick_add_secret(op_cli._context())
                else:
                    result = op_cli.dispatch(list(payload))
                    ok = result == 0
                    try:
                        input("  Press Enter to return to NovaNode… ")
                    except (EOFError, KeyboardInterrupt):
                        pass
                    note = "Command completed" if ok else "Command did not complete"
        except (KeyboardInterrupt, SystemExit):
            note = "Operation cancelled"
        except (OSError, op.OpError):
            note = "Operation failed; check the 1Password CLI and retry"
        content = self.query_one("#action-content", VerticalScroll)
        content.mount(Static(note, classes="action-output"))
        self.query_one("#action-flow-start", NovaAction).remove()
        self.query_one("#action-flow-back", NovaAction).focus()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        if event.input.id == "input-address":
            try:
                self.query_one("#input-email", Input).focus()
            except Exception:
                pass
        elif event.input.id == "input-email":
            self.execute()

    def action_activate(self) -> None:
        focused = self.app.focused
        if isinstance(focused, NovaAction):
            focused.press()

    def action_previous(self) -> None:
        self.app.action_focus_previous()

    def action_next(self) -> None:
        self.app.action_focus_next()

    def action_back(self) -> None:
        self.dashboard.refresh_menu()
        self.app.pop_screen()
