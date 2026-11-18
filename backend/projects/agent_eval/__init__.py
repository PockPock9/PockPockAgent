"""Local agent eval harness (Phase 1 of the agentic-AI differentiation plan).

Run a fixed suite of verifiable tasks against an executor, measure
pass@1 and pass^k (k=3, 5), steps / tokens / wall time per task, and
record the exact model, quantisation and seed per run. Optimise the
system prompt against the harness (GEPA-style, training-free) and
export verified traces as SFT data for later LoRA distillation of the
small executor.

See ``README.md`` in this package and
``docs/features/agent-eval-harness.md``.
"""

from .executors import DEFAULT_SYSTEM_PROMPT, OllamaExecutor, StubExecutor
from .optimizer import candidate_pool, mutate_prompt, optimize
from .runner import RunConfig, RunReport, run_suite
from .tasks import EvalTask, load_suite, split_suite
from .traces import export_traces_from_report
from .verifiers import VerificationResult, verify_task

__all__ = [
    "DEFAULT_SYSTEM_PROMPT",
    "EvalTask",
    "OllamaExecutor",
    "RunConfig",
    "RunReport",
    "StubExecutor",
    "VerificationResult",
    "candidate_pool",
    "export_traces_from_report",
    "load_suite",
    "mutate_prompt",
    "optimize",
    "run_suite",
    "split_suite",
    "verify_task",
]
