#!/usr/bin/env python3
import curses
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import config as nnconfig  # noqa: E402
from detect import run_detect  # noqa: E402
from doctor import run_doctor  # noqa: E402
from setup import run_setup  # noqa: E402
from tui import run_tui  # noqa: E402

VERSION = "1.1.0"


def main(argv=None):
    argv = list(sys.argv[1:]) if argv is None else list(argv)
    if not argv:
        if not sys.stdin.isatty() or not sys.stdout.isatty():
            print_help()
            return 0
        return curses.wrapper(run_tui, "PBX")
    if argv[0] in ("-h", "--help"):
        print_help()
        return 0
    if argv[0] in ("-v", "--version"):
        print(VERSION)
        return 0

    cmd = argv[0]
    if cmd in ("usage",):
        return curses.wrapper(run_tui, "USAGE")
    if cmd in ("pbx",):
        sub = argv[1] if len(argv) > 1 else ""
        if sub in ("setup",):
            return run_setup()
        if sub in ("doctor", "--doctor"):
            return 0 if run_doctor() else 1
        if sub in ("detect", "info"):
            return run_detect()
        if sub in ("phone",):
            return curses.wrapper(run_tui, "PHONE")
        if sub in ("console", "status"):
            return curses.wrapper(run_tui, "PBX")
        if sub in ("test", "test-call"):
            return run_test_call()
        if sub in ("-h", "--help"):
            print_help("pbx")
            return 0
        return curses.wrapper(run_tui, "PBX")
    if cmd in ("phone",):
        return curses.wrapper(run_tui, "PHONE")
    if cmd in ("doctor", "health"):
        return 0 if run_doctor() else 1
    if cmd in ("setup",):
        return run_setup()
    if cmd in ("calls",):
        return curses.wrapper(run_tui, "CALLS")
    if cmd in ("trunks",):
        return curses.wrapper(run_tui, "TRUNKS")
    if cmd in ("debug", "debugger", "trace"):
        return curses.wrapper(run_tui, "DEBUG")
    print(f"nn: unknown command '{cmd}'\n")
    print_help()
    return 2


def run_test_call():
    import testcall

    return testcall.run_test_call()


def print_help(scope="main"):
    if scope == "main":
        print(f"""NovaNode Telephony DevKit · {VERSION}

Asterisk development/test station for your Fedora PBX.

Usage:
  nn                       Open the TUI (USAGE · PBX · PHONE · CALLS · TRUNKS · DEBUG)
  nn usage                 Open the usage dashboard
  nn pbx                   PBX console (endpoints, trunks, channels, AMI events)
  nn pbx setup             Configure the PBX connection + softphone
  nn pbx doctor            Run connectivity diagnostics
  nn pbx detect            Detect the live Asterisk/PJSIP topology
  nn pbx phone             Open the softphone directly
  nn pbx test-call         Run the 3000 → LiveKit agent test
  nn calls                 Active channel / call table
  nn trunks                Outbound SIP trunk registrations
  nn debug                 SIP/AMI event stream
  nn --version / --help
""")
    elif scope == "pbx":
        print(f"""nn pbx · {VERSION}

Usage:
  nn pbx                 PBX console TUI
  nn pbx setup           Configure the connection
  nn pbx doctor          Run diagnostics
  nn pbx detect          Detect transports/endpoints/trunks
  nn pbx phone           Open the softphone
  nn pbx test-call       Exercise baresip → 3000 → LiveKit
  nn pbx console         Alias for the PBX console

Key bindings inside the TUI:
  Tab / 1-6              Switch tabs
  r                      Refresh
  F5                     Force refresh right now
  F4                     Open the loopback AMI SSH tunnel
  q                      Quit
""")


if __name__ == "__main__":
    sys.exit(main())
