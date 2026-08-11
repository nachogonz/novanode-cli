import getpass
import os
import secrets as pysecrets
import socket

import config as nnconfig
from connection import Runner
from pbx import PBX

MANAGER_CONF = "/etc/asterisk/manager.conf"
MANAGED_CONF = "/etc/asterisk/manager_novanode.conf"
INCLUDE_LINE = "#include manager_novanode.conf"


def prompt(label, default="", secret=False, required=True):
    suffix = f" [default: {default}]" if default else ""
    while True:
        try:
            if secret:
                value = getpass.getpass(f"  {label}{suffix}: ")
            else:
                value = input(f"  {label}{suffix}: ")
        except (EOFError, KeyboardInterrupt):
            print()
            raise
        value = value.strip()
        if not value and default:
            return default
        if value:
            return value
        if not required:
            return ""


def ssh_ok(ssh_host, ssh_user):
    import subprocess

    target = ssh_user + "@" + ssh_host if ssh_user else ssh_host
    try:
        proc = subprocess.run(
            ["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=8", target, "true"],
            capture_output=True, text=True, timeout=10,
        )
        return proc.returncode == 0, proc.stderr.strip()
    except Exception as e:
        return False, str(e)


def detect_remote(cfg):
    pbx = PBX(cfg)
    info = {}
    info["version"] = pbx.core_version()
    info["transports"] = pbx.transports()
    info["endpoints"] = pbx.endpoints_long()
    info["registrations"] = pbx.registrations()
    info["modules_pjsip"] = pbx.module_loaded("res_pjsip")
    try:
        mgr = pbx.runner.read_remote_file(MANAGER_CONF)
        info["manager_conf_exists"] = True
        info["manager_novanode"] = "novanode-tui" in mgr
    except Exception:
        info["manager_conf_exists"] = False
        info["manager_novanode"] = False
    return info


def render_propose(title, lines):
    print()
    print(f"  ┌─ {title} " + "─" * (48 - len(title) - 6) + "┐")
    for line in lines:
        print(f"  │  {line}")
    print("  └" + "─" * 50 + "┘")
    print()


