"""Unit tests for the OpenClaw bridge. A fake helper process stands in for Node and OpenClaw."""

from __future__ import annotations

import json
import queue
import tempfile
import unittest
from pathlib import Path

from projects.openclaw_bridge.bridge import (
    MAX_MESSAGE_CHARS,
    MAX_TRACKED_SESSIONS,
    OpenClawBridge,
    OpenClawConfig,
    OpenClawError,
    PermissionState,
    session_key,
    validate_mode,
    validate_session_id,
)


class FakeStdin:
    def __init__(self, process: "FakeProcess"):
        self.process = process
        self.closed = False

    def write(self, data: bytes) -> None:
        if self.closed:
            raise ValueError("closed")
        self.process.received.append(json.loads(data.decode("utf-8")))

    def flush(self) -> None:
        pass

    def close(self) -> None:
        self.closed = True
        self.process.finish()


class FakeStdout:
    def __init__(self, lines: "queue.Queue[bytes | None]"):
        self.lines = lines

    def __iter__(self):
        return self

    def __next__(self) -> bytes:
        line = self.lines.get(timeout=5)
        if line is None:
            raise StopIteration
        return line


class FakeProcess:
    """Records what the bridge writes and replays scripted helper output."""

    def __init__(self):
        self.received: list[dict] = []
        self._lines: "queue.Queue[bytes | None]" = queue.Queue()
        self.stdin = FakeStdin(self)
        self.stdout = FakeStdout(self._lines)
        self.exited = False
        self.killed = False

    def emit(self, event: dict) -> None:
        self._lines.put((json.dumps(event) + "\n").encode("utf-8"))

    def emit_raw(self, raw: bytes) -> None:
        self._lines.put(raw)

    def finish(self) -> None:
        if not self.exited:
            self.exited = True
            self._lines.put(None)

    def poll(self):
        return 0 if self.exited else None

    def wait(self, timeout=None):
        self.finish()
        return 0

    def kill(self) -> None:
        self.killed = True
        self.finish()


class BridgeHarness:
    def __init__(self, directory: str, **config):
        self.processes: list[FakeProcess] = []
        self.commands: list[list[str]] = []
        self.helper = Path(directory) / "gateway_turn.mjs"
        self.helper.write_text("// test helper", encoding="utf-8")
        self.permissions = PermissionState(Path(directory) / "pockpock" / "permissions.json")
        self.bridge = OpenClawBridge(
            OpenClawConfig(**config),
            spawn=self._spawn,
            which=lambda name: f"C:/node/{name}.exe",
            permissions=self.permissions,
            helper_path=self.helper,
        )

    def _spawn(self, command: list[str]) -> FakeProcess:
        self.commands.append(command)
        process = FakeProcess()
        self.processes.append(process)
        return process


def drain(turn) -> list[dict]:
    events = []
    while True:
        event = turn.next_event(5)
        if event is None:
            return events
        if event is False:
            raise AssertionError("turn produced no event in time")
        events.append(event)


class ConfigAndValidationTests(unittest.TestCase):
    def test_config_defaults_and_clamps_timeout(self):
        self.assertEqual(OpenClawConfig.from_env({}).agent, "main")
        self.assertEqual(OpenClawConfig.from_env({"POCKPOCK_OPENCLAW_TIMEOUT_SECONDS": "5"}).timeout_seconds, 30)
        self.assertEqual(OpenClawConfig.from_env({"POCKPOCK_OPENCLAW_TIMEOUT_SECONDS": "99999"}).timeout_seconds, 3600)
        self.assertFalse(OpenClawConfig.from_env({"POCKPOCK_OPENCLAW_ENABLED": "off"}).enabled)

    def test_config_rejects_unsafe_agent_name(self):
        with self.assertRaises(ValueError):
            OpenClawConfig.from_env({"POCKPOCK_OPENCLAW_AGENT": "main; rm"})

    def test_session_id_must_carry_pockpock_prefix(self):
        self.assertEqual(validate_session_id("pockpock-abc_123"), "pockpock-abc_123")
        for bad in ("abc", "main", "pockpock-", "pockpock-a b", "pockpock-../x", "agent:main:main"):
            with self.assertRaises(OpenClawError):
                validate_session_id(bad)

    def test_mode_validation(self):
        self.assertEqual(validate_mode(" Auto "), "auto")
        with self.assertRaises(OpenClawError):
            validate_mode("yolo")


