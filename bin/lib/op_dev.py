"""Mock 1Password backend for `nn-op --dev`.

Mirrors the subset of `op.py` that `op_cli.py` and the Textual UI call, so
every screen renders the same whether the backend is real `op` or this mock.
Nothing talks to the real 1Password CLI; all state lives in a tmp folder
(`NNOP_DEV_HOME`, default `/tmp/novanode-dev-op`). First run seeds a demo
account, vault, env items, and access credentials so the UI has real data to
walk through.

Install the mock with `install()` — it swaps the public functions on the
`op` module in place, so no caller needs to be dev-mode-aware.
"""

import json
import os
import re
import shutil
import subprocess
import tempfile
import time
from typing import List, Optional


DEV_HOME = os.environ.get("NNOP_DEV_HOME", "/tmp/novanode-dev-op")
STATE_FILE = os.path.join(DEV_HOME, "state.json")

DEV_ACCOUNT = {
    "id": "DEVACCOUNTAAAAAAAAAAAAAA",
    "url": "nakdev.1password.com",
    "email": "dev@novanode.local",
    "shorthand": "nakdev",
    "user_uuid": "DEVUSERAAAAAAAAAAAAAAAAA",
}

DEMO_VAULT = "novanode-demo"
DEMO_APPS = ("client", "server")
DEMO_ENVS = ("development", "staging", "production")

DEMO_SECRETS = {
    "client": {
        "development": [("API_BASE_URL", "https://api.dev.novanode.local", False),
                        ("STRIPE_PUBLISHABLE_KEY", "pk_test_dev_demo", False),
                        ("SENTRY_DSN", "https://dev@sentry.novanode.local/1", True)],
        "staging": [("API_BASE_URL", "https://api.staging.novanode.local", False),
                    ("STRIPE_PUBLISHABLE_KEY", "pk_test_staging_demo", False),
                    ("SENTRY_DSN", "https://staging@sentry.novanode.local/1", True)],
        "production": [("API_BASE_URL", "https://api.novanode.com", False),
                       ("STRIPE_PUBLISHABLE_KEY", "pk_live_prod_demo", False),
                       ("SENTRY_DSN", "https://prod@sentry.novanode.local/1", True)],
    },
    "server": {
        "development": [("DATABASE_URL", "postgres://dev:dev@localhost:5432/novanode", True),
                        ("JWT_SECRET", "dev-jwt-secret-not-real", True),
                        ("REDIS_URL", "redis://localhost:6379/0", True),
                        ("LOG_LEVEL", "debug", False)],
        "staging": [("DATABASE_URL", "postgres://stg:stg@db.staging/novanode", True),
                    ("JWT_SECRET", "stg-jwt-secret-not-real", True),
                    ("REDIS_URL", "redis://redis.staging:6379/0", True),
                    ("LOG_LEVEL", "info", False)],
        "production": [("DATABASE_URL", "postgres://prod:prod@db.prod/novanode", True),
                       ("JWT_SECRET", "prod-jwt-secret-not-real", True),
                       ("REDIS_URL", "redis://redis.prod:6379/0", True),
                       ("LOG_LEVEL", "warn", False)],
    },
}

DEMO_ACCESS = [
    {"title": "AWS · Production Deploy", "tags": ["aws", "novanode-access"],
     "category": "API Credential",
     "fields": [("Access Key ID", "AKIADEMO1234567890", False),
                ("Secret Access Key", "demoSecretKey/abcdefghijklmnop", True),
                ("Region", "us-east-1", False),
                ("Account ID", "123456789012", False)]},
    {"title": "Vercel · nakdev team", "tags": ["vercel", "novanode-access"],
     "category": "API Credential",
     "fields": [("Team", "nakdev", False),
                ("Token", "vrcl_demo_token_1234", True)]},
    {"title": "Cloudflare · DNS", "tags": ["cloudflare", "novanode-access"],
     "category": "API Credential",
     "fields": [("Account ID", "deadbeefdeadbeefdeadbeefdeadbeef", False),
                ("API Token", "cf_demo_api_token", True)]},
]


