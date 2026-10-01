import contextlib
import os
import sys
import unittest
from types import SimpleNamespace
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "bin", "lib"))

try:
    from ui.app_usage import NovaUsageApp
    from ui.app_secrets import NovaSecretsApp
    from ui.app_hub import NovaHubApp
    from ui.components import NovaAction
    from ui.screens.usage import average
    import usage
    import op
    import op_cli
except ImportError:
    NovaUsageApp = None


@unittest.skipUnless(NovaUsageApp, "Textual optional dependency not installed")
class TextualUITests(unittest.IsolatedAsyncioTestCase):
    async def test_usage_renders_legacy_rows_and_available_only_averages(self):
        rows = [
            dict(provider="openai", name="Codex CLI · Nova", version="0.145.0",
                 usage_status="live", p1="5h", used1="n/a", reset1="n/a",
                 p2="Weekly", used2="52", reset2="5 Oct"),
            dict(provider="claude", name="Claude Code · Work", version="2.1.152",
                 usage_status="live", p1="5h", used1="100", reset1="22:00",
                 p2="Weekly", used2="51", reset2="5 Oct"),
        ]
        self.assertEqual(average(rows, "used1"), 100)
        self.assertEqual(average(rows, "used2"), 51.5)
        with mock.patch.object(usage, "fetch_usage", return_value=rows) as fetch:
            app = NovaUsageApp()
            async with app.run_test(size=(100, 30)) as pilot:
                await pilot.pause()
                self.assertEqual(len(app.screen.query("ProviderCard")), 2)
                self.assertEqual(len(app.screen.query(".combined Static")), 6)
            fetch.assert_called()

    async def test_secrets_keyboard_and_mouse_share_account_action(self):
        with mock.patch.object(op, "installed", return_value=True), \
             mock.patch.object(op, "whoami", return_value=None), \
             mock.patch.object(op, "account_list", return_value=[]), \
             mock.patch.object(op_cli, "_interactive_add_account", return_value=(False, "Cancelled")) as add, \
             mock.patch.object(NovaSecretsApp, "suspend", return_value=contextlib.nullcontext()):
            app = NovaSecretsApp()
            async with app.run_test(size=(100, 30)) as pilot:
                await pilot.pause()
                self.assertEqual(app.focused, app.screen._rows[1])
                await pilot.press("down")
                self.assertEqual(app.focused, app.screen._rows[2])
                await pilot.press("up")
                self.assertEqual(app.focused, app.screen._rows[1])
                await pilot.press("enter")
                await pilot.pause()
                self.assertEqual(app.screen.label, "Add a 1Password account")
                self.assertEqual(add.call_count, 0)
                await pilot.click("#action-flow-start")
                await pilot.pause()
                self.assertEqual(add.call_count, 1)
                add.assert_called_with(address=None, email=None)
                await pilot.press("escape")
                await pilot.pause()
                await pilot.click(f"#{app.screen._rows[1].id}")
                await pilot.pause()
                await pilot.click("#action-flow-start")
                await pilot.pause()
                self.assertEqual(add.call_count, 2)
                await pilot.press("escape")
                await pilot.pause()
                await pilot.press("a")
                await pilot.pause()
                await pilot.click("#action-flow-start")
                await pilot.pause()
                self.assertEqual(add.call_count, 3)
                await pilot.press("escape")
                await pilot.press("q")

    async def test_account_add_passes_textual_inputs_to_handoff(self):
        with mock.patch.object(op, "installed", return_value=True), \
             mock.patch.object(op, "whoami", return_value=None), \
             mock.patch.object(op, "account_list", return_value=[]), \
             mock.patch.object(op_cli, "_interactive_add_account", return_value=(True, "Connected")) as add, \
             mock.patch.object(NovaSecretsApp, "suspend", return_value=contextlib.nullcontext()):
            app = NovaSecretsApp()
            async with app.run_test(size=(100, 30)) as pilot:
                await pilot.pause()
                await pilot.press("enter")
                await pilot.pause()
                await pilot.press(*list("example.1password.com"))
                await pilot.press("enter")
                await pilot.pause()
                await pilot.press(*list("dev@example.com"))
                await pilot.press("enter")
                await pilot.pause()
                add.assert_called_once_with(
                    address="example.1password.com",
                    email="dev@example.com",
                )

    async def test_usage_refresh_renders_new_rows_without_duplicate_ids(self):
        rows = [dict(provider="openai", name="Codex CLI · Nova", version="1",
                     usage_status="live", p1="5h", used1="10", reset1="12:00",
                     p2="Weekly", used2="52", reset2="5 Oct")]
        with mock.patch.object(usage, "fetch_usage", return_value=rows):
            app = NovaUsageApp()
            async with app.run_test(size=(80, 24)) as pilot:
                await pilot.pause()
                await pilot.press("r")
                await pilot.pause()
                self.assertEqual(len(app.screen.query("ProviderCard")), 1)

    async def test_usage_provider_unavailable_does_not_hide_other_profiles(self):
        rows = [dict(provider="openai", name="Codex CLI · Nova", version="1",
                     usage_status="unavailable", used1="n/a", used2="n/a"),
                dict(provider="claude", name="Claude Code · Work", version="2",
                     usage_status="live", p1="5h", used1="100", reset1="22:00",
                     p2="Weekly", used2="51", reset2="5 Oct")]
        with mock.patch.object(usage, "fetch_usage", return_value=rows):
            app = NovaUsageApp()
            async with app.run_test(size=(120, 35)) as pilot:
                await pilot.pause()
                self.assertEqual(len(app.screen.query("ProviderCard")), 2)
                self.assertEqual(average(rows, "used2"), 51)

    async def test_usage_renders_at_common_terminal_sizes(self):
        rows = [dict(provider="claude", name="Claude Code · Work", version="2",
                     usage_status="live", p1="5h", used1="100", reset1="22:00",
                     p2="Weekly", used2="51", reset2="5 Oct")]
        with mock.patch.object(usage, "fetch_usage", return_value=rows):
            for size in ((80, 24), (100, 30), (120, 35), (131, 68), (160, 45)):
                with self.subTest(size=size):
                    app = NovaUsageApp()
                    async with app.run_test(size=size) as pilot:
                        await pilot.pause()
                        self.assertEqual(len(app.screen.query("ProviderCard")), 1)
                        self.assertEqual(len(app.screen.query(".combined Static")), 6)

    async def test_authenticated_setup_runs_legacy_dispatch_in_project_directory(self):
        original = os.getcwd()
        context = op_cli.ProjectContext(None, {}, {})
        with mock.patch.object(op, "installed", return_value=True), \
             mock.patch.object(op, "whoami", return_value={"email": "dev@example.com"}), \
             mock.patch.object(op_cli, "_context", return_value=context), \
             mock.patch.object(op_cli, "dispatch", return_value=0) as dispatch, \
             mock.patch("builtins.input", return_value=""), \
             mock.patch.object(NovaSecretsApp, "suspend", return_value=contextlib.nullcontext()):
            app = NovaSecretsApp()
            async with app.run_test(size=(80, 24)) as pilot:
                await pilot.pause()
                self.assertEqual(app.focused, app.screen._rows[0])
                await pilot.press("enter")
                await pilot.pause()
                self.assertEqual(app.screen.label, "Initialize this directory")
                await pilot.press("enter")
                await pilot.pause()
                dispatch.assert_called_once_with(["project", "init"])
                self.assertEqual(os.getcwd(), original)

    async def test_hub_navigates_into_usage_secrets_and_help(self):
        rows = [dict(provider="claude", name="Claude Code", version="2",
                     usage_status="live", p1="5h", used1="10", reset1="12:00",
                     p2="Weekly", used2="20", reset2="5 Oct")]
        with mock.patch.object(usage, "fetch_usage", return_value=rows), \
             mock.patch.object(op, "installed", return_value=True), \
             mock.patch.object(op, "whoami", return_value=None), \
             mock.patch.object(op, "account_list", return_value=[]):
            app = NovaHubApp()
            async with app.run_test(size=(120, 36)) as pilot:
                await pilot.pause()
                from ui.screens.hub import HubScreen
                self.assertIsInstance(app.screen, HubScreen)
                await pilot.press("u")
                await pilot.pause()
                from ui.screens.usage import UsageScreen
                self.assertIsInstance(app.screen, UsageScreen)
                await pilot.press("q")
                await pilot.pause()
                self.assertIsInstance(app.screen, HubScreen)
                await pilot.press("s")
                await pilot.pause()
                from ui.screens.secrets import SecretsScreen
                self.assertIsInstance(app.screen, SecretsScreen)
                await pilot.press("escape")
                await pilot.pause()
                self.assertIsInstance(app.screen, HubScreen)
                await pilot.press("h")
                await pilot.pause()
                from ui.screens.help import HelpScreen
                self.assertIsInstance(app.screen, HelpScreen)
                await pilot.press("escape")
                await pilot.pause()
                self.assertIsInstance(app.screen, HubScreen)
                await pilot.press("q")

    async def test_hub_honors_initial_target(self):
        rows = [dict(provider="claude", name="Claude Code", version="2",
                     usage_status="live", p1="5h", used1="10", reset1="12:00",
                     p2="Weekly", used2="20", reset2="5 Oct")]
        with mock.patch.object(usage, "fetch_usage", return_value=rows):
            app = NovaHubApp()
            app._initial_target = "usage"
            async with app.run_test(size=(100, 30)) as pilot:
                await pilot.pause()
                from ui.screens.usage import UsageScreen
                self.assertIsInstance(app.screen, UsageScreen)
                await pilot.press("q")

    async def test_status_screen_displays_existing_cli_output(self):
        result = SimpleNamespace(returncode=0, stdout="NovaNode · 1Password Status\nAuthentication signed out\n", stderr="")
        with mock.patch.object(op, "installed", return_value=True), \
             mock.patch.object(op, "whoami", return_value=None), \
             mock.patch.object(op, "account_list", return_value=[]), \
             mock.patch("ui.screens.secrets.subprocess.run", return_value=result) as run:
            app = NovaSecretsApp()
            async with app.run_test(size=(100, 30)) as pilot:
                await pilot.pause()
                await pilot.click(f"#{app.screen._rows[2].id}")
                await pilot.pause()
                self.assertEqual(app.screen.label, "Connection status")
                self.assertIn("Authentication signed out",
                              str(app.screen.query_one("#action-output").render()))
                self.assertEqual(run.call_args.args[0][1:], [op_cli.__file__, "status"])
                await pilot.press("escape")
                await pilot.pause()
                self.assertEqual(len(app.screen._rows), 4)
