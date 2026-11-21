import json
import threading
import unittest

from projects.nemoclaw_bridge.bridge import (
    MAX_MESSAGE_CHARS,
    STATUS_SCRIPT,
    TURN_SCRIPT,
    NemoClawBridge,
    NemoClawConfig,
    NemoClawError,
    build_command,
    build_environment,
    parse_status_output,
    parse_turn_output,
)


def turn_json(text="Hello", status="ok", model="qwen3.5:9b"):
    return json.dumps({
        "runId": "r1",
        "status": status,
        "summary": "completed",
        "result": {
            "payloads": [{"text": text, "mediaUrl": None}],
            "meta": {"durationMs": 1234, "agentMeta": {"model": model, "sessionId": "s1"}},
        },
    })


STATUS_TEXT = """
  Sandbox: pockpock
    Model:    qwen3.5:9b
    Provider: ollama-local
    Inference: healthy (http://host.openshell.internal:11434/v1/chat/completions)
    Agent:    OpenClaw v2026.10.5
  Name: pockpock
  Phase: \x1b[32mReady\x1b[39m
"""


class FakeRunner:
    def __init__(self, stdout="", code=0):
        self.stdout = stdout
        self.code = code
        self.calls = []

    def __call__(self, command, env, timeout):
        self.calls.append((command, env, timeout))
        return self.code, self.stdout, ""


class ConfigTests(unittest.TestCase):
    def test_defaults(self):
        config = NemoClawConfig.from_env({})
        self.assertEqual((config.sandbox, config.agent, config.distro, config.enabled), ("pockpock", "main", "", True))

    def test_rejects_unsafe_names(self):
        for key in ("POCKPOCK_NEMOCLAW_SANDBOX", "POCKPOCK_NEMOCLAW_AGENT", "POCKPOCK_NEMOCLAW_DISTRO"):
            with self.subTest(key=key), self.assertRaises(ValueError):
                NemoClawConfig.from_env({key: "bad name; rm -rf"})

    def test_timeout_is_clamped_and_can_disable(self):
        self.assertEqual(NemoClawConfig.from_env({"POCKPOCK_NEMOCLAW_TIMEOUT_SECONDS": "5"}).timeout_seconds, 30)
        self.assertEqual(NemoClawConfig.from_env({"POCKPOCK_NEMOCLAW_TIMEOUT_SECONDS": "99999"}).timeout_seconds, 900)
        self.assertFalse(NemoClawConfig.from_env({"POCKPOCK_NEMOCLAW_ENABLED": "0"}).enabled)


class CommandTests(unittest.TestCase):
    def test_command_uses_fixed_script_and_optional_distro(self):
        self.assertEqual(build_command(NemoClawConfig(), TURN_SCRIPT, "win32"), ["wsl.exe", "--exec", "/bin/bash", "-c", TURN_SCRIPT])
        self.assertEqual(build_command(NemoClawConfig(distro="Ubuntu-24.04"), STATUS_SCRIPT, "win32")[:3], ["wsl.exe", "-d", "Ubuntu-24.04"])

    def test_macos_runs_the_same_script_in_a_login_shell(self):
        self.assertEqual(build_command(NemoClawConfig(distro="Ubuntu-24.04"), TURN_SCRIPT, "darwin"), ["/bin/bash", "-lc", TURN_SCRIPT])

    def test_environment_forwards_values_and_keeps_existing_wslenv(self):
        env = build_environment({"NC_MESSAGE": "hi"}, {"WSLENV": "FOO/p:NC_MESSAGE/l"})
        self.assertEqual(env["NC_MESSAGE"], "hi")
        self.assertEqual(env["WSLENV"], "FOO/p:NC_MESSAGE/u")

    def test_user_text_never_reaches_argv(self):
        runner = FakeRunner(turn_json())
        bridge = NemoClawBridge(NemoClawConfig(), runner=runner)
        hostile = '"; rm -rf / #`whoami` $HOME'
        bridge.run_turn("pockpock-conv-1", hostile)
        command, env, timeout = runner.calls[0]
        self.assertTrue(all(hostile not in part for part in command))
        self.assertEqual(env["NC_MESSAGE"], hostile)
        self.assertEqual(env["NC_SESSION"], "pockpock-conv-1")
        self.assertIn("NC_MESSAGE/u", env["WSLENV"].split(":"))
        self.assertGreater(timeout, NemoClawConfig().timeout_seconds)


