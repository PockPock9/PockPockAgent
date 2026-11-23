// Reads and changes OpenClaw's MCP server list through the local Gateway WebSocket.
//
// The OpenClaw CLI refuses MCP changes while the Gateway is running, so PockPock asks the
// Gateway itself. stdin: one JSON line {"op":"mcp_list"} | {"op":"mcp_set","name","server","replace"}
// | {"op":"mcp_remove","name"} | {"op":"mcp_enable","name","enabled"} | {"op":"skills_list"}
// | {"op":"skill_enable","name","enabled"} | {"op":"mcp_export","name"}. stdout: one JSON line. Server
// definitions (which may hold keys) arrive on stdin. Environment values and headers are written to stdout
// only by mcp_export, which the gateway calls to move a server PockPock installed into Local MCP; the
// gateway reads that line from the pipe and sends it on to Local MCP, and never logs it.
import fs from 'node:fs'
import os from 'node:os'
import path from 'node:path'

const STATE_DIR = process.env.OPENCLAW_STATE_DIR || path.join(os.homedir(), '.openclaw')
const CONFIG_PATH = process.env.OPENCLAW_CONFIG_PATH || path.join(STATE_DIR, 'openclaw.json')
const TIMEOUT_MS = 30_000

let finished = false
function finish(result, code = 0) {
  if (finished) return
  finished = true
  process.stdout.write(`${JSON.stringify(result)}\n`, () => process.exit(code))
}
const fail = (code, message) => finish({ ok: false, code, message }, 1)

function summarize(servers) {
  const result = {}
  for (const [name, server] of Object.entries(servers || {})) {
    if (!server || typeof server !== 'object') continue
    result[name] = {
      transport: server.url ? (server.transport || 'streamable-http') : 'stdio',
      command: typeof server.command === 'string' ? server.command : '',
      args: Array.isArray(server.args) ? server.args.map(String) : [],
      url: typeof server.url === 'string' ? server.url : '',
      envKeys: Object.keys(server.env || {}),
      hasHeaders: Object.keys(server.headers || {}).length > 0,
      enabled: server.enabled !== false,
    }
  }
  return result
}

async function main() {
  const input = await new Promise((resolve) => {
    let text = ''
    process.stdin.setEncoding('utf8')
    process.stdin.on('data', (chunk) => { text += chunk })
    process.stdin.on('end', () => resolve(text))
  })
  let request
  try { request = JSON.parse(input) } catch { return fail('bad_request', 'The request was not valid JSON.') }

  let config
  try { config = JSON.parse(fs.readFileSync(CONFIG_PATH, 'utf8')) } catch { return fail('not_installed', 'OpenClaw is not set up on this PC.') }
  const port = Number(process.env.OPENCLAW_GATEWAY_PORT || config?.gateway?.port || 18789)
  const token = config?.gateway?.auth?.token
  if (typeof token !== 'string' || !token) return fail('not_installed', 'The OpenClaw gateway has no token configured.')

  const socket = new WebSocket(`ws://127.0.0.1:${port}`)
  const pending = new Map()
  let sequence = 0
  const call = (method, params) => new Promise((resolve, reject) => {
    const id = `ppx${++sequence}`
    const timer = setTimeout(() => { pending.delete(id); reject(new Error(`OpenClaw gateway request ${method} timed out.`)) }, TIMEOUT_MS)
    pending.set(id, { resolve, reject, timer })
    socket.send(JSON.stringify({ type: 'req', id, method, params }))
  })
  socket.addEventListener('error', () => fail('gateway_offline', 'The OpenClaw gateway is not running. Start it with `openclaw gateway start`.'))
  socket.addEventListener('close', () => fail('gateway_offline', 'The OpenClaw gateway closed the connection.'))
  socket.addEventListener('message', (message) => {
    let frame
    try { frame = JSON.parse(message.data) } catch { return }
    if (frame.type === 'res') {
      const entry = pending.get(frame.id)
      if (!entry) return
      pending.delete(frame.id)
      clearTimeout(entry.timer)
      if (frame.ok) entry.resolve(frame.payload)
      else entry.reject(Object.assign(new Error(frame.error?.message || 'Gateway request failed.'), { code: frame.error?.code }))
    } else if (frame.type === 'event' && frame.event === 'connect.challenge') {
      call('connect', {
        minProtocol: 4,
        maxProtocol: 4,
        client: { id: 'gateway-client', version: '1.0.0', platform: process.platform, mode: 'backend' },
        role: 'operator',
        scopes: ['operator.read', 'operator.write', 'operator.admin'],
        caps: [],
        commands: [],
        permissions: {},
        auth: { token },
        locale: 'en-US',
        userAgent: 'pockpock-extensions/1.0.0',
      }).then(() => run(request, call, config), (error) => fail('gateway_refused', error.message))
    }
  })
}

