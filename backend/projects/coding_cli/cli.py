"""PockPock Code: a terminal coding agent for local models.

  pockpock-code                      interactive session in the current folder
  pockpock-code "fix the failing test"   start with a request
  pockpock-code -p "explain src/app.py"  answer once and exit (scripts, CI)
  pockpock-code --resume             continue the last session in this folder
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import time
from pathlib import Path

from . import llm
from .agent import Agent
from . import engines
from .tools import Workspace
from .ui import TerminalUI

MODES = ("suggest", "auto-edit", "full-auto")
HELP = """Commands:
  /engine [e]     code (built-in coding agent) · pockpock (PockPock Agent, checked steps) · openclaw (shell, browser, apps) · auto
  /model [name]   show installed models or switch model
  /planner [name] Plan in steps planner for the pockpock engine (off: one model plans and works)
  /mode [m]       suggest (ask before edits and commands) · auto-edit (ask before commands) · full-auto
  /think          turn the model's thinking on or off (slower, better on hard tasks)
  /undo           restore the files changed by the last request
  /diff           show git diff of the working tree
  /todo           show the to-do list
  /compact        shorten old tool output to free context
  /clear          start a fresh conversation
  /init           write an AGENTS.md describing this project
  /exit           quit
End a line with \\ to continue typing on the next line."""


def data_dir() -> Path:
    if sys.platform == "win32":
        base = Path(os.environ.get("LOCALAPPDATA") or Path.home() / "AppData" / "Local")
    elif sys.platform == "darwin":
        base = Path.home() / "Library" / "Application Support"
    else:
        base = Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local" / "share")
    folder = base / "PockPock" / "code-sessions"
    folder.mkdir(parents=True, exist_ok=True)
    return folder


def settings_path() -> Path:
    return data_dir().parent / "code-settings.json"


def load_settings() -> dict:
    try:
        return json.loads(settings_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def save_settings(**values) -> None:
    current = load_settings()
    current.update(values)
    try:
        settings_path().write_text(json.dumps(current, indent=1), encoding="utf-8")
    except OSError:
        pass


def session_file(root: Path) -> Path:
    return data_dir() / (hashlib.sha256(str(root).lower().encode()).hexdigest()[:16] + ".json")


def save_session(agent: Agent) -> None:
    try:
        session_file(agent.ws.root).write_text(json.dumps({"root": str(agent.ws.root), "model": agent.model, "saved": time.time(), "messages": agent.messages[-200:], "todos": agent.ws.todos}, ensure_ascii=False), encoding="utf-8")
    except OSError:
        pass


def load_session(agent: Agent) -> bool:
    try:
        data = json.loads(session_file(agent.ws.root).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return False
    messages = data.get("messages") or []
    if len(messages) < 2:
        return False
    agent.messages = [agent.messages[0]] + [m for m in messages[1:] if m.get("role") != "system"]
    agent.ws.todos = data.get("todos") or []
    return True


INIT_REQUEST = ("Look around this project (manifests, folders, main entry points, tests) and write AGENTS.md at the project root for coding agents: "
                "what the project is, how it is organised, how to install, run, test and build it (exact commands), and the code style rules you can see. "
                "Keep it under 80 lines. If AGENTS.md exists, read it and improve it instead.")


def slash(command: str, agent: Agent, ui: TerminalUI, router: "Router") -> str | None:
    """Handle a /command. Returns a request to send to the agent, or None."""
    name, _, arg = command[1:].partition(" ")
    arg = arg.strip()
    if name in ("help", "?"):
        ui._print(HELP)
    elif name == "model":
        available = llm.list_models(agent.base)
        if not arg:
            for item in available:
                ui._print(("* " if item == agent.model else "  ") + item)
        else:
            agent.model = llm.pick_model(available, arg)
            save_settings(model=agent.model)
            ui.notice(f"Model: {agent.model}")
    elif name == "engine":
        if arg not in engines.ENGINES:
            ui._print(f"Engine: {router.engine}. Choose one of: {', '.join(engines.ENGINES)}")
        else:
            router.engine = arg
            save_settings(engine=arg)
            ui.notice(f"Engine: {arg}")
    elif name == "planner":
        router.planner = None if arg in ("", "off", "none") else llm.pick_model(llm.list_models(agent.base), arg)
        save_settings(planner=router.planner)
        ui.notice(f"Planner: {router.planner or 'off (one model plans and works)'}")
    elif name == "mode":
        if arg not in MODES:
            ui._print(f"Mode: {agent.mode}. Choose one of: {', '.join(MODES)}")
        else:
            agent.mode = arg
            agent.always.clear()
            save_settings(mode=arg)
            ui.notice(f"Mode: {arg}")
    elif name == "think":
        agent.think = not agent.think
        ui.notice("Thinking on." if agent.think else "Thinking off.")
    elif name == "undo":
        restored = agent.ws.undo()
        ui.notice("Restored: " + ", ".join(restored) if restored else "Nothing to undo.")
        if restored:
            agent.messages.append({"role": "user", "content": f"[The user undid your last changes to: {', '.join(restored)}.]"})
    elif name == "diff":
        from .tools import run_command

        ui._print(run_command(agent.ws, "git diff --stat; git diff")[:20000])
    elif name == "todo":
        ui._print("\n".join(f"[{'x' if t['status'] == 'done' else '>' if t['status'] == 'in_progress' else ' '}] {t['task']}" for t in agent.ws.todos) or "No to-do list.")
    elif name == "compact":
        ui.notice("Shortened older output." if agent.compact(force=True) else "Nothing to shorten.")
    elif name in ("clear", "new"):
        agent.reset()
        ui.notice("Started a fresh conversation.")
    elif name == "init":
        return INIT_REQUEST
    elif name in ("exit", "quit", "q"):
        raise EOFError
    else:
        ui.notice(f"Unknown command /{name}. Type /help.")
    return None


def read_request() -> str:
    lines = []
    prompt = "\n› "
    while True:
        line = input(prompt)
        if line.endswith("\\"):
            lines.append(line[:-1])
            prompt = "  "
            continue
        lines.append(line)
        return "\n".join(lines).strip()


CODE_EXTENSIONS = {".py", ".js", ".ts", ".tsx", ".jsx", ".go", ".rs", ".java", ".kt", ".dart", ".cs", ".cpp", ".c", ".rb", ".php", ".swift", ".vue", ".svelte"}


class Router:
    """Sends each request to the chosen engine; with "auto", to the one that fits it best."""

    def __init__(self, engine: str, planner: str | None, gateway: str, auto_approve_plan: bool = False) -> None:
        self.engine, self.planner, self.gateway, self.auto_approve_plan = engine, planner, gateway, auto_approve_plan
        self._gateway_up: bool | None = None

    def gateway_up(self) -> bool:
        if self._gateway_up is None:
            self._gateway_up = engines.gateway_running(self.gateway)
        return self._gateway_up

    def pick(self, agent: Agent, request: str) -> tuple[str, str]:
        if self.engine != "auto":
            return self.engine, ""
        from .tools import project_files

        has_code = any(Path(name).suffix.lower() in CODE_EXTENSIONS for name in project_files(agent.ws, limit=3000))
        return engines.choose_engine(request, project_has_code=has_code, gateway_up=self.gateway_up())

    def run(self, agent: Agent, ui: TerminalUI, request: str) -> str:
        engine, reason = self.pick(agent, request)
        if reason:
            ui._print(f"→ {engine}: {reason}", "dim")
        if engine == "code":
            return agent.run(request, ui)
        if engine == "pockpock":
            runner = engines.PockPockEngine(root=str(agent.ws.root), model=agent.model, mode=agent.mode, planner=self.planner, base=self.gateway, auto_approve_plan=self.auto_approve_plan)
        else:
            runner = engines.OpenClawEngine(root=str(agent.ws.root), model=agent.model, mode=agent.mode, base=self.gateway)
        ui.streamed_any = False
        answer = runner.run(request, ui)
        if answer and not ui.streamed_any:
            ui.markdown(answer)
        # The coding agent keeps a note of what the other engine did, so a follow-up request has the context.
        agent.messages.append({"role": "user", "content": f"[Handled by the {engine} engine: {request}]"})
        agent.messages.append({"role": "assistant", "content": (answer or "(no reply)")[:4000]})
        return answer


def run_request(agent: Agent, ui: TerminalUI, request: str, router: Router | None = None) -> int:
    started = time.time()
    try:
        if router:
            router.run(agent, ui, request)
        else:
            agent.run(request, ui)
    except (llm.ModelError, engines.GatewayError) as err:
        ui.error(str(err))
        return 1
    except KeyboardInterrupt:
        ui.notice("Stopped. Files changed so far are kept; /undo restores them.")
        agent.messages.append({"role": "user", "content": "[The user stopped you here.]"})
        return 130
    finally:
        save_session(agent)
    changed = sorted(set(agent.ws.changed))
    ui._print(f"\n{time.time() - started:.0f} s · context {agent.usage['prompt']} tokens" + (f" · changed {', '.join(changed[-6:])}" if changed else ""), "dim")
    agent.ws.changed.clear()
    return 0


def main(argv: list[str] | None = None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        try:
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        except (OSError, ValueError):
            pass
    settings = load_settings()
    parser = argparse.ArgumentParser(prog="pockpock-code", description="A coding agent in your terminal, running on local models with Ollama.")
    parser.add_argument("request", nargs="*", help="what to do (optional)")
    parser.add_argument("-p", "--print", action="store_true", help="run the request once, print the result and exit")
    parser.add_argument("-m", "--model", default=os.environ.get("POCKPOCK_CODE_MODEL") or settings.get("model"))
    parser.add_argument("--mode", choices=MODES, default=settings.get("mode", "auto-edit"))
    parser.add_argument("-e", "--engine", choices=engines.ENGINES, default=os.environ.get("POCKPOCK_CODE_ENGINE") or settings.get("engine", "code"),
                        help="code: built-in coding agent (default) · pockpock: PockPock Agent · openclaw: OpenClaw · auto: choose per request")
    parser.add_argument("--planner", default=settings.get("planner"), help="planner model for the pockpock engine (Plan in steps)")
    parser.add_argument("--gateway", default=engines.DEFAULT_GATEWAY, help="PockPock gateway URL for the pockpock and openclaw engines")
    parser.add_argument("-C", "--cwd", default=".", help="project folder (default: current folder)")
    parser.add_argument("--resume", action="store_true", help="continue the last session in this folder")
    parser.add_argument("--think", action="store_true", help="let the model think before answering")
    parser.add_argument("--ctx", type=int, default=int(settings.get("num_ctx", 32768)), help="context window in tokens (default 32768)")
    parser.add_argument("--ollama", default=os.environ.get("OLLAMA_HOST_URL") or settings.get("ollama") or llm.DEFAULT_OLLAMA)
    args = parser.parse_args(argv)

    root = Path(args.cwd).expanduser().resolve()
    ui = TerminalUI(quiet=args.print)
    if not root.is_dir():
        ui.error(f"{root} is not a folder.")
        return 2
    try:
        model = llm.pick_model(llm.list_models(args.ollama), args.model)
    except llm.ModelError as err:
        ui.error(str(err))
        return 2
    mode = args.mode
    if args.print and mode != "full-auto":
        # Nobody is there to approve: commands are declined unless --mode full-auto.
        mode = "auto-edit"
    agent = Agent(ws=Workspace(root=root), model=model, mode=mode, base=args.ollama.rstrip("/"), num_ctx=args.ctx, think=args.think)
    router = Router(args.engine, args.planner, args.gateway.rstrip("/"), auto_approve_plan=args.print)
    if args.print:
        ui.approve = lambda kind, summary, detail: "no"  # type: ignore[method-assign]
        request = " ".join(args.request).strip() or sys.stdin.read().strip()
        if not request:
            ui.error("Give a request, for example: pockpock-code -p \"explain main.py\"")
            return 2
        return run_request(agent, ui, request, router)

    ui.banner(model, str(root), mode, args.engine)
    if args.resume:
        ui.notice("Continuing the last session." if load_session(agent) else "No earlier session in this folder.")
    pending = " ".join(args.request).strip()
    while True:
        try:
            request = pending or read_request()
            pending = ""
            if not request:
                continue
            if request.startswith("/"):
                request = slash(request, agent, ui, router)
                if not request:
                    continue
            run_request(agent, ui, request, router)
        except (EOFError, KeyboardInterrupt):
            save_session(agent)
            print()
            return 0
        except llm.ModelError as err:
            ui.error(str(err))


if __name__ == "__main__":
    sys.exit(main())