# ── state ─────────────────────────────────────────────────────────────

class OpError(Exception):
    def __init__(self, message, stderr="", code=1):
        super().__init__(message)
        self.stderr = stderr
        self.code = code

    @property
    def needs_auth(self):
        text = (self.stderr or str(self)).lower()
        return any(t in text for t in (
            "you are not currently signed in", "session expired",
            "session is invalid", "no session found", "unauthorized"))


def _load() -> dict:
    try:
        with open(STATE_FILE) as handle:
            return json.load(handle)
    except (OSError, ValueError):
        return _seed()


def _save(state: dict) -> None:
    os.makedirs(DEV_HOME, exist_ok=True)
    with open(STATE_FILE, "w") as handle:
        json.dump(state, handle, indent=2)


def _seed() -> dict:
    state = {
        "accounts": [DEV_ACCOUNT],
        "signed_in": False,
        "vaults": [{"id": "DEMOVAULT1", "name": DEMO_VAULT,
                    "description": "NovaNode dev-mode demo vault"}],
        "items": [],
    }
    for app in DEMO_APPS:
        for env in DEMO_ENVS:
            fields = []
            for name, value, concealed in DEMO_SECRETS[app][env]:
                fields.append({
                    "label": name,
                    "value": value,
                    "type": "CONCEALED" if concealed else "STRING",
                })
            state["items"].append({
                "id": f"ITEM-{app}-{env}",
                "title": f"{app}-{env}",
                "vault": DEMO_VAULT,
                "category": "Secure Note",
                "tags": [app, env, "novanode-env"],
                "fields": fields,
            })
    for payload in DEMO_ACCESS:
        state["items"].append({
            "id": "ITEM-" + re.sub(r"[^a-z0-9]+", "-", payload["title"].lower()),
            "title": payload["title"],
            "vault": DEMO_VAULT,
            "category": payload["category"],
            "tags": payload["tags"],
            "fields": [{"label": name, "value": value,
                        "type": "CONCEALED" if concealed else "STRING"}
                       for name, value, concealed in payload["fields"]],
        })
    _save(state)
    return state


# ── API shaped like op.py ────────────────────────────────────────────

def which_op() -> Optional[str]:
    return "/dev/null/op-mock"


def installed() -> bool:
    return True


def version() -> Optional[str]:
    return "mock 2.30.0 (nn-op --dev)"


def whoami() -> Optional[dict]:
    state = _load()
    if not state.get("signed_in"):
        return None
    account = state["accounts"][0] if state.get("accounts") else DEV_ACCOUNT
    return {
        "url": account["url"],
        "email": account["email"],
        "user_uuid": account["user_uuid"],
        "account_uuid": account["id"],
    }


def account_list() -> List[dict]:
    return list(_load().get("accounts", []))


def signin(account: Optional[str] = None) -> int:
    state = _load()
    if not state.get("accounts"):
        return 1
    state["signed_in"] = True
    _save(state)
    return 0


def signin_session(account: Optional[str] = None) -> bool:
    return signin(account) == 0


def account_add(signin: bool = False, address: Optional[str] = None,
                email: Optional[str] = None,
                secret_key: Optional[str] = None,
                password: Optional[str] = None) -> bool:
    # Mock just logs that we received the fields; nothing persists them.
    _ = secret_key, password
    state = _load()
    new = dict(DEV_ACCOUNT)
    if address:
        new["url"] = address
        new["shorthand"] = re.sub(r"[^a-z0-9]+", "-",
                                  address.split(".")[0].lower()) or "nakdev"
    if email:
        new["email"] = email
    new["id"] = f"DEVACCOUNT-{int(time.time())}"
    existing = {a["url"] for a in state.get("accounts", [])}
    if new["url"] in existing:
        state["accounts"] = [new if a["url"] == new["url"] else a
                             for a in state["accounts"]]
    else:
        state.setdefault("accounts", []).append(new)
    if signin:
        state["signed_in"] = True
    _save(state)
    return True


