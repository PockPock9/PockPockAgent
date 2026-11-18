"""End-to-end lifecycle test for the service facade.

distil (stub) -> candidate in inbox -> verification -> promotion ->
retrieval returns it; an unverified candidate is NOT retrieved.
"""

import json
import tempfile
import unittest
from pathlib import Path

from projects.agent_skills.distiller import RunRecord
from projects.agent_skills.memory import Fact
from projects.agent_skills.service import AgentSkillsService


class LifecycleTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.service = AgentSkillsService(
            skills_dir=root / "skills", db_path=root / "m.sqlite3", dense_enabled=False
        )

    def tearDown(self):
        self.tmp.cleanup()

    def _record(self):
        return RunRecord(
            run_id="run-demo",
            task="Summarise the attached CSV file",
            trajectory=[
                {"step": "Read the attached file", "tool": "read_selected_file", "outcome": "ok"},
                {"step": "Count rows and columns", "tool": "save_text_artifact", "outcome": "ok"},
                {"step": "Write summary.md", "tool": "save_text_artifact", "outcome": "ok"},
            ],
            outcome="success",
            verifier_verdict={"verdict": "pass", "note": "numbers match"},
        )

    def test_full_lifecycle(self):
        task = "Summarise the attached CSV file"
        # 1. Nothing retrievable before distillation.
        self.assertEqual(self.service.retrieve_for_task(task)["skills"], [])
        # 2. Distil -> candidates land in the inbox, pending.
        candidates = self.service.distill_run(self._record())
        self.assertTrue(candidates)
        self.assertTrue(all(c.status == "pending" for c in candidates))
        # 3. Unverified candidates are NOT retrieved.
        self.assertEqual(self.service.retrieve_for_task(task)["skills"], [])
        self.assertEqual(self.service.retrieve_for_task(task)["tips"], [])
        # 4. Verify + approve each candidate (manual ones need no test run).
        for candidate in candidates:
            if (candidate.verification or {}).get("type") != "manual":
                self.service.verify_candidate(candidate.id)
            self.service.approve_candidate(candidate.id, reason="demo approval")
        # 5. Retrieval now returns the promoted skill (plus the workflow,
        # which is stored as a second skill) and the tip.
        retrieved = self.service.retrieve_for_task(task)
        names = [s["name"] for s in retrieved["skills"]]
        self.assertIn("summarise-the-attached-csv-file", names)
        self.assertIn("workflow-summarise-the-attached-csv-file", names)
        self.assertTrue(retrieved["tips"])
        # 6. The context block a live run would see contains the skill.
        block = self.service.context_block_for_task(task)
        self.assertIn("summarise-the-attached-csv-file", block)

    def test_rejected_candidate_never_retrievable(self):
        candidates = self.service.distill_run(self._record())
        for candidate in candidates:
            self.service.reject_candidate(candidate.id, reason="not useful")
        retrieved = self.service.retrieve_for_task("Summarise the attached CSV file")
        self.assertEqual(retrieved["skills"], [])
        self.assertEqual(retrieved["tips"], [])

    def test_fact_invalidation_through_service(self):
        self.service.memory.add_fact(
            Fact(subject="project", predicate="language", value="Python")
        )
        self.service.memory.add_fact(
            Fact(subject="project", predicate="language", value="Rust")
        )
        active = self.service.memory.get_facts("project")
        self.assertEqual([f.value for f in active], ["Rust"])

    def test_maintenance_through_service(self):
        self.service.distill_run(self._record())
        report = self.service.run_maintenance()
        self.assertEqual(report.total, 0)  # fresh items: nothing to prune


if __name__ == "__main__":
    unittest.main()
