"""Local MCP hub: a real hub on a free port, with a stand-in stdio server (fake_server.py)."""

from __future__ import annotations

import json
import os
import shutil
import socket
import sys
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch

import uvicorn

from projects.mcp_hub import protect
from projects.mcp_hub.app import create_app
from projects.mcp_hub.hub import Hub
from projects.mcp_hub.store import ServerStore, StoreError, spec_from

FAKE = str(Path(__file__).with_name("fake_server.py"))
INTERNAL = "internal-token-for-tests"


def free_port() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


class Running:
    """A hub served by uvicorn in a thread."""

    def __init__(self, directory: Path):
        self.port = free_port()
        self.hub = Hub(ServerStore(directory), port=self.port)
        self.server = uvicorn.Server(uvicorn.Config(create_app(self.hub), host="127.0.0.1", port=self.port, log_level="error"))
        self.thread = threading.Thread(target=self.server.run, daemon=True)
        self.thread.start()
        for _ in range(200):
            if self.server.started:
                break
            time.sleep(0.05)
        self.base = f"http://127.0.0.1:{self.port}"

    def close(self):
        self.server.should_exit = True
        self.thread.join(timeout=10)

    def http(self, method: str, path: str, body: Any = None, headers: dict | None = None) -> tuple[int, Any]:
        request = urllib.request.Request(self.base + path, data=None if body is None else json.dumps(body).encode(), method=method,
                                         headers={"Content-Type": "application/json", **(headers or {})})
        try:
            with urllib.request.urlopen(request, timeout=60) as response:
                raw = response.read()
                return response.status, json.loads(raw) if raw else None
        except urllib.error.HTTPError as err:
            raw = err.read()
            return err.code, json.loads(raw) if raw else None

    def manage(self, method: str, path: str, body: Any = None) -> tuple[int, Any]:
        return self.http(method, path, body, {"X-PockPock-Internal-Token": INTERNAL})

    def rpc(self, name: str, method: str, params: Any = None, request_id: int = 1, token: str | None = None) -> tuple[int, Any]:
        body = {"jsonrpc": "2.0", "id": request_id, "method": method, **({"params": params} if params is not None else {})}
        return self.http("POST", f"/mcp/{name}", body, {"Authorization": f"Bearer {token or self.hub.token()}"})

    def call(self, name: str, tool: str, arguments: dict | None = None) -> dict:
        status, reply = self.rpc(name, "tools/call", {"name": tool, "arguments": arguments or {}})
        assert status == 200, (status, reply)
        return reply


from typing import Any  # noqa: E402


