// Starts, stops and watches every local service PockPock needs. Services the app started are
// stopped when it quits (unless the user chose to keep them); services that were already running
// are adopted for status and can still be stopped from the Services page.
const crypto = require('node:crypto')
const fs = require('node:fs')
const http = require('node:http')
const net = require('node:net')
const path = require('node:path')
const { spawn, execFile } = require('node:child_process')
const paths = require('./paths.cjs')

const CHECK_INTERVAL_MS = 4000
const STARTUP_TIMEOUT_MS = 60000
const NEMOCLAW_SANDBOX = process.env.POCKPOCK_NEMOCLAW_SANDBOX || 'pockpock'
const WSL_PREFIX = 'export PATH="$HOME/.local/bin:$PATH"; '

/** Ordered as they start; stopping goes in reverse. */
const DEFINITIONS = [
  { id: 'ollama', name: 'Ollama', group: 'Models', port: 11434, description: 'Runs the local AI models.' },
  { id: 'planner', name: 'Planner', group: 'Backend', port: 8771, project: 'planner', description: 'Plans agent tasks and picks a model.' },
  { id: 'validator', name: 'Validator', group: 'Backend', port: 8772, project: 'validator', description: 'Checks agent workspaces.' },
  { id: 'run-store', name: 'Run store', group: 'Backend', port: 8773, project: 'run_store', description: 'Saves agent runs and their events.' },
  { id: 'browser-automation', name: 'Browser automation', group: 'Backend', port: 8774, project: 'browser_automation', description: 'Isolated browser for agent web tasks.' },
  { id: 'gateway', name: 'PockPock gateway', group: 'Backend', port: 8766, description: 'The API the app talks to: chat, agents, approvals.' },
  { id: 'openclaw', name: 'OpenClaw gateway', group: 'Agents', port: 18810, description: 'Runs the OpenClaw engine on this PC.' },
  { id: 'nemoclaw', name: 'NemoClaw sandbox', group: 'Agents', port: 18789, description: 'OpenClaw in a WSL sandbox (needs Docker Desktop).' },
]

function httpJson(url, timeoutMs = 1500) {
  return new Promise((resolve) => {
    const request = http.get(url, { timeout: timeoutMs }, (response) => {
      let body = ''
      response.setEncoding('utf8')
      response.on('data', (chunk) => { if (body.length < 65536) body += chunk })
      response.on('end', () => {
        try { resolve({ status: response.statusCode, json: JSON.parse(body) }) } catch { resolve({ status: response.statusCode, json: null }) }
      })
    })
    request.on('timeout', () => { request.destroy(); resolve(null) })
    request.on('error', () => resolve(null))
  })
}

function portOpen(port, timeoutMs = 800) {
  return new Promise((resolve) => {
    const socket = net.connect({ host: '127.0.0.1', port })
    const done = (open) => { socket.destroy(); resolve(open) }
    socket.setTimeout(timeoutMs, () => done(false))
    socket.once('connect', () => done(true))
    socket.once('error', () => done(false))
  })
}

function run(file, args, options = {}) {
  return new Promise((resolve) => {
    execFile(file, args, { windowsHide: true, timeout: options.timeout ?? 120000, maxBuffer: 4 * 1024 * 1024, env: options.env ?? paths.cleanEnv(), cwd: options.cwd, shell: options.shell }, (error, stdout, stderr) => {
      resolve({ ok: !error, code: error?.code ?? 0, stdout: String(stdout || ''), stderr: String(stderr || '') })
    })
  })
}

function wsl(script, timeout = 180000) {
  return run('wsl.exe', ['-e', 'bash', '-lc', WSL_PREFIX + script], { timeout })
}

async function pidsOnPort(port) {
  const result = await run('netstat.exe', ['-ano', '-p', 'tcp'], { timeout: 10000 })
  const pids = new Set()
  for (const line of result.stdout.split(/\r?\n/)) {
    const parts = line.trim().split(/\s+/)
    if (parts[0] === 'TCP' && parts[3] === 'LISTENING' && /[:.]\d+$/.test(parts[1]) && parts[1].endsWith(`:${port}`)) pids.add(Number(parts[4]))
  }
  return [...pids].filter((pid) => pid > 0)
}

function killTree(pid) {
  return run('taskkill.exe', ['/PID', String(pid), '/T', '/F'], { timeout: 20000 })
}

