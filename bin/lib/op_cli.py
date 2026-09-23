#!/usr/bin/env python3
"""`nn-op` — NovaNode 1Password wrapper.

Coherent surface over `op` for project init, env management, access items,
client sharing, and session handling. All secret material stays inside `op`
and the 1Password app; nn-op only orchestrates.

Project awareness
─────────────────
When you `cd` into a project that has a `.novanode.yml` at (or above) the
current directory, every env/access/share command auto-picks that project.
A second file, `.novanode.local` (git-ignored), records the *current* app
and environment so `nn-op run -- <cmd>` works with no arguments.

Precedence for (project, app, env) resolution:
  1. Explicit positional arguments to the command
  2. `.novanode.local`   (per-clone, git-ignored)
  3. `.novanode.yml`     (checked into the repo)
  4. Interactive prompt  (only if still missing)
"""

import getpass
import json
import os
import re
import subprocess
import sys
import tempfile
from typing import List, Optional, Tuple

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import op  # noqa: E402


VERSION = "1.1.0"

GREEN = "\033[38;5;82m"
ORANGE = "\033[38;5;208m"
RED = "\033[38;5;196m"
DIM = "\033[38;5;245m"
BOLD = "\033[1m"
RESET = "\033[0m"

CONFIG_FILENAMES = (".novanode.yml", ".novanode.yaml", ".novanode.json")
LOCAL_FILENAME = ".novanode.local"

SECRET_TOKENS = (
    "SECRET", "TOKEN", "KEY", "PASSWORD", "PASS", "PWD",
    "PRIVATE", "CREDENTIAL", "DSN", "AUTH", "SIGNING", "SESSION",
)
CONFIG_HINTS = (
    "PORT", "HOST", "NODE_ENV", "PUBLIC_", "NEXT_PUBLIC_",
    "VITE_PUBLIC_", "LOG_LEVEL", "REGION", "TIMEZONE",
)


# ── printing helpers ──────────────────────────────────────────────────

def _color(text: str, code: str) -> str:
    return f"{code}{text}{RESET}"


def _print_error(message: str) -> None:
    print(f"{_color('error', RED)}  {message}", file=sys.stderr)


def _print_header(title: str) -> None:
    print()
    print(f"  {_color('NovaNode', BOLD)} {DIM}·{RESET} {title}")
    print(f"  {ORANGE}{'─' * max(28, len(title) + 12)}{RESET}")


def _prompt(label: str, default: Optional[str] = None, allow_empty: bool = False) -> str:
    suffix = f" [{default}]" if default else ""
    while True:
        try:
            value = input(f"{label}{suffix}: ").strip()
        except EOFError:
            value = ""
        if not value and default is not None:
            value = default
        if value or allow_empty:
            return value


def _prompt_secret(label: str) -> str:
    while True:
        value = getpass.getpass(f"{label}: ")
        if value:
            return value


def _prompt_yes_no(label: str, default: bool = True) -> bool:
    suffix = "Y/n" if default else "y/N"
    try:
        answer = input(f"{label} [{suffix}]: ").strip().lower()
    except EOFError:
        answer = ""
    if not answer:
        return default
    return answer.startswith("y")


def _require_installed() -> None:
    if not op.installed():
        _print_error(
            "1Password CLI (`op`) is not installed.\n"
            "  Install:  brew install --cask 1password-cli\n"
            "  Docs:     https://developer.1password.com/docs/cli/get-started/"
        )
        raise SystemExit(127)


def _require_auth() -> dict:
    _require_installed()
    identity = op.whoami()
    if identity:
        return identity
    print()
    print(f"  {_color('1Password authentication required.', ORANGE)}")
    print(f"  {DIM}Starting `op signin` — the 1Password app will handle credentials.{RESET}")
    print()
    if op.signin() != 0:
        _print_error("Sign-in cancelled or failed.")
        raise SystemExit(1)
    identity = op.whoami()
    if not identity:
        _print_error("Still not signed in after `op signin`. Try `nn-op doctor`.")
        raise SystemExit(1)
    return identity


# ── project context ───────────────────────────────────────────────────

class ProjectContext:
    """(project, app, env) resolved from files + explicit overrides."""

    def __init__(self, root: Optional[str], data: dict, local: dict):
        self.root = root
        self.data = data
        self.local = local

    @property
    def project(self) -> Optional[str]:
        return self.data.get("project")

    @property
    def default_app(self) -> Optional[str]:
        return self.local.get("app") or self.data.get("default_app")

    @property
    def default_env(self) -> Optional[str]:
        return self.local.get("env") or self.data.get("default_env")

    @property
    def apps(self) -> List[str]:
        raw = self.data.get("apps") or ""
        if isinstance(raw, list):
            return raw
        return [item.strip() for item in re.split(r"[,\s]+", raw) if item.strip()]

    @property
    def envs(self) -> List[str]:
        raw = self.data.get("envs") or ""
        if isinstance(raw, list):
            return raw
        return [item.strip() for item in re.split(r"[,\s]+", raw) if item.strip()]

    @property
    def config_path(self) -> Optional[str]:
        if not self.root:
            return None
        for name in CONFIG_FILENAMES:
            candidate = os.path.join(self.root, name)
            if os.path.isfile(candidate):
                return candidate
        return None

    @property
    def local_path(self) -> Optional[str]:
        return os.path.join(self.root, LOCAL_FILENAME) if self.root else None


