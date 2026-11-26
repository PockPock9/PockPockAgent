// Runs one OpenClaw chat turn over the local Gateway WebSocket for PockPock.
//
// stdin  (JSON lines): {"type":"start",...} first, then {"type":"approval",...} or {"type":"abort"}
// stdout (JSON lines): status | delta | replace | tool | approval | approval_resolved | final | error
//
// The message arrives on stdin, never on the command line. The Gateway token is
// read from the local OpenClaw config and is sent only to 127.0.0.1.
import crypto from 'node:crypto'
import fs from 'node:fs'
import os from 'node:os'
import path from 'node:path'
import readline from 'node:readline'
import { buildSubtaskMessage, cleanToolError, DEFAULT_STALL_SECONDS, explainTurnError, grantKey, isStalled, sanitizeToolOverrides, subtaskTimeoutSeconds, validateSubtask } from './turn_helpers.mjs'

const DEBUG = process.env.POCKPOCK_OPENCLAW_DEBUG === '1'
const STATE_DIR = process.env.OPENCLAW_STATE_DIR || path.join(os.homedir(), '.openclaw')
const CONFIG_PATH = process.env.OPENCLAW_CONFIG_PATH || path.join(STATE_DIR, 'openclaw.json')
const PLUGIN_STATUS_METHOD = 'pockpock.permissions.status'
const CONNECT_TIMEOUT_MS = 20_000
const RPC_TIMEOUT_MS = 30_000
const FULL_AUTO_NOTE = '(Full auto: work on your own until the task is done. Do not stop to ask me questions or for confirmation; choose sensible defaults, and list any assumptions you made in your final reply.)'
const TERMINAL_CHAT_STATES = new Set(['final', 'error', 'aborted'])

let finished = false
const emit = (event) => { process.stdout.write(`${JSON.stringify(event)}\n`) }
const debug = (...parts) => { if (DEBUG) process.stderr.write(`${parts.join(' ')}\n`) }

function finish(event, code = 0) {
  if (finished) return
  finished = true
  emit(event)
  // Let stdout drain before exiting so the parent always sees the last event.
  process.stdout.write('', () => process.exit(code))
}

function fail(code, message) {
  finish({ type: 'error', code, message }, 1)
}

function loadGateway() {
  let config
  try {
    config = JSON.parse(fs.readFileSync(CONFIG_PATH, 'utf8'))
  } catch {
    throw new Error('OpenClaw is not set up on this PC (its config file could not be read).')
  }
  const port = Number(process.env.OPENCLAW_GATEWAY_PORT || config?.gateway?.port || 18789)
  const token = config?.gateway?.auth?.token
  if (!Number.isInteger(port) || port < 1 || port > 65535) throw new Error('The OpenClaw gateway port is not valid.')
  if (typeof token !== 'string' || !token) throw new Error('The OpenClaw gateway has no token configured.')
  return { port, token }
}

