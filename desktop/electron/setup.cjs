// First-run setup: installs and configures everything PockPock needs, skipping what is already
// there, then starts every service and checks it works. Components: core (Python backend), ollama
// (+ default models), openclaw (+ skills choice), nemoclaw (sandbox + Docker). The operating-system
// specific parts live in setup-win.cjs and setup-mac.cjs. Progress streams to the renderer; a plan
// that needs a restart or a user action is saved and resumed on the next run.
const fs = require('node:fs')
const https = require('node:https')
const http = require('node:http')
const os = require('node:os')
const path = require('node:path')
const { spawn } = require('node:child_process')
const paths = require('./paths.cjs')
const platform = require('./platform.cjs')
const { DEFINITIONS, httpJson } = require('./services.cjs')

const host = paths.IS_MAC ? require('./setup-mac.cjs') : require('./setup-win.cjs')
const { run } = platform

const DEFAULT_MODEL = 'qwen3.5:9b'
const ROUTER_MODEL = 'qwen2.5:1.5b' // the Smart Router's classifier
const MODELS = [DEFAULT_MODEL, ROUTER_MODEL]
const NEMOCLAW_ENV = `NEMOCLAW_NO_EXPRESS=1 NEMOCLAW_NON_INTERACTIVE=1 NEMOCLAW_PROVIDER=ollama NEMOCLAW_MODEL=${DEFAULT_MODEL} NEMOCLAW_SANDBOX_NAME=pockpock NEMOCLAW_CONTEXT_WINDOW=32768 NEMOCLAW_ACCEPT_THIRD_PARTY_SOFTWARE=1`
const OPENCLAW_HOME = path.join(os.homedir(), '.openclaw')
const BUNDLED_SKILLS = require('./openclaw-skills.json').skills
const COMPONENTS = ['core', 'ollama', 'openclaw', 'nemoclaw']

class SetupError extends Error {}

function download(url, dest, onProgress, redirects = 5) {
  return new Promise((resolve, reject) => {
    const client = url.startsWith('https:') ? https : http
    client.get(url, { headers: { 'User-Agent': 'PockPock-Agent-Setup' } }, (response) => {
      if (response.statusCode >= 300 && response.statusCode < 400 && response.headers.location && redirects > 0) {
        response.resume()
        resolve(download(new URL(response.headers.location, url).href, dest, onProgress, redirects - 1))
        return
      }
      if (response.statusCode !== 200) { response.resume(); reject(new SetupError(`Download failed (HTTP ${response.statusCode}): ${url}`)); return }
      const total = Number(response.headers['content-length'] || 0)
      let received = 0
      const file = fs.createWriteStream(dest)
      response.on('data', (chunk) => { received += chunk.length; if (total) onProgress(received / total) })
      response.pipe(file)
      file.on('finish', () => file.close(() => resolve(dest)))
      file.on('error', reject)
    }).on('error', (error) => reject(new SetupError(`Download failed: ${error.message}. Check the internet connection and run setup again.`)))
  })
}

class Setup {
  constructor({ services, userData, emit }) {
    this.services = services
    this.stateFile = path.join(userData, 'setup.json')
    this.emit = emit
    this.child = null
    this.cancelled = false
    this.running = false
    this.liveSkills = null
  }

  /** Helpers handed to the operating-system installers. */
  get context() {
    return { download, SetupError, NEMOCLAW_ENV, services: this.services }
  }

  readState() {
    try { return JSON.parse(fs.readFileSync(this.stateFile, 'utf8')) } catch { return {} }
  }

  writeState(change) {
    const next = { ...this.readState(), ...change }
    fs.writeFileSync(this.stateFile, JSON.stringify(next, null, 2), 'utf8')
    return next
  }

  log(line) { this.emit({ type: 'log', line: String(line).split(String.fromCharCode(0)).join('').slice(0, 2000) }) }
  step(component, id, label, status, detail = '', progress) { this.emit({ type: 'step', component, id, label, status, detail, progress }) }

