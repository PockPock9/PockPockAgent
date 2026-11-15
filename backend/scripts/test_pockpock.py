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
            pockpock.REPOSITORY_ROOT / "backend" / "scripts" / "requirements-frog-ai.txt",
        )
        self.assertEqual(
            {path.parent.name for path in files[1:]},
            {"agent_tools", "browser_automation", "planner", "run_store", "validator"},
        )

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


if __name__ == "__main__":
    unittest.main()
