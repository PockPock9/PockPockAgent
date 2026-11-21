"""Run the agent eval harness.

Runs the seeded task suite (default: ``backend/projects/agent_eval/suite.json``)
against the deterministic stub or a live local Ollama model, verifies every
attempt with deterministic checks, and writes ``report.json`` + ``report.md``
into the output directory. It also exports verified passing traces as SFT
JSONL (``traces.jsonl``) for later LoRA distillation of the small executor.

Usage (from the repo root, using the backend venv)::

    .venv/bin/python backend/scripts/run_agent_eval.py [--executor stub|ollama]
    .venv/bin/python backend/scripts/run_agent_eval.py --executor ollama \\
        --model qwen3.5:2b --quantisation Q4_K_M --k 3

Exit code is 0 when pass@1 >= --min-pass (default 0: the harness reports,
it does not gate, unless you ask it to). The live executor deliberately
bypasses the gateway planner — see backend/projects/agent_eval/README.md
for why, and what a number from each executor does and does not mean.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))
sys.path.insert(0, str(ROOT / "backend" / "projects"))

from projects.agent_eval import (  # noqa: E402
    DEFAULT_SYSTEM_PROMPT,
    OllamaExecutor,
    RunConfig,
    StubExecutor,
    export_traces_from_report,
    load_suite,
    run_suite,
)


def _read_system_prompt(path: str | None) -> str:
    if path is None:
        return DEFAULT_SYSTEM_PROMPT
    return Path(path).read_text(encoding="utf-8").strip()


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the agent eval harness.")
    parser.add_argument("--suite", default=str(ROOT / "backend" / "projects" / "agent_eval" / "suite.json"),
                        help="Task suite JSON/YAML file.")
    parser.add_argument("--executor", choices=["stub", "ollama"], default="stub",
                        help="stub = reference solutions through the real tools; "
                             "ollama = live local model loop.")
    parser.add_argument("--model", default="stub",
                        help="Model name recorded per run (e.g. qwen3.5:2b).")
    parser.add_argument("--quantisation", default="n/a",
                        help="Model quantisation recorded per run (e.g. Q4_K_M).")
    parser.add_argument("--ollama-url", default="http://127.0.0.1:11434")
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--k", type=int, default=1,
                        help="Attempts per task; pass@k needs k >= 3 (or 5).")
    parser.add_argument("--tasks", default="",
                        help="Comma-separated task ids to run (default: all).")
    parser.add_argument("--include-network", action="store_true",
                        help="Also run tasks tagged requires: [network].")
    parser.add_argument("--system-prompt-file", default=None,
                        help="Use this file's text as the system prompt (live executor).")
    parser.add_argument("--max-steps", type=int, default=8,
                        help="Max tool steps per live attempt.")
    parser.add_argument("--out", default="",
                        help="Output directory (default: agent_eval_runs/<timestamp> under cwd).")
    parser.add_argument("--min-pass", type=float, default=0.0,
                        help="Exit 1 when pass@1 is below this (default 0: report only).")
    parser.add_argument("--json", action="store_true", help="Print the JSON summary.")
    args = parser.parse_args()

    if args.k < 1:
        print("--k must be at least 1", file=sys.stderr)
        return 2
    tasks = load_suite(args.suite)
    if args.tasks.strip():
        wanted = {item.strip() for item in args.tasks.split(",") if item.strip()}
        tasks = [task for task in tasks if task.id in wanted]
        if not tasks:
            print(f"No tasks matched: {sorted(wanted)}", file=sys.stderr)
            return 2
    if args.executor == "ollama":
        executor = OllamaExecutor(model=args.model, max_steps=args.max_steps, base_url=args.ollama_url)
    else:
        executor = StubExecutor()
        if args.model == "stub":
            print("Note: stub executor — numbers prove the harness/tools/verifiers, not the model.")
    config = RunConfig(
        model=args.model,
        quantisation=args.quantisation,
        seed=args.seed,
        attempts=args.k,
        executor=args.executor,
        system_prompt=_read_system_prompt(args.system_prompt_file),
        include_network=args.include_network,
    )
    from datetime import datetime, timezone
    out_dir = Path(args.out) if args.out else Path("agent_eval_runs") / datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    report = run_suite(tasks, executor, config, suite_name=Path(args.suite).stem, out_dir=out_dir)
    traces = export_traces_from_report(report, out_dir / "traces.jsonl")
    summary = report.summary()
    if args.json:
        print(json.dumps({"summary": summary, "traces": traces, "out_dir": str(out_dir)}, indent=2))
    else:
        print(f"Agent eval: {summary['tasks_run']} tasks run, {summary['tasks_skipped']} skipped "
              f"({summary['tasks_total']} total) — executor {args.executor}, "
              f"model {args.model} ({args.quantisation}), seed {args.seed}")
        print(f"  pass@1: {summary['pass@1']:.3f}" if summary["pass@1"] is not None else "  pass@1: n/a")
        for k in (3, 5):
            if f"pass@{k}" in summary:
                print(f"  pass@{k}: {summary[f'pass@{k}']:.3f}")
        print(f"  Mean steps/task: {summary['mean_steps_per_task']}  "
              f"tokens/task: {summary['mean_tokens_per_task']}  "
              f"wall/task: {summary['mean_wall_seconds_per_task']}s")
        print(f"  Traces exported: {traces['exported']} of {traces['attempts']} attempts -> {out_dir / 'traces.jsonl'}")
        print(f"  Reports: {out_dir / 'report.json'} and {out_dir / 'report.md'}")
    if summary["pass@1"] is None or summary["pass@1"] < args.min_pass:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
