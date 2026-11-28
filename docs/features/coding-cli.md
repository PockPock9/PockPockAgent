# PockPock Code (terminal coding agent)

PockPock Code is a coding agent you run in a terminal, in the folder of a project. It reads the code, answers
questions with file and line references, makes changes, runs the project's tests and fixes what fails. It runs
on local models through Ollama: nothing leaves the computer, and PockPock's own services do not need to be
running.

```
pockpock-code                         # interactive session in the current folder
pockpock-code "fix the failing test"  # start with a request
pockpock-code -p "explain src/app.py" # answer once and exit (scripts, CI)
pockpock-code --resume                # continue the last session in this folder
```

## Install

The desktop app installs the command:
- **Windows:** `%LOCALAPPDATA%\PockPock\bin\pockpock-code.cmd`. The folder is added to your user PATH once,
  so open a new terminal after the first start.
- **macOS:** `~/.local/bin/pockpock-code`. If that folder is not on PATH, a line adding it is appended to
  `~/.zprofile`.

The launcher runs the app's own Python (`%LOCALAPPDATA%\PockPock\runtime\venv`) with the bundled backend, so
it always matches the installed version. It is written after setup finishes and again at every start (only
when it changed). Development builds never install it. From a checkout, run
`python backend/scripts/pockpock_code.py` with the repository's `.venv`.

## Using it

| Option | Meaning |
|---|---|
| `-m, --model` | Ollama model. Default: the last one chosen with `/model`, otherwise the first installed of `qwen3.5:9b`, `qwen3.8:27b`, `qwen3.5:27b`, `qwen3.6:35b-a3b`, `qwen2.5-coder:14b`… Also `POCKPOCK_CODE_MODEL`. |
| `--mode` | `suggest`: ask before every edit and command. `auto-edit` (default): edit freely, ask before commands. `full-auto`: ask for nothing. |
| `-p, --print` | One request, no questions: commands are declined unless `--mode full-auto`. The request can also come from stdin. |
| `-C, --cwd` | Project folder (default: the current folder). |
| `--resume` | Continue the last saved session for this folder. |
| `--think` | Let the model think before answering (slower; better on hard problems). |
| `--ctx` | Context window in tokens (default 32768). |
| `--ollama` | Ollama URL (default `http://127.0.0.1:11434`; also `OLLAMA_HOST_URL`). |

Commands inside a session: `/model [name]`, `/mode [suggest|auto-edit|full-auto]`, `/think`, `/undo` (restore
the files the last request changed), `/diff` (git diff), `/todo`, `/compact`, `/clear`, `/init` (write an
`AGENTS.md` for the project) and `/exit`. End a line with `\` to type more lines. Ctrl+C stops the current
request; the changes made so far stay, and `/undo` restores them.

When asked, answer `y` (yes), `a` (always, for the rest of the session) or `n` (no). A declined action is
reported to the model, which must find another way or ask.

## How it works

Modules in [`backend/projects/coding_cli/`](../../backend/projects/coding_cli/):

| Module | Role |
|---|---|
| `cli.py` | Arguments, the interactive loop, `/` commands, saved sessions and settings. |
| `agent.py` | The agent loop: model reply → tool calls (with approval) → results → model, until it answers. |
| `llm.py` | Streaming Ollama `/api/chat` client with native tool calls, plus recovery of tool calls written as text. |
| `tools.py` | The tools and the project-folder boundary, edit snapshots for `/undo`. |
| `context.py` | The system prompt: working rules, a project overview and the project's instruction files. |
| `ui.py` | Terminal output (uses `rich` when installed, plain text otherwise). |

**Context the model starts with:** the operating system and shell (PowerShell on Windows, `sh` elsewhere);
the number and types of files; the top-level folders; manifests (`package.json`, `pyproject.toml`,
`pubspec.yaml`…); the git branch and uncommitted changes; and the project's instructions from `AGENTS.md`,
`CLAUDE.md`, `.pockpock/instructions.md` or `.github/copilot-instructions.md` (6,000 characters each).

**Tools:**

| Tool | Contract |
|---|---|
| `list_files` | Project files (git's list when it is a repository, so `.gitignore` applies), filtered by glob or folder; 300 shown. |
| `search` | Regular-expression search, `path:line: text`, 200 matches at most. |
| `read_file` | Up to 400 numbered lines per call; says where the file ends or how to read on. A missing file suggests close names. |
| `edit_file` | Replaces exact text that must be unique. If it is not found exactly, a match that differs only in indentation or trailing spaces is accepted and the new text is re-indented. Returns a diff. |
| `write_file` | Creates a file, or replaces one that was read first. Returns a diff. |
| `run_command` | Runs in the project folder, non-interactive, 120 s by default (900 s at most). Returns exit code and output, cut to 12,000 characters. |
| `todo_write` | The agent's to-do list for multi-step work, shown in the terminal. |

Every path must stay inside the project folder. Argument names used by other agents (`file_path`,
`old_string`, `cmd`…) are accepted.

**Guard rails for small models:**
- A tool call written as text (`<tool_call>{…}</tool_call>`, a fenced JSON block or bare JSON) is run as a
  tool call.
- The third identical call is refused, with a hint to change approach.
- An answer that ends with to-do items still open is sent back once to continue.
- An answer after edits with no check since is sent back once, to run the project's tests, build or linter.
- When the context passes about 70% of the window, older tool output is shortened. If that is not enough,
  the oldest steps are dropped, keeping the first request and the list of changed files.
- 60 steps at most per request; say "continue" to go on.

**Saved data:** sessions are saved in `<PockPock data>/code-sessions/<hash of folder>.json` (last 200
messages and the to-do list). Settings chosen with `/model` and `/mode` are saved in
`<PockPock data>/code-settings.json`. `<PockPock data>` is `%LOCALAPPDATA%\PockPock` on Windows and
`~/Library/Application Support/PockPock` on macOS. Nothing is sent anywhere except the local Ollama.

## Security

- Paths outside the project folder are refused.
- By default every command is asked about. `full-auto` runs commands without asking. Use it only in a
  folder you can restore (for example a git repository).
- `-p` runs without anyone to approve, so commands are declined unless `--mode full-auto` is given.
- The system prompt forbids destructive commands (`rm -rf`, `git reset --hard`, force push) unless asked.
  The model can still ignore it: this is a rule given to the model, not a sandbox.

## Verified

- Unit tests: `backend/projects/coding_cli/test_coding_cli.py` (21: tools, text tool calls, approvals, the
  loop with a scripted model, compaction) and `desktop/electron/cli-command.test.cjs` (the launcher).
- Live with `qwen3.5:9b` on Windows (2026-11-28):
  - fixed a Python module so its unit tests pass (206 s);
  - added discount codes to a JavaScript cart, with tests, `npm test` passing (20 s);
  - answered "How does Plan in steps check that a step is done?" on this repository with correct files,
    functions and line numbers (20 s).
- Not verified yet: macOS, long sessions near the context limit with a real model, cloud models.
