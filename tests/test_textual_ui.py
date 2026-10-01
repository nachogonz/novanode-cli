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
                self.assertEqual(len(app.screen.query(".combined Static")), 9)
            fetch.assert_called()

    async def test_secrets_keyboard_and_mouse_share_account_action(self):
        with mock.patch.object(op, "installed", return_value=True), \
             mock.patch.object(op, "whoami", return_value=None), \
             mock.patch.object(op, "account_list", return_value=[]):
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
                self.assertEqual(len(app.screen.query("#input-address")), 1)
                self.assertEqual(len(app.screen.query("#input-password")), 1)
                await pilot.press("escape")
                await pilot.pause()
                await pilot.click(f"#{app.screen._rows[1].id}")
                await pilot.pause()
                self.assertEqual(app.screen.label, "Add a 1Password account")
                await pilot.press("escape")
                await pilot.press("q")

    async def test_account_add_sends_all_four_fields_to_op(self):
        with mock.patch.object(op, "installed", return_value=True), \
             mock.patch.object(op, "whoami", return_value=None), \
             mock.patch.object(op, "account_list", return_value=[]), \
             mock.patch.object(op, "account_add", return_value=True) as add:
            app = NovaSecretsApp()
            async with app.run_test(size=(100, 36)) as pilot:
                await pilot.pause()
                await pilot.press("enter")
                await pilot.pause()
                from textual.widgets import Input as _Input
                app.screen.query_one("#input-address", _Input).value = "nakdev.1password.com"
                app.screen.query_one("#input-email", _Input).value = "dev@novanode.local"
                app.screen.query_one("#input-secret", _Input).value = "A3-SECRET"
                app.screen.query_one("#input-password", _Input).value = "hunter2"
                await pilot.click("#action-flow-start")
                for _ in range(10):
                    if add.call_count:
                        break
                    await pilot.pause()
                add.assert_called_once_with(
                    signin=True,
                    address="nakdev.1password.com",
                    email="dev@novanode.local",
                    secret_key="A3-SECRET",
                    password="hunter2",
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
                        self.assertEqual(len(app.screen.query(".combined Static")), 9)

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

    async def test_dev_mode_seeds_workspace_and_shows_banner(self):
        import importlib
        import shutil
        import tempfile
        import os as _os

        tmp = tempfile.mkdtemp(prefix="nnop-dev-test-")
        prev_home = _os.environ.get("NNOP_DEV_HOME")
        prev_dev = _os.environ.get("NNOP_DEV")
        prev_cwd = _os.getcwd()
        try:
            _os.environ["NNOP_DEV_HOME"] = tmp
            _os.environ.pop("NNOP_DEV", None)
            import op_dev
            importlib.reload(op_dev)
            # Reload op so the install() patch acts on a fresh module copy.
            import op as real_op
            importlib.reload(real_op)
            op_dev.install()
            self.assertTrue(real_op.whoami())
            self.assertIn("mock", (real_op.version() or "").lower())
            self.assertTrue(_os.path.isfile(_os.path.join(tmp, "workspace",
                                                          ".novanode.yml")))
            # Patch the already-imported op_cli/secrets copies that the test
            # suite loaded at top of file to see the newly-installed mocks.
            import op_cli as cli
            importlib.reload(cli)
            from ui.screens import secrets as secrets_screen
            importlib.reload(secrets_screen)
            app = NovaSecretsApp()
            async with app.run_test(size=(100, 36)) as pilot:
                await pilot.pause()
                self.assertEqual(len(app.screen.query(".dev-banner")), 1)
                labels = [row._label for row in app.screen._rows]
                self.assertIn("Open op CLI session", labels)
        finally:
            _os.chdir(prev_cwd)
            if prev_home is None:
                _os.environ.pop("NNOP_DEV_HOME", None)
            else:
                _os.environ["NNOP_DEV_HOME"] = prev_home
            if prev_dev is None:
                _os.environ.pop("NNOP_DEV", None)
            else:
                _os.environ["NNOP_DEV"] = prev_dev
            shutil.rmtree(tmp, ignore_errors=True)
            # Restore the real `op` module for subsequent tests.
            import op as real_op
            importlib.reload(real_op)
            import op_cli as cli
            importlib.reload(cli)
            from ui.screens import secrets as secrets_screen
            importlib.reload(secrets_screen)

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
