"""Plan-and-Sequence: sequence plan schema, validation, state capsule,
verifier, sequenced runner, and planner/executor model routing.

Public API for the Plan-and-Sequence design (see the wiki page
``Plan-and-Sequence`` and ``docs/features/plan-and-sequence.md``).
The names exported here are frozen; do not rename them.
"""

from .capsule import build_capsule, capsule_to_text, capsule_token_estimate
from .contracts import (
    MAX_CAPSULE_TOKENS,
    MAX_STEPS,
    MAX_STEP_RETRIES,
    MAX_TOOLS_PER_STEP,
    MIN_STEPS,
    SEQUENCE_CONTRACT_VERSION,
    CapsuleEntry,
    DoneCondition,
    SequencePlan,
    SequenceRunResult,
    SequenceStep,
    StateCapsule,
    StepResult,
    validate_sequence_plan,
)
from .routing import (
    CLOUD_PLANNER_MODEL_ENV,
    DEFAULT_EXECUTOR_MODEL,
    DEFAULT_PLANNER_MODEL,
    EXECUTOR_MODEL_ENV,
    MIN_EXECUTOR_BILLIONS,
    PLANNER_MODEL_ENV,
    SIMPLE_EXECUTOR_MODEL,
    choose_executor_model,
    choose_planner_model,
)
from .runner import SequenceRunner, build_step_prompt
from .verifier import verify_done_condition

__all__ = [
    "MAX_CAPSULE_TOKENS",
    "MAX_STEPS",
    "MAX_STEP_RETRIES",
    "MAX_TOOLS_PER_STEP",
    "MIN_STEPS",
    "SEQUENCE_CONTRACT_VERSION",
    "CLOUD_PLANNER_MODEL_ENV",
    "DEFAULT_EXECUTOR_MODEL",
    "DEFAULT_PLANNER_MODEL",
    "EXECUTOR_MODEL_ENV",
    "MIN_EXECUTOR_BILLIONS",
    "PLANNER_MODEL_ENV",
    "SIMPLE_EXECUTOR_MODEL",
    "CapsuleEntry",
    "DoneCondition",
    "SequencePlan",
    "SequenceRunResult",
    "SequenceStep",
    "SequenceRunner",
    "StateCapsule",
    "StepResult",
    "build_capsule",
    "build_step_prompt",
    "capsule_to_text",
    "capsule_token_estimate",
    "choose_executor_model",
    "choose_planner_model",
    "validate_sequence_plan",
    "verify_done_condition",
]