def signout(account: Optional[str] = None, forget: bool = False) -> int:
    state = _load()
    state["signed_in"] = False
    if forget:
        state["accounts"] = []
    _save(state)
    return 0


def _require_auth() -> dict:
    state = _load()
    if not state.get("signed_in"):
        raise OpError("not signed in", stderr="You are not currently signed in.")
    return state


def vault_list() -> List[dict]:
    return list(_require_auth().get("vaults", []))


def vault_get(name: str) -> Optional[dict]:
    for vault in vault_list():
        if vault["name"] == name:
            return vault
    return None


def vault_create(name: str, description: str = "") -> dict:
    state = _require_auth()
    existing = vault_get(name)
    if existing:
        raise OpError(f"vault {name!r} already exists",
                      stderr=f"vault {name!r} already exists")
    vault = {"id": f"VAULT-{len(state['vaults'])+1}", "name": name,
             "description": description}
    state["vaults"].append(vault)
    _save(state)
    return vault


def item_list(vault: Optional[str] = None,
              categories: Optional[List[str]] = None) -> List[dict]:
    state = _require_auth()
    items = state.get("items", [])
    if vault:
        items = [item for item in items if item.get("vault") == vault]
    if categories:
        items = [item for item in items if item.get("category") in categories]
    return [{"id": item["id"], "title": item["title"], "vault": item["vault"],
             "category": item["category"], "tags": item.get("tags", [])}
            for item in items]


def item_get(title: str, vault: Optional[str] = None,
             fields: Optional[List[str]] = None) -> dict:
    state = _require_auth()
    for item in state.get("items", []):
        if item["title"] == title and (not vault or item["vault"] == vault):
            return {"id": item["id"], "title": item["title"],
                    "vault": item["vault"], "category": item["category"],
                    "tags": item.get("tags", []), "fields": item["fields"]}
    raise OpError(f"item {title!r} not found",
                  stderr=f"\"{title}\" isn't an item in vault {vault!r}.")


def _upsert_fields(item: dict, assignments: List[str]) -> None:
    existing = {field["label"]: field for field in item["fields"]}
    for assignment in assignments:
        name, _, body = assignment.partition("=")
        field_type = "STRING"
        if "[" in name and name.endswith("]"):
            name, _, type_hint = name.partition("[")
            type_hint = type_hint.rstrip("]")
            if type_hint == "password":
                field_type = "CONCEALED"
        field = existing.get(name)
        if field:
            field["value"] = body
            field["type"] = field_type
        else:
            item["fields"].append({"label": name, "value": body,
                                   "type": field_type})
            existing[name] = item["fields"][-1]


def item_create(title: str, vault: str, category: str = "Secure Note",
                fields: Optional[List[str]] = None,
                tags: Optional[List[str]] = None) -> dict:
    state = _require_auth()
    item = {"id": f"ITEM-{title}-{int(time.time())}", "title": title,
            "vault": vault, "category": category, "tags": tags or [],
            "fields": []}
    _upsert_fields(item, fields or [])
    state.setdefault("items", []).append(item)
    _save(state)
    return item


def item_edit(title: str, vault: str, assignments: List[str]) -> dict:
    state = _require_auth()
    for item in state.get("items", []):
        if item["title"] == title and item["vault"] == vault:
            _upsert_fields(item, assignments)
            _save(state)
            return item
    raise OpError(f"item {title!r} not found",
                  stderr=f"\"{title}\" isn't an item in vault {vault!r}.")


def item_delete(title: str, vault: str) -> None:
    state = _require_auth()
    state["items"] = [item for item in state.get("items", [])
                      if not (item["title"] == title and item["vault"] == vault)]
    _save(state)


