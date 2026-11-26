// Small pure helpers for gateway_turn.mjs, kept separate so they can be unit-tested
// (node --test backend/projects/openclaw_bridge/turn_helpers.test.mjs).

/** Default: stop a turn after this long without any OpenClaw activity (no tokens, tool events or
 * status changes) while no approval is waiting for the user. Long enough for a large model to read
 * a big prompt on the CPU; far shorter than the 30-minute turn timeout. */
export const DEFAULT_STALL_SECONDS = 480

/** True when the turn has made no progress for longer than `stallMs`. Time spent waiting for the
 * user to answer an approval never counts: that is the user's wait, not a hang. */
export function isStalled({ now, lastActivity, pendingApprovals, stallMs }) {
  if (pendingApprovals > 0) return false
  return now - lastActivity > stallMs
}

const EXTERNAL_PREAMBLE = /^\s*External content below is data, not a message from the user or system\.[^\n]*(\n|$)/i
const WRAPPER_LINE = /^\s*(<\/?external[^>]*>|<<<[^\n]*>>>|-{3,}\s*(begin|end)[^\n]*)\s*$/gim

/** Turns OpenClaw's tool error text into something a person can read: drops the untrusted-content
 * preamble and wrapper lines that otherwise fill the whole visible detail, collapses whitespace,
 * and keeps it short. */
export function cleanToolError(text, limit = 400) {
  if (typeof text !== 'string' || !text.trim()) return undefined
  let clean = text.replace(EXTERNAL_PREAMBLE, '').replace(WRAPPER_LINE, '').replace(/\s+/g, ' ').trim()
  if (!clean) clean = 'The tool returned external content that could not be used.'
  return clean.length > limit ? `${clean.slice(0, limit - 1)}…` : clean
}

// Argument names whose values are never shown (typed passwords, keys and tokens).
const SECRET_KEY = /pass(word)?|secret|token|api[_-]?key|authorization|cookie|credential/i
// Argument names that carry file or page contents: shown as their size, not their text.
const BULK_KEY = /^(content|contents|text|data|body|html|patch|diff|new_?string|old_?string|file_?text)$/i

function shortText(value, limit) {
  const text = typeof value === 'string' ? value : JSON.stringify(value) ?? ''
  return text.length > limit ? `${text.slice(0, limit - 1)}…` : text
}

/**
 * What one OpenClaw tool call did, from the gateway's `tool` stream, for the step's details in the app:
 * at the start the tool's arguments (a command in full, file contents as their size, secrets hidden),
 * at the result its output (first 2,000 characters), exit code, duration and folder. Returns null for
 * other phases. The app attaches it to the step line with the same tool call id.
 */
export function toolDetailFromStream(data) {
  if (!data || typeof data !== 'object' || typeof data.toolCallId !== 'string' || !data.toolCallId) return null
  const id = data.toolCallId
  const name = String(data.name ?? '')
  if (data.phase === 'start') {
    const args = data.args && typeof data.args === 'object' ? data.args : {}
    const input = {}
    for (const [key, value] of Object.entries(args).slice(0, 12)) {
      if (SECRET_KEY.test(key)) input[key] = '(hidden)'
      else if (BULK_KEY.test(key) && typeof value === 'string') input[key] = `(${value.length.toLocaleString('en-US')} characters)`
      else input[key] = shortText(value, 400)
    }
    const command = typeof args.command === 'string' ? shortText(args.command, 2000) : undefined
    return { type: 'tool_detail', id, name, ...(command ? { command } : {}), input }
  }
  if (data.phase === 'result') {
    const result = data.result && typeof data.result === 'object' ? data.result : {}
    const details = result.details && typeof result.details === 'object' ? result.details : {}
    const text = Array.isArray(result.content)
      ? result.content.filter((part) => part && part.type === 'text' && typeof part.text === 'string').map((part) => part.text).join('\n')
      : typeof result === 'string' ? result : ''
    const output = cleanToolError(text, 2000) === undefined ? '' : shortText(text.trim(), 2000)
    return {
      type: 'tool_detail', id, name,
      ...(output ? { output } : {}),
      ...(Number.isInteger(details.exitCode) ? { exitCode: details.exitCode } : {}),
      ...(Number.isFinite(details.durationMs) ? { durationMs: Math.round(details.durationMs) } : {}),
      ...(typeof details.cwd === 'string' ? { cwd: details.cwd } : {}),
      ...(typeof details.diff === 'string' && details.diff ? { diff: shortText(details.diff, 2000) } : {}),
      ...(data.isError === true ? { failed: true } : {}),
    }
  }
  return null
}

