/**
 * PockPock permission policy for OpenClaw.
 *
 * Applies only to sessions PockPock starts (session key contains ":pockpock-").
 * PockPock writes the permission mode it wants for each session to
 * ~/.openclaw/pockpock/permissions.json before every turn:
 *
 *   ask   every action pauses for approval in PockPock
 *   auto  local read-only actions run; everything else pauses for approval
 *   full  nothing pauses
 *
 * A session with no recorded mode, or an unreadable state file, is treated as
 * "ask" so a missing record can never widen access.
 */
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { definePluginEntry } from "openclaw/plugin-sdk/plugin-entry";

const PLUGIN_ID = "pockpock-permissions";
const POLICY_VERSION = 1;
const SESSION_MARKER = ":pockpock-";
const APPROVAL_TIMEOUT_MS = 600_000;
const STATE_FILE = path.join(
  process.env.OPENCLAW_STATE_DIR || path.join(os.homedir(), ".openclaw"),
  "pockpock",
  "permissions.json",
);

type Mode = "ask" | "auto" | "full";
type Params = Record<string, unknown>;

/** Bookkeeping tools with no effect outside the conversation; never prompt. */
const INTERNAL_TOOLS = new Set([
  "session_status",
  "get_goal",
  "create_goal",
  "update_goal",
  "progress_card",
  "skills_search",
  "skills_read",
  "memory_search",
  "memory_get",
  "sessions_yield",
  "agents_wait",
  "agents_list",
  "decision_evaluate",
  "heartbeat_respond",
  "suggest_task",
  "dismiss_task",
  // Tool-search wrappers. Looking a tool up has no effect, and a tool run through
  // dispatch_action reaches this hook again under its own name, where it is checked.
  "tool_search",
  "tool_describe",
  "dispatch_action",
]);

/** Tools that only read local state; "auto" lets these run. */
const LOCAL_READ_TOOLS = new Set([
  "ls",
  "read",
  "view_image",
  "sessions_list",
  "sessions_history",
  "sessions_search",
]);

/** `browser` actions that only look at pages that are already open. */
const BROWSER_READ_ACTIONS = new Set([
  "status", "doctor", "profiles", "tabs", "snapshot", "screenshot", "text", "console", "errors", "requests",
]);

/** `process` actions that only observe a running command. */
const PROCESS_READ_ACTIONS = new Set(["list", "poll", "log", "status"]);

/** PockPock has no question UI, so the agent must ask in its reply instead. */
const BLOCKED_TOOLS = new Map([
  ["ask_user", "Ask the question in your reply instead; this chat cannot show question prompts."],
]);

/** First words of PowerShell/console commands that only read state. */
const SAFE_COMMANDS = new Set([
  "get-childitem", "gci", "dir", "ls",
  "get-content", "gc", "cat", "type",
  "select-string", "sls", "findstr",
  "get-location", "gl", "pwd",
  "get-item", "gi", "get-itemproperty", "gp",
  "test-path", "resolve-path", "split-path", "join-path",
  "get-date", "hostname", "whoami", "ver",
  "get-process", "gps", "tasklist", "get-service",
  "get-command", "gcm", "get-help", "where.exe",
  "get-filehash", "get-psdrive", "get-volume", "get-computerinfo",
  "measure-object", "measure", "select-object", "select",
  "sort-object", "sort", "group-object", "group",
  "format-table", "ft", "format-list", "fl", "out-string",
  "write-output", "echo", "tree", "systeminfo",
]);

/** Programs that are read-only only for specific subcommands. */
const SAFE_SUBCOMMANDS: Record<string, Set<string>> = {
  git: new Set(["status", "log", "diff", "show", "rev-parse", "ls-files", "blame", "describe", "shortlog"]),
  ollama: new Set(["list", "ls", "ps", "show", "--version", "-v"]),
  node: new Set(["--version", "-v"]),
  python: new Set(["--version", "-V"]),
  py: new Set(["--version", "-V"]),
  npm: new Set(["--version", "-v", "ls", "list", "view", "outdated"]),
  pip: new Set(["--version", "list", "show", "freeze"]),
  docker: new Set(["ps", "images", "version", "info"]),
  wsl: new Set(["--list", "-l", "--status", "--version"]),
};

