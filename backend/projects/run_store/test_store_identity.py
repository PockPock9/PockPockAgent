import io
import json
import os
import unittest
from contextlib import contextmanager
from unittest.mock import patch

import app as run_store_app

store = run_store_app.store


@contextmanager
def remote_store(health):
    """The gateway's view: a run-store URL is configured and /health answers ``health``."""

    def fake_urlopen(url, timeout=None):
        if isinstance(health, Exception):
            raise health
        return io.BytesIO(json.dumps(health).encode("utf-8"))

    with patch.dict(os.environ, {"POCKPOCK_RUN_STORE_URL": "http://127.0.0.1:1", "POCKPOCK_RUN_STORE_INTERNAL": "0"}), \
            patch.object(store, "urlopen", fake_urlopen), \
            patch.dict(store._remote_check, {"at": -store._REMOTE_CHECK_SECONDS * 2, "matches": True}):
        yield


class StoreIdentityTests(unittest.TestCase):
    def test_health_reports_the_store_fingerprint(self):
        import asyncio

        health = asyncio.run(run_store_app.health())
        self.assertEqual(health["store"], store.store_identity())
        self.assertRegex(health["store"], r"^[a-f0-9]{16}$")

    def test_a_run_store_with_another_database_is_not_used(self):
        # Issues #60/#61: a leftover run-store from another data folder held the runs.
        with remote_store({"ok": True, "service": "run-store", "store": "0" * 16}):
            with self.assertLogs(store.logger, "WARNING"):
                self.assertFalse(store._use_remote_store())

    def test_the_matching_run_store_is_used(self):
        with remote_store({"ok": True, "service": "run-store", "store": store.store_identity()}):
            self.assertTrue(store._use_remote_store())

    def test_an_older_or_unreachable_run_store_keeps_the_old_behaviour(self):
        with remote_store({"ok": True, "service": "run-store"}):
            self.assertTrue(store._use_remote_store())
        with remote_store(OSError("refused")):
            self.assertTrue(store._use_remote_store())

    def test_the_check_is_cached(self):
        calls = []
        with remote_store({"ok": True, "service": "run-store", "store": store.store_identity()}):
            original = store._remote_store_matches
            with patch.object(store, "_remote_store_matches", lambda: calls.append(1) or original()):
                for _ in range(5):
                    store._use_remote_store()
        self.assertEqual(len(calls), 1)


if __name__ == "__main__":
    unittest.main()
