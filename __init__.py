"""Hermes Locker — Locker Secrets Manager source plugin.

Resolves explicitly mapped ``locker://lower_snake_case`` references through
Locker CLI. Values stay in the Hermes secret-source orchestration path and are
never written by this plugin to config files, logs, or a disk cache.
"""
from __future__ import annotations

import importlib.util
import re
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


def _run_locker(argv: list[str], *, timeout: float, bootstrap_env: dict[str, str]):
    return run_secret_cli(
        argv,
        allow_env=(),
        extra_env=bootstrap_env,
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
                        "--access-key-id", access_key_id,
                        "--secret-access-key-env", "LOCKER_ACCESS_KEY_SECRET",
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