/** Syntax that can write, chain hidden work, or evaluate code. */
const UNSAFE_SYNTAX = /[>`{}()&\r\n]|\$\(|(^|[\s|;])(iex|invoke-expression|start-process|saps|invoke-command|icm)(\s|$)/i;

function readMode(sessionKey: string): Mode {
  try {
    const state = JSON.parse(fs.readFileSync(STATE_FILE, "utf8")) as { sessions?: Record<string, unknown> };
    const mode = state.sessions?.[sessionKey];
    return mode === "full" || mode === "auto" ? mode : "ask";
  } catch {
    return "ask";
  }
}

function text(value: unknown): string {
  return typeof value === "string" ? value : "";
}

function clip(value: string, limit: number): string {
  const flat = value.replace(/\s+/g, " ").trim();
  return flat.length > limit ? `${flat.slice(0, limit - 1)}…` : flat;
}

/** True only when every pipeline segment is a known read-only command. */
export function isReadOnlyCommand(command: string): boolean {
  const trimmed = command.trim();
  if (!trimmed || trimmed.length > 600 || UNSAFE_SYNTAX.test(trimmed)) return false;
  const segments = trimmed.split(/\|\||&&|[|;]/).map((segment) => segment.trim());
  if (segments.some((segment) => !segment)) return false;
  return segments.every((segment) => {
    const words = segment.split(/\s+/);
    const head = words[0].toLowerCase().replace(/\.exe$/, "");
    const subcommands = SAFE_SUBCOMMANDS[head];
    if (subcommands) {
      // Options such as `git diff --output=<file>` turn a read into a write.
      if (words.some((word) => /^(--output|-o$)/i.test(word))) return false;
      return words.length > 1 && subcommands.has(words[1]);
    }
    return SAFE_COMMANDS.has(head) || SAFE_COMMANDS.has(`${head}.exe`);
  });
}

function isLocalRead(toolName: string, params: Params): boolean {
  if (LOCAL_READ_TOOLS.has(toolName)) return true;
  if (toolName === "process") return PROCESS_READ_ACTIONS.has(text(params.action).toLowerCase());
  if (toolName === "browser") return BROWSER_READ_ACTIONS.has(text(params.action).toLowerCase());
  // Looking at the screen is a read; moving the mouse or typing is not.
  if (toolName === "computer") return text(params.action).toLowerCase() === "screenshot";
  if (toolName === "exec") return isReadOnlyCommand(text(params.command));
  return false;
}

function describe(toolName: string, params: Params): { title: string; description: string; severity: "info" | "warning" } {
  const target = text(params.path) || text(params.file_path) || text(params.filePath);
  if (toolName === "exec") {
    const workdir = text(params.workdir);
    return {
      title: "Run command",
      description: clip(`${text(params.command)}${workdir ? `  (in ${workdir})` : ""}`, 500),
      severity: "warning",
    };
  }
  if (toolName === "write" || toolName === "edit" || toolName === "apply_patch") {
    return {
      title: toolName === "write" ? "Write file" : "Edit file",
      description: clip(target || text(params.input) || "File change", 500),
      severity: "warning",
    };
  }
  if (toolName === "read" || toolName === "ls" || toolName === "view_image") {
    return { title: toolName === "ls" ? "List folder" : "Read file", description: clip(target || ".", 500), severity: "info" };
  }
  if (toolName === "web_fetch" || toolName === "web_search" || toolName === "x_search") {
    return {
      title: toolName === "web_fetch" ? "Fetch web page" : "Search the web",
      description: clip(text(params.url) || text(params.query) || toolName, 500),
      severity: "info",
    };
  }
  if (toolName === "browser") {
    const action = text(params.action) || "use";
    const detail = text(params.url) || [text(params.kind), text(params.ref), text(params.text)].filter(Boolean).join(" ");
    return { title: "Control the browser", description: clip(`${action} ${detail}`, 500), severity: "warning" };
  }
  if (toolName === "computer") {
    const action = text(params.action) || "use";
    const detail = [text(params.text), text(params.key), Array.isArray(params.coordinate) ? `at ${params.coordinate.join(",")}` : ""].filter(Boolean).join(" ");
    return {
      title: action === "screenshot" ? "Look at the screen" : "Control mouse and keyboard",
      description: clip(`${action} ${detail}`, 500),
      severity: action === "screenshot" ? "info" : "warning",
    };
  }
  // Tools from a connected MCP server are named "<server>__<tool>".
  const [server, tool] = toolName.includes("__") ? [toolName.split("__")[0], toolName.split("__").slice(1).join("__")] : ["", ""];
  const summary = Object.entries(params)
    .filter(([, value]) => typeof value === "string" || typeof value === "number" || typeof value === "boolean")
    .map(([key, value]) => `${key}=${String(value)}`)
    .join(", ");
  return { title: clip(server && tool ? `Use MCP tool: ${server} › ${tool}` : `Use tool: ${toolName}`, 80), description: clip(summary || toolName, 500), severity: "warning" };
}

export default definePluginEntry({
  id: PLUGIN_ID,
  name: "PockPock permissions",
  description: "Ask-first, auto-approve-safe, and full-access permission modes for PockPock chat sessions.",
  register(api) {
    api.on(
      "before_tool_call",
      (event, ctx) => {
        const sessionKey = text(ctx.sessionKey);
        if (!sessionKey.includes(SESSION_MARKER)) return;
        const toolName = event.toolName;
        const blockReason = BLOCKED_TOOLS.get(toolName);
        if (blockReason) return { block: true, blockReason };
        const mode = readMode(sessionKey);
        if (mode === "full" || INTERNAL_TOOLS.has(toolName)) return;
        const params = (event.params ?? {}) as Params;
        if (mode === "auto" && isLocalRead(toolName, params)) return;
        return {
          requireApproval: {
            ...describe(toolName, params),
            allowedDecisions: ["allow-once", "deny"],
            timeoutMs: APPROVAL_TIMEOUT_MS,
          },
        };
      },
      { priority: 100 },
    );

    api.registerGatewayMethod(
      "pockpock.permissions.status",
      async ({ respond }) => {
        respond(true, { ok: true, plugin: PLUGIN_ID, policyVersion: POLICY_VERSION, stateFile: STATE_FILE }, undefined);
      },
      { scope: "operator.read" },
    );
  },
});
