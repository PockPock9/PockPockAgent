#!/usr/bin/env python3
"""Measure tok/s, time-to-first-token, and first-tool-call accuracy of a local
OpenAI-compatible server (Ollama, llama-server, or FreeToken).

Usage (from the repo root):

    python3 docs/experiments/measure-tool-calls.py \
        --base-url http://127.0.0.1:11434/v1 --model qwen3.5:2b

    python3 docs/experiments/measure-tool-calls.py \
        --base-url http://127.0.0.1:1919/v1 --model Qwen3.6-35B-A3B \
        --out freetoken-qwen36.json

The script sends a fixed set of small tasks with a fixed tool list (same
order, same schemas, every run, so runs are comparable), streams each reply,
and scores only the FIRST tool call: the right function, valid JSON
arguments, and the right argument values. It does not execute tools and
does not score multi-turn task completion — a model can pass here and still
fail a long agent run, so treat this as a smoke measurement, not a full
agent evaluation. See docs/experiments/README.md.

One long plain-text task is included so the script also yields a real
decode rate: tool calls stream as a single chunk once generation is
done, so no tok/s can be measured from them, and tok/s is reported
only for that text task. See docs/experiments/README.md.

Stdlib only. Exits 0 when every task passes, 1 otherwise.
"""

from __future__ import annotations

import argparse
import ast
import json
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone


TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "calculator",
            "description": "Evaluate one arithmetic expression and return the number.",
            "parameters": {
                "type": "object",
                "properties": {
                    "expression": {
                        "type": "string",
                        "description": "Arithmetic expression, e.g. '17 * 23'.",
                    },
                },
                "required": ["expression"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "write_file",
            "description": "Save a text file at the given relative path.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string"},
                    "content": {"type": "string"},
                },
                "required": ["path", "content"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "read_file",
            "description": "Read a text file at the given relative path.",
            "parameters": {
                "type": "object",
                "properties": {"path": {"type": "string"}},
                "required": ["path"],
            },
        },
    },
]

TASKS = [
    {
        "id": "calc-mul",
        "prompt": "What is 17 multiplied by 23? Use the calculator tool.",
        "expect_function": "calculator",
        "expect_eval": 391,
    },
    {
        "id": "calc-convert",
        "prompt": "What is 42 degrees Celsius in Fahrenheit? Use the calculator tool.",
        "expect_function": "calculator",
        "expect_eval": 107.6,
    },
    {
        "id": "write-file",
        "prompt": "Save a file called hello.txt containing exactly the words hello world. Use the write_file tool.",
        "expect_function": "write_file",
        "expect_args": {"path": "hello.txt", "content": "hello world"},
    },
    {
        "id": "read-file",
        "prompt": "Read the file config.json and report its contents. Use the read_file tool.",
        "expect_function": "read_file",
        "expect_args": {"path": "config.json"},
    },
    {
        "id": "calc-sum",
        "prompt": "Add 148 and 276 using the calculator tool.",
        "expect_function": "calculator",
        "expect_eval": 424,
    },
    {
        "id": "write-report",
        "prompt": "Save a file called report.md containing the single line Weekly report. Use the write_file tool.",
        "expect_function": "write_file",
        "expect_args": {"path": "report.md", "content": "Weekly report"},
    },
    {
        "id": "plain-fact",
        "prompt": "What is the capital of France? Answer in plain text without calling any tool.",
        "expect_function": None,
        "expect_text_contains": "Paris",
    },
    {
        "id": "calc-div",
        "prompt": "Divide 100 by 4 using the calculator tool.",
        "expect_function": "calculator",
        "expect_eval": 25,
    },
    {
        # Long plain-text reply: the only task that yields a measurable
        # decode rate, since tool calls stream as a single chunk.
        "id": "explain-sky",
        "prompt": "Write a short paragraph of about 120 words explaining why the sky is blue. Answer in plain text without calling any tool.",
        "expect_function": None,
        "expect_text_contains": "sky",
    },
]