class HubTest(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp(prefix="mcp-hub-"))
        self.env = patch.dict(os.environ, {"POCKPOCK_INTERNAL_TOKEN": INTERNAL})
        self.env.start()
        self.hub = Running(self.dir)

    def tearDown(self):
        self.hub.hub.stop_all()
        self.hub.close()
        self.env.stop()
        shutil.rmtree(self.dir, ignore_errors=True)

    def add_fake(self, name="fake", **extra):
        status, reply = self.hub.manage("PUT", f"/servers/{name}", {"transport": "stdio", "command": sys.executable, "args": ["-u", FAKE], "env": {"FAKE_GREETING": "secret-hello"}, "source": "https://example.test/fake", **extra})
        self.assertEqual(status, 200, reply)
        return reply

    def test_management_needs_the_internal_token_and_mcp_needs_the_hub_token(self):
        self.assertEqual(self.hub.http("GET", "/health")[1], {"ok": True, "service": "mcp-hub"})
        self.assertEqual(self.hub.http("GET", "/servers")[0], 401)
        self.assertEqual(self.hub.http("PUT", "/servers/x", {"transport": "stdio", "command": "node"})[0], 401)
        reply = self.add_fake()
        client = reply["client"]
        self.assertEqual(client["url"], f"{self.hub.base}/mcp/fake")
        self.assertEqual(client["transport"], "streamable-http")
        self.assertEqual(client["headers"]["Authorization"], f"Bearer {self.hub.hub.token()}")
        self.assertEqual(self.hub.rpc("fake", "tools/list", {}, token="wrong")[0], 401)
        self.assertEqual(self.hub.http("POST", "/mcp/fake", {"jsonrpc": "2.0", "id": 1, "method": "ping"})[0], 401)
        self.assertEqual(self.hub.http("GET", "/mcp/fake")[0], 405)
        # The listing never contains a secret.
        listing = self.hub.manage("GET", "/servers")[1]
        self.assertNotIn("secret-hello", json.dumps(listing))
        self.assertEqual(listing["servers"][0]["env_keys"], ["FAKE_GREETING"])
        self.assertEqual(listing["servers"][0]["state"], "stopped", "nothing starts before a client asks")

    def test_a_client_session_through_the_hub(self):
        self.add_fake()
        status, reply = self.hub.rpc("fake", "initialize", {"protocolVersion": "2025-03-26", "capabilities": {}, "clientInfo": {"name": "t", "version": "1"}})
        self.assertEqual(status, 200)
        self.assertEqual(reply["result"]["protocolVersion"], "2025-03-26")
        self.assertEqual(reply["result"]["serverInfo"]["name"], "fake")
        self.assertEqual(reply["result"]["capabilities"]["tools"], {"listChanged": False})
        self.assertEqual(self.hub.http("POST", "/mcp/fake", {"jsonrpc": "2.0", "method": "notifications/initialized"}, {"Authorization": f"Bearer {self.hub.hub.token()}"})[0], 202)
        tools = self.hub.rpc("fake", "tools/list", {})[1]["result"]["tools"]
        self.assertEqual([tool["name"] for tool in tools], ["echo", "roots", "slow", "crash"])
        text = self.hub.call("fake", "echo", {"text": "hi"})["result"]["content"][0]["text"]
        self.assertTrue(text.startswith("hi|secret-hello|pid="), text)
        # The server's own error comes back as its JSON-RPC error.
        self.assertEqual(self.hub.rpc("fake", "tools/call", {"name": "nope"})[1]["error"]["code"], -32602)
        # A request from the server to its client is answered by the hub.
        roots = json.loads(self.hub.call("fake", "roots")["result"]["content"][0]["text"])
        self.assertEqual(roots["result"], {"roots": []})
        server = self.hub.manage("GET", "/servers")[1]["servers"][0]
        self.assertEqual((server["state"], server["tools"]), ("running", 4))
        log = self.hub.manage("GET", "/servers/fake/log")[1]["lines"]
        self.assertTrue(any("fake server starting" in line for line in log))
        self.assertFalse(any("secret-hello" in line for line in log))

    def test_clients_share_one_process_and_calls_run_together(self):
        self.add_fake()
        pid = self.hub.call("fake", "echo")["result"]["content"][0]["text"].split("pid=")[1]
        started = time.monotonic()
        with ThreadPoolExecutor(4) as pool:
            slow = [pool.submit(self.hub.call, "fake", "slow", {"seconds": 1}) for _ in range(1)]
            echoes = [pool.submit(self.hub.call, "fake", "echo", {"text": str(index)}) for index in range(3)]
            texts = [future.result()["result"]["content"][0]["text"] for future in echoes]
            self.assertEqual(slow[0].result()["result"]["content"][0]["text"], "done")
        self.assertTrue(all(text.endswith(f"pid={pid}") for text in texts), texts)
        self.assertEqual(sorted(text.split("|")[0] for text in texts), ["0", "1", "2"])
        self.assertLess(time.monotonic() - started, 5)

    def test_a_crashed_server_is_restarted_then_held_after_three_crashes(self):
        self.add_fake()
        first = self.hub.call("fake", "echo")["result"]["content"][0]["text"].split("pid=")[1]
        crashed = self.hub.call("fake", "crash")["result"]
        self.assertTrue(crashed["isError"])
        self.assertIn("could not run the tool", crashed["content"][0]["text"])
        server = self.hub.manage("GET", "/servers")[1]["servers"][0]
        self.assertEqual(server["state"], "error")
        self.assertIn("exit code 3", server["detail"])
        second = self.hub.call("fake", "echo")["result"]["content"][0]["text"].split("pid=")[1]
        self.assertNotEqual(first, second, "started again on the next request")
        self.hub.call("fake", "crash")
        self.hub.call("fake", "echo")
        self.hub.call("fake", "crash")
        held = self.hub.call("fake", "echo")["result"]
        self.assertTrue(held["isError"])
        self.assertIn("3 times in a minute", held["content"][0]["text"])
        restarted = self.hub.manage("POST", "/servers/fake/restart")[1]["server"]
        self.assertEqual(restarted["state"], "running")
        self.assertFalse(self.hub.call("fake", "echo")["result"].get("isError"))

    def test_switching_off_changing_and_removing(self):
        self.add_fake()
        pid = self.hub.call("fake", "echo")["result"]["content"][0]["text"].split("pid=")[1]
        self.assertEqual(self.hub.manage("POST", "/servers/fake/enabled", {"enabled": False})[1]["server"]["state"], "off")
        refused = self.hub.call("fake", "echo")["result"]
        self.assertIn("switched off", refused["content"][0]["text"])
        self.hub.manage("POST", "/servers/fake/enabled", {"enabled": True})
        # New settings: the process is replaced on next use.
        self.add_fake(env={"FAKE_GREETING": "changed"})
        text = self.hub.call("fake", "echo")["result"]["content"][0]["text"]
        self.assertIn("|changed|", text)
        self.assertNotIn(f"pid={pid}", text)
        self.assertEqual(self.hub.manage("DELETE", "/servers/fake")[1], {"removed": True})
        self.assertEqual(self.hub.rpc("fake", "tools/list", {})[1]["error"]["code"], -32002)
        self.assertEqual(self.hub.manage("GET", "/servers")[1], {"servers": []})

    def test_a_missing_command_is_explained(self):
        self.add_fake(name="broken", command="pockpock-no-such-launcher")
        reply = self.hub.rpc("broken", "initialize", {"protocolVersion": "2025-06-18"})[1]
        self.assertIn("not installed on this PC", reply["error"]["message"])
        self.assertEqual(self.hub.manage("GET", "/servers")[1]["servers"][0]["state"], "error")

    def test_a_server_that_fails_to_start_keeps_its_reason(self):
        self.hub.manage("PUT", "/servers/dies", {"transport": "stdio", "command": sys.executable, "args": ["-c", "import sys; print('Error: missing API key', file=sys.stderr); sys.exit(2)"]})
        server = self.hub.manage("POST", "/servers/dies/restart")[1]["server"]
        self.assertEqual(server["state"], "error")
        self.assertIn("missing API key", server["detail"])
        time.sleep(0.5)
        self.assertEqual(self.hub.manage("GET", "/servers")[1]["servers"][0]["state"], "error", "still error after the process is gone")

    def test_a_remote_server_is_reached_through_the_hub(self):
        # A second hub reaches the first one's server as a remote streamable-HTTP server.
        self.add_fake()
        other_dir = Path(tempfile.mkdtemp(prefix="mcp-hub-b-"))
        other = Running(other_dir)
        try:
            entry = self.hub.hub.client_entry("fake")
            status, reply = other.manage("PUT", "/servers/remote", {"transport": "streamable-http", "url": entry["url"], "headers": entry["headers"]})
            self.assertEqual(status, 200, reply)
            self.assertEqual(other.rpc("remote", "initialize", {"protocolVersion": "2025-06-18"})[1]["result"]["serverInfo"]["name"], "fake")
            self.assertIn("|secret-hello|", other.call("remote", "echo", {"text": "x"})["result"]["content"][0]["text"])
            other.manage("PUT", "/servers/bad", {"transport": "streamable-http", "url": entry["url"], "headers": {"Authorization": "Bearer wrong"}})
            self.assertIn("refused the saved key", other.rpc("bad", "tools/list", {})[1]["error"]["message"])
        finally:
            other.hub.stop_all()
            other.close()
            shutil.rmtree(other_dir, ignore_errors=True)