def _find_project_root(start: Optional[str] = None) -> Optional[str]:
    here = os.path.abspath(start or os.getcwd())
    while True:
        for name in CONFIG_FILENAMES:
            if os.path.isfile(os.path.join(here, name)):
                return here
        parent = os.path.dirname(here)
        if parent == here:
            return None
        here = parent


def _parse_minimal_yaml(text: str) -> dict:
    """Tiny YAML subset: `key: value` and one level of `key:` + indented pairs.

    Enough for `.novanode.yml` — no lists, no anchors. Users who need YAML
    features can switch the file to `.novanode.json`.
    """
    root: dict = {}
    current_section: Optional[dict] = None
    for raw in text.splitlines():
        line = raw.rstrip()
        if not line.strip() or line.strip().startswith("#"):
            continue
        indent = len(line) - len(line.lstrip())
        stripped = line.strip()
        if ":" not in stripped:
            continue
        key, _, value = stripped.partition(":")
        key = key.strip()
        value = value.strip()
        if indent == 0:
            if value:
                root[key] = value
                current_section = None
            else:
                current_section = {}
                root[key] = current_section
        elif current_section is not None:
            current_section[key] = value
    return root


def _read_config_file(path: str) -> dict:
    try:
        with open(path) as handle:
            if path.endswith(".json"):
                return json.load(handle) or {}
            return _parse_minimal_yaml(handle.read()) or {}
    except (OSError, ValueError):
        return {}


def _read_local_state(path: str) -> dict:
    if not os.path.isfile(path):
        return {}
    try:
        with open(path) as handle:
            return json.load(handle) or {}
    except (OSError, ValueError):
        return {}


def _write_local_state(path: str, state: dict) -> None:
    parent = os.path.dirname(path) or "."
    os.makedirs(parent, exist_ok=True)
    with open(path, "w") as handle:
        json.dump(state, handle, indent=2)
        handle.write("\n")


def _context() -> ProjectContext:
    root = _find_project_root()
    data = _read_config_file(os.path.join(root, next(
        (name for name in CONFIG_FILENAMES if os.path.isfile(os.path.join(root, name))),
        CONFIG_FILENAMES[0],
    ))) if root else {}
    local = _read_local_state(os.path.join(root, LOCAL_FILENAME)) if root else {}
    return ProjectContext(root, data, local)


def _resolve(
    positional: List[str],
    *,
    require: Tuple[str, ...] = ("project", "app", "env"),
    ctx: Optional[ProjectContext] = None,
) -> Tuple[str, Optional[str], Optional[str]]:
    """Merge positional args with project context.

    Positional forms accepted:
      []                    → all from context
      [env]                 → override env only
      [app, env]            → override app + env
      [project, app, env]   → override everything
    """
    ctx = ctx or _context()
    project = ctx.project
    app = ctx.default_app
    env = ctx.default_env

    if len(positional) == 1:
        env = positional[0]
    elif len(positional) == 2:
        app, env = positional
    elif len(positional) == 3:
        project, app, env = positional
    elif len(positional) > 3:
        raise SystemExit("too many positional arguments (max 3: project app env)")

    if "project" in require and not project:
        project = _prompt("Project (vault)")
    if "app" in require and not app:
        app = _prompt("Application")
    if "env" in require and not env:
        env = _prompt("Environment", default="development")
    return project, app, env


def _split_command(args: List[str]) -> Tuple[List[str], List[str]]:
    if "--" not in args:
        return args, []
    idx = args.index("--")
    return args[:idx], args[idx + 1:]


# ── env-file / classification helpers ─────────────────────────────────

def _classify(name: str) -> str:
    upper = name.upper()
    if any(upper.startswith(hint) or hint in upper for hint in CONFIG_HINTS):
        return "config"
    if any(token in upper for token in SECRET_TOKENS):
        return "secret"
    return "secret"


def _parse_env_file(path: str) -> List[Tuple[str, str]]:
    entries: List[Tuple[str, str]] = []
    with open(path) as handle:
        for raw in handle:
            line = raw.strip()
            if not line or line.startswith("#"):
                continue
            if line.startswith("export "):
                line = line[len("export "):]
            if "=" not in line:
                continue
            key, value = line.split("=", 1)
            key = key.strip()
            value = value.strip()
            if len(value) >= 2 and value[0] == value[-1] and value[0] in ("'", '"'):
                value = value[1:-1]
            if not re.match(r"^[A-Za-z_][A-Za-z0-9_]*$", key):
                continue
            entries.append((key, value))
    return entries


def _item_field_names(payload: dict) -> List[str]:
    names: List[str] = []
    for field in payload.get("fields", []) or []:
        label = field.get("label") or field.get("id")
        if not label or label == "notesPlain":
            continue
        if not re.match(r"^[A-Za-z_][A-Za-z0-9_]*$", label):
            continue
        names.append(label)
    return names


def _ensure_gitignore(root: str, entries: List[str]) -> Optional[str]:
    """Append missing entries to <root>/.gitignore. Returns path if changed."""
    path = os.path.join(root, ".gitignore")
    existing: List[str] = []
    if os.path.isfile(path):
        with open(path) as handle:
            existing = [line.rstrip("\n") for line in handle]
    changed = False
    with open(path, "a") as handle:
        for entry in entries:
            if entry not in existing:
                if existing and existing[-1].strip():
                    handle.write("\n")
                    existing.append("")
                handle.write(entry + "\n")
                existing.append(entry)
                changed = True
    return path if changed else None


# ── auth / status commands ────────────────────────────────────────────