class PermissionStateTests(unittest.TestCase):
    def test_set_read_and_missing_file(self):
        with tempfile.TemporaryDirectory() as directory:
            state = PermissionState(Path(directory) / "nested" / "permissions.json")
            self.assertEqual(state.read(), {})
            state.set("agent:main:explicit:pockpock-a", "full")
            state.set("agent:main:explicit:pockpock-b", "auto")
            self.assertEqual(state.read()["agent:main:explicit:pockpock-a"], "full")
            self.assertEqual(json.loads(state.path.read_text("utf-8"))["version"], 1)

    def test_corrupt_file_and_unknown_modes_are_ignored(self):
        with tempfile.TemporaryDirectory() as directory:
            state = PermissionState(Path(directory) / "permissions.json")
            state.path.write_text("{not json", encoding="utf-8")
            self.assertEqual(state.read(), {})
            state.path.write_text(json.dumps({"sessions": {"a": "root", "b": "ask"}}), encoding="utf-8")
            self.assertEqual(state.read(), {"b": "ask"})

    def test_oldest_sessions_are_pruned(self):
        with tempfile.TemporaryDirectory() as directory:
            state = PermissionState(Path(directory) / "permissions.json")
            for index in range(MAX_TRACKED_SESSIONS + 5):
                state.set(f"s{index}", "ask")
            sessions = state.read()
            self.assertEqual(len(sessions), MAX_TRACKED_SESSIONS)
            self.assertNotIn("s0", sessions)
            self.assertIn(f"s{MAX_TRACKED_SESSIONS + 4}", sessions)


