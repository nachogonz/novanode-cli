import json
import os
import select
import shutil
import sqlite3
import subprocess
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime

import usage_accounts


CACHE_DIR = os.path.expanduser(
    os.environ.get("NOVANODE_USAGE_CACHE_DIR", "~/.cache/novanode")
)
STALE_CACHE_MAX_AGE = 120


def command_version(command, env=None):
    try:
        output = subprocess.check_output(
            [command, "--version"], stderr=subprocess.DEVNULL, text=True, timeout=3, env=env
        )
        return output.strip().splitlines()[0].replace(" (Claude Code)", "").replace("codex-cli ", "")
    except Exception:
        return "n/a"


def percent(value):
    try:
        return max(0.0, min(100.0, float(value)))
    except (TypeError, ValueError):
        return None


def reset_label(value, weekly=False):
    if value in (None, ""):
        return "n/a"
    try:
        if isinstance(value, (int, float)):
            stamp = float(value)
            if stamp > 1e12:
                stamp /= 1000
            dt = datetime.fromtimestamp(stamp).astimezone()
        else:
            text = str(value).replace("Z", "+00:00")
            dt = datetime.fromisoformat(text).astimezone()
        return dt.strftime("%-d %b") if weekly else dt.strftime("%H:%M")
    except Exception:
        return "n/a"


def empty_row(key, command, version, first="5h", second="Weekly"):
    return {
        "key": key,
        "command": command,
        "version": version,
        "p1": first,
        "used1": "n/a",
        "left1": "n/a",
        "reset1": "n/a",
        "p2": second,
        "used2": "n/a",
        "left2": "n/a",
        "reset2": "n/a",
    }


def make_row(key, command, version, first, second):
    row = empty_row(key, command, version, first[0], second[0])
    for index, window in enumerate((first, second), 1):
        used = percent(window[1])
        row[f"used{index}"] = "n/a" if used is None else f"{used:g}"
        row[f"left{index}"] = "n/a" if used is None else f"{max(0, 100 - used):g}"
        row[f"reset{index}"] = window[2]
    return row


def load_json(path):
    try:
        with open(path) as handle:
            data = json.load(handle)
            return data if isinstance(data, dict) else None
    except (OSError, ValueError):
        return None


def save_cache(name, payload):
    try:
        os.makedirs(CACHE_DIR, exist_ok=True)
        path = os.path.join(CACHE_DIR, name + ".json")
        with open(path, "w") as handle:
            json.dump({"fetched_at": time.time(), "payload": payload}, handle)
    except OSError:
        pass


def load_cache(name, max_age=None):
    data = load_json(os.path.join(CACHE_DIR, name + ".json"))
    if not data:
        return None
    if max_age is not None:
        try:
            if time.time() - float(data.get("fetched_at", 0)) > max_age:
                return None
        except (TypeError, ValueError):
            return None
    return data.get("payload")


def account_cache_name(prefix, account):
    account_id = (account or {}).get("id", "profile")
    safe_id = "".join(char if char.isalnum() or char in "-_" else "-" for char in account_id)
    return f"{prefix}-{safe_id}"


def decorate_row(row, account):
    provider = account["provider"]
    base_key = "codex" if provider == "openai" else "claude"
    base_name = "Codex CLI" if provider == "openai" else "Claude Code"
    row["key"] = f"{base_key}:{account['slug']}"
    row["provider"] = provider
    row["profile"] = account["label"]
    row["name"] = f"{base_name} · {account['label']}"
    return row


def _fetch_json(url, headers, timeout=12):
    """GET a JSON URL. Falls back to curl (system trust store) if Python's
    SSL context has no CA bundle — common with the python.org installer."""
    request = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.URLError as error:
        reason = getattr(error, "reason", None)
        ssl_broken = reason.__class__.__name__ == "SSLCertVerificationError" if reason else False
        if not ssl_broken and "CERTIFICATE_VERIFY_FAILED" not in str(error):
            return None
    except Exception:
        return None
    curl = shutil.which("curl") if callable(getattr(shutil, "which", None)) else None
    if not curl:
        return None
    args = [curl, "-fsSL", "--max-time", str(timeout)]
    for key, value in headers.items():
        args += ["-H", f"{key}: {value}"]
    args.append(url)
    try:
        output = subprocess.check_output(args, stderr=subprocess.DEVNULL,
                                          timeout=timeout + 2)
        return json.loads(output)
    except (OSError, subprocess.SubprocessError, ValueError):
        return None


def fetch_claude(account):
    env = usage_accounts.account_env(account)
    version = command_version("claude", env=env)
    cache_name = account_cache_name("claude-usage", account)
    payload = load_cache(cache_name, 30)
    if payload is None:
        token = usage_accounts.claude_token(account)
        if token:
            payload = _fetch_json(
                "https://api.anthropic.com/api/oauth/usage",
                headers={
                    "Authorization": f"Bearer {token}",
                    "anthropic-beta": "oauth-2025-04-20",
                    "User-Agent": f"claude-code/{version}",
                    "Accept": "application/json",
                },
            )
            if payload is not None:
                save_cache(cache_name, payload)
    # If the fresh fetch failed, accept a slightly older cached snapshot before
    # blanking the card — brief API flakes shouldn't erase a working reading.
    payload = payload or load_cache(cache_name, 300) or load_cache(cache_name, STALE_CACHE_MAX_AGE)
    live = isinstance(payload, dict)
    payload = payload or {}
    five = payload.get("five_hour") or {}
    week = payload.get("seven_day") or {}
    row = decorate_row(make_row(
        "claude",
        "claude",
        version,
        ("5h", five.get("utilization"), reset_label(five.get("resets_at"))),
        ("Weekly", week.get("utilization"), reset_label(week.get("resets_at"), weekly=True)),
    ), account)
    row["usage_status"] = "live" if live else "unavailable"
    return row


