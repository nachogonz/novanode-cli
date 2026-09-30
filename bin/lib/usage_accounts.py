"""Named provider profiles for the NovaNode usage dashboard.

NovaNode stores profile metadata only. Authentication remains owned by the
official Codex and Claude CLIs inside isolated provider configuration homes.
"""

import getpass
import json
import os
import re
import shutil
import stat
import subprocess
import sys
import tempfile
from datetime import datetime, timezone


ACCOUNTS_PATH = os.path.expanduser(
    os.environ.get("NOVANODE_USAGE_ACCOUNTS_PATH", "~/.config/novanode/usage-accounts.json")
)
PROFILES_DIR = os.path.expanduser(
    os.environ.get("NOVANODE_USAGE_PROFILES_DIR", "~/.config/novanode/providers")
)
CACHE_DIR = os.path.expanduser(
    os.environ.get("NOVANODE_USAGE_CACHE_DIR", "~/.cache/novanode")
)
PROVIDERS = {
    "openai": {
        "title": "OpenAI / Codex",
        "command": "codex",
        "home_env": "CODEX_HOME",
    },
    "claude": {
        "title": "Anthropic / Claude",
        "command": "claude",
        "home_env": "CLAUDE_CONFIG_DIR",
    },
}


def slugify(value):
    slug = re.sub(r"[^a-z0-9]+", "-", str(value).strip().lower()).strip("-")
    return slug[:48] or "personal"


def load_accounts(path=None):
    path = path or ACCOUNTS_PATH
    try:
        with open(path) as handle:
            payload = json.load(handle)
    except (OSError, ValueError):
        return []
    rows = payload.get("accounts", []) if isinstance(payload, dict) else []
    accounts = []
    seen = set()
    for row in rows:
        if not isinstance(row, dict) or row.get("provider") not in PROVIDERS:
            continue
        label = str(row.get("label") or "Personal").strip()[:64]
        slug = slugify(row.get("slug") or label)
        account_id = f"{row['provider']}:{slug}"
        if account_id in seen:
            continue
        # Managed homes are derived, never trusted from editable registry data.
        home = profile_home(row["provider"], slug)
        accounts.append(
            {
                "id": account_id,
                "provider": row["provider"],
                "label": label,
                "slug": slug,
                "home": os.path.abspath(os.path.expanduser(home)),
                "managed": True,
                "created_at": row.get("created_at"),
                "connected_at": row.get("connected_at"),
                "last_seen_at": row.get("last_seen_at"),
                "cli_version": row.get("cli_version"),
                "last_seen_version": row.get("last_seen_version"),
            }
        )
        seen.add(account_id)
    return accounts


