"""Exercise installed Hermes hydration/registry/scope, without network or real keys."""
import json
import os
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace
from unittest.mock import patch

from test_locker_source import load_plugin
from test_systemd_bootstrap import credential


def test_cold_hydration_profile_isolation_and_failure_cache(tmp_path):
    from agent.secret_sources.registry import register_source, restore_registration, snapshot_registration
    from agent.secret_scope import build_profile_secret_scope
    from hermes_cli.env_loader import hydrate_profile_secret_sources, reset_secret_source_cache
    from hermes_constants import set_hermes_home_override, reset_hermes_home_override
    plugin = load_plugin()
    directory, _ = credential(tmp_path)
    source = plugin.LockerSecretSource()
    homes = {name: tmp_path / name for name in ("a", "b", "c")}
    old = {}
    configurations = {}
    for name, home in homes.items():
        home.mkdir()
        config = {"enabled": True, "env": {f"PROFILE_{name.upper()}_KEY": f"locker://profile_{name}_key"}}
        if name != "c": config["bootstrap_credential"] = "locker_bootstrap_env"
        configurations[name] = config
        (home / "config.yaml").write_text(json.dumps({"secrets": {"locker": config}}))
        old[str(home)] = snapshot_registration("locker", scope=str(home))
        assert register_source(source, replace=True, scope=str(home))
    def fetch(name):
        home = homes[name]
        token = set_hermes_home_override(str(home))
        try:
            hydrate_profile_secret_sources(home)
            return build_profile_secret_scope(home)
        finally:
            reset_hermes_home_override(token)
    def fake_cli(argv, *, timeout, bootstrap_env):
        assert bootstrap_env == {"LOCKER_ACCESS_KEY_ID": "test-systemd-id", "LOCKER_ACCESS_KEY_SECRET": "test-systemd-secret"}
        return SimpleNamespace(returncode=0, stdout=f"value-for-{argv[-1]}", stderr="")
    try:
        reset_secret_source_cache()
        with patch.dict(os.environ, {"CREDENTIALS_DIRECTORY": str(directory), "LOCKER_ACCESS_KEY_ID": "ambient-other-id", "LOCKER_ACCESS_KEY_SECRET": "ambient-other-secret", "UNRELATED_API_KEY": "ambient-unrelated"}, clear=True), patch.object(plugin, "_run_locker", fake_cli):
            before = dict(os.environ)
            with ThreadPoolExecutor(max_workers=3) as pool:
                results = dict(zip(("b", "c", "a"), pool.map(fetch, ("b", "c", "a"))))
            assert results == {"a": {"PROFILE_A_KEY": "value-for-profile_a_key"}, "b": {"PROFILE_B_KEY": "value-for-profile_b_key"}, "c": {}}
            assert dict(os.environ) == before
            configurations["c"]["bootstrap_credential"] = "locker_bootstrap_env"
            (homes["c"] / "config.yaml").write_text(json.dumps({"secrets": {"locker": configurations["c"]}}))
            assert fetch("c") == {}  # Failed fetch is memoized in this Hermes runtime.
            reset_secret_source_cache()
            assert fetch("c") == {"PROFILE_C_KEY": "value-for-profile_c_key"}
            assert dict(os.environ) == before
    finally:
        reset_secret_source_cache()
        for home in homes.values():
            restore_registration("locker", source, old[str(home)], scope=str(home))