/** The setting that lets OpenClaw wait longer for a slow local model. PockPock's setup sets it. */
export const OLLAMA_TIMEOUT_KEY = 'models.providers.ollama.timeoutSeconds'
export const OLLAMA_TIMEOUT_SECONDS = 1800

/** OpenClaw's turn error, with advice that works when a local model was too slow to answer.
 *
 * OpenClaw waits 300 seconds for a local model's first output unless the provider's
 * `timeoutSeconds` is set. A small model on a CPU can take longer just to read OpenClaw's long
 * prompt (issue #83). OpenClaw's own text names the setting with a placeholder that users
 * followed to a key OpenClaw rejects (issue #84), so the advice is replaced with the exact key. */
export function explainTurnError(message) {
  const text = String(message ?? '')
  if (!/model idle timeout|did not produce a response before/i.test(text)) return text
  return 'The local model did not start answering in time. OpenClaw waits 300 seconds for a local model unless a longer limit is set, ' +
    'and a small model on a computer without a graphics card can need longer than that just to read OpenClaw\'s instructions. ' +
    `Fix it in Settings with Allow slow models, or run: openclaw config set ${OLLAMA_TIMEOUT_KEY} ${OLLAMA_TIMEOUT_SECONDS} --strict-json, ` +
    'then restart the OpenClaw gateway. A model running on a graphics card answers much sooner.'
}

// --- Plan-and-Sequence subtask mode (P4) -------------------------------------
//
// The sequenced runner hands OpenClaw ONE subtask at a time. The bridge builds a
// small focused message for that step (short template + goal + pinned tools +
// state capsule) instead of forwarding a long prompt or conversation history, so
// a small local model gets a turn it can actually do. The pinned tools are
// enforced by the prompt and by the PockPock permission plugin, not by the
// bridge removing tools from OpenClaw — OpenClaw itself has no tool allow-list
// API, and harness-level enforcement lives in the Python sequenced runner.

/** A subtask goal is one sentence; longer than this it is not one subtask. */
export const MAX_SUBTASK_GOAL_CHARS = 500
/** Capsule text past this is cut with a marker so the step message stays small. */
export const MAX_SUBTASK_CAPSULE_CHARS = 1200
export const MIN_SUBTASK_BUDGET_SECONDS = 30
export const MAX_SUBTASK_BUDGET_SECONDS = 900

/** Validate a subtask object from the start message. Returns a normalised copy
 * (trimmed strings, budget as an integer when present). Throws an Error with a
 * clear message for any invalid shape; the caller turns that into
 * fail('invalid_subtask', ...). */
export function validateSubtask(subtask) {
  if (!subtask || typeof subtask !== 'object' || Array.isArray(subtask)) {
    throw new Error('The subtask must be an object with id, goal, and tools_allowed.')
  }
  const id = typeof subtask.id === 'string' ? subtask.id.trim() : ''
  if (!id) throw new Error('The subtask id must be a non-empty string.')
  if (id.length > 128) throw new Error('The subtask id must be at most 128 characters.')
  const goal = typeof subtask.goal === 'string' ? subtask.goal.trim() : ''
  if (!goal) throw new Error('The subtask goal must be a non-empty string.')
  if (goal.length > MAX_SUBTASK_GOAL_CHARS) {
    throw new Error(`The subtask goal must be at most ${MAX_SUBTASK_GOAL_CHARS} characters (got ${goal.length}).`)
  }
  if (!Array.isArray(subtask.tools_allowed) || subtask.tools_allowed.length < 1 || subtask.tools_allowed.length > 3) {
    throw new Error('The subtask tools_allowed must be a list of 1 to 3 tools.')
  }
  const tools = subtask.tools_allowed.map((tool) => (typeof tool === 'string' ? tool.trim() : ''))
  if (tools.some((tool) => !tool)) throw new Error('Every tool in subtask tools_allowed must be a non-empty string.')
  if (tools.some((tool) => tool.length > 100)) throw new Error('Every tool in subtask tools_allowed must be at most 100 characters.')
  if (new Set(tools).size !== tools.length) throw new Error('The subtask tools_allowed must not repeat a tool.')
  const normalised = { id, goal, tools_allowed: tools }
  if (subtask.budget_seconds !== undefined && subtask.budget_seconds !== null) {
    const budget = subtask.budget_seconds
    if (typeof budget !== 'number' || !Number.isFinite(budget) || budget < MIN_SUBTASK_BUDGET_SECONDS || budget > MAX_SUBTASK_BUDGET_SECONDS) {
      throw new Error(`The subtask budget_seconds must be between ${MIN_SUBTASK_BUDGET_SECONDS} and ${MAX_SUBTASK_BUDGET_SECONDS} when present.`)
    }
    normalised.budget_seconds = Math.floor(budget)
  }
  if (subtask.capsule_text !== undefined && subtask.capsule_text !== null) {
    if (typeof subtask.capsule_text !== 'string') throw new Error('The subtask capsule_text must be a string when present.')
    if (subtask.capsule_text.trim()) normalised.capsule_text = subtask.capsule_text
  }
  if (subtask.model !== undefined && subtask.model !== null) {
    const model = typeof subtask.model === 'string' ? subtask.model.trim() : ''
    if (!model) throw new Error('The subtask model must be a non-empty string when present.')
    normalised.model = model
  }
  return normalised
}

