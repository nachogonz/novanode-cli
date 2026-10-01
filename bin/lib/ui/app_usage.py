"""NovaNode Usage App — Textual application entry point."""

from textual.app import App, ComposeResult
from textual.binding import Binding

from .screens.usage import UsageScreen


class NovaUsageApp(App):
    """NovaNode Usage Dashboard — premium TUI."""

    CSS_PATH = "styles/nova.tcss"
    TITLE = "NovaNode Usage"
    SUB_TITLE = "Provider-owned credentials · live plan windows"

    def on_mount(self) -> None:
        self.push_screen(UsageScreen())

    def action_quit(self) -> None:
        self.exit()


def main():
    app = NovaUsageApp()
    app.run()


if __name__ == "__main__":
    main()
