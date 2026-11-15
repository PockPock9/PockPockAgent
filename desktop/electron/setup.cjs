// First-run setup: installs and configures everything PockPock needs, skipping what is already
// there. Components: core (Python backend), ollama (+ default models), openclaw (+ skills choice),
// nemoclaw (WSL + Docker Desktop + sandbox). Progress streams to the renderer; a plan that needs a
// Windows restart is saved and resumed on the next launch.
const fs = require('node:fs')
const https = require('node:https')
const http = require('node:http')
const os = require('node:os')
const path = require('node:path')
const { spawn } = require('node:child_process')
const paths = require('./paths.cjs')
const { run, wsl } = require('./services.cjs')

const PYTHON_VERSION = '3.12.10'
const PYTHON_URL = `https://www.python.org/ftp/python/${PYTHON_VERSION}/python-${PYTHON_VERSION}-amd64.exe`
const OLLAMA_URL = 'https://ollama.com/download/OllamaSetup.exe'
const DEFAULT_MODEL = 'qwen3.5:9b'
const ROUTER_MODEL = 'qwen2.5:1.5b' // the Smart Router's classifier
const MODELS = [DEFAULT_MODEL, ROUTER_MODEL]
const DISTRO = 'Ubuntu-24.04'
const NEMOCLAW_ENV = `NEMOCLAW_NO_EXPRESS=1 NEMOCLAW_NON_INTERACTIVE=1 NEMOCLAW_PROVIDER=ollama NEMOCLAW_MODEL=${DEFAULT_MODEL} NEMOCLAW_SANDBOX_NAME=pockpock NEMOCLAW_CONTEXT_WINDOW=32768 NEMOCLAW_ACCEPT_THIRD_PARTY_SOFTWARE=1`
const OPENCLAW_HOME = path.join(os.homedir(), '.openclaw')
const SKILLS = require('./openclaw-skills.json').skills

class SetupError extends Error {}

