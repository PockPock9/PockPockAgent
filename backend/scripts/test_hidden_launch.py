from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

import hidden_launch

HELPER = Path(hidden_launch.__file__).resolve()


class HiddenLaunchTests(unittest.TestCase):
    def test_requires_log_file_separator_and_command(self):
        for argv in ([], ["log.txt"], ["log.txt", "--"], ["log.txt", "python", "-V"]):
            with self.assertRaises(SystemExit):
                hidden_launch.parse_arguments(argv)

    def test_parses_log_file_and_command(self):
        self.assertEqual(hidden_launch.parse_arguments(["log.txt", "--", "python", "-V"]), ("log.txt", ["python", "-V"]))

    def test_appends_service_output_to_log_and_returns_its_exit_code(self):
        with tempfile.TemporaryDirectory() as folder:
            log = Path(folder) / "service.log"
            log.write_bytes(b"header\n")
            script = "import sys; print('to stdout'); print('to stderr', file=sys.stderr); sys.exit(3)"
            result = subprocess.run([sys.executable, str(HELPER), str(log), "--", sys.executable, "-c", script], capture_output=True, timeout=60)
            self.assertEqual(result.returncode, 3)
            text = log.read_text(encoding="utf-8")
            self.assertTrue(text.startswith("header\n"))
            self.assertIn("to stdout", text)
            self.assertIn("to stderr", text)


if __name__ == "__main__":
    unittest.main()
