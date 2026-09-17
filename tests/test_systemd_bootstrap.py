"""Synthetic bootstrap fixtures only; never run tests with live credentials."""
import os
import pytest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from test_locker_source import load_plugin, source_environment


def credential(tmp_path):
    directory = tmp_path / "credentials"
    directory.mkdir(mode=0o700)
    item = directory / "locker_bootstrap_env"
    item.write_text("LOCKER_ACCESS_KEY_ID=test-systemd-id\nLOCKER_ACCESS_KEY_SECRET=test-systemd-secret\n")
    item.chmod(0o400)
    return directory, item


def config(**extra):
    return {"enabled": True, "env": {"COMPOSIO_API_KEY": "locker://composio_api_key"}, **extra}


def test_cold_profile_resolves_opted_in_service_credential_without_global_secret(tmp_path):
    plugin = load_plugin()
    directory, _ = credential(tmp_path)
    with patch.dict(os.environ, {"CREDENTIALS_DIRECTORY": str(directory)}, clear=True), source_environment({}), patch.object(
        plugin, "_run_locker", return_value=SimpleNamespace(returncode=0, stdout="test-composio", stderr="")
    ) as run:
        before = dict(os.environ)
        result = plugin.LockerSecretSource().fetch(config(bootstrap_credential="locker_bootstrap_env"), tmp_path)
        assert result.ok
        assert result.secrets == {"COMPOSIO_API_KEY": "test-composio"}
        assert run.call_args.kwargs["bootstrap_env"] == {
            "LOCKER_ACCESS_KEY_ID": "test-systemd-id", "LOCKER_ACCESS_KEY_SECRET": "test-systemd-secret"
        }
        assert dict(os.environ) == before


def test_bootstrap_identity_never_appears_in_locker_process_arguments(tmp_path):
    plugin = load_plugin()
    with source_environment({"LOCKER_ACCESS_KEY_ID": "test-private-id", "LOCKER_ACCESS_KEY_SECRET": "test-private-secret"}), patch.object(
        plugin, "run_secret_cli", return_value=SimpleNamespace(returncode=0, stdout="test-composio", stderr="")
    ) as run:
        result = plugin.LockerSecretSource().fetch(config(), tmp_path)
        assert result.ok
        argv = run.call_args.args[0]
        assert "test-private-id" not in argv
        assert "test-private-secret" not in argv
        assert run.call_args.kwargs["extra_env"] == {
            "LOCKER_ACCESS_KEY_ID": "test-private-id", "LOCKER_SECRET_ACCESS_KEY": "test-private-secret"
        }


@pytest.mark.parametrize("case", [
    "no_opt_in", "traversal", "absolute_name", "empty_name", "missing_directory",
    "relative_directory", "directory_symlink", "directory_permissions", "file_symlink",
    "file_permissions", "file_executable", "fifo", "oversized", "duplicate", "unknown_key",
    "blank_value", "missing_pair", "nul", "invalid_utf8", "conflicting_aliases", "partial_profile",
])
def test_unsafe_or_unconfigured_bootstrap_fails_closed(tmp_path, case):
    plugin = load_plugin()
    directory, item = credential(tmp_path)
    env = {"CREDENTIALS_DIRECTORY": str(directory), "LOCKER_ACCESS_KEY_ID": "ambient-id", "LOCKER_ACCESS_KEY_SECRET": "ambient-secret"}
    cfg = config(bootstrap_credential="locker_bootstrap_env")
    scoped = {}
    if case == "no_opt_in": cfg.pop("bootstrap_credential")
    elif case == "traversal": cfg["bootstrap_credential"] = "../locker_bootstrap_env"
    elif case == "absolute_name": cfg["bootstrap_credential"] = str(item)
    elif case == "empty_name": cfg["bootstrap_credential"] = ""
    elif case == "missing_directory": env.pop("CREDENTIALS_DIRECTORY")
    elif case == "relative_directory": env["CREDENTIALS_DIRECTORY"] = "credentials"
    elif case == "directory_symlink":
        link = tmp_path / "link"
        link.symlink_to(directory, target_is_directory=True)
        env["CREDENTIALS_DIRECTORY"] = str(link)
    elif case == "directory_permissions": directory.chmod(0o755)
    elif case == "file_symlink":
        target = directory / "other"
        item.rename(target)
        item.symlink_to(target)
    elif case == "file_permissions": item.chmod(0o644)
    elif case == "file_executable": item.chmod(0o700)
    elif case == "fifo":
        item.unlink()
        os.mkfifo(item, 0o600)
    elif case == "oversized": item.write_bytes(b"x" * 16385)
    elif case == "duplicate": item.write_text("LOCKER_ACCESS_KEY_ID=a\nLOCKER_ACCESS_KEY_ID=b\nLOCKER_ACCESS_KEY_SECRET=c\n")
    elif case == "unknown_key": item.write_text("UNRELATED_SECRET=fixture-private-content\n")
    elif case == "blank_value": item.write_text("LOCKER_ACCESS_KEY_ID= \nLOCKER_ACCESS_KEY_SECRET=c\n")
    elif case == "missing_pair": item.write_text("LOCKER_ACCESS_KEY_ID=a\n")
    elif case == "nul": item.write_bytes(b"LOCKER_ACCESS_KEY_ID=a\x00b\nLOCKER_ACCESS_KEY_SECRET=c\n")
    elif case == "invalid_utf8": item.write_bytes(b"\xff")
    elif case == "conflicting_aliases": item.write_text("LOCKER_ACCESS_KEY_ID=a\nLOCKER_ACCESS_KEY_SECRET=b\nLOCKER_SECRET_ACCESS_KEY=c\n")
    elif case == "partial_profile": scoped["LOCKER_ACCESS_KEY_ID"] = "profile-specific-id"
    with patch.dict(os.environ, env, clear=True), source_environment(scoped), patch.object(plugin, "_run_locker") as run:
        result = plugin.LockerSecretSource().fetch(cfg, tmp_path)
    assert not result.ok
    assert result.secrets == {}
    assert result.error_kind.value == "not_configured"
    assert "fixture-private-content" not in result.error
    assert "ambient-secret" not in result.error
    run.assert_not_called()


