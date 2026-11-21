"""Deterministic verifiers for eval tasks.

A verifier never asks a model whether the task is done: it checks the
workspace the agent left behind — files exist and contain the right
content, JSON parses and matches a schema, a command exits 0 and prints
what it should. This is the external ground truth the differentiation
research calls for (report §2.2/§5 #2): self-report is not evidence.

Supported verifier kinds (each is one dict in a task's ``verifiers``)::

    {"kind": "file_exists", "path": "shopping.txt"}
    {"kind": "file_contains", "path": "report.md",
     "contains": ["Decisions", "Priya"]}
    {"kind": "file_not_contains", "path": "notes.md", "contains": ["TODO"]}
    {"kind": "file_matches", "path": "answer.txt", "pattern": r"total:\\s*42"}
    {"kind": "file_json", "path": "settings.json", "schema": {...}}
    {"kind": "command", "command": ["{python}", "greet.py"],
     "expect_exit": 0, "stdout_contains": ["Good morning"]}
    {"kind": "all", "checks": [...]}   # every sub-check must pass
    {"kind": "any", "checks": [...]}   # at least one sub-check must pass

``file_json`` checks a small, self-contained subset of JSON Schema —
``type``, ``required``, ``properties``, ``items``, ``enum``,
``minimum``/``maximum``, ``minLength``/``maxLength`` — because the
backend has no ``jsonschema`` dependency and the harness must stay
dependency-free. Unknown schema keywords are ignored, not errors.

``command`` runs with no shell, a bounded timeout, and the task
workspace as its working directory. ``{python}`` in argv is replaced
with the current interpreter so suites work on Windows, macOS and
Linux. Commands never run outside the workspace.
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

MAX_COMMAND_OUTPUT_CHARS = 20_000


@dataclass
class CheckResult:
    kind: str
    passed: bool
    detail: str = ""
    subresults: list["CheckResult"] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "passed": self.passed,
            "detail": self.detail,
            "subresults": [item.to_dict() for item in self.subresults],
        }


def _resolve(workspace: Path, relative: str) -> Path:
    """Resolve a verifier path inside the workspace; escape is a failure."""
    candidate = (workspace / relative).resolve()
    try:
        candidate.relative_to(workspace.resolve())
    except ValueError:
        raise ValueError(f"Verifier path escapes the workspace: {relative!r}")
    return candidate


def _read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _check_file_exists(spec: dict[str, Any], workspace: Path) -> CheckResult:
    path = _resolve(workspace, str(spec.get("path", "")))
    if path.is_file():
        return CheckResult("file_exists", True, f"{spec.get('path')} exists")
    return CheckResult("file_exists", False, f"{spec.get('path')} does not exist")


def _check_file_contains(spec: dict[str, Any], workspace: Path, *, negate: bool) -> CheckResult:
    kind = "file_not_contains" if negate else "file_contains"
    path = _resolve(workspace, str(spec.get("path", "")))
    needles = spec.get("contains") or []
    if not isinstance(needles, list) or not needles:
        return CheckResult(kind, False, "'contains' must be a non-empty list")
    if not path.is_file():
        return CheckResult(kind, False, f"{spec.get('path')} does not exist")
    try:
        text = _read_text(path)
    except (OSError, UnicodeDecodeError) as err:
        return CheckResult(kind, False, f"Could not read {spec.get('path')}: {err}")
    missing = [needle for needle in needles if needle not in text]
    present = [needle for needle in needles if needle in text]
    if negate:
        if present:
            return CheckResult(kind, False, f"Forbidden text present in {spec.get('path')}: {present!r}")
        return CheckResult(kind, True, f"None of {needles!r} in {spec.get('path')}")
    if missing:
        return CheckResult(kind, False, f"Missing from {spec.get('path')}: {missing!r}")
    return CheckResult(kind, True, f"All of {needles!r} in {spec.get('path')}")


def _check_file_matches(spec: dict[str, Any], workspace: Path) -> CheckResult:
    path = _resolve(workspace, str(spec.get("path", "")))
    pattern = str(spec.get("pattern", ""))
    if not path.is_file():
        return CheckResult("file_matches", False, f"{spec.get('path')} does not exist")
    try:
        compiled = re.compile(pattern)
    except re.error as err:
        return CheckResult("file_matches", False, f"Invalid pattern {pattern!r}: {err}")
    try:
        text = _read_text(path)
    except (OSError, UnicodeDecodeError) as err:
        return CheckResult("file_matches", False, f"Could not read {spec.get('path')}: {err}")
    if compiled.search(text):
        return CheckResult("file_matches", True, f"{pattern!r} matched in {spec.get('path')}")
    return CheckResult("file_matches", False, f"{pattern!r} did not match in {spec.get('path')}")


def _schema_errors(value: Any, schema: dict[str, Any], where: str) -> list[str]:
    """Check ``value`` against a small JSON Schema subset; return errors."""
    errors: list[str] = []
    if not isinstance(schema, dict):
        return [f"{where}: schema must be an object"]
    expected = schema.get("type")
    if expected is not None:
        ok = {
            "object": isinstance(value, dict),
            "array": isinstance(value, list),
            "string": isinstance(value, str),
            "integer": isinstance(value, int) and not isinstance(value, bool),
            "number": isinstance(value, (int, float)) and not isinstance(value, bool),
            "boolean": isinstance(value, bool),
            "null": value is None,
        }.get(expected)
        if ok is False:
            errors.append(f"{where}: expected type {expected}, got {type(value).__name__}")
            return errors
        if ok is None:
            errors.append(f"{where}: unsupported schema type {expected!r}")
    if "enum" in schema and value not in schema["enum"]:
        errors.append(f"{where}: {value!r} not in enum {schema['enum']!r}")
    if isinstance(value, str):
        if "minLength" in schema and len(value) < schema["minLength"]:
            errors.append(f"{where}: shorter than minLength {schema['minLength']}")
        if "maxLength" in schema and len(value) > schema["maxLength"]:
            errors.append(f"{where}: longer than maxLength {schema['maxLength']}")
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        if "minimum" in schema and value < schema["minimum"]:
            errors.append(f"{where}: {value} below minimum {schema['minimum']}")
        if "maximum" in schema and value > schema["maximum"]:
            errors.append(f"{where}: {value} above maximum {schema['maximum']}")
    if isinstance(value, dict):
        for name in schema.get("required") or []:
            if name not in value:
                errors.append(f"{where}: missing required property {name!r}")
        for name, subschema in (schema.get("properties") or {}).items():
            if name in value:
                errors.extend(_schema_errors(value[name], subschema, f"{where}.{name}"))
    if isinstance(value, list) and isinstance(schema.get("items"), dict):
        for index, item in enumerate(value):
            errors.extend(_schema_errors(item, schema["items"], f"{where}[{index}]"))
    return errors


def _check_file_json(spec: dict[str, Any], workspace: Path) -> CheckResult:
    path = _resolve(workspace, str(spec.get("path", "")))
    if not path.is_file():
        return CheckResult("file_json", False, f"{spec.get('path')} does not exist")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as err:
        return CheckResult("file_json", False, f"{spec.get('path')} is not valid JSON: {err}")
    schema = spec.get("schema")
    if schema is None:
        return CheckResult("file_json", True, f"{spec.get('path')} parses as JSON")
    errors = _schema_errors(value, schema, "$")
    if errors:
        return CheckResult("file_json", False, "; ".join(errors))
    return CheckResult("file_json", True, f"{spec.get('path')} matches its schema")


def _check_command(spec: dict[str, Any], workspace: Path) -> CheckResult:
    argv = spec.get("command")
    if not isinstance(argv, list) or not argv or not all(isinstance(part, str) for part in argv):
        return CheckResult("command", False, "'command' must be a non-empty list of strings")
    argv = [sys.executable if part == "{python}" else part for part in argv]
    timeout = spec.get("timeout_s", 30)
    if isinstance(timeout, bool) or not isinstance(timeout, int) or timeout <= 0:
        return CheckResult("command", False, "'timeout_s' must be a positive integer")
    try:
        result = subprocess.run(
            argv,
            cwd=workspace,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except FileNotFoundError:
        return CheckResult("command", False, f"Command not found: {argv[0]!r}")
    except subprocess.TimeoutExpired:
        return CheckResult("command", False, f"Command timed out after {timeout}s: {' '.join(argv)}")
    except OSError as err:
        return CheckResult("command", False, f"Could not run command: {err}")
    expected_exit = spec.get("expect_exit", 0)
    problems: list[str] = []
    if result.returncode != expected_exit:
        problems.append(f"exit {result.returncode}, expected {expected_exit}")
    for needle in spec.get("stdout_contains") or []:
        if needle not in result.stdout:
            problems.append(f"stdout missing {needle!r}")
    for needle in spec.get("stderr_contains") or []:
        if needle not in result.stderr:
            problems.append(f"stderr missing {needle!r}")
    detail = "; ".join(problems) if problems else f"exit {result.returncode}"
    if result.stdout.strip():
        detail += f" | stdout: {result.stdout.strip()[:200]!r}"
    if problems and result.stderr.strip():
        detail += f" | stderr: {result.stderr.strip()[:500]!r}"
    return CheckResult("command", not problems, detail[:2000])


def run_check(spec: dict[str, Any], workspace: Path) -> CheckResult:
    """Run one verifier spec against ``workspace``; never raises for bad specs."""
    kind = spec.get("kind") if isinstance(spec, dict) else None
    try:
        if kind == "file_exists":
            return _check_file_exists(spec, workspace)
        if kind == "file_contains":
            return _check_file_contains(spec, workspace, negate=False)
        if kind == "file_not_contains":
            return _check_file_contains(spec, workspace, negate=True)
        if kind == "file_matches":
            return _check_file_matches(spec, workspace)
        if kind == "file_json":
            return _check_file_json(spec, workspace)
        if kind == "command":
            return _check_command(spec, workspace)
        if kind in {"all", "any"}:
            checks = spec.get("checks")
            if not isinstance(checks, list) or not checks:
                return CheckResult(str(kind), False, f"'{kind}' needs a non-empty 'checks' list")
            subresults = [run_check(item, workspace) for item in checks]
            passed = (
                all(item.passed for item in subresults)
                if kind == "all"
                else any(item.passed for item in subresults)
            )
            return CheckResult(str(kind), passed, "", subresults)
        return CheckResult(str(kind), False, f"Unknown verifier kind: {kind!r}")
    except (ValueError, OSError) as err:
        return CheckResult(str(kind), False, str(err))


@dataclass
class VerificationResult:
    passed: bool
    checks: list[CheckResult] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {"passed": self.passed, "checks": [item.to_dict() for item in self.checks]}


def verify_task(task: Any, workspace: Path) -> VerificationResult:
    """Run every verifier of ``task`` (all must pass); see ``run_check``."""
    checks = [run_check(spec, workspace) for spec in task.verifiers]
    return VerificationResult(passed=all(item.passed for item in checks), checks=checks)
