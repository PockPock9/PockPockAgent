"""Planner/executor model selection for Plan-and-Sequence (P3).

Pure functions, no I/O: given the set of installed (enabled local) models,
pick the model that plans and the model that executes one subtask at a time.
The planner service calls these before asking a model for a sequence plan.

Open-decision defaults implemented here (see the Plan-and-Sequence design
page, "Open decisions"):

* **Planner model: local by default.** The planner is the strong local
  model (:data:`DEFAULT_PLANNER_MODEL`) unless a cloud planner is explicitly
  configured (``POCKPOCK_PLAN_SEQUENCE_CLOUD_PLANNER_MODEL``) and explicitly
  requested as the preferred model. Cloud is never the silent default.
* **Step count: 5-15 steps.** Enforced by the plan validator
  (``projects.plan_sequence.contracts``); routing does not re-check it.
* **Capsule size: <=400 tokens.** Enforced by the capsule builder
  (``projects.plan_sequence.capsule``); routing does not re-check it.
* **Re-plan scope: remaining steps only.** A failed step triggers a re-plan
  of the steps after it, not of the whole task. (Implemented by the runner,
  P2+; recorded here so the default is not re-decided per call.)

Model tags
----------
``DEFAULT_PLANNER_MODEL`` (``"qwen3.6:35b-a3b"``) is a real Ollama library
tag for Qwen3.6-35B-A3B, verified Nov 2026 against the Ollama tag list as
reported by independent setup guides (aifoss.dev, "Qwen3.6-35B-A3B Local
Setup 2026", and axiomi.si, "Qwen 3.6 MoE Local Setup: 35B-A3B Guide",
both showing ``ollama pull qwen3.6:35b-a3b``; ``qwen3.6:35b`` is the short
alias for the same build, ~23-24 GB). Override it with
``POCKPOCK_PLAN_SEQUENCE_PLANNER_MODEL`` if the installed tag differs.
``DEFAULT_EXECUTOR_MODEL`` (``"qwen3.5:9b"``) is already used elsewhere in
the repo.
"""

from __future__ import annotations

import os
from typing import Any

#: Strong local planner: Qwen3.6-35B-A3B (35B total / 3B active MoE).
#: Verified Ollama tag — see the module docstring.
DEFAULT_PLANNER_MODEL = "qwen3.6:35b-a3b"

#: Standard executor: Qwen3.5-9B.
DEFAULT_EXECUTOR_MODEL = "qwen3.5:9b"

#: Executor for the simplest, most constrained steps.
SIMPLE_EXECUTOR_MODEL = "qwen3.5:2b"

#: Minimum size, in billions of parameters, for an executor fallback model.
MIN_EXECUTOR_BILLIONS = 2.0

PLANNER_MODEL_ENV = "POCKPOCK_PLAN_SEQUENCE_PLANNER_MODEL"
EXECUTOR_MODEL_ENV = "POCKPOCK_PLAN_SEQUENCE_EXECUTOR_MODEL"
CLOUD_PLANNER_MODEL_ENV = "POCKPOCK_PLAN_SEQUENCE_CLOUD_PLANNER_MODEL"


def _env_model(name: str) -> str | None:
    """A non-blank env-configured model name, or ``None`` when unset."""
    value = os.environ.get(name, "").strip()
    return value or None


def _is_available(model: str, installed: set[str], *, cloud_model: str | None) -> bool:
    """Whether ``model`` can be used: installed locally, or the configured cloud planner."""
    return model in installed or (cloud_model is not None and model == cloud_model)


def _profile_size(profiles: list[dict] | None, name: str) -> float | None:
    """``parameter_billions`` for ``name`` from the profiles, or ``None`` when unknown."""
    if not profiles:
        return None
    for item in profiles:
        if item.get("name") == name:
            size = item.get("parameter_billions")
            return size if isinstance(size, (int, float)) else None
    return None


def _tool_capable_candidates(
    installed: set[str],
    profiles: list[dict] | None,
) -> list[tuple[str, float | None]]:
    """Installed models that advertise tool support, with known sizes.

    When ``profiles`` is given, only models whose profile lists ``"tools"``
    in ``capabilities`` are candidates. When it is not given, size and
    tool support are unknown, so every installed model stays eligible
    (mirroring ``planner.routing.choose_candidate``, where unknown context
    stays eligible) with an unknown size.
    """
    if not profiles:
        return [(name, None) for name in installed]
    candidates: list[tuple[str, float | None]] = []
    for item in profiles:
        name = item.get("name")
        capabilities = item.get("capabilities")
        if (
            isinstance(name, str)
            and name in installed
            and isinstance(capabilities, list)
            and "tools" in capabilities
        ):
            size = item.get("parameter_billions")
            candidates.append((name, size if isinstance(size, (int, float)) else None))
    return candidates


