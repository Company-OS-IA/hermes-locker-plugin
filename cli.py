"""Operator CLI for the Hermes Locker plugin."""
from __future__ import annotations

import argparse
import os
import re
import shutil
import subprocess

_AUTH_ENV = ("LOCKER_ACCESS_KEY_ID", "LOCKER_ACCESS_KEY_SECRET")
_KEY_RE = re.compile(r"^[a-z][a-z0-9_]{0,127}$")
_ERROR_CODE_RE = re.compile(r"^Code: ([a-z][a-z0-9_-]*)$", re.MULTILINE)


def register_cli(subparser: argparse.ArgumentParser) -> None:
    subs = subparser.add_subparsers(dest="locker_command")
    status = subs.add_parser("status", help="Validate Locker CLI and bootstrap authentication")
    status.add_argument(
        "--probe-key",
        help="Optional lower_snake_case Locker key to verify authentication without printing its value",
    )
    setup = subs.add_parser("setup", help="Show safe Locker authentication setup")
    setup.add_argument(
        "--auth-mode",
        choices=("access-keys", "credential-file", "oauth"),
        default="access-keys",
        help="Locker CLI authentication mode to assess",
    )
    subparser.set_defaults(func=locker_command)


def _safe_locker_env() -> dict[str, str]:
    allowed = ("PATH", "HOME", "USER", "LANG", "LC_ALL", "TMPDIR", "XDG_CONFIG_HOME", *_AUTH_ENV)
    return {key: os.environ[key] for key in allowed if key in os.environ}


def _locker_version(binary: str) -> str | None:
    env = _safe_locker_env()
    for name in _AUTH_ENV:
        env.pop(name, None)
    try:
        proc = subprocess.run(
            [binary, "--version"],
            capture_output=True,
            text=True,
            stdin=subprocess.DEVNULL,
            env=env,
            timeout=5,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    text = (proc.stdout or proc.stderr or "").strip().splitlines()
    return text[0] if proc.returncode == 0 and text else None


def _access_keys_present() -> bool:
    return bool(os.environ.get("LOCKER_ACCESS_KEY_ID")) and bool(
        os.environ.get("LOCKER_ACCESS_KEY_SECRET")
    )


def _error_code(stderr: str) -> str | None:
    match = _ERROR_CODE_RE.search(stderr or "")
    return match.group(1) if match else None


def _cmd_status(probe_key: str | None = None) -> int:
    binary = shutil.which("locker")
    if not binary:
        print("locker CLI: missing")
        print("Install the Locker CLI binary. See: https://locker.io/secrets/download")
        return 1
    version = _locker_version(binary)
    if not version:
        print(f"locker CLI: unavailable ({binary})")
        return 1
    print(f"locker CLI: available ({version})")
    print("authentication: access keys " + ("configured" if _access_keys_present() else "not detected"))
    print("oauth: unsupported by this Locker CLI")
    if probe_key is None:
        return 0 if _access_keys_present() else 1
    if not _KEY_RE.fullmatch(probe_key):
        print("authentication probe: invalid key reference")
        return 2
    if not _access_keys_present():
        print("authentication probe: bootstrap access keys not configured")
        return 1
    child_env = _safe_locker_env()
    cmd = [
        binary, "secret", "get",
        "--plain",
        "--no-newline",
        "--refresh",
        "--access-key-id", child_env["LOCKER_ACCESS_KEY_ID"],
        "--secret-access-key-env", "LOCKER_ACCESS_KEY_SECRET",
        "--", probe_key,
    ]
    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            stdin=subprocess.DEVNULL,
            env=child_env,
            timeout=15,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        print("authentication probe: failed")
        return 1
    if proc.returncode != 0 or not (proc.stdout or "").strip():
        code = _error_code(proc.stderr)
        print("authentication probe: failed" + (f" ({code})" if code else ""))
        if code in {"unauthorized", "forbidden"}:
            print("Verify that the access key pair matches and has read access to this secret.")
        return 1
    print("authentication probe: passed")
    return 0


def _cmd_setup(auth_mode: str) -> int:
    if auth_mode == "oauth":
        print("OAuth is not supported by the installed Locker CLI. Use profile-scoped access keys.")
        return 2
    if auth_mode == "credential-file":
        print("Credential-file mode is not supported for Hermes startup. Use profile-scoped access keys.")
        return 2
    print("Access-key mode: provision LOCKER_ACCESS_KEY_ID and LOCKER_ACCESS_KEY_SECRET in the protected service environment. Do not put them in Hermes config, plugin config, repositories, or agent workspaces.")
    return 0


def locker_command(args: argparse.Namespace) -> int:
    command = getattr(args, "locker_command", None)
    if command == "status":
        return _cmd_status(getattr(args, "probe_key", None))
    if command == "setup":
        return _cmd_setup(getattr(args, "auth_mode", "access-keys"))
    print("usage: hermes locker {status,setup}")
    return 2
