"""NovaNode Secrets App — Textual application entry point for nn-op."""

from textual.app import App, ComposeResult
from textual.binding import Binding

from .screens.secrets import SecretsScreen


class NovaSecretsApp(App):
    """NovaNode Secrets Dashboard — premium TUI."""

    CSS_PATH = "styles/nova.tcss"
    TITLE = "NovaNode Secrets"
    SUB_TITLE = "Secure project environments"

    def on_mount(self) -> None:
        self.push_screen(SecretsScreen())

    def action_quit(self) -> None:
        self.exit()


def main():
    app = NovaSecretsApp()
    app.run()


if __name__ == "__main__":
    main()
