"""Tests for the distiller (stub + model-draft parsing)."""

import json
import unittest

from projects.agent_skills.distiller import (
    OllamaDistiller,
    RunRecord,
    StubDistiller,
    _candidates_from_draft,
    _parse_model_draft,
)


def _record(**kwargs):
    defaults = dict(
        run_id="run-42",
        task="Summarise the attached CSV file",
        trajectory=[
            {"step": "Read the attached file 'data.csv'", "tool": "read_selected_file", "outcome": "ok"},
            {"step": "Count 120 rows and 4 columns", "tool": "save_text_artifact", "outcome": "ok"},
            {"step": "Write summary.md", "tool": "save_text_artifact", "outcome": "ok"},
        ],
        outcome="success",
    )
    defaults.update(kwargs)
    return RunRecord(**defaults)


class StubDistillerTests(unittest.TestCase):
    def setUp(self):
        self.distiller = StubDistiller()

    def test_success_run_yields_skill_workflow_and_tip(self):
        candidates = self.distiller.distill(_record())
        kinds = [c.kind for c in candidates]
        self.assertIn("skill", kinds)
        self.assertIn("workflow", kinds)
        self.assertIn("tip", kinds)
        skill = next(c for c in candidates if c.kind == "skill")
        self.assertIn("Summarise the attached CSV", skill.payload)
        self.assertIn("name:", skill.payload)

    def test_failed_steps_yield_failure_tips(self):
        record = _record(
            outcome="failure",
            trajectory=[
                {"step": "Call the API with no delay", "tool": "fetch_api",
                 "outcome": "error", "detail": "HTTP 429 rate limited"},
            ],
        )
        candidates = self.distiller.distill(record)
        self.assertFalse([c for c in candidates if c.kind == "skill"])
        tips = [json.loads(c.payload) for c in candidates if c.kind == "tip"]
        self.assertTrue(tips)
        self.assertTrue(all(t["kind"] == "failure" for t in tips))
        self.assertIn("429", tips[0]["content"])

    def test_verifier_verdict_overrides_outcome(self):
        # Run claims success but the verifier failed it: no skill.
        record = _record(verifier_verdict={"verdict": "fail", "note": "numbers wrong"})
        candidates = self.distiller.distill(record)
        self.assertFalse([c for c in candidates if c.kind == "skill"])

    def test_verifier_pass_promotes_partial_run(self):
        record = _record(outcome="partial", verifier_verdict={"verdict": "pass", "note": "ok"})
        kinds = [c.kind for c in self.distiller.distill(record)]
        self.assertIn("skill", kinds)

    def test_empty_trajectory_yields_no_skill(self):
        candidates = self.distiller.distill(_record(trajectory=[]))
        self.assertFalse([c for c in candidates if c.kind == "skill"])


class ModelDraftTests(unittest.TestCase):
    def test_parse_model_draft_with_surrounding_text(self):
        text = 'Here is the draft:\n{"skill": {"name": "x", "description": "d", "body": "b"}, "tips": []}\nDone.'
        draft = _parse_model_draft(text)
        self.assertEqual(draft["skill"]["name"], "x")

    def test_parse_model_draft_garbage_returns_none(self):
        self.assertIsNone(_parse_model_draft("no json here"))
        self.assertIsNone(_parse_model_draft("{not json"))

    def test_candidates_from_draft(self):
        draft = {
            "skill": {"name": "summarise-csv", "description": "Summarise CSVs", "body": "1. Read it."},
            "workflow": "1. Read it.\n2. Summarise it.",
            "tips": [{
                "title": "Check headers first", "description": "d", "content": "c",
                "kind": "success", "action": "check headers", "confidence": 0.9,
            }],
        }
        candidates = _candidates_from_draft(_record(), draft)
        self.assertEqual({c.kind for c in candidates}, {"skill", "workflow", "tip"})

    def test_candidates_from_invalid_draft_is_empty(self):
        # Invalid skill (empty body) and no tips -> empty, so the caller falls back to stub.
        candidates = _candidates_from_draft(_record(), {"skill": {"name": "x", "description": "d", "body": ""}})
        self.assertEqual(candidates, [])

    def test_ollama_distiller_falls_back_to_stub_when_offline(self):
        distiller = OllamaDistiller(base_url="http://127.0.0.1:9", timeout_s=2.0)
        candidates = distiller.distill(_record())
        kinds = [c.kind for c in candidates]
        self.assertIn("skill", kinds)


if __name__ == "__main__":
    unittest.main()