def _write_json_message(process, message):
    process.stdin.write(json.dumps(message, separators=(",", ":")) + "\n")
    process.stdin.flush()


def codex_rate_limits(account):
    try:
        process = subprocess.Popen(
            ["codex", "app-server", "--stdio"],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            bufsize=1,
            env=usage_accounts.account_env(account),
        )
    except OSError:
        return None
    try:
        # Complete the app-server handshake before asking for account data.
        # Pipelining this request with initialize is racy across CLI releases.
        _write_json_message(process, {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {"clientInfo": {"name": "nn-usage", "version": "1.2.6"}},
        })
        deadline = time.monotonic() + 8
        initialized = False
        while time.monotonic() < deadline:
            ready, _, _ = select.select([process.stdout], [], [], 0.25)
            if not ready:
                continue
            line = process.stdout.readline()
            if not line:
                break
            try:
                message = json.loads(line)
            except ValueError:
                continue
            if message.get("id") == 1 and not initialized:
                if message.get("error"):
                    return None
                _write_json_message(process, {
                    "jsonrpc": "2.0",
                    "method": "initialized",
                    "params": {},
                })
                _write_json_message(process, {
                    "jsonrpc": "2.0",
                    "id": 2,
                    "method": "account/rateLimits/read",
                    "params": {},
                })
                initialized = True
                continue
            if message.get("id") == 2:
                result = message.get("result") or {}
                limits = result.get("rateLimits")
                if limits:
                    return limits
                by_id = result.get("rateLimitsByLimitId") or {}
                return by_id.get("codex") or next(iter(by_id.values()), None)
    except (BrokenPipeError, OSError):
        return None
    finally:
        if process.poll() is None:
            process.kill()
        try:
            process.wait(timeout=1)
        except Exception:
            pass
    return None


def codex_rate_limits_from_cache(account):
    home = account.get("home") or os.environ.get("CODEX_HOME") or "~/.codex"
    path = os.path.join(os.path.expanduser(home), "logs_2.sqlite")
    if not os.path.isfile(path):
        return None
    try:
        connection = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
        row = connection.execute(
            "SELECT ts, feedback_log_body FROM logs "
            "WHERE feedback_log_body LIKE '%\"type\":\"codex.rate_limits\"%' "
            "ORDER BY ts DESC LIMIT 1"
        ).fetchone()
        connection.close()
        if not row or not timestamp_is_recent(row[0], STALE_CACHE_MAX_AGE):
            return None
        start = row[1].find("{")
        return json.loads(row[1][start:]).get("rate_limits") if start >= 0 else None
    except Exception:
        return None


def timestamp_is_recent(value, max_age):
    try:
        stamp = float(value)
        while stamp > 100_000_000_000:
            stamp /= 1000
    except (TypeError, ValueError):
        try:
            stamp = datetime.fromisoformat(str(value).replace("Z", "+00:00")).timestamp()
        except (TypeError, ValueError):
            return False
    age = time.time() - stamp
    return -300 <= age <= max_age


def normalize_codex_window(window):
    if not window:
        return None
    return {
        "used": window.get("usedPercent", window.get("used_percent")),
        "reset": window.get("resetsAt", window.get("reset_at")),
        "duration": window.get("windowDurationMins", window.get("window_duration_mins")),
    }


def fetch_codex(account):
    env = usage_accounts.account_env(account)
    version = command_version("codex", env=env)
    limits = codex_rate_limits(account) or codex_rate_limits_from_cache(account)
    live = isinstance(limits, dict)
    limits = limits or {}
    windows = [normalize_codex_window(limits.get(key)) for key in ("primary", "secondary")]
    windows = [window for window in windows if window]
    short = next((window for window in windows if not window.get("duration") or window["duration"] <= 360), None)
    weekly = next((window for window in windows if window.get("duration") and window["duration"] > 360), None)
    row = decorate_row(make_row(
        "codex",
        "codex",
        version,
        ("5h", short.get("used") if short else None, reset_label(short.get("reset") if short else None)),
        ("Weekly", weekly.get("used") if weekly else None, reset_label(weekly.get("reset") if weekly else None, weekly=True)),
    ), account)
    row["usage_status"] = "live" if live else "unavailable"
    return row


def fetch_usage():
    accounts = usage_accounts.active_accounts()
    with ThreadPoolExecutor(max_workers=min(6, max(1, len(accounts)))) as pool:
        checks = [pool.submit(usage_accounts.connection_status, account) for account in accounts]
        states = {
            account["id"]: check.result() for account, check in zip(accounts, checks)
        }
    try:
        usage_accounts.record_statuses(accounts, states)
    except OSError:
        pass
    accounts = [
        account for account in accounts
        if states[account["id"]].get("connected")
    ]
    if not accounts:
        return []
    with ThreadPoolExecutor(max_workers=min(6, max(1, len(accounts)))) as pool:
        futures = []
        for account in accounts:
            fetcher = fetch_codex if account["provider"] == "openai" else fetch_claude
            futures.append(pool.submit(fetcher, account))
        return [future.result() for future in futures]


def pct_num(value):
    return percent(str(value).strip().rstrip("%"))