class ParseTests(unittest.TestCase):
    def test_parses_reply_after_banner_noise(self):
        result = parse_turn_output("[plugin] banner\n" + turn_json("All done"), 10)
        self.assertEqual((result.text, result.model, result.duration_ms, result.truncated), ("All done", "qwen3.5:9b", 1234, False))

    def test_flags_truncated_reply(self):
        result = parse_turn_output(turn_json("Partial ⚠️ Reply truncated at the model's output token limit."), 10)
        self.assertTrue(result.truncated)

    def test_error_status_raises_with_agent_text(self):
        with self.assertRaises(NemoClawError) as ctx:
            parse_turn_output(turn_json("The model reached its output token limit", status="error"), 10)
        self.assertEqual(ctx.exception.code, "turn_failed")
        self.assertIn("output token limit", str(ctx.exception))

    def test_missing_or_bad_json_raises(self):
        for output in ("no json here", "{not json"):
            with self.subTest(output=output), self.assertRaises(NemoClawError):
                parse_turn_output(output, 10)

    def test_status_parsing_strips_ansi(self):
        parsed = parse_status_output(STATUS_TEXT)
        self.assertTrue(parsed["ready"])
        self.assertEqual(parsed["model"], "qwen3.5:9b")
        self.assertEqual(parsed["agent_version"], "OpenClaw v2026.10.5")


class BridgeTests(unittest.TestCase):
    def test_validates_session_and_message(self):
        bridge = NemoClawBridge(NemoClawConfig(), runner=FakeRunner(turn_json()))
        with self.assertRaises(NemoClawError):
            bridge.run_turn("../etc", "hi")
        # Issue #75: the same pockpock-<id> contract as OpenClaw.
        with self.assertRaises(NemoClawError) as ctx:
            bridge.run_turn("bogus-123", "hi")
        self.assertEqual(ctx.exception.status_code, 422)
        with self.assertRaises(NemoClawError):
            bridge.run_turn("pockpock-ok", "   ")
        with self.assertRaises(NemoClawError) as ctx:
            bridge.run_turn("pockpock-ok", "x" * (MAX_MESSAGE_CHARS + 1))
        self.assertEqual(ctx.exception.status_code, 413)

    def test_rejects_concurrent_turn(self):
        started = threading.Event()
        release = threading.Event()

        def slow_runner(command, env, timeout):
            started.set()
            release.wait(5)
            return 0, turn_json(), ""

        bridge = NemoClawBridge(NemoClawConfig(), runner=slow_runner)
        worker = threading.Thread(target=bridge.run_turn, args=("pockpock-a", "first"))
        worker.start()
        started.wait(5)
        with self.assertRaises(NemoClawError) as ctx:
            bridge.run_turn("pockpock-b", "second")
        self.assertEqual(ctx.exception.code, "busy")
        release.set()
        worker.join(5)

    def test_failed_process_without_json_reports_actionable_error(self):
        bridge = NemoClawBridge(NemoClawConfig(), runner=FakeRunner("", code=1))
        with self.assertRaises(NemoClawError) as ctx:
            bridge.run_turn("pockpock-s", "hello")
        self.assertIn("nemoclaw pockpock status", str(ctx.exception))

    def test_status_without_probe_never_runs_the_sandbox_check(self):
        runner = FakeRunner(STATUS_TEXT)
        bridge = NemoClawBridge(NemoClawConfig(), runner=runner)
        unchecked = bridge.status(probe=False)
        self.assertEqual((unchecked["available"], unchecked["ready"], unchecked["checked"]), (True, False, False))
        self.assertEqual(len(runner.calls), 0)
        self.assertTrue(bridge.status()["ready"])
        self.assertTrue(bridge.status(probe=False)["ready"])  # a recent result is reused
        self.assertEqual(len(runner.calls), 1)

    def test_status_is_cached_until_forced(self):
        runner = FakeRunner(STATUS_TEXT)
        clock = [100.0]
        bridge = NemoClawBridge(NemoClawConfig(), runner=runner, clock=lambda: clock[0])
        self.assertTrue(bridge.status()["ready"])
        bridge.status()
        self.assertEqual(len(runner.calls), 1)
        bridge.status(force=True)
        self.assertEqual(len(runner.calls), 2)
        clock[0] += 60
        bridge.status()
        self.assertEqual(len(runner.calls), 3)

    def test_disabled_integration_skips_wsl(self):
        runner = FakeRunner(STATUS_TEXT)
        status = NemoClawBridge(NemoClawConfig(enabled=False), runner=runner).status()
        self.assertFalse(status["available"])
        self.assertEqual(runner.calls, [])


ROUTE_LOCAL = "Inference:\n\n  Workspace: default\n  Provider: compatible-endpoint\n  Model: qwen3.5:9b\n  Version: 1\n  Timeout: 180s\n\nSystem inference:\n\n  Not configured\n"
ROUTE_CLOUD = ROUTE_LOCAL.replace("compatible-endpoint", "pockpock-cloud").replace("qwen3.5:9b", "nim/meta/llama-3.3-70b-instruct")


