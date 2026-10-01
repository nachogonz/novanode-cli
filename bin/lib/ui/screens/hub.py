"""NovaNode Hub — unified entry point for usage, secrets, and help."""

from textual.app import ComposeResult
from textual.containers import VerticalScroll
from textual.screen import Screen
from textual.widgets import Static

from ..components import NovaAction, NovaFooter, NovaHeader


class HubScreen(Screen):
    BINDINGS = [
        ("up", "previous", "Previous"), ("down", "next", "Next"),
        ("tab", "next", "Next"), ("shift+tab", "previous", "Previous"),
        ("enter", "activate", "Select"), ("space", "activate", "Select"),
        ("u", "usage", "Usage"), ("s", "secrets", "Secrets"),
        ("h", "help", "Help"), ("question_mark", "help", "Help"),
        ("q", "quit", "Quit"), ("escape", "quit", "Quit"),
    ]
    DEFAULT_CSS = """
    HubScreen { layout: vertical; }
    #hub-content { height: 1fr; padding: 1 2; }
    #hub-content Static { height: auto; }
    #hub-content NovaAction {
        width: 100%;
        min-height: 3;
        padding: 1 2;
        margin: 0 0 1 0;
        background: #0D110E;
        border-left: heavy #242A25;
    }
    #hub-content NovaAction:hover {
        background: #121713;
        border-left: heavy #50C900;
    }
    #hub-content NovaAction:focus {
        background: #121713;
        border-left: heavy #75FF00;
    }
    #hub-content NovaActionLabel { text-style: bold; }
    .section-title { color: #50C900; text-style: bold; margin: 1 0 1 0; }
    .context { color: #9AA39C; }
    .tagline { color: #626A64; margin-bottom: 1; }
    """

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._rows = []

    def compose(self) -> ComposeResult:
        yield NovaHeader("NOVANODE", "/ HOME")
        yield VerticalScroll(id="hub-content")
        yield NovaFooter([("↑↓", "Navigate"), ("Enter", "Open"),
                          ("H", "Help"), ("Q", "Quit")])

    def on_mount(self) -> None:
        self.render_menu()

    def render_menu(self) -> None:
        container = self.query_one("#hub-content", VerticalScroll)
        container.remove_children()
        self._rows = []

        container.mount(Static("Telephony devkit · AI plan usage · 1Password secrets",
                               classes="tagline"))

        container.mount(Static("DASHBOARDS", classes="section-title"))
        self._add(container, "Usage dashboard", "usage",
                  shortcut="U",
                  description="Live Codex / Claude Code plan windows")
        self._add(container, "Secrets dashboard", "secrets",
                  shortcut="S",
                  description="1Password-backed project environments")

        container.mount(Static("GUIDE", classes="section-title"))
        self._add(container, "Help & command reference", "help",
                  shortcut="H",
                  description="How this entire system works")

        container.mount(Static("SESSION", classes="section-title"))
        self._add(container, "Quit", "quit", shortcut="Q")

        if self._rows:
            self.call_after_refresh(self._rows[0].focus)

    def _add(self, container, label, action_id, shortcut="", description=""):
        row = NovaAction(label, action_id, shortcut=shortcut, description=description)
        self._rows.append(row)
        container.mount(row)

    def _focused_index(self) -> int:
        focused = self.app.focused
        return self._rows.index(focused) if focused in self._rows else -1

    def action_previous(self) -> None:
        if not self._rows:
            return
        index = self._focused_index()
        self._rows[(index - 1) % len(self._rows)].focus()

    def action_next(self) -> None:
        if not self._rows:
            return
        index = self._focused_index()
        self._rows[(index + 1) % len(self._rows)].focus()

    def action_activate(self) -> None:
        focused = self.app.focused
        if isinstance(focused, NovaAction):
            focused.press()

    def on_nova_action_activated(self, event: NovaAction.Activated) -> None:
        self._dispatch(event.action_id)

    def _dispatch(self, action_id: str) -> None:
        if action_id == "quit":
            self.app.exit()
        elif action_id == "usage":
            from .usage import UsageScreen
            self.app.push_screen(UsageScreen())
        elif action_id == "secrets":
            from .secrets import SecretsScreen
            self.app.push_screen(SecretsScreen())
        elif action_id == "help":
            from .help import HelpScreen
            self.app.push_screen(HelpScreen())

    def action_usage(self) -> None:
        self._dispatch("usage")

    def action_secrets(self) -> None:
        self._dispatch("secrets")

    def action_help(self) -> None:
        self._dispatch("help")

    def action_quit(self) -> None:
        self.app.exit()
