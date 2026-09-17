"""Hermes Locker — Locker Secrets Manager source plugin.

Resolves explicitly mapped ``locker://lower_snake_case`` references through
Locker CLI. Values stay in the Hermes secret-source orchestration path and are
never written by this plugin to config files, logs, or a disk cache.
"""
from __future__ import annotations

import importlib.util
import os
import re
import stat
import subprocess
from pathlib import Path
from typing import Any

from agent.secret_sources.base import (
    ErrorKind,
    FetchResult,
    SecretSource,
    get_source_environment,
    run_secret_cli,
)


def _load_cli_module():
    path = Path(__file__).with_name("cli.py")
    spec = importlib.util.spec_from_file_location("hermes_locker_plugin_cli", path)
    if spec is None or spec.loader is None:
        raise ImportError("Could not load Hermes Locker CLI module")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


cli = _load_cli_module()

_NAME_RE = re.compile(r"^[a-z][a-z0-9_]{0,127}$")
_BOOTSTRAP_ENV = (
    "LOCKER_ACCESS_KEY_ID",
    "LOCKER_ACCESS_KEY_SECRET",
)


def _open_credential_directory(directory: str) -> int:
    """Walk from root by descriptor; reject symlinks in every component."""
    if not directory or not os.path.isabs(directory):
        raise ValueError("Missing service credential directory")
    components = directory.split("/")[1:]
    if any(part in {"", ".", ".."} for part in components):
        raise ValueError("Invalid service credential directory")
    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC
    fd = os.open("/", flags)
    try:
        for part in components:
            child = os.open(part, flags, dir_fd=fd)
            os.close(fd)
            fd = child
            info = os.fstat(fd)
            mode = stat.S_IMODE(info.st_mode)
            # A root-owned sticky parent such as /tmp protects owner-controlled
            # descendants; all other parents must not be group/world writable.
            trusted_sticky = info.st_uid == 0 and bool(mode & stat.S_ISVTX)
            if info.st_uid not in {0, os.geteuid()} or (mode & 0o022 and not trusted_sticky):
                raise ValueError("Untrusted credential directory ancestor")
        return fd
    except BaseException:
        os.close(fd)
        raise


def _service_bootstrap(credential_name: Any) -> dict[str, str]:
    """Read an explicitly opted-in systemd credential, never ambient secrets.

    Only the non-secret directory locator comes from process environment.
    Values remain local to this fetch and the allowlisted Locker subprocess.
    """
    if not isinstance(credential_name, str) or not _NAME_RE.fullmatch(credential_name):
        raise ValueError("Invalid bootstrap credential name")
    directory = os.environ.get("CREDENTIALS_DIRECTORY", "")
    # Fail closed on platforms without secure open flags.
    dir_fd = _open_credential_directory(directory)
    try:
        info = os.fstat(dir_fd)
        if info.st_uid not in {0, os.geteuid()} or stat.S_IMODE(info.st_mode) & 0o077:
            raise ValueError("Unsafe credential directory")
        fd = os.open(credential_name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC, dir_fd=dir_fd)
        try:
            info = os.fstat(fd)
            if (not stat.S_ISREG(info.st_mode) or info.st_uid not in {0, os.geteuid()}
                    or stat.S_IMODE(info.st_mode) & 0o177 or info.st_size > 16384):
                raise ValueError("Unsafe credential file")
            with os.fdopen(fd, "rb", closefd=False) as stream:
                raw = stream.read(16385)
            if len(raw) > 16384:
                raise ValueError("Oversized credential")
        finally:
            os.close(fd)
    finally:
        os.close(dir_fd)
    values: dict[str, str] = {}
    for line in raw.decode("utf-8").splitlines():
        if not line:
            continue
        key, separator, value = line.partition("=")
        if not separator or key not in _BOOTSTRAP_ENV or key in values or not value.strip() or "\x00" in value:
            raise ValueError("Invalid bootstrap payload")
        values[key] = value
    return values


def _run_locker(argv: list[str], *, timeout: float, bootstrap_env: dict[str, str]):
    return run_secret_cli(
        argv,
        allow_env=(),
        extra_env={
            "LOCKER_ACCESS_KEY_ID": bootstrap_env["LOCKER_ACCESS_KEY_ID"],
            "LOCKER_SECRET_ACCESS_KEY": bootstrap_env["LOCKER_ACCESS_KEY_SECRET"],
        },
        timeout=timeout,
    )


def _reference_key(reference: Any) -> str | None:
    if not isinstance(reference, str) or not reference.startswith("locker://"):
        return None
    key = reference[len("locker://") :]
    return key if _NAME_RE.fullmatch(key) else None


def _runtime_error_kind(exc: RuntimeError) -> ErrorKind:
    message = str(exc).lower()
    if isinstance(exc.__cause__, subprocess.TimeoutExpired) or "timed out" in message:
        return ErrorKind.TIMEOUT
    if isinstance(exc.__cause__, OSError) or message.startswith("failed to invoke "):
        return ErrorKind.BINARY_MISSING
    return ErrorKind.INTERNAL