class StoreTest(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp(prefix="mcp-store-"))

    def tearDown(self):
        shutil.rmtree(self.dir, ignore_errors=True)

    def test_secrets_are_sealed_on_disk_and_read_back(self):
        store = ServerStore(self.dir)
        store.save(spec_from("gh", {"transport": "stdio", "command": "npx", "args": ["-y", "server"], "env": {"TOKEN": "ghp_secret"}}))
        store.save(spec_from("web", {"transport": "streamable-http", "url": "https://mcp.example.test/mcp", "headers": {"Authorization": "Bearer abc"}}))
        raw = (self.dir / "servers.json").read_text(encoding="utf-8")
        self.assertNotIn("ghp_secret", raw)
        self.assertNotIn("Bearer abc", raw)
        if protect.protected():
            self.assertIn("dpapi:", raw)
        loaded = ServerStore(self.dir).load()
        self.assertEqual(loaded["gh"].env, {"TOKEN": "ghp_secret"})
        self.assertEqual(loaded["web"].headers, {"Authorization": "Bearer abc"})
        self.assertEqual(loaded["gh"].target(), "npx -y server")
        token = store.token()
        self.assertGreaterEqual(len(token), 32)
        self.assertEqual(ServerStore(self.dir).token(), token)

    def test_a_secret_that_cannot_be_read_marks_the_server(self):
        store = ServerStore(self.dir)
        store.save(spec_from("gh", {"transport": "stdio", "command": "npx", "env": {"TOKEN": "x"}}))
        data = json.loads((self.dir / "servers.json").read_text(encoding="utf-8"))
        data["servers"]["gh"]["env"]["TOKEN"] = "dpapi:bm90LWEtcmVhbC1ibG9i" if protect.protected() else "unknown:x"
        (self.dir / "servers.json").write_text(json.dumps(data), encoding="utf-8")
        hub = Hub(ServerStore(self.dir), port=1)
        self.assertEqual(hub.describe("gh")["state"], "error")
        self.assertIn("cannot be read", hub.describe("gh")["detail"])
        reply = hub.handle("gh", {"jsonrpc": "2.0", "id": 1, "method": "tools/list"})
        self.assertIn("cannot be read", reply["error"]["message"])

    def test_definitions_are_checked(self):
        for name, data in [
            ("Bad Name", {"command": "npx"}),
            ("ok", {"transport": "sse", "url": "https://x.test"}),
            ("ok", {"command": ""}),
            ("ok", {"command": "npx", "args": [""]}),
            ("ok", {"command": "npx", "env": {"1BAD": "x"}}),
            ("ok", {"transport": "streamable-http", "url": "ftp://x"}),
            ("ok", {"transport": "streamable-http", "url": "https://x.test", "headers": {"X": "a\nb"}}),
        ]:
            with self.assertRaises(StoreError, msg=(name, data)):
                spec_from(name, data)


if __name__ == "__main__":
    unittest.main()
