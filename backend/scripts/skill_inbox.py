"""Review the skill inbox from the command line.

Usage:
    python backend/scripts/skill_inbox.py list [--status pending]
    python backend/scripts/skill_inbox.py show <candidate-id>
    python backend/scripts/skill_inbox.py verify <candidate-id>
    python backend/scripts/skill_inbox.py approve <candidate-id> --reason "..." [--force] [--by NAME]
    python backend/scripts/skill_inbox.py reject <candidate-id> --reason "..." [--by NAME]
    python backend/scripts/skill_inbox.py skills [--status promoted]
    python backend/scripts/skill_inbox.py maintain
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from projects.agent_skills.service import AgentSkillsService  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Review the skill inbox.")
    sub = parser.add_subparsers(dest="command", required=True)

    list_parser = sub.add_parser("list", help="List inbox candidates")
    list_parser.add_argument("--status", default="pending")

    show_parser = sub.add_parser("show", help="Show one candidate")
    show_parser.add_argument("candidate_id")

    verify_parser = sub.add_parser("verify", help="Run a candidate's verification test")
    verify_parser.add_argument("candidate_id")

    approve_parser = sub.add_parser("approve", help="Approve (promote) a candidate")
    approve_parser.add_argument("candidate_id")
    approve_parser.add_argument("--reason", default="")
    approve_parser.add_argument("--force", action="store_true",
                                help="Approve without a passed test (recorded override)")
    approve_parser.add_argument("--by", default="human")

    reject_parser = sub.add_parser("reject", help="Reject a candidate")
    reject_parser.add_argument("candidate_id")
    reject_parser.add_argument("--reason", required=True)
    reject_parser.add_argument("--by", default="human")

    skills_parser = sub.add_parser("skills", help="List library skills")
    skills_parser.add_argument("--status", default=None)

    sub.add_parser("maintain", help="Run contradiction detection + pruning")

    args = parser.parse_args(argv)
    service = AgentSkillsService()

    if args.command == "list":
        candidates = service.inbox.list(status=args.status)
        if not candidates:
            print(f"No {args.status} candidates.")
            return 0
        for candidate in candidates:
            verified = (candidate.verification_result or {}).get("passed")
            print(f"{candidate.id} [{candidate.kind}] {candidate.name} "
                  f"run={candidate.source_run_id} verified={verified} "
                  f"test={json.dumps(candidate.verification)}")
        return 0

    if args.command == "show":
        candidate = service.inbox.get(args.candidate_id)
        if candidate is None:
            print(f"No such candidate: {args.candidate_id}")
            return 1
        print(json.dumps(candidate.as_dict(), indent=2))
        print(candidate.payload)
        return 0

    if args.command == "verify":
        try:
            result = service.verify_candidate(args.candidate_id)
        except (FileNotFoundError, ValueError) as err:
            print(f"Cannot verify: {err}")
            return 1
        print(f"{'PASSED' if result.passed else 'FAILED'} ({result.method}): {result.detail}")
        return 0 if result.passed else 1

    if args.command == "approve":
        try:
            candidate = service.approve_candidate(
                args.candidate_id, reason=args.reason, by=args.by, force=args.force)
        except (FileNotFoundError, ValueError) as err:
            print(f"Cannot approve: {err}")
            return 1
        print(f"Approved {candidate.id} [{candidate.kind}] {candidate.name}: {candidate.decision_reason}")
        return 0

    if args.command == "reject":
        try:
            candidate = service.reject_candidate(
                args.candidate_id, reason=args.reason, by=args.by)
        except (FileNotFoundError, ValueError) as err:
            print(f"Cannot reject: {err}")
            return 1
        print(f"Rejected {candidate.id}: {candidate.decision_reason}")
        return 0

    if args.command == "skills":
        for record in service.library.list(status=args.status):
            print(f"{record.skill.name} [{record.skill.status}] v{record.skill.version}: "
                  f"{record.skill.description}")
        return 0

    if args.command == "maintain":
        report = service.run_maintenance()
        print(f"Contradictions invalidated: {len(report.contradictions)}")
        print(f"Tips pruned: {len(report.pruned_tips)}")
        print(f"Facts pruned: {len(report.pruned_facts)}")
        print(f"Skills pruned: {len(report.pruned_skills)}")
        for decision in (
            report.contradictions + report.pruned_tips
            + report.pruned_facts + report.pruned_skills
        ):
            print(f"  {decision.item_type} {decision.item_id}: {decision.decision} — {decision.reason}")
        return 0

    parser.error("unknown command")  # pragma: no cover
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
