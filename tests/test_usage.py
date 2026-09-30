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

    def test_claude_keychain_lookup_is_scoped_for_default_profile(self):
        account = {"provider": "claude", "home": None, "managed": False}
        credential = json.dumps({"claudeAiOauth": {"accessToken": "secret"}})
        with mock.patch.dict(os.environ, {}, clear=True), \
             mock.patch.object(usage_accounts.sys, "platform", "darwin"), \
             mock.patch.object(usage_accounts.subprocess, "check_output", return_value=credential) as call:
            token = usage_accounts.claude_token(account)

        self.assertEqual(token, "secret")
        args = call.call_args.args[0]
        self.assertEqual(args[args.index("-a") + 1], os.path.expanduser("~/.claude"))

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

    def test_claude_status_rejects_login_without_durable_credential(self):
        account = {"provider": "claude", "home": "/tmp/claude-profile", "managed": True}
        result = mock.Mock(returncode=0, stdout='{"loggedIn":true,"authMethod":"claude.ai"}', stderr="")
        with mock.patch.object(usage_accounts.shutil, "which", return_value="/usr/bin/claude"), \
             mock.patch.object(usage_accounts, "provider_version", return_value="2.1.152"), \
             mock.patch.object(usage_accounts.subprocess, "run", return_value=result), \
             mock.patch.object(usage_accounts, "claude_token", return_value=None):
            status = usage_accounts.connection_status(account)

        self.assertFalse(status["connected"])
        self.assertIn("credential unavailable", status["detail"])

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
