import contextlib
import io
import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(__file__)), "bin", "lib"))
import usage_cli


class UsageEntryTests(unittest.TestCase):
    def test_missing_textual_does_not_silently_show_old_ui(self):
        stderr = io.StringIO()
        with mock.patch.object(sys.stdin, "isatty", return_value=True), \
             mock.patch.object(sys.stdout, "isatty", return_value=True), \
             mock.patch.dict(sys.modules, {"ui.app_hub": None}), \
             mock.patch.object(usage_cli.usage, "fetch_usage") as fetch, \
             contextlib.redirect_stderr(stderr):
            self.assertEqual(usage_cli.main([]), 1)
        self.assertIn("Textual UI unavailable", stderr.getvalue())
        fetch.assert_not_called()

    def test_classic_is_still_explicitly_available(self):
        with mock.patch.object(usage_cli.usage, "fetch_usage", return_value=[]), \
             mock.patch.object(usage_cli, "dashboard") as dashboard:
            self.assertEqual(usage_cli.main(["--classic"]), 0)
        dashboard.assert_called_once_with([])