def item_share(title: str, vault: str, emails=None, expires=None,
               view_once: bool = False) -> str:
    _require_auth()
    token = f"demo-{int(time.time())}"
    audience = ",".join(emails) if emails else "anyone-with-the-link"
    return (f"https://share.novanode.local/{token}  "
            f"[dev-mode fake share · {audience} · expires {expires or '24h'}"
            f"{' · view-once' if view_once else ''}]")


def read_reference(reference: str) -> str:
    match = re.match(r"op://([^/]+)/([^/]+)/([^/]+)", reference)
    if not match:
        raise OpError(f"invalid reference: {reference}")
    vault, title, field_name = match.group(1), match.group(2), match.group(3)
    payload = item_get(title, vault=vault)
    for field in payload["fields"]:
        if field["label"] == field_name:
            return field["value"]
    raise OpError(f"field {field_name!r} not found on {title!r}",
                  stderr=f"field {field_name!r} not found")


def inject(template_text: str) -> str:
    pattern = re.compile(r"op://([^/\s{}]+)/([^/\s{}]+)/([^/\s{}]+)")

    def replace(match):
        try:
            return read_reference(match.group(0))
        except OpError:
            return match.group(0)

    return pattern.sub(replace, template_text)


def run_with_env(env_file: str, command: List[str],
                 no_masking: bool = False) -> int:
    """Resolve op:// refs in env_file, inject into the child's environment."""
    env = os.environ.copy()
    try:
        with open(env_file) as handle:
            text = handle.read()
    except OSError:
        return 1
    resolved = inject(text)
    for line in resolved.splitlines():
        if not line.strip() or line.startswith("#"):
            continue
        if "=" in line:
            key, value = line.split("=", 1)
            env[key.strip()] = value.strip().strip('"').strip("'")
    return subprocess.run(command, env=env).returncode


# ── installer ────────────────────────────────────────────────────────

def is_enabled() -> bool:
    return bool(os.environ.get("NNOP_DEV"))


def install() -> None:
    """Replace the public functions on `op` with these mocks, in place.

    Also seeds a demo workspace (chdir'd to) with .novanode.yml +
    .novanode.local so the Secrets UI enters the full connected view and
    every per-app/env flow is reachable from a cold start.
    """
    import op as real
    real.OpError = OpError  # keep exception identity for `except op.OpError`
    for name in ("which_op", "installed", "version", "whoami",
                 "account_list", "signin", "signin_session", "account_add",
                 "signout", "vault_list", "vault_get", "vault_create",
                 "item_list", "item_get", "item_create", "item_edit",
                 "item_delete", "item_share", "read_reference", "inject",
                 "run_with_env"):
        setattr(real, name, globals()[name])
    os.environ["NNOP_DEV"] = "1"
    state = _load()
    state["signed_in"] = True
    _save(state)
    workspace = os.path.join(DEV_HOME, "workspace")
    os.makedirs(workspace, exist_ok=True)
    config_path = os.path.join(workspace, ".novanode.yml")
    if not os.path.isfile(config_path):
        with open(config_path, "w") as handle:
            handle.write(
                f"# NovaNode dev-mode demo project (auto-generated).\n"
                f"project: {DEMO_VAULT}\n"
                f"default_app: {DEMO_APPS[1]}\n"
                f"default_env: {DEMO_ENVS[0]}\n"
                f"apps: {', '.join(DEMO_APPS)}\n"
                f"envs: {', '.join(DEMO_ENVS)}\n"
            )
    local_path = os.path.join(workspace, ".novanode.local")
    if not os.path.isfile(local_path):
        with open(local_path, "w") as handle:
            json.dump({"app": DEMO_APPS[1], "env": DEMO_ENVS[0]}, handle)
    try:
        os.chdir(workspace)
    except OSError:
        pass


def reset() -> None:
    """Wipe the dev folder and reseed. Useful between demos/tests."""
    if os.path.isdir(DEV_HOME):
        shutil.rmtree(DEV_HOME, ignore_errors=True)
    _seed()
