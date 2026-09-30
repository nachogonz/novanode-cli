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
        result = SimpleNamespace(returncode=0, stdout="new-session\n")
        with mock.patch.dict(op.os.environ, {}, clear=True), \
             mock.patch.object(op, "_run", return_value=result) as run:
            self.assertTrue(op.account_add(signin=True))
            self.assertEqual(op.os.environ["OP_SESSION"], "new-session")
        run.assert_called_once_with(
            ["account", "add", "--signin", "--raw"],
            inherit_tty=True,
            capture_stdout=True,
            check=False,
            timeout=None,
        )

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