class RouteRunner:
    """Answers ``openshell inference get`` from a mutable route and records every script."""

    def __init__(self, route=ROUTE_LOCAL, fail=None):
        self.route = route
        self.fail = fail
        self.calls = []

    def __call__(self, command, env, timeout):
        script = command[-1]
        self.calls.append((script, env))
        if self.fail and self.fail in script:
            return 1, "", "\x1b[31mError:\x1b[0m endpoint refused\n"
        if "inference set" in script:
            self.route = ROUTE_LOCAL.replace("compatible-endpoint", env["NC_PROVIDER"]).replace("qwen3.5:9b", env["NC_MODEL"])
        return 0, self.route if "inference get" in script else "", ""


class CloudModelTests(unittest.TestCase):
    def test_route_text_is_parsed_and_ignores_the_system_route(self):
        from projects.nemoclaw_bridge.bridge import parse_route_output
        self.assertEqual(parse_route_output(ROUTE_LOCAL), {"provider": "compatible-endpoint", "model": "qwen3.5:9b", "timeout": 180})
        self.assertEqual(parse_route_output("System inference:\n  Provider: x\n")["provider"], "")

    def test_switching_to_a_cloud_model_and_back(self):
        from projects.nemoclaw_bridge.bridge import CLOUD_BASE_URL, PROVIDER_SCRIPT, ROUTE_SET_SCRIPT
        saved = []
        runner = RouteRunner()
        bridge = NemoClawBridge(NemoClawConfig(distro="Ubuntu-24.04"), runner=runner, load_state=lambda: saved[-1] if saved else "", save_state=saved.append)
        self.assertEqual(bridge.route()["cloud"], False)

        result = bridge.set_model("nim/meta/llama-3.3-70b-instruct", token="local-token")
        self.assertEqual((result["cloud"], result["model"]), (True, "nim/meta/llama-3.3-70b-instruct"))
        self.assertEqual(result["local"]["model"], "qwen3.5:9b")
        self.assertEqual(json.loads(saved[-1]), {"provider": "compatible-endpoint", "model": "qwen3.5:9b", "timeout": 180})
        provider_script, provider_env = next(call for call in runner.calls if call[0] == PROVIDER_SCRIPT)
        self.assertEqual((provider_env["NC_TOKEN"], provider_env["NC_BASE_URL"]), ("local-token", CLOUD_BASE_URL))
        # The token travels in the environment; no script text or argument contains it.
        self.assertTrue(all("local-token" not in script for script, _ in runner.calls))
        self.assertIn("NC_TOKEN/u", provider_env["WSLENV"])

        # A second cloud model does not overwrite the remembered local route.
        bridge.set_model("openrouter/qwen/qwen3-coder", token="local-token")
        self.assertEqual(len(saved), 1)

        back = bridge.set_model("")
        self.assertEqual((back["cloud"], back["provider"], back["model"]), (False, "compatible-endpoint", "qwen3.5:9b"))
        _, restore_env = [call for call in runner.calls if call[0] == ROUTE_SET_SCRIPT][-1]
        self.assertEqual(restore_env["NC_ROUTE_TIMEOUT"], "180")
        self.assertIn("--no-verify", ROUTE_SET_SCRIPT)

    def test_bad_names_missing_token_and_failures_are_reported(self):
        bridge = NemoClawBridge(NemoClawConfig(), runner=RouteRunner())
        for bad in ("qwen3.5:9b", "nim/has space", "other/model", "nim/$(reboot)"):
            with self.assertRaises(NemoClawError) as caught:
                bridge.set_model(bad, token="t")
            self.assertEqual(caught.exception.code, "invalid_model")
        with self.assertRaises(NemoClawError) as caught:
            bridge.set_model("nim/meta/llama-3.3-70b-instruct")
        self.assertEqual(caught.exception.code, "cloud_not_ready")
        failing = NemoClawBridge(NemoClawConfig(), runner=RouteRunner(fail="provider"))
        with self.assertRaises(NemoClawError) as caught:
            failing.set_model("nim/meta/llama-3.3-70b-instruct", token="t")
        self.assertEqual(caught.exception.code, "provider_failed")
        self.assertIn("endpoint refused", str(caught.exception))
        # Already local: nothing is changed.
        idle = RouteRunner()
        NemoClawBridge(NemoClawConfig(), runner=idle).set_model("")
        self.assertTrue(all("inference set" not in script for script, _ in idle.calls))
        # In the cloud with no remembered local route: refuse instead of guessing.
        with self.assertRaises(NemoClawError) as caught:
            NemoClawBridge(NemoClawConfig(), runner=RouteRunner(route=ROUTE_CLOUD)).set_model("")
        self.assertEqual(caught.exception.code, "no_local_route")


if __name__ == "__main__":
    unittest.main()
