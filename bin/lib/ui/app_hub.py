"""NovaNode Hub App — unified Textual entry point for `nn` and `novanode`."""

from textual.app import App

from .screens.hub import HubScreen


class NovaHubApp(App):
    """Unified NovaNode Textual app: Usage, Secrets, and Help in one UI."""

    CSS_PATH = "styles/nova.tcss"
    TITLE = "NovaNode"
    SUB_TITLE = "Telephony · AI usage · Secrets"

    def on_mount(self) -> None:
        self.push_screen(HubScreen())
        target = getattr(self, "_initial_target", "hub")
        if target == "usage":
            from .screens.usage import UsageScreen
            self.push_screen(UsageScreen())
        elif target == "secrets":
            from .screens.secrets import SecretsScreen
            self.push_screen(SecretsScreen())
        elif target == "help":
            from .screens.help import HelpScreen
            self.push_screen(HelpScreen())

    def action_quit(self) -> None:
        self.exit()


def main() -> None:
    NovaHubApp().run()


if __name__ == "__main__":
    main()
