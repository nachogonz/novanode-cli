"""Thin wrapper around the official 1Password `op` CLI.

Design rules:
  * Never persist the 1Password password, Secret Key, or session token.
  * Never echo secret values to stdout.
  * All authentication is delegated to `op` — we only *observe* auth state.
  * Every call surfaces a structured result so op_cli.py can render UX.
"""

import json
import os
import shutil
import subprocess
from typing import List, Optional


class OpError(Exception):
    """Raised when the underlying `op` CLI fails."""

    def __init__(self, message: str, stderr: str = "", code: int = 1):
        super().__init__(message)
        self.stderr = stderr
        self.code = code

    @property
    def needs_auth(self) -> bool:
        text = (self.stderr or str(self)).lower()
        return any(
            token in text
            for token in (
                "you are not currently signed in",
                "session expired",
                "session is invalid",
                "no session found",
                "unauthorized",
            )
        )


def which_op() -> Optional[str]:
    """Return the path to the real 1Password `op` CLI.

    Skip NovaNode's shortcut even when installed globally through npm (and
    symlinked into a different PATH entry). Otherwise `op whoami` starts
    another nn-op process indefinitely.
    """
    for entry in (os.environ.get("PATH") or "").split(os.pathsep):
        if not entry:
            continue
        candidate = os.path.join(entry, "op")
        if os.path.isfile(candidate) and os.access(candidate, os.X_OK):
            try:
                with open(candidate, "rb") as handle:
                    if b"# Fast alias for `nn-op`." in handle.read(512):
                        continue
            except OSError:
                continue
            return candidate
    return None


def installed() -> bool:
    return which_op() is not None


def version() -> Optional[str]:
    binary = which_op()
    if not binary:
        return None
    try:
        return subprocess.check_output([binary, "--version"], text=True, timeout=5).strip()
    except Exception:
        return None


def _run(
    args: List[str],
    *,
    check: bool = True,
    input_text: Optional[str] = None,
    inherit_tty: bool = False,
    capture_stdout: bool = False,
    env: Optional[dict] = None,
    timeout: Optional[int] = 30,
):
    """Invoke `op` with sane defaults.

    inherit_tty=True lets `op signin` open the desktop app or prompt for a
    passphrase interactively — nn-op never handles those credentials. With
    capture_stdout=True, stdin/stderr still belong to `op` while its session
    token is captured instead of printed.
    """
    binary = which_op()
    if not binary:
        raise OpError("1Password CLI (`op`) is not installed.", code=127)
    cmd = [binary, *args]
    if inherit_tty:
        result = subprocess.run(
            cmd,
            env=env,
            timeout=timeout,
            stdout=subprocess.PIPE if capture_stdout else None,
            text=capture_stdout,
        )
        if check and result.returncode != 0:
            raise OpError(
                f"`{' '.join(cmd)}` exited with code {result.returncode}.",
                code=result.returncode,
            )
        return result
    result = subprocess.run(
        cmd,
        input=input_text,
        capture_output=True,
        text=True,
        env=env,
        timeout=timeout,
    )
    if check and result.returncode != 0:
        message = (result.stderr or result.stdout or "").strip() or f"`{' '.join(cmd)}` failed."
        raise OpError(message, stderr=result.stderr, code=result.returncode)
    return result


def _json(args: List[str], **kwargs) -> Optional[object]:
    result = _run([*args, "--format=json"], **kwargs)
    if not result.stdout.strip():
        return None
    try:
        return json.loads(result.stdout)
    except ValueError as exc:
        raise OpError(f"Could not parse `op` output as JSON: {exc}") from exc


# ── auth ──────────────────────────────────────────────────────────────

def whoami() -> Optional[dict]:
    """Return the active session's identity, or None if signed out."""
    try:
        return _json(["whoami"])
    except OpError as err:
        if err.needs_auth or err.code != 0:
            return None
        raise


def account_list() -> List[dict]:
    try:
        data = _json(["account", "list"])
        return data or []
    except OpError:
        return []


def _remember_session(token: str, account: Optional[str] = None) -> None:
    """Keep a session only for this nn-op process and commands it launches."""
    os.environ["OP_SESSION"] = token
    if account:
        os.environ["OP_ACCOUNT"] = account
        os.environ[f"OP_SESSION_{account}"] = token


def signin(account: Optional[str] = None) -> int:
    """Delegate to `op signin` — `op` owns the credential prompt entirely."""
    args = ["signin"]
    if account:
        args += ["--account", account]
    result = _run(args, inherit_tty=True, check=False, timeout=None)
    return result.returncode


def signin_session(account: Optional[str] = None) -> bool:
    """Sign in interactively and retain the raw token in memory for this TUI."""
    args = ["signin", "--raw"]
    if account:
        args += ["--account", account]
    result = _run(
        args,
        inherit_tty=True,
        capture_stdout=True,
        check=False,
        timeout=None,
    )
    token = (result.stdout or "").strip()
    if result.returncode != 0 or not token:
        return False
    _remember_session(token, account)
    return True