  /** Runs a program, streaming its output to the setup log. Resolves with the exit code. */
  exec(file, args, options = {}) {
    if (this.cancelled) return Promise.reject(new SetupError('Setup was cancelled.'))
    this.log(`> ${path.basename(file)} ${args.join(' ')}`.slice(0, 400))
    return new Promise((resolve, reject) => {
      const child = spawn(file, args, { cwd: options.cwd, env: options.env ?? paths.cleanEnv(), shell: options.shell ?? false, windowsHide: true, detached: !paths.IS_WIN })
      this.child = child
      let tail = ''
      const onData = (chunk) => {
        const text = chunk.toString('utf8').split(String.fromCharCode(0)).join('')
        tail = (tail + text).slice(-4000)
        for (const line of text.split(/\r?\n|\r/)) if (line.trim()) this.log(line)
      }
      child.stdout.on('data', onData)
      child.stderr.on('data', onData)
      child.on('error', (error) => { this.child = null; reject(new SetupError(`${path.basename(file)} could not start: ${error.message}`)) })
      child.on('exit', (code) => { this.child = null; resolve({ code: code ?? 1, tail }) })
    })
  }

  async must(file, args, what, options) {
    const result = await this.exec(file, args, options)
    if (result.code !== 0) throw new SetupError(`${what} failed (exit code ${result.code}). See the setup log.`)
    return result
  }

  // ---------- detection ----------

  async coreReady() {
    if (!fs.existsSync(paths.venvPython())) return false
    const result = await run(paths.venvPython(), ['-c', 'import fastapi, uvicorn, aiohttp, playwright, pypdf'], { timeout: 30000 })
    return result.ok
  }

  async ollamaModels() {
    const reply = await httpJson('http://127.0.0.1:11434/api/tags', 3000)
    return Array.isArray(reply?.json?.models) ? reply.json.models.map((model) => model.name) : null
  }

  async nemoInstalled() {
    if (!platform.nemoHostReady()) return false
    const listing = await platform.nemoShell('command -v nemoclaw >/dev/null 2>&1 && nemoclaw list --json 2>/dev/null', 30000)
    try { return JSON.parse(listing.stdout.split(String.fromCharCode(0)).join('')).sandboxes.some((sandbox) => sandbox.name === 'pockpock') } catch { return false }
  }

  /** Skills OpenClaw reports as usable on this computer, or the bundled list before it is installed. */
  async skills() {
    if (this.liveSkills) return this.liveSkills
    const entry = paths.openclawEntry()
    if (entry) {
      const listed = await run(entry.node, [entry.script, 'skills', 'list', '--json'], { timeout: 90000 })
      try {
        const start = listed.stdout.indexOf('{')
        const items = JSON.parse(listed.stdout.slice(start)).skills
        const eligible = items.filter((skill) => skill.eligible).map((skill) => ({ key: skill.name, name: skill.name, description: String(skill.description || '').slice(0, 300), source: skill.source }))
        if (eligible.length) { this.liveSkills = eligible; return eligible }
      } catch { /* fall back to the bundled list */ }
    }
    return BUNDLED_SKILLS
  }

  async status() {
    const models = await this.ollamaModels()
    const state = this.readState()
    const nemoSupport = platform.nemoSupported()
    const core = await this.coreReady()
    return {
      platform: process.platform,
      arch: os.arch(),
      core: { installed: core },
      ollama: { installed: Boolean(paths.ollamaExe()), running: models !== null, models: Object.fromEntries(MODELS.map((name) => [name, Boolean(models?.some((item) => item === name || item === `${name}:latest`))])) },
      openclaw: { installed: Boolean(paths.openclawCmd()) && fs.existsSync(path.join(OPENCLAW_HOME, 'openclaw.json')), cli: Boolean(paths.openclawCmd()), node: Boolean(paths.nodeExe()) },
      nemoclaw: { supported: nemoSupport.supported, reason: nemoSupport.reason, installed: nemoSupport.supported ? await this.nemoInstalled() : false, docker: Boolean(paths.dockerCli()) },
      winget: paths.IS_WIN ? host.packageManager() : true,
      skills: await this.skills(),
      pending: state.pending ?? null,
      lastRun: state.lastRun ?? null,
      verified: state.verified ?? null,
      needsSetup: !core,
    }
  }

