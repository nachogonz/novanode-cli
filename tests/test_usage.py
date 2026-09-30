import io
import json
import os
import sys
import tempfile
import unittest
from unittest import mock


ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "bin", "lib"))

import usage
import usage_accounts


class FakeProcess:
    def __init__(self, messages):
        self.stdout = io.StringIO("".join(json.dumps(item) + "\n" for item in messages))
        self.stdin = io.StringIO()
        self.killed = False

    def poll(self):
        return None if not self.killed else -9

    def kill(self):
        self.killed = True

    def wait(self, timeout=None):
        return -9


class UsageTests(unittest.TestCase):
    def test_codex_completes_handshake_before_rate_limit_request(self):
        process = FakeProcess([
            {"id": 1, "result": {"codexHome": "/tmp/codex-home"}},
            {"id": 2, "result": {"rateLimits": {"primary": {"usedPercent": 12}}}},
        ])
        account = {"provider": "openai", "home": "/tmp/codex-home"}
        write_snapshots = []

        def ready(*_args, **_kwargs):
            write_snapshots.append(process.stdin.getvalue())
            return [process.stdout], [], []

        with mock.patch.object(usage.subprocess, "Popen", return_value=process), \
             mock.patch.object(usage.select, "select", side_effect=ready):
            limits = usage.codex_rate_limits(account)

        self.assertEqual(limits["primary"]["usedPercent"], 12)
        self.assertIn('"method":"initialize"', write_snapshots[0])
        self.assertNotIn('"method":"account/rateLimits/read"', write_snapshots[0])
        final = process.stdin.getvalue()
        self.assertLess(final.index('"method":"initialized"'), final.index('"method":"account/rateLimits/read"'))
        self.assertTrue(process.killed)

    def test_only_managed_profiles_are_considered(self):
        with tempfile.TemporaryDirectory() as root:
            os.environ["NOVANODE_USAGE_ACCOUNTS_PATH"] = os.path.join(root, "accounts.json")
            os.environ["NOVANODE_USAGE_PROFILES_DIR"] = os.path.join(root, "providers")
            import importlib
            importlib.reload(usage_accounts)
            self.assertEqual(usage_accounts.all_accounts(), [])
            account = usage_accounts.account_for("openai", "Personal")
            usage_accounts.remember_account(account)
            accounts = usage_accounts.all_accounts()
            self.assertEqual(len(accounts), 1)
            self.assertTrue(accounts[0]["managed"])
            self.assertEqual(accounts[0]["provider"], "openai")

    def test_claude_keychain_lookup_is_scoped_for_named_profile(self):
        with tempfile.TemporaryDirectory() as home:
            account = {"provider": "claude", "home": home, "managed": True}
            credential = json.dumps({"claudeAiOauth": {"accessToken": "secret"}})
            with mock.patch.object(usage_accounts.sys, "platform", "darwin"), \
                 mock.patch.object(usage_accounts.subprocess, "check_output", return_value=credential) as call:
                token = usage_accounts.claude_token(account)

        self.assertEqual(token, "secret")
        args = call.call_args.args[0]
        self.assertEqual(args[args.index("-a") + 1], home)

    def test_claude_token_falls_back_to_user_scoped_keychain(self):
        account = {"provider": "claude", "home": "/tmp/claude-profile", "managed": True}
        credential = json.dumps({"claudeAiOauth": {"accessToken": "user-scoped-token"}})

        def keychain(args, *_, **__):
            if args[args.index("-a") + 1] == "nachogonzalez":
                return credential
            raise usage_accounts.subprocess.CalledProcessError(1, args)

        with mock.patch.dict(os.environ, {"USER": "nachogonzalez"}, clear=True), \
             mock.patch.object(usage_accounts.sys, "platform", "darwin"), \
             mock.patch.object(usage_accounts.subprocess, "check_output", side_effect=keychain):
            token = usage_accounts.claude_token(account)

        self.assertEqual(token, "user-scoped-token")

    def test_claude_status_trusts_provider_cli(self):
        account = {"provider": "claude", "home": "/tmp/claude-profile", "managed": True}
        result = mock.Mock(returncode=0, stdout='{"loggedIn":true,"authMethod":"claude.ai"}', stderr="")
        with mock.patch.object(usage_accounts.shutil, "which", return_value="/usr/bin/claude"), \
             mock.patch.object(usage_accounts, "provider_version", return_value="2.1.152"), \
             mock.patch.object(usage_accounts.subprocess, "run", return_value=result):
            status = usage_accounts.connection_status(account)

        self.assertTrue(status["connected"])
        self.assertEqual(status["detail"], "claude.ai")

    def test_managed_profiles_ignore_shell_credentials_and_provider_overrides(self):
        account = {"provider": "claude", "home": "/tmp/claude-work", "managed": True}
        inherited = {
            "ANTHROPIC_API_KEY": "wrong-account",
            "ANTHROPIC_PROFILE": "default",
            "CLAUDE_CODE_OAUTH_TOKEN": "wrong-account",
            "CLAUDE_CODE_USE_BEDROCK": "1",
            "UNRELATED_SETTING": "keep-me",
        }
        with mock.patch.dict(os.environ, inherited, clear=True):
            env = usage_accounts.account_env(account)

        self.assertEqual(env["CLAUDE_CONFIG_DIR"], "/tmp/claude-work")
        self.assertEqual(env["UNRELATED_SETTING"], "keep-me")
        for key in inherited:
            if key != "UNRELATED_SETTING":
                self.assertNotIn(key, env)


if __name__ == "__main__":
    unittest.main()
