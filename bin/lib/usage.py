import json
import os
import select
import sqlite3
import subprocess
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime


CACHE_DIR = os.path.expanduser("~/.cache/novanode")


def command_version(command):
    try:
        output = subprocess.check_output([command, "--version"], stderr=subprocess.DEVNULL, text=True, timeout=3)
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
    if max_age is not None and time.time() - data.get("fetched_at", 0) > max_age:
        return None
    return data.get("payload")


def claude_token():
    token = os.environ.get("CLAUDE_ACCESS_TOKEN")
    if token:
        return token
    if os.uname().sysname == "Darwin":
        try:
            raw = subprocess.check_output(
                ["security", "find-generic-password", "-s", "Claude Code-credentials", "-w"],
                stderr=subprocess.DEVNULL,
                text=True,
                timeout=3,
            )
            return json.loads(raw).get("claudeAiOauth", {}).get("accessToken")
        except Exception:
            pass
    for path in ("~/.claude/.credentials.json", "~/.config/claude/credentials.json"):
        data = load_json(os.path.expanduser(path)) or {}
        token = data.get("claudeAiOauth", {}).get("accessToken") or data.get("accessToken")
        if token:
            return token
    return None


def fetch_claude():
    version = command_version("claude")
    payload = load_cache("claude-usage", 30)
    if payload is None:
        token = claude_token()
        if token:
            request = urllib.request.Request(
                "https://api.anthropic.com/api/oauth/usage",
                headers={
                    "Authorization": f"Bearer {token}",
                    "anthropic-beta": "oauth-2025-04-20",
                    "User-Agent": f"claude-code/{version}",
                    "Accept": "application/json",
                },
            )
            try:
                with urllib.request.urlopen(request, timeout=6) as response:
                    payload = json.loads(response.read().decode("utf-8"))
                    save_cache("claude-usage", payload)
            except Exception:
                payload = None
    payload = payload or load_cache("claude-usage") or {}
    five = payload.get("five_hour") or {}
    week = payload.get("seven_day") or {}
    return make_row(
        "claude",
        "claude",
        version,
        ("5h", five.get("utilization"), reset_label(five.get("resets_at"))),
        ("Weekly", week.get("utilization"), reset_label(week.get("resets_at"), weekly=True)),
    )


def codex_rate_limits():
    try:
        process = subprocess.Popen(
            ["codex", "app-server", "--stdio"],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            bufsize=1,
        )
    except OSError:
        return None
    request = (
        '{"jsonrpc":"2.0","id":1,"method":"initialize",'
        '"params":{"clientInfo":{"name":"nn-usage","version":"1.1.0"}}}\n'
        '{"jsonrpc":"2.0","id":2,"method":"account/rateLimits/read","params":{}}\n'
    )
    try:
        process.stdin.write(request)
        process.stdin.flush()
        deadline = time.monotonic() + 8
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
            if message.get("id") == 2:
                return (message.get("result") or {}).get("rateLimits")
    finally:
        process.kill()
        try:
            process.wait(timeout=1)
        except Exception:
            pass
    return None


def codex_rate_limits_from_cache():
    path = os.path.expanduser("~/.codex/logs_2.sqlite")
    if not os.path.isfile(path):
        return None
    try:
        connection = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
        row = connection.execute(
            "SELECT feedback_log_body FROM logs "
            "WHERE feedback_log_body LIKE '%\"type\":\"codex.rate_limits\"%' "
            "ORDER BY ts DESC LIMIT 1"
        ).fetchone()
        connection.close()
        if not row:
            return None
        start = row[0].find("{")
        return json.loads(row[0][start:]).get("rate_limits") if start >= 0 else None
    except Exception:
        return None


def normalize_codex_window(window):
    if not window:
        return None
    return {
        "used": window.get("usedPercent", window.get("used_percent")),
        "reset": window.get("resetsAt", window.get("reset_at")),
        "duration": window.get("windowDurationMins", window.get("window_duration_mins")),
    }


def fetch_codex():
    version = command_version("codex")
    limits = codex_rate_limits() or codex_rate_limits_from_cache() or {}
    windows = [normalize_codex_window(limits.get(key)) for key in ("primary", "secondary")]
    windows = [window for window in windows if window]
    short = next((window for window in windows if not window.get("duration") or window["duration"] <= 360), None)
    weekly = next((window for window in windows if window.get("duration") and window["duration"] > 360), None)
    return make_row(
        "codex",
        "codex",
        version,
        ("5h", short.get("used") if short else None, reset_label(short.get("reset") if short else None)),
        ("Weekly", weekly.get("used") if weekly else None, reset_label(weekly.get("reset") if weekly else None, weekly=True)),
    )


def fetch_usage():
    with ThreadPoolExecutor(max_workers=2) as pool:
        claude = pool.submit(fetch_claude)
        codex = pool.submit(fetch_codex)
        return [claude.result(), codex.result()]


def pct_num(value):
    return percent(str(value).strip().rstrip("%"))