def confirm(msg, default=True):
    suffix = " [Y/n]" if default else " [y/N]"
    while True:
        try:
            value = input(f"  {msg}{suffix}: ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            print()
            return False
        if not value:
            return default
        if value in ("y", "yes"):
            return True
        if value in ("n", "no"):
            return False


def run_setup():
    print()
    print("  NovaNode TUI · configure a live Asterisk (nn-pbx) box")
    print("  Credentials stay outside git: secrets file (0600) + env only.")
    print()

    cfg = nnconfig.load_config()
    p = cfg["pbx"]

    p["name"] = prompt("PBX name/label", p["name"])
    p["host"] = prompt("PBX host (VM IP)", p["host"])
    p["ssh_host"] = prompt("SSH host (same host = leave default)", p["ssh_host"] or p["host"], required=False)
    p["ssh_user"] = prompt("SSH user (key auth)", p["ssh_user"])

    ok, err = ssh_ok(p["ssh_host"], p["ssh_user"])
    if not ok:
        print(f"\n  ⚠ SSH not reachable: {err or 'auth failed'}")
        print("    Add a key or check the VM before continuing. Config still saved.")
        p["via_ssh"] = True
    else:
        p["via_ssh"] = True
        print("  ✓ SSH reachable — live detection enabled.")

    print()
    print("  Detecting the box…")
    try:
        info = detect_remote(cfg)
    except Exception as e:
        info = {}
        print(f"  ⚠ detection failed: {e}")

    print()
    print(f"  Asterisk      {info.get('version', 'n/a')}")
    transp = info.get("transports") or []
    tstr = ", ".join(f"{t['type']} {t['bind']}" for t in transp) or "n/a"
    print(f"  Transports    {tstr}")
    eps = info.get("endpoints") or []
    names = ", ".join(e["name"] for e in eps)
    print(f"  Endpoints     {names or 'n/a'}")
    print(f"  PJSIP stack   {'loaded ✓' if info.get('modules_pjsip') else 'n/a'}")

    render_propose("Proposed changes", [
        "1  Enable AMI on 127.0.0.1:5038 (loopback only)",
        "2  Add [novanode-tui] manager account — restricted, random password",
        "3  Back up manager.conf → *.novanode-bak (never rewrite a working PBX)",
        "4  Store credentials in ~/.config/novanode/secrets.json (0600)",
        "5  Touches only the Novanode-owned block, not your endpoints/dialplan",
    ])

    remote_ok = True
    if confirm("Apply these changes to the nn-pbx VM?"):
        remote_ok = apply_remote(cfg, info)
    else:
        print("  Skipped remote changes — saved local config only.")

    ph = cfg["phone"]
    print()
    print("  ┌─ Softphone (drives baresip on the Fedora host) ────────────┐")
    ph["extension"] = prompt("Your extension", ph["extension"])
    ph["display_name"] = prompt("Display name", ph["display_name"])
    ph["sip_user"] = prompt("SIP username", ph["sip_user"] or ph["extension"])
    ph["codec"] = prompt("Preferred codec", ph["codec"])
    ph["ssh_host"] = prompt("Fedora baresip SSH host", ph.get("ssh_host") or "192.168.0.23")
    ph["ssh_user"] = prompt("Fedora SSH user", ph.get("ssh_user") or os.environ.get("USER", ""))

    cfg["pbx"] = p
    cfg["phone"] = ph
    nnconfig.save_config(cfg)

    print()
    print(f"  Saved local config → {nnconfig.CONFIG_PATH}")
    print()
    print("  Next steps:")
    print("    nn pbx doctor     verify the six sections against the live box")
    print("    nn pbx            open the PBX console")
    print("    nn pbx phone      drive baresip → 3000 (LiveKit agent)")
    print()
    return 0 if remote_ok else 1


def update_manager_general(contents):
    lines = contents.splitlines()
    wanted = {
        "enabled": "yes",
        "webenabled": "no",
        "port": "5038",
        "bindaddr": "127.0.0.1",
    }
    out = []
    in_general = False
    seen_general = False
    written = set()

    def finish_general():
        for key, value in wanted.items():
            if key not in written:
                out.append(f"{key} = {value}")

    for line in lines:
        stripped = line.strip()
        if stripped.startswith("[") and stripped.endswith("]"):
            if in_general:
                finish_general()
            in_general = stripped.lower() == "[general]"
            seen_general = seen_general or in_general
            written = set()
            out.append(line)
            continue
        if in_general and "=" in stripped and not stripped.startswith((";", "#")):
            key = stripped.split("=", 1)[0].strip().lower()
            if key in wanted:
                out.append(f"{key} = {wanted[key]}")
                written.add(key)
                continue
        out.append(line)
    if in_general:
        finish_general()
    if not seen_general:
        prefix = ["[general]"] + [f"{key} = {value}" for key, value in wanted.items()] + [""]
        out = prefix + out
    if not any(line.strip() == INCLUDE_LINE for line in out):
        out.extend(["", "; Novanode-owned restricted AMI account", INCLUDE_LINE])
    return "\n".join(out).rstrip() + "\n"


def apply_remote(cfg, info):
    p = cfg["pbx"]
    pbx = PBX(cfg)
    runner = pbx.runner
    password = pysecrets.token_urlsafe(18)

    try:
        existing = runner.read_remote_file(MANAGER_CONF) if runner.remote_file_exists(MANAGER_CONF) else ""
    except Exception as exc:
        print(f"  ✗ refusing to modify unreadable {MANAGER_CONF}: {exc}")
        return False

    manager_conf = update_manager_general(existing)
    managed_conf = (
        "; Managed by `nn pbx setup`; do not commit this file.\n"
        + "[novanode-tui]\n"
        + f"secret = {password}\n"
        + "deny = 0.0.0.0/0.0.0.0\n"
        + "permit = 127.0.0.1/255.255.255.255\n"
        + "read = system,call,reporting\n"
        + "write = none\n"
        + "displayconnects = no\n"
    )

    try:
        runner.write_remote_file(MANAGER_CONF, manager_conf)
        runner.write_remote_file(MANAGED_CONF, managed_conf)
    except Exception as e:
        print(f"  ✗ could not write AMI configuration: {e}")
        return False

    try:
        runner.run("manager reload")
        print("  ✓ manager.conf updated + manager reloaded (backup .novanode-bak created)")
    except Exception as e:
        print(f"  ✗ config written but 'manager reload' failed: {e}")
        return False

    secrets = nnconfig.load_secrets()
    secrets["ami_secret"] = password
    nnconfig.save_secrets(secrets)
    print(f"  ✓ AMI secret stored in {nnconfig.SECRETS_PATH} (0600)")
    print("    Tip: export NOVANODE_AMI_SECRET to keep it out of the local secret file.")
    return True
