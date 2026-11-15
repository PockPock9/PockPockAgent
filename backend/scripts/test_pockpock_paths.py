import os
from pathlib import Path
import unittest
from unittest.mock import patch

import pockpock_paths


class UserDataRootTests(unittest.TestCase):
    def setUp(self):
        self.home = Path.cwd() / "test-home"

    def root_for(self, platform_name, environment):
        with patch.object(pockpock_paths.sys, "platform", platform_name):
            with patch.dict(os.environ, environment, clear=True):
                with patch.object(Path, "home", return_value=self.home):
                    return pockpock_paths.user_data_root()

    def test_windows_uses_existing_local_app_data_location(self):
        local_data = str(self.home / "Local")
        self.assertEqual(self.root_for("win32", {"LOCALAPPDATA": local_data}), Path(local_data))

    def test_macos_uses_application_support(self):
        self.assertEqual(
            self.root_for("darwin", {}),
            self.home / "Library" / "Application Support",
        )

    def test_linux_honors_absolute_xdg_data_home(self):
        data_home = self.home / "xdg-data"
        self.assertEqual(
            self.root_for("linux", {"XDG_DATA_HOME": str(data_home)}),
            data_home,
        )

    def test_linux_defaults_to_local_share(self):
        self.assertEqual(
            self.root_for("linux", {}),
            self.home / ".local" / "share",
        )


if __name__ == "__main__":
    unittest.main()