function internalToken() {
  const file = path.join(paths.dataRoot(), 'services.token')
  fs.mkdirSync(paths.dataRoot(), { recursive: true })
  try {
    const token = fs.readFileSync(file, 'utf8').trim()
    if (token) return token
  } catch { /* create below */ }
  const token = crypto.randomBytes(32).toString('base64url')
  fs.writeFileSync(file, `${token}\n`, { encoding: 'utf8', flag: 'w' })
  return token
}

function tail(file, lines = 200) {
  try {
    const stat = fs.statSync(file)
    const size = Math.min(stat.size, 128 * 1024)
    const handle = fs.openSync(file, 'r')
    const buffer = Buffer.alloc(size)
    fs.readSync(handle, buffer, 0, size, stat.size - size)
    fs.closeSync(handle)
    return buffer.toString('utf8').split(/\r?\n/).slice(-lines).join('\n')
  } catch {
    return ''
  }
}

class ServiceManager {
  constructor({ onChange, settings }) {
    this.onChange = onChange
    this.settings = settings
    this.children = new Map() // id -> child process started by this app
    this.started = new Set() // ids this app started (including ones that detach, like OpenClaw)
    this.busy = new Map() // id -> 'starting' | 'stopping'
    this.errors = new Map()
    this.state = new Map(DEFINITIONS.map((definition) => [definition.id, { ...definition, status: 'checking', detail: '', startedByApp: false, available: true }]))
    this.nemoInstalled = null
    this.timer = null
  }

  list() {
    return DEFINITIONS.map((definition) => this.state.get(definition.id))
  }

  emit() {
    this.onChange(this.list())
  }

  async availability(definition) {
    if (definition.project || definition.id === 'gateway') {
      if (!fs.existsSync(paths.venvPython())) return 'PockPock is not set up yet. Run Setup.'
      if (!fs.existsSync(paths.backendRoot())) return `The backend was not found at ${paths.backendRoot()}.`
      return ''
    }
    if (definition.id === 'ollama') return paths.ollamaExe() ? '' : 'Ollama is not installed. Run Setup.'
    if (definition.id === 'openclaw') return paths.openclawEntry() ? '' : 'OpenClaw is not installed. Run Setup.'
    if (definition.id === 'nemoclaw') {
      if (this.nemoInstalled === null) {
        if (!paths.findExecutable(['wsl.exe'])) this.nemoInstalled = false
        else {
          const listing = await wsl('nemoclaw list --json 2>/dev/null', 30000)
          try {
            const parsed = JSON.parse(listing.stdout.replace(/\0/g, ''))
            this.nemoInstalled = Array.isArray(parsed.sandboxes) && parsed.sandboxes.some((sandbox) => sandbox.name === NEMOCLAW_SANDBOX)
          } catch { this.nemoInstalled = false }
        }
      }
      return this.nemoInstalled ? '' : `NemoClaw with a "${NEMOCLAW_SANDBOX}" sandbox is not installed in WSL. Run Setup.`
    }
    return ''
  }

  async healthy(definition) {
    if (definition.id === 'ollama') return Boolean((await httpJson('http://127.0.0.1:11434/api/version'))?.status === 200)
    if (definition.id === 'gateway') return (await httpJson('http://127.0.0.1:8766/api/health'))?.status === 200
    if (definition.project) {
      const reply = await httpJson(`http://127.0.0.1:${definition.port}/health`)
      return Boolean(reply?.json?.ok === true && reply.json.service === definition.id)
    }
    return portOpen(definition.port)
  }

  async check(definition) {
    const current = this.state.get(definition.id)
    const unavailable = await this.availability(definition)
    const running = unavailable ? false : await this.healthy(definition)
    const busy = this.busy.get(definition.id)
    const error = this.errors.get(definition.id)
    const next = {
      ...current,
      available: !unavailable,
      startedByApp: this.started.has(definition.id),
      status: busy ?? (unavailable ? 'unavailable' : running ? 'running' : error ? 'error' : 'stopped'),
      detail: unavailable || (busy === 'starting' ? 'Starting…' : busy === 'stopping' ? 'Stopping…' : running ? (this.started.has(definition.id) ? 'Started by PockPock Agent' : 'Running') : error || 'Not running'),
    }
    this.state.set(definition.id, next)
    return next
  }

  async refresh() {
    await Promise.all(DEFINITIONS.map((definition) => this.check(definition)))
    this.emit()
    return this.list()
  }

  watch() {
    if (this.timer) return
    void this.refresh()
    this.timer = setInterval(() => void this.refresh(), CHECK_INTERVAL_MS)
  }

