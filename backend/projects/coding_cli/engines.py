"""Engines PockPock Code can hand a request to, besides its own coding loop.

- ``pockpock``: PockPock Agent through the app's gateway. With a planner model it is Plan in steps (a checked
  step plan, each step verified in code); without one, one model plans and works.
- ``openclaw``: the OpenClaw agent through the gateway (real shell, browser and apps, skills, MCP).
- ``auto``: picks per request (:func:`choose_engine`).

The gateway is the app's own (``http://127.0.0.1:8766``, or ``POCKPOCK_BACKEND_URL``), so these engines need
PockPock running. Their output uses the same terminal UI as the coding loop: one line per tool call,
approvals asked in the terminal and sent back to the gateway.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import urllib.error
import urllib.request
import uuid
from dataclasses import dataclass, field
from typing import Iterator

DEFAULT_GATEWAY = os.environ.get("POCKPOCK_BACKEND_URL", "http://127.0.0.1:8766").rstrip("/")
ENGINES = ("code", "pockpock", "openclaw", "auto")

# The CLI's three modes in each engine's own permission words.
POCKPOCK_PERMISSION = {"suggest": "auto-review", "auto-edit": "auto-review", "full-auto": "full-access"}
OPENCLAW_PERMISSION = {"suggest": "ask", "auto-edit": "auto", "full-auto": "full"}


class GatewayError(RuntimeError):
    pass


def _request(base: str, path: str, body: dict | None = None, timeout: float = 900):
    data = json.dumps(body).encode() if body is not None else None
    return urllib.request.Request(base + path, data=data, headers={"Content-Type": "application/json"}, method="POST" if body is not None else "GET")


def gateway_json(base: str, path: str, body: dict | None = None, timeout: float = 900) -> dict:
    try:
        with urllib.request.urlopen(_request(base, path, body), timeout=timeout) as response:
            return json.loads(response.read().decode() or "{}")
    except urllib.error.HTTPError as err:
        detail = err.read().decode(errors="replace")
        try:
            detail = json.loads(detail).get("detail", detail)
        except ValueError:
            pass
        raise GatewayError(f"{path}: {detail}"[:800]) from err
    except (urllib.error.URLError, OSError) as err:
        raise GatewayError(f"PockPock is not running at {base}. Open the PockPock app (or start its services), or use --engine code. ({err})") from err


def gateway_stream(base: str, path: str, body: dict) -> Iterator[dict]:
    try:
        response = urllib.request.urlopen(_request(base, path, body), timeout=3600)
    except urllib.error.HTTPError as err:
        detail = err.read().decode(errors="replace")
        try:
            detail = json.loads(detail).get("detail", detail)
        except ValueError:
            pass
        raise GatewayError(f"{path}: {detail}"[:800]) from err
    except (urllib.error.URLError, OSError) as err:
        raise GatewayError(f"PockPock is not running at {base}. ({err})") from err
    with response:
        buffer = ""
        while True:
            chunk = response.read1(65536) if hasattr(response, "read1") else response.read(65536)
            if not chunk:
                break
            buffer += chunk.decode("utf-8", errors="replace")
            while "\n\n" in buffer:
                frame, buffer = buffer.split("\n\n", 1)
                data = "\n".join(line[5:].lstrip() for line in frame.splitlines() if line.startswith("data:"))
                if data:
                    try:
                        yield json.loads(data)
                    except ValueError:
                        continue


def gateway_running(base: str = DEFAULT_GATEWAY) -> bool:
    try:
        return bool(gateway_json(base, "/api/health", timeout=3).get("ok"))
    except GatewayError:
        return False


# ---------------- choosing an engine ----------------

_OPENCLAW_WORDS = re.compile(
    r"\b(browser|browse|web ?site\s+(?:at|on)|open (?:the )?(?:app|website|page|url)|click|screenshot|screen|desktop app(?:lication)? (?:on|in) my|"
    r"my (?:email|inbox|calendar|downloads|desktop)|send (?:an? )?(?:email|message)|telegram|slack|discord|install (?:the )?app|"
    r"log ?in|sign ?in|fill (?:in|out)|download (?:the|a) |search the web|look up online|on the internet)\b|https?://", re.I)
_PROJECT_WORDS = re.compile(
    r"\b(build|create|make|design|generate|write)\b.{0,60}\b(website|web ?site|landing page|web app|app|game|resume|cv|cover letter|invoice|report|"
    r"presentation|slides|deck|spreadsheet|excel|word document|pdf|document|business plan|blog post|portfolio)\b", re.I | re.S)
_CODE_WORDS = re.compile(r"\b(fix|bug|test|tests|refactor|explain|why does|how does|where is|function|class|module|error|traceback|stack trace|compile|lint|type ?check|review|rename|add (?:a )?(?:flag|option|endpoint|parameter))\b|\.(py|ts|tsx|js|jsx|go|rs|java|kt|dart|cs|cpp|c|rb|php)\b", re.I)


def choose_engine(request: str, *, project_has_code: bool, gateway_up: bool) -> tuple[str, str]:
    """(engine, reason). Coding stays in the lean local loop; real-world actions go to OpenClaw; new
    multi-part deliverables go to Plan in steps, whose steps are checked in code."""
    if not gateway_up:
        return "code", "PockPock is not running, so the built-in coding agent handles it"
    if _OPENCLAW_WORDS.search(request):
        return "openclaw", "it needs the browser, apps or accounts on this PC"
    if _CODE_WORDS.search(request) and project_has_code:
        return "code", "it is a coding task in this project"
    if _PROJECT_WORDS.search(request):
        return "pockpock", "it is a multi-part deliverable, built step by step with checks"
    return "code", "the built-in coding agent is fastest for this"


# ---------------- PockPock Agent ----------------

@dataclass
class PockPockEngine:
    root: str
    model: str
    mode: str = "auto-edit"
    planner: str | None = None
    base: str = DEFAULT_GATEWAY
    auto_approve_plan: bool = False
    last_status: str = ""

    def run(self, request: str, ui) -> str:
        permission = POCKPOCK_PERMISSION.get(self.mode, "auto-review")
        if self.planner:
            return self._sequence(request, ui, permission)
        return self._one_model(request, ui, permission)

    def _approve_plan(self, ui, steps: list[str], details: list[list[str]] | None = None) -> bool:
        ui._print("Plan:", "bold")
        for index, step in enumerate(steps, 1):
            ui._print(f"  {index}. {step}")
            for line in (details[index - 1] if details and index - 1 < len(details) else [])[:4]:
                ui._print(f"     · {line}", "dim")
        if self.auto_approve_plan:
            return True
        try:
            answer = input("  Run this plan? [y] yes  [n] no › ").strip().lower()
        except EOFError:
            return False
        return answer in ("", "y", "yes")

    def _sequence(self, request: str, ui, permission: str) -> str:
        ui.notice(f"PockPock Agent · Plan in steps ({self.planner} plans, {self.model} works)")
        prepared = gateway_json(self.base, "/api/agents/plan-sequence", {
            "task": request, "source_task": request, "permission_mode": permission,
            "preferred_model": self.model, "planner_model": self.planner, "workspace_path": self.root})
        steps = prepared["sequence_plan"]["steps"]
        checks = prepared.get("step_checks") or []
        if not self._approve_plan(ui, [s.get("goal", "") for s in steps], [[f"tools: {', '.join(s.get('tools_allowed') or [])}"] + ([f"checked by: {checks[i]}"] if i < len(checks) else []) for i, s in enumerate(steps)]):
            gateway_json(self.base, f"/api/agents/plans/{prepared['plan_id']}/decision", {"action_hash": prepared["plan_hash"], "decision": "rejected", "plan": [s.get("goal") for s in steps], "success_checks": checks or ["done"]})
            return "Plan declined; nothing was changed."
        decision = gateway_json(self.base, f"/api/agents/plans/{prepared['plan_id']}/decision", {"action_hash": prepared["plan_hash"], "decision": "approved", "plan": [s.get("goal") for s in steps], "success_checks": checks or ["done"]})
        run_id = uuid.uuid4().hex
        return self._follow(gateway_stream(self.base, "/api/agents/run-sequence", {"plan_id": prepared["plan_id"], "plan_hash": decision.get("approved_plan_hash"), "run_id": run_id}), ui, run_id)

    def _one_model(self, request: str, ui, permission: str) -> str:
        ui.notice(f"PockPock Agent · {self.model} plans and works")
        prepared = gateway_json(self.base, "/api/agents/plan", {"task": request, "source_task": request, "permission_mode": permission, "preferred_model": self.model, "workspace_path": self.root})
        brief = prepared.get("task_brief") or {}
        if brief.get("requires_clarification") and brief.get("clarifying_questions"):
            questions = "\n".join(f"- {q}" for q in brief["clarifying_questions"])
            return f"PockPock Agent has questions before planning:\n{questions}\nAnswer them in your next request."
        checks = list(brief.get("success_checks") or [])
        plan = prepared["plan"]
        if not self._approve_plan(ui, plan, prepared.get("step_details")):
            gateway_json(self.base, f"/api/agents/plans/{prepared['plan_id']}/decision", {"action_hash": prepared["plan_hash"], "decision": "rejected", "plan": plan, "success_checks": checks or ["done"]})
            return "Plan declined; nothing was changed."
        decision = gateway_json(self.base, f"/api/agents/plans/{prepared['plan_id']}/decision", {"action_hash": prepared["plan_hash"], "decision": "approved", "plan": plan, "success_checks": checks})
        if not decision.get("accepted"):
            raise GatewayError(f"The plan was not accepted: {decision}")
        execution = f"{prepared['execution_prompt']}\n\nApproved plan:\n" + "\n".join(f"{i}. {s}" for i, s in enumerate(plan, 1)) + "\n\nApproved success checks:\n" + "\n".join(f"- {c}" for c in checks)
        history = [
            {"version": 1, "status": "proposed", "plan": plan, "success_checks": checks, "rationale": "", "plan_hash": prepared.get("plan_version_hash")},
            {"version": 2, "status": "approved", "plan": plan, "success_checks": checks, "rationale": "User approved the plan in PockPock Code.", "plan_hash": decision.get("approved_version_hash")},
        ]
        run_id = uuid.uuid4().hex
        body = {"task": execution, "source_task": request, "preferred_model": prepared["selected_model"], "files": [], "conversation_id": "pockpock-code",
                "run_id": run_id, "permission_mode": permission, "workspace_path": self.root, "plan": plan, "success_checks": checks, "task_brief": brief,
                "plan_history": history, "plan_id": prepared["plan_id"], "plan_hash": decision.get("approved_plan_hash"), "delegation_plan": prepared.get("delegation_plan")}
        return self._follow(gateway_stream(self.base, "/api/agents/run", body), ui, run_id)

    def _follow(self, events: Iterator[dict], ui, run_id: str) -> str:
        """Show a run's events in the terminal and answer its approvals."""
        answer, final, inputs = "", "", {}
        for event in events:
            kind = event.get("type")
            if kind == "token":
                answer += str(event.get("content") or "")
                ui.text(str(event.get("content") or ""))
            elif kind == "replace":
                answer = str(event.get("content") or "")
            elif kind == "tool_start":
                ui.end_text()
                inputs[event.get("call_id")] = event.get("input") or {}
                ui.tool_start(str(event.get("tool")), _gateway_arguments(event.get("input") or {}))
            elif kind == "tool_result":
                ok = event.get("status") == "success"
                error = event.get("error")
                message = (error.get("message") if isinstance(error, dict) else str(error or "")) if not ok else str(event.get("message") or "done")
                ui.tool_result(str(event.get("tool")), inputs.get(event.get("call_id"), {}), message, ok)
            elif kind == "plan_step":
                ui.end_text()
                ui._print(f"▸ Step {event.get('step')} of {event.get('total')}: {event.get('label') or ''}", "bold")
            elif kind == "sequence_check":
                ui._print(("  ✓ " if event.get("passed") else "  ✗ ") + str(event.get("message") or "")[:300], "green" if event.get("passed") else "red")
            elif kind == "sequence_retry":
                ui.notice("  " + str(event.get("message") or "trying again")[:240])
            elif kind == "error" and event.get("status") == "partial":
                ui.error("  " + str(event.get("message") or "A step could not be finished.")[:500])
            elif kind == "artifact":
                ui._print(f"  ⇣ {event.get('name')}  {event.get('path', '')}", "magenta")
            elif kind == "approval_requested":
                ui.end_text()
                action = event.get("action") or {}
                detail = str(action.get("diff") or action.get("content") or "")
                choice = ui.approve("edit" if action.get("path") else "command", str(action.get("path") or event.get("message") or "this action"), detail)
                gateway_json(self.base, f"/api/runs/{run_id}/approvals/{event.get('approval_id')}", {
                    "action_hash": event.get("action_hash"), "decision": "rejected" if choice == "no" else "approved", "scope": "task" if choice == "always" else "once"})
            elif kind == "error":
                ui.end_text()
                raise GatewayError(str(event.get("message") or "The run failed."))
            elif kind == "done":
                result = event.get("result") or {}
                self.last_status = str(result.get("status") or "done")
                final = answer.strip() or _sequence_summary(result)
        ui.end_text()
        return final or answer.strip()


