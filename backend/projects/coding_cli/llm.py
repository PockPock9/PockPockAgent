"""Streaming chat client for Ollama with tool calls, built for small local models.

Local models sometimes write a tool call as text instead of using the tool-call channel
(``<tool_call>{...}</tool_call>``, a fenced JSON block, or a bare ``{"name": ..., "arguments": ...}``);
:func:`text_tool_calls` recovers those so the turn is not lost.
"""

from __future__ import annotations

import json
import re
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from typing import Callable, Iterator

DEFAULT_OLLAMA = "http://127.0.0.1:11434"
# Preferred coding models, best first, among those that fit a 12 GB GPU or run well partly on CPU.
PREFERRED_MODELS = (
    "qwen3.5:9b", "qwen3.8:27b", "qwen3.5:27b", "qwen3.6:35b-a3b", "qwen2.5-coder:14b-agent", "qwen2.5-coder:14b",
    "qwen2.5-coder:7b", "qwen2.5:7b",
)


class ModelError(RuntimeError):
    pass


@dataclass
class ToolCall:
    name: str
    arguments: dict
    id: str = ""


@dataclass
class Reply:
    content: str = ""
    thinking: str = ""
    tool_calls: list[ToolCall] = field(default_factory=list)
    prompt_tokens: int = 0
    output_tokens: int = 0
    done_reason: str = ""


def list_models(base: str = DEFAULT_OLLAMA) -> list[str]:
    try:
        with urllib.request.urlopen(base + "/api/tags", timeout=5) as response:
            return [item["name"] for item in json.loads(response.read().decode()).get("models", [])]
    except (urllib.error.URLError, OSError, ValueError) as err:
        raise ModelError(f"Ollama is not reachable at {base}. Start Ollama (or PockPock), then try again. ({err})") from err


def pick_model(available: list[str], wanted: str | None = None) -> str:
    if wanted:
        if wanted in available or f"{wanted}:latest" in available:
            return wanted
        raise ModelError(f"The model {wanted} is not installed. Installed: {', '.join(available) or 'none'}. Run: ollama pull {wanted}")
    for name in PREFERRED_MODELS:
        if name in available:
            return name
    chat = [name for name in available if not re.search(r"embed|llava|vision", name)]
    if not chat:
        raise ModelError("No chat model is installed in Ollama. Run: ollama pull qwen3.5:9b")
    return chat[0]


_TAGGED = re.compile(r"<tool_call>\s*(\{.*?\})\s*</tool_call>", re.S)
_FENCED = re.compile(r"```(?:json|tool_call)?\s*(\{.*?\})\s*```", re.S)


def _as_call(blob: str, names: set[str]) -> ToolCall | None:
    try:
        data = json.loads(blob)
    except ValueError:
        return None
    if not isinstance(data, dict):
        return None
    name = data.get("name") or (data.get("function") or {}).get("name")
    arguments = data.get("arguments", data.get("parameters", (data.get("function") or {}).get("arguments", {})))
    if isinstance(arguments, str):
        try:
            arguments = json.loads(arguments)
        except ValueError:
            return None
    if name in names and isinstance(arguments, dict):
        return ToolCall(name=name, arguments=arguments)
    return None


def text_tool_calls(content: str, names: set[str]) -> tuple[list[ToolCall], str]:
    """Tool calls written as text, and the content with them removed."""
    calls: list[ToolCall] = []
    remaining = content
    for pattern in (_TAGGED, _FENCED):
        for match in pattern.finditer(content):
            call = _as_call(match.group(1), names)
            if call:
                calls.append(call)
                remaining = remaining.replace(match.group(0), "")
        if calls:
            return calls, remaining.strip()
    stripped = content.strip()
    if stripped.startswith("{") and stripped.endswith("}"):
        call = _as_call(stripped, names)
        if call:
            return [call], ""
    return [], content


def chat(
    messages: list[dict],
    *,
    model: str,
    tools: list[dict],
    base: str = DEFAULT_OLLAMA,
    num_ctx: int = 32768,
    think: bool = False,
    on_text: Callable[[str], None] | None = None,
    on_thinking: Callable[[str], None] | None = None,
    timeout: float = 600,
) -> Reply:
    body = {
        "model": model, "messages": messages, "tools": tools, "stream": True, "think": think,
        "options": {"num_ctx": num_ctx, "temperature": 0.2, "top_p": 0.9},
        "keep_alive": "15m",
    }
    request = urllib.request.Request(base + "/api/chat", data=json.dumps(body).encode(), headers={"Content-Type": "application/json"}, method="POST")
    reply = Reply()
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            for line in _lines(response):
                chunk = json.loads(line)
                if chunk.get("error"):
                    raise ModelError(str(chunk["error"]))
                message = chunk.get("message") or {}
                if message.get("thinking"):
                    reply.thinking += message["thinking"]
                    if on_thinking:
                        on_thinking(message["thinking"])
                if message.get("content"):
                    reply.content += message["content"]
                    if on_text:
                        on_text(message["content"])
                for call in message.get("tool_calls") or []:
                    function = call.get("function") or {}
                    arguments = function.get("arguments") or {}
                    if isinstance(arguments, str):
                        try:
                            arguments = json.loads(arguments)
                        except ValueError:
                            arguments = {"_raw": arguments}
                    reply.tool_calls.append(ToolCall(name=function.get("name", ""), arguments=arguments, id=call.get("id", "")))
                if chunk.get("done"):
                    reply.prompt_tokens = chunk.get("prompt_eval_count") or 0
                    reply.output_tokens = chunk.get("eval_count") or 0
                    reply.done_reason = chunk.get("done_reason") or ""
    except urllib.error.HTTPError as err:
        detail = err.read().decode(errors="replace")[:400]
        if "does not support tools" in detail:
            raise ModelError(f"{model} cannot call tools, so it cannot work as a coding agent. Choose another model with /model.") from err
        raise ModelError(f"The model request failed (HTTP {err.code}): {detail}") from err
    except (urllib.error.URLError, OSError) as err:
        raise ModelError(f"Lost the connection to Ollama: {err}") from err
    if not reply.tool_calls and reply.content:
        names = {tool["function"]["name"] for tool in tools}
        calls, rest = text_tool_calls(reply.content, names)
        if calls:
            reply.tool_calls, reply.content = calls, rest
    return reply


def _lines(response) -> Iterator[str]:
    buffer = b""
    while True:
        chunk = response.read1(65536) if hasattr(response, "read1") else response.read(65536)
        if not chunk:
            break
        buffer += chunk
        while b"\n" in buffer:
            line, buffer = buffer.split(b"\n", 1)
            if line.strip():
                yield line.decode("utf-8", errors="replace")
    if buffer.strip():
        yield buffer.decode("utf-8", errors="replace")
