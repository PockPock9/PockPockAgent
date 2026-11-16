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
import { cleanToolError, DEFAULT_STALL_SECONDS, isStalled } from './turn_helpers.mjs'

const DEBUG = process.env.POCKPOCK_OPENCLAW_DEBUG === '1'
const STATE_DIR = process.env.OPENCLAW_STATE_DIR || path.join(os.homedir(), '.openclaw')
const CONFIG_PATH = process.env.OPENCLAW_CONFIG_PATH || path.join(STATE_DIR, 'openclaw.json')
const PLUGIN_STATUS_METHOD = 'pockpock.permissions.status'
const CONNECT_TIMEOUT_MS = 20_000
const RPC_TIMEOUT_MS = 30_000
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

/** The default model and the tool-capable Ollama models in OpenClaw's config. */
function localModels() {
  try {
    const config = JSON.parse(fs.readFileSync(CONFIG_PATH, 'utf8'))
    const listed = config?.models?.providers?.ollama?.models
    return {
      model: String(config?.agents?.defaults?.model?.primary ?? ''),
      models: (Array.isArray(listed) ? listed : [])
        .filter((entry) => entry && typeof entry.id === 'string' && entry.compat?.supportsTools !== false)
        .map((entry) => entry.id),
    }
  } catch {
    return { model: '', models: [] } // Status still reports the gateway as reachable.
  }
}

async function run(start) {
  const sessionKey = `agent:${start.agent}:explicit:${start.sessionId}`
  const gateway = new Gateway(loadGateway())
  await gateway.connected

  if (start.statusOnly) {
    let plugin = false
    try { plugin = (await gateway.call(PLUGIN_STATUS_METHOD, {}))?.ok === true } catch { plugin = false }
    const { model, models } = localModels()
    finish({ type: 'status_result', gateway: true, plugin, model, models })
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
  const pendingApprovals = new Map()
  let aborting = false
  let lastActivity = Date.now()
  const stallSeconds = Number(start.stallSeconds) > 0 ? Number(start.stallSeconds) : DEFAULT_STALL_SECONDS

  const abort = async (reason) => {
    if (aborting || finished) return
    aborting = true
    for (const [id, kind] of pendingApprovals) {
      gateway.call(kind === 'exec' ? 'exec.approval.resolve' : 'plugin.approval.resolve', { id, decision: 'deny' }).catch(() => {})
    }
    try { await gateway.call('chat.abort', runId ? { sessionKey, runId } : { sessionKey }, 5_000) } catch { /* The run may already be over. */ }
    if (reason === 'timeout') fail('timeout', `OpenClaw did not finish within ${start.timeoutSeconds} seconds, so the turn was stopped.`)
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
      pendingApprovals.set(approval.id, kind)
      lastActivity = Date.now()
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
    lastActivity = Date.now() // any event for this turn is progress (tokens, tools, status)
    if (event === 'agent') {
      const data = payload.data ?? {}
      if (payload.stream === 'lifecycle' && data.phase === 'model' && data.model) model = String(data.model)
      // A tool run through dispatch_action is reported twice; keep the outer entry only.
      const nested = String(data.toolCallId ?? '').startsWith('tool_call:')
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
        finish({ type: 'final', text: finalText, model, durationMs: Date.now() - startedAt, stopReason: String(payload.stopReason ?? '') })
      } else if (payload.state === 'aborted') {
        finish({ type: 'error', code: 'aborted', message: 'The OpenClaw turn was stopped.' })
      } else {
        fail('turn_failed', String(payload.errorMessage ?? payload.error?.message ?? 'OpenClaw could not complete this turn.').slice(0, 600))
      }
    }
  }

  commands.onLine = (line) => {
    let command
    try { command = JSON.parse(line) } catch { return }
    if (command?.type === 'abort') {
      void abort('user')
    } else if (command?.type === 'approval' && typeof command.id === 'string') {
      const kind = pendingApprovals.get(command.id)
      if (!kind) return
      const decision = command.decision === 'allow-once' ? 'allow-once' : 'deny'
      gateway.call(kind === 'exec' ? 'exec.approval.resolve' : 'plugin.approval.resolve', { id: command.id, decision })
        .catch((error) => emit({ type: 'approval_error', id: command.id, message: String(error.message).slice(0, 300) }))
    }
  }
  // The parent closing stdin means it went away; do not leave an agent running unattended.
  commands.onClose = () => { void abort('user') }
  if (commands.closed) void abort('user')

  // OpenClaw's own session mode is opened fully; the permission plugin applies
  // the PockPock mode to every tool call instead (see pockpock-permissions.ts).
  // A conversation may pick one of the local models OpenClaw already knows; anything else is refused.
  const available = localModels()
  const requested = String(start.model || '')
  if (requested && !available.models.includes(requested)) return fail('unknown_model', `OpenClaw has no local model named "${requested}".`)
  const sessionModel = requested ? `ollama/${requested}` : available.model
  await gateway.call('sessions.patch', { key: sessionKey, permissionMode: 'full', ...(sessionModel ? { model: sessionModel } : {}) })
  const sent = await gateway.call('chat.send', { sessionKey, message: start.message, idempotencyKey: crypto.randomUUID() })
  runId = String(sent?.runId ?? '')
  emit({ type: 'started', runId })
  setTimeout(() => { void abort('timeout') }, start.timeoutSeconds * 1000).unref()
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
