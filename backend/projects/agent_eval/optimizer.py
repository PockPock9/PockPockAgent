"""GEPA/DSPy-style prompt optimisation, training-free, stdlib only.

No ``dspy`` package is installed and none is needed: the loop here is
the minimal GEPA idea — propose prompt variants, evaluate them against
a metric on real tasks, keep the best, and iterate by mutating the
winner. What it is *not*: fine-tuning. Prompts stay human-readable and
the optimiser never touches weights.

How it works
------------
1.  A candidate pool: the current system prompt plus hand-written
    variants (verification nudge, step-by-step nudge, a one-shot tool
    example, a minimal prompt).
2.  One mutation round: the best train candidate is mutated (append an
    instruction sentence, drop a sentence, swap two sentences) with a
    seeded RNG, so the search is reproducible.
3.  Selection on a *train* slice of the suite; the winner is then
    scored once on a *held-out* slice and that held-out number is the
    reported result. Selecting on the same tasks you report on would
    be overfitting by construction.
4.  Metric: pass@1 first, then fewer mean steps, then fewer mean
    tokens. Every evaluation is appended to a JSONL log so a run can
    be audited or resumed by hand.

The optimiser needs a *real* executor (the live Ollama loop): the
deterministic stub ignores the prompt, so optimising against it would
optimise nothing. ``dry_run=True`` skips model calls entirely and
scores prompts with a cheap heuristic (mentions tools, mentions
verifying before finishing, length) — only a smoke test of the loop
mechanics, clearly labelled as such in the log.
"""

from __future__ import annotations

import json
import random
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Sequence

from .executors import DEFAULT_SYSTEM_PROMPT, estimate_tokens
from .runner import RunConfig, run_suite
from .tasks import EvalTask, split_suite

#: Instruction sentences the mutator can append to a prompt.
MUTATION_SENTENCES = [
    "Before you finish, re-read the task and check that every requested file exists.",
    "If a tool call fails, read the error and try once more with corrected arguments before giving up.",
    "Read a file fully before editing it; never guess its contents.",
    "Prefer the smallest tool call that completes the next step.",
    "When a task has several parts, do them in order and confirm each one with a tool result.",
]

#: One-shot tool-use example (kept tiny: a 2B model's context is precious).
FEWSHOT_EXAMPLE = (
    "\n\nExample: for \"Save hello.txt containing Hello\", call "
    "save_text_artifact with filename \"hello.txt\" and content \"Hello\", "
    "then stop."
)


def candidate_pool(base: str = DEFAULT_SYSTEM_PROMPT) -> list[dict[str, str]]:
    """Hand-written starting candidates: base plus four variants."""
    return [
        {"name": "base", "prompt": base, "source": "pool"},
        {
            "name": "verify-first",
            "prompt": base + " " + MUTATION_SENTENCES[0],
            "source": "pool",
        },
        {
            "name": "read-before-edit",
            "prompt": base + " " + MUTATION_SENTENCES[2],
            "source": "pool",
        },
        {"name": "fewshot", "prompt": base + FEWSHOT_EXAMPLE, "source": "pool"},
        {
            "name": "minimal",
            "prompt": (
                "Complete the task using the tools provided. "
                "Do not claim completion until a tool confirms it."
            ),
            "source": "pool",
        },
    ]


def mutate_prompt(prompt: str, rng: random.Random) -> str:
    """One deterministic mutation: append, drop, or swap a sentence."""
    sentences = [item.strip() for item in prompt.split(". ") if item.strip()]
    choice = rng.choice(["append", "drop", "swap"])
    if choice == "append":
        sentences.append(rng.choice(MUTATION_SENTENCES).rstrip("."))
    elif choice == "drop" and len(sentences) > 1:
        sentences.pop(rng.randrange(len(sentences)))
    elif choice == "swap" and len(sentences) > 1:
        first, second = rng.sample(range(len(sentences)), 2)
        sentences[first], sentences[second] = sentences[second], sentences[first]
    else:  # degenerate case: fall back to appending
        sentences.append(rng.choice(MUTATION_SENTENCES).rstrip("."))
    text = ". ".join(sentences)
    return text if text.endswith(".") else text + "."


