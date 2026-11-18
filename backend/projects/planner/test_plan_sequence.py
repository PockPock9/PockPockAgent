"""Tests for POST /plan-sequence (Plan-and-Sequence P3).

The endpoint handler is called directly (as in test_plan_gate.py) with
``_request_model_json`` stubbed, so no model, network, or HTTP client is
needed. No FastAPI TestClient: the repo venv has no httpx.
"""

import asyncio
import unittest
from unittest import mock

import app
from fastapi import HTTPException

from projects.model_router import ModelProviderError


def _step(step_id, tools=("list_project_files",), done=None, inputs=()):
    return {
        "id": step_id,
        "goal": f"Do step {step_id}",
        "tools_allowed": list(tools),
        "done_condition": done or {"type": "no_error"},
        "inputs": list(inputs),
    }


def _valid_plan():
    return {
        "task": "Summarise my Canva invoices from Gmail and save the totals.",
        "steps": [
            _step("find-files", ["list_project_files"],
                  {"type": "file_exists", "path": "src/main.py"}),
            _step("read-code", ["read_project_file"],
                  {"type": "file_contains", "path": "src/main.py", "pattern": "def main"},
                  inputs=["find-files"]),
            _step("check-code", ["validate_project"],
                  {"type": "command_exit_0"}, inputs=["read-code"]),
            _step("write-summary", ["save_text_artifact"],
                  {"type": "file_exists", "path": "summary.md"}, inputs=["check-code"]),
            _step("verify", ["read_project_file"],
                  {"type": "value_equals", "field": "total", "expected": "42"},
                  inputs=["write-summary"]),
        ],
    }


def _payload(**overrides):
    fields = {
        "task": "Summarise my Canva invoices from Gmail and save the totals.",
        "capable_models": ["qwen3.6:35b-a3b", "qwen3.5:9b"],
        "model_profiles": [
            {"name": "qwen3.6:35b-a3b", "capabilities": ["tools"], "parameter_billions": 35.0},
            {"name": "qwen3.5:9b", "capabilities": ["tools"], "parameter_billions": 9.7},
        ],
        "default_model": "qwen3.5:9b",
    }
    fields.update(overrides)
    return app.SequencePlanRequest(**fields)