  // ---------- run ----------

  async start(plan) {
    if (this.running) throw new SetupError('Setup is already running.')
    const nemoSupport = platform.nemoSupported()
    const components = COMPONENTS.filter((name) => name === 'core' || (plan.components.includes(name) && (name !== 'nemoclaw' || nemoSupport.supported)))
    const known = new Set([...BUNDLED_SKILLS, ...(this.liveSkills ?? [])].map((skill) => skill.key))
    const disabledSkills = Array.isArray(plan.disabledSkills) ? plan.disabledSkills.filter((key) => known.has(key)) : []
    this.running = true
    this.cancelled = false
    this.writeState({ pending: { components, disabledSkills }, lastRun: { startedAt: new Date().toISOString(), result: 'running' } })
    this.emit({ type: 'started', components })
    let outcome = 'done'
    let message = ''
    try {
      await host.refreshPath()
      for (const component of components) {
        if (component === 'core') await this.installCore()
        if (component === 'ollama') await this.installOllama()
        if (component === 'openclaw') await this.installOpenClaw(disabledSkills)
        if (component === 'nemoclaw') {
          const result = await this.installNemoClaw()
          if (result === 'restart') { outcome = 'restart'; message = this.restartMessage; break }
          if (result === 'action') { outcome = 'action'; message = this.actionMessage; break }
        }
      }
      if (outcome === 'done') {
        const problems = await this.verify(components)
        if (problems.length) { outcome = 'failed'; message = `Installed, but ${problems.join('; ')}. Open Services to read the log, then press Try again.` }
      }
    } catch (error) {
      outcome = this.cancelled ? 'cancelled' : 'failed'
      message = error instanceof Error ? error.message : String(error)
      this.log(`Setup stopped: ${message}`)
    } finally {
      this.running = false
      this.writeState({ pending: outcome === 'done' ? null : { components, disabledSkills }, lastRun: { finishedAt: new Date().toISOString(), result: outcome, message } })
      this.emit({ type: 'finished', outcome, message })
    }
    return { outcome, message }
  }

  cancel() {
    this.cancelled = true
    if (this.child?.pid) void platform.killTree(this.child.pid)
    else this.child?.kill?.()
  }

  async installCore() {
    const C = 'core'
    if (await this.coreReady()) { this.step(C, 'core', 'PockPock backend', 'done', 'Already installed'); return }
    this.step(C, 'python', 'Python 3.12', 'running')
    const python = await host.ensurePython(this, this.context)
    this.step(C, 'python', 'Python 3.12', 'done', python)
    this.step(C, 'venv', 'Python environment', 'running')
    if (!fs.existsSync(paths.venvPython())) {
      fs.mkdirSync(path.dirname(paths.venvRoot()), { recursive: true })
      await this.must(python, ['-m', 'venv', paths.venvRoot()], 'Creating the Python environment')
    }
    this.step(C, 'venv', 'Python environment', 'done', paths.venvRoot())
    this.step(C, 'packages', 'Backend packages', 'running')
    const backend = paths.backendRoot()
    const requirements = [path.join(backend, 'scripts', 'requirements-pockpock.txt'), ...fs.readdirSync(path.join(backend, 'projects')).map((name) => path.join(backend, 'projects', name, 'requirements.txt')).filter((file) => fs.existsSync(file))]
    await this.must(paths.venvPython(), ['-m', 'pip', 'install', '--disable-pip-version-check', '--upgrade', 'pip'], 'Updating pip')
    await this.must(paths.venvPython(), ['-m', 'pip', 'install', '--disable-pip-version-check', ...requirements.flatMap((file) => ['-r', file])], 'Installing backend packages')
    this.step(C, 'packages', 'Backend packages', 'done')
    this.step(C, 'chromium', 'Isolated browser for agents', 'running')
    await this.must(paths.venvPython(), ['-m', 'playwright', 'install', 'chromium'], 'Installing the agent browser')
    this.step(C, 'chromium', 'Isolated browser for agents', 'done')
  }