def account_add(
    signin: bool = False,
    address: Optional[str] = None,
    email: Optional[str] = None,
) -> bool:
    """Let the official CLI collect credentials on the terminal.

    `op account add` has no --secret-key flag. With --signin --raw it
    authenticates in one step and prints only a session token, which we keep
    in this process. Call from a suspended TUI so its prompts are visible.
    """
    binary = which_op()
    if not binary:
        raise OpError("1Password CLI (`op`) is not installed.", code=127)
    add_args = [binary, "account", "add"]
    if address:
        add_args += ["--address", address]
    if email:
        add_args += ["--email", email]
    if signin:
        add_args += ["--signin", "--raw"]
    result = subprocess.run(
        add_args,
        stdout=subprocess.PIPE if signin else None,
        text=signin,
        timeout=None,
    )
    if result.returncode != 0:
        return False
    if signin:
        token = (result.stdout or "").strip()
        if not token:
            return False
        _remember_session(token, address)
    return True


def signout(account: Optional[str] = None, forget: bool = False) -> int:
    args = ["signout"]
    if account:
        args += ["--account", account]
    if forget:
        args += ["--forget"]
    result = _run(args, inherit_tty=True, check=False, timeout=None)
    os.environ.pop("OP_SESSION", None)
    os.environ.pop("OP_ACCOUNT", None)
    for key in [name for name in os.environ if name.startswith("OP_SESSION_")]:
        os.environ.pop(key, None)
    return result.returncode


# ── vaults / items ────────────────────────────────────────────────────

def vault_list() -> List[dict]:
    return _json(["vault", "list"]) or []


def vault_get(name: str) -> Optional[dict]:
    try:
        return _json(["vault", "get", name])
    except OpError:
        return None


def vault_create(name: str, description: str = "") -> dict:
    args = ["vault", "create", name]
    if description:
        args += ["--description", description]
    return _json(args)


def item_list(vault: Optional[str] = None, categories: Optional[List[str]] = None) -> List[dict]:
    args = ["item", "list"]
    if vault:
        args += ["--vault", vault]
    if categories:
        args += ["--categories", ",".join(categories)]
    return _json(args) or []


def item_get(title: str, vault: Optional[str] = None, fields: Optional[List[str]] = None) -> dict:
    args = ["item", "get", title]
    if vault:
        args += ["--vault", vault]
    if fields:
        # `--fields` returns a compact payload; we still ask for JSON.
        args += ["--fields", ",".join(fields)]
    return _json(args)


def item_create(
    title: str,
    vault: str,
    category: str = "Secure Note",
    fields: Optional[List[str]] = None,
    tags: Optional[List[str]] = None,
) -> dict:
    args = [
        "item", "create",
        "--title", title,
        "--vault", vault,
        "--category", category,
    ]
    if tags:
        args += ["--tags", ",".join(tags)]
    if fields:
        args += list(fields)
    return _json(args)


def item_edit(
    title: str,
    vault: str,
    assignments: List[str],
) -> dict:
    args = ["item", "edit", title, "--vault", vault, *assignments]
    return _json(args)


def item_delete(title: str, vault: str) -> None:
    _run(["item", "delete", title, "--vault", vault])


def item_share(
    title: str,
    vault: str,
    emails: Optional[List[str]] = None,
    expires: Optional[str] = None,
    view_once: bool = False,
) -> str:
    args = ["item", "share", title, "--vault", vault]
    if emails:
        args += ["--emails", ",".join(emails)]
    if expires:
        args += ["--expires-in", expires]
    if view_once:
        args += ["--view-once"]
    result = _run(args)
    return (result.stdout or "").strip()


# ── secret injection ──────────────────────────────────────────────────

def read_reference(reference: str) -> str:
    """Resolve a single `op://vault/item/field` reference to its value."""
    result = _run(["read", reference])
    return result.stdout.rstrip("\n")


def run_with_env(env_file: str, command: List[str], no_masking: bool = False) -> int:
    """Exec `command` with secrets injected via `op run`.

    `env_file` is a plaintext file whose values are `op://…` references.
    `op` resolves them at process start; the child sees real values,
    stdout is masked by default.
    """
    binary = which_op()
    if not binary:
        raise OpError("1Password CLI (`op`) is not installed.", code=127)
    args = [binary, "run", f"--env-file={env_file}"]
    if no_masking:
        args.append("--no-masking")
    args += ["--", *command]
    return subprocess.run(args).returncode


def inject(template_text: str) -> str:
    """Return the template with all `{{ op://… }}` refs resolved."""
    result = _run(["inject"], input_text=template_text)
    return result.stdout