def choose_planner_model(
    installed: set[str],
    *,
    preferred: str | None = None,
    cloud_model: str | None = None,
    fallback: str | None = None,
    profiles: list[dict] | None = None,
) -> tuple[str, str]:
    """Pick the planner model.

    Order: explicit ``preferred`` if available (installed locally, or the
    configured ``cloud_model``); else the ``POCKPOCK_PLAN_SEQUENCE_PLANNER_MODEL``
    env model if available; else :data:`DEFAULT_PLANNER_MODEL` if installed;
    else ``fallback`` (the gateway's configured default model) if installed;
    else the largest installed tool-capable model by ``parameter_billions``.
    ``cloud_model`` defaults to the ``POCKPOCK_PLAN_SEQUENCE_CLOUD_PLANNER_MODEL``
    env value when not passed explicitly. Raises ``ValueError`` when no model
    is available for planning.
    """
    if cloud_model is None:
        cloud_model = _env_model(CLOUD_PLANNER_MODEL_ENV)
    if preferred and _is_available(preferred, installed, cloud_model=cloud_model):
        if cloud_model is not None and preferred == cloud_model and preferred not in installed:
            return preferred, "Used the explicitly requested cloud planner model."
        return preferred, "Used the explicitly requested planner model."
    env_model = _env_model(PLANNER_MODEL_ENV)
    if env_model and _is_available(env_model, installed, cloud_model=cloud_model):
        return env_model, "Used the configured planner model (POCKPOCK_PLAN_SEQUENCE_PLANNER_MODEL)."
    if DEFAULT_PLANNER_MODEL in installed:
        return DEFAULT_PLANNER_MODEL, "Used the default local planner model (Qwen3.6-35B-A3B)."
    if fallback and fallback in installed:
        return fallback, "Used the gateway's configured default model as the planner."
    candidates = _tool_capable_candidates(installed, profiles)
    if not candidates:
        raise ValueError("No model available for planning")
    # Largest known size wins; unknown sizes rank last, name breaks ties
    # so the choice is deterministic.
    selected = max(candidates, key=lambda item: (item[1] if item[1] is not None else -1.0, item[0]))
    if selected[1] is None:
        return selected[0], "No configured planner model is installed; used an installed tool-capable model (size unknown without model profiles)."
    return selected[0], f"No configured planner model is installed; used the largest installed tool-capable model ({selected[1]:g}B parameters)."


def choose_executor_model(
    installed: set[str],
    *,
    step_complexity: str = "standard",
    profiles: list[dict] | None = None,
) -> tuple[str, str]:
    """Pick the executor model for one subtask.

    ``step_complexity`` is ``"simple"`` or ``"standard"``. Simple steps
    prefer :data:`SIMPLE_EXECUTOR_MODEL` (qwen3.5:2b); standard steps prefer
    :data:`DEFAULT_EXECUTOR_MODEL` (qwen3.5:9b). A
    ``POCKPOCK_PLAN_SEQUENCE_EXECUTOR_MODEL`` env model, when installed,
    wins over both. Otherwise the fallback is the smallest installed
    tool-capable model with at least ``MIN_EXECUTOR_BILLIONS`` parameters.
    Raises ``ValueError`` when nothing fits, or for an unknown complexity.
    """
    if step_complexity not in ("simple", "standard"):
        raise ValueError(f"Unknown step complexity: {step_complexity!r}")
    env_model = _env_model(EXECUTOR_MODEL_ENV)
    if env_model and env_model in installed:
        return env_model, "Used the configured executor model (POCKPOCK_PLAN_SEQUENCE_EXECUTOR_MODEL)."
    if step_complexity == "simple" and SIMPLE_EXECUTOR_MODEL in installed:
        return SIMPLE_EXECUTOR_MODEL, "Used the small executor model for a simple step."
    if DEFAULT_EXECUTOR_MODEL in installed:
        if step_complexity == "simple":
            return DEFAULT_EXECUTOR_MODEL, "The small executor model is not installed; used the default executor model for a simple step."
        return DEFAULT_EXECUTOR_MODEL, "Used the default executor model."
    candidates = [
        (name, size)
        for name, size in _tool_capable_candidates(installed, profiles)
        # Unknown size stays eligible (no profiles to rank by); known sizes
        # must clear the 2B floor.
        if size is None or size >= MIN_EXECUTOR_BILLIONS
    ]
    if not candidates:
        raise ValueError("No model available for execution")
    # Smallest known size wins; unknown sizes rank last, name breaks ties.
    selected = min(candidates, key=lambda item: (item[1] if item[1] is not None else float("inf"), item[0]))
    if selected[1] is None:
        return selected[0], "No default executor model is installed; used an installed tool-capable model (size unknown without model profiles)."
    return selected[0], f"No default executor model is installed; used the smallest installed tool-capable model at or above 2B parameters ({selected[1]:g}B)."
