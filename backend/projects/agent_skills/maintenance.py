"""Maintenance: contradiction detection and pruning.

The literature's recurring failure mode is memory *pollution*: stale,
wrong, or overly specific memories actively hurt later tasks. So memory
is refined, not just accumulated:

* **Contradiction detection.** Two active tips contradict when they share
  a ``task_tag`` and the same ``action`` but opposite kinds — one says do
  it, the other says don't. A token-overlap fallback catches tips the
  distiller gave different action phrases to: same tag, title-token
  Jaccard >= 0.5, opposite kinds. The loser is the lower-confidence tip
  (ties: the older one); it is marked ``invalidated`` — never silently
  overwritten — and the decision is logged with its reason.
* **Pruning.** An active tip/fact/skill is pruned when it is disused
  (``use_count == 0`` and older than its TTL), expired (past
  ``expires_at``), or below the confidence floor. Pruned items stay in
  the database with status ``pruned`` so the decision is auditable; they
  are never retrieved.
* Every decision is written to the pruning log
  (:meth:`ReasoningMemory.pruning_log`).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Sequence

from ..agent_tools.tool_retriever import tokenize
from .memory import MIN_CONFIDENCE, PruningDecision, ReasoningMemory, ReasoningTip

#: Title-token Jaccard at or above which two same-tag, opposite-kind tips
#: count as contradictory even when their ``action`` phrases differ.
CONTRADICTION_JACCARD = 0.5


@dataclass
class MaintenanceReport:
    contradictions: list[PruningDecision] = field(default_factory=list)
    pruned_tips: list[PruningDecision] = field(default_factory=list)
    pruned_facts: list[PruningDecision] = field(default_factory=list)
    pruned_skills: list[PruningDecision] = field(default_factory=list)

    @property
    def total(self) -> int:
        return (
            len(self.contradictions)
            + len(self.pruned_tips)
            + len(self.pruned_facts)
            + len(self.pruned_skills)
        )


def _jaccard(left: Sequence[str], right: Sequence[str]) -> float:
    a, b = set(left), set(right)
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def _contradicts(a: ReasoningTip, b: ReasoningTip) -> bool:
    """True when two active tips give opposite advice about the same thing."""
    if a.id == b.id or a.kind == b.kind:
        return False
    if a.task_tag != b.task_tag:
        return False
    if a.action and a.action == b.action:
        return True
    return _jaccard(tokenize(a.title), tokenize(b.title)) >= CONTRADICTION_JACCARD


def _loser(a: ReasoningTip, b: ReasoningTip) -> ReasoningTip:
    if a.confidence != b.confidence:
        return a if a.confidence < b.confidence else b
    # Tie: the older tip loses (newer evidence wins).
    return a if (a.created_at or "") <= (b.created_at or "") else b


def detect_contradictions(memory: ReasoningMemory) -> list[PruningDecision]:
    """Find contradictory active tips, invalidate the loser of each pair, log it."""
    active = memory.list_tips(status="active")
    decisions: list[PruningDecision] = []
    invalidated: set[str] = set()
    for i, first in enumerate(active):
        if first.id in invalidated:
            continue
        for second in active[i + 1 :]:
            if second.id in invalidated:
                continue
            if not _contradicts(first, second):
                continue
            loser = _loser(first, second)
            winner = second if loser is first else first
            reason = (
                f"contradicts tip {winner.id} ({winner.title!r}): same task "
                f"({loser.task_tag}) and action ({loser.action or 'similar title'}), "
                f"opposite kind ({loser.kind} vs {winner.kind}); "
                f"loser confidence {loser.confidence} vs {winner.confidence}"
            )
            memory.set_tip_status(loser.id, "invalidated", reason=reason)
            decisions.append(PruningDecision(
                item_type="tip", item_id=loser.id,
                decision="invalidated", reason=reason,
            ))
            invalidated.add(loser.id)
    return decisions


def _expired(expires_at: str, now: str) -> bool:
    return bool(expires_at) and expires_at <= now


def prune_stale(memory: ReasoningMemory, *, now: str | None = None) -> MaintenanceReport:
    """Prune disused / expired / low-confidence tips and facts. Returns the report."""
    now = now or datetime.now(timezone.utc).isoformat()
    report = MaintenanceReport()
    for tip in memory.list_tips(status="active"):
        reason: str | None = None
        if tip.confidence < MIN_CONFIDENCE:
            reason = f"confidence {tip.confidence} below floor {MIN_CONFIDENCE}"
        elif _expired(tip.expires_at, now) and tip.use_count == 0:
            reason = f"expired {tip.expires_at} and never used"
        elif _expired(tip.expires_at, now):
            reason = f"expired {tip.expires_at}"
        if reason:
            memory.set_tip_status(tip.id, "pruned", reason=reason)
            report.pruned_tips.append(PruningDecision(
                item_type="tip", item_id=tip.id, decision="pruned", reason=reason,
            ))
    for fact in memory.get_facts(status="active"):
        reason = None
        if fact.confidence < MIN_CONFIDENCE:
            reason = f"confidence {fact.confidence} below floor {MIN_CONFIDENCE}"
        elif _expired(fact.expires_at, now):
            reason = f"expired {fact.expires_at}"
        if reason:
            memory.set_fact_status(fact.id, "pruned", reason=reason)
            report.pruned_facts.append(PruningDecision(
                item_type="fact", item_id=fact.id, decision="pruned", reason=reason,
            ))
    return report


def run_maintenance(
    memory: ReasoningMemory,
    *,
    inbox: object | None = None,
    now: str | None = None,
) -> MaintenanceReport:
    """Full maintenance pass: contradictions first, then stale pruning.

    ``inbox`` (a :class:`SkillInbox`) is optional: when given, promoted
    skills whose registry confidence fell below the floor are pruned too.
    """
    report = MaintenanceReport()
    report.contradictions = detect_contradictions(memory)
    stale = prune_stale(memory, now=now)
    report.pruned_tips = stale.pruned_tips
    report.pruned_facts = stale.pruned_facts
    if inbox is not None:
        from .inbox import SkillInbox  # local import: avoids a cycle at module load

        assert isinstance(inbox, SkillInbox)
        for entry in inbox.registry_entries():
            if entry["status"] != "promoted":
                continue
            if float(entry.get("confidence") or 0.0) < MIN_CONFIDENCE:
                reason = (
                    f"confidence {entry['confidence']} below floor {MIN_CONFIDENCE}"
                )
                inbox.set_skill_status(entry["name"], "pruned", reason=reason)
                report.pruned_skills.append(PruningDecision(
                    item_type="skill", item_id=entry["name"],
                    decision="pruned", reason=reason,
                ))
    return report