  serviceEnv() {
    return paths.cleanEnv({
      PYTHONUNBUFFERED: '1',
      POCKPOCK_INTERNAL_TOKEN: internalToken(),
      POCKPOCK_PLANNER_URL: 'http://127.0.0.1:8771',
      POCKPOCK_VALIDATOR_URL: 'http://127.0.0.1:8772',
      POCKPOCK_RUN_STORE_URL: 'http://127.0.0.1:8773',
      POCKPOCK_BROWSER_AUTOMATION_URL: 'http://127.0.0.1:8774',
      FROG_AI_PORT: '8766',
    })
  }

  logFile(id) {
    if (id === 'openclaw') {
      const day = new Date().toISOString().slice(0, 10)
      return path.join(process.env.LOCALAPPDATA || '', 'Temp', 'openclaw', `openclaw-${day}.log`)
    }
    if (id === 'ollama' && !this.children.has('ollama')) return path.join(paths.LOCAL, 'Ollama', 'server.log')
    return path.join(paths.logsRoot(), `${id === 'gateway' ? 'PockPock AI' : id}.log`)
  }

  logs(id) {
    const definition = DEFINITIONS.find((item) => item.id === id)
    if (!definition) throw new Error('Unknown service.')
    const file = this.logFile(id)
    return { file, text: tail(file) || 'No log output yet.' }
  }

  spawnLogged(id, file, args, options) {
    const logPath = this.logFile(id)
    const log = fs.openSync(logPath, 'a')
    fs.writeSync(log, `\n=== ${new Date().toISOString()} started by PockPock Agent ===\n`)
    const child = spawn(file, args, { ...options, windowsHide: true, stdio: ['ignore', log, log] })
    fs.closeSync(log)
    this.children.set(id, child)
    child.on('exit', (code) => {
      this.children.delete(id)
      if (this.busy.get(id) !== 'stopping' && code !== 0 && code !== null) this.errors.set(id, `Stopped unexpectedly (exit code ${code}). See the log.`)
      void this.refresh()
    })
    return child
  }

  async waitUntil(definition, wantRunning, timeoutMs = STARTUP_TIMEOUT_MS) {
    const deadline = Date.now() + timeoutMs
    while (Date.now() < deadline) {
      if ((await this.healthy(definition)) === wantRunning) return true
      if (wantRunning && definition.project && !this.children.has(definition.id) && this.started.has(definition.id)) return false
      await new Promise((resolve) => setTimeout(resolve, 700))
    }
    return false
  }

  async start(id) {
    const definition = DEFINITIONS.find((item) => item.id === id)
    if (!definition) throw new Error('Unknown service.')
    if (this.busy.has(id)) return this.state.get(id)
    const unavailable = await this.availability(definition)
    if (unavailable) throw new Error(unavailable)
    if (await this.healthy(definition)) return this.check(definition)
    this.busy.set(id, 'starting')
    this.errors.delete(id)
    await this.check(definition)
    this.emit()
    try {
      await this.launch(definition)
      this.started.add(id)
      const ok = await this.waitUntil(definition, true, id === 'nemoclaw' ? 240000 : STARTUP_TIMEOUT_MS)
      if (!ok) this.errors.set(id, `Did not start within ${id === 'nemoclaw' ? 4 : 1} minute${id === 'nemoclaw' ? 's' : ''}. See the log.`)
    } catch (error) {
      this.errors.set(id, error instanceof Error ? error.message : String(error))
    } finally {
      this.busy.delete(id)
    }
    return this.check(definition).then((state) => { this.emit(); return state })
  }

  async launch(definition) {
    const env = this.serviceEnv()
    const python = paths.venvPython()
    if (definition.project) {
      this.spawnLogged(definition.id, python, ['-m', 'uvicorn', 'app:app', '--host', '127.0.0.1', '--port', String(definition.port)], { cwd: path.join(paths.backendRoot(), 'projects', definition.project), env })
    } else if (definition.id === 'gateway') {
      this.spawnLogged('gateway', python, ['-u', path.join(paths.backendRoot(), 'scripts', 'frog_ai_server.py')], { cwd: path.dirname(paths.backendRoot()), env })
    } else if (definition.id === 'ollama') {
      this.spawnLogged('ollama', paths.ollamaExe(), ['serve'], { env: paths.cleanEnv() })
    } else if (definition.id === 'openclaw') {
      const entry = paths.openclawEntry()
      if (!entry) throw new Error('OpenClaw was not found.')
      const result = await run(entry.node, [entry.script, 'gateway', 'start'], { timeout: 120000 })
      fs.appendFileSync(path.join(paths.logsRoot(), 'openclaw-start.log'), `\n=== ${new Date().toISOString()}\n${result.stdout}${result.stderr}`)
      if (!result.ok && !(await portOpen(definition.port))) throw new Error((result.stderr || result.stdout).trim().split('\n').slice(-3).join(' ') || 'openclaw gateway start failed.')
    } else if (definition.id === 'nemoclaw') {
      await this.ensureDocker()
      const result = await wsl(`nemoclaw ${NEMOCLAW_SANDBOX} start 2>&1`, 300000)
      fs.appendFileSync(this.logFile('nemoclaw'), `\n=== ${new Date().toISOString()} start\n${result.stdout.replace(/\0/g, '')}`)
      if (!result.ok && !(await portOpen(definition.port))) throw new Error('nemoclaw start failed. See the log.')
    }
  }

