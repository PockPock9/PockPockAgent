"""The agent loop: model -> tool calls (with approval) -> results -> model, until it answers.

Small local models need help to finish real work, so the loop adds guard rails:
- a repeated identical call is refused with a hint to change approach;
- a reply that stops while to-do items are open, or after edits that were never checked, is sent
  back once with a nudge to continue or check the work;
- old tool output is shortened when the context fills up, so long sessions keep working.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from typing import Protocol

from . import llm, tools
from .context import system_prompt

MAX_STEPS = 60


class UI(Protocol):
    def text(self, chunk: str) -> None: ...
    def thinking(self, chunk: str) -> None: ...
    def end_text(self) -> None: ...
    def tool_start(self, name: str, arguments: dict) -> None: ...
    def tool_result(self, name: str, arguments: dict, output: str, ok: bool) -> None: ...
    def approve(self, kind: str, summary: str, detail: str) -> str: ...  # "yes" | "no" | "always"
    def notice(self, message: str) -> None: ...


@dataclass
class Agent:
    ws: tools.Workspace
    model: str
    mode: str = "auto-edit"  # suggest | auto-edit | full-auto
    base: str = llm.DEFAULT_OLLAMA
    num_ctx: int = 32768
    think: bool = False
    messages: list[dict] = field(default_factory=list)
    always: set[str] = field(default_factory=set)
    usage: dict = field(default_factory=lambda: {"prompt": 0, "output": 0})

    def __post_init__(self) -> None:
        if not self.messages:
            self.messages = [{"role": "system", "content": system_prompt(self.ws, self.mode)}]

    def reset(self) -> None:
        self.messages = [{"role": "system", "content": system_prompt(self.ws, self.mode)}]
        self.ws.todos = []

    # ---------- approvals ----------
    def needs_approval(self, name: str, arguments: dict) -> str | None:
        if name in tools.READ_ONLY or self.mode == "full-auto":
            return None
        if name in tools.EDITS:
            return "edit" if self.mode == "suggest" and "edit" not in self.always else None
        if name == "run_command":
            command = str(arguments.get("command", "")).strip()
            if command in self.always or "command" in self.always:
                return None
            return "command"
        return None

    # ---------- context ----------
    def context_chars(self) -> int:
        return sum(len(str(m.get("content") or "")) + len(json.dumps(m.get("tool_calls") or "")) for m in self.messages)

    def compact(self, ui: UI | None = None, force: bool = False) -> bool:
        """Shorten old tool outputs (keeping the newest) when the context is near the model's window."""
        budget = int(self.num_ctx * 3.2 * 0.7)  # ~3.2 characters per token, keep 30% for the reply
        if not force and self.context_chars() < budget:
            return False
        keep = 8
        shortened = 0
        for message in self.messages[1:-keep]:
            content = str(message.get("content") or "")
            if message.get("role") == "tool" and len(content) > 400:
                message["content"] = content[:300] + f"\n[older output shortened; {len(content)} characters. Call the tool again if you need it.]"
                shortened += 1
        if self.context_chars() > budget and len(self.messages) > keep + 2:
            # Still too long: drop the oldest turns but keep the first request so the goal is not lost.
            first_user = next((m for m in self.messages if m.get("role") == "user"), None)
            tail = self.messages[-keep:]
            while tail and tail[0].get("role") == "tool":
                tail = tail[1:]
            note = {"role": "user", "content": "[Earlier steps were removed to save space. Files you changed: " + (", ".join(sorted(set(self.ws.changed))) or "none") + ". Continue the task.]"}
            self.messages = [self.messages[0]] + ([first_user] if first_user and first_user not in tail else []) + [note] + tail
            shortened += 1
        if shortened and ui:
            ui.notice("Context was getting full: older tool output was shortened.")
        return bool(shortened)

    # ---------- one request ----------
    def run(self, request: str, ui: UI) -> str:
        self.ws.begin_turn()
        self.messages.append({"role": "user", "content": request})
        seen: dict[str, int] = {}
        nudged_todo = nudged_check = False
        changed_since_check = False
        final = ""
        for _ in range(MAX_STEPS):
            self.compact(ui)
            reply = llm.chat(self.messages, model=self.model, tools=tools.TOOLS, base=self.base, num_ctx=self.num_ctx, think=self.think,
                             on_text=ui.text, on_thinking=ui.thinking)
            ui.end_text()
            self.usage["prompt"] = reply.prompt_tokens
            self.usage["output"] += reply.output_tokens
            assistant = {"role": "assistant", "content": reply.content}
            if reply.tool_calls:
                assistant["tool_calls"] = [{"function": {"name": c.name, "arguments": c.arguments}} for c in reply.tool_calls]
            self.messages.append(assistant)
            if not reply.tool_calls:
                final = reply.content.strip()
                open_items = [t for t in self.ws.todos if t["status"] != "done"]
                if open_items and not nudged_todo and not final.rstrip().endswith("?"):
                    nudged_todo = True
                    self.messages.append({"role": "user", "content": f"Your to-do list still has {len(open_items)} open item(s): " + "; ".join(t["task"] for t in open_items[:5]) + ". Continue with them, or mark them done if they are finished."})
                    continue
                if changed_since_check and not nudged_check and not final.rstrip().endswith("?"):
                    nudged_check = True
                    self.messages.append({"role": "user", "content": "You changed files but did not run any check since. If the project has tests, a build, a type check or a linter, run it now and fix failures. If there is nothing to run, reply with your summary."})
                    continue
                if not final:
                    final = "(The model ended without a reply.)"
                return final
            for call in reply.tool_calls:
                key = call.name + json.dumps(call.arguments, sort_keys=True)
                seen[key] = seen.get(key, 0) + 1
                ui.tool_start(call.name, call.arguments)
                if seen[key] >= 3 and call.name not in ("run_command", "todo_write"):
                    output, ok = f"You already called {call.name} with these exact arguments {seen[key] - 1} times and got the same result. Do something different: use the result you have, read another part, or change approach.", False
                else:
                    output, ok = self._execute(call, ui)
                if ok and call.name in tools.EDITS:
                    changed_since_check = True
                if ok and call.name == "run_command":
                    changed_since_check = False
                ui.tool_result(call.name, call.arguments, output, ok)
                self.messages.append({"role": "tool", "content": output, "tool_name": call.name})
        ui.notice(f"Stopped after {MAX_STEPS} steps. Say 'continue' to keep going.")
        return final

    def _execute(self, call: llm.ToolCall, ui: UI) -> tuple[str, bool]:
        kind = self.needs_approval(call.name, call.arguments)
        if kind:
            summary = call.arguments.get("command") if kind == "command" else call.arguments.get("path", "")
            detail = call.arguments.get("new_text") or call.arguments.get("content") or ""
            answer = ui.approve(kind, str(summary), str(detail))
            if answer == "always":
                self.always.add("command" if kind == "command" else "edit")
            elif answer != "yes":
                return f"The user declined this {kind}. Do not retry it; choose another way or ask the user.", False
        started = time.time()
        try:
            output = tools.call(self.ws, call.name, call.arguments)
            return output, not output.startswith("Exit code ") or output.startswith("Exit code 0")
        except tools.ToolError as err:
            return f"Error: {err}", False
        except Exception as err:  # A tool bug is reported to the model, never crashes the session.
            return f"Error: {type(err).__name__}: {err} (after {time.time() - started:.1f} s)", False
