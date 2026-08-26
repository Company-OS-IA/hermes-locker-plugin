from __future__ import annotations

import importlib.util
import os
import unittest
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import patch

from agent.secret_sources.base import reset_source_environment, set_source_environment


ROOT = Path(__file__).parents[1]
PLUGIN = ROOT / "__init__.py"


def load_plugin():
    spec = importlib.util.spec_from_file_location(
        "hermes_locker", PLUGIN, submodule_search_locations=[str(ROOT)]
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@contextmanager
def source_environment(environ):
    token = set_source_environment(environ)
    try:
        yield
    finally:
        reset_source_environment(token)


class LockerSecretSourceTests(unittest.TestCase):
    def test_runner_passes_only_the_ephemeral_bootstrap_environment(self):
        plugin = load_plugin()
        bootstrap = {
            "LOCKER_ACCESS_KEY_ID": "test-access-key-id",
            "LOCKER_ACCESS_KEY_SECRET": "test-access-key-secret",
        }
        sentinel = object()

        with patch.object(plugin, "run_secret_cli", return_value=sentinel) as run:
            result = plugin._run_locker(
                ["locker", "--version"], timeout=4.0, bootstrap_env=bootstrap
            )

        self.assertIs(result, sentinel)
        run.assert_called_once_with(
            ["locker", "--version"],
            allow_env=(),
            extra_env=bootstrap,
            timeout=4.0,
        )

    def test_fetch_resolves_explicit_locker_references(self):
        plugin = load_plugin()
        seen = []

        class Result:
            returncode = 0
            stderr = ""
            stdout = "value-from-locker"

        def fake_run(argv, *, timeout, bootstrap_env):
            seen.append((argv, timeout, bootstrap_env))
            return Result()

        with source_environment(
            {
                "LOCKER_ACCESS_KEY_ID": "test-access-key-id",
                "LOCKER_ACCESS_KEY_SECRET": "test-access-key-secret",
            }
        ), patch.object(plugin, "_run_locker", fake_run):
            result = plugin.LockerSecretSource().fetch(
                {
                    "enabled": True,
                    "env": {
                        "PRIMARY_API_KEY": "locker://primary_api_key",
                        "SECONDARY_API_TOKEN": "locker://secondary_api_token",
                    },
                },
                Path("/tmp"),
            )

        self.assertTrue(result.ok)
        self.assertEqual(
            result.secrets,
            {
                "PRIMARY_API_KEY": "value-from-locker",
                "SECONDARY_API_TOKEN": "value-from-locker",
            },
        )
        self.assertEqual(
            seen,
            [
                (
                    ["locker", "secret", "get", "--plain", "--no-newline", "--refresh", "--access-key-id", "test-access-key-id", "--secret-access-key-env", "LOCKER_ACCESS_KEY_SECRET", "--", "primary_api_key"],
                    15.0,
                    {
                        "LOCKER_ACCESS_KEY_ID": "test-access-key-id",
                        "LOCKER_ACCESS_KEY_SECRET": "test-access-key-secret",
                    },
                ),
                (
                    ["locker", "secret", "get", "--plain", "--no-newline", "--refresh", "--access-key-id", "test-access-key-id", "--secret-access-key-env", "LOCKER_ACCESS_KEY_SECRET", "--", "secondary_api_token"],
                    15.0,
                    {
                        "LOCKER_ACCESS_KEY_ID": "test-access-key-id",
                        "LOCKER_ACCESS_KEY_SECRET": "test-access-key-secret",
                    },
                ),
            ],
        )

    def test_fetch_rejects_invalid_reference_without_invoking_locker(self):
        plugin = load_plugin()
        with patch.object(plugin, "_run_locker", side_effect=AssertionError("should not run")):
            result = plugin.LockerSecretSource().fetch(
                {"enabled": True, "env": {"PRIMARY_API_KEY": "op://wrong-backend/item"}}, Path("/tmp")
            )

        self.assertFalse(result.ok)
        self.assertEqual(result.error_kind.value, "ref_invalid")
        self.assertEqual(result.secrets, {})

    def test_fetch_never_returns_empty_secret(self):
        plugin = load_plugin()

        class Result:
            returncode = 0
            stderr = ""
            stdout = " \n"

        with source_environment(
            {
                "LOCKER_ACCESS_KEY_ID": "test-access-key-id",
                "LOCKER_ACCESS_KEY_SECRET": "test-access-key-secret",
            }
        ), patch.object(plugin, "_run_locker", return_value=Result()):
            result = plugin.LockerSecretSource().fetch(
                {"enabled": True, "env": {"PRIMARY_API_KEY": "locker://primary_api_key"}}, Path("/tmp")
            )

        self.assertFalse(result.ok)
        self.assertEqual(result.error_kind.value, "empty_value")
        self.assertEqual(result.secrets, {})

    def test_fetch_uses_the_active_profile_without_reusing_values(self):
        plugin = load_plugin()
        seen = []

        def fake_run(argv, *, timeout, bootstrap_env):
            seen.append(dict(bootstrap_env))
            return type(
                "Result",
                (),
                {"returncode": 0, "stdout": bootstrap_env["LOCKER_ACCESS_KEY_ID"], "stderr": ""},
            )()

        results = []
        with patch.dict(
            os.environ,
            {
                "LOCKER_ACCESS_KEY_ID": "global-access-key-id",
                "LOCKER_ACCESS_KEY_SECRET": "global-access-key-secret",
            },
        ), patch.object(plugin, "_run_locker", fake_run):
            for profile in ("first", "second"):
                with source_environment(
                    {
                        "LOCKER_ACCESS_KEY_ID": f"{profile}-access-key-id",
                        "LOCKER_ACCESS_KEY_SECRET": f"{profile}-access-key-secret",
                    }
                ):
                    results.append(
                        plugin.LockerSecretSource().fetch(
                            {"enabled": True, "env": {"API_KEY": "locker://shared_key"}},
                            Path("/tmp"),
                        ).secrets["API_KEY"]
                    )

        self.assertEqual(results, ["first-access-key-id", "second-access-key-id"])
        self.assertEqual(
            seen,
            [
                {
                    "LOCKER_ACCESS_KEY_ID": "first-access-key-id",
                    "LOCKER_ACCESS_KEY_SECRET": "first-access-key-secret",
                },
                {
                    "LOCKER_ACCESS_KEY_ID": "second-access-key-id",
                    "LOCKER_ACCESS_KEY_SECRET": "second-access-key-secret",
                },
            ],
        )

    def test_fetch_normalizes_legacy_bootstrap_only_for_the_subprocess(self):
        plugin = load_plugin()
        seen = []
        result_type = type("Result", (), {"returncode": 0, "stdout": "resolved", "stderr": ""})

        def fake_run(argv, *, timeout, bootstrap_env):
            seen.append(dict(bootstrap_env))
            return result_type()

        profile_env = {
            "LOCKER_ACCESS_KEY_ID": "legacy-access-key-id",
            "LOCKER_SECRET_ACCESS_KEY": "legacy-access-key-secret",
        }
        with source_environment(profile_env), patch.object(plugin, "_run_locker", fake_run):
            result = plugin.LockerSecretSource().fetch(
                {"enabled": True, "env": {"API_KEY": "locker://api_key"}}, Path("/tmp")
            )

        self.assertTrue(result.ok)
        self.assertEqual(
            seen,
            [{
                "LOCKER_ACCESS_KEY_ID": "legacy-access-key-id",
                "LOCKER_ACCESS_KEY_SECRET": "legacy-access-key-secret",
            }],
        )
        self.assertNotIn("LOCKER_ACCESS_KEY_SECRET", profile_env)

    def test_fetch_reports_missing_bootstrap_without_invoking_locker(self):
        plugin = load_plugin()
        with source_environment({}), patch.object(
            plugin, "_run_locker", side_effect=AssertionError("should not run")
        ):
            result = plugin.LockerSecretSource().fetch(
                {"enabled": True, "env": {"API_KEY": "locker://api_key"}}, Path("/tmp")
            )

        self.assertFalse(result.ok)
        self.assertEqual(result.error_kind.value, "not_configured")
        self.assertEqual(result.secrets, {})

    def test_fetch_classifies_runtime_errors(self):
        plugin = load_plugin()
        cases = (
            (RuntimeError("locker timed out after 15s"), "timeout"),
            (RuntimeError("failed to invoke locker: missing"), "binary_missing"),
            (RuntimeError("unexpected helper failure"), "internal"),
        )
        bootstrap = {
            "LOCKER_ACCESS_KEY_ID": "test-access-key-id",
            "LOCKER_ACCESS_KEY_SECRET": "test-access-key-secret",
        }

        for error, expected in cases:
            with self.subTest(expected=expected), source_environment(bootstrap), patch.object(
                plugin, "_run_locker", side_effect=error
            ):
                result = plugin.LockerSecretSource().fetch(
                    {"enabled": True, "env": {"API_KEY": "locker://api_key"}}, Path("/tmp")
                )
            self.assertFalse(result.ok)
            self.assertEqual(result.error_kind.value, expected)
            self.assertEqual(result.secrets, {})

    def test_plugin_registers_the_locker_source(self):
        plugin = load_plugin()

        class Context:
            source = None
            command = None

            def register_secret_source(self, source):
                self.source = source

            def register_cli_command(self, **kwargs):
                self.command = kwargs

        ctx = Context()
        plugin.register(ctx)
        self.assertIsInstance(ctx.source, plugin.LockerSecretSource)
        self.assertEqual(ctx.command["name"], "locker")
        self.assertEqual(ctx.source.name, "locker")


if __name__ == "__main__":
    unittest.main()
