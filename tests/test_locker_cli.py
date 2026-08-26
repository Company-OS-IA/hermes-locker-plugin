from __future__ import annotations

import importlib.util
import io
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).parents[1]
PLUGIN = ROOT / "__init__.py"


def load_plugin():
    spec = importlib.util.spec_from_file_location(
        "hermes_locker_cli", PLUGIN, submodule_search_locations=[str(ROOT)]
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class LockerCliTests(unittest.TestCase):
    def test_version_check_does_not_receive_authentication(self):
        plugin = load_plugin()
        cli = plugin.cli
        result = type("Result", (), {"returncode": 0, "stdout": "Locker test", "stderr": ""})()

        with patch.dict(
            cli.os.environ,
            {
                "LOCKER_ACCESS_KEY_ID": "test-access-key-id",
                "LOCKER_ACCESS_KEY_SECRET": "test-access-key-secret",
            },
        ), patch.object(cli.subprocess, "run", return_value=result) as run:
            version = cli._locker_version("/usr/local/bin/locker")

        self.assertEqual(version, "Locker test")
        self.assertNotIn("LOCKER_ACCESS_KEY_ID", run.call_args.kwargs["env"])
        self.assertNotIn("LOCKER_ACCESS_KEY_SECRET", run.call_args.kwargs["env"])

    def test_status_reports_missing_cli_without_installing(self):
        plugin = load_plugin()
        cli = plugin.cli
        output = io.StringIO()
        with patch.object(cli.shutil, "which", return_value=None), redirect_stdout(output):
            rc = cli.locker_command(type("Args", (), {"locker_command": "status", "probe_key": None})())

        self.assertEqual(rc, 1)
        self.assertIn("locker CLI: missing", output.getvalue())
        self.assertNotIn("curl", output.getvalue())

    def test_status_probe_discards_value_and_reports_authentication(self):
        plugin = load_plugin()
        cli = plugin.cli

        class Result:
            returncode = 0
            stdout = "never-print-this-secret"
            stderr = ""

        output = io.StringIO()
        with patch.dict(
            cli.os.environ,
            {
                "LOCKER_ACCESS_KEY_ID": "test-access-key-id",
                "LOCKER_ACCESS_KEY_SECRET": "test-access-key-secret",
            },
        ), patch.object(cli.shutil, "which", return_value="/usr/local/bin/locker"), \
             patch.object(cli, "_locker_version", return_value="Locker version test"), \
             patch.object(cli.subprocess, "run", return_value=Result()) as run, \
             redirect_stdout(output):
            rc = cli.locker_command(type("Args", (), {"locker_command": "status", "probe_key": "test_key"})())

        self.assertEqual(rc, 0)
        self.assertIn("authentication probe: passed", output.getvalue())
        self.assertNotIn("never-print-this-secret", output.getvalue())
        self.assertEqual(
            run.call_args.args[0],
            ["/usr/local/bin/locker", "secret", "get", "--plain", "--no-newline", "--refresh", "--access-key-id", "test-access-key-id", "--secret-access-key-env", "LOCKER_ACCESS_KEY_SECRET", "--", "test_key"],
        )

    def test_status_probe_filters_unrelated_environment(self):
        plugin = load_plugin()
        cli = plugin.cli
        result = type("Result", (), {"returncode": 0, "stdout": "resolved", "stderr": ""})()
        output = io.StringIO()

        with patch.dict(
            cli.os.environ,
            {
                "LOCKER_ACCESS_KEY_ID": "test-access-key-id",
                "LOCKER_ACCESS_KEY_SECRET": "test-access-key-secret",
                "UNRELATED_SECRET": "must-not-reach-child",
            },
        ), patch.object(cli.shutil, "which", return_value="/usr/local/bin/locker"), patch.object(
            cli, "_locker_version", return_value="Locker version test"
        ), patch.object(cli.subprocess, "run", return_value=result) as run, redirect_stdout(output):
            rc = cli.locker_command(
                type("Args", (), {"locker_command": "status", "probe_key": "test_key"})()
            )

        self.assertEqual(rc, 0)
        child_env = run.call_args.kwargs["env"]
        self.assertEqual(child_env["LOCKER_ACCESS_KEY_ID"], "test-access-key-id")
        self.assertEqual(child_env["LOCKER_ACCESS_KEY_SECRET"], "test-access-key-secret")
        self.assertNotIn("UNRELATED_SECRET", child_env)

    def test_status_probe_does_not_print_helper_stderr(self):
        plugin = load_plugin()
        cli = plugin.cli
        result = type(
            "Result",
            (),
            {"returncode": 1, "stdout": "", "stderr": "diagnostic-containing-sensitive-data"},
        )()
        output = io.StringIO()

        with patch.dict(
            cli.os.environ,
            {
                "LOCKER_ACCESS_KEY_ID": "test-access-key-id",
                "LOCKER_ACCESS_KEY_SECRET": "test-access-key-secret",
            },
        ), patch.object(cli.shutil, "which", return_value="/usr/local/bin/locker"), patch.object(
            cli, "_locker_version", return_value="Locker version test"
        ), patch.object(cli.subprocess, "run", return_value=result), redirect_stdout(output):
            rc = cli.locker_command(
                type("Args", (), {"locker_command": "status", "probe_key": "test_key"})()
            )

        self.assertEqual(rc, 1)
        self.assertIn("authentication probe: failed", output.getvalue())
        self.assertNotIn("diagnostic-containing-sensitive-data", output.getvalue())

    def test_status_probe_reports_only_the_structured_error_code(self):
        plugin = load_plugin()
        cli = plugin.cli
        result = type(
            "Result",
            (),
            {
                "returncode": 3,
                "stdout": "",
                "stderr": "Error: sensitive diagnostic\nCode: unauthorized\nHint: sensitive hint",
            },
        )()
        output = io.StringIO()

        with patch.dict(
            cli.os.environ,
            {
                "LOCKER_ACCESS_KEY_ID": "test-access-key-id",
                "LOCKER_ACCESS_KEY_SECRET": "test-access-key-secret",
            },
        ), patch.object(cli.shutil, "which", return_value="/usr/local/bin/locker"), patch.object(
            cli, "_locker_version", return_value="Locker version test"
        ), patch.object(cli.subprocess, "run", return_value=result), redirect_stdout(output):
            rc = cli.locker_command(
                type("Args", (), {"locker_command": "status", "probe_key": "test_key"})()
            )

        self.assertEqual(rc, 1)
        self.assertIn("authentication probe: failed (unauthorized)", output.getvalue())
        self.assertNotIn("sensitive diagnostic", output.getvalue())
        self.assertNotIn("sensitive hint", output.getvalue())

    def test_status_probe_requires_profile_bootstrap(self):
        plugin = load_plugin()
        cli = plugin.cli
        output = io.StringIO()

        with patch.object(cli.shutil, "which", return_value="/usr/local/bin/locker"), patch.object(
            cli, "_locker_version", return_value="Locker version test"
        ), patch.object(cli.subprocess, "run", side_effect=AssertionError("should not run")), redirect_stdout(output):
            rc = cli.locker_command(
                type("Args", (), {"locker_command": "status", "probe_key": "test_key"})()
            )

        self.assertEqual(rc, 1)
        self.assertIn("bootstrap access keys not configured", output.getvalue())

    def test_setup_rejects_oauth_as_unsupported(self):
        plugin = load_plugin()
        cli = plugin.cli
        output = io.StringIO()
        args = type("Args", (), {"locker_command": "setup", "auth_mode": "oauth"})()
        with redirect_stdout(output):
            rc = cli.locker_command(args)

        self.assertEqual(rc, 2)
        self.assertIn("OAuth is not supported", output.getvalue())

    def test_setup_rejects_credential_file_for_startup(self):
        plugin = load_plugin()
        cli = plugin.cli
        output = io.StringIO()
        args = type("Args", (), {"locker_command": "setup", "auth_mode": "credential-file"})()
        with redirect_stdout(output):
            rc = cli.locker_command(args)

        self.assertEqual(rc, 2)
        self.assertIn("not supported for Hermes startup", output.getvalue())

    def test_plugin_registers_cli_and_secret_source(self):
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


if __name__ == "__main__":
    unittest.main()
