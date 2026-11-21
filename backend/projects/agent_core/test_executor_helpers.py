import re
import sys
import unittest
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[2] / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from projects.agent_core.executor import effective_task_capabilities  # noqa: E402


class EffectiveCapabilityTests(unittest.TestCase):
    def test_a_tool_task_with_no_planned_capability_gets_the_artifact_tools(self):
        # Issue #92: an empty capability list gave the model zero tools, then failed it for calling none.
        self.assertEqual(effective_task_capabilities([], requires_tool=True, has_files=False), ["artifact_creation"])

    def test_attachments_are_readable(self):
        self.assertEqual(
            effective_task_capabilities([], requires_tool=True, has_files=True),
            ["attachment_read", "artifact_creation"],
        )

    def test_planned_capabilities_are_kept_and_never_widened(self):
        planned = ["workspace_read", "workspace_write"]
        self.assertEqual(effective_task_capabilities(planned, requires_tool=True, has_files=False), planned)
        self.assertEqual(effective_task_capabilities([], requires_tool=False, has_files=False), [])
        for risky in ("workspace_write", "public_research", "browser_action"):
            self.assertNotIn(risky, effective_task_capabilities([], requires_tool=True, has_files=True))


class OwnTaskFolderTests(unittest.TestCase):
    def test_an_artifact_run_may_read_its_own_task_folder(self):
        # Live validation 2026-11-21: a plan check 'read the file back' could only end INCOMPLETE.
        self.assertEqual(
            effective_task_capabilities(["artifact_creation"], requires_tool=True, has_files=False, own_task_folder=True),
            ["artifact_creation", "workspace_read"],
        )
        # With a folder of the user's open, reading it still needs the approved plan.
        self.assertEqual(
            effective_task_capabilities(["artifact_creation"], requires_tool=True, has_files=False, own_task_folder=False),
            ["artifact_creation"],
        )


class TelemetryEventTests(unittest.TestCase):
    def test_every_event_the_executor_records_is_accepted(self):
        # Issue #50: build_review (and other diagnostics) were rejected as "Unsupported event type".
        import telemetry_store

        source = (Path(__file__).resolve().parent / "executor.py").read_text(encoding="utf-8")
        recorded = set(re.findall(r'record\(\{\s*"event":\s*"([a-z_]+)"', source))
        self.assertIn("build_review", recorded)
        self.assertEqual(recorded - telemetry_store.SUPPORTED_EVENTS, set())


if __name__ == "__main__":
    unittest.main()
