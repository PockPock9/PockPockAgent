import asyncio
import hashlib
import io
import json
import os
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import patch
from urllib.error import HTTPError

from fastapi import HTTPException

import app as run_store_app
from test_event_contracts import isolated_store

store = run_store_app.store


def run(coroutine):
    return asyncio.run(coroutine)


def approval_payload(action):
    action_hash = hashlib.sha256(
        json.dumps(action, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    expires_at = (datetime.now(timezone.utc) + timedelta(minutes=5)).isoformat()
    return run_store_app.NewApproval(approval_id="9" * 32, action_hash=action_hash, action=action, expires_at=expires_at)


class RunStoreErrorCodeTests(unittest.TestCase):
    def test_finish_on_an_unknown_run_is_404(self):
        # Issue #49: finish answered {"finished": true} while cancel and events answered 404.
        with isolated_store():
            store.initialize_agent_store()
            with self.assertRaises(HTTPException) as ctx:
                run(run_store_app.finish_run("d" * 32))
            self.assertEqual(ctx.exception.status_code, 404)
            store.create_agent_run("e" * 32, None, "agent", "known run")
            self.assertEqual(run(run_store_app.finish_run("e" * 32)), {"finished": True})

    def test_delegate_result_on_a_run_that_is_not_delegated_is_422(self):
        # Issue #67: delegation is None on ordinary runs, which crashed with AttributeError (500).
        with isolated_store():
            store.initialize_agent_store()
            store.create_agent_run("f" * 32, None, "agent", "ordinary run")
            payload = run_store_app.NewEvent(sequence=1, event={"type": "delegate_result", "parent_run_id": "a" * 32})
            with self.assertRaises(HTTPException) as ctx:
                run(run_store_app.append_event("f" * 32, payload))
            self.assertEqual(ctx.exception.status_code, 422)

    def test_a_reused_approval_id_is_409(self):
        # Issue #68: the second insert raised sqlite3.IntegrityError (500).
        with isolated_store():
            store.initialize_agent_store()
            store.create_agent_run("8" * 32, None, "agent", "approval run")
            payload = approval_payload({"tool": "propose_project_patch", "path": "index.html", "diff": "-a\n+b"})
            run(run_store_app.create_approval("8" * 32, payload))
            with self.assertRaises(HTTPException) as ctx:
                run(run_store_app.create_approval("8" * 32, payload))
            self.assertEqual(ctx.exception.status_code, 409)
            self.assertIn("approval ID", ctx.exception.detail)


class ServiceErrorDetailTests(unittest.TestCase):
    def setUp(self):
        self.env = patch.dict(os.environ, {"POCKPOCK_RUN_STORE_URL": "http://127.0.0.1:1", "POCKPOCK_RUN_STORE_INTERNAL": "0"})
        self.env.start()

    def tearDown(self):
        self.env.stop()

    def fail_with(self, code, detail):
        body = io.BytesIO(json.dumps({"detail": detail}).encode("utf-8"))
        error = HTTPError("http://127.0.0.1:1/x", code, "error", {}, body)
        return patch.object(store, "urlopen", side_effect=error)

    def test_the_service_detail_is_kept(self):
        # Issue #71: every 404 became "Run not found", even for an unknown approval.
        with self.fail_with(404, "Approval not found"):
            with self.assertRaisesRegex(store.RunNotFound, "Approval not found"):
                store._service_request("/runs/" + "a" * 32 + "/approvals/" + "b" * 32, method="POST", payload={})
        with self.fail_with(409, "Approvals can only be requested for an active run"):
            with self.assertRaisesRegex(ValueError, "active run") as ctx:
                store._service_request("/runs/" + "a" * 32 + "/approvals", method="POST", payload={})
            self.assertNotIsInstance(ctx.exception, store.RunAlreadyExists)
        with self.fail_with(409, "duplicate"):
            with self.assertRaises(store.RunAlreadyExists):
                store._service_request("/runs", method="POST", payload={})

    def test_an_unknown_run_reads_as_no_run(self):
        # Issue #66: RunNotFound escaped get_run_events and the gateway answered 500.
        with self.fail_with(404, "Run not found"):
            self.assertEqual(store.get_run_events("c" * 32, 0, 10), (None, []))


if __name__ == "__main__":
    unittest.main()
