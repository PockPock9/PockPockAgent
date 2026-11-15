"""Connect to an MCP server once and list its tools, before it is saved for the agent.

This is the first point at which code from a pasted link runs, so it is called only after the
user has approved the exact command or address.
"""

from __future__ import annotations

import json
import os
import queue
import re
import shutil
import subprocess
import threading
import time
import urllib.error
import urllib.request
from typing import Any

PROTOCOL_VERSION = "2025-06-18"
STDIO_TIMEOUT_SECONDS = 150  # the first run of an npx or uvx server downloads the package
HTTP_TIMEOUT_SECONDS = 30
MAX_LINE_BYTES = 2 * 1024 * 1024
MAX_TOOLS = 200
CMD_UNSAFE = re.compile(r'[&|<>^%"!\r\n]')
CLIENT_INFO = {"name": "pockpock-extension-probe", "version": "1.0.0"}


class ProbeError(Exception):
    """The server could not be reached or did not speak MCP; the message is safe to show."""


def resolve_command(command: str) -> str:
    resolved = shutil.which(command)
    if not resolved:
        raise ProbeError(f"`{command}` is not installed on this PC, so this server cannot be started. Install it and try again.")
    return resolved


def check_arguments(resolved: str, args: list[str]) -> None:
    """Windows starts .cmd launchers through cmd.exe, which would interpret these characters."""
    if resolved.lower().endswith((".cmd", ".bat")):
        for arg in args:
            if CMD_UNSAFE.search(arg):
                raise ProbeError("One of the arguments contains a character (& | < > ^ % \" !) that cannot be passed safely to this launcher on Windows.")


def _tool_summaries(result: Any) -> list[dict[str, str]]:
    tools = result.get("tools") if isinstance(result, dict) else None
    if not isinstance(tools, list):
        raise ProbeError("The server answered but did not list any tools.")
    return [
        {"name": str(tool.get("name") or "")[:120], "description": " ".join(str(tool.get("description") or "").split())[:240]}
        for tool in tools[:MAX_TOOLS] if isinstance(tool, dict) and tool.get("name")
    ]


def _initialize_params() -> dict[str, Any]:
    return {"protocolVersion": PROTOCOL_VERSION, "capabilities": {}, "clientInfo": CLIENT_INFO}


def _kill(process: subprocess.Popen) -> None:
    if process.poll() is None:
        if os.name == "nt":
            # Launchers such as npx start the real server as a child, so end the whole tree.
            subprocess.run(["taskkill", "/PID", str(process.pid), "/T", "/F"], capture_output=True, check=False)
        else:
            process.kill()
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            pass
    for stream in (process.stdin, process.stdout, process.stderr):
        try:
            stream.close()
        except OSError:
            pass


def probe_stdio(command: str, args: list[str], env: dict[str, str], timeout: float = STDIO_TIMEOUT_SECONDS) -> list[dict[str, str]]:
    resolved = resolve_command(command)
    check_arguments(resolved, args)
    try:
        process = subprocess.Popen(
            [resolved, *args], stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            env={**os.environ, **env}, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except OSError as err:
        raise ProbeError(f"`{command}` could not be started on this PC.") from err
    lines: queue.Queue[bytes | None] = queue.Queue()
    errors: list[bytes] = []

    def read_stdout() -> None:
        for line in iter(lambda: process.stdout.readline(MAX_LINE_BYTES), b""):
            lines.put(line)
        lines.put(None)

    def read_stderr() -> None:
        for line in iter(lambda: process.stderr.readline(8192), b""):
            errors.append(line)
            del errors[:-20]

    threading.Thread(target=read_stdout, daemon=True).start()
    threading.Thread(target=read_stderr, daemon=True).start()
    deadline = time.monotonic() + timeout

    def send(message: dict[str, Any]) -> None:
        process.stdin.write(json.dumps(message).encode("utf-8") + b"\n")
        process.stdin.flush()

    def wait_for(request_id: int) -> Any:
        while True:
            try:
                line = lines.get(timeout=max(0.1, deadline - time.monotonic()))
            except queue.Empty:
                raise ProbeError("The server did not answer in time. It may still be downloading; try again in a minute.") from None
            if line is None:
                detail = b"".join(errors).decode("utf-8", "replace").strip()[-400:]
                raise ProbeError(f"The server stopped before answering.{' Its last output: ' + detail if detail else ''}")
            try:
                message = json.loads(line)
            except ValueError:
                continue  # launchers sometimes print banners on stdout
            if isinstance(message, dict) and message.get("id") == request_id:
                if "error" in message:
                    raise ProbeError("The server reported an error while connecting.")
                return message.get("result")

    try:
        send({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": _initialize_params()})
        wait_for(1)
        send({"jsonrpc": "2.0", "method": "notifications/initialized"})
        send({"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}})
        return _tool_summaries(wait_for(2))
    except (BrokenPipeError, OSError) as err:
        raise ProbeError("The server closed its input before PockPock could connect.") from err
    finally:
        _kill(process)


def _http_call(url: str, headers: dict[str, str], body: dict[str, Any], session: str = "") -> tuple[Any, str]:
    request = urllib.request.Request(url, data=json.dumps(body).encode("utf-8"), method="POST", headers={
        "Content-Type": "application/json",
        "Accept": "application/json, text/event-stream",
        "MCP-Protocol-Version": PROTOCOL_VERSION,
        "User-Agent": "local-mcp-client",
        **({"Mcp-Session-Id": session} if session else {}),
        **headers,
    })
    try:
        with urllib.request.urlopen(request, timeout=HTTP_TIMEOUT_SECONDS) as response:
            session = response.headers.get("Mcp-Session-Id", session) or ""
            content_type = response.headers.get("Content-Type", "")
            raw = response.read(MAX_LINE_BYTES).decode("utf-8", "replace")
    except urllib.error.HTTPError as err:
        if err.code in {401, 403}:
            raise ProbeError("The server requires sign-in or an access key. Add an Authorization header value and try again; servers that need browser sign-in (OAuth) are not supported yet.") from err
        raise ProbeError(f"The server refused the connection (HTTP {err.code}).") from err
    except (urllib.error.URLError, TimeoutError, OSError) as err:
        raise ProbeError("Could not reach the server at that address.") from err
    if "id" not in body:
        return None, session
    payloads = [raw]
    if "text/event-stream" in content_type:
        payloads = [line[5:].strip() for line in raw.splitlines() if line.startswith("data:")]
    for payload in payloads:
        try:
            message = json.loads(payload)
        except ValueError:
            continue
        if isinstance(message, dict) and message.get("id") == body["id"]:
            if "error" in message:
                raise ProbeError("The server reported an error while connecting.")
            return message.get("result"), session
    raise ProbeError("The address answered, but not as an MCP server.")


def probe_http(url: str, headers: dict[str, str]) -> list[dict[str, str]]:
    _, session = _http_call(url, headers, {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": _initialize_params()})
    _http_call(url, headers, {"jsonrpc": "2.0", "method": "notifications/initialized"}, session)
    result, _ = _http_call(url, headers, {"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}}, session)
    return _tool_summaries(result)