def cmd_login(_args: List[str]) -> int:
    _require_installed()
    identity = op.whoami()
    if identity:
        _print_header("1Password")
        print(f"  {_color('✓ Signed in', GREEN)}")
        print(f"  Account: {identity.get('url', 'n/a')}")
        print(f"  User:    {identity.get('email', 'n/a')}")
        print(f"  {DIM}Ready to use nn-op.{RESET}\n")
        return 0
    print()
    print(f"  {_color('NovaNode · 1Password', BOLD)}")
    print(f"  {DIM}Delegating to `op signin`. 1Password owns the credential prompt.{RESET}")
    print()
    return op.signin()


def cmd_logout(_args: List[str]) -> int:
    _require_installed()
    return op.signout()


def cmd_whoami(_args: List[str]) -> int:
    _require_installed()
    identity = op.whoami()
    if not identity:
        print(f"{DIM}not signed in{RESET}")
        return 1
    print(json.dumps(identity, indent=2))
    return 0


def cmd_accounts(_args: List[str]) -> int:
    _require_installed()
    accounts = op.account_list()
    if not accounts:
        print(f"{DIM}no accounts configured. Run `op account add` to add one.{RESET}")
        return 1
    _print_header("1Password Accounts")
    for entry in accounts:
        print(f"  · {entry.get('shorthand', '?'):<12} {entry.get('email', ''):<32} {DIM}{entry.get('url', '')}{RESET}")
    print()
    return 0


def cmd_status(_args: List[str]) -> int:
    _print_header("1Password Status")
    installed_flag = op.installed()
    ver = op.version() or ""
    identity = op.whoami() if installed_flag else None
    line = lambda label, ok, detail: print(
        f"  {label:<18} {(_color('✓', GREEN) if ok else _color('✗', RED))} {detail}"
    )
    line("CLI", installed_flag, ver or "not installed")
    line("Authentication", bool(identity), "signed in" if identity else "signed out")
    if identity:
        line("Account", True, identity.get("url", "n/a"))
        line("User", True, identity.get("email", "n/a"))
        try:
            vaults = op.vault_list()
            line("Vault access", bool(vaults), f"{len(vaults)} vault(s) visible")
        except op.OpError as err:
            line("Vault access", False, err.stderr.strip() or str(err))
    ctx = _context()
    if ctx.root:
        line("Project", True, f"{ctx.project or '(unset)'} · {ctx.root}")
        if ctx.default_app or ctx.default_env:
            line("Current env", True, f"{ctx.default_app or '?'} / {ctx.default_env or '?'}")
    else:
        line("Project", False, "no .novanode.yml in this tree")
    print()
    return 0 if installed_flag and identity else 1


def cmd_doctor(_args: List[str]) -> int:
    _print_header("nn-op doctor")
    ok = True

    def check(label: str, condition: bool, detail: str, notes: Optional[List[str]] = None) -> None:
        nonlocal ok
        ok = ok and condition
        mark = _color("✓", GREEN) if condition else _color("✗", RED)
        print(f"  {mark} {label:<26} {detail}")
        for note in notes or []:
            print(f"      {DIM}{note}{RESET}")

    check("op installed", op.installed(), op.version() or "install: brew install --cask 1password-cli")
    accounts = op.account_list() if op.installed() else []
    check("account configured", bool(accounts), f"{len(accounts)} account(s)")
    identity = op.whoami() if op.installed() else None
    check("authenticated", bool(identity), identity.get("email", "signed out") if identity else "run `nn-op login`")
    if identity:
        try:
            vaults = op.vault_list()
            check("vault access", bool(vaults), f"{len(vaults)} vault(s)")
        except op.OpError as err:
            check("vault access", False, err.stderr.strip() or str(err))
    ctx = _context()
    check(
        "project config",
        bool(ctx.config_path),
        ctx.config_path or "no .novanode.yml in this tree",
        ["optional — enables `nn-op run --` without positional args"],
    )
    if ctx.default_app or ctx.default_env:
        check("current env selected", True, f"{ctx.default_app or '?'} / {ctx.default_env or '?'}")
    print()
    print(f"  Result: {_color('READY', GREEN) if ok else _color('ACTION REQUIRED', ORANGE)}\n")
    return 0 if ok else 1


def cmd_where(_args: List[str]) -> int:
    ctx = _context()
    _print_header("Project context")
    if not ctx.root:
        print(f"  {DIM}no .novanode.yml found in this tree.{RESET}")
        print(f"  {DIM}Run `nn-op project init` inside your project to create one.{RESET}\n")
        return 1
    print(f"  root         {ctx.root}")
    print(f"  config       {ctx.config_path}")
    print(f"  project      {ctx.project or DIM + '(unset)' + RESET}")
    print(f"  app          {ctx.default_app or DIM + '(unset)' + RESET}")
    print(f"  env          {ctx.default_env or DIM + '(unset)' + RESET}")
    if ctx.apps:
        print(f"  apps         {', '.join(ctx.apps)}")
    if ctx.envs:
        print(f"  envs         {', '.join(ctx.envs)}")
    print()
    return 0


# ── project init ──────────────────────────────────────────────────────

