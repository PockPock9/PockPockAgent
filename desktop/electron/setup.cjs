// First-run setup: installs and configures everything PockPock needs, skipping what is already
// there, then starts every service and checks it works. Components: core (Python backend), ollama
// (+ default models), openclaw (+ skills choice), nemoclaw (sandbox + Docker). The operating-system
// specific parts live in setup-win.cjs and setup-mac.cjs. Progress streams to the renderer; a plan
// that needs a restart or a user action is saved and resumed on the next run.
const crypto = require('node:crypto')
const fs = require('node:fs')
const https = require('node:https')
const http = require('node:http')
const os = require('node:os')
const path = require('node:path')
const { spawn } = require('node:child_process')
const { powerSaveBlocker } = require('electron')
const paths = require('./paths.cjs')
const hardware = require('./hardware.cjs')
const { syncGuidance } = require('./openclaw-guidance.cjs')
const platform = require('./platform.cjs')
const { DEFINITIONS, httpJson } = require('./services.cjs')

const host = paths.IS_MAC ? require('./setup-mac.cjs') : require('./setup-win.cjs')
const { run } = platform

// The default model is chosen per computer (hardware.cjs) and remembered in setup.json.
const ROUTER_MODEL = 'qwen2.5:1.5b' // the Smart Router's classifier
const nemoclawEnv = (model) => `NEMOCLAW_NO_EXPRESS=1 NEMOCLAW_NON_INTERACTIVE=1 NEMOCLAW_PROVIDER=ollama NEMOCLAW_MODEL=${model} NEMOCLAW_SANDBOX_NAME=pockpock NEMOCLAW_CONTEXT_WINDOW=32768 NEMOCLAW_ACCEPT_THIRD_PARTY_SOFTWARE=1`
const OPENCLAW_HOME = path.join(os.homedir(), '.openclaw')
const BUNDLED_SKILLS = require('./openclaw-skills.json').skills
const COMPONENTS = ['core', 'ollama', 'openclaw', 'nemoclaw']
// What "Set up PockPock" installs. NemoClaw is left out: it needs administrator approval, Docker,
// and on Windows a restart and an Ubuntu account, so it is offered under Customize instead.
const RECOMMENDED = ['core', 'ollama', 'openclaw']
const hasModel = (installed, name) => Boolean(installed?.some((item) => item === name || item === `${name}:latest`))

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
    this.model = null // the default model of the current run
  }

  /** Helpers handed to the operating-system installers. */
  get context() {
    return { download, SetupError, NEMOCLAW_ENV: nemoclawEnv(this.model || this.readState().defaultModel || 'qwen3.5:9b'), services: this.services }
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

  /** The default model: the one chosen at an earlier setup, else the one that fits this computer. */
  chooseModel(state, specs, installed) {
    if (state.defaultModel) return { name: state.defaultModel, reason: 'Chosen when PockPock was set up.' }
    return hardware.recommendModel(specs, installed ?? [])
  }

  async status() {
    const models = await this.ollamaModels()
    const state = this.readState()
    const nemoSupport = platform.nemoSupported()
    const core = await this.coreReady()
    const specs = await hardware.detect()
    const recommended = this.chooseModel(state, specs, models)
    const openclawInstalled = Boolean(paths.openclawCmd()) && fs.existsSync(path.join(OPENCLAW_HOME, 'openclaw.json'))
    const missing = [
      !core && 'core', !paths.ollamaExe() && 'ollama', !openclawInstalled && 'openclaw', 'nemoclaw',
      !hasModel(models, recommended.name) && 'model', !hasModel(models, ROUTER_MODEL) && 'router',
    ].filter(Boolean)
    return {
      platform: process.platform,
      arch: os.arch(),
      hardware: specs,
      model: { ...recommended, choices: hardware.MODEL_CHOICES, missing },
      recommended: { components: RECOMMENDED, ...hardware.estimate(RECOMMENDED, recommended.name, missing) },
      core: { installed: core },
      ollama: { installed: Boolean(paths.ollamaExe()), running: models !== null, models: Object.fromEntries([recommended.name, ROUTER_MODEL].map((name) => [name, hasModel(models, name)])) },
      openclaw: { installed: openclawInstalled, cli: Boolean(paths.openclawCmd()), node: Boolean(paths.nodeExe()) },
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
    const state = this.readState()
    const choices = hardware.MODEL_CHOICES.map((item) => item.name)
    this.running = true
    this.cancelled = false
    // Keep the computer awake: a long model download must not be cut off by sleep.
    const awake = powerSaveBlocker.start('prevent-app-suspension')
    let outcome = 'done'
    let message = ''
    try {
      const installed = await this.ollamaModels()
      this.model = choices.includes(plan.model) ? plan.model : state.pending?.model || this.chooseModel(state, await hardware.detect(), installed).name
      this.writeState({ pending: { components, disabledSkills, model: this.model }, lastRun: { startedAt: new Date().toISOString(), result: 'running' } })
      this.emit({ type: 'started', components })
      await this.checkDiskSpace(components, installed)
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
      powerSaveBlocker.stop(awake)
      this.running = false
      this.writeState({
        pending: outcome === 'done' ? null : { components, disabledSkills, model: this.model },
        ...(outcome === 'done' && components.includes('ollama') ? { defaultModel: this.model } : {}),
        lastRun: { finishedAt: new Date().toISOString(), result: outcome, message },
      })
      this.emit({ type: 'finished', outcome, message })
    }
    return { outcome, message }
  }

  /** Stops before downloading anything when the disk is too full for what is still missing. */
  async checkDiskSpace(components, installed) {
    const specs = await hardware.detect()
    if (specs.freeDiskGB === null) return
    const missing = [
      !(await this.coreReady()) && 'core', !paths.ollamaExe() && 'ollama', !paths.openclawEntry() && 'openclaw',
      components.includes('nemoclaw') && !(await this.nemoInstalled()) && 'nemoclaw',
      !hasModel(installed, this.model) && 'model', !hasModel(installed, ROUTER_MODEL) && 'router',
    ].filter(Boolean)
    const { downloadGB, neededGB } = hardware.estimate(components, this.model, missing)
    this.log(`Free disk space: ${specs.freeDiskGB} GB. Download: about ${downloadGB} GB; space needed: about ${neededGB} GB.`)
    if (specs.freeDiskGB < neededGB) {
      const computer = paths.IS_MAC ? 'Mac' : 'PC'
      const bin = paths.IS_MAC ? 'Trash' : 'Recycle Bin'
      throw new SetupError(`Not enough free disk space. Setup needs about ${neededGB} GB, and this ${computer} has ${specs.freeDiskGB} GB free. Free up ${Math.ceil(neededGB - specs.freeDiskGB)} GB (for example by emptying the ${bin} or removing large files you no longer need), then press Try again.`)
    }
  }

  cancel() {
    this.cancelled = true
    if (this.child?.pid) void platform.killTree(this.child.pid)
    else this.child?.kill?.()
  }

  /** The backend's requirements files, as bundled with this version of the app. */
  requirementsFiles() {
    const backend = paths.backendRoot()
    return [path.join(backend, 'scripts', 'requirements-pockpock.txt'), ...fs.readdirSync(path.join(backend, 'projects')).map((name) => path.join(backend, 'projects', name, 'requirements.txt')).filter((file) => fs.existsSync(file))]
  }

  /** A fingerprint of the requirements: an app update that needs new packages changes it. */
  backendDepsHash() {
    const hash = crypto.createHash('sha256')
    for (const file of this.requirementsFiles()) hash.update(path.basename(path.dirname(file))).update(fs.readFileSync(file, 'utf8').replace(/\r\n/g, '\n'))
    return hash.digest('hex').slice(0, 16)
  }

  /** True when the backend is installed but its packages were installed for other requirements,
   * which happens after the app updated itself. */
  backendOutdated() {
    if (!fs.existsSync(paths.venvPython())) return false
    try { return this.readState().backendDeps !== this.backendDepsHash() } catch { return false }
  }

  async installPackages() {
    await this.must(paths.venvPython(), ['-m', 'pip', 'install', '--disable-pip-version-check', '--upgrade', 'pip'], 'Updating pip')
    await this.must(paths.venvPython(), ['-m', 'pip', 'install', '--disable-pip-version-check', ...this.requirementsFiles().flatMap((file) => ['-r', file])], 'Installing backend packages')
  }

  /** After an app update: installs the packages the new version needs and the matching agent
   * browser, before the services start. Output goes to logs/backend-update.log. */
  async refreshBackend() {
    if (this.running) return { ok: false, error: 'Setup is running.' }
    const logFile = path.join(paths.logsRoot(), 'backend-update.log')
    const write = (line) => { try { fs.appendFileSync(logFile, `${line}\n`) } catch { /* ignore */ } }
    write(`=== ${new Date().toISOString()} updating backend packages for PockPock ${require('electron').app.getVersion()}`)
    const run = async (args) => {
      const result = await platform.run(paths.venvPython(), args, { timeout: 15 * 60 * 1000 })
      write(`> python ${args.join(' ')}\n${result.stdout}${result.stderr}`.slice(-20000))
      if (!result.ok) throw new SetupError(`python ${args.slice(0, 3).join(' ')} failed`)
    }
    try {
      await run(['-m', 'pip', 'install', '--disable-pip-version-check', ...this.requirementsFiles().flatMap((file) => ['-r', file])])
      await run(['-m', 'playwright', 'install', 'chromium'])
      this.writeState({ backendDeps: this.backendDepsHash() })
      write('done')
      return { ok: true }
    } catch (error) {
      write(`failed: ${error.message}`)
      return { ok: false, error: error.message }
    }
  }

  async installCore() {
    const C = 'core'
    if (await this.coreReady()) {
      if (!this.backendOutdated()) { this.step(C, 'core', 'PockPock backend', 'done', 'Already installed'); return }
      // Installed, but for an older version of the app: bring the packages up to date.
      this.step(C, 'packages', 'Updating backend packages', 'running')
      await this.installPackages()
      await this.must(paths.venvPython(), ['-m', 'playwright', 'install', 'chromium'], 'Installing the agent browser')
      this.writeState({ backendDeps: this.backendDepsHash() })
      this.step(C, 'packages', 'Updating backend packages', 'done')
      return
    }
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
    await this.installPackages()
    this.step(C, 'packages', 'Backend packages', 'done')
    this.step(C, 'chromium', 'Isolated browser for agents', 'running')
    await this.must(paths.venvPython(), ['-m', 'playwright', 'install', 'chromium'], 'Installing the agent browser')
    this.writeState({ backendDeps: this.backendDepsHash() })
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
    for (const model of [this.model, ROUTER_MODEL]) {
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
    await set('agents.defaults.model.primary', `ollama/${this.model}`)
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
      const model = models.find((item) => item.id === this.model)
      if (model && model.contextTokens !== 65536) {
        model.contextTokens = 65536
        await set('models.providers.ollama.models', models)
      }
    } catch { this.log('Could not adjust the model context window; OpenClaw keeps its default.') }
    this.liveSkills = null // now that OpenClaw is installed, use the skills it reports for this computer
    for (const skill of await this.skills()) await set(`skills.entries.${skill.key}.enabled`, !disabledSkills.includes(skill.key))
    // Teach the agent how to use the browser and this computer (a managed block in AGENTS.md).
    syncGuidance(paths.backendRoot(), OPENCLAW_HOME)
  }

  async installNemoClaw() {
    const C = 'nemoclaw'
    const prepared = await host.installNemoClaw(this, this.context)
    if (prepared !== 'installed') return prepared
    if (!(await this.nemoInstalled())) {
      // Onboarding builds the sandbox image and points its inference at Ollama on this computer.
      if ((await this.ollamaModels()) === null) await this.services.start('ollama')
      const { file, args } = platform.nemoSpawn(`env ${nemoclawEnv(this.model)} nemoclaw onboard --non-interactive --yes --yes-i-accept-third-party-software`, host.DISTRO)
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

module.exports = { Setup, ROUTER_MODEL, RECOMMENDED }
