import os
import sys
import unittest
from types import SimpleNamespace
from unittest import mock


ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "bin", "lib"))

import op
import op_cli


class OpAuthenticationTests(unittest.TestCase):
    def test_signin_session_keeps_token_only_in_process_environment(self):
        result = SimpleNamespace(returncode=0, stdout="session-token\n")
        with mock.patch.dict(op.os.environ, {}, clear=True), \
             mock.patch.object(op, "_run", return_value=result) as run:
            self.assertTrue(op.signin_session("work"))
            self.assertEqual(op.os.environ["OP_SESSION"], "session-token")
            self.assertEqual(op.os.environ["OP_SESSION_work"], "session-token")
            self.assertEqual(op.os.environ["OP_ACCOUNT"], "work")
        run.assert_called_once_with(
            ["signin", "--raw", "--account", "work"],
            inherit_tty=True,
            capture_stdout=True,
            check=False,
            timeout=None,
        )

    def test_account_add_uses_native_secure_wizard_and_retains_session(self):
        add_ok = SimpleNamespace(returncode=0, stdout="", stderr="")
        signin_ok = SimpleNamespace(returncode=0, stdout="new-session\n", stderr="")
        with mock.patch.dict(op.os.environ, {}, clear=True), \
             mock.patch.object(op, "installed", return_value=True), \
             mock.patch("op.subprocess.run",
                        side_effect=[add_ok, signin_ok]) as run:
            self.assertTrue(op.account_add(signin=True))
            self.assertEqual(op.os.environ["OP_SESSION"], "new-session")
        self.assertEqual(run.call_count, 2)
        # Interactive add owns the TTY when fields are missing.
        self.assertEqual(run.call_args_list[0].args[0], ["op", "account", "add"])
        self.assertEqual(run.call_args_list[1].args[0], ["op", "signin", "--raw"])

    def test_account_add_two_step_persistence_with_all_fields(self):
        add_ok = SimpleNamespace(returncode=0, stdout="", stderr="")
        signin_ok = SimpleNamespace(returncode=0, stdout="piped-session\n", stderr="")
        with mock.patch.dict(op.os.environ, {}, clear=True), \
             mock.patch.object(op, "installed", return_value=True), \
             mock.patch("op.subprocess.run",
                        side_effect=[add_ok, signin_ok]) as run:
            self.assertTrue(op.account_add(
                signin=True, address="nakdev.1password.com",
                email="dev@novanode.local",
                secret_key="A3-SECRET-KEY", password="hunter2"))
            self.assertEqual(op.os.environ["OP_SESSION"], "piped-session")
        add_call = run.call_args_list[0]
        signin_call = run.call_args_list[1]
        self.assertEqual(add_call.args[0], [
            "op", "account", "add",
            "--address", "nakdev.1password.com",
            "--email", "dev@novanode.local",
            "--secret-key", "A3-SECRET-KEY",
        ])
        self.assertTrue(add_call.kwargs.get("capture_output"))
        self.assertNotIn("input", add_call.kwargs)
        self.assertEqual(signin_call.args[0], [
            "op", "signin", "--raw",
            "--account", "nakdev.1password.com",
        ])
        self.assertEqual(signin_call.kwargs.get("input"), "hunter2\n")

    def test_account_add_still_persists_when_signin_fails(self):
        add_ok = SimpleNamespace(returncode=0, stdout="", stderr="")
        signin_bad = SimpleNamespace(returncode=1, stdout="",
                                     stderr="wrong password\n")
        with mock.patch.dict(op.os.environ, {}, clear=True), \
             mock.patch.object(op, "installed", return_value=True), \
             mock.patch("op.subprocess.run",
                        side_effect=[add_ok, signin_bad]):
            # Account was added, so the function returns True; session is
            # just not retained in-process.
            self.assertTrue(op.account_add(
                signin=True, address="nakdev.1password.com",
                email="dev@novanode.local",
                secret_key="A3-SECRET-KEY", password="wrong"))
            self.assertNotIn("OP_SESSION", op.os.environ)

    def test_signout_removes_in_memory_session(self):
        result = SimpleNamespace(returncode=0)
        environment = {
            "OP_SESSION": "token",
            "OP_SESSION_work": "token",
            "OP_ACCOUNT": "work",
            "UNRELATED": "keep",
        }
        with mock.patch.dict(op.os.environ, environment, clear=True), \
             mock.patch.object(op, "_run", return_value=result):
            self.assertEqual(op.signout(), 0)
            self.assertNotIn("OP_SESSION", op.os.environ)
            self.assertNotIn("OP_SESSION_work", op.os.environ)
            self.assertNotIn("OP_ACCOUNT", op.os.environ)
            self.assertEqual(op.os.environ["UNRELATED"], "keep")


class OpOnboardingTests(unittest.TestCase):
    @staticmethod
    def selectable_values(items):
        return [item.value for item in items if not item.disabled]

    def test_signed_out_screen_starts_with_sign_in_and_offers_account_add(self):
        accounts = [{"shorthand": "work", "email": "dev@example.com"}]
        values = self.selectable_values(op_cli._signed_out_items(accounts, True))
        self.assertEqual(values[0], ("signin", None))
        self.assertIn(("account-add", None), values)
        self.assertNotIn(("cmd", ["project", "init"]), values)

    def test_workspace_setup_starts_with_initialize_after_authentication(self):
        values = self.selectable_values(op_cli._workspace_setup_items())
        self.assertEqual(values[0], ("cmd", ["project", "init"]))
        self.assertIn(("account-add", None), values)


if __name__ == "__main__":
    unittest.main()
