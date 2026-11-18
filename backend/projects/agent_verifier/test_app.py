"""HTTP boundary checks for the agent verifier service (no live HTTP needed).

FastAPI's TestClient needs httpx, which is not in the repo venv, so these
tests assert on the registered routes and the auth guard instead of making
requests. The ledger/harness behaviour behind the routes is covered by
test_ledger.py / test_harness.py.
"""

import os
import sys
import tempfile
import unittest
from pathlib import Path

_TMP = tempfile.TemporaryDirectory()
os.environ["POCKPOCK_AGENT_VERIFIER_DB"] = str(Path(_TMP.name) / "ledger.sqlite3")

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "projects"))
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import app as verifier_app  # noqa: E402
from agent_verifier.harness import Harness  # noqa: E402


class AppTests(unittest.TestCase):
    def test_routes_are_registered(self):
        routes = {(route.path, tuple(route.methods)) for route in verifier_app.app.routes
                  if hasattr(route, "methods")}
        self.assertIn(("/health", ("GET",)), routes)
        self.assertIn(("/runs", ("POST",)), routes)
        self.assertIn(("/runs", ("GET",)), routes)
        self.assertIn(("/runs/{run_id}", ("GET",)), routes)
        self.assertIn(("/runs/{run_id}/steps/{step_index}", ("GET",)), routes)
        self.assertIn(("/runs/{run_id}/verify", ("POST",)), routes)
        self.assertIn(("/runs/{run_id}/rewind", ("POST",)), routes)
        self.assertIn(("/runs/{run_id}/resume", ("POST",)), routes)

    def test_get_run_or_404_rejects_bad_ids(self):
        from fastapi import HTTPException

        with self.assertRaises(HTTPException) as ctx:
            verifier_app._get_run_or_404("not-a-run-id")
        self.assertEqual(ctx.exception.status_code, 404)
        with self.assertRaises(HTTPException) as ctx:
            verifier_app._get_run_or_404("c" * 32)
        self.assertEqual(ctx.exception.status_code, 404)

    def test_service_ledger_and_harness_share_one_store(self):
        self.assertIsInstance(verifier_app.HARNESS, Harness)
        self.assertIs(verifier_app.HARNESS.ledger, verifier_app.LEDGER)


if __name__ == "__main__":
    unittest.main()