def save_accounts(accounts, path=None):
    path = path or ACCOUNTS_PATH
    parent = os.path.dirname(path) or "."
    os.makedirs(parent, mode=0o700, exist_ok=True)
    serializable = []
    for account in accounts:
        if not account.get("managed"):
            continue
        serializable.append(
            {
                "provider": account["provider"],
                "label": account["label"],
                "slug": account["slug"],
                "home": account["home"],
                "created_at": account.get("created_at"),
                "connected_at": account.get("connected_at"),
                "last_seen_at": account.get("last_seen_at"),
                "cli_version": account.get("cli_version"),
                "last_seen_version": account.get("last_seen_version"),
            }
        )
    fd, temporary = tempfile.mkstemp(prefix=".usage-accounts-", dir=parent, text=True)
    try:
        os.fchmod(fd, stat.S_IRUSR | stat.S_IWUSR)
        with os.fdopen(fd, "w") as handle:
            json.dump({"version": 2, "accounts": serializable}, handle, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        try:
            os.unlink(temporary)
        except OSError:
            pass


def all_accounts():
    return load_accounts()


def profile_home(provider, slug):
    return os.path.join(PROFILES_DIR, provider, slugify(slug))


def account_for(provider, label):
    if provider not in PROVIDERS:
        raise ValueError(f"Unsupported provider: {provider}")
    label = str(label or "Personal").strip()[:64] or "Personal"
    slug = slugify(label)
    account_id = f"{provider}:{slug}"
    existing = next((row for row in load_accounts() if row["id"] == account_id), None)
    if existing:
        return existing
    return {
        "id": account_id,
        "provider": provider,
        "label": label,
        "slug": slug,
        "home": os.path.abspath(profile_home(provider, slug)),
        "managed": True,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }


def remember_account(account):
    accounts = load_accounts()
    accounts = [row for row in accounts if row["id"] != account["id"]]
    accounts.append(account)
    save_accounts(accounts)


def account_env(account):
    env = os.environ.copy()
    home = account.get("home")
    if home:
        env[PROVIDERS[account["provider"]]["home_env"]] = home
    if account["provider"] == "openai" and home:
        for key in (
            "OPENAI_API_KEY",
            "CODEX_API_KEY",
            "CODEX_ACCESS_TOKEN",
            "CHATGPT_ACCESS_TOKEN",
        ):
            env.pop(key, None)
    if account["provider"] == "claude" and home:
        for key in (
            "ANTHROPIC_API_KEY",
            "ANTHROPIC_AUTH_TOKEN",
            "ANTHROPIC_PROFILE",
            "ANTHROPIC_FEDERATION_RULE_ID",
            "ANTHROPIC_ORGANIZATION_ID",
            "CLAUDE_ACCESS_TOKEN",
            "CLAUDE_CODE_OAUTH_TOKEN",
            "CLAUDE_CODE_USE_BEDROCK",
            "CLAUDE_CODE_USE_VERTEX",
            "CLAUDE_CODE_USE_FOUNDRY",
        ):
            env.pop(key, None)
    return env


def claude_config_home(account):
    """Return the exact config directory Claude uses for this account."""
    home = account.get("home")
    if not home:
        home = os.environ.get("CLAUDE_CONFIG_DIR") or "~/.claude"
    return os.path.abspath(os.path.expanduser(home))


def _credential_json(path):
    try:
        with open(path) as handle:
            payload = json.load(handle)
            return payload if isinstance(payload, dict) else {}
    except (OSError, ValueError):
        return {}


def _keychain_token(account_arg):
    if sys.platform != "darwin":
        return None
    try:
        raw = subprocess.check_output(
            [
                "security",
                "find-generic-password",
                "-a",
                account_arg,
                "-s",
                "Claude Code-credentials",
                "-w",
            ],
            stderr=subprocess.DEVNULL,
            text=True,
            timeout=3,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    try:
        payload = json.loads(raw)
    except ValueError:
        return None
    if not isinstance(payload, dict):
        return None
    return payload.get("claudeAiOauth", {}).get("accessToken") or payload.get("accessToken")


def claude_token(account):
    """Read Claude's OAuth token from the provider-owned credential store.

    Claude Code currently keys its macOS Keychain entry by the login username,
    not by CLAUDE_CONFIG_DIR. We try the path-scoped entry first (in case
    future Claude versions isolate per profile), then fall back to the
    standard user-scoped entry and to a `.credentials.json` inside the
    isolated profile.
    """
    home = claude_config_home(account)
    for arg in (home, os.environ.get("USER") or getpass.getuser()):
        if not arg:
            continue
        token = _keychain_token(arg)
        if token:
            return token

    payload = _credential_json(os.path.join(home, ".credentials.json"))
    return payload.get("claudeAiOauth", {}).get("accessToken") or payload.get("accessToken")


def prepare_profile(account):
    home = account.get("home")
    if not home:
        return
    os.makedirs(home, mode=0o700, exist_ok=True)
    try:
        os.chmod(home, 0o700)
    except OSError:
        pass
    if account["provider"] != "openai":
        return
    config_path = os.path.join(home, "config.toml")
    try:
        with open(config_path) as handle:
            config = handle.read()
    except FileNotFoundError:
        config = '# NovaNode named profile; credentials stay inside this CODEX_HOME.\n'
    setting = 'cli_auth_credentials_store = "file"'
    pattern = r"(?m)^\s*cli_auth_credentials_store\s*=.*$"
    if re.search(pattern, config):
        updated = re.sub(pattern, setting, config)
    else:
        updated = config.rstrip() + "\n" + setting + "\n"
    if updated == config:
        return
    fd, temporary = tempfile.mkstemp(prefix=".config-", dir=home, text=True)
    try:
        os.fchmod(fd, stat.S_IRUSR | stat.S_IWUSR)
        with os.fdopen(fd, "w") as handle:
            handle.write(updated)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, config_path)
    finally:
        try:
            os.unlink(temporary)
        except OSError:
            pass


def provider_installed(provider):
    return bool(shutil.which(PROVIDERS[provider]["command"]))


def provider_version(account):
    command = PROVIDERS[account["provider"]]["command"]
    if not shutil.which(command):
        return None
    try:
        output = subprocess.check_output(
            [command, "--version"],
            env=account_env(account),
            stderr=subprocess.DEVNULL,
            text=True,
            timeout=3,
        )
        version = output.strip().splitlines()[0]
        return version.replace(" (Claude Code)", "").replace("codex-cli ", "") or None
    except (OSError, subprocess.SubprocessError):
        return None


def has_isolated_openai_store(account, require_auth=True):
    home = account.get("home")
    if account.get("provider") != "openai" or not account.get("managed") or not home:
        return False
    try:
        with open(os.path.join(home, "config.toml")) as handle:
            config = handle.read()
    except OSError:
        return False
    file_store = bool(re.search(
        r"(?m)^\s*cli_auth_credentials_store\s*=\s*['\"]file['\"]\s*$",
        config,
    ))
    return file_store and (not require_auth or os.path.isfile(os.path.join(home, "auth.json")))


def connection_status(account):
    provider = account["provider"]
    command = PROVIDERS[provider]["command"]
    if not shutil.which(command):
        return {"connected": False, "detail": f"{command} not installed", "version": None}
    version = provider_version(account)
    if provider == "openai" and account.get("managed") and not has_isolated_openai_store(account):
        return {"connected": False, "detail": "reconnect required", "version": version}
    try:
        if provider == "openai":
            result = subprocess.run(
                [command, "login", "status"],
                env=account_env(account),
                capture_output=True,
                text=True,
                timeout=6,
            )
            output = (result.stdout or result.stderr or "").strip()
            connected = result.returncode == 0 and "not logged" not in output.lower()
            detail = "ChatGPT session" if connected else "not connected"
            return {"connected": connected, "detail": detail, "version": version}
        result = subprocess.run(
            [command, "auth", "status", "--json"],
            env=account_env(account),
            capture_output=True,
            text=True,
            timeout=6,
        )
        try:
            payload = json.loads(result.stdout or "{}")
        except ValueError:
            payload = {}
        connected = bool(payload.get("loggedIn"))
        detail = payload.get("authMethod") if connected else "not connected"
        return {"connected": connected, "detail": detail or "connected", "version": version}
    except (OSError, subprocess.SubprocessError):
        return {"connected": False, "detail": "status unavailable", "version": version}


def record_statuses(accounts, statuses):
    """Persist lightweight session history without copying provider credentials."""
    managed = {row["id"]: row for row in load_accounts()}
    changed = False
    now_dt = datetime.now(timezone.utc)
    now = now_dt.isoformat()
    for account in accounts:
        stored = managed.get(account["id"])
        current = statuses.get(account["id"], {})
        if not stored or not current.get("connected"):
            continue
        version = current.get("version")
        try:
            last_seen = datetime.fromisoformat(
                str(stored.get("last_seen_at")).replace("Z", "+00:00")
            )
            refresh_seen = (now_dt - last_seen.astimezone(timezone.utc)).total_seconds() >= 60
        except (TypeError, ValueError):
            refresh_seen = True
        if refresh_seen:
            stored["last_seen_at"] = now
            changed = True
        if version and stored.get("last_seen_version") != version:
            stored["last_seen_version"] = version
            changed = True
    if changed:
        save_accounts(list(managed.values()))


def connect_account(account):
    provider = account["provider"]
    command = PROVIDERS[provider]["command"]
    if not shutil.which(command):
        return False, f"{command} is not installed"
    try:
        prepare_profile(account)
    except OSError as error:
        return False, f"could not prepare the profile directory: {error}"
    args = [command, "login"] if provider == "openai" else [command, "auth", "login", "--claudeai"]
    try:
        result = subprocess.run(args, env=account_env(account))
    except OSError as error:
        return False, str(error)
    if result.returncode != 0:
        return False, f"{command} login exited with status {result.returncode}"
    status = connection_status(account)
    if not status["connected"]:
        return False, "login finished but no active session was detected"
    now = datetime.now(timezone.utc).isoformat()
    account["connected_at"] = now
    account["last_seen_at"] = now
    account["cli_version"] = status.get("version")
    account["last_seen_version"] = status.get("version")
    try:
        remember_account(account)
    except OSError as error:
        return False, f"signed in, but could not save the profile metadata: {error}"
    return True, status["detail"]


def removable_account(account_id):
    return next((row for row in load_accounts() if row["id"] == account_id), None)


def _safe_profile_path(account):
    """Return the verified managed path, or raise before any recursive deletion."""
    if not account.get("managed") or not account.get("home"):
        raise ValueError("only NovaNode-managed profiles can be removed")
    root = os.path.realpath(PROFILES_DIR)
    raw_home = os.path.abspath(os.path.expanduser(account["home"]))
    raw_expected = os.path.abspath(profile_home(account["provider"], account["slug"]))
    home = os.path.realpath(raw_home)
    expected = os.path.realpath(raw_expected)
    try:
        within_root = os.path.commonpath((root, home)) == root
    except ValueError:
        within_root = False
    if (
        root == os.path.sep
        or raw_home != raw_expected
        or os.path.islink(raw_home)
        or not within_root
        or home == root
        or home != expected
    ):
        raise ValueError("profile path is outside NovaNode's managed provider directory")
    return home


def remove_account(account_id):
    """Log out and remove one isolated profile, its metadata, and usage cache."""
    account = removable_account(account_id)
    if not account:
        return False, "profile was not found"
    try:
        home = _safe_profile_path(account)
    except ValueError as error:
        return False, str(error)

    provider = account["provider"]
    command = PROVIDERS[provider]["command"]
    logout = [command, "logout"] if provider == "openai" else [command, "auth", "logout"]
    scoped_logout = provider != "openai" or has_isolated_openai_store(account, require_auth=False)
    if shutil.which(command) and scoped_logout:
        try:
            subprocess.run(
                logout,
                env=account_env(account),
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=12,
            )
        except (OSError, subprocess.SubprocessError):
            pass

    try:
        if os.path.lexists(home):
            shutil.rmtree(home)
        safe_id = "".join(
            char if char.isalnum() or char in "-_" else "-" for char in account["id"]
        )
        for cache_name in (f"claude-usage-{safe_id}.json",):
            try:
                os.unlink(os.path.join(CACHE_DIR, cache_name))
            except FileNotFoundError:
                pass
        remaining = [row for row in load_accounts() if row["id"] != account_id]
        save_accounts(remaining)
    except OSError as error:
        return False, f"could not remove the local profile: {error}"
    return True, f"Removed {PROVIDERS[provider]['title']} · {account['label']}"