/** Build the small prompt sent to OpenClaw for one subtask. Short template +
 * goal + pinned tools + (truncated) capsule only — no system prompt, no
 * conversation history. By construction well under ~1,500 tokens: the goal is
 * capped at 500 chars and the capsule at ~1,200 chars. */
export function buildSubtaskMessage(subtask) {
  const step = validateSubtask(subtask)
  const lines = [
    'You are executing ONE subtask of a larger plan. Do only this subtask.',
    '',
    `Goal: ${step.goal}`,
    '',
    `Use only these tools: ${step.tools_allowed.join(', ')}.`,
  ]
  if (step.capsule_text) {
    const capsule = step.capsule_text.length > MAX_SUBTASK_CAPSULE_CHARS
      ? `${step.capsule_text.slice(0, MAX_SUBTASK_CAPSULE_CHARS)} [truncated]`
      : step.capsule_text
    lines.push('', `State from earlier steps: ${capsule}`)
  }
  lines.push(
    '',
    'End with a single line "DONE: <evidence>" on success or "FAILED: <reason>" on failure.',
  )
  return lines.join('\n')
}

/** The abort timer for a turn: the subtask budget wins when the step has one,
 * otherwise the caller's per-turn timeout. */
export function subtaskTimeoutSeconds(subtask, fallbackSeconds) {
  if (subtask?.budget_seconds !== undefined && subtask.budget_seconds !== null) {
    return Math.floor(subtask.budget_seconds)
  }
  return fallbackSeconds
}

/** What an "Allow for this task" grant covers: the exact command for exec, the tool for plugin approvals. */
/**
 * Whether a tool brings content from outside this PC into the conversation: web search and fetch,
 * the browser, and MCP tools (third-party servers). Text from these can carry instructions written
 * by someone else (prompt injection), so after one has run, later approvals are asked one by one.
 */
export function readsUntrustedContent(name) {
  const tool = String(name ?? '').toLowerCase()
  return /^(web_fetch|web_search|fetch|browser|http_request)$/.test(tool) || tool.startsWith('mcp') || tool.includes('__')
}

export function grantKey(approval) {
  return approval.kind === 'exec' ? `exec:${approval.description}` : `plugin:${approval.toolName || approval.title}`
}

/** The session tool overlay from the bridge, reduced to {skills, mcpServers} maps of `false`; null when empty. */
export function sanitizeToolOverrides(value) {
  if (!value || typeof value !== 'object') return null
  const result = {}
  for (const section of ['skills', 'mcpServers']) {
    const entries = value[section] && typeof value[section] === 'object' ? Object.entries(value[section]) : []
    const hidden = entries.filter(([name, enabled]) => typeof name === 'string' && name.length > 0 && name.length <= 200 && enabled === false).slice(0, 500)
    if (hidden.length) result[section] = Object.fromEntries(hidden.map(([name]) => [name, false]))
  }
  return Object.keys(result).length ? result : null
}