def safe_eval(expression: str) -> float:
    """Evaluate a plain arithmetic expression; anything else raises ValueError."""
    tree = ast.parse(expression, mode="eval")
    allowed = (
        ast.Expression, ast.BinOp, ast.UnaryOp, ast.Constant,
        ast.Add, ast.Sub, ast.Mult, ast.Div, ast.Mod, ast.Pow, ast.USub,
    )
    for node in ast.walk(tree):
        if not isinstance(node, allowed):
            raise ValueError(f"unsupported node {type(node).__name__}")
        if isinstance(node, ast.Constant) and not isinstance(node.value, (int, float)):
            raise ValueError("only numbers allowed")

    def _eval(node):
        if isinstance(node, ast.Expression):
            return _eval(node.body)
        if isinstance(node, ast.Constant):
            return node.value
        if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.USub):
            return -_eval(node.operand)
        if isinstance(node, ast.BinOp):
            left, right = _eval(node.left), _eval(node.right)
            if isinstance(node.op, ast.Add):
                return left + right
            if isinstance(node.op, ast.Sub):
                return left - right
            if isinstance(node.op, ast.Mult):
                return left * right
            if isinstance(node.op, ast.Div):
                return left / right
            if isinstance(node.op, ast.Mod):
                return left % right
            if isinstance(node.op, ast.Pow):
                return left ** right
        raise ValueError("unsupported expression")

    return float(_eval(tree))


def run_task(base_url: str, model: str, task: dict, timeout: int) -> dict:
    """Stream one chat completion and score its first tool call."""
    payload = {
        "model": model,
        "messages": [{"role": "user", "content": task["prompt"]}],
        "tools": TOOLS,
        "temperature": 0,
        "max_tokens": 512,
        "stream": True,
        "stream_options": {"include_usage": True},
        # Qwen models think by default and can return an empty reply on a
        # tool turn; think off keeps the turn on the tool call.
        "think": False,
    }
    request = urllib.request.Request(
        f"{base_url.rstrip('/')}/chat/completions",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    started = time.monotonic()
    first_token_at: float | None = None
    content = ""
    tool_name: str | None = None
    tool_args = ""
    usage: dict | None = None
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            for raw in response:
                line = raw.decode("utf-8", errors="replace").strip()
                if not line.startswith("data:"):
                    continue
                data = line[5:].strip()
                if data == "[DONE]":
                    break
                try:
                    chunk = json.loads(data)
                except json.JSONDecodeError:
                    continue
                if chunk.get("usage"):
                    usage = chunk["usage"]
                choices = chunk.get("choices") or []
                if not choices:
                    continue
                delta = choices[0].get("delta") or {}
                if first_token_at is None and (delta.get("content") or delta.get("tool_calls")):
                    first_token_at = time.monotonic()
                if isinstance(delta.get("content"), str):
                    content += delta["content"]
                for call in delta.get("tool_calls") or []:
                    function = call.get("function") or {}
                    if function.get("name"):
                        tool_name = function["name"]
                    if isinstance(function.get("arguments"), str):
                        tool_args += function["arguments"]
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError) as err:
        return {"id": task["id"], "passed": False, "error": f"request failed: {err}"}
    total_s = time.monotonic() - started
    ttft_s = (first_token_at - started) if first_token_at is not None else None

    result: dict = {
        "id": task["id"],
        "ttft_s": round(ttft_s, 3) if ttft_s is not None else None,
        "total_s": round(total_s, 3),
        "called_function": tool_name,
        "content": content[:200],
    }
    if usage and usage.get("completion_tokens"):
        decode_s = total_s - (ttft_s or 0)
        # tok/s is only measurable for plain-text replies that stream token
        # by token. A tool call streams as a single chunk once generation
        # is done, so (tokens / time-after-first-chunk) would read as
        # hundreds of tok/s on any hardware — it is not a decode rate.
        # Tool-call tasks are therefore scored on TTFT and accuracy, not
        # speed; use a long text prompt for raw speed.
        if tool_name is None and content and decode_s > 0 and usage["completion_tokens"] >= 20:
            result["completion_tokens"] = usage["completion_tokens"]
            result["tok_per_s"] = round(usage["completion_tokens"] / decode_s, 1)
    if "tok_per_s" not in result:
        result["tok_per_s"] = None

    expected = task["expect_function"]
    if expected is None:
        ok = tool_name is None and task["expect_text_contains"] in content
        result["detail"] = "no tool call, answer contains expected text" if ok else (
            f"expected plain answer, got tool call {tool_name!r} / {content[:80]!r}"
        )
        result["passed"] = ok
        return result
    if tool_name is None:
        result["passed"] = False
        result["detail"] = f"expected tool call {expected!r}, model answered in text: {content[:120]!r}"
        return result
    if tool_name != expected:
        result["passed"] = False
        result["detail"] = f"called {tool_name!r}, expected {expected!r}"
        return result
    try:
        args = json.loads(tool_args) if tool_args.strip() else {}
    except json.JSONDecodeError:
        result["passed"] = False
        result["detail"] = f"tool arguments are not valid JSON: {tool_args[:120]!r}"
        return result
    result["arguments"] = args
    if "expect_args" in task:
        ok = args == task["expect_args"]
        result["detail"] = "arguments match" if ok else f"arguments {args} != expected {task['expect_args']}"
        result["passed"] = ok
        return result
    if "expect_eval" in task:
        try:
            value = safe_eval(str(args.get("expression", "")))
        except (ValueError, SyntaxError, ZeroDivisionError):
            result["passed"] = False
            result["detail"] = f"expression not evaluable: {args.get('expression')!r}"
            return result
        ok = abs(value - task["expect_eval"]) < 1e-6
        result["detail"] = f"expression = {value}" if ok else f"expression = {value}, expected {task['expect_eval']}"
        result["passed"] = ok
        return result
    result["passed"] = True
    result["detail"] = "tool called"
    return result