class Gateway {
  constructor({ port, token }) {
    this.token = token
    this.socket = new WebSocket(`ws://127.0.0.1:${port}`)
    this.pending = new Map()
    this.sequence = 0
    this.onEvent = () => {}
    this.connected = new Promise((resolve, reject) => {
      const timer = setTimeout(() => reject(new Error('The OpenClaw gateway did not answer in time.')), CONNECT_TIMEOUT_MS)
      this.socket.addEventListener('error', () => { clearTimeout(timer); reject(new Error('The OpenClaw gateway is not running.')) })
      this.socket.addEventListener('close', () => {
        clearTimeout(timer)
        reject(new Error('The OpenClaw gateway closed the connection.'))
        for (const { reject: rejectCall } of this.pending.values()) rejectCall(new Error('The OpenClaw gateway closed the connection.'))
        this.pending.clear()
        if (!finished) fail('gateway_closed', 'The OpenClaw gateway closed the connection before the turn finished.')
      })
      this.socket.addEventListener('message', (message) => {
        let frame
        try { frame = JSON.parse(message.data) } catch { return }
        if (frame.type === 'res') {
          const call = this.pending.get(frame.id)
          if (!call) return
          this.pending.delete(frame.id)
          clearTimeout(call.timer)
          if (frame.ok) call.resolve(frame.payload)
          else call.reject(Object.assign(new Error(frame.error?.message || 'Gateway request failed.'), { code: frame.error?.code }))
        } else if (frame.type === 'event') {
          if (frame.event === 'connect.challenge') {
            this.call('connect', {
              minProtocol: 4,
              maxProtocol: 4,
              client: { id: 'gateway-client', version: '1.0.0', platform: process.platform, mode: 'backend' },
              role: 'operator',
              scopes: ['operator.read', 'operator.write', 'operator.approvals', 'operator.admin'],
              caps: ['approvals', 'exec-approvals', 'plugin-approvals', 'tool-events'],
              commands: [],
              permissions: {},
              auth: { token: this.token },
              locale: 'en-US',
              userAgent: 'pockpock-openclaw-bridge/1.0.0',
            }).then((hello) => { clearTimeout(timer); resolve(hello) }, (error) => { clearTimeout(timer); reject(error) })
          } else {
            this.onEvent(frame.event, frame.payload ?? {})
          }
        }
      })
    })
  }

  call(method, params, timeoutMs = RPC_TIMEOUT_MS) {
    return new Promise((resolve, reject) => {
      const id = `pp${++this.sequence}`
      const timer = setTimeout(() => {
        this.pending.delete(id)
        reject(new Error(`OpenClaw gateway request ${method} timed out.`))
      }, timeoutMs)
      this.pending.set(id, { resolve, reject, timer })
      this.socket.send(JSON.stringify({ type: 'req', id, method, params }))
    })
  }
}

function messageText(message) {
  if (!message || !Array.isArray(message.content)) return ''
  return message.content.filter((block) => block?.type === 'text' && typeof block.text === 'string').map((block) => block.text).join('')
}

function approvalEvent(kind, payload) {
  const request = payload.request ?? {}
  const id = typeof payload.id === 'string' ? payload.id : ''
  if (kind === 'exec') {
    return { type: 'approval', id, kind, title: 'Run command', description: String(request.command ?? ''), severity: 'warning', toolName: 'exec' }
  }
  return {
    type: 'approval',
    id,
    kind,
    title: String(request.title ?? payload.title ?? 'Approval required'),
    description: String(request.description ?? payload.description ?? ''),
    severity: String(request.severity ?? payload.severity ?? 'warning'),
    toolName: String(request.toolName ?? payload.toolName ?? ''),
  }
}

/** The provider PockPock adds for cloud models: its ids are "<provider>/<model>" (see docs/features/cloud-models.md). */
const CLOUD_PROVIDER = 'pockpock-cloud'

/** OpenClaw's own workspace (agents.defaults.workspace), used when no folder is chosen. */
function defaultWorkspace() {
  try {
    const configured = JSON.parse(fs.readFileSync(CONFIG_PATH, 'utf8'))?.agents?.defaults?.workspace
    if (typeof configured === 'string' && configured.trim()) return configured.trim().replace(/^~(?=$|[\\/])/, os.homedir())
  } catch { /* fall back to OpenClaw's default */ }
  return path.join(STATE_DIR, 'workspace')
}

/** The default model, the tool-capable Ollama models and the cloud models in OpenClaw's config. */
function localModels() {
  try {
    const config = JSON.parse(fs.readFileSync(CONFIG_PATH, 'utf8'))
    const usable = (listed) => (Array.isArray(listed) ? listed : [])
      .filter((entry) => entry && typeof entry.id === 'string' && entry.compat?.supportsTools !== false)
      .map((entry) => entry.id)
    return {
      model: String(config?.agents?.defaults?.model?.primary ?? ''),
      models: usable(config?.models?.providers?.ollama?.models),
      cloud: usable(config?.models?.providers?.[CLOUD_PROVIDER]?.models),
    }
  } catch {
    return { model: '', models: [], cloud: [] } // Status still reports the gateway as reachable.
  }
}

