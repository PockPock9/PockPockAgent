"""One running MCP server behind the hub: a local process (stdio) or a remote address (streamable HTTP).

Clients never talk to the server directly. The hub sends their requests on with its own request ids,
so any number of clients (OpenClaw today; PockPock Agent and NemoClaw later) share one process.

Stdio: the process is started on first use and kept running. It is restarted on the next request
after it stops, unless it stopped three times within a minute; then it waits for a manual restart
(or one minute). Requests the server sends to its client are answered by the hub: ``ping``, and
``roots/list`` with no roots (the server gets the folders it may use from its arguments). Others
(sampling, elicitation) are refused, because the hub has no model or user to ask. Notifications the
server sends are not passed on; a changed tool list is picked up on the next ``tools/list``.

Remote: requests are posted to the address with the saved headers. The hub keeps one MCP session
with it and opens a new one when the server forgets it (HTTP 404).
"""

from __future__ import annotations

import collections
import concurrent.futures
import itertools
import json
import os
import subprocess
import threading
import time
import urllib.error
import urllib.request
from typing import Any

from projects.agent_extensions import mcp_probe

from .store import ServerSpec

PROTOCOL_VERSION = mcp_probe.PROTOCOL_VERSION
START_TIMEOUT_SECONDS = 150  # the first run of an npx or uvx server downloads the package
MAX_LINE_BYTES = 8 * 1024 * 1024
LOG_LINES = 200
CRASH_WINDOW_SECONDS = 60
CRASH_LIMIT = 3
CLIENT_INFO = {"name": "pockpock-local-mcp", "title": "PockPock Local MCP", "version": "1.0.0"}


class UpstreamError(Exception):
    """The server could not answer. ``rpc_code`` is set when the server itself returned a JSON-RPC error."""

    def __init__(self, message: str, *, rpc_code: int | None = None, data: Any = None):
        super().__init__(message)
        self.rpc_code = rpc_code
        self.data = data


def _initialize_params() -> dict[str, Any]:
    return {"protocolVersion": PROTOCOL_VERSION, "capabilities": {"roots": {"listChanged": False}}, "clientInfo": CLIENT_INFO}


class Upstream:
    """Common status for both kinds."""

    def __init__(self, spec: ServerSpec):
        self.spec = spec
        self.state = "stopped"  # stopped | starting | running | error
        self.detail = ""
        self.initialize_result: dict[str, Any] | None = None
        self.tool_count: int | None = None
        self.started_at: float | None = None
        self.log: collections.deque[str] = collections.deque(maxlen=LOG_LINES)
        self.calls = 0
        self.failures = 0

    def status(self) -> dict[str, Any]:
        return {"state": self.state, "detail": self.detail, "tools": self.tool_count, "started_at": self.started_at, "calls": self.calls, "failures": self.failures}

    def note(self, line: str) -> None:
        self.log.append(f"{time.strftime('%H:%M:%S')} {line.rstrip()[:2000]}")

    def ensure_started(self) -> dict[str, Any]:
        raise NotImplementedError

    def request(self, method: str, params: Any, timeout: float) -> Any:
        raise NotImplementedError

    def notify(self, method: str, params: Any = None) -> None:
        raise NotImplementedError

    def stop(self) -> None:
        raise NotImplementedError


