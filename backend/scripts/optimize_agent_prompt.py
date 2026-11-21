"""Optimise the agent system prompt against the eval harness (GEPA-style).

Evaluates a small pool of prompt candidates (plus seeded mutations of
the best one) on a train slice of the suite, selects the best by pass@1
(then fewer steps, then fewer tokens), and scores the winner once on a
held-out slice. Every evaluation is appended to a JSONL log.

Usage (from the repo root, using the backend venv)::

    # Smoke-test the loop mechanics without any model call:
    .venv/bin/python backend/scripts/optimize_agent_prompt.py --dry-run

    # Real optimisation against a live local model (slow on CPU — the
    # default pool is 5 candidates + 4 mutations on a 12-task slice):
    .venv/bin/python backend/scripts/optimize_agent_prompt.py \\
        --model qwen3.5:2b --quantisation Q4_K_M --train-size 12

The winning prompt is printed and written to the output directory
(``best_prompt.txt``); it is never applied automatically — a human
reviews it and wires it into the executor. See
backend/projects/agent_eval/README.md.
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
    candidate_pool,
    load_suite,
    optimize,
)


def main() -> int:
    parser = argparse.ArgumentParser(description="Optimise the agent system prompt (GEPA-style).")
    parser.add_argument("--suite", default=str(ROOT / "backend" / "projects" / "agent_eval" / "suite.json"))
    parser.add_argument("--model", default="qwen3.5:2b")
    parser.add_argument("--quantisation", default="Q4_K_M")
    parser.add_argument("--ollama-url", default="http://127.0.0.1:11434")
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--train-size", type=int, default=12,
                        help="Tasks in the train slice; the rest are held out.")
    parser.add_argument("--mutations", type=int, default=4)
    parser.add_argument("--max-steps", type=int, default=8)
    parser.add_argument("--base-prompt-file", default=None,
                        help="Start from this prompt instead of the default.")
    parser.add_argument("--dry-run", action="store_true",
                        help="Score prompts heuristically; no model calls.")
    parser.add_argument("--out", default="",
                        help="Output directory for best_prompt.txt and optimizer_log.jsonl.")
    args = parser.parse_args()

    tasks = load_suite(args.suite)
    base_prompt = DEFAULT_SYSTEM_PROMPT
    if args.base_prompt_file:
        base_prompt = Path(args.base_prompt_file).read_text(encoding="utf-8").strip()
    config = RunConfig(
        model=args.model,
        quantisation=args.quantisation,
        seed=args.seed,
        attempts=1,
        executor="ollama",
        system_prompt=base_prompt,
    )
    from datetime import datetime, timezone
    out_dir = Path(args.out) if args.out else Path("agent_eval_runs") / ("optimizer-" + datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S"))
    out_dir.mkdir(parents=True, exist_ok=True)

    def _factory() -> OllamaExecutor:
        return OllamaExecutor(model=args.model, max_steps=args.max_steps, base_url=args.ollama_url)

    result = optimize(
        tasks,
        _factory,
        config,
        candidates=candidate_pool(base_prompt),
        train_size=args.train_size,
        mutations=args.mutations,
        seed=args.seed,
        dry_run=args.dry_run,
        log_path=out_dir / "optimizer_log.jsonl",
    )
    (out_dir / "best_prompt.txt").write_text(result.best.prompt, encoding="utf-8")
    (out_dir / "optimizer_result.json").write_text(
        json.dumps(result.to_dict(), indent=2), encoding="utf-8"
    )
    print(f"Prompt optimisation ({'DRY RUN — heuristic scores only' if args.dry_run else 'live'}): "
          f"{len(result.evaluations)} evaluations, {len(tasks)} tasks in suite")
    print(f"  Best on train: {result.best.name} pass@1={result.best.pass_at_1} "
          f"steps={result.best.mean_steps} tokens={result.best.mean_tokens}")
    if result.held_out is not None:
        print(f"  Held-out score of the winner: pass@1={result.held_out.pass_at_1} "
              f"steps={result.held_out.mean_steps} tokens={result.held_out.mean_tokens}")
    print(f"  Best prompt -> {out_dir / 'best_prompt.txt'}  (review before using)")
    print(f"  Log -> {out_dir / 'optimizer_log.jsonl'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