def cmd_project_init(_args: List[str]) -> int:
    _require_auth()
    _print_header("Project init")
    cwd = os.getcwd()
    existing = _find_project_root(cwd)
    if existing:
        print(f"  {DIM}Existing config at {os.path.join(existing, next(name for name in CONFIG_FILENAMES if os.path.isfile(os.path.join(existing, name))))}. Continuing will update it.{RESET}\n")

    default_name = os.path.basename(cwd)
    name = _prompt("Project name", default=default_name)
    apps_raw = _prompt("Applications (comma-separated)", default="client,server")
    envs_raw = _prompt("Environments (comma-separated)", default="development,staging,production")
    apps = [item.strip() for item in apps_raw.split(",") if item.strip()]
    envs = [item.strip() for item in envs_raw.split(",") if item.strip()]

    default_app = _prompt(
        "Default app in this repo",
        default=apps[0] if apps else "server",
    )
    default_env = _prompt("Default env", default="development")

    write_config = _prompt_yes_no(f"Write .novanode.yml to {cwd}?", default=True)
    create_vault = _prompt_yes_no(f"Create 1Password vault {_color(name, BOLD)} with {len(apps)}×{len(envs)} env items?", default=True)

    if write_config:
        config_path = os.path.join(cwd, ".novanode.yml")
        with open(config_path, "w") as handle:
            handle.write(
                f"# NovaNode project config — safe to commit (no secrets).\n"
                f"project: {name}\n"
                f"default_app: {default_app}\n"
                f"default_env: {default_env}\n"
                f"apps: {', '.join(apps)}\n"
                f"envs: {', '.join(envs)}\n"
            )
        print(f"  {_color('✓', GREEN)} wrote {config_path}")
        gi = _ensure_gitignore(cwd, [LOCAL_FILENAME, ".env", ".env.local"])
        if gi:
            print(f"  {_color('✓', GREEN)} updated {gi}")

    if create_vault:
        try:
            op.vault_create(name, description=f"NovaNode project: {name}")
        except op.OpError as err:
            if "already exists" not in (err.stderr or "").lower():
                _print_error(err.stderr.strip() or str(err))
                return 1
        created = 0
        for app in apps:
            for env in envs:
                title = f"{app}-{env}"
                try:
                    op.item_create(
                        title=title,
                        vault=name,
                        category="Secure Note",
                        tags=[app, env, "novanode-env"],
                    )
                    created += 1
                except op.OpError as err:
                    if "already exists" in (err.stderr or "").lower():
                        continue
                    _print_error(f"{title}: {err.stderr.strip() or err}")
        print(f"  {_color('✓', GREEN)} vault ready · {created} new item(s)")

    print()
    return 0


def cmd_project_list(_args: List[str]) -> int:
    _require_auth()
    _print_header("Projects (vaults)")
    for vault in op.vault_list():
        print(f"  · {vault.get('name', '?'):<24} {DIM}{vault.get('id', '')}{RESET}")
    print()
    return 0


# ── env commands ──────────────────────────────────────────────────────

def cmd_env_use(args: List[str]) -> int:
    ctx = _context()
    if not ctx.root:
        _print_error("no .novanode.yml in this tree. Run `nn-op project init` first.")
        return 2
    if not args:
        _print_error("usage: nn-op env use [<app>] <env>")
        return 2
    if len(args) == 1:
        app = ctx.default_app or ctx.data.get("default_app")
        env = args[0]
    else:
        app, env = args[0], args[1]
    if not app:
        _print_error("no app configured. Pass `<app> <env>` or set default_app in .novanode.yml.")
        return 2
    state = dict(ctx.local)
    state["app"] = app
    state["env"] = env
    _write_local_state(ctx.local_path, state)
    print(f"  {_color('✓', GREEN)} current env → {app} / {env}  {DIM}({ctx.local_path}){RESET}\n")
    return 0


def cmd_env_envs(args: List[str]) -> int:
    _require_auth()
    ctx = _context()
    project = args[0] if args else ctx.project
    if not project:
        project = _prompt("Project (vault)")
    _print_header(f"{project} · env items")
    items = op.item_list(vault=project)
    tagged = [item for item in items if "novanode-env" in (item.get("tags") or [])]
    if not tagged:
        print(f"  {DIM}no env items tagged 'novanode-env' in {project}.{RESET}\n")
        return 0
    current = f"{ctx.default_app}-{ctx.default_env}" if (ctx.default_app and ctx.default_env) else None
    for entry in sorted(tagged, key=lambda item: item.get("title", "")):
        title = entry.get("title", "?")
        mark = _color("● ", GREEN) if title == current else "  "
        print(f"  {mark}{title}")
    print()
    return 0


def cmd_env_list(args: List[str]) -> int:
    _require_auth()
    project, app, env = _resolve(args)
    title = f"{app}-{env}"
    try:
        payload = op.item_get(title, vault=project)
    except op.OpError as err:
        _print_error(err.stderr.strip() or str(err))
        return 1
    _print_header(f"{project} / {title}")
    for field in payload.get("fields", []) or []:
        label = field.get("label") or field.get("id") or "?"
        if str(field.get("type", "")).upper() == "CONCEALED":
            display = "••••••••"
        else:
            display = field.get("value", "") or ""
        print(f"  {label:<28} {DIM}{display}{RESET}")
    print()
    return 0


def cmd_env_set(args: List[str]) -> int:
    _require_auth()
    positional = args
    variable = None
    if len(args) in (1, 2, 4):
        positional = args[:-1]
        variable = args[-1]
    project, app, env = _resolve(positional)
    if not variable:
        variable = _prompt("Variable")
    value = _prompt_secret("Value")
    title = f"{app}-{env}"
    assignments = [f"{variable}[password]={value}"]
    try:
        op.item_edit(title, vault=project, assignments=assignments)
    except op.OpError as err:
        message = (err.stderr or "").lower()
        if "isn't an item" in message or "not found" in message or "no item found" in message:
            try:
                op.item_create(
                    title=title,
                    vault=project,
                    category="Secure Note",
                    fields=[f"{variable}[password]={value}"],
                    tags=[app, env, "novanode-env"],
                )
            except op.OpError as inner:
                _print_error(inner.stderr.strip() or str(inner))
                return 1
        else:
            _print_error(err.stderr.strip() or str(err))
            return 1
    print(f"\n  {_color('✓', GREEN)} {variable} updated · {project} / {app} / {env}\n")
    return 0