def _gateway_arguments(arguments: dict) -> dict:
    """Gateway tool inputs use filename/url/query; the UI shows path/command/pattern."""
    shown = dict(arguments)
    for key, target in (("filename", "path"), ("url", "command"), ("query", "pattern")):
        if key in shown and target not in shown:
            shown[target] = shown[key]
    return shown


def _sequence_summary(result: dict) -> str:
    steps = result.get("steps") or []
    passed = sum(1 for s in steps if s.get("status") in ("done", "completed", "passed") or s.get("verified"))
    status = result.get("status") or "done"
    return f"Plan in steps {status}: {passed} of {len(steps)} steps passed their checks." if steps else f"Plan in steps {status}."


# ---------------- OpenClaw ----------------

@dataclass
class OpenClawEngine:
    root: str
    model: str | None = None
    mode: str = "auto-edit"
    base: str = DEFAULT_GATEWAY
    session: str = field(default="")

    def __post_init__(self) -> None:
        # One OpenClaw session per folder: the same session keeps its long prompt prefix cached in Ollama.
        if not self.session:
            self.session = "pockpock-code-" + hashlib.sha256(self.root.lower().encode()).hexdigest()[:12]

    def run(self, request: str, ui) -> str:
        ui.notice("OpenClaw" + (f" · {self.model}" if self.model else ""))
        model = self.model if not self.model or "/" in self.model else f"ollama/{self.model}"
        body = {"session_id": self.session, "message": request, "permission_mode": OPENCLAW_PERMISSION.get(self.mode, "auto"), "workspace_path": self.root}
        if model:
            body["model"] = model
        answer, tools = "", {}
        for event in gateway_stream(self.base, "/api/openclaw/chat", body):
            kind = event.get("type")
            if kind == "token":
                answer += str(event.get("content") or "")
                ui.text(str(event.get("content") or ""))
            elif kind == "replace":
                answer = str(event.get("content") or "")
            elif kind == "tool":
                ui.end_text()
                if event.get("phase") == "start":
                    tools[event.get("id")] = str(event.get("title") or event.get("name") or "tool")
                    ui._print(f"● {tools[event.get('id')][:140]}", "cyan")
                elif event.get("status") not in ("completed", None):
                    ui._print(f"  ✗ {str(event.get('error') or event.get('status'))[:300]}", "red")
            elif kind == "tool_detail":
                if event.get("command"):
                    ui._print(f"  $ {str(event.get('command'))[:200]}", "dim")
                if event.get("diff"):
                    ui.tool_result("edit_file", {}, "Edited.\n" + str(event["diff"]), True)
                elif event.get("output") and not ui.quiet:
                    ui._tail(str(event["output"])[-1500:])
            elif kind == "approval":
                ui.end_text()
                choice = ui.approve("command", str(event.get("title") or event.get("tool_name") or "OpenClaw action"), str(event.get("description") or ""))
                gateway_json(self.base, "/api/openclaw/approvals", {"approval_id": event.get("id"), "decision": {"yes": "allow-once", "always": "allow-task"}.get(choice, "deny")})
            elif kind == "error":
                ui.end_text()
                raise GatewayError(str(event.get("message") or "OpenClaw failed."))
        ui.end_text()
        return answer.strip()
