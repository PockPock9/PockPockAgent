"""Terminal output for PockPock Code: streamed replies, one line per tool call, coloured diffs, approvals."""

from __future__ import annotations

import sys

try:  # rich is optional: without it the output is plain text.
    from rich.console import Console
    from rich.markdown import Markdown
    from rich.syntax import Syntax
    from rich.text import Text
except ImportError:  # pragma: no cover - exercised when rich is missing
    Console = None


def _short(arguments: dict) -> str:
    for key in ("command", "path", "pattern"):
        if arguments.get(key):
            value = str(arguments[key]).replace("\n", " ")
            extra = ""
            if key == "path" and arguments.get("start_line"):
                extra = f" ({arguments['start_line']}-{arguments.get('end_line', '')})"
            return (value[:110] + "…" if len(value) > 110 else value) + extra
    if arguments.get("items"):
        return f"{len(arguments['items'])} items"
    return ""


LABELS = {"list_files": "List", "search": "Search", "read_file": "Read", "edit_file": "Edit", "write_file": "Write", "run_command": "Run", "todo_write": "Plan"}


class TerminalUI:
    def __init__(self, quiet: bool = False, show_thinking: bool = False) -> None:
        self.console = Console(highlight=False, soft_wrap=True) if Console else None
        self.quiet = quiet
        self.show_thinking = show_thinking
        self.streamed = ""
        self.streamed_any = False
        self.thinking_open = False

    # ---------- plain helpers ----------
    def _print(self, message: str = "", style: str | None = None) -> None:
        if self.console:
            # Text, never markup: "[name]" in help or file paths must print as written.
            self.console.print(Text(message, style=style or ""))
        else:
            print(message, flush=True)

    def banner(self, model: str, root: str, mode: str, engine: str = "code") -> None:
        self._print("PockPock Code", "bold magenta")
        self._print(f"{engine} engine · model {model} · {mode} · {root}", "dim")
        self._print("Type a request. /help for commands, /exit to quit.", "dim")

    # ---------- streamed text ----------
    def thinking(self, chunk: str) -> None:
        if not self.show_thinking:
            return
        if not self.thinking_open:
            self.thinking_open = True
            sys.stdout.write("\x1b[2m")
        sys.stdout.write(chunk)
        sys.stdout.flush()

    def text(self, chunk: str) -> None:
        if self.thinking_open:
            sys.stdout.write("\x1b[0m\n")
            self.thinking_open = False
        self.streamed += chunk
        self.streamed_any = True
        sys.stdout.write(chunk)
        sys.stdout.flush()

    def end_text(self) -> None:
        if self.thinking_open:
            sys.stdout.write("\x1b[0m\n")
            self.thinking_open = False
        if self.streamed and not self.streamed.endswith("\n"):
            sys.stdout.write("\n")
        self.streamed = ""
        sys.stdout.flush()

    # ---------- tools ----------
    def tool_start(self, name: str, arguments: dict) -> None:
        self._print(f"● {LABELS.get(name, name)} {_short(arguments)}", "cyan")

    def tool_result(self, name: str, arguments: dict, output: str, ok: bool) -> None:
        if not ok:
            self._print("  ✗ " + output.splitlines()[0][:300] if output else "  ✗ failed", "red")
            if name == "run_command" and not self.quiet:
                self._tail(output)
            return
        if self.quiet:
            return
        if name in ("edit_file", "write_file"):
            first, _, diff = output.partition("\n")
            self._print("  " + first, "green")
            if diff.strip() and diff.strip() != "(no change)":
                if self.console:
                    self.console.print(Syntax(diff[:4000], "diff", theme="ansi_dark", background_color="default"))
                else:
                    print(diff[:4000])
        elif name == "run_command":
            self._tail(output)
        elif name == "todo_write":
            for line in output.splitlines()[1:]:
                self._print("  " + line, "yellow")
        else:
            lines = output.count("\n") + 1
            self._print(f"  {lines} line(s)", "dim")

    def _tail(self, output: str) -> None:
        lines = output.splitlines()
        for line in lines[:1] + (["  …"] if len(lines) > 13 else []) + lines[max(1, len(lines) - 12):]:
            self._print("  " + line[:220], "dim")

    def approve(self, kind: str, summary: str, detail: str) -> str:
        if kind == "command":
            self._print(f"  Run this command?  {summary}", "bold yellow")
        else:
            self._print(f"  Change {summary}?", "bold yellow")
            if detail:
                preview = "\n".join(detail.splitlines()[:15])
                self._print("  " + preview.replace("\n", "\n  "), "dim")
        try:
            answer = input("  [y] yes  [a] always  [n] no › ").strip().lower()
        except EOFError:
            return "no"
        return "always" if answer.startswith("a") else "yes" if answer in ("", "y", "yes") else "no"

    def notice(self, message: str) -> None:
        self._print(message, "yellow")

    def error(self, message: str) -> None:
        self._print(message, "bold red")

    def markdown(self, text: str) -> None:
        if self.console:
            self.console.print(Markdown(text))
        else:
            print(text)