def cmd_env_import(args: List[str]) -> int:
    _require_auth()
    if not args:
        _print_error("usage: nn-op env import <path-to-env> [<app>] [<env>]")
        return 2
    path = args[0]
    if not os.path.isfile(path):
        _print_error(f"file not found: {path}")
        return 1
    entries = _parse_env_file(path)
    if not entries:
        _print_error("no KEY=VALUE lines found.")
        return 1
    project, app, env = _resolve(args[1:])
    print()
    print(f"  Detected {_color(str(len(entries)), BOLD)} variables in {path}")
    print()
    secrets = [(k, v) for k, v in entries if _classify(k) == "secret"]
    configs = [(k, v) for k, v in entries if _classify(k) == "config"]
    print(f"  {_color('Secrets', BOLD)}")
    for key, _ in secrets:
        print(f"    [x] {key}")
    if configs:
        print(f"\n  {_color('Configuration (skipped)', BOLD)}")
        for key, _ in configs:
            print(f"    [ ] {key}")
    print()
    if not _prompt_yes_no(f"Import {len(secrets)} secret(s) into {project}/{app}-{env}?"):
        print("cancelled.")
        return 1
    title = f"{app}-{env}"
    fields = [f"{k}[password]={v}" for k, v in secrets]
    try:
        op.item_edit(title, vault=project, assignments=fields)
    except op.OpError as err:
        message = (err.stderr or "").lower()
        if "not found" in message or "no item found" in message or "isn't an item" in message:
            op.item_create(
                title=title,
                vault=project,
                category="Secure Note",
                fields=fields,
                tags=[app, env, "novanode-env"],
            )
        else:
            _print_error(err.stderr.strip() or str(err))
            return 1
    print(f"\n  {_color('✓', GREEN)} {len(secrets)} secret(s) saved\n")
    return 0


def _render_env_template(project: str, app: str, env: str, names: List[str]) -> str:
    title = f"{app}-{env}"
    return "\n".join(f'{name}="op://{project}/{title}/{name}"' for name in names) + "\n"


def cmd_env_template(args: List[str]) -> int:
    _require_auth()
    out_path = None
    positional = list(args)
    if "--out" in positional:
        idx = positional.index("--out")
        out_path = positional[idx + 1]
        positional = positional[:idx] + positional[idx + 2:]
    project, app, env = _resolve(positional)
    title = f"{app}-{env}"
    try:
        payload = op.item_get(title, vault=project)
    except op.OpError as err:
        _print_error(err.stderr.strip() or str(err))
        return 1
    names = _item_field_names(payload)
    if not names:
        _print_error(f"no variables on {project}/{title}.")
        return 1
    text = _render_env_template(project, app, env, names)
    if not out_path:
        sys.stdout.write(text)
        return 0
    with open(out_path, "w") as handle:
        handle.write(text)
    print(f"  {_color('✓', GREEN)} wrote {out_path} · {len(names)} op:// reference(s)")
    print(f"  {DIM}Safe to commit. Run with `op run --env-file={out_path} -- <cmd>`.{RESET}\n")
    return 0


def cmd_env_pull(args: List[str]) -> int:
    """Materialize a *plaintext* .env file. Warns and gitignores by default."""
    _require_auth()
    out_path = ".env"
    force = False
    materialize = False
    positional: List[str] = []
    it = iter(args)
    for token in it:
        if token == "--out":
            out_path = next(it, ".env")
        elif token in ("--force", "-f"):
            force = True
        elif token in ("--materialize", "--plain", "--values"):
            materialize = True
        else:
            positional.append(token)

    ctx = _context()
    project, app, env = _resolve(positional, ctx=ctx)
    title = f"{app}-{env}"

    if not materialize:
        # Safe default: write a template (op:// references).
        return cmd_env_template(positional + ["--out", out_path if out_path != ".env" else ".env.template"])

    try:
        payload = op.item_get(title, vault=project)
    except op.OpError as err:
        _print_error(err.stderr.strip() or str(err))
        return 1
    names = _item_field_names(payload)
    if not names:
        _print_error(f"no variables on {project}/{title}.")
        return 1

    print()
    print(f"  {_color('⚠', ORANGE)} About to write {len(names)} plaintext secret(s) to {os.path.abspath(out_path)}")
    print(f"  {DIM}Prefer `nn-op run -- <cmd>` unless your tool absolutely needs a .env file.{RESET}")
    if not force and not _prompt_yes_no("Continue?", default=False):
        print("cancelled.")
        return 1

    template = _render_env_template(project, app, env, names)
    resolved = op.inject(template)
    with open(out_path, "w") as handle:
        handle.write(resolved)
    os.chmod(out_path, 0o600)

    if ctx.root:
        gi = _ensure_gitignore(ctx.root, [os.path.basename(out_path)])
        if gi:
            print(f"  {_color('✓', GREEN)} added {os.path.basename(out_path)} to {gi}")
    print(f"  {_color('✓', GREEN)} wrote {out_path} · chmod 600\n")
    return 0