class TurnTests(unittest.TestCase):
    def test_turn_sends_message_on_stdin_and_records_mode(self):
        with tempfile.TemporaryDirectory() as directory:
            harness = BridgeHarness(directory)
            secret = 'delete "everything"; $(whoami) `x`'
            turn = harness.bridge.start_turn("pockpock-c1", secret, "auto")
            process = harness.processes[0]
            process.emit({"type": "delta", "text": "Hi"})
            process.emit({"type": "final", "text": "Hi there", "model": "qwen3.5:9b"})
            events = drain(turn)
            self.assertEqual([event["type"] for event in events], ["delta", "final"])
            start = process.received[0]
            self.assertEqual(start["message"], secret)
            self.assertEqual(start["mode"], "auto")
            self.assertEqual(start["model"], "")
            self.assertEqual(start["sessionId"], "pockpock-c1")
            self.assertNotIn(secret, " ".join(harness.commands[0]))
            self.assertEqual(len(harness.commands[0]), 2)
            self.assertEqual(harness.permissions.read()[session_key("main", "pockpock-c1")], "auto")
            self.assertNotIn("toolOverrides", start, "no selection: the session's tools are left as they are")

    def test_a_tool_selection_goes_to_the_helper(self):
        with tempfile.TemporaryDirectory() as directory:
            harness = BridgeHarness(directory)
            overlay = {"skills": {"meme": False}}
            harness.bridge.start_turn("pockpock-c1", "read the pdf", "auto", selection={"toolOverrides": overlay})
            self.assertEqual(harness.processes[0].received[0]["toolOverrides"], overlay)
            harness.processes[0].emit({"type": "final", "text": "ok"})
            drain(harness.bridge._active)
            harness.bridge.start_turn("pockpock-c1", "hello", "auto", selection={"toolOverrides": None})
            self.assertIsNone(harness.processes[1].received[0]["toolOverrides"], "null clears an earlier overlay")

    def test_select_tools_never_fails_a_turn(self):
        with tempfile.TemporaryDirectory() as directory:
            harness = BridgeHarness(directory)
            self.assertIsNone(harness.bridge.select_tools("pockpock-c1", "hi"), "no selector configured")

            class Broken:
                def select(self, session, message):
                    raise RuntimeError("boom")
            harness.bridge.tool_selector = Broken()
            self.assertIsNone(harness.bridge.select_tools("pockpock-c1", "hi"))

    def test_only_one_turn_runs_and_slot_frees_after_final(self):
        with tempfile.TemporaryDirectory() as directory:
            harness = BridgeHarness(directory)
            turn = harness.bridge.start_turn("pockpock-c1", "hello", "ask")
            with self.assertRaises(OpenClawError) as caught:
                harness.bridge.start_turn("pockpock-c2", "hello", "ask")
            self.assertEqual(caught.exception.code, "busy")
            self.assertEqual(caught.exception.status_code, 409)
            harness.processes[0].emit({"type": "final", "text": "done"})
            drain(turn)
            second = harness.bridge.start_turn("pockpock-c2", "hello", "ask")
            harness.processes[1].emit({"type": "final", "text": "done"})
            drain(second)

    def test_approval_is_relayed_only_while_pending(self):
        with tempfile.TemporaryDirectory() as directory:
            harness = BridgeHarness(directory)
            turn = harness.bridge.start_turn("pockpock-c1", "run it", "ask")
            process = harness.processes[0]
            with self.assertRaises(OpenClawError) as caught:
                harness.bridge.resolve_approval("plugin:nope", "allow-once")
            self.assertEqual(caught.exception.status_code, 404)
            process.emit({"type": "approval", "id": "plugin:1", "title": "Run command", "description": "hostname"})
            self.assertEqual(turn.next_event(5)["type"], "approval")
            with self.assertRaises(OpenClawError):
                harness.bridge.resolve_approval("plugin:1", "allow-always")
            harness.bridge.resolve_approval("plugin:1", "allow-once")
            self.assertEqual(process.received[-1], {"type": "approval", "id": "plugin:1", "decision": "allow-once"})
            process.emit({"type": "approval_resolved", "id": "plugin:1", "decision": "allow-once"})
            self.assertEqual(turn.next_event(5)["type"], "approval_resolved")
            with self.assertRaises(OpenClawError):
                harness.bridge.resolve_approval("plugin:1", "deny")
            # "Allow for this task" is relayed as allow-task; the turn keeps the grant (turn_helpers.grantKey).
            process.emit({"type": "approval", "id": "plugin:2", "title": "Run command", "description": "hostname"})
            self.assertEqual(turn.next_event(5)["type"], "approval")
            harness.bridge.resolve_approval("plugin:2", "allow-task")
            self.assertEqual(process.received[-1], {"type": "approval", "id": "plugin:2", "decision": "allow-task"})
            process.emit({"type": "final", "text": "ok"})
            drain(turn)
            with self.assertRaises(OpenClawError):
                harness.bridge.resolve_approval("plugin:1", "deny")

    def test_abort_tells_helper_and_frees_slot(self):
        with tempfile.TemporaryDirectory() as directory:
            harness = BridgeHarness(directory)
            turn = harness.bridge.start_turn("pockpock-c1", "long task", "full")
            harness.bridge.cancel_active()
            self.assertIn({"type": "abort"}, harness.processes[0].received)
            events = drain(turn)
            self.assertEqual(events[-1]["type"], "error")
            again = harness.bridge.start_turn("pockpock-c1", "next", "full")
            harness.processes[1].emit({"type": "final", "text": "ok"})
            drain(again)

    def test_helper_exit_without_result_reports_error(self):
        with tempfile.TemporaryDirectory() as directory:
            harness = BridgeHarness(directory)
            turn = harness.bridge.start_turn("pockpock-c1", "hello", "ask")
            process = harness.processes[0]
            process.emit_raw(b"not json\n")
            process.emit({"no": "type"})
            process.finish()
            events = drain(turn)
            self.assertEqual(len(events), 1)
            self.assertEqual(events[0]["code"], "bridge_failed")

    def test_invalid_input_never_spawns(self):
        with tempfile.TemporaryDirectory() as directory:
            harness = BridgeHarness(directory)
            for args in (("main", "hi", "ask"), ("pockpock-c1", "   ", "ask"), ("pockpock-c1", "hi", "root"),
                         ("pockpock-c1", "x" * (MAX_MESSAGE_CHARS + 1), "ask"), ("pockpock-c1", "a\x00b", "ask"),
                         ("pockpock-c1", "hi", "ask", "bad model; rm"), ("pockpock-c1", "hi", "ask", "x" * 101)):
                with self.assertRaises(OpenClawError):
                    harness.bridge.start_turn(*args)
            self.assertEqual(harness.processes, [])
            turn = harness.bridge.start_turn("pockpock-c1", "hi", "ask", "qwen3.5:27b")
            self.assertEqual(harness.processes[0].received[0]["model"], "qwen3.5:27b")
            harness.processes[0].emit({"type": "final", "text": "ok"})
            drain(turn)

    def test_unwritable_permission_state_stops_the_turn(self):
        with tempfile.TemporaryDirectory() as directory:
            harness = BridgeHarness(directory)
            blocker = Path(directory) / "blocker"
            blocker.write_text("file, not a folder", encoding="utf-8")
            harness.bridge.permissions = PermissionState(blocker / "permissions.json")
            with self.assertRaises(OpenClawError) as caught:
                harness.bridge.start_turn("pockpock-c1", "hi", "full")
            self.assertEqual(caught.exception.code, "permission_state")
            self.assertEqual(harness.processes, [])
            harness.bridge.permissions = harness.permissions
            turn = harness.bridge.start_turn("pockpock-c1", "hi", "full")
            harness.processes[0].emit({"type": "final", "text": "ok"})
            drain(turn)


