"""Eval harness for Plan-and-Sequence (P1 gate).

Measures the design targets from the Plan-and-Sequence wiki page on
PockPock's own task sample — prompt tokens per step, capsule size, step
success rate, and end-to-end task success — against the monolithic path.

* ``REFERENCE_TASKS`` — 6 hand-written reference plans (labelled as such:
  they are planner-shaped input written for this eval, NOT model output).
  Task (a) is the spec's Canva-invoices worked example, adapted because
  the tools it names (``gmail_search``, ``read_message``, ``calculator``,
  ``write_file``) do not exist in the registered tool catalog — the
  invoices arrive as an attached file instead. Tasks (b)-(f) are drawn
  from ``tool_retrieval_real_cases.md`` (scenarios-1000 #233, #327, #477,
  #376, #239): each decomposes into file read/write + simple computation
  with the real registered tools.
* Measurement A (deterministic, no model): per-step prompt tokens via
  ``build_step_prompt`` with the real ``ToolRetriever`` specs and the
  capsule as it stands at each step boundary, plus capsule tokens.
* Measurement B (fake model, real tools): ``SequenceRunner`` over each
  reference plan with a scripted fake chat client (one scripted tool
  call per step, ``think=False`` asserted) and the REAL tool execution
  path (``execute_agent_tool`` / ``execute_project_tool``) against a
  temp workspace. Records step success rate, verifier pass/fail per
  step, retries, and total prompt tokens.
* Measurement C (live, bounded, best-effort): ONE sequenced run against
  the real local Ollama model ``qwen3.5:2b`` on a tiny 5-step file task
  in a temp dir, hard-capped at 120 s overall. Skipped (recorded as
  "not measured") when Ollama or the model is unavailable. Never pulls
  a model, never restarts any service, never loads the 9B/35B models.

The monolithic baseline is the spec's own figure: PockPock's measured
~21K-token OpenClaw system prompt, plus the full 15-tool schema tokens
measured here (1,909 tokens at eval time). Whether the 21K already
includes tool schemas is not established — both figures are reported.

Usage (from the repo root, using the backend venv):

    .venv/bin/python backend/scripts/evaluate_plan_sequence.py [--no-live] [--json]
    .venv/bin/python backend/scripts/evaluate_plan_sequence.py --self-check

Exit code is 0 when the harness itself succeeds (all reference plans
valid, every Measurement B run completes, capsule cap holds) and the
report is written; 1 on harness failure (bad reference plan, verifier
error, a fake-model run that does not complete). A live run that fails
steps, or live resources being unavailable, is a measurement — it is
recorded, not an exit-code failure.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import tempfile
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))
sys.path.insert(0, str(ROOT / "backend" / "projects"))

from projects.agent_tools import (  # noqa: E402
    AgentToolContext,
    ProjectAgentContext,
    execute_agent_tool,
    execute_project_tool,
)
from projects.agent_tools.registry import registered_tool_specs  # noqa: E402
from projects.agent_tools.tool_retriever import ToolRetriever, estimate_tokens  # noqa: E402
from projects.plan_sequence import (  # noqa: E402
    MAX_CAPSULE_TOKENS,
    StateCapsule,
    build_capsule,
    validate_sequence_plan,
)
from projects.plan_sequence.runner import SequenceRunner, build_step_prompt  # noqa: E402

# ---------------------------------------------------------------------------
# Monolithic baseline (spec, PockPock's own measurement — not re-measured)
# ---------------------------------------------------------------------------

#: ~21K-token OpenClaw system prompt, measured in PockPock's own
#: smaller-model validation (Nov 2026); see the Plan-and-Sequence page.
MONOLITHIC_SYSTEM_PROMPT_TOKENS = 21_000

#: Design targets from the spec (targets, not measurements, until P1).
STEP_PROMPT_TOKEN_TARGET = 1_500

#: Live run: model, overall wall-clock cap, per-call HTTP timeout.
LIVE_MODEL = "qwen3.5:2b"
LIVE_OVERALL_TIMEOUT_SECONDS = 120
LIVE_CALL_TIMEOUT_SECONDS = 110
OLLAMA_BASE_URL = "http://127.0.0.1:11434"

#: Tools dispatched through the project-tool path (everything else goes
#: through the agent-tool path).
PROJECT_TOOLS = frozenset({
    "list_project_files",
    "search_project",
    "read_project_file",
    "propose_project_edit",
    "propose_project_patch",
    "validate_project",
})

REPORT_PATH = Path(__file__).resolve().parent / "plan_sequence_eval.md"


def _step(step_id, goal, tools, done, inputs=("task",)):
    return {
        "id": step_id,
        "goal": goal,
        "tools_allowed": list(tools),
        "budget_tokens": 4000,
        "budget_seconds": 300,
        "done_condition": done,
        "inputs": list(inputs),
    }


def _file_contains(path, pattern):
    return {"type": "file_contains", "path": path, "pattern": pattern}


def _file_exists(path):
    return {"type": "file_exists", "path": path}


def _no_error():
    return {"type": "no_error"}


def _plan(task, steps):
    return {
        "contract_version": 1,
        "task": task,
        # Hand-written reference plans, not model output.
        "planner_model": "hand-written reference plan (eval fixture, not model output)",
        "executor_model": "qwen3.5:2b",
        "steps": steps,
    }


# ---------------------------------------------------------------------------
# Reference tasks: hand-written plans + scripted fake-model tool calls.
# ---------------------------------------------------------------------------
# Each task: id, title, source, task text, files seeded into the temp
# workspace, attachments (for read_selected_file), the reference plan, and
# the scripted tool call per step (flat, in step order) used by the fake
# chat client in Measurement B.

REFERENCE_TASKS: list[dict] = [
    {
        "id": "canva-invoices",
        "title": "Canva invoices summary (spec worked example, adapted)",
        "source": "Plan-and-Sequence wiki, worked example. Adapted: the spec's "
        "gmail_search / read_message / calculator / write_file tools are not "
        "in the registered tool catalog (15 tools), so the invoices arrive "
        "as an attached file and the addition is done by the executor.",
        "task": "Summarise my Canva invoices and save the totals.",
        "seed_files": {
            "invoices.txt": (
                "Canva invoice 2026-11-01: Pro subscription, $19.19.\n"
                "Canva invoice 2026-10-12: Pro subscription, $19.19.\n"
            ),
        },
        "attachments": {
            "invoices.txt": (
                "Canva invoice 2026-11-01: Pro subscription, $19.19.\n"
                "Canva invoice 2026-10-12: Pro subscription, $19.19.\n"
            ),
        },
        "plan": _plan(
            "Summarise my Canva invoices and save the totals.",
            [
                _step("list-files", "List the files in the workspace.",
                      ["list_project_files"], _no_error()),
                _step("read-invoices", "Read the attached invoices file.",
                      ["read_selected_file"], _no_error(), ("list-files",)),
                _step("extract-amounts", "Write the extracted (date, amount) pairs to amounts.md.",
                      ["save_text_artifact"], _file_contains("amounts.md", "19.19"), ("read-invoices",)),
                _step("write-summary", "Write summary.md with the invoice count and the total.",
                      ["save_text_artifact"], _file_contains("summary.md", "38.38"), ("extract-amounts",)),
                _step("verify-summary", "Read summary.md back and confirm it holds the total.",
                      ["read_project_file"], _file_contains("summary.md", "38.38"), ("write-summary",)),
            ],
        ),
        "script": [
            {"name": "list_project_files", "arguments": {}},
            {"name": "read_selected_file", "arguments": {"name": "invoices.txt"}},
            {"name": "save_text_artifact", "arguments": {
                "filename": "amounts.md",
                "content": "# Extracted amounts\n\n- 2026-11-01: $19.19\n- 2026-10-12: $19.19\n"}},
            {"name": "save_text_artifact", "arguments": {
                "filename": "summary.md",
                "content": "# Canva invoices summary\n\nInvoices: 2\nTotal: $38.38\n"}},
            {"name": "read_project_file", "arguments": {"path": "summary.md"}},
        ],
    },
    {
        "id": "expenses-csv",
        "title": "Expenses CSV + totals (real case scenarios-1000#233)",
        "source": "tool_retrieval_real_cases.md, scenarios-1000#233: 'Save a CSV file "
        "called expenses.csv with these rows: Jan, Groceries, 520; Jan, Rent, "
        "1500; Feb, Groceries, 480; Feb, Rent, 1500.'",
        "task": "Save expenses.csv with the given rows and a summary with the grand total.",
        "seed_files": {
            "expenses.txt": (
                "Jan, Groceries, 520\nJan, Rent, 1500\n"
                "Feb, Groceries, 480\nFeb, Rent, 1500\n"
            ),
        },
        "attachments": {},
        "plan": _plan(
            "Save expenses.csv with the given rows and a summary with the grand total.",
            [
                _step("list-files", "List the files in the workspace.",
                      ["list_project_files"], _no_error()),
                _step("read-expenses", "Read the expenses list.",
                      ["read_project_file"], _no_error(), ("list-files",)),
                _step("write-csv", "Write expenses.csv with the four rows.",
                      ["save_text_artifact"], _file_contains("expenses.csv", "Feb,Rent,1500"), ("read-expenses",)),
                _step("write-summary", "Write expenses-summary.md with the grand total.",
                      ["save_text_artifact"], _file_contains("expenses-summary.md", "4000"), ("write-csv",)),
                _step("verify-summary", "Read expenses-summary.md back and confirm it holds the total.",
                      ["read_project_file"], _file_contains("expenses-summary.md", "4000"), ("write-summary",)),
            ],
        ),
        "script": [
            {"name": "list_project_files", "arguments": {}},
            {"name": "read_project_file", "arguments": {"path": "expenses.txt"}},
            {"name": "save_text_artifact", "arguments": {
                "filename": "expenses.csv",
                "content": "month,category,amount\nJan,Groceries,520\nJan,Rent,1500\nFeb,Groceries,480\nFeb,Rent,1500\n"}},
            {"name": "save_text_artifact", "arguments": {
                "filename": "expenses-summary.md",
                "content": "# Expenses summary\n\nTotal: 4000\n"}},
            {"name": "read_project_file", "arguments": {"path": "expenses-summary.md"}},
        ],
    },
    {
        "id": "report-summary",
        "title": "Summarise report.txt (real case scenarios-1000#327)",
        "source": "tool_retrieval_real_cases.md, scenarios-1000#327: 'Summarise the "
        "attached file report.txt and save the summary as report-summary.md.'",
        "task": "Summarise report.txt and save the summary as report-summary.md.",
        "seed_files": {
            "report.txt": (
                "Weekly report: the beta launch is on Dec 1. Login failures affect "
                "5% of users after the October update. The fix is session token "
                "handling, due Nov 20.\n"
            ),
        },
        "attachments": {},
        "plan": _plan(
            "Summarise report.txt and save the summary as report-summary.md.",
            [
                _step("list-files", "List the files in the workspace.",
                      ["list_project_files"], _no_error()),
                _step("read-report", "Read report.txt.",
                      ["read_project_file"], _no_error(), ("list-files",)),
                _step("write-summary", "Write report-summary.md with the launch date, failure rate, and fix.",
                      ["save_text_artifact"], _file_contains("report-summary.md", "Dec 1"), ("read-report",)),
                _step("write-doc", "Write the same summary as a Word document report-summary.docx.",
                      ["create_office_document"], _file_exists("report-summary.docx"), ("write-summary",)),
                _step("verify-summary", "Read report-summary.md back and confirm it holds the launch date.",
                      ["read_project_file"], _file_contains("report-summary.md", "Dec 1"), ("write-summary",)),
            ],
        ),
        "script": [
            {"name": "list_project_files", "arguments": {}},
            {"name": "read_project_file", "arguments": {"path": "report.txt"}},
            {"name": "save_text_artifact", "arguments": {
                "filename": "report-summary.md",
                "content": "# Report summary\n\n- Beta launch: Dec 1\n- Login failures: 5% of users\n- Fix: session token handling, due Nov 20\n"}},
            {"name": "create_office_document", "arguments": {
                "filename": "report-summary.docx", "kind": "word", "title": "Report summary",
                "content": "Beta launch: Dec 1. Login failures: 5% of users. Fix: session token handling, due Nov 20."}},
            {"name": "read_project_file", "arguments": {"path": "report-summary.md"}},
        ],
    },
    {
        "id": "data-scores",
        "title": "Average score + top scorer (real case scenarios-1000#477)",
        "source": "tool_retrieval_real_cases.md, scenarios-1000#477: 'Using the "
        "attached data.csv, calculate the average score and list the top scorer.' "
        "The file is attached (read_selected_file): read_project_file cannot "
        "read .csv — it is not in the project agent's supported extensions.",
        "task": "From data.csv, calculate the average score and list the top scorer.",
        "seed_files": {
            "data.csv": "name,score\nAna,88\nBen,95\nCleo,76\n",
        },
        "attachments": {
            "data.csv": "name,score\nAna,88\nBen,95\nCleo,76\n",
        },
        "plan": _plan(
            "From data.csv, calculate the average score and list the top scorer.",
            [
                _step("list-files", "List the files in the workspace.",
                      ["list_project_files"], _no_error()),
                _step("read-data", "Read the attached data.csv.",
                      ["read_selected_file"], _no_error(), ("list-files",)),
                _step("write-summary", "Write scores-summary.md with the average score and top scorer.",
                      ["save_text_artifact"], _file_contains("scores-summary.md", "Ben (95)"), ("read-data",)),
                _step("write-sheet", "Write the same rows as a spreadsheet scores.xlsx.",
                      ["create_office_document"], _file_exists("scores.xlsx"), ("write-summary",)),
                _step("verify-summary", "Read scores-summary.md back and confirm it holds the average.",
                      ["read_project_file"], _file_contains("scores-summary.md", "86.33"), ("write-summary",)),
            ],
        ),
        "script": [
            {"name": "list_project_files", "arguments": {}},
            {"name": "read_selected_file", "arguments": {"name": "data.csv"}},
            {"name": "save_text_artifact", "arguments": {
                "filename": "scores-summary.md",
                "content": "# Scores\n\nAverage score: 86.33\nTop scorer: Ben (95)\n"}},
            {"name": "create_office_document", "arguments": {
                "filename": "scores.xlsx", "kind": "spreadsheet", "title": "Scores",
                "content": "name,score\nAna,88\nBen,95\nCleo,76\n"}},
            {"name": "read_project_file", "arguments": {"path": "scores-summary.md"}},
        ],
    },
    {
        "id": "policy-diff",
        "title": "Compare two policy drafts (real case scenarios-1000#376)",
        "source": "tool_retrieval_real_cases.md, scenarios-1000#376: 'Compare these "
        "two attached policy drafts, policy-old.txt and policy-new.txt, list the "
        "substantive changes with section references, and save the comparison "
        "as policy-diff.md. Do not overwrite either original.'",
        "task": "Compare policy-old.txt and policy-new.txt and save the changes as policy-diff.md.",
        "seed_files": {
            "policy-old.txt": (
                "Section 1: Refunds within 14 days.\n"
                "Section 2: Support hours are 9am-5pm weekdays.\n"
                "Section 3: Data is kept for 30 days.\n"
            ),
            "policy-new.txt": (
                "Section 1: Refunds within 30 days.\n"
                "Section 2: Support hours are 8am-8pm every day.\n"
                "Section 3: Data is kept for 30 days.\n"
            ),
        },
        "attachments": {},
        "plan": _plan(
            "Compare policy-old.txt and policy-new.txt and save the changes as policy-diff.md.",
            [
                _step("list-files", "List the files in the workspace.",
                      ["list_project_files"], _no_error()),
                _step("read-old", "Read policy-old.txt.",
                      ["read_project_file"], _no_error(), ("list-files",)),
                _step("read-new", "Read policy-new.txt.",
                      ["read_project_file"], _no_error(), ("read-old",)),
                _step("write-diff", "Write policy-diff.md listing the substantive changes by section.",
                      ["save_text_artifact"], _file_contains("policy-diff.md", "Section 2"), ("read-old", "read-new")),
                _step("verify-diff", "Read policy-diff.md back and confirm it covers Section 2.",
                      ["read_project_file"], _file_contains("policy-diff.md", "Section 2"), ("write-diff",)),
            ],
        ),
        "script": [
            {"name": "list_project_files", "arguments": {}},
            {"name": "read_project_file", "arguments": {"path": "policy-old.txt"}},
            {"name": "read_project_file", "arguments": {"path": "policy-new.txt"}},
            {"name": "save_text_artifact", "arguments": {
                "filename": "policy-diff.md",
                "content": "# Policy changes\n\n- Section 1: refunds 14 days -> 30 days.\n"
                "- Section 2: support 9am-5pm weekdays -> 8am-8pm every day.\n"
                "- Section 3: unchanged.\n"}},
            {"name": "read_project_file", "arguments": {"path": "policy-diff.md"}},
        ],
    },
    {
        "id": "invoices-sheet",
        "title": "Invoices spreadsheet (real case scenarios-1000#239)",
        "source": "tool_retrieval_real_cases.md, scenarios-1000#239: 'Read these two "
        "invoices and create a spreadsheet called invoices.xlsx with vendor, "
        "invoice number, date, subtotal, tax, and total, one row per invoice.'",
        "task": "Read the two invoices and create invoices.xlsx with one row per invoice.",
        "seed_files": {
            "invoices.txt": (
                "Invoice A: Acme Supplies, #1042, Nov 1, subtotal 200, tax 16, total 216.\n"
                "Invoice B: Beta Office, #88, Nov 3, subtotal 150, tax 12, total 162.\n"
            ),
        },
        "attachments": {},
        "plan": _plan(
            "Read the two invoices and create invoices.xlsx with one row per invoice.",
            [
                _step("list-files", "List the files in the workspace.",
                      ["list_project_files"], _no_error()),
                _step("read-invoices", "Read invoices.txt.",
                      ["read_project_file"], _no_error(), ("list-files",)),
                _step("write-notes", "Write invoices-notes.md with one line per invoice and the combined total.",
                      ["save_text_artifact"], _file_contains("invoices-notes.md", "378"), ("read-invoices",)),
                _step("write-sheet", "Write invoices.xlsx with vendor, invoice, date, subtotal, tax, and total.",
                      ["create_office_document"], _file_exists("invoices.xlsx"), ("write-notes",)),
                _step("verify-notes", "Read invoices-notes.md back and confirm it holds the combined total.",
                      ["read_project_file"], _file_contains("invoices-notes.md", "378"), ("write-notes",)),
            ],
        ),
        "script": [
            {"name": "list_project_files", "arguments": {}},
            {"name": "read_project_file", "arguments": {"path": "invoices.txt"}},
            {"name": "save_text_artifact", "arguments": {
                "filename": "invoices-notes.md",
                "content": "# Invoices\n\n- Acme Supplies #1042: total 216\n- Beta Office #88: total 162\nCombined total: 378\n"}},
            {"name": "create_office_document", "arguments": {
                "filename": "invoices.xlsx", "kind": "spreadsheet", "title": "Invoices",
                "content": "vendor,invoice,date,subtotal,tax,total\nAcme Supplies,1042,Nov 1,200,16,216\nBeta Office,88,Nov 3,150,12,162\n"}},
            {"name": "read_project_file", "arguments": {"path": "invoices-notes.md"}},
        ],
    },
]


# ---------------------------------------------------------------------------
# Real-tool adapter: the repo's dispatchers return bare result dicts, while
# SequenceRunner expects {"ok", "output", "exit_code", "error"}. This adapter
# is the translation — no such adapter exists in the repo yet (the runner
# has no in-repo wiring to real tools), which the report records.
# ---------------------------------------------------------------------------

class RealToolAdapter:
    """Dispatch to the real agent/project tools; translate to runner shape."""

    def __init__(self, workspace: Path, attachments: dict[str, str]):
        self.agent_context = AgentToolContext(
            "a" * 32, set(), dict(attachments), workspace
        )
        self.project_context = ProjectAgentContext("a" * 32, project_root=workspace)
        self.calls: list[tuple[str, dict]] = []

    async def __call__(self, name: str, arguments: dict) -> dict:
        self.calls.append((name, dict(arguments)))
        if name in PROJECT_TOOLS:
            result = await execute_project_tool(name, arguments, self.project_context)
        else:
            result = await execute_agent_tool(name, arguments, self.agent_context)
        # execute_* raise AgentToolError on failure; success has no "ok" key.
        return {
            "ok": True,
            "output": json.dumps(result, default=str),
            "exit_code": None,
            "error": None,
        }


def _seed_workspace(task_def: dict, workspace: Path) -> None:
    for name, content in task_def["seed_files"].items():
        (workspace / name).write_text(content, encoding="utf-8")


def _fake_chat_factory(script: list[dict]):
    """Scripted fake chat client: one scripted tool call per step, in order."""
    calls: list[dict] = []
    queue = list(script)

    async def chat(model, messages, tools, *, think):
        calls.append({"model": model, "think": think, "tool_count": len(tools)})
        if not queue:
            return {"content": "done", "tool_calls": []}
        call = queue.pop(0)
        return {"content": "scripted step", "tool_calls": [dict(call)]}

    chat.calls = calls  # type: ignore[attr-defined]
    return chat


def validate_reference_plans() -> list[str]:
    """Validate every reference plan; returns error strings (empty = ok)."""
    errors = []
    for task_def in REFERENCE_TASKS:
        try:
            validate_sequence_plan(task_def["plan"])
        except ValueError as exc:
            errors.append(f"{task_def['id']}: {exc}")
        if len(task_def["script"]) != len(task_def["plan"]["steps"]):
            errors.append(
                f"{task_def['id']}: script has {len(task_def['script'])} calls for "
                f"{len(task_def['plan']['steps'])} steps"
            )
        for step, call in zip(task_def["plan"]["steps"], task_def["script"]):
            if call["name"] not in step["tools_allowed"]:
                errors.append(
                    f"{task_def['id']} step {step['id']}: scripted tool "
                    f"{call['name']} is not in tools_allowed {step['tools_allowed']}"
                )
    return errors


def full_schema_tokens() -> int:
    """Measured tokens of all 15 registered tool schemas (the monolithic set)."""
    return sum(estimate_tokens(json.dumps(spec)) for spec in registered_tool_specs())


def monolithic_baseline_tokens() -> dict:
    """Monolithic per-call baseline: 21K system prompt + full schemas.

    The 21K figure is the spec's cited PockPock measurement; whether it
    already includes tool schemas is not established, so both the
    prompt-only and prompt+schemas totals are reported.
    """
    schemas = full_schema_tokens()
    return {
        "system_prompt_tokens": MONOLITHIC_SYSTEM_PROMPT_TOKENS,
        "full_schema_tokens": schemas,
        "total_with_schemas": MONOLITHIC_SYSTEM_PROMPT_TOKENS + schemas,
    }


# ---------------------------------------------------------------------------
# Measurement A — deterministic prompt/capsule tokens, no model.
# ---------------------------------------------------------------------------

def measure_prompt_tokens(task_def: dict) -> dict:
    """Per-step prompt + capsule tokens for one reference plan.

    Walks the plan in order with the real ToolRetriever specs and the
    capsule as it stands at each step boundary. The scripted calls are
    executed once through the real adapter in a scratch workspace so the
    capsule entries (and their token cost) are the real ones, including
    the JSON-wrapped tool outputs the runner actually sees.
    """
    validated = validate_sequence_plan(task_def["plan"])
    steps = validated["steps"]
    with tempfile.TemporaryDirectory(prefix="ps-eval-a-") as tmp:
        workspace = Path(tmp)
        _seed_workspace(task_def, workspace)
        adapter = RealToolAdapter(workspace, task_def["attachments"])
        runner = SequenceRunner(chat=None, execute_tool=adapter, retriever=ToolRetriever())
        capsule = StateCapsule()
        rows = []
        for step, call in zip(steps, task_def["script"]):
            capsule_text = runner._capsule_text_for_step(step, capsule)
            specs = runner._tool_specs_for_step(step)
            prompt = build_step_prompt(
                task=validated["task"], step=step,
                capsule_text=capsule_text, tool_specs=specs,
            )
            prompt_tokens = estimate_tokens(prompt)
            rows.append({
                "step_id": step["id"],
                "tools": list(step["tools_allowed"]),
                "specs_sent": [s["function"]["name"] for s in specs],
                "prompt_tokens": prompt_tokens,
                "capsule_tokens": estimate_tokens(capsule_text),
                "over_target": prompt_tokens > STEP_PROMPT_TOKEN_TARGET,
            })
            # Execute the scripted call for real so the next step's capsule
            # carries the real entries.
            result = asyncio.run(adapter(call["name"], call["arguments"]))
            step_result = {
                "tool_calls": [{
                    "tool": call["name"], "ok": result["ok"],
                    "output": result["output"], "exit_code": result.get("exit_code"),
                }],
                "values": {},
                "errors": [],
            }
            capsule = build_capsule(
                list(capsule.entries)
                + runner._capsule_entries_for_step(
                    step, step_result,
                    [{"tool": call["name"], "arguments": call["arguments"]}],
                )
            )
    total = sum(row["prompt_tokens"] for row in rows)
    max_capsule = max((row["capsule_tokens"] for row in rows), default=0)
    return {
        "task_id": task_def["id"],
        "rows": rows,
        "total_prompt_tokens": total,
        "max_step_prompt_tokens": max((row["prompt_tokens"] for row in rows), default=0),
        "max_capsule_tokens": max_capsule,
        "steps_over_target": sum(1 for row in rows if row["over_target"]),
        "final_capsule_tokens": rows[-1]["capsule_tokens"] if rows else 0,
    }


# ---------------------------------------------------------------------------
# Measurement B — fake model, real runner, real tools.
# ---------------------------------------------------------------------------

def run_fake(task_def: dict) -> dict:
    """Run one reference plan through SequenceRunner with a scripted fake chat."""
    validated = validate_sequence_plan(task_def["plan"])
    with tempfile.TemporaryDirectory(prefix="ps-eval-b-") as tmp:
        workspace = Path(tmp)
        _seed_workspace(task_def, workspace)
        adapter = RealToolAdapter(workspace, task_def["attachments"])
        chat = _fake_chat_factory(task_def["script"])
        runner = SequenceRunner(chat=chat, execute_tool=adapter, retriever=ToolRetriever())
        result = asyncio.run(runner.run(
            validated, workspace=workspace,
            run_id=f"eval-{task_def['id']}", executor_model="qwen3.5:2b",
        ))
    think_values = {call["think"] for call in chat.calls}
    steps = result["steps"]
    passed = sum(1 for item in steps if item["status"] == "passed")
    capsule = StateCapsule.model_validate(result["capsule"])
    return {
        "task_id": task_def["id"],
        "status": result["status"],
        "steps": [
            {
                "step_id": item["step_id"], "status": item["status"],
                "attempts": item["attempts"], "prompt_tokens": item["prompt_tokens"],
                "evidence": item.get("evidence", ""), "error": item.get("error"),
            }
            for item in steps
        ],
        "steps_passed": passed,
        "steps_total": len(steps),
        "step_success_rate": round(passed / len(steps), 3) if steps else 0.0,
        "retries_used": sum(item["attempts"] - 1 for item in steps),
        "total_prompt_tokens": result["total_prompt_tokens"],
        "final_capsule_tokens": capsule.estimated_tokens(),
        "capsule_dropped_pointers": capsule.dropped_pointers,
        "think_always_false": think_values == {False},
        "chat_calls": len(chat.calls),
        "tool_calls": [f"{name}({json.dumps(args, sort_keys=True)})" for name, args in adapter.calls],
        "failure": result.get("failure"),
    }


# ---------------------------------------------------------------------------
# Measurement C — one live run against local Ollama (best-effort).
# ---------------------------------------------------------------------------

def _ollama_get(path: str, timeout: float = 5.0) -> dict | None:
    try:
        with urllib.request.urlopen(
            f"{OLLAMA_BASE_URL}{path}", timeout=timeout
        ) as response:
            return json.loads(response.read().decode("utf-8"))
    except (urllib.error.URLError, OSError, ValueError, TimeoutError):
        return None


class OllamaChat:
    """Minimal Ollama /api/chat client with think=False, tools passed through.

    Async: the HTTP POST runs in a worker thread so the runner's per-step
    timeout and the overall live cap can cancel the await (the underlying
    HTTP call still finishes in its thread, bounded by its own timeout).
    """

    def __init__(self, model: str):
        self.model = model
        self.calls: list[dict] = []

    async def __call__(self, model, messages, tools, *, think):
        self.calls.append({"model": model, "think": think, "tool_count": len(tools)})
        payload = {
            "model": model,
            "messages": messages,
            "stream": False,
            "think": False,
            "tools": tools,
        }
        data = await asyncio.to_thread(self._post, payload)
        message = data.get("message", {})
        tool_calls = []
        for call in message.get("tool_calls") or []:
            function = call.get("function") or {}
            arguments = function.get("arguments") or {}
            if isinstance(arguments, str):
                try:
                    arguments = json.loads(arguments)
                except ValueError:
                    arguments = {}
            if isinstance(function.get("name"), str) and isinstance(arguments, dict):
                tool_calls.append({"name": function["name"], "arguments": arguments})
        return {"content": message.get("content", ""), "tool_calls": tool_calls}

    @staticmethod
    def _post(payload: dict) -> dict:
        body = json.dumps(payload).encode("utf-8")
        request = urllib.request.Request(
            f"{OLLAMA_BASE_URL}/api/chat", data=body,
            headers={"Content-Type": "application/json"}, method="POST",
        )
        with urllib.request.urlopen(request, timeout=LIVE_CALL_TIMEOUT_SECONDS) as response:
            return json.loads(response.read().decode("utf-8"))


async def run_live(task_def: dict) -> dict:
    """One live sequenced run with qwen3.5:2b; 'not measured' when unavailable.

    Never pulls a model, never restarts a service, never loads the 9B/35B
    models (they cannot run on this VM). The model named here is only the
    one already installed; if it is not installed, this is skipped.
    """
    tags = _ollama_get("/api/tags")
    if tags is None:
        return {"status": "not measured", "reason": "Ollama is not reachable at 127.0.0.1:11434"}
    installed = {item.get("name") for item in tags.get("models", []) if isinstance(item, dict)}
    if LIVE_MODEL not in installed:
        return {
            "status": "not measured",
            "reason": f"model {LIVE_MODEL} is not installed (installed: {sorted(installed)})",
        }
    ps = _ollama_get("/api/ps") or {}
    loaded = [item.get("name") for item in ps.get("models", []) if isinstance(item, dict)]
    validated = validate_sequence_plan(task_def["plan"])
    started = time.monotonic()
    try:
        with tempfile.TemporaryDirectory(prefix="ps-eval-live-") as tmp:
            workspace = Path(tmp)
            _seed_workspace(task_def, workspace)
            adapter = RealToolAdapter(workspace, task_def["attachments"])
            chat = OllamaChat(LIVE_MODEL)
            runner = SequenceRunner(chat=chat, execute_tool=adapter, retriever=ToolRetriever())
            result = await asyncio.wait_for(
                runner.run(
                    validated, workspace=workspace,
                    run_id=f"eval-live-{task_def['id']}",
                    executor_model=LIVE_MODEL,
                ),
                timeout=LIVE_OVERALL_TIMEOUT_SECONDS,
            )
    except asyncio.TimeoutError:
        return {
            "status": "not measured",
            "reason": f"live run exceeded the {LIVE_OVERALL_TIMEOUT_SECONDS}s overall budget",
            "model": LIVE_MODEL, "loaded_before_run": loaded,
            "wall_seconds": round(time.monotonic() - started, 1),
        }
    except Exception as exc:  # Live-model/network failure is a measurement, not a harness failure.
        return {
            "status": "not measured",
            "reason": f"live run errored: {exc}",
            "model": LIVE_MODEL, "loaded_before_run": loaded,
            "wall_seconds": round(time.monotonic() - started, 1),
        }
    steps = result["steps"]
    passed = sum(1 for item in steps if item["status"] == "passed")
    return {
        "status": result["status"],
        "model": LIVE_MODEL,
        "loaded_before_run": loaded,
        "task_id": task_def["id"],
        "steps": [
            {
                "step_id": item["step_id"], "status": item["status"],
                "attempts": item["attempts"], "prompt_tokens": item["prompt_tokens"],
                "error": item.get("error"),
            }
            for item in steps
        ],
        "steps_passed": passed,
        "steps_total": len(steps),
        "step_success_rate": round(passed / len(steps), 3) if steps else 0.0,
        "total_prompt_tokens": result["total_prompt_tokens"],
        "wall_seconds": round(time.monotonic() - started, 1),
        "chat_calls": len(chat.calls),
        "think_always_false": {call["think"] for call in chat.calls} == {False},
    }


# ---------------------------------------------------------------------------
# Report
# ---------------------------------------------------------------------------

def _verdict(confirmed: bool, label: str) -> str:
    return f"confirmed ({label})" if confirmed else f"NOT confirmed ({label})"


def build_report(baseline: dict, measure_a: list[dict], measure_b: list[dict], live: dict) -> str:
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    total_a = sum(item["total_prompt_tokens"] for item in measure_a)
    max_step = max(item["max_step_prompt_tokens"] for item in measure_a)
    max_capsule = max(item["max_capsule_tokens"] for item in measure_a)
    over = sum(item["steps_over_target"] for item in measure_a)
    b_passed = sum(item["steps_passed"] for item in measure_b)
    b_total = sum(item["steps_total"] for item in measure_b)
    b_completed = sum(1 for item in measure_b if item["status"] == "completed")
    lines = [
        "# Plan-and-Sequence P1 measurement report",
        "",
        f"Generated {now} by `backend/scripts/evaluate_plan_sequence.py`. "
        "Token counts use the repo's `estimate_tokens` (~4 chars per token), "
        "the same estimator the runner uses — they are estimates, not "
        "tokenizer counts.",
        "",
        "## Method",
        "",
        "- **Task sample:** 6 hand-written reference plans (NOT model output). "
        "Task (a) is the spec's Canva-invoices worked example, adapted: the "
        "spec's `gmail_search` / `read_message` / `calculator` / `write_file` "
        "tools do not exist in the registered catalog (15 tools), so the "
        "invoices arrive as an attached file and the addition is done by the "
        "executor. Tasks (b)–(f) come from `tool_retrieval_real_cases.md` "
        "(scenarios-1000 #233, #327, #477, #376, #239). Each plan has 5 steps, "
        "typed done-conditions, and 1 pinned tool per step.",
        "- **Measurement A (deterministic, no model):** per-step prompt tokens "
        "via `build_step_prompt` with the real `ToolRetriever` specs and the "
        "capsule at each step boundary; scripted calls executed once through "
        "the real tool adapter in a scratch workspace so capsule entries are real.",
        "- **Measurement B (fake model, real tools):** `SequenceRunner` over "
        "each plan with a scripted fake chat client (one scripted tool call "
        "per step, `think=False` asserted) and the real `execute_agent_tool` / "
        "`execute_project_tool` path against a temp workspace. This measures "
        "the harness (runner, verifier, capsule), NOT model ability — a real "
        "model would have to produce these calls itself.",
        "- **Measurement C (live, bounded):** one sequenced run against local "
        "Ollama `qwen3.5:2b`, 120 s overall cap. See below.",
        "- **Monolithic baseline:** the spec's own figure — PockPock's measured "
        f"~21K-token OpenClaw system prompt — plus the full 15-tool schemas "
        f"measured here ({baseline['full_schema_tokens']:,} tokens). Whether "
        "the 21K already includes tool schemas is not established, so both "
        f"{baseline['system_prompt_tokens']:,} (prompt only) and "
        f"{baseline['total_with_schemas']:,} (prompt + schemas) are reported.",
        "",
        "## Measurement A — prompt tokens per step (deterministic)",
        "",
        "| Task | Steps | Max step prompt | Total prompt | Max capsule | Steps > 1,500 |",
        "| --- | ---: | ---: | ---: | ---: | ---: |",
    ]
    for item in measure_a:
        lines.append(
            f"| {item['task_id']} | {len(item['rows'])} | {item['max_step_prompt_tokens']} | "
            f"{item['total_prompt_tokens']} | {item['max_capsule_tokens']} | {item['steps_over_target']} |"
        )
    lines += [
        "",
        "Per-step detail:",
        "",
    ]
    for item in measure_a:
        detail = ", ".join(
            f"{row['step_id']}={row['prompt_tokens']} (capsule {row['capsule_tokens']})"
            for row in item["rows"]
        )
        lines.append(f"- **{item['task_id']}**: {detail}")
    lines += [
        "",
        f"Across all 6 tasks: max step prompt **{max_step} tokens**, "
        f"max capsule **{max_capsule} tokens**, total sequenced prompt tokens "
        f"**{total_a}** over 30 steps (mean {round(total_a / 30)} per step). "
        f"Monolithic baseline per call: {baseline['system_prompt_tokens']:,} "
        f"(prompt only) / {baseline['total_with_schemas']:,} (prompt + schemas). "
        f"A sequenced step prompt is ~{max_step / baseline['total_with_schemas'] * 100:.1f}% "
        "of the monolithic per-call prompt at worst.",
        "",
        "## Measurement B — runner end-to-end (fake model, real tools)",
        "",
        "| Task | Status | Steps passed | Retries | Total prompt tokens | Final capsule |",
        "| --- | --- | ---: | ---: | ---: | ---: |",
    ]
    for item in measure_b:
        lines.append(
            f"| {item['task_id']} | {item['status']} | {item['steps_passed']}/{item['steps_total']} | "
            f"{item['retries_used']} | {item['total_prompt_tokens']} | {item['final_capsule_tokens']} |"
        )
    lines += [
        "",
    ]
    if measure_b:
        lines += [
            f"Step success rate: **{b_passed}/{b_total} "
            f"({b_passed / b_total * 100:.0f}%)** with the scripted fake model. "
            f"End-to-end task success: **{b_completed}/6 tasks completed**. "
            "Retries used: "
            f"{sum(item['retries_used'] for item in measure_b)}. "
            "`think=False` on every chat call: "
            f"{all(item['think_always_false'] for item in measure_b)}. "
            "No capsule dropped pointers: "
            f"{not any(item['capsule_dropped_pointers'] for item in measure_b)}.",
        ]
    else:
        lines += [
            "Measurement B was not run in this invocation (`--self-check` runs "
            "Measurement A only).",
        ]
    lines += [
        "",
        "## Measurement C — live run (Ollama qwen3.5:2b, bounded)",
        "",
    ]
    if live.get("status") == "not measured":
        lines += [
            f"**Not measured — {live.get('reason')}.**",
            "",
            "No model was pulled and no service was restarted.",
        ]
    else:
        lines += [
            f"Task `{live.get('task_id')}` with `{live.get('model')}`: "
            f"status **{live.get('status')}**, steps passed "
            f"{live.get('steps_passed')}/{live.get('steps_total')} "
            f"({live.get('step_success_rate', 0) * 100:.0f}%), wall-clock "
            f"{live.get('wall_seconds')} s, total prompt tokens "
            f"{live.get('total_prompt_tokens')}, chat calls {live.get('chat_calls')}, "
            f"think always False: {live.get('think_always_false')}. "
            f"Models loaded before the run: {live.get('loaded_before_run')}.",
            "",
        ]
        for step in live.get("steps", []):
            lines.append(
                f"- {step['step_id']}: {step['status']} "
                f"(attempts {step['attempts']}, prompt {step['prompt_tokens']} tokens)"
                + (f" — {step['error']}" if step.get("error") else "")
            )
        lines.append("")
    lines += [
        "## Verdicts on the P1 targets",
        "",
        f"- **~1,500 tokens per step: {_verdict(over == 0, f'max {max_step} tokens over 30 steps, 0 steps over target')}.**",
        f"- **Capsule ≤ 400 tokens: {_verdict(max_capsule <= MAX_CAPSULE_TOKENS, f'max {max_capsule} tokens at any step boundary' + (f'; final capsules ≤ {max(item['final_capsule_tokens'] for item in measure_b)} tokens' if measure_b else ''))}.**",
        f"- **Step success rate (sequenced, fake model): "
        + (f"{b_passed}/{b_total} passed. " if measure_b else "NOT RUN in this invocation. ")
        + "This measures the harness, not model ability — it says the runner, "
        "verifier, and capsule work when the executor makes the right calls.",
        "- **End-to-end task success vs the monolithic path: NOT MEASURED. "
        "There is no monolithic runner to run the same tasks through, and no "
        "live monolithic comparison was attempted. Prior PockPock validation "
        "(Nov 2026) found qwen3.5:2b OpenClaw turns never completed against "
        "the ~21K-token prompt; that is prior evidence, not a P1 measurement.",
        "- **Live executor behaviour (real qwen3.5:2b): "
        + ("measured in Measurement C above." if live.get("status") != "not measured"
           else "NOT MEASURED — see Measurement C.") + "**",
        "",
        "## Findings beyond the targets",
        "",
        "- **No in-repo adapter from the runner to the real tools.** "
        "`SequenceRunner` expects `execute_tool` to return "
        "`{\"ok\", \"output\", \"exit_code\", \"error\"}`, but "
        "`execute_agent_tool` / `execute_project_tool` return bare result "
        "dicts with no `ok`/`output` keys (a bare success would read as "
        "`ok=False` to the runner). This eval supplies the translation in "
        "`RealToolAdapter`; the repo needs a real one before the runner can "
        "run against live tools outside this harness.",
        "- **The spec's worked-example tools do not exist.** `gmail_search`, "
        "`read_message`, `calculator`, and `write_file` are not among the 15 "
        "registered tools, so the Canva task as written in the spec cannot "
        "validate as a sequence plan. The adapted version (attached invoices, "
        "executor-side addition) is what was measured.",
        "- **No gateway run-sequence endpoint exists.** The planner service "
        "has `POST /plan-sequence`; the gateway has no "
        "`/api/agents/plan-sequence` or `/api/agents/run-sequence` route, "
        "and `openclaw_bridge` does not send a subtask yet (subtask mode "
        "lives only in the Node helper). End-to-end sequenced runs through "
        "the product surface are therefore not yet possible.",
        "",
        "## Limits of this measurement",
        "",
        "- Token counts are `estimate_tokens` (~4 chars/token) estimates, not "
        "tokenizer counts; the same estimator is used on both sides of the "
        "comparison, so the ratio is more reliable than the absolute numbers.",
        "- Reference plans are hand-written, not planner output: plan quality "
        "(decomposition correctness) is not measured here.",
        "- Measurement B's fake model always makes the right call, so its "
        "100% step success rate must not be quoted as model performance.",
        "- The monolithic baseline's 21K figure is cited from the spec "
        "(PockPock's own Nov 2026 validation), not re-measured here.",
        "",
    ]
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> int:
    parser = argparse.ArgumentParser(description="Evaluate Plan-and-Sequence (P1 gate).")
    parser.add_argument("--no-live", action="store_true", help="Skip the live Ollama run (Measurement C).")
    parser.add_argument("--self-check", action="store_true",
                        help="Only validate reference plans and run Measurement A; no runner or live runs.")
    parser.add_argument("--json", action="store_true", help="Print machine-readable JSON summary.")
    parser.add_argument("--no-report", action="store_true", help="Do not write plan_sequence_eval.md.")
    args = parser.parse_args()

    errors = validate_reference_plans()
    if errors:
        for error in errors:
            print(f"INVALID REFERENCE PLAN: {error}", file=sys.stderr)
        return 1

    baseline = monolithic_baseline_tokens()
    measure_a = [measure_prompt_tokens(task_def) for task_def in REFERENCE_TASKS]
    over_target = sum(item["steps_over_target"] for item in measure_a)
    max_capsule = max(item["max_capsule_tokens"] for item in measure_a)
    harness_ok = True
    if max_capsule > MAX_CAPSULE_TOKENS:
        print(f"HARNESS FAILURE: capsule reached {max_capsule} tokens (> {MAX_CAPSULE_TOKENS})", file=sys.stderr)
        harness_ok = False

    measure_b: list[dict] = []
    live: dict = {"status": "not measured", "reason": "skipped (--self-check)"}
    if not args.self_check:
        for task_def in REFERENCE_TASKS:
            result = run_fake(task_def)
            measure_b.append(result)
            if result["status"] != "completed":
                print(
                    f"HARNESS FAILURE: fake-model run of {task_def['id']} ended "
                    f"{result['status']}: {result['failure']}",
                    file=sys.stderr,
                )
                harness_ok = False
        if args.no_live:
            live = {"status": "not measured", "reason": "skipped (--no-live)"}
        else:
            # One live run, on the simplest file task (expenses-csv).
            live = asyncio.run(run_live(REFERENCE_TASKS[1]))
    else:
        live = {"status": "not measured", "reason": "skipped (--self-check)"}

    summary = {
        "baseline": baseline,
        "step_prompt_token_target": STEP_PROMPT_TOKEN_TARGET,
        "measurement_a": measure_a,
        "measurement_b": measure_b,
        "live": live,
    }
    if not args.no_report:
        REPORT_PATH.write_text(
            build_report(baseline, measure_a, measure_b, live), encoding="utf-8"
        )

    if args.json:
        print(json.dumps(summary, indent=2))
    else:
        total_a = sum(item["total_prompt_tokens"] for item in measure_a)
        max_step = max(item["max_step_prompt_tokens"] for item in measure_a)
        print(f"Plan-and-Sequence P1 eval: {len(REFERENCE_TASKS)} tasks, 30 steps, "
              f"{len(registered_tool_specs())} registered tools")
        print(f"  Monolithic baseline/call: {baseline['system_prompt_tokens']:,} system prompt "
              f"+ {baseline['full_schema_tokens']:,} schemas = {baseline['total_with_schemas']:,}")
        print(f"  Measurement A: max step prompt {max_step} tokens (target {STEP_PROMPT_TOKEN_TARGET}), "
              f"{over_target} steps over target; max capsule {max_capsule} tokens "
              f"(cap {MAX_CAPSULE_TOKENS}); total {total_a} tokens over 30 steps")
        if measure_b:
            passed = sum(item["steps_passed"] for item in measure_b)
            total = sum(item["steps_total"] for item in measure_b)
            completed = sum(1 for item in measure_b if item["status"] == "completed")
            print(f"  Measurement B (fake model, real tools): step success {passed}/{total}, "
                  f"tasks completed {completed}/{len(measure_b)}, "
                  f"retries {sum(item['retries_used'] for item in measure_b)}")
            for item in measure_b:
                print(f"    {item['task_id']}: {item['status']} "
                      f"{item['steps_passed']}/{item['steps_total']} steps, "
                      f"{item['total_prompt_tokens']} prompt tokens, "
                      f"final capsule {item['final_capsule_tokens']} tokens")
        if live.get("status") == "not measured":
            print(f"  Measurement C (live {LIVE_MODEL}): NOT MEASURED — {live.get('reason')}")
        else:
            print(f"  Measurement C (live {LIVE_MODEL}): {live.get('status')}, "
                  f"{live.get('steps_passed')}/{live.get('steps_total')} steps, "
                  f"{live.get('wall_seconds')} s wall-clock")
        if not args.no_report:
            print(f"  Report: {REPORT_PATH}")
    return 0 if harness_ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