/** Child processes do not see PATH changes made by installers until PATH is re-read. */
async function refreshPath() {
  const read = async (key) => {
    const result = await run('reg.exe', ['query', key, '/v', 'Path'], { timeout: 10000 })
    const match = /Path\s+REG_(?:EXPAND_)?SZ\s+(.*)/i.exec(result.stdout)
    return match ? match[1].trim().replace(/%([^%]+)%/g, (_, name) => process.env[name] ?? `%${name}%`) : ''
  }
  const machine = await read('HKLM\\SYSTEM\\CurrentControlSet\\Control\\Session Manager\\Environment')
  const user = await read('HKCU\\Environment')
  const merged = [...new Set([...machine.split(';'), ...user.split(';'), ...(process.env.PATH || '').split(';')].filter(Boolean))]
  process.env.PATH = merged.join(';')
}

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
    }).on('error', reject)
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
  }

  readState() {
    try { return JSON.parse(fs.readFileSync(this.stateFile, 'utf8')) } catch { return {} }
  }

  writeState(change) {
    const next = { ...this.readState(), ...change }
    fs.writeFileSync(this.stateFile, JSON.stringify(next, null, 2), 'utf8')
    return next
  }

  log(line) { this.emit({ type: 'log', line: String(line).replace(/\0/g, '').slice(0, 2000) }) }
  step(component, id, label, status, detail = '', progress) { this.emit({ type: 'step', component, id, label, status, detail, progress }) }

  /** Runs a program, streaming its output to the setup log. Resolves with the exit code. */
  exec(file, args, options = {}) {
    if (this.cancelled) return Promise.reject(new SetupError('Setup was cancelled.'))
    this.log(`> ${path.basename(file)} ${args.join(' ')}`.slice(0, 400))
    return new Promise((resolve, reject) => {
      const child = spawn(file, args, { cwd: options.cwd, env: options.env ?? paths.cleanEnv(), shell: options.shell ?? false, windowsHide: true })
      this.child = child
      let tail = ''
      const onData = (chunk) => {
        const text = chunk.toString('utf8').replace(/\0/g, '')
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

  async winget(id, extra = []) {
    if (!paths.findExecutable(['winget.exe'])) return false
    const result = await this.exec('winget.exe', ['install', '-e', '--id', id, '--silent', '--accept-package-agreements', '--accept-source-agreements', '--disable-interactivity', ...extra])
    await refreshPath()
    return result.code === 0 || result.code === -1978335189 || result.code === 2316632107 // already installed
  }

  // ---------- detection ----------

  async findPython() {
    const candidates = [
      path.join(paths.LOCAL, 'Programs', 'Python', 'Python312', 'python.exe'),
      path.join(paths.LOCAL, 'Programs', 'Python', 'Python313', 'python.exe'),
      paths.findExecutable(['python.exe']),
    ].filter(Boolean)
    const launcher = paths.findExecutable(['py.exe'])
    if (launcher) {
      const result = await run(launcher, ['-3.12', '-c', 'import sys; print(sys.executable)'], { timeout: 20000 })
      if (result.ok && result.stdout.trim()) candidates.unshift(result.stdout.trim())
    }
    for (const candidate of candidates) {
      if (!fs.existsSync(candidate) || /WindowsApps/i.test(candidate)) continue
      const result = await run(candidate, ['-c', 'import sys; print("%d.%d" % sys.version_info[:2])'], { timeout: 20000 })
      const [major, minor] = result.stdout.trim().split('.').map(Number)
      if (result.ok && major === 3 && minor >= 12) return candidate
    }
    return null
  }

  async coreReady() {
    if (!fs.existsSync(paths.venvPython())) return false
    const result = await run(paths.venvPython(), ['-c', 'import fastapi, uvicorn, aiohttp, playwright, pypdf'], { timeout: 30000 })
    return result.ok
  }

  async ollamaModels() {
    return new Promise((resolve) => {
      http.get('http://127.0.0.1:11434/api/tags', { timeout: 3000 }, (response) => {
        let body = ''
        response.on('data', (chunk) => { body += chunk })
        response.on('end', () => { try { resolve(JSON.parse(body).models.map((model) => model.name)) } catch { resolve(null) } })
      }).on('error', () => resolve(null)).on('timeout', function () { this.destroy(); resolve(null) })
    })
  }

  async status() {
    const models = await this.ollamaModels()
    const state = this.readState()
    const openclawConfig = fs.existsSync(path.join(OPENCLAW_HOME, 'openclaw.json'))
    let nemo = { installed: false, wsl: Boolean(paths.findExecutable(['wsl.exe'])), docker: Boolean(paths.findExecutable(['docker.exe'])) }
    if (nemo.wsl) {
      const listing = await wsl('command -v nemoclaw >/dev/null 2>&1 && nemoclaw list --json 2>/dev/null', 30000)
      try { nemo.installed = JSON.parse(listing.stdout.replace(/\0/g, '')).sandboxes.some((sandbox) => sandbox.name === 'pockpock') } catch { nemo.installed = false }
    }
    const core = await this.coreReady()
    return {
      core: { installed: core },
      ollama: { installed: Boolean(paths.ollamaExe()), running: models !== null, models: Object.fromEntries(MODELS.map((name) => [name, Boolean(models?.some((item) => item === name || item === `${name}:latest`))])) },
      openclaw: { installed: Boolean(paths.openclawCmd()) && openclawConfig, cli: Boolean(paths.openclawCmd()), node: Boolean(paths.findExecutable(['node.exe'])) },
      nemoclaw: nemo,
      winget: Boolean(paths.findExecutable(['winget.exe'])),
      skills: SKILLS,
      pending: state.pending ?? null,
      lastRun: state.lastRun ?? null,
      needsSetup: !core,
    }
  }

  // ---------- run ----------

  async start(plan) {
    if (this.running) throw new SetupError('Setup is already running.')
    const components = ['core', 'ollama', 'openclaw', 'nemoclaw'].filter((name) => plan.components.includes(name) || name === 'core')
    const disabledSkills = Array.isArray(plan.disabledSkills) ? plan.disabledSkills.filter((key) => SKILLS.some((skill) => skill.key === key)) : []
    this.running = true
    this.cancelled = false
    this.writeState({ pending: { components, disabledSkills }, lastRun: { startedAt: new Date().toISOString(), result: 'running' } })
    this.emit({ type: 'started', components })
    let outcome = 'done'
    let message = ''
    try {
      await refreshPath()
      for (const component of components) {
        if (component === 'core') await this.installCore()
        if (component === 'ollama') await this.installOllama()
        if (component === 'openclaw') await this.installOpenClaw(disabledSkills)
        if (component === 'nemoclaw') {
          const result = await this.installNemoClaw()
          if (result === 'restart') { outcome = 'restart'; message = 'Restart Windows to finish installing WSL, then open PockPock Agent. Setup continues where it stopped.'; break }
          if (result === 'action') { outcome = 'action'; message = this.actionMessage; break }
        }
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
    if (this.child?.pid) void run('taskkill.exe', ['/PID', String(this.child.pid), '/T', '/F'], { timeout: 15000 })
  }

  async installCore() {
    const C = 'core'
    if (await this.coreReady()) { this.step(C, 'core', 'PockPock backend', 'done', 'Already installed'); return }
    this.step(C, 'python', 'Python 3.12', 'running')
    let python = await this.findPython()
    if (!python) {
      if (!(await this.winget('Python.Python.3.12', ['--scope', 'user']))) {
        const installer = path.join(os.tmpdir(), `python-${PYTHON_VERSION}-amd64.exe`)
        await download(PYTHON_URL, installer, (fraction) => this.step(C, 'python', 'Downloading Python 3.12', 'running', '', fraction))
        await this.must(installer, ['/quiet', 'InstallAllUsers=0', 'PrependPath=0', 'Include_test=0', 'Include_launcher=0'], 'Installing Python')
      }
      python = await this.findPython()
      if (!python) throw new SetupError('Python 3.12 could not be installed. Install it from python.org and run setup again.')
    }
    this.step(C, 'python', 'Python 3.12', 'done', python)
    this.step(C, 'venv', 'Python environment', 'running')
    if (!fs.existsSync(paths.venvPython())) {
      fs.mkdirSync(path.dirname(paths.venvRoot()), { recursive: true })
      await this.must(python, ['-m', 'venv', paths.venvRoot()], 'Creating the Python environment')
    }
    this.step(C, 'venv', 'Python environment', 'done', paths.venvRoot())
    this.step(C, 'packages', 'Backend packages', 'running')
    const backend = paths.backendRoot()
    const requirements = [path.join(backend, 'scripts', 'requirements-frog-ai.txt'), ...fs.readdirSync(path.join(backend, 'projects')).map((name) => path.join(backend, 'projects', name, 'requirements.txt')).filter((file) => fs.existsSync(file))]
    await this.must(paths.venvPython(), ['-m', 'pip', 'install', '--disable-pip-version-check', '--upgrade', 'pip'], 'Updating pip')
    await this.must(paths.venvPython(), ['-m', 'pip', 'install', '--disable-pip-version-check', ...requirements.flatMap((file) => ['-r', file])], 'Installing backend packages')
    this.step(C, 'packages', 'Backend packages', 'done')
    this.step(C, 'chromium', 'Isolated browser for agents', 'running')
    await this.must(paths.venvPython(), ['-m', 'playwright', 'install', 'chromium'], 'Installing the agent browser')
    this.step(C, 'chromium', 'Isolated browser for agents', 'done')
    this.step(C, 'start', 'Starting backend services', 'running')
    await this.services.startAll({ includeNemo: false })
    this.step(C, 'start', 'Starting backend services', 'done')
  }

  async installOllama() {
    const C = 'ollama'
    this.step(C, 'ollama', 'Ollama', 'running')
    if (!paths.ollamaExe()) {
      if (!(await this.winget('Ollama.Ollama'))) {
        const installer = path.join(os.tmpdir(), 'OllamaSetup.exe')
        await download(OLLAMA_URL, installer, (fraction) => this.step(C, 'ollama', 'Downloading Ollama', 'running', '', fraction))
        await this.must(installer, ['/VERYSILENT', '/NORESTART', '/SUPPRESSMSGBOXES'], 'Installing Ollama')
      }
      await refreshPath()
      if (!paths.ollamaExe()) throw new SetupError('Ollama could not be installed. Install it from ollama.com and run setup again.')
    }
    // NemoClaw and long agent turns need a larger context than Ollama's default.
    const current = await run('reg.exe', ['query', 'HKCU\\Environment', '/v', 'OLLAMA_CONTEXT_LENGTH'], { timeout: 10000 })
    if (!current.ok) {
      await run('reg.exe', ['add', 'HKCU\\Environment', '/v', 'OLLAMA_CONTEXT_LENGTH', '/t', 'REG_SZ', '/d', '32768', '/f'], { timeout: 10000 })
      process.env.OLLAMA_CONTEXT_LENGTH = '32768'
      if ((await this.ollamaModels()) !== null) await this.services.stop('ollama')
    }
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
    if (!paths.findExecutable(['node.exe'])) {
      if (!(await this.winget('OpenJS.NodeJS.LTS'))) throw new SetupError('Node.js could not be installed. Install Node.js 24 LTS from nodejs.org and run setup again.')
      if (!paths.findExecutable(['node.exe'])) throw new SetupError('Node.js was installed but is not on PATH yet. Restart Windows and run setup again.')
    }
    this.step(C, 'node', 'Node.js', 'done')
    this.step(C, 'cli', 'OpenClaw', 'running')
    if (!paths.openclawCmd()) {
      const npm = paths.findExecutable(['npm.cmd'])
      if (!npm) throw new SetupError('npm was not found next to Node.js.')
      await this.must(npm, ['install', '-g', 'openclaw@latest', '--allow-scripts=esbuild,protobufjs,openclaw'], 'Installing OpenClaw', { shell: true })
      await refreshPath()
      if (!paths.openclawCmd()) throw new SetupError('OpenClaw was installed but its command was not found. Restart Windows and run setup again.')
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
    this.step(C, 'gateway', 'Starting the OpenClaw gateway', 'running')
    await this.services.stop('openclaw')
    await this.services.start('openclaw')
    this.step(C, 'gateway', 'Starting the OpenClaw gateway', 'done')
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
    for (const skill of SKILLS) await set(`skills.entries.${skill.key}.enabled`, !disabledSkills.includes(skill.key))
    // Teach the agent how to use the browser and this PC.
    const guidance = fs.readFileSync(path.join(paths.backendRoot(), 'projects', 'openclaw_bridge', 'workspace-guidance.md'), 'utf8')
    const agentsFile = path.join(OPENCLAW_HOME, 'workspace', 'AGENTS.md')
    fs.mkdirSync(path.dirname(agentsFile), { recursive: true })
    const existing = fs.existsSync(agentsFile) ? fs.readFileSync(agentsFile, 'utf8') : ''
    if (!existing.includes('## Using the browser on this PC')) fs.appendFileSync(agentsFile, `\n\n${guidance.trim()}\n`)
  }

  async installNemoClaw() {
    const C = 'nemoclaw'
    this.step(C, 'wsl', 'WSL and Ubuntu', 'running')
    const status = await run('wsl.exe', ['--status'], { timeout: 30000 })
    if (!status.ok) {
      this.log('WSL is not installed. Windows will ask for administrator permission.')
      await this.exec('powershell.exe', ['-NoProfile', '-Command', `Start-Process wsl.exe -ArgumentList '--install','-d','${DISTRO}','--no-launch' -Verb RunAs -Wait`])
      this.step(C, 'wsl', 'WSL and Ubuntu', 'waiting', 'Restart Windows to finish')
      return 'restart'
    }
    const distros = (await run('wsl.exe', ['-l', '-q'], { timeout: 30000 })).stdout.replace(/\0/g, '').split(/\r?\n/).map((line) => line.trim()).filter(Boolean)
    if (!distros.includes(DISTRO)) {
      await this.must('wsl.exe', ['--install', '-d', DISTRO, '--no-launch'], 'Installing Ubuntu')
    }
    const probe = await run('wsl.exe', ['-d', DISTRO, '-e', 'id', '-un'], { timeout: 60000 })
    if (!probe.ok || probe.stdout.replace(/\0/g, '').trim() === 'root' || !probe.stdout.trim()) {
      // Ubuntu asks for a username and password on first launch; that cannot be done silently.
      spawn('cmd.exe', ['/c', 'start', 'Ubuntu first run', 'wsl.exe', '-d', DISTRO], { detached: true, stdio: 'ignore' }).unref()
      this.actionMessage = 'A terminal opened to finish setting up Ubuntu. Choose a username and password there, close it, then press Continue setup.'
      this.step(C, 'wsl', 'WSL and Ubuntu', 'waiting', 'Create your Ubuntu user in the window that opened')
      return 'action'
    }
    await run('wsl.exe', ['--set-default', DISTRO], { timeout: 30000 })
    this.step(C, 'wsl', 'WSL and Ubuntu', 'done')
    const wslConfig = path.join(os.homedir(), '.wslconfig')
    if (fs.existsSync(wslConfig) && /networkingMode\s*=\s*mirrored/i.test(fs.readFileSync(wslConfig, 'utf8'))) {
      this.log('Warning: .wslconfig uses networkingMode=mirrored, which breaks the NemoClaw dashboard port. Remove that line if onboarding fails.')
    }
    this.step(C, 'docker', 'Docker Desktop', 'running')
    if (!paths.findExecutable(['docker.exe'], [path.join(process.env.ProgramFiles || 'C:\\Program Files', 'Docker', 'Docker', 'resources', 'bin')])) {
      this.log('Installing Docker Desktop. Windows will ask for administrator permission.')
      if (!(await this.winget('Docker.DockerDesktop'))) throw new SetupError('Docker Desktop could not be installed. Install it from docker.com and run setup again.')
    }
    await this.services.ensureDocker()
    this.step(C, 'docker', 'Docker Desktop', 'done')
    this.step(C, 'install', 'NemoClaw', 'running', 'This can take 15 to 30 minutes')
    const installed = await wsl('command -v nemoclaw >/dev/null 2>&1 && echo yes', 30000)
    if (!installed.stdout.includes('yes')) {
      await this.must('wsl.exe', ['-d', DISTRO, '-e', 'bash', '-lc', `curl -fsSL https://www.nvidia.com/nemoclaw.sh | env ${NEMOCLAW_ENV} bash`], 'Installing NemoClaw')
    }
    const listing = await wsl('nemoclaw list --json 2>/dev/null', 30000)
    let hasSandbox = false
    try { hasSandbox = JSON.parse(listing.stdout.replace(/\0/g, '')).sandboxes.some((sandbox) => sandbox.name === 'pockpock') } catch { hasSandbox = false }
    if (!hasSandbox) {
      await this.must('wsl.exe', ['-d', DISTRO, '-e', 'bash', '-lc', `export PATH="$HOME/.local/bin:$PATH"; env ${NEMOCLAW_ENV} nemoclaw onboard --non-interactive --yes --yes-i-accept-third-party-software`], 'NemoClaw onboarding')
    }
    this.services.nemoInstalled = null
    this.step(C, 'install', 'NemoClaw', 'done')
    return 'done'
  }
}

module.exports = { Setup, MODELS, DEFAULT_MODEL }