class LockerSecretSource(SecretSource):
    name = "locker"
    label = "Locker Secrets"
    shape = "mapped"
    scheme = "locker"

    def override_existing(self, cfg: dict) -> bool:
        # Locker is the intended rotation authority for mapped credentials.
        cfg = cfg if isinstance(cfg, dict) else {}
        return bool(cfg.get("override_existing", True))

    def protected_env_vars(self, cfg: dict):
        return frozenset(_BOOTSTRAP_ENV)

    def fetch_timeout_seconds(self, cfg: dict) -> float:
        cfg = cfg if isinstance(cfg, dict) else {}
        try:
            value = float(cfg.get("timeout_seconds", 15))
        except (TypeError, ValueError):
            return 15.0
        return value if value > 0 else 15.0

    def config_schema(self) -> dict:
        return {
            "enabled": {"description": "Enable Locker secret resolution.", "default": False},
            "env": {"description": "Explicit ENV_VAR to locker://key mappings.", "default": {}},
            "timeout_seconds": {"description": "Resolution timeout per startup pass.", "default": 15},
            "bootstrap_credential": {"description": "Opt-in basename of a protected systemd credential in CREDENTIALS_DIRECTORY; no path or secret value.", "default": None},
            "override_existing": {"description": "Let Locker replace stale shell/.env values.", "default": True},
        }

    def remediation(self, kind: ErrorKind | None, cfg: dict) -> str:
        if kind == ErrorKind.NOT_CONFIGURED:
            return "Provide Locker bootstrap access keys in the protected service environment."
        if kind in {ErrorKind.AUTH_FAILED, ErrorKind.AUTH_EXPIRED}:
            return "Verify Locker bootstrap access keys in the protected service environment."
        if kind == ErrorKind.BINARY_MISSING:
            return "Install the Locker CLI and ensure it is on PATH for the gateway service."
        if kind == ErrorKind.REF_INVALID:
            return "Use explicit locker://lower_snake_case references in secrets.locker.env."
        return super().remediation(kind, cfg)

    def fetch(self, cfg: dict, home_path: Path) -> FetchResult:
        result = FetchResult()
        cfg = cfg if isinstance(cfg, dict) else {}
        mappings = cfg.get("env")
        if not isinstance(mappings, dict) or not mappings:
            result.error = "secrets.locker.enabled is true but no env mappings are configured."
            result.error_kind = ErrorKind.NOT_CONFIGURED
            return result

        parsed: list[tuple[str, str]] = []
        for env_name, reference in mappings.items():
            if not isinstance(env_name, str) or not re.fullmatch(r"[A-Z][A-Z0-9_]*", env_name):
                result.error = "Locker mapping has an invalid environment-variable name."
                result.error_kind = ErrorKind.REF_INVALID
                return result
            key = _reference_key(reference)
            if key is None:
                result.error = "Locker mapping has an invalid reference."
                result.error_kind = ErrorKind.REF_INVALID
                return result
            parsed.append((env_name, key))

        source_env = get_source_environment()
        # Never combine half a profile-specific identity with a shared identity.
        # Profiles without explicit opt-in cannot consume the service credential.
        if "bootstrap_credential" in cfg and not any(k in source_env for k in _BOOTSTRAP_ENV):
            try:
                source_env = _service_bootstrap(cfg["bootstrap_credential"])
            except (OSError, ValueError, AttributeError):
                result.error = "Locker service bootstrap credential is unavailable or invalid."
                result.error_kind = ErrorKind.NOT_CONFIGURED
                return result
        invalid_field = any(
            k in source_env and (not isinstance(source_env[k], str) or not source_env[k].strip()
                                 or any(c in source_env[k] for c in ("\x00", "\n", "\r")))
            for k in _BOOTSTRAP_ENV
        )
        if invalid_field:
            result.error = "Locker bootstrap identity is incomplete or invalid."
            result.error_kind = ErrorKind.NOT_CONFIGURED
            return result
        access_key_id = source_env.get("LOCKER_ACCESS_KEY_ID")
        secret_access_key = source_env.get("LOCKER_ACCESS_KEY_SECRET")
        if (
            not isinstance(access_key_id, str)
            or not access_key_id.strip()
            or not isinstance(secret_access_key, str)
            or not secret_access_key.strip()
        ):
            result.error = "Locker bootstrap access keys are not configured."
            result.error_kind = ErrorKind.NOT_CONFIGURED
            return result

        bootstrap_env = {
            "LOCKER_ACCESS_KEY_ID": access_key_id,
            "LOCKER_ACCESS_KEY_SECRET": secret_access_key,
        }
        values: dict[str, str] = {}
        for env_name, key in parsed:
            try:
                proc = _run_locker(
                    [
                        "locker", "secret", "get",
                        "--plain",
                        "--no-newline",
                        "--refresh",
                        "--", key,
                    ],
                    timeout=self.fetch_timeout_seconds(cfg),
                    bootstrap_env=bootstrap_env,
                )
            except RuntimeError as exc:
                result.error = "Locker CLI could not retrieve a mapped secret."
                result.error_kind = _runtime_error_kind(exc)
                return result
            except Exception:
                result.error = "Locker secret retrieval failed unexpectedly."
                result.error_kind = ErrorKind.INTERNAL
                return result
            if proc.returncode != 0:
                result.error = "Locker rejected or could not retrieve a mapped secret."
                result.error_kind = ErrorKind.AUTH_FAILED
                return result
            value = proc.stdout or ""
            if not value.strip():
                result.error = "Locker returned an empty mapped secret."
                result.error_kind = ErrorKind.EMPTY_VALUE
                return result
            values[env_name] = value

        result.secrets = values
        return result


def register(ctx):
    ctx.register_secret_source(LockerSecretSource())
    ctx.register_cli_command(
        name="locker",
        help="Validate Locker CLI and bootstrap authentication",
        setup_fn=cli.register_cli,
        handler_fn=cli.locker_command,
        description="Safe operator controls for Hermes Locker secret resolution.",
    )
