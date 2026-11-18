"""Distil a completed run record into skill-inbox candidates.

Usage:
    python backend/scripts/distill_skill.py run.json [--model] [--show]

``run.json`` is a run record: {"run_id", "task", "trajectory": [...],
"outcome": "success"|"partial"|"failure", "verifier_verdict": {...}}.
Each trajectory step is {"step", "tool", "outcome", "detail"}.

By default the deterministic stub distiller runs (offline, no model).
``--model`` uses the small local Ollama model (think:false) with a stub
fallback. Candidates land in the inbox as ``pending`` — nothing is
retrievable until it passes the promotion gate.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from projects.agent_skills.distiller import RunRecord  # noqa: E402
from projects.agent_skills.service import AgentSkillsService  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run_json", help="Path to a run-record JSON file")
    parser.add_argument("--model", action="store_true",
                        help="Use the local Ollama model instead of the stub distiller")
    parser.add_argument("--show", action="store_true",
                        help="Print each candidate payload")
    args = parser.parse_args(argv)

    data = json.loads(Path(args.run_json).read_text(encoding="utf-8"))
    record = RunRecord(
        run_id=str(data.get("run_id", "unknown")),
        task=str(data.get("task", "")),
        trajectory=list(data.get("trajectory") or []),
        outcome=str(data.get("outcome", "success")),
        verifier_verdict=data.get("verifier_verdict"),
    )
    service = AgentSkillsService()
    candidates = service.distill_run(record, use_model=args.model)
    print(f"Distilled {len(candidates)} candidate(s) from run {record.run_id} into the inbox:")
    for candidate in candidates:
        print(f"  {candidate.id} [{candidate.kind}] {candidate.name} (pending)")
        if args.show:
            print(candidate.payload)
            print("  ---")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
