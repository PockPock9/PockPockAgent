"""Standalone CLI for the agent verifier.

Usage (from backend/projects/agent_verifier, with the repo venv):
    python -m cli verify --run-id <32-hex> --workspace <dir> --spec <spec.json>
    python -m cli show --run-id <32-hex>
    python -m cli resume --run-id <32-hex>
    python -m cli rewind --run-id <32-hex> --step 1

The verifier is runnable standalone against any finished run: it reads the
run's stored requirements from the ledger and checks the workspace on disk.
Set POCKPOCK_AGENT_VERIFIER_DB to point at a ledger file (tests use a temp
file); otherwise the default PockPock data-dir ledger is used.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # backend/projects/
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from agent_verifier.harness import Harness  # noqa: E402
from agent_verifier.ledger import Ledger  # noqa: E402
from agent_verifier.verifiers import list_verifiers, run_verifiers  # noqa: E402


def _ledger() -> Ledger:
    return Ledger()


def cmd_verify(args: argparse.Namespace) -> int:
    ledger = _ledger()
    run = ledger.get_run(args.run_id)
    if run is None:
        print(f"Run not found: {args.run_id}", file=sys.stderr)
        return 1
    spec = json.loads(Path(args.spec).read_text(encoding="utf-8")) if args.spec else {"verifiers": []}
    workspace = Path(args.workspace).expanduser()
    verdict = run_verifiers(workspace, spec, run=run)
    for check in verdict.checks:
        ledger.record_verdict(
            args.run_id, verifier=check.name,
            verdict="pass" if check.status == "passed" else
                    "fail" if check.status == "failed" else
                    "error" if check.status == "error" else "skipped",
            evidence=[check.evidence],
            failed_check=check.name if check.status != "passed" else None,
        )
    print(json.dumps(verdict.to_dict(), indent=2))
    return 0 if verdict.verdict == "pass" else 1


def cmd_show(args: argparse.Namespace) -> int:
    ledger = _ledger()
    run = ledger.get_run(args.run_id)
    if run is None:
        print(f"Run not found: {args.run_id}", file=sys.stderr)
        return 1
    print(json.dumps({
        "run": run,
        "steps": ledger.get_steps(args.run_id),
        "verdicts": ledger.get_verdicts(args.run_id),
        "file_diffs": ledger.get_file_diffs(args.run_id),
        "events": ledger.get_events(args.run_id),
    }, indent=2))
    return 0


def cmd_resume(args: argparse.Namespace) -> int:
    try:
        snapshot = Harness(_ledger()).resume_snapshot(args.run_id)
    except ValueError as err:
        print(str(err), file=sys.stderr)
        return 1
    print(json.dumps(snapshot, indent=2))
    return 0


def cmd_rewind(args: argparse.Namespace) -> int:
    try:
        summary = Harness(_ledger()).rewind_run(args.run_id, args.step)
    except ValueError as err:
        print(str(err), file=sys.stderr)
        return 1
    print(json.dumps(summary, indent=2))
    return 0


def cmd_list_verifiers(args: argparse.Namespace) -> int:
    print("\n".join(list_verifiers()))
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="agent-verifier", description="External verifier + durable run ledger")
    sub = parser.add_subparsers(dest="command", required=True)
    verify = sub.add_parser("verify", help="Run external verifiers against a run's workspace")
    verify.add_argument("--run-id", required=True)
    verify.add_argument("--workspace", required=True)
    verify.add_argument("--spec", help="JSON file with {verifiers: [...], critic: {...}}")
    verify.set_defaults(func=cmd_verify)
    show = sub.add_parser("show", help="Print a run, its steps, verdicts, diffs, and events")
    show.add_argument("--run-id", required=True)
    show.set_defaults(func=cmd_show)
    resume = sub.add_parser("resume", help="Print the resume snapshot for a run")
    resume.add_argument("--run-id", required=True)
    resume.set_defaults(func=cmd_resume)
    rewind = sub.add_parser("rewind", help="Rewind a run to a step")
    rewind.add_argument("--run-id", required=True)
    rewind.add_argument("--step", type=int, required=True)
    rewind.set_defaults(func=cmd_rewind)
    sub.add_parser("list-verifiers", help="List registered verifiers").set_defaults(func=cmd_list_verifiers)
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
