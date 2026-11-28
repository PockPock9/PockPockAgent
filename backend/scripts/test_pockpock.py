import os
from pathlib import Path
import stat
import tempfile
import unittest
from unittest.mock import patch

import pockpock


class LauncherTests(unittest.TestCase):
    def test_virtual_environment_python_path_is_platform_specific(self):
        root = Path.cwd()
        self.assertEqual(
            pockpock.venv_python_path(root, "win32"),
            root / ".venv" / "Scripts" / "python.exe",
        )
        self.assertEqual(
            pockpock.venv_python_path(root, "darwin"),
            root / ".venv" / "bin" / "python",
        )

    def test_dependency_manifests_include_gateway_and_project_requirements(self):
        files = pockpock.requirements_files()
        self.assertEqual(
            files[0],
            pockpock.REPOSITORY_ROOT / "backend" / "scripts" / "requirements-pockpock.txt",
        )
        self.assertEqual(
            {path.parent.name for path in files[1:]},
            {"agent_tools", "agent_verifier", "browser_automation", "coding_cli", "planner", "run_store", "validator"},
        )

    def test_the_browser_download_is_retried(self):
        # Issue #51: one failed Chromium download failed the whole setup.
        import subprocess

        calls, sleeps = [], []

        def flaky(command, **kwargs):
            calls.append(command)
            if len(calls) < 3:
                raise subprocess.CalledProcessError(1, command)

        pockpock.install_browser(Path("python"), Path("."), run=flaky, sleep=sleeps.append)
        self.assertEqual(len(calls), 3)
        self.assertEqual(sleeps, [5.0, 10.0])

        def broken(command, **kwargs):
            raise subprocess.CalledProcessError(1, command)

        with self.assertRaisesRegex(RuntimeError, "after 3 tries"):
            pockpock.install_browser(Path("python"), Path("."), run=broken, sleep=lambda seconds: None)

    def test_every_service_hides_its_api_schema(self):
        # Issue #70: docs were off but /openapi.json still served the full schema.
        import re

        backend = pockpock.REPOSITORY_ROOT / "backend"
        sources = [backend / "scripts" / "pockpock_server.py", *backend.glob("projects/*/app.py")]
        apps = 0
        for source in sources:
            for call in re.findall(r"FastAPI\((.*?)\)\n", source.read_text(encoding="utf-8")):
                apps += 1
                self.assertIn("openapi_url=None", call, source)
        self.assertGreaterEqual(apps, 6)

    def test_internal_token_is_persistent_and_private(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            data_directory = Path(temporary_directory)
            with patch("pockpock.app_data_dir", return_value=data_directory):
                token = pockpock.get_internal_token()
                token_path = data_directory / "services.token"
                self.assertTrue(token)
                self.assertEqual(pockpock.get_internal_token(), token)
                if os.name != "nt":
                    self.assertEqual(stat.S_IMODE(token_path.stat().st_mode), 0o600)

    def test_service_environment_configures_loopback_endpoints(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            with patch("pockpock.app_data_dir", return_value=Path(temporary_directory)):
                environment = pockpock.service_environment()
        self.assertTrue(environment["POCKPOCK_INTERNAL_TOKEN"])
        self.assertEqual(environment["POCKPOCK_PLANNER_URL"], "http://127.0.0.1:8771")
        self.assertEqual(environment["POCKPOCK_BROWSER_AUTOMATION_URL"], "http://127.0.0.1:8774")

    def test_existing_api_uses_its_health_route_without_starting_another_process(self):
        processes = []
        with patch("pockpock.service_is_healthy", return_value=True) as health_check:
            with patch("pockpock.launch_process") as launch:
                pockpock.start_service(
                    "PockPock AI",
                    [],
                    Path.cwd(),
                    8766,
                    {},
                    Path.cwd(),
                    processes,
                    health_path="/api/health",
                )
        health_check.assert_called_once_with("http://127.0.0.1:8766/api/health", "PockPock AI")
        launch.assert_not_called()
        self.assertEqual(processes, [])

    def test_check_command_starts_services_without_waiting_for_interrupt(self):
        with patch("pockpock.start_stack") as start:
            self.assertEqual(pockpock.main(["check"]), 0)
        start.assert_called_once_with(supervise=False)


class LegacyDataMigrationTests(unittest.TestCase):
    def test_moves_missing_entries_and_keeps_existing_ones(self):
        import pockpock_paths

        with tempfile.TemporaryDirectory() as temp, patch.object(pockpock_paths, "user_data_root", return_value=Path(temp)):
            legacy = Path(temp) / "FrogAI"
            (legacy / "logs").mkdir(parents=True)
            (legacy / "logs" / "planner.log").write_text("old log", encoding="utf-8")
            (legacy / "services.token").write_text("old-token", encoding="utf-8")
            target = Path(temp) / "PockPock"
            target.mkdir()
            (target / "services.token").write_text("new-token", encoding="utf-8")

            moved = pockpock_paths.migrate_legacy_data()

            self.assertEqual(moved, ["logs"])
            self.assertEqual((target / "logs" / "planner.log").read_text(encoding="utf-8"), "old log")
            self.assertEqual((target / "services.token").read_text(encoding="utf-8"), "new-token")
            self.assertTrue((legacy / "services.token").exists())  # not overwritten, left in place

    def test_removes_the_legacy_folder_once_empty(self):
        import pockpock_paths

        with tempfile.TemporaryDirectory() as temp, patch.object(pockpock_paths, "user_data_root", return_value=Path(temp)):
            (Path(temp) / "FrogAI" / "browser-recipes.sqlite3").parent.mkdir(parents=True)
            (Path(temp) / "FrogAI" / "browser-recipes.sqlite3").write_bytes(b"db")

            self.assertEqual(pockpock_paths.migrate_legacy_data(), ["browser-recipes.sqlite3"])
            self.assertFalse((Path(temp) / "FrogAI").exists())
            self.assertEqual(pockpock_paths.migrate_legacy_data(), [])


if __name__ == "__main__":
    unittest.main()
