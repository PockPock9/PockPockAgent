import asyncio
from pathlib import Path
import sys
import time
import unittest

from starlette.requests import Request

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))

import frog_ai_server as gateway


def local_request(path: str) -> Request:
    scope = {
        "type": "http", "method": "POST", "path": path,
        "headers": [(b"origin", b"http://127.0.0.1:5173")],
        "client": ("127.0.0.1", 40000), "server": ("127.0.0.1", 8766),
        "scheme": "http", "query_string": b"",
    }

    async def receive():
        return {"type": "http.request", "body": b"", "more_body": False}

    return Request(scope, receive=receive)


class PlanGateTests(unittest.TestCase):
    def test_critic_review_is_bound_to_plan_approval_hash(self):
        state = {
            "plan_id": "a" * 32,
            "plan": ["Create the app"],
            "success_checks": ["The files contain the requested features"],
            "critic_review": {"status": "revised", "findings": ["Add validation"]},
        }
        original_hash = gateway.agent_plan_hash(state)
        changed_review = {**state, "critic_review": {"status": "approved", "findings": []}}

        self.assertNotEqual(original_hash, gateway.agent_plan_hash(changed_review))

    def test_workspace_tool_gate_rejects_default_and_does_not_elevate_permission(self):
        with self.assertRaises(gateway.ToolContractError) as raised:
            gateway.require_agent_tool_permission("full-access", "default")
        self.assertEqual(raised.exception.error.code, "permission_required")

        gateway.require_agent_tool_permission("full-access", "auto-review")
        gateway.require_agent_tool_permission("full-access", "full-access")

    def test_plan_requires_matching_approval_before_run_and_rejects_mutated_plan(self):
        plan_id = "a" * 32
        state = {
            "plan_id": plan_id,
            "request": "Build a tiny app",
            "source_task": "Build a tiny app",
            "permission_mode": "auto-review",
            "workspace_path": None,
            "plan": ["Create the app"],
            "success_checks": ["The app opens"],
            "proposed_plan": ["Create the app"],
            "proposed_checks": ["The app opens"],
            "execution_prompt": "Complete the requested task with tools.",
            "selected_model": "local-tool-model",
            "task_brief": {"contract_version": 1},
            "reason": "Tool capable model",
            "status": "pending",
            "expires_at": time.monotonic() + 60,
        }
        state["task_brief"] = gateway.TaskBrief(
            original_request="Build a tiny app", desired_outcome="A tiny app", permission_level="auto-review",
            milestones=[{"id": "one", "title": "Create", "completion_check": "Open"}],
            success_checks=["The app opens"],
        ).model_dump(mode="json")
        state["action_hash"] = gateway.agent_plan_hash(state)
        gateway.AGENT_PLAN_TICKETS[plan_id] = state

        async def scenario():
            decision = await gateway.decide_agent_plan(
                plan_id,
                gateway.AgentPlanDecisionPayload(
                    action_hash=state["action_hash"], decision="approved",
                    plan=["Create the app"], success_checks=["The app opens"],
                ),
                local_request(f"/api/agents/plans/{plan_id}/decision"),
            )
            self.assertTrue(decision["accepted"])
            prompt = (
                "Complete the requested task with tools.\n\nApproved plan:\n1. Create the app"
                "\n\nApproved success checks:\n- The app opens"
            )
            altered = gateway.AgentTaskPayload(
                task=prompt, source_task="Build a tiny app", preferred_model="local-tool-model",
                permission_mode="auto-review", plan=["Create the app", "Send user data"],
                success_checks=["The app opens"], plan_id=plan_id, plan_hash=decision["approved_plan_hash"],
                task_brief=state["task_brief"],
                plan_history=[
                    {"version": 1, "status": "proposed", "plan": ["Create the app"], "success_checks": ["The app opens"], "plan_hash": gateway.agent_plan_version_hash(state, 1, ["Create the app"], ["The app opens"])},
                    {"version": 2, "status": "approved", "plan": ["Create the app"], "success_checks": ["The app opens"], "plan_hash": gateway.agent_plan_version_hash(state, 2, ["Create the app"], ["The app opens"])},
                ],
            )
            with self.assertRaises(gateway.HTTPException) as raised:
                await gateway.run_agent_task(altered, local_request("/api/agents/run"))
            self.assertEqual(raised.exception.status_code, 409)
            elevated = altered.model_copy(update={
                "permission_mode": "full-access",
                "plan": ["Create the app"],
            })
            with self.assertRaises(gateway.HTTPException) as raised:
                await gateway.run_agent_task(elevated, local_request("/api/agents/run"))
            self.assertEqual(raised.exception.status_code, 409)
            self.assertEqual(state["status"], "approved")

        try:
            asyncio.run(scenario())
        finally:
            gateway.AGENT_PLAN_TICKETS.pop(plan_id, None)


if __name__ == "__main__":
    unittest.main()