  async ensureDocker() {
    if ((await run('docker.exe', ['info', '--format', '{{.ServerVersion}}'], { timeout: 15000 })).ok) return
    const desktop = path.join(process.env.ProgramFiles || 'C:\\Program Files', 'Docker', 'Docker', 'Docker Desktop.exe')
    if (!fs.existsSync(desktop)) throw new Error('Docker Desktop is not installed. NemoClaw needs it.')
    spawn(desktop, [], { detached: true, stdio: 'ignore', windowsHide: true }).unref()
    for (let attempt = 0; attempt < 60; attempt += 1) {
      await new Promise((resolve) => setTimeout(resolve, 3000))
      if ((await run('docker.exe', ['info', '--format', '{{.ServerVersion}}'], { timeout: 15000 })).ok) return
    }
    throw new Error('Docker Desktop did not start within 3 minutes.')
  }

  async stop(id) {
    const definition = DEFINITIONS.find((item) => item.id === id)
    if (!definition) throw new Error('Unknown service.')
    if (this.busy.has(id)) return this.state.get(id)
    this.busy.set(id, 'stopping')
    this.errors.delete(id)
    await this.check(definition)
    this.emit()
    try {
      if (id === 'openclaw') { const entry = paths.openclawEntry(); if (entry) await run(entry.node, [entry.script, 'gateway', 'stop'], { timeout: 60000 }) }
      else if (id === 'nemoclaw') await wsl(`nemoclaw ${NEMOCLAW_SANDBOX} stop 2>&1`, 180000)
      else {
        const child = this.children.get(id)
        if (child?.pid) await killTree(child.pid)
        for (const pid of await pidsOnPort(definition.port)) await killTree(pid)
        if (id === 'ollama') {
          // The Ollama tray app restarts the server, so it is closed too.
          await run('taskkill.exe', ['/IM', 'ollama app.exe', '/T', '/F'], { timeout: 15000 })
          await run('taskkill.exe', ['/IM', 'ollama.exe', '/T', '/F'], { timeout: 15000 })
        }
      }
      await this.waitUntil(definition, false, 30000)
      this.started.delete(id)
    } catch (error) {
      this.errors.set(id, error instanceof Error ? error.message : String(error))
    } finally {
      this.busy.delete(id)
    }
    return this.check(definition).then((state) => { this.emit(); return state })
  }

  async startAll({ includeNemo = true } = {}) {
    const results = []
    const step = async (id) => {
      try { results.push(await this.start(id)) } catch (error) { this.errors.set(id, error instanceof Error ? error.message : String(error)) }
    }
    await step('ollama')
    await Promise.all(['planner', 'validator', 'run-store', 'browser-automation'].map(step))
    await step('gateway')
    await step('openclaw')
    if (includeNemo) await step('nemoclaw')
    await this.refresh()
    return results
  }

  async stopAll(onlyStartedByApp = false) {
    for (const definition of [...DEFINITIONS].reverse()) {
      if (onlyStartedByApp && !this.started.has(definition.id)) continue
      const state = this.state.get(definition.id)
      if (!onlyStartedByApp && state?.status !== 'running') continue
      await this.stop(definition.id)
    }
  }

  /** Synchronous best effort for app quit: end the child processes this app owns. */
  killOwnedSync() {
    const { spawnSync } = require('node:child_process')
    for (const child of this.children.values()) {
      if (child.pid) spawnSync('taskkill.exe', ['/PID', String(child.pid), '/T', '/F'], { windowsHide: true })
    }
    this.children.clear()
  }
}

module.exports = { ServiceManager, DEFINITIONS, httpJson, run, wsl }
