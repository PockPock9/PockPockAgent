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
        responses = iter([
            {"approved": False, "findings": ["Add validation."]},
            {"plan": [], "success_checks": self.checks},
        ])

        async def generate_json(messages):
            return next(responses)

        with self.assertRaises(ValueError):
            asyncio.run(review_plan(
                task=self.task,
                task_brief=self.brief,
                plan=self.plan,
                success_checks=self.checks,
                generate_json=generate_json,
            ))


if __name__ == "__main__":
    unittest.main()