def cmd_env_copy(args: List[str]) -> int:
    """Copy variables between env items.

    Forms:
      nn-op env copy <src-app> <src-env> <dst-app> <dst-env>
      nn-op env copy <src-project>/<src-app>/<src-env> <dst-project>/<dst-app>/<dst-env>
    """
    _require_auth()
    ctx = _context()

    def parse_ref(token: str) -> Tuple[str, str, str]:
        if "/" in token:
            parts = token.split("/")
            if len(parts) != 3:
                raise SystemExit("qualified reference must be <project>/<app>/<env>")
            return parts[0], parts[1], parts[2]
        raise SystemExit("use qualified <project>/<app>/<env> or four positionals")

    if len(args) == 2:
        src_project, src_app, src_env = parse_ref(args[0])
        dst_project, dst_app, dst_env = parse_ref(args[1])
    elif len(args) == 4:
        if not ctx.project:
            _print_error("no project context. Use qualified references or pass --project.")
            return 2
        src_app, src_env, dst_app, dst_env = args
        src_project = dst_project = ctx.project
    else:
        _print_error("usage: nn-op env copy <src-app> <src-env> <dst-app> <dst-env>\n"
                     "   or: nn-op env copy <src-project>/<src-app>/<src-env> <dst-project>/<dst-app>/<dst-env>")
        return 2

    src_title = f"{src_app}-{src_env}"
    dst_title = f"{dst_app}-{dst_env}"
    try:
        payload = op.item_get(src_title, vault=src_project)
    except op.OpError as err:
        _print_error(err.stderr.strip() or str(err))
        return 1
    names = _item_field_names(payload)
    if not names:
        _print_error(f"no variables on {src_project}/{src_title}.")
        return 1

    print()
    print(f"  {_color('Copy', BOLD)} {src_project}/{src_title}  →  {dst_project}/{dst_title}")
    print(f"  {DIM}{len(names)} variable(s): {', '.join(names[:8])}{'…' if len(names) > 8 else ''}{RESET}")
    print()
    if not _prompt_yes_no("Proceed?", default=True):
        print("cancelled.")
        return 1

    # Read via `op read` so values never touch our stdout logs.
    assignments = []
    for name in names:
        value = op.read_reference(f"op://{src_project}/{src_title}/{name}")
        assignments.append(f"{name}[password]={value}")
    try:
        op.item_edit(dst_title, vault=dst_project, assignments=assignments)
    except op.OpError as err:
        message = (err.stderr or "").lower()
        if "not found" in message or "no item found" in message or "isn't an item" in message:
            op.item_create(
                title=dst_title,
                vault=dst_project,
                category="Secure Note",
                fields=assignments,
                tags=[dst_app, dst_env, "novanode-env"],
            )
        else:
            _print_error(err.stderr.strip() or str(err))
            return 1

    print(f"  {_color('✓', GREEN)} copied {len(names)} variable(s)\n")
    return 0


def cmd_env_run(args: List[str]) -> int:
    _require_auth()
    positional, command = _split_command(args)
    if not command:
        _print_error("usage: nn-op env run [[<project>] <app>] <env> -- <cmd> [args…]")
        return 2
    project, app, env = _resolve(positional)
    title = f"{app}-{env}"
    try:
        payload = op.item_get(title, vault=project)
    except op.OpError as err:
        _print_error(err.stderr.strip() or str(err))
        return 1
    names = _item_field_names(payload)
    if not names:
        _print_error(f"no variables on {project}/{title}.")
        return 1

    with tempfile.NamedTemporaryFile("w", prefix="nn-op-", suffix=".env", delete=False) as tmp:
        tmp.write(_render_env_template(project, app, env, names))
        tmp_path = tmp.name

    print(f"\n  {_color('NovaNode Secrets', BOLD)}")
    print(f"  {_color('✓', GREEN)} Project:     {project}")
    print(f"  {_color('✓', GREEN)} Application: {app}")
    print(f"  {_color('✓', GREEN)} Environment: {env}")
    print(f"  {_color('✓', GREEN)} {len(names)} variable(s) resolved via op://\n")
    print(f"  → {' '.join(command)}\n")
    try:
        return op.run_with_env(tmp_path, command)
    finally:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass


# ── access commands ───────────────────────────────────────────────────

ACCESS_CATEGORIES = {
    "aws":       ("API Credential", ["Access Key ID", "Secret Access Key", "Region", "Account ID", "Role ARN"]),
    "gcp":       ("API Credential", ["Project ID", "Service Account Email", "Private Key"]),
    "vercel":    ("API Credential", ["Team", "Token"]),
    "github":    ("API Credential", ["Username", "Token"]),
    "cloudflare":("API Credential", ["Account ID", "API Token"]),
    "database":  ("Database",       ["Server", "Port", "Database", "Username", "Password"]),
    "login":     ("Login",          ["Username", "Password", "URL"]),
    "api":       ("API Credential", ["Endpoint", "Token"]),
}


def cmd_access_add(_args: List[str]) -> int:
    _require_auth()
    _print_header("Access · add")
    ctx = _context()
    project = ctx.project or _prompt("Project (vault)")
    print("  Types: " + ", ".join(ACCESS_CATEGORIES.keys()))
    kind = _prompt("Type", default="aws").lower()
    if kind not in ACCESS_CATEGORIES:
        _print_error(f"unknown type: {kind}")
        return 2
    category, fields_spec = ACCESS_CATEGORIES[kind]
    name = _prompt("Name (e.g. 'Production Deploy')")
    fields: List[str] = []
    for label in fields_spec:
        low = label.lower()
        if any(token.lower() in low for token in ("secret", "password", "token", "key")):
            value = _prompt_secret(label)
            fields.append(f"{label}[password]={value}")
        else:
            value = _prompt(label, allow_empty=True)
            if value:
                fields.append(f"{label}[text]={value}")
    try:
        op.item_create(
            title=name,
            vault=project,
            category=category,
            fields=fields,
            tags=[kind, "novanode-access"],
        )
    except op.OpError as err:
        _print_error(err.stderr.strip() or str(err))
        return 1
    print(f"\n  {_color('✓', GREEN)} {name} saved to {project}\n")
    return 0