class StatusTests(unittest.TestCase):
    def test_disabled_and_missing_node(self):
        with tempfile.TemporaryDirectory() as directory:
            harness = BridgeHarness(directory, enabled=False)
            status = harness.bridge.status()
            self.assertFalse(status["available"])
            self.assertEqual(harness.processes, [])
            with self.assertRaises(OpenClawError) as caught:
                harness.bridge.start_turn("pockpock-c1", "hi", "ask")
            self.assertEqual(caught.exception.code, "unavailable")
            missing = OpenClawBridge(OpenClawConfig(), spawn=harness._spawn, which=lambda name: None, helper_path=harness.helper)
            self.assertIn("Node.js", missing.status()["detail"])

    def test_status_reports_plugin_and_is_cached(self):
        with tempfile.TemporaryDirectory() as directory:
            harness = BridgeHarness(directory)
            original = harness._spawn

            def spawn(command):
                process = original(command)
                process.emit({"type": "status_result", "gateway": True, "plugin": len(harness.processes) > 1, "model": "ollama/qwen3.5:9b"})
                return process

            harness.bridge._spawn = spawn
            first = harness.bridge.status()
            self.assertTrue(first["ready"])
            self.assertFalse(first["plugin"])
            self.assertEqual(first["model"], "qwen3.5:9b")
            self.assertEqual(harness.processes[0].received[0], {"type": "start", "statusOnly": True})
            self.assertIs(harness.bridge.status(), first)
            refreshed = harness.bridge.status(force=True)
            self.assertTrue(refreshed["plugin"])
            self.assertEqual(refreshed["detail"], "Ready")

    def test_status_reports_gateway_offline(self):
        with tempfile.TemporaryDirectory() as directory:
            harness = BridgeHarness(directory)
            original = harness._spawn

            def spawn(command):
                process = original(command)
                process.emit({"type": "error", "code": "bridge_failed", "message": "The OpenClaw gateway is not running."})
                return process

            harness.bridge._spawn = spawn
            status = harness.bridge.status()
            self.assertTrue(status["available"])
            self.assertFalse(status["ready"])
            self.assertIn("not running", status["detail"])


if __name__ == "__main__":
    unittest.main()
