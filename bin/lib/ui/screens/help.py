"""NovaNode Help — Textual help/command-reference screen."""

from textual.app import ComposeResult
from textual.containers import VerticalScroll
from textual.screen import Screen
from textual.widgets import Static

from ..components import NovaAction, NovaFooter, NovaHeader


SECTIONS = [
    (
        "GETTING STARTED",
        "NovaNode unifies three tools in one black-themed interface:\n"
        "  · Usage — AI plan windows for Codex CLI and Claude Code\n"
        "  · Secrets — 1Password-backed project environments (nn-op)\n"
        "  · PBX — Asterisk/PJSIP console (nn pbx, legacy curses tabs)",
    ),
    (
        "COMMANDS",
        "nn                       Open this unified home screen\n"
        "nn usage                 Open the usage dashboard\n"
        "nn secrets               Open the secrets dashboard (alias of nn-op)\n"
        "nn help                  Open this help screen\n"
        "nn pbx                   PBX console (endpoints, trunks, channels)\n"
        "nn pbx setup             Configure the PBX connection + softphone\n"
        "nn pbx doctor            Run connectivity diagnostics\n"
        "nn-usage                 Usage dashboard (also as `usage`)\n"
        "nn-op                    Secrets dashboard (also as `nnop`)\n"
        "nn --version / --help    Version and help text",
    ),
    (
        "USAGE DASHBOARD",
        "Live view of your Codex CLI and Claude Code plan windows.\n"
        "  R   Refresh usage data\n"
        "  C   Add/manage provider connections\n"
        "  Q   Return to the home screen\n"
        "Averages ignore windows your plan doesn't include. Add providers with\n"
        "`usage connect` from a shell.",
    ),
    (
        "SECRETS DASHBOARD",
        "Project-aware wrapper over the official 1Password CLI (`op`).\n"
        "  A   Add a secret (or add an account when signed out)\n"
        "  L   Sign in to 1Password\n"
        "  G   Initialize a NovaNode workspace in this directory\n"
        "  U   Switch app / environment\n"
        "  P   Pull real .env file (plaintext, chmod 600, auto-gitignored)\n"
        "  I   Import a .env file into the vault\n"
        "  T   Write a .env.template with op:// references\n"
        "  C   Copy highlighted secret to clipboard\n"
        "  R   Refresh\n"
        "Values stay inside 1Password; NovaNode never persists them.",
    ),
    (
        "1PASSWORD HANDOFF",
        "For your Secret Key and account password, the official `op` CLI\n"
        "takes over the terminal. NovaNode collects address and email in\n"
        "this UI first, then hands off only for the parts that must be\n"
        "entered directly into 1Password.",
    ),
    (
        "PBX",
        "`nn pbx` opens the Asterisk console. Legacy curses interface is\n"
        "retained for low-level channel/trunk/AMI inspection; the rest of\n"
        "NovaNode uses this black Textual UI.",
    ),
    (
        "KEYBOARD",
        "Up / Down / Tab      Navigate rows\n"
        "Enter / Space        Activate the focused row\n"
        "Esc / Q              Back / Quit\n"
        "Letter keys          Shortcuts shown in brackets next to each row",
    ),
    (
        "SUPPORT",
        "`nn pbx doctor` and `nn-op doctor` surface setup diagnostics.\n"
        "`nn-op status` prints CLI, auth, and project state in one view.",
    ),
]


class HelpScreen(Screen):
    BINDINGS = [
        ("up", "scroll_up", "Up"), ("down", "scroll_down", "Down"),
        ("pageup", "page_up", "Page Up"), ("pagedown", "page_down", "Page Down"),
        ("home", "home", "Top"), ("end", "end", "Bottom"),
        ("escape", "back", "Back"), ("q", "back", "Back"),
    ]
    DEFAULT_CSS = """
    HelpScreen { layout: vertical; }
    #help-content { height: 1fr; padding: 1 2; }
    #help-content Static { height: auto; }
    #help-content NovaAction { width: 100%; }
    .section-title { color: #50C900; text-style: bold; margin-top: 1; }
    .section-body { color: #E7ECE8; margin-bottom: 1; }
    """

    def compose(self) -> ComposeResult:
        yield NovaHeader("NOVANODE", "/ HELP")
        with VerticalScroll(id="help-content") as scroll:
            scroll.can_focus = True
            yield Static("A short tour of the system and its commands.",
                         classes="section-body")
            for title, body in SECTIONS:
                yield Static(title, classes="section-title")
                yield Static(body, classes="section-body")
            yield NovaAction("Back to home", "help-back", shortcut="Esc")
        yield NovaFooter([("↑↓", "Scroll"), ("Esc", "Back")])

    def on_mount(self) -> None:
        self.query_one("#help-content", VerticalScroll).focus()

    def on_nova_action_activated(self, event: NovaAction.Activated) -> None:
        if event.action_id == "help-back":
            self.action_back()

    def action_scroll_up(self) -> None:
        self.query_one("#help-content", VerticalScroll).scroll_up()

    def action_scroll_down(self) -> None:
        self.query_one("#help-content", VerticalScroll).scroll_down()

    def action_page_up(self) -> None:
        self.query_one("#help-content", VerticalScroll).scroll_page_up()

    def action_page_down(self) -> None:
        self.query_one("#help-content", VerticalScroll).scroll_page_down()

    def action_home(self) -> None:
        self.query_one("#help-content", VerticalScroll).scroll_home()

    def action_end(self) -> None:
        self.query_one("#help-content", VerticalScroll).scroll_end()

    def action_back(self) -> None:
        target = getattr(self.app, "_initial_target", "hub")
        if target == "hub" and len(self.app.screen_stack) > 1:
            self.app.pop_screen()
        else:
            self.app.exit()