  async installOllama() {
    const C = 'ollama'
    this.step(C, 'ollama', 'Ollama', 'running')
    await host.ensureOllama(this, this.context)
    // NemoClaw and long agent turns need a larger context than Ollama's default.
    const changed = await host.setUserEnv('OLLAMA_CONTEXT_LENGTH', '32768')
    if (changed && (await this.ollamaModels()) !== null) await this.services.stop('ollama')
    await this.services.start('ollama')
    if ((await this.ollamaModels()) === null) throw new SetupError('Ollama did not start. Open Services to see its log.')
    this.step(C, 'ollama', 'Ollama', 'done')
    for (const model of MODELS) {
      const installed = await this.ollamaModels()
      if (installed?.some((name) => name === model || name === `${model}:latest`)) { this.step(C, `model:${model}`, `Model ${model}`, 'done', 'Already downloaded'); continue }
      this.step(C, `model:${model}`, `Downloading ${model}`, 'running', '', 0)
      await this.pull(model, (fraction, detail) => this.step(C, `model:${model}`, `Downloading ${model}`, 'running', detail, fraction))
      this.step(C, `model:${model}`, `Model ${model}`, 'done')
    }
  }

  pull(model, onProgress) {
    return new Promise((resolve, reject) => {
      const request = http.request('http://127.0.0.1:11434/api/pull', { method: 'POST', headers: { 'Content-Type': 'application/json' } }, (response) => {
        let buffer = ''
        let failed = ''
        response.on('data', (chunk) => {
          buffer += chunk.toString('utf8')
          const lines = buffer.split('\n')
          buffer = lines.pop() ?? ''
          for (const line of lines) {
            try {
              const event = JSON.parse(line)
              if (event.error) failed = event.error
              if (event.total && event.completed !== undefined) onProgress(event.completed / event.total, `${(event.completed / 1e9).toFixed(1)} of ${(event.total / 1e9).toFixed(1)} GB`)
              else if (event.status) onProgress(undefined, event.status)
            } catch { /* partial line */ }
          }
        })
        response.on('end', () => (failed ? reject(new SetupError(`Downloading ${model} failed: ${failed}`)) : resolve()))
      })
      request.on('error', (error) => reject(new SetupError(`Ollama stopped while downloading ${model}: ${error.message}`)))
      request.end(JSON.stringify({ model, stream: true }))
      this.child = { pid: 0, kill: () => request.destroy() }
    })
  }

  async openclaw(args, what) {
    const entry = paths.openclawEntry()
    if (!entry) throw new SetupError('OpenClaw was not found.')
    return this.must(entry.node, [entry.script, ...args], what)
  }