def cmd_access_list(args: List[str]) -> int:
    _require_auth()
    ctx = _context()
    project = args[0] if args else (ctx.project or _prompt("Project (vault)"))
    _print_header(f"{project} · Access")
    items = op.item_list(vault=project)
    grouped: dict = {}
    for entry in items:
        tags = entry.get("tags") or []
        if "novanode-access" not in tags:
            continue
        kind = next((tag for tag in tags if tag in ACCESS_CATEGORIES), "other")
        grouped.setdefault(kind, []).append(entry.get("title", "?"))
    if not grouped:
        print(f"  {DIM}no access items found. Run `nn-op access add`.{RESET}\n")
        return 0
    for kind in sorted(grouped):
        print(f"\n  {_color(kind.upper(), BOLD)}")
        for title in sorted(grouped[kind]):
            print(f"    · {title}")
    print()
    return 0


def cmd_access_show(args: List[str]) -> int:
    _require_auth()
    ctx = _context()
    if len(args) == 1 and ctx.project:
        project, name = ctx.project, args[0]
    elif len(args) >= 2:
        project, name = args[0], args[1]
    else:
        _print_error("usage: nn-op access show [<project>] <name>")
        return 2
    try:
        payload = op.item_get(name, vault=project)
    except op.OpError as err:
        _print_error(err.stderr.strip() or str(err))
        return 1
    _print_header(f"{project} · {name}")
    for field in payload.get("fields", []) or []:
        label = field.get("label") or field.get("id") or "?"
        if str(field.get("type", "")).upper() == "CONCEALED":
            display = "••••••••"
        else:
            display = field.get("value", "") or ""
        print(f"  {label:<28} {display}")
    print()
    return 0


# ── share ─────────────────────────────────────────────────────────────

def cmd_share_create(_args: List[str]) -> int:
    _require_auth()
    _print_header("Share · create")
    ctx = _context()
    project = ctx.project or _prompt("Project (vault)")
    title = _prompt("Item to share")
    email = _prompt("Recipient email", allow_empty=True)
    expires = _prompt("Expires (e.g. 24h, 7d)", default="24h")
    view_once = _prompt_yes_no("Require view-once (one-time link)?", default=False)
    emails = [email] if email else None
    try:
        link = op.item_share(title, vault=project, emails=emails, expires=expires, view_once=view_once)
    except op.OpError as err:
        _print_error(err.stderr.strip() or str(err))
        return 1
    print(f"\n  {_color('✓', GREEN)} Share link created.")
    if emails:
        print(f"  Restricted to: {email}")
    print(f"  Expires in: {expires}")
    print(f"  {DIM}{link}{RESET}\n")
    return 0


# ── interactive menu ──────────────────────────────────────────────────

def _interactive_items(ctx: ProjectContext) -> List[Tuple[str, List[str]]]:
    where = ""
    if ctx.default_app and ctx.default_env:
        where = f" {DIM}({ctx.default_app}/{ctx.default_env}){RESET}"
    return [
        (f"Run project with secrets{where}", ["env", "run"]),
        ("Switch current env",               ["env", "use"]),
        ("List envs in this project",        ["env", "envs"]),
        ("Update / set a secret",            ["env", "set"]),
        ("Import a .env file",               ["env", "import"]),
        ("Write .env.template (op:// refs)", ["env", "template", "--out", ".env.template"]),
        ("Pull real .env file (⚠ plaintext)", ["env", "pull", "--materialize"]),
        ("Copy env between apps/projects",   ["env", "copy"]),
        ("List access items",                ["access", "list"]),
        ("Add access credentials",           ["access", "add"]),
        ("Share with client",                ["share", "create"]),
        ("Where am I?",                      ["where"]),
        ("Project init here",                ["project", "init"]),
        ("Status",                           ["status"]),
        ("Login",                            ["login"]),
        ("Diagnostics (doctor)",             ["doctor"]),
    ]


def cmd_interactive() -> int:
    ctx = _context()
    _print_header("Secrets")
    identity = op.whoami() if op.installed() else None
    if identity:
        print(f"  {_color('✓', GREEN)} 1Password authenticated · {identity.get('email', '')}")
    else:
        print(f"  {_color('✗', RED)} not signed in · choose 'Login' below")
    if ctx.root:
        print(f"  {_color('•', GREEN)} project: {ctx.project or DIM+'(unset)'+RESET}"
              f"  {DIM}({os.path.relpath(ctx.root, os.getcwd()) or '.'}){RESET}")
    else:
        print(f"  {DIM}• no .novanode.yml in this tree{RESET}")
    print()
    items = _interactive_items(ctx)
    for index, (label, _cmd) in enumerate(items, 1):
        print(f"  {index:>2}. {label}")
    print()
    try:
        choice = input("  Select: ").strip()
    except (EOFError, KeyboardInterrupt):
        print()
        return 0
    if not choice.isdigit() or not (1 <= int(choice) <= len(items)):
        _print_error("invalid selection.")
        return 2
    return dispatch(items[int(choice) - 1][1])