class PlanSequenceEndpointTests(unittest.TestCase):
    def test_valid_plan_returned_unchanged_with_selected_models(self):
        fake = mock.AsyncMock(return_value=_valid_plan())
        with mock.patch.object(app, "_request_model_json", fake):
            result = asyncio.run(app.plan_sequence(_payload()))
        self.assertEqual(result["contract_version"], 1)
        self.assertEqual(result["selected_model"], "qwen3.6:35b-a3b")
        self.assertEqual(result["executor_model"], "qwen3.5:9b")
        self.assertTrue(result["reason"])
        self.assertTrue(result["executor_reason"])
        plan = result["sequence_plan"]
        self.assertEqual(plan["task"], _payload().task)
        self.assertEqual(
            [step["id"] for step in plan["steps"]],
            ["find-files", "read-code", "check-code", "write-summary", "verify"],
        )
        self.assertEqual(plan["planner_model"], "qwen3.6:35b-a3b")
        self.assertEqual(plan["executor_model"], "qwen3.5:9b")
        self.assertEqual(fake.call_count, 1)

    def test_invalid_plan_fixed_on_retry(self):
        invalid = _valid_plan()
        invalid["steps"][0]["tools_allowed"] = ["does_not_exist"]
        fake = mock.AsyncMock(side_effect=[invalid, _valid_plan()])
        with mock.patch.object(app, "_request_model_json", fake):
            result = asyncio.run(app.plan_sequence(_payload()))
        self.assertEqual(fake.call_count, 2)
        self.assertEqual(result["sequence_plan"]["steps"][0]["tools_allowed"], ["list_project_files"])
        retry_messages = fake.call_args_list[1].args[1]
        self.assertIn("rejected by validation", retry_messages[0]["content"])
        self.assertIn("does_not_exist", retry_messages[0]["content"])

    def test_still_invalid_after_retry_returns_502(self):
        invalid = _valid_plan()
        invalid["steps"][0]["tools_allowed"] = ["does_not_exist"]
        fake = mock.AsyncMock(return_value=invalid)
        with mock.patch.object(app, "_request_model_json", fake):
            with self.assertRaises(HTTPException) as raised:
                asyncio.run(app.plan_sequence(_payload()))
        self.assertEqual(raised.exception.status_code, 502)
        self.assertIn("invalid sequence plan after one fix-up attempt", raised.exception.detail)
        self.assertIn("does_not_exist", raised.exception.detail)
        self.assertEqual(fake.call_count, 2)

    def test_timeout_surfaces_as_replan_trigger(self):
        fake = mock.AsyncMock(side_effect=asyncio.TimeoutError())
        with mock.patch.object(app, "_request_model_json", fake):
            with self.assertRaises(HTTPException) as raised:
                asyncio.run(app.plan_sequence(_payload()))
        self.assertEqual(raised.exception.status_code, 502)
        self.assertIn("re-plan trigger", raised.exception.detail)
        self.assertIn("not a fatal error", raised.exception.detail)

    def test_wrapped_timeout_error_surfaces_as_replan_trigger(self):
        async def failing(*args, **kwargs):
            raise HTTPException(status_code=502, detail="The planner model failed.") from ModelProviderError(
                "Local model request failed: Connection timeout to host http://127.0.0.1:11434"
            )

        with mock.patch.object(app, "_request_model_json", failing):
            with self.assertRaises(HTTPException) as raised:
                asyncio.run(app.plan_sequence(_payload()))
        self.assertEqual(raised.exception.status_code, 502)
        self.assertIn("re-plan trigger", raised.exception.detail)

    def test_non_timeout_provider_error_passes_through(self):
        async def failing(*args, **kwargs):
            raise HTTPException(status_code=502, detail="The planner model failed.")

        with mock.patch.object(app, "_request_model_json", failing):
            with self.assertRaises(HTTPException) as raised:
                asyncio.run(app.plan_sequence(_payload()))
        self.assertEqual(raised.exception.status_code, 502)
        self.assertEqual(raised.exception.detail, "The planner model failed.")

    def test_malformed_model_json_returns_502_without_fixup(self):
        fake = mock.AsyncMock(side_effect=ValueError("Planner model returned an invalid object"))
        with mock.patch.object(app, "_request_model_json", fake):
            with self.assertRaises(HTTPException) as raised:
                asyncio.run(app.plan_sequence(_payload()))
        self.assertEqual(raised.exception.status_code, 502)
        self.assertIn("unusable JSON", raised.exception.detail)
        self.assertEqual(fake.call_count, 1)

    def test_no_model_available_returns_503(self):
        payload = _payload(
            capable_models=["qwen3.5:9b"],
            model_profiles=[{"name": "qwen3.5:9b", "capabilities": ["completion"]}],
            default_model="missing-model",
        )
        fake = mock.AsyncMock(return_value=_valid_plan())
        with mock.patch.object(app, "_request_model_json", fake):
            with self.assertRaises(HTTPException) as raised:
                asyncio.run(app.plan_sequence(payload))
        self.assertEqual(raised.exception.status_code, 503)
        self.assertEqual(fake.call_count, 0)


class SequencePlanPromptTests(unittest.TestCase):
    def test_prompt_lists_known_tools_and_validation_rules(self):
        prompt = app.build_sequence_plan_prompt(
            "Do the thing",
            ["list_project_files", "read_project_file"],
            None,
            "auto-review",
        )
        self.assertIn("list_project_files", prompt)
        self.assertIn("read_project_file", prompt)
        self.assertIn("5-15 sequential steps", prompt)
        self.assertIn("file_contains needs path and pattern", prompt)
        self.assertIn("validated and rejected", prompt)
        self.assertIn("Do the thing", prompt)

    def test_fixup_prompt_carries_error_and_previous_plan(self):
        prompt = app.build_sequence_plan_fixup_prompt(
            "Step 'x' uses unknown tool(s): nope",
            {"task": "t", "steps": []},
            ["list_project_files"],
        )
        self.assertIn("unknown tool(s): nope", prompt)
        self.assertIn('"task": "t"', prompt)
        self.assertIn("list_project_files", prompt)


if __name__ == "__main__":
    unittest.main()