  async installOpenClaw(disabledSkills) {
    const C = 'openclaw'
    this.step(C, 'node', 'Node.js', 'running')
    await host.ensureNode(this, this.context)
    this.step(C, 'node', 'Node.js', 'done', paths.nodeExe() || '')
    this.step(C, 'cli', 'OpenClaw', 'running')
    if (!paths.openclawEntry()) {
      const npm = host.npmInvocation(['install', '-g', 'openclaw@latest', '--allow-scripts=esbuild,protobufjs,openclaw'])
      if (!npm) throw new SetupError('npm was not found next to Node.js.')
      await this.must(npm.file, npm.args, 'Installing OpenClaw', npm.options)
      await host.refreshPath()
      if (!paths.openclawEntry()) throw new SetupError(`OpenClaw was installed but its command was not found.${paths.IS_WIN ? ' Restart Windows and run setup again.' : ' See the setup log.'}`)
    }
    this.step(C, 'cli', 'OpenClaw', 'done')
    this.step(C, 'onboard', 'Connecting OpenClaw to Ollama', 'running')
    if (!fs.existsSync(path.join(OPENCLAW_HOME, 'openclaw.json'))) {
      await this.openclaw(['onboard', '--non-interactive', '--accept-risk', '--flow', 'quickstart', '--auth-choice', 'ollama', '--gateway-port', '18810', '--gateway-bind', 'loopback', '--gateway-auth', 'token', '--install-daemon'], 'OpenClaw onboarding')
    }
    await this.tuneOpenClaw(disabledSkills)
    this.step(C, 'onboard', 'Connecting OpenClaw to Ollama', 'done')
    this.step(C, 'plugin', 'PockPock permission plugin', 'running')
    const pluginDir = path.join(paths.backendRoot(), 'projects', 'openclaw_bridge')
    await this.must(paths.venvPython(), ['install_plugin.py'], 'Installing the permission plugin', { cwd: pluginDir, env: paths.cleanEnv({ PYTHONIOENCODING: 'utf-8' }) })
    this.step(C, 'plugin', 'PockPock permission plugin', 'done')
    this.step(C, 'gateway', 'Restarting the OpenClaw gateway', 'running')
    await this.services.stop('openclaw')
    await this.services.start('openclaw')
    this.step(C, 'gateway', 'Restarting the OpenClaw gateway', 'done')
  }

  async tuneOpenClaw(disabledSkills) {
    const set = (key, value) => this.openclaw(['config', 'set', key, JSON.stringify(value), '--strict-json'], `Setting ${key}`)
    await set('agents.defaults.model.primary', `ollama/${DEFAULT_MODEL}`)
    await set('agents.defaults.thinkingDefault', 'low')
    await set('agents.defaults.compaction.timeoutSeconds', 900)
    await set('models.providers.ollama.timeoutSeconds', 1800)
    await set('tools.profile', 'full')
    await set('plugins.entries.cua-computer.enabled', true)
    // The default model needs a 64K window: OpenClaw's own prompt is about 21K tokens.
    const entry = paths.openclawEntry()
    const listed = await run(entry.node, [entry.script, 'config', 'get', 'models.providers.ollama.models', '--json'], { timeout: 60000 })
    try {
      const models = JSON.parse(listed.stdout.slice(listed.stdout.indexOf('[')))
      const model = models.find((item) => item.id === DEFAULT_MODEL)
      if (model && model.contextTokens !== 65536) {
        model.contextTokens = 65536
        await set('models.providers.ollama.models', models)
      }
    } catch { this.log('Could not adjust the model context window; OpenClaw keeps its default.') }
    this.liveSkills = null // now that OpenClaw is installed, use the skills it reports for this computer
    for (const skill of await this.skills()) await set(`skills.entries.${skill.key}.enabled`, !disabledSkills.includes(skill.key))
    // Teach the agent how to use the browser and this computer.
    const guidance = fs.readFileSync(path.join(paths.backendRoot(), 'projects', 'openclaw_bridge', 'workspace-guidance.md'), 'utf8')
    const agentsFile = path.join(OPENCLAW_HOME, 'workspace', 'AGENTS.md')
    fs.mkdirSync(path.dirname(agentsFile), { recursive: true })
    const existing = fs.existsSync(agentsFile) ? fs.readFileSync(agentsFile, 'utf8') : ''
    if (!existing.includes('## Using the browser on this PC')) fs.appendFileSync(agentsFile, `\n\n${guidance.trim()}\n`)
  }

  async installNemoClaw() {
    const C = 'nemoclaw'
    const prepared = await host.installNemoClaw(this, this.context)
    if (prepared !== 'installed') return prepared
    if (!(await this.nemoInstalled())) {
      // Onboarding builds the sandbox image and points its inference at Ollama on this computer.
      if ((await this.ollamaModels()) === null) await this.services.start('ollama')
      const { file, args } = platform.nemoSpawn(`env ${NEMOCLAW_ENV} nemoclaw onboard --non-interactive --yes --yes-i-accept-third-party-software`, host.DISTRO)
      await this.must(file, args, 'NemoClaw onboarding')
    }
    this.services.nemoInstalled = null
    this.step(C, 'install', 'NemoClaw', 'done')
    return 'done'
  }