async function run(start) {
  // Subtask mode (Plan-and-Sequence P4): validate before connecting so an
  // invalid subtask fails fast without touching the gateway.
  let subtask = null
  if (start.subtask !== undefined && start.subtask !== null) {
    try {
      subtask = validateSubtask(start.subtask)
    } catch (error) {
      fail('invalid_subtask', String(error?.message ?? error))
      return
    }
  }
  // The subtask budget replaces the caller's per-turn timeout for this step.
  const timeoutSeconds = subtaskTimeoutSeconds(subtask, start.timeoutSeconds)
  // In subtask mode the small built message replaces the caller's full message:
  // no long system prompt, no conversation history.
  // Full auto: the user chose to let OpenClaw work on its own, so it must not stop to ask.
  const message = subtask ? buildSubtaskMessage(subtask) : start.fullAuto ? `${start.message}\n\n${FULL_AUTO_NOTE}` : start.message

  const sessionKey = `agent:${start.agent}:explicit:${start.sessionId}`
  const gateway = new Gateway(loadGateway())
  await gateway.connected

  if (start.statusOnly) {
    let plugin = false
    try { plugin = (await gateway.call(PLUGIN_STATUS_METHOD, {}))?.ok === true } catch { plugin = false }
    const { model, models, cloud } = localModels()
    finish({ type: 'status_result', gateway: true, plugin, model, models: [...models, ...cloud] })
    return
  }

  // Ask and auto modes are enforced by the PockPock permission plugin. Without
  // it, OpenClaw would run every tool unprompted, so refuse instead of degrading.
  let pluginReady = false
  try { pluginReady = (await gateway.call(PLUGIN_STATUS_METHOD, {}))?.ok === true } catch { pluginReady = false }
  if (!pluginReady && start.mode !== 'full') {
    fail('plugin_missing', 'The PockPock permission plugin is not loaded in OpenClaw, so Ask first and Auto-approve safe cannot be enforced. Reinstall it or choose Full access.')
    return
  }

  let runId = ''
  let model = ''
  let text = ''
  const startedAt = Date.now()
  const pendingApprovals = new Map() // id -> { kind, key }
  // "Allow for this task": approvals granted for the rest of this turn. An exec grant covers the exact
  // command; a plugin grant covers that tool. They end with the turn.
  const grants = new Set()
  let aborting = false
  let lastActivity = Date.now()
  const stallSeconds = Number(start.stallSeconds) > 0 ? Number(start.stallSeconds) : DEFAULT_STALL_SECONDS

  const abort = async (reason) => {
    if (aborting || finished) return
    aborting = true
    for (const [id, { kind }] of pendingApprovals) {
      gateway.call(kind === 'exec' ? 'exec.approval.resolve' : 'plugin.approval.resolve', { id, decision: 'deny' }).catch(() => {})
    }
    try { await gateway.call('chat.abort', runId ? { sessionKey, runId } : { sessionKey }, 5_000) } catch { /* The run may already be over. */ }
    if (reason === 'timeout') fail('timeout', `OpenClaw did not finish within ${timeoutSeconds} seconds, so the turn was stopped.`)
    else if (reason === 'stalled') fail('stalled', `OpenClaw made no progress for ${Math.round(stallSeconds / 60)} minutes (no reply, tool activity or approval request), so the turn was stopped. Try again, or ask for a smaller step; a smaller model or a new chat can also help when the conversation is long.`)
    else finish({ type: 'error', code: 'aborted', message: 'The OpenClaw turn was stopped.' }, 0)
  }

  gateway.onEvent = (event, payload) => {
    debug('EVT', event, JSON.stringify(payload).slice(0, 1500))
    if (event === 'plugin.approval.requested' || event === 'exec.approval.requested') {
      const kind = event.startsWith('exec') ? 'exec' : 'plugin'
      const request = payload.request ?? {}
      const owner = request.sessionKey ?? payload.sessionKey
      if (owner && owner !== sessionKey) return
      const approval = approvalEvent(kind, payload)
      if (!approval.id) return
      const key = grantKey(approval)
      lastActivity = Date.now()
      if (grants.has(key)) {
        gateway.call(kind === 'exec' ? 'exec.approval.resolve' : 'plugin.approval.resolve', { id: approval.id, decision: 'allow-once' })
          .then(() => emit({ type: 'approval_auto', id: approval.id, title: approval.title, description: approval.description }))
          .catch((error) => emit({ type: 'approval_error', id: approval.id, message: String(error.message).slice(0, 300) }))
        return
      }
      pendingApprovals.set(approval.id, { kind, key })
      emit(approval)
      return
    }
    if (event === 'plugin.approval.resolved' || event === 'exec.approval.resolved') {
      if (typeof payload.id === 'string' && pendingApprovals.delete(payload.id)) {
        lastActivity = Date.now()
        emit({ type: 'approval_resolved', id: payload.id, decision: String(payload.decision ?? '') })
      }
      return
    }
    if (payload.sessionKey !== sessionKey || (runId && payload.runId && payload.runId !== runId)) return
    // Only real progress resets the stall watchdog: a model call starting, a tool starting or ending,
    // or reply text. OpenClaw keeps sending status and lifecycle events while a run is stuck (for
    // example on a tool that never returns), so those do not count.
    if (event === 'agent') {
      const data = payload.data ?? {}
      if (payload.stream === 'lifecycle' && data.phase === 'model' && data.model) { model = String(data.model); lastActivity = Date.now() }
      // A tool run through dispatch_action is reported twice; keep the outer entry only.
      const nested = String(data.toolCallId ?? '').startsWith('tool_call:')
      if (payload.stream === 'item' && data.kind === 'tool' && (data.phase === 'start' || data.phase === 'end')) lastActivity = Date.now()
      if (payload.stream === 'item' && data.kind === 'tool' && !nested && (data.phase === 'start' || data.phase === 'end')) {
        emit({
          type: 'tool',
          phase: data.phase,
          id: String(data.toolCallId ?? data.itemId ?? ''),
          name: String(data.name ?? ''),
          title: String(data.title ?? data.name ?? ''),
          status: String(data.status ?? ''),
          error: cleanToolError(data.error),
        })
      }
      return
    }
    if (event !== 'chat') return
    if (payload.state === 'status') {
      emit({ type: 'status', phase: String(payload.phase ?? '') })
    } else if (payload.state === 'delta') {
      lastActivity = Date.now()
      if (payload.replace === true) {
        text = messageText(payload.message)
        emit({ type: 'replace', text })
      } else if (typeof payload.deltaText === 'string' && payload.deltaText) {
        text += payload.deltaText
        emit({ type: 'delta', text: payload.deltaText })
      }
    } else if (TERMINAL_CHAT_STATES.has(payload.state)) {
      if (payload.state === 'final') {
        const finalText = messageText(payload.message) || text
        finish({ type: 'final', text: finalText, model, durationMs: Date.now() - startedAt, stopReason: String(payload.stopReason ?? ''), ...(subtask ? { subtaskId: subtask.id } : {}) })
      } else if (payload.state === 'aborted') {
        finish({ type: 'error', code: 'aborted', message: 'The OpenClaw turn was stopped.' })
      } else {
        fail('turn_failed', explainTurnError(String(payload.errorMessage ?? payload.error?.message ?? 'OpenClaw could not complete this turn.')).slice(0, 600))
      }
    }
  }

  commands.onLine = (line) => {
    let command
    try { command = JSON.parse(line) } catch { return }
    if (command?.type === 'abort') {
      void abort('user')
    } else if (command?.type === 'approval' && typeof command.id === 'string') {
      const pending = pendingApprovals.get(command.id)
      if (!pending) return
      const { kind, key } = pending
      const decision = command.decision === 'allow-once' || command.decision === 'allow-task' ? 'allow-once' : 'deny'
      if (command.decision === 'allow-task') grants.add(key)
      gateway.call(kind === 'exec' ? 'exec.approval.resolve' : 'plugin.approval.resolve', { id: command.id, decision })
        .catch((error) => emit({ type: 'approval_error', id: command.id, message: String(error.message).slice(0, 300) }))
    }
  }
  // The parent closing stdin means it went away; do not leave an agent running unattended.
  commands.onClose = () => { void abort('user') }
  if (commands.closed) void abort('user')

  // OpenClaw's own session mode is opened fully; the permission plugin applies
  // the PockPock mode to every tool call instead (see pockpock-permissions.ts).
  // A conversation may pick one of the local or cloud models OpenClaw already knows; anything else is refused.
  const available = localModels()
  const requested = String(subtask?.model || start.model || '')
  const isCloud = available.cloud.includes(requested)
  if (requested && !isCloud && !available.models.includes(requested)) return fail('unknown_model', `OpenClaw has no model named "${requested}".`)
  const sessionModel = requested ? `${isCloud ? CLOUD_PROVIDER : 'ollama'}/${requested}` : available.model
  // Tool retrieval (tool_selection.py): skills and MCP servers that do not fit this message are hidden
  // for the session; null clears an earlier overlay. Only false entries are accepted, so nothing the
  // user switched off can be switched on here.
  const overlay = 'toolOverrides' in start && !subtask ? { toolOverrides: sanitizeToolOverrides(start.toolOverrides) } : {}
  // The working folder: commands run there and relative file paths resolve there. sessions.create on an
  // existing key keeps the conversation and updates its folder, so a folder changed between turns applies.
  // No folder chosen: back to OpenClaw's own workspace (a reset failing is not worth stopping the turn).
  const chosenFolder = typeof start.cwd === 'string' && start.cwd ? start.cwd : ''
  try {
    await gateway.call('sessions.create', { key: sessionKey, cwd: chosenFolder || defaultWorkspace() })
  } catch (error) {
    if (chosenFolder) return fail('workspace_failed', `OpenClaw could not work in ${chosenFolder}: ${String(error?.message ?? error).slice(0, 300)}`)
  }
  await gateway.call('sessions.patch', { key: sessionKey, permissionMode: 'full', ...(sessionModel ? { model: sessionModel } : {}), ...overlay })
  const sent = await gateway.call('chat.send', { sessionKey, message, idempotencyKey: crypto.randomUUID() })
  runId = String(sent?.runId ?? '')
  emit({ type: 'started', runId, ...(subtask ? { subtaskId: subtask.id } : {}) })
  setTimeout(() => { void abort('timeout') }, timeoutSeconds * 1000).unref()
  // Watchdog: a run that goes quiet (for example after a failed approval) would otherwise wait for the
  // full timeout. Approvals waiting for the user never count as quiet.
  lastActivity = Date.now()
  setInterval(() => {
    if (finished || aborting) return
    if (isStalled({ now: Date.now(), lastActivity, pendingApprovals: pendingApprovals.size, stallMs: stallSeconds * 1000 })) void abort('stalled')
  }, 15_000).unref()
}

// One reader owns stdin: the first line is the start request, later lines are commands.
const commands = { onLine: () => {}, onClose: () => {}, closed: false }

function readStart() {
  return new Promise((resolve, reject) => {
    let started = false
    const input = readline.createInterface({ input: process.stdin })
    input.on('line', (line) => {
      if (started) { commands.onLine(line); return }
      started = true
      try { resolve(JSON.parse(line)) } catch { reject(new Error('The turn request was not valid JSON.')) }
    })
    input.on('close', () => {
      commands.closed = true
      if (!started) reject(new Error('No turn request was received.'))
      else commands.onClose()
    })
  })
}

try {
  const start = await readStart()
  if (start?.type !== 'start') throw new Error('The first message must be a start request.')
  await run(start)
} catch (error) {
  fail('bridge_failed', String(error?.message ?? error).slice(0, 600))
}
