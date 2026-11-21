"""Run every backend test suite. Usage: python backend/scripts/run_tests.py

Packages under backend/projects are discovered from the backend folder; the loopback services
(planner, validator, run_store, browser_automation) are not packages and run from their own folder.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
PACKAGES = ["agent_core", "agent_eval", "agent_extensions", "agent_skills", "agent_tools", "connectors", "local_memory", "model_router", "nemoclaw_bridge", "observability", "openclaw_bridge", "plan_sequence"]
SERVICES = ["planner", "run_store", "browser_automation", "validator", "agent_verifier"]


def run(label: str, args: list[str], cwd: Path) -> bool:
    # Some service tests import "projects.<name>", so the backend folder is always importable.
    env = {**os.environ, "PYTHONPATH": os.pathsep.join(filter(None, [str(BACKEND), os.environ.get("PYTHONPATH", "")]))}
    result = subprocess.run([sys.executable, "-m", "unittest", *args], cwd=cwd, capture_output=True, text=True, env=env)
    summary = [line for line in result.stderr.splitlines() if line.startswith(("Ran ", "OK", "FAILED"))]
    print(f"{label:<20} {' '.join(summary) or 'no tests'}")
    if result.returncode != 0:
        print(result.stderr[-3000:])
    return result.returncode == 0


def main() -> int:
    ok = True
    for package in PACKAGES:
        folder = BACKEND / "projects" / package
        if any(folder.glob("test_*.py")):
            ok &= run(package, ["discover", "-s", f"projects/{package}", "-t", ".", "-p", "test_*.py"], BACKEND)
    for service in SERVICES:
        folder = BACKEND / "projects" / service
        if any(folder.glob("test_*.py")):
            ok &= run(service, ["discover", "-s", ".", "-p", "test_*.py"], folder)
    ok &= run("smart_router", ["scripts.test_smart_router"], BACKEND)
    ok &= run("pockpock", ["test_pockpock", "test_pockpock_paths", "test_pockpock_chat", "test_hidden_launch", "test_plan_sequence_eval", "test_agent_run_stream"], BACKEND / "scripts")
    print("All backend tests passed." if ok else "Some backend tests failed.")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