def _dry_run_score(prompt: str) -> float:
    """Heuristic smoke-test score; NOT a model measurement (see docstring)."""
    score = 0.0
    lowered = prompt.lower()
    if "tool" in lowered:
        score += 0.4
    if "confirm" in lowered or "verif" in lowered:
        score += 0.3
    if "read" in lowered and "before" in lowered:
        score += 0.2
    score -= min(0.2, estimate_tokens(prompt) / 5000)
    return round(score, 3)


@dataclass
class CandidateScore:
    name: str
    prompt: str
    source: str
    pass_at_1: float | None
    mean_steps: float | None
    mean_tokens: float | None
    dry_run: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "prompt": self.prompt,
            "source": self.source,
            "pass@1": self.pass_at_1,
            "mean_steps_per_task": self.mean_steps,
            "mean_tokens_per_task": self.mean_tokens,
            "dry_run": self.dry_run,
        }


@dataclass
class OptimizerResult:
    best: CandidateScore
    held_out: CandidateScore | None
    evaluations: list[CandidateScore] = field(default_factory=list)
    log_path: Path | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "best": self.best.to_dict(),
            "held_out": self.held_out.to_dict() if self.held_out else None,
            "evaluations": [item.to_dict() for item in self.evaluations],
        }


def optimize(
    tasks: Sequence[EvalTask],
    executor_factory: Callable[[], Any],
    config: RunConfig,
    *,
    candidates: list[dict[str, str]] | None = None,
    train_size: int = 12,
    mutations: int = 4,
    seed: int = 0,
    dry_run: bool = False,
    log_path: Path | None = None,
) -> OptimizerResult:
    """Run one optimisation round; see the module docstring.

    ``executor_factory`` must return a fresh executor per evaluation
    (no state may leak between candidates). With ``dry_run`` no
    executor is built at all. The log (when ``log_path`` is given) is
    one JSON object per evaluation, in order.
    """
    rng = random.Random(seed)
    train_tasks, held_out_tasks = split_suite(list(tasks), train_size=train_size, seed=seed)
    pool = candidates if candidates is not None else candidate_pool(config.system_prompt)
    evaluations: list[CandidateScore] = []
    log_file = open(log_path, "w", encoding="utf-8") if log_path else None

    def _log(record: dict[str, Any]) -> None:
        if log_file is not None:
            log_file.write(json.dumps(record) + "\n")
            log_file.flush()

    def _evaluate(name: str, prompt: str, source: str, subset: list[EvalTask]) -> CandidateScore:
        if dry_run:
            scored = CandidateScore(
                name=name, prompt=prompt, source=source,
                pass_at_1=_dry_run_score(prompt), mean_steps=None,
                mean_tokens=float(estimate_tokens(prompt)), dry_run=True,
            )
        else:
            run_config = RunConfig(
                model=config.model,
                quantisation=config.quantisation,
                seed=config.seed,
                attempts=1,
                executor=config.executor,
                system_prompt=prompt,
                include_network=config.include_network,
            )
            report = run_suite(
                subset, executor_factory(), run_config,
                suite_name="agent_eval-optimizer",
            )
            summary = report.summary()
            scored = CandidateScore(
                name=name, prompt=prompt, source=source,
                pass_at_1=summary["pass@1"],
                mean_steps=summary["mean_steps_per_task"],
                mean_tokens=summary["mean_tokens_per_task"],
            )
        evaluations.append(scored)
        _log({**scored.to_dict(), "subset": "train" if subset is train_tasks else "held-out",
              "tasks": [task.id for task in subset], "at": time.time()})
        return scored

    for candidate in pool:
        _evaluate(candidate["name"], candidate["prompt"], candidate.get("source", "pool"), train_tasks)
    best_train = min(
        evaluations,
        key=lambda item: (-(item.pass_at_1 or 0.0), item.mean_steps or 0.0, item.mean_tokens or 0.0),
    )
    for index in range(mutations):
        child = mutate_prompt(best_train.prompt, rng)
        _evaluate(f"{best_train.name}-mut{index + 1}", child, "mutation", train_tasks)
    best_train = min(
        evaluations,
        key=lambda item: (-(item.pass_at_1 or 0.0), item.mean_steps or 0.0, item.mean_tokens or 0.0),
    )
    held_out: CandidateScore | None = None
    if held_out_tasks:
        held_out = _evaluate(best_train.name, best_train.prompt, "best-on-train", held_out_tasks)
    if log_file is not None:
        log_file.close()
    return OptimizerResult(best=best_train, held_out=held_out, evaluations=evaluations, log_path=log_path)
