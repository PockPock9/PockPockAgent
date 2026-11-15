import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parent
EXTENSION = ROOT / "extension"


class ChromeCompanionContractTests(unittest.TestCase):
    def test_manifest_uses_only_temporary_tab_and_native_messaging_permissions(self):
        manifest = json.loads((EXTENSION / "manifest.json").read_text(encoding="utf-8"))

        self.assertEqual(manifest["manifest_version"], 3)
        self.assertEqual(set(manifest["permissions"]), {"activeTab", "nativeMessaging"})
        self.assertNotIn("host_permissions", manifest)
        self.assertNotIn("content_scripts", manifest)

    def test_worker_and_installer_use_the_same_native_host_name(self):
        worker = (EXTENSION / "service_worker.js").read_text(encoding="utf-8")
        installer = (ROOT / "install.ps1").read_text(encoding="utf-8")

        self.assertIn('"com.pockpock.chrome_companion"', worker)
        self.assertIn("name = 'com.pockpock.chrome_companion'", installer)


if __name__ == "__main__":
    unittest.main()
