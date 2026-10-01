import os
import sys
import tempfile
import unittest
from types import SimpleNamespace
from unittest import mock


ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "bin", "lib"))

import op
import op_cli


class OpAuthenticationTests(unittest.TestCase):
    def test_resolves_real_op_past_global_novanode_alias(self):
        with tempfile.TemporaryDirectory() as aliases, tempfile.TemporaryDirectory() as real:
            wrapper = os.path.join(aliases, "op")
            binary = os.path.join(real, "op")
            with open(wrapper, "w") as handle:
                handle.write("#!/usr/bin/env bash\n# Fast alias for `nn-op`.\nexec nn-op \"$@\"\n")
            with open(binary, "w") as handle:
                handle.write("#!/usr/bin/env bash\nexit 0\n")
            os.chmod(wrapper, 0o755)
            os.chmod(binary, 0o755)
            with mock.patch.dict(os.environ, {"PATH": aliases + os.pathsep + real}):
                self.assertEqual(op.which_op(), binary)
                with mock.patch("op.subprocess.run", return_value=SimpleNamespace(
                        returncode=0, stdout='{"email":"test@example.com"}', stderr="")) as run:
                    self.assertEqual(op.whoami()["email"], "test@example.com")
                    self.assertEqual(run.call_args.args[0][:2], [binary, "whoami"])

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
             mock.patch.object(op, "which_op", return_value="/real/op"), \
             mock.patch("op.subprocess.run", return_value=result) as run:
            self.assertTrue(op.account_add(signin=True))
            self.assertEqual(op.os.environ["OP_SESSION"], "new-session")
        run.assert_called_once_with(
            ["/real/op", "account", "add", "--signin", "--raw"],
            stdout=op.subprocess.PIPE, text=True, timeout=None,
        )

    def test_account_add_keeps_credentials_out_of_process_arguments(self):
        result = SimpleNamespace(returncode=0, stdout="session-token\n")
        with mock.patch.dict(op.os.environ, {}, clear=True), \
             mock.patch.object(op, "which_op", return_value="/real/op"), \
             mock.patch("op.subprocess.run", return_value=result) as run:
            self.assertTrue(op.account_add(
                signin=True, address="nakdev.1password.com",
                email="dev@novanode.local"))
            self.assertEqual(op.os.environ["OP_SESSION"], "session-token")
        run.assert_called_once_with([
            "/real/op", "account", "add",
            "--address", "nakdev.1password.com",
            "--email", "dev@novanode.local",
            "--signin", "--raw",
        ], stdout=op.subprocess.PIPE, text=True, timeout=None)

    def test_account_add_failure_does_not_claim_a_session(self):
        result = SimpleNamespace(returncode=1, stdout="")
        with mock.patch.dict(op.os.environ, {}, clear=True), \
             mock.patch.object(op, "which_op", return_value="/real/op"), \
             mock.patch("op.subprocess.run", return_value=result):
            self.assertFalse(op.account_add(signin=True))
            self.assertNotIn("OP_SESSION", op.os.environ)

    def test_account_add_without_signin_leaves_stdout_with_op(self):
        result = SimpleNamespace(returncode=0)
        with mock.patch.object(op, "which_op", return_value="/real/op"), \
             mock.patch("op.subprocess.run", return_value=result) as run:
            self.assertTrue(op.account_add())
        run.assert_called_once_with(
            ["/real/op", "account", "add"], stdout=None, text=False, timeout=None,
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

    def test_no_account_screen_only_offers_connection(self):
        items = op_cli._signed_out_items([], True)
        self.assertEqual(self.selectable_values(items)[0], ("account-add", None))
        self.assertNotIn(("signin", None), self.selectable_values(items))
        self.assertIn("Internet required", items[2].subtitle)

    def test_workspace_setup_starts_with_initialize_after_authentication(self):
        values = self.selectable_values(op_cli._workspace_setup_items())
        self.assertEqual(values[0], ("cmd", ["project", "init"]))
        self.assertIn(("account-add", None), values)

    def test_existing_account_add_signs_in_instead_of_registering_again(self):
        account = {
            "url": "https://novanode.1password.com",
            "email": "nacho@novanode.co",
            "shorthand": "novanode",
        }
        with mock.patch.object(op, "account_list", return_value=[account]), \
             mock.patch.object(op, "account_add") as add, \
             mock.patch.object(op_cli, "_interactive_sign_in",
                               return_value=(True, "Signed in")) as sign_in:
            self.assertEqual(
                op_cli._interactive_add_account("novanode.1password.com", "NACHO@NOVANODE.CO"),
                (True, "Signed in"),
            )
        sign_in.assert_called_once_with([account], account="novanode")
        add.assert_not_called()


if __name__ == "__main__":
    unittest.main()
