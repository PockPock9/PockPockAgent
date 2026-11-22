import asyncio
import sys
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "projects"))

from planner.critic import CriticVerdict, review_plan


class PlanCriticTests(unittest.TestCase):
    def setUp(self):
        self.task = "Create a small local app"
        self.brief = {"required_capabilities": ["workspace_read", "workspace_write"]}
        self.plan = ["Inspect the workspace", "Create the app"]
        self.checks = ["The app source files contain the requested features"]

    def test_approved_plan_passes_through_without_revision(self):
        calls = []

        async def generate_json(messages):
            calls.append(messages)
            return {"approved": True, "findings": []}

        result = asyncio.run(review_plan(
            task=self.task,
            task_brief=self.brief,
            plan=self.plan,
            success_checks=self.checks,
            generate_json=generate_json,
        ))

        self.assertEqual(len(calls), 1)
        self.assertEqual(result["plan"], self.plan)
        self.assertEqual(result["success_checks"], self.checks)
        self.assertEqual(result["critic_review"]["status"], "approved")

    def test_rejected_plan_gets_one_bounded_revision(self):
        responses = iter([
            {"approved": False, "findings": ["Add an explicit validation step."]},
            {
                "plan": ["Inspect the workspace", "Create the app", "Validate the requested files"],
                "success_checks": ["The app source files contain the requested features"],
            },
        ])
        calls = []

        async def generate_json(messages):
            calls.append(messages)
            return next(responses)

        result = asyncio.run(review_plan(
            task=self.task,
            task_brief=self.brief,
            plan=self.plan,
            success_checks=self.checks,
            generate_json=generate_json,
        ))

        self.assertEqual(len(calls), 2)
        self.assertEqual(result["plan"][-1], "Validate the requested files")
        self.assertEqual(result["critic_review"]["revision_count"], 1)
        self.assertEqual(result["critic_review"]["findings"], ["Add an explicit validation step."])

    def test_rejected_verdict_without_findings_is_invalid(self):
        with self.assertRaises(ValueError):
            CriticVerdict.model_validate({"approved": False, "findings": []})

    def test_invalid_revision_is_not_returned_as_a_successful_plan(self):
        # An unusable revision is never used. It used to fail the whole request (a 502 with a valid
        # plan in hand); now the original plan is shown, marked unrevised, with the findings.
        for bad_revision in ({"plan": [], "success_checks": self.checks}, {"plan": ["x"] * 11, "success_checks": self.checks}, "not json"):
            responses = iter([{"approved": False, "findings": ["Add validation."]}, bad_revision])

            async def generate_json(messages):
                return next(responses)

            result = asyncio.run(review_plan(
                task=self.task,
                task_brief=self.brief,
                plan=self.plan,
                success_checks=self.checks,
                generate_json=generate_json,
            ))
            self.assertEqual(result["plan"], self.plan, bad_revision)
            self.assertEqual(result["success_checks"], self.checks)
            self.assertEqual(result["critic_review"]["status"], "unrevised")
            self.assertEqual(result["critic_review"]["findings"], ["Add validation."])

    def test_revision_steps_written_as_objects_are_accepted(self):
        responses = iter([
            {"approved": False, "findings": ["Add validation."]},
            {"plan": [{"step": "Inspect"}, {"action": "Validate"}], "success_checks": [{"check": "Files exist"}], "notes": "extra"},
        ])

        async def generate_json(messages):
            return next(responses)

        result = asyncio.run(review_plan(task=self.task, task_brief=self.brief, plan=self.plan, success_checks=self.checks, generate_json=generate_json))
        self.assertEqual(result["plan"], ["Inspect", "Validate"])
        self.assertEqual(result["success_checks"], ["Files exist"])
        self.assertEqual(result["critic_review"]["status"], "revised")


    def test_verdicts_as_small_models_write_them_are_read(self):
        # R&D validation 2026-11-21: a strict verdict schema failed the whole plan request (HTTP 502).
        from planner.critic import _lenient_verdict

        self.assertTrue(_lenient_verdict({"approved": "true", "reason": "fine"}).approved)
        verdict = _lenient_verdict({"approved": False, "findings": [{"issue": "Missing check"}, "x" * 500] + ["more"] * 10})
        self.assertFalse(verdict.approved)
        self.assertEqual(verdict.findings[0], "Missing check")
        self.assertLessEqual(len(verdict.findings[1]), 320)
        self.assertEqual(len(verdict.findings), 8)
        self.assertEqual(_lenient_verdict({"approved": False}).findings, ["The reviewer did not approve the plan but gave no reason."])
        self.assertIsNone(_lenient_verdict({"verdict": "ok"}))
        self.assertIsNone(_lenient_verdict("approved"))

    def test_an_unreadable_review_keeps_the_plan(self):
        async def generate_json(messages):
            return {"looks": "good"}

        result = asyncio.run(review_plan(task=self.task, task_brief=self.brief, plan=self.plan, success_checks=self.checks, generate_json=generate_json))
        self.assertEqual(result["plan"], self.plan)
        self.assertEqual(result["critic_review"]["status"], "unreviewed")


if __name__ == "__main__":
    unittest.main()
