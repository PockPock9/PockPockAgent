"""Tests for the promotion gate: inbox, verification, approve/reject."""

import json
import tempfile
import unittest
from pathlib import Path

from projects.agent_skills.inbox import (
    Candidate,
    SkillInbox,
    VerificationResult,
    run_verification,
)
from projects.agent_skills.memory import ReasoningMemory, connect_sqlite
from projects.agent_skills.skills import Skill, SkillLibrary

SKILL_MD = """---
name: "summarise-csv"
description: "Summarise a CSV file into a short markdown table."
version: "0.1.0"
verification: {"type": "python", "code": "assert 1 + 1 == 2"}
tags: ["csv"]
---

# Summarise a CSV

1. Read the CSV file.
2. Write a short markdown table.
"""

TIP_PAYLOAD = json.dumps({
    "title": "Retry with backoff",
    "description": "Retries need a delay.",
    "content": "Wait before retrying or the server throttles you.",
    "kind": "success",
    "action": "retry with backoff",
    "task_tag": "api-call",
    "confidence": 0.8,
})


class VerificationTests(unittest.TestCase):
    def test_python_pass(self):
        result = run_verification({"type": "python", "code": "assert 2 * 3 == 6"})
        self.assertTrue(result.passed)
        self.assertEqual(result.method, "python")

    def test_python_fail(self):
        result = run_verification({"type": "python", "code": "raise SystemExit(3)"})
        self.assertFalse(result.passed)

    def test_script_pass_and_fail(self):
        self.assertTrue(run_verification(
            {"type": "script", "command": ["python3", "-c", "pass"]}).passed)
        self.assertFalse(run_verification(
            {"type": "script", "command": ["python3", "-c", "import sys; sys.exit(1)"]}).passed)

    def test_manual_is_not_verified(self):
        result = run_verification({"type": "manual"})
        self.assertFalse(result.passed)
        self.assertEqual(result.method, "manual")

    def test_unknown_type_fails_closed(self):
        result = run_verification({"type": "telepathy"})
        self.assertFalse(result.passed)

    def test_missing_command_fails_closed(self):
        self.assertFalse(run_verification({"type": "script"}).passed)


class InboxTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.library = SkillLibrary(root / "skills", dense_enabled=False)
        self.memory = ReasoningMemory(connect_sqlite(root / "m.sqlite3"))
        self.inbox = SkillInbox(connect_sqlite(root / "m.sqlite3"), self.library, self.memory)

    def tearDown(self):
        self.tmp.cleanup()

    def _submit_skill(self):
        return self.inbox.submit(Candidate(
            kind="skill", payload=SKILL_MD, name="summarise-csv",
            source_run_id="run-1",
            verification={"type": "python", "code": "assert 1 + 1 == 2"},
        ))

    def test_submit_starts_pending(self):
        candidate = self._submit_skill()
        self.assertEqual(candidate.status, "pending")
        self.assertEqual([c.id for c in self.inbox.list()], [candidate.id])

    def test_approve_requires_verification(self):
        candidate = self._submit_skill()
        with self.assertRaises(ValueError):
            self.inbox.approve(candidate.id, reason="looks good")

    def test_verify_then_approve_promotes_skill(self):
        candidate = self._submit_skill()
        result = self.inbox.verify(candidate.id)
        self.assertTrue(result.passed)
        approved = self.inbox.approve(candidate.id, reason="test passed")
        self.assertEqual(approved.status, "approved")
        # The skill file now exists and is promoted in the registry.
        record = self.library.read("summarise-csv")
        self.assertEqual(record.skill.status, "promoted")
        self.assertEqual(self.library.retrieve("summarise the csv file")[0].skill.name, "summarise-csv")

    def test_unverified_candidate_never_retrievable(self):
        candidate = self._submit_skill()
        # Even though the skill file does not exist yet, nothing is retrievable.
        self.assertEqual(self.library.retrieve("summarise the csv file"), [])
        # Rejecting keeps it that way forever.
        self.inbox.reject(candidate.id, reason="not useful")
        self.assertEqual(self.library.retrieve("summarise the csv file"), [])

    def test_reject_needs_reason(self):
        candidate = self._submit_skill()
        with self.assertRaises(ValueError):
            self.inbox.reject(candidate.id, reason="  ")
        rejected = self.inbox.reject(candidate.id, reason="duplicate")
        self.assertEqual(rejected.status, "rejected")
        with self.assertRaises(ValueError):
            self.inbox.approve(candidate.id, reason="too late")

    def test_force_approve_records_override(self):
        candidate = self._submit_skill()
        approved = self.inbox.approve(candidate.id, reason="trusted author", force=True)
        self.assertIn("OVERRIDE", approved.decision_reason)
        self.assertEqual(self.library.read("summarise-csv").skill.status, "promoted")

    def test_manual_candidate_approvable_by_human(self):
        candidate = self.inbox.submit(Candidate(
            kind="tip", payload=TIP_PAYLOAD, name="Retry with backoff",
            source_run_id="run-1", verification={"type": "manual"},
        ))
        approved = self.inbox.approve(candidate.id, reason="reviewed", by="kan")
        self.assertEqual(approved.status, "approved")
        tips = self.memory.retrieve_tips("retry the api call with backoff")
        self.assertEqual(len(tips), 1)
        self.assertEqual(tips[0].title, "Retry with backoff")

    def test_workflow_promotes_as_skill(self):
        candidate = self.inbox.submit(Candidate(
            kind="workflow", payload="## Workflow\n\n1. Do the first thing.\n2. Do the second.",
            name="summarise-csv", source_run_id="run-1",
            verification={"type": "manual"},
        ))
        self.inbox.approve(candidate.id, reason="reviewed")
        record = self.library.read("workflow-summarise-csv")
        self.assertEqual(record.skill.status, "promoted")
        self.assertIn("workflow", record.skill.tags)

    def test_verify_unknown_candidate(self):
        with self.assertRaises(FileNotFoundError):
            self.inbox.verify("nope")

    def test_set_skill_status_prune_logs(self):
        candidate = self._submit_skill()
        self.inbox.verify(candidate.id)
        self.inbox.approve(candidate.id, reason="ok")
        self.inbox.set_skill_status("summarise-csv", "pruned", reason="superseded")
        self.assertEqual(self.library.read("summarise-csv").skill.status, "pruned")
        self.assertEqual(self.library.retrieve("summarise the csv file"), [])
        log = self.memory.pruning_log()
        self.assertTrue(any(e.item_id == "summarise-csv" for e in log))


if __name__ == "__main__":
    unittest.main()