  // ---------- final check ----------

  /** Starts every installed service and checks each one answers, then runs one tiny model reply.
   * Returns a list of problems; empty means everything works. */
  async verify(components) {
    const C = 'verify'
    const problems = []
    const includeNemo = components.includes('nemoclaw') || (platform.nemoSupported().supported && (await this.nemoInstalled()))
    this.step(C, 'start', 'Starting all services', 'running')
    this.services.nemoInstalled = null
    await this.services.startAll({ includeNemo })
    this.step(C, 'start', 'Starting all services', 'done')
    const list = await this.services.refresh()
    for (const definition of DEFINITIONS) {
      if (definition.id === 'nemoclaw' && !includeNemo) continue
      const state = list.find((item) => item.id === definition.id)
      if (!state || state.status === 'unavailable') {
        // Optional engines that were not chosen are skipped; the core services must exist.
        if (definition.id === 'openclaw' || definition.id === 'ollama') continue
        problems.push(`${definition.name} is missing`)
        this.step(C, definition.id, definition.name, 'failed', state?.detail || 'Not installed')
        continue
      }
      if (state.status === 'running') this.step(C, definition.id, definition.name, 'done', 'Running')
      else { problems.push(`${definition.name} did not start`); this.step(C, definition.id, definition.name, 'failed', state.detail || 'Not running') }
    }
    if (list.find((item) => item.id === 'ollama')?.status === 'running') {
      this.step(C, 'model', `Test reply from ${ROUTER_MODEL}`, 'running')
      const reply = await this.generate(ROUTER_MODEL, 'Reply with only the word OK.')
      if (reply.ok) this.step(C, 'model', `Test reply from ${ROUTER_MODEL}`, 'done', `Answered in ${(reply.ms / 1000).toFixed(1)} s`)
      else { problems.push(`the test model reply failed (${reply.error})`); this.step(C, 'model', `Test reply from ${ROUTER_MODEL}`, 'failed', reply.error) }
    }
    const gateway = await httpJson('http://127.0.0.1:8766/api/health', 5000)
    if (gateway?.status !== 200) { problems.push('the PockPock gateway does not answer'); this.step(C, 'gateway-api', 'PockPock API', 'failed', 'No answer on port 8766') }
    else this.step(C, 'gateway-api', 'PockPock API', 'done', 'Answering')
    this.writeState({ verified: { at: new Date().toISOString(), ok: problems.length === 0, problems } })
    return problems
  }

  /** One short, non-streamed reply; the model is unloaded right after so it does not hold memory. */
  generate(model, prompt) {
    const started = Date.now()
    return new Promise((resolve) => {
      const request = http.request('http://127.0.0.1:11434/api/generate', { method: 'POST', headers: { 'Content-Type': 'application/json' }, timeout: 180000 }, (response) => {
        let body = ''
        response.on('data', (chunk) => { body += chunk })
        response.on('end', () => {
          try {
            const parsed = JSON.parse(body)
            resolve(parsed.error ? { ok: false, error: String(parsed.error).slice(0, 200) } : { ok: typeof parsed.response === 'string', ms: Date.now() - started, error: 'Empty reply' })
          } catch { resolve({ ok: false, error: `HTTP ${response.statusCode}` }) }
        })
      })
      request.on('timeout', () => { request.destroy(); resolve({ ok: false, error: 'No reply within 3 minutes' }) })
      request.on('error', (error) => resolve({ ok: false, error: error.message }))
      request.end(JSON.stringify({ model, prompt, stream: false, keep_alive: 0, options: { num_predict: 8 } }))
    })
  }
}

module.exports = { Setup, MODELS, DEFAULT_MODEL }