def warm_up(base_url: str, model: str, timeout: int) -> None:
    """Load the model with one throwaway token so the measured TTFTs are
    warm. Without this the first task's TTFT includes the model load,
    which is not comparable across runs."""
    payload = {
        "model": model,
        "messages": [{"role": "user", "content": "Reply with the single word ok."}],
        "temperature": 0,
        "max_tokens": 1,
        "stream": False,
        "think": False,
    }
    request = urllib.request.Request(
        f"{base_url.rstrip('/')}/chat/completions",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            response.read()
        print("Warmed up (model loaded).", flush=True)
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError) as err:
        print(f"Warm-up failed ({err}); continuing — first TTFT will include the load.", flush=True)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", required=True,
                        help="OpenAI-compatible base URL, e.g. http://127.0.0.1:11434/v1")
    parser.add_argument("--model", required=True, help="Model name as the server reports it")
    parser.add_argument("--limit", type=int, default=0,
                        help="Run only the first N tasks (0 = all)")
    parser.add_argument("--timeout", type=int, default=300, help="Seconds per task")
    parser.add_argument("--out", default="", help="Write the JSON results here")
    parser.add_argument("--no-warmup", action="store_true",
                        help="Skip the warm-up call (first TTFT then includes the model load)")
    args = parser.parse_args()

    if not args.no_warmup:
        warm_up(args.base_url, args.model, args.timeout)
    tasks = TASKS[: args.limit] if args.limit > 0 else TASKS
    results = []
    for task in tasks:
        print(f"[{task['id']}] {task['prompt'][:60]}...", flush=True)
        result = run_task(args.base_url, args.model, task, args.timeout)
        results.append(result)
        status = "PASS" if result["passed"] else "FAIL"
        detail = result.get("detail") or result.get("error", "")
        ttft = f"ttft={result['ttft_s']}s " if result.get("ttft_s") is not None else ""
        tps = f"{result['tok_per_s']} tok/s" if result.get("tok_per_s") else "tok/s n/a"
        print(f"  {status} {ttft}{tps} — {detail}", flush=True)

    passed = sum(1 for r in results if r["passed"])
    ttfts = [r["ttft_s"] for r in results if r.get("ttft_s") is not None]
    speeds = [r["tok_per_s"] for r in results if r.get("tok_per_s")]
    summary = {
        "base_url": args.base_url,
        "model": args.model,
        "measured_at": datetime.now(timezone.utc).isoformat(),
        "tasks_run": len(results),
        "tasks_passed": passed,
        "mean_ttft_s": round(sum(ttfts) / len(ttfts), 3) if ttfts else None,
        "mean_tok_per_s": round(sum(speeds) / len(speeds), 1) if speeds else None,
        "results": results,
    }
    print(f"\n{passed}/{len(results)} tasks passed; "
          f"mean TTFT {summary['mean_ttft_s']}s; mean {summary['mean_tok_per_s']} tok/s")
    out = args.out or (
        f"measure-{args.model.replace('/', '_').replace(':', '-')}-"
        f"{datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S')}.json"
    )
    with open(out, "w", encoding="utf-8") as handle:
        json.dump(summary, handle, indent=2)
    print(f"Results written to {out}")
    return 0 if passed == len(results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