async function run(request, call, fileConfig) {
  try {
    const servers = async () => {
      const snapshot = await call('config.get', {})
      const source = snapshot.parsed || snapshot.config || {}
      return { hash: snapshot.hash, servers: source.mcp?.servers || {} }
    }
    if (request.op === 'mcp_list') {
      return finish({ ok: true, servers: summarize((await servers()).servers) })
    }
    if (request.op === 'mcp_export') {
      // From the config file, not config.get: the gateway's copy replaces secret values with
      // "__OPENCLAW_REDACTED__", and the real ones are needed to move the server into Local MCP.
      const name = String(request.name || '')
      const server = fileConfig?.mcp?.servers?.[name]
      if (!/^[a-z0-9][a-z0-9-]{0,39}$/.test(name) || !server || typeof server !== 'object') return fail('not_found', `OpenClaw has no MCP server named "${name}".`)
      const text = (value) => (typeof value === 'string' ? value : '')
      const strings = (value) => Object.fromEntries(Object.entries(value && typeof value === 'object' ? value : {}).filter(([, item]) => typeof item === 'string'))
      return finish({
        ok: true,
        server: {
          transport: server.url ? (server.transport || 'streamable-http') : 'stdio',
          command: text(server.command), args: Array.isArray(server.args) ? server.args.map(String) : [],
          env: strings(server.env), url: text(server.url), headers: strings(server.headers), enabled: server.enabled !== false,
        },
      })
    }
    if (request.op === 'skills_list') {
      const status = await call('skills.status', {})
      return finish({
        ok: true,
        skills: (status.skills || []).map((skill) => ({
          name: String(skill.name || ''),
          key: String(skill.skillKey || skill.name || ''),
          description: String(skill.description || '').slice(0, 400),
          source: String(skill.source || ''),
          eligible: skill.eligible === true,
          disabled: skill.disabled === true,
          missing: [...(skill.missing?.bins || []), ...(skill.missing?.anyBins || []), ...(skill.missing?.env || []), ...(skill.missing?.os || [])].map(String).slice(0, 8),
        })),
      })
    }
    if (request.op === 'skill_enable' || request.op === 'mcp_enable') {
      const key = String(request.name || '')
      if (!/^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$/.test(key)) return fail('bad_request', 'The name is not valid.')
      const enabled = request.enabled === true
      const current = await servers()
      if (request.op === 'mcp_enable' && !Object.hasOwn(current.servers, key)) return fail('not_found', `OpenClaw has no MCP server named "${key}".`)
      const patch = request.op === 'mcp_enable' ? { mcp: { servers: { [key]: { enabled } } } } : { skills: { entries: { [key]: { enabled } } } }
      await call('config.patch', { raw: JSON.stringify(patch), baseHash: current.hash, note: 'PockPock extensions' })
      return finish({ ok: true, enabled })
    }
    if (request.op !== 'mcp_set' && request.op !== 'mcp_remove') return fail('bad_request', 'Unknown operation.')
    const name = String(request.name || '')
    if (!/^[a-z0-9][a-z0-9-]{0,39}$/.test(name)) return fail('bad_request', 'The server name is not valid.')
    // The config may change between read and write; one retry covers a concurrent edit.
    for (let attempt = 0; ; attempt += 1) {
      const current = await servers()
      const exists = Object.hasOwn(current.servers, name)
      if (request.op === 'mcp_set' && exists && !request.replace) return fail('exists', `OpenClaw already has an MCP server named "${name}".`)
      if (request.op === 'mcp_remove' && !exists) return finish({ ok: true, removed: false })
      const patch = { mcp: { servers: { [name]: request.op === 'mcp_set' ? request.server : null } } }
      // A merge patch would keep stale fields of a replaced server, so remove it first.
      const steps = request.op === 'mcp_set' && exists ? [{ mcp: { servers: { [name]: null } } }, patch] : [patch]
      try {
        let hash = current.hash
        for (const step of steps) {
          const params = { raw: JSON.stringify(step), baseHash: hash, note: 'PockPock extensions' }
          let applied
          try {
            applied = await call('config.patch', params)
          } catch (error) {
            // Deleting a server drops its argument list, which the gateway wants named explicitly.
            const named = /array path\(s\): (.+?)\. Pass replacePaths/.exec(error.message)?.[1].split(/,\s*/) ?? []
            const prefix = `mcp.servers.${name}`
            if (!named.length || !named.every((item) => item === prefix || item.startsWith(`${prefix}.`))) throw error
            applied = await call('config.patch', { ...params, replacePaths: named })
          }
          hash = applied.hash
        }
        return finish({ ok: true, removed: request.op === 'mcp_remove' })
      } catch (error) {
        if (attempt === 0 && /hash/i.test(error.message)) continue
        return fail('config_rejected', `OpenClaw did not accept the change: ${error.message}`)
      }
    }
  } catch (error) {
    fail('gateway_failed', error.message)
  }
}

main()