class StdioUpstream(Upstream):
    def __init__(self, spec: ServerSpec):
        super().__init__(spec)
        self._process: subprocess.Popen | None = None
        self._lock = threading.RLock()
        self._write_lock = threading.Lock()
        self._ids = itertools.count(1)
        self._pending: dict[int, concurrent.futures.Future] = {}
        self._crashes: collections.deque[float] = collections.deque(maxlen=CRASH_LIMIT)
        self._stopping = False

    # ----- process -----

    def _alive(self) -> bool:
        return self._process is not None and self._process.poll() is None

    def ensure_started(self) -> dict[str, Any]:
        with self._lock:
            if self._alive() and self.initialize_result is not None:
                return self.initialize_result
            if len(self._crashes) == CRASH_LIMIT and time.monotonic() - self._crashes[0] < CRASH_WINDOW_SECONDS:
                raise UpstreamError(f"The server stopped {CRASH_LIMIT} times in a minute. {self.detail} Restart it on the MCP servers page after fixing the cause.".strip())
            self._start()
            return self.initialize_result or {}

    def _start(self) -> None:
        self.state, self.detail = "starting", ""
        self.initialize_result = None
        try:
            resolved = mcp_probe.resolve_command(self.spec.command)
            mcp_probe.check_arguments(resolved, list(self.spec.args))
            self._stopping = False
            self._process = subprocess.Popen(
                [resolved, *self.spec.args], stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                env={**os.environ, **self.spec.env}, cwd=os.path.expanduser("~"),
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
        except mcp_probe.ProbeError as err:
            self._fail(str(err))
            raise UpstreamError(str(err)) from err
        except OSError as err:
            self._fail(f"`{self.spec.command}` could not be started on this PC.")
            raise UpstreamError(self.detail) from err
        self.note(f"started: {self.spec.target()}")
        process = self._process
        threading.Thread(target=self._read_stdout, args=(process,), name=f"mcp-{self.spec.name}-out", daemon=True).start()
        threading.Thread(target=self._read_stderr, args=(process,), name=f"mcp-{self.spec.name}-err", daemon=True).start()
        try:
            result = self._call("initialize", _initialize_params(), START_TIMEOUT_SECONDS)
            self.notify("notifications/initialized")
            self.initialize_result = result if isinstance(result, dict) else {}
            listed = self._call("tools/list", {}, 60)
            self.tool_count = len(listed.get("tools") or []) if isinstance(listed, dict) else None
        except UpstreamError as err:
            last = self._last_output()
            self._fail(f"It did not start: {err}{' Last output: ' + last if last else ''}")
            self._kill()
            raise UpstreamError(self.detail) from err
        self.state, self.started_at = "running", time.time()

    def _last_output(self) -> str:
        """The most telling line the server printed: the last one naming an error, else the last one."""
        lines = [line[9:].strip() for line in self.log if line[9:].strip() and not line[9:].startswith(("stdout:", "started:", "It did not start", "The server stopped"))]
        errors = [line for line in lines if "error" in line.lower()]
        return (errors or lines or [""])[-1][:300]

    def _fail(self, detail: str) -> None:
        self.state, self.detail = "error", detail
        self.note(detail)

    def _read_stdout(self, process: subprocess.Popen) -> None:
        assert process.stdout is not None
        for line in iter(lambda: process.stdout.readline(MAX_LINE_BYTES), b""):
            try:
                message = json.loads(line)
            except ValueError:
                self.note(f"stdout: {line.decode('utf-8', 'replace')}")  # launchers print banners
                continue
            if isinstance(message, dict):
                self._dispatch(message)
        self._exited(process)

    def _read_stderr(self, process: subprocess.Popen) -> None:
        assert process.stderr is not None
        for line in iter(lambda: process.stderr.readline(8192), b""):
            self.note(line.decode("utf-8", "replace"))
        try:
            process.stderr.close()
        except OSError:
            pass

    def _dispatch(self, message: dict[str, Any]) -> None:
        if "method" in message:
            if "id" in message:  # a request from the server to its client
                method = message["method"]
                if method == "ping":
                    self._send({"jsonrpc": "2.0", "id": message["id"], "result": {}})
                elif method == "roots/list":
                    self._send({"jsonrpc": "2.0", "id": message["id"], "result": {"roots": []}})
                else:
                    self._send({"jsonrpc": "2.0", "id": message["id"], "error": {"code": -32601, "message": f"PockPock Local MCP does not support {method}."}})
            elif message.get("method") == "notifications/tools/list_changed":
                self.tool_count = None
            return
        future = self._pending.pop(message.get("id"), None) if isinstance(message.get("id"), int) else None
        if future is None or future.done():
            return
        if isinstance(message.get("error"), dict):
            error = message["error"]
            future.set_exception(UpstreamError(str(error.get("message") or "The server returned an error."), rpc_code=int(error.get("code") or -32603), data=error.get("data")))
        else:
            future.set_result(message.get("result"))

    def _exited(self, process: subprocess.Popen) -> None:
        if process is not self._process:
            return
        # Fail waiting requests first: a start in progress holds the lock while it waits for its reply.
        pending, self._pending = self._pending, {}
        for future in pending.values():
            if not future.done():
                future.set_exception(UpstreamError("The server stopped before answering."))
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            pass
        for stream in (process.stdin, process.stdout):
            try:
                stream.close()
            except (OSError, ValueError):
                pass
        with self._lock:
            if process is not self._process:
                return
            code = process.poll()
            last = self._last_output()
            if not self._stopping:
                self._crashes.append(time.monotonic())
                self.state = "error"
                self.detail = f"The server stopped (exit code {code}).{' Last output: ' + last if last else ''}"
                self.note(self.detail)
            elif self.state != "error":  # a failed start keeps its reason
                self.state, self.detail = "stopped", ""
            self.initialize_result = None

    def _kill(self) -> None:
        process = self._process
        if process is not None:
            self._stopping = True
            mcp_probe._kill(process)

    def stop(self) -> None:
        with self._lock:
            self._kill()
            self.state, self.detail = "stopped", ""
            self.initialize_result = None
            self.started_at = None

    # ----- messages -----

    def _send(self, message: dict[str, Any]) -> None:
        process = self._process
        if process is None or process.stdin is None:
            raise UpstreamError("The server is not running.")
        data = json.dumps(message, ensure_ascii=False).encode("utf-8") + b"\n"
        try:
            with self._write_lock:
                process.stdin.write(data)
                process.stdin.flush()
        except (BrokenPipeError, OSError, ValueError) as err:
            raise UpstreamError("The server closed its input.") from err

    def _call(self, method: str, params: Any, timeout: float) -> Any:
        request_id = next(self._ids)
        future: concurrent.futures.Future = concurrent.futures.Future()
        self._pending[request_id] = future
        message: dict[str, Any] = {"jsonrpc": "2.0", "id": request_id, "method": method}
        if params is not None:
            message["params"] = params
        try:
            self._send(message)
            return future.result(timeout=timeout)
        except concurrent.futures.TimeoutError:
            self._pending.pop(request_id, None)
            try:
                self.notify("notifications/cancelled", {"requestId": request_id, "reason": "PockPock stopped waiting"})
            except UpstreamError:
                pass
            raise UpstreamError(f"The server did not answer {method} within {int(timeout)} seconds.") from None
        finally:
            self._pending.pop(request_id, None)

    def request(self, method: str, params: Any, timeout: float) -> Any:
        self.ensure_started()
        self.calls += 1
        try:
            result = self._call(method, params, timeout)
        except UpstreamError as err:
            if err.rpc_code is None:
                self.failures += 1
            raise
        if method == "tools/list" and isinstance(result, dict) and "nextCursor" not in (params or {}):
            self.tool_count = len(result.get("tools") or [])
        return result

    def notify(self, method: str, params: Any = None) -> None:
        message: dict[str, Any] = {"jsonrpc": "2.0", "method": method}
        if params is not None:
            message["params"] = params
        self._send(message)


class HttpUpstream(Upstream):
    """A remote streamable-HTTP server. Stateless from the hub's side apart from the MCP session id."""

    def __init__(self, spec: ServerSpec, timeout: float = 30):
        super().__init__(spec)
        self._session = ""
        self._ids = itertools.count(1)
        self._lock = threading.Lock()
        self.timeout = timeout

    def _post(self, body: dict[str, Any], timeout: float) -> Any:
        request = urllib.request.Request(self.spec.url, data=json.dumps(body).encode("utf-8"), method="POST", headers={
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
            "MCP-Protocol-Version": PROTOCOL_VERSION,
            "User-Agent": "pockpock-local-mcp",
            **({"Mcp-Session-Id": self._session} if self._session else {}),
            **self.spec.headers,
        })
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                self._session = response.headers.get("Mcp-Session-Id", self._session) or ""
                content_type = response.headers.get("Content-Type", "")
                raw = response.read(MAX_LINE_BYTES).decode("utf-8", "replace")
        except urllib.error.HTTPError as err:
            if err.code == 404 and self._session:
                self._session = ""
                raise _SessionExpired() from err
            if err.code in {401, 403}:
                raise UpstreamError("The server refused the saved key or sign-in (HTTP %d). Connect it again with a new value." % err.code) from err
            raise UpstreamError(f"The server answered with HTTP {err.code}.") from err
        except (urllib.error.URLError, TimeoutError, OSError) as err:
            raise UpstreamError("The server could not be reached.") from err
        if "id" not in body:
            return None
        payloads = [line[5:].strip() for line in raw.splitlines() if line.startswith("data:")] if "text/event-stream" in content_type else [raw]
        for payload in payloads:
            try:
                message = json.loads(payload)
            except ValueError:
                continue
            if isinstance(message, dict) and message.get("id") == body["id"] and "method" not in message:
                if isinstance(message.get("error"), dict):
                    error = message["error"]
                    raise UpstreamError(str(error.get("message") or "The server returned an error."), rpc_code=int(error.get("code") or -32603), data=error.get("data"))
                return message.get("result")
        raise UpstreamError("The server's answer did not contain a reply.")

    def _call(self, method: str, params: Any, timeout: float) -> Any:
        body: dict[str, Any] = {"jsonrpc": "2.0", "id": next(self._ids), "method": method}
        if params is not None:
            body["params"] = params
        return self._post(body, timeout)

    def ensure_started(self) -> dict[str, Any]:
        with self._lock:
            if self.initialize_result is not None:
                return self.initialize_result
            self.state = "starting"
            try:
                result = self._call("initialize", _initialize_params(), self.timeout)
                self._post({"jsonrpc": "2.0", "method": "notifications/initialized"}, self.timeout)
            except (UpstreamError, _SessionExpired) as err:
                self.state, self.detail = "error", str(err) or "The server could not be reached."
                self.note(self.detail)
                raise UpstreamError(self.detail) from err
            self.initialize_result = result if isinstance(result, dict) else {}
            self.state, self.detail, self.started_at = "running", "", time.time()
            self.note(f"connected: {self.spec.url}")
            return self.initialize_result

    def request(self, method: str, params: Any, timeout: float) -> Any:
        self.ensure_started()
        self.calls += 1
        try:
            try:
                result = self._call(method, params, timeout)
            except _SessionExpired:
                with self._lock:
                    self.initialize_result = None
                self.ensure_started()
                result = self._call(method, params, timeout)
        except UpstreamError as err:
            if err.rpc_code is None:
                self.failures += 1
                self.note(str(err))
            raise
        if method == "tools/list" and isinstance(result, dict):
            self.tool_count = len(result.get("tools") or [])
        return result

    def notify(self, method: str, params: Any = None) -> None:
        body: dict[str, Any] = {"jsonrpc": "2.0", "method": method}
        if params is not None:
            body["params"] = params
        try:
            self._post(body, self.timeout)
        except (UpstreamError, _SessionExpired):
            pass

    def stop(self) -> None:
        with self._lock:
            self.initialize_result = None
            self._session = ""
            self.state, self.detail, self.started_at = "stopped", "", None


class _SessionExpired(Exception):
    pass


def make_upstream(spec: ServerSpec) -> Upstream:
    return StdioUpstream(spec) if spec.transport == "stdio" else HttpUpstream(spec)