def test_complete_profile_identity_takes_precedence_without_file_access(tmp_path):
    plugin = load_plugin()
    with source_environment({"LOCKER_ACCESS_KEY_ID": "profile-id", "LOCKER_ACCESS_KEY_SECRET": "profile-secret"}), patch.object(
        plugin, "_service_bootstrap", side_effect=AssertionError("must not read shared identity")
    ), patch.object(plugin, "_run_locker", return_value=SimpleNamespace(returncode=0, stdout="own-value", stderr="")) as run:
        result = plugin.LockerSecretSource().fetch(config(bootstrap_credential="locker_bootstrap_env"), tmp_path)
    assert result.ok
    assert run.call_args.kwargs["bootstrap_env"]["LOCKER_ACCESS_KEY_ID"] == "profile-id"


def test_service_rotation_has_no_cache_and_profile_without_opt_in_gets_nothing(tmp_path):
    plugin = load_plugin()
    directory, item = credential(tmp_path)
    seen = []
    def fake(argv, *, timeout, bootstrap_env):
        seen.append(bootstrap_env["LOCKER_ACCESS_KEY_SECRET"])
        return SimpleNamespace(returncode=0, stdout="mapped-value", stderr="")
    with patch.dict(os.environ, {"CREDENTIALS_DIRECTORY": str(directory)}, clear=True), source_environment({}), patch.object(plugin, "_run_locker", fake):
        first = plugin.LockerSecretSource().fetch(config(bootstrap_credential="locker_bootstrap_env"), tmp_path)
        item.write_text("LOCKER_ACCESS_KEY_ID=test-systemd-id\nLOCKER_ACCESS_KEY_SECRET=test-rotated-secret\n")
        second = plugin.LockerSecretSource().fetch(config(bootstrap_credential="locker_bootstrap_env"), tmp_path)
        third = plugin.LockerSecretSource().fetch(config(), tmp_path)
    assert first.ok and second.ok and not third.ok
    assert seen == ["test-systemd-secret", "test-rotated-secret"]
    assert third.secrets == {}


@pytest.mark.parametrize("scoped", [
    {"LOCKER_ACCESS_KEY_ID": ""},
    {"LOCKER_ACCESS_KEY_SECRET": ""},
    {"LOCKER_ACCESS_KEY_ID": "id", "LOCKER_ACCESS_KEY_SECRET": "   "},
])
def test_invalid_profile_bootstrap_never_borrows_service_identity(tmp_path, scoped):
    plugin = load_plugin()
    directory, _ = credential(tmp_path)
    with patch.dict(os.environ, {"CREDENTIALS_DIRECTORY": str(directory)}, clear=True), source_environment(scoped), patch.object(plugin, "_service_bootstrap") as file_read, patch.object(plugin, "_run_locker") as run:
        result = plugin.LockerSecretSource().fetch(config(bootstrap_credential="locker_bootstrap_env"), tmp_path)
    assert not result.ok
    file_read.assert_not_called()
    run.assert_not_called()


def test_symlink_ancestor_of_credential_directory_is_rejected(tmp_path):
    plugin = load_plugin()
    directory, _ = credential(tmp_path)
    alias = tmp_path / "ancestor_alias"
    alias.symlink_to(tmp_path, target_is_directory=True)
    with patch.dict(os.environ, {"CREDENTIALS_DIRECTORY": str(alias / "credentials")}, clear=True), source_environment({}), patch.object(plugin, "_run_locker", return_value=SimpleNamespace(returncode=0, stdout="mapped", stderr="")) as run:
        result = plugin.LockerSecretSource().fetch(config(bootstrap_credential="locker_bootstrap_env"), tmp_path)
    assert not result.ok
    run.assert_not_called()