# ── dispatch ──────────────────────────────────────────────────────────

def dispatch(argv: List[str]) -> int:
    if not argv:
        return cmd_interactive()
    head = argv[0]
    rest = argv[1:]

    aliases = {
        "set":      ["env", "set"],
        "list":     ["env", "list"],
        "import":   ["env", "import"],
        "run":      ["env", "run"],
        "use":      ["env", "use"],
        "envs":     ["env", "envs"],
        "pull":     ["env", "pull"],
        "template": ["env", "template"],
        "copy":     ["env", "copy"],
        "share":    ["share", "create"],
    }
    if head in aliases and (not rest or rest[0] not in ("--help", "-h")):
        argv = aliases[head] + rest
        head, rest = argv[0], argv[1:]

    top_level = {
        "login":    cmd_login,
        "logout":   cmd_logout,
        "whoami":   cmd_whoami,
        "accounts": cmd_accounts,
        "status":   cmd_status,
        "doctor":   cmd_doctor,
        "where":    cmd_where,
    }
    if head in top_level:
        return top_level[head](rest)

    if head == "project":
        sub = rest[0] if rest else ""
        if sub == "init":
            return cmd_project_init(rest[1:])
        if sub in ("list", "ls"):
            return cmd_project_list(rest[1:])
        _print_error(f"unknown project subcommand: {sub or '(missing)'}")
        return 2

    if head == "env":
        sub = rest[0] if rest else ""
        handlers = {
            "list":     cmd_env_list,
            "set":      cmd_env_set,
            "import":   cmd_env_import,
            "run":      cmd_env_run,
            "use":      cmd_env_use,
            "envs":     cmd_env_envs,
            "template": cmd_env_template,
            "pull":     cmd_env_pull,
            "copy":     cmd_env_copy,
        }
        if sub in handlers:
            return handlers[sub](rest[1:])
        _print_error(f"unknown env subcommand: {sub or '(missing)'}")
        return 2

    if head == "access":
        sub = rest[0] if rest else ""
        handlers = {
            "add":  cmd_access_add,
            "list": cmd_access_list,
            "show": cmd_access_show,
        }
        if sub in handlers:
            return handlers[sub](rest[1:])
        _print_error(f"unknown access subcommand: {sub or '(missing)'}")
        return 2

    if head == "share":
        sub = rest[0] if rest else "create"
        if sub == "create":
            return cmd_share_create(rest[1:])
        _print_error(f"unknown share subcommand: {sub}")
        return 2

    _print_error(f"unknown command: {head}")
    print_help()
    return 2


def print_help(_scope: str = "main") -> None:
    print(f"""nn-op {VERSION}

NovaNode 1Password wrapper — layered on top of the official `op` CLI.
Project-aware: reads .novanode.yml at (or above) the current directory.

Session:
  nn-op                              Open the interactive menu
  nn-op login                        Sign in (delegates to `op signin`)
  nn-op logout                       Sign out
  nn-op status                       CLI + auth + project status
  nn-op accounts                     List configured 1Password accounts
  nn-op whoami                       JSON identity dump
  nn-op doctor                       Full diagnostics
  nn-op where                        Show resolved project/app/env

Project:
  nn-op project init                 Create vault + write .novanode.yml here
  nn-op project list                 List project vaults

Everyday env flow (all context-aware — `<app>` and `<env>` default to
your current selection from .novanode.yml + .novanode.local):

  nn-op run -- <cmd>                 Run <cmd> with secrets injected
  nn-op run <env> -- <cmd>           Run against a specific env
  nn-op run <app> <env> -- <cmd>     Run against a specific app+env
  nn-op run <project> <app> <env> -- <cmd>
                                     Fully qualified (borrow another project)

  nn-op env use <env>                Switch current env (writes .novanode.local)
  nn-op env use <app> <env>          Switch app + env
  nn-op env envs                     List env items in this project
  nn-op env list                     Show variables (masked)
  nn-op env set [<VAR>]              Set/update one variable
  nn-op env import <path>            Import a .env file
  nn-op env template [--out FILE]    Write .env.template with op:// refs (safe)
  nn-op env pull --materialize [--out FILE]
                                     Materialize real values into .env (⚠)
  nn-op env copy <src-app> <src-env> <dst-app> <dst-env>
  nn-op env copy <proj>/<app>/<env> <proj>/<app>/<env>
                                     Mirror variables across items/projects

Access & sharing:
  nn-op access add                   Add IAM / API / login credentials
  nn-op access list                  List access items
  nn-op access show <name>           Show metadata (secrets masked)
  nn-op share create                 Create a client-safe share link

Shortcuts (all also work as top-level commands):
  set · list · import · run · use · envs · pull · template · copy · share

Security:
  · `op signin` owns all credential prompts.
  · nn-op never persists your password, Secret Key, or session token.
  · Secret values enter via prompts, never as CLI arguments.
  · `nn-op env pull --materialize` warns before writing plaintext, chmod 600,
    and auto-appends the output file to .gitignore.
""")


def main(argv: Optional[List[str]] = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv and argv[0] in ("-h", "--help", "help"):
        print_help()
        return 0
    if argv and argv[0] in ("-v", "--version"):
        print(VERSION)
        return 0
    try:
        return dispatch(argv)
    except KeyboardInterrupt:
        print()
        return 130
    except op.OpError as err:
        if err.needs_auth:
            _print_error("1Password session expired. Run `nn-op login`.")
        else:
            _print_error(err.stderr.strip() or str(err))
        return err.code or 1


if __name__ == "__main__":
    raise SystemExit(main())
