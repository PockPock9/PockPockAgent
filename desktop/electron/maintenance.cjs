// Maintenance Manager setup (LRN-04A): which AI does the maintenance work, the GitHub connection,
// and the user's permission-based clone of the PockPock repository. Fix runs (LRN-04B) and draft pull
// requests (LRN-04C) build on this. Settings are kept in <userData>/maintenance.json.
const fs = require('node:fs')
const os = require('node:os')
const path = require('node:path')
const { spawn } = require('node:child_process')
const paths = require('./paths.cjs')
const { run } = require('./platform.cjs')
const { httpJson } = require('./services.cjs')
const { INSTALLERS, LOGIN, installPlan, parseUrl, stream } = require('./maintenance-connect.cjs')

const UPSTREAM = 'PockPock9/PockPockAgent'
const AGENT_IDS = ['local', 'claude', 'codex', 'copilot']

const home = os.homedir()
const env = (name) => process.env[name] || ''

// winget puts portable tools (such as Claude Code) here; a running app does not see the new PATH entry.
const WINGET_LINKS = path.join(env('LOCALAPPDATA'), 'Microsoft', 'WinGet', 'Links')
/** Folders of winget "portable" packages whose name starts with `id`. Without Developer Mode winget
 * makes no link in Links; it only adds the package folder to PATH, which a running app does not see. */
function wingetPackageDirs(id) {
  const root = path.join(env('LOCALAPPDATA'), 'Microsoft', 'WinGet', 'Packages')
  try { return fs.readdirSync(root).filter((name) => name.toLowerCase().startsWith(`${id.toLowerCase()}_`)).map((name) => path.join(root, name)) } catch { return [] }
}

/** Where each coding agent's command-line tool is usually installed. */
const AGENTS = {
  claude: {
    name: 'Claude Code', vendor: 'Anthropic',
    names: paths.IS_WIN ? ['claude.exe', 'claude.cmd'] : ['claude'],
    dirs: () => [path.join(home, '.local', 'bin'), path.join(home, '.claude', 'local'), WINGET_LINKS, ...wingetPackageDirs('Anthropic.ClaudeCode'), path.join(env('APPDATA'), 'npm'), '/opt/homebrew/bin', '/usr/local/bin'],
    install: 'Not on this PC yet. Connect installs Claude Code and opens the Anthropic sign-in page. It needs a Claude subscription or API account.',
  },
  codex: {
    name: 'OpenAI Codex', vendor: 'OpenAI',
    names: paths.IS_WIN ? ['codex.exe', 'codex.cmd'] : ['codex'],
    dirs: () => [path.join(env('APPDATA'), 'npm'), path.join(home, '.local', 'bin'), '/opt/homebrew/bin', '/usr/local/bin'],
    install: 'Install the Codex CLI (`npm install -g @openai/codex`), then run `codex` once in a terminal to sign in.',
  },
  copilot: {
    name: 'GitHub Copilot', vendor: 'GitHub',
    names: paths.IS_WIN ? ['copilot.exe', 'copilot.cmd'] : ['copilot'],
    dirs: () => [path.join(env('LOCALAPPDATA'), 'GitHubCopilotCLI'), WINGET_LINKS, ...wingetPackageDirs('GitHub.Copilot'), path.join(env('APPDATA'), 'npm'), path.join(home, '.local', 'bin'), '/opt/homebrew/bin', '/usr/local/bin'],
    install: 'Not on this PC yet. Connect installs the GitHub Copilot CLI and opens the GitHub sign-in page. It needs a Copilot subscription.',
  },
}

/** Pulls the one-time code out of `gh auth login --web` output. */
function parseDeviceCode(text) {
  const match = /one-time code:\s*([A-Z0-9]{4}-[A-Z0-9]{4})/i.exec(String(text))
  return match ? match[1].toUpperCase() : ''
}

/** The local model to suggest: the largest installed model, by parameter count in its name. */
function suggestLocalModel(models) {
  const size = (name) => Number(/:(\d+(?:\.\d+)?)b/i.exec(name)?.[1] || 0)
  const coding = models.filter((name) => !/embed|vision|llava|reader/i.test(name))
  return [...coding].sort((a, b) => size(b) - size(a))[0] || ''
}

class Maintenance {
  constructor({ userData, emit }) {
    this.file = path.join(userData, 'maintenance.json')
    this.emit = emit
    this.loginChild = null
    this.connecting = null // { id, child } while Connect is installing or signing in
  }

  config() {
    try { return JSON.parse(fs.readFileSync(this.file, 'utf8')) } catch { return {} }
  }

  save(change) {
    const next = { ...this.config(), ...change }
    fs.writeFileSync(this.file, JSON.stringify(next, null, 2), 'utf8')
    return next
  }

  defaultFolder() {
    let documents = path.join(home, 'Documents')
    try { documents = require('electron').app.getPath('documents') } catch { /* tests run outside Electron */ }
    return path.join(documents, 'PockPock', 'PockPockAgent')
  }

  gh() {
    return paths.findExecutable(paths.IS_WIN ? ['gh.exe'] : ['gh'], [path.join(env('ProgramFiles'), 'GitHub CLI'), path.join(env('LOCALAPPDATA'), 'Programs', 'GitHub CLI'), '/opt/homebrew/bin', '/usr/local/bin'])
  }

  git() {
    return paths.findExecutable(paths.IS_WIN ? ['git.exe'] : ['git'], [path.join(env('ProgramFiles'), 'Git', 'cmd'), '/opt/homebrew/bin', '/usr/local/bin', '/usr/bin'])
  }

  /** Every AI the Maintenance Manager can use, with whether it is installed. */
  async agents() {
    const tags = await httpJson('http://127.0.0.1:11434/api/tags', 3000)
    const models = Array.isArray(tags?.json?.models) ? tags.json.models.map((model) => model.name) : []
    const local = {
      id: 'local', name: 'PockPock itself', vendor: '', installed: models.length > 0, openclaw: Boolean(paths.openclawEntry()),
      models, suggested: suggestLocalModel(models),
      dataNotice: 'PockPock fixes itself with a model on this PC; nothing leaves it. Local models are slower and fix fewer problems, and a fix that fails the checks is not proposed.',
      install: tags === null ? 'Ollama is not running. Start it on the Services page.' : 'Ollama has no models. Run Setup to download one.',
    }
    const others = await Promise.all(Object.entries(AGENTS).map(async ([id, agent]) => {
      const file = paths.findExecutable(agent.names, agent.dirs())
      let version = ''
      if (file) {
        const result = await run(file, ['--version'], { timeout: 20000, shell: /\.cmd$/i.test(file) })
        version = (result.stdout || result.stderr).trim().split('\n')[0].slice(0, 80)
      }
      const canConnect = Boolean(INSTALLERS[id])
      return {
        id, name: agent.name, vendor: agent.vendor, installed: Boolean(file), version, canConnect,
        signedIn: file && canConnect ? await this.signedIn(id, file) : null,
        dataNotice: `Sends the report, the parts of the PockPock code it reads, and its changes to ${agent.vendor}. Uses your own ${agent.name} account.`,
        install: agent.install,
      }
    }))
    const order = ['local', 'claude', 'copilot', 'codex']
    return [local, ...others].sort((a, b) => order.indexOf(a.id) - order.indexOf(b.id))
  }

  /** The command-line tool of a cloud coding agent, or null when it is not installed. */
  agentPath(id) {
    const agent = AGENTS[id]
    return agent ? paths.findExecutable(agent.names, agent.dirs()) : null
  }

  /**
   * Is the agent's CLI signed in? Claude Code answers through `claude auth status` (exit code 0).
   * The Copilot CLI has no status command: it is signed in after `copilot login` here, or when the
   * GitHub CLI is signed in, whose token it uses.
   */
  async signedIn(id, file = this.agentPath(id)) {
    if (!file) return false
    if (id === 'claude') return (await run(/\.cmd$/i.test(file) ? `"${file}"` : file, ['auth', 'status'], { timeout: 30000, shell: /\.cmd$/i.test(file) })).ok
    if (id === 'copilot') {
      if (this.config().connected?.copilot || env('COPILOT_GITHUB_TOKEN') || env('GH_TOKEN')) return true
      const gh = this.gh()
      return Boolean(gh) && (await run(gh, ['auth', 'token'], { timeout: 20000 })).ok
    }
    return null
  }

  /**
   * Connect: install the agent's CLI when it is missing, then sign in when needed. Started only by
   * the user's Connect button. Progress goes out as `agent-log` events; sign-in pages as `agent-url`.
   */
  async connectAgent(id) {
    if (!INSTALLERS[id]) throw new Error('This AI cannot be connected from here.')
    if (this.connecting) throw new Error('Another connection is still running.')
    const agent = AGENTS[id]
    const say = (line) => this.emit({ type: 'agent-log', id, line })
    this.connecting = { id, child: null, cancelled: false }
    const state = this.connecting
    const onSpawn = (child) => { state.child = child }
    try {
      if (!this.agentPath(id)) {
        const plan = installPlan(id, { tools: { winget: paths.IS_WIN ? paths.findExecutable(['winget.exe']) : null, brew: paths.IS_MAC ? paths.findExecutable(['brew'], ['/opt/homebrew/bin', '/usr/local/bin']) : null, npm: paths.npmCmd() } })
        if (!plan.length) throw new Error(`${agent.name} could not be installed: ${paths.IS_WIN ? 'winget and npm are' : 'Homebrew and npm are'} both missing. Run Setup first.`)
        for (const step of plan) {
          say(`Installing ${agent.name} with ${step.label}…`)
          const result = await stream(step.file, step.args, { onLine: say, onSpawn, shell: step.shell })
          if (state.cancelled) throw new Error('Cancelled.')
          if (this.agentPath(id)) break
          say(`${step.label} did not install it${result.ok ? '' : ` (exit code ${result.code})`}.`)
        }
        if (!this.agentPath(id)) throw new Error(`${agent.name} could not be installed. See the lines above.`)
        say(`${agent.name} is installed.`)
      }
      const file = this.agentPath(id)
      // A fresh Copilot install is signed in explicitly, so it does not depend on the GitHub CLI's token.
      const needsLogin = id === 'copilot' ? !this.config().connected?.copilot && !(await this.signedIn(id, file)) : !(await this.signedIn(id, file))
      if (needsLogin) {
        say(`Signing in to ${agent.vendor}. Finish in your browser…`)
        let announced = false
        const shell = /\.cmd$/i.test(file)
        const result = await stream(shell ? `"${file}"` : file, LOGIN[id], { onSpawn, shell, timeout: 10 * 60 * 1000, onLine: (line) => {
          say(line)
          const url = parseUrl(line)
          if (url && !announced) { announced = true; this.emit({ type: 'agent-url', id, url }) }
        } })
        if (state.cancelled) throw new Error('Cancelled.')
        if (!result.ok && !(await this.signedIn(id, file))) throw new Error(`Sign-in did not finish. You can also run \`${id === 'claude' ? 'claude' : 'copilot login'}\` in a terminal, then press Check again.`)
        say('Signed in.')
      }
      this.save({ connected: { ...this.config().connected, [id]: new Date().toISOString() } })
      return this.agents()
    } finally {
      this.connecting = null
    }
  }

  cancelConnect() {
    if (!this.connecting) return false
    this.connecting.cancelled = true
    this.connecting.child?.kill()
    return true
  }

  setAgent(choice) {
    const id = choice?.id
    if (!AGENT_IDS.includes(id)) throw new Error('Unknown AI.')
    const model = id === 'local' ? String(choice.model || '').slice(0, 120) : ''
    if (id === 'local' && !model) throw new Error('Choose a local model.')
    // PockPock itself can work through OpenClaw, which lets it run commands (build, test, automate).
    const openclaw = id === 'local' && choice.openclaw === true
    if (openclaw && !paths.openclawEntry()) throw new Error('OpenClaw is not installed. Run Setup and include OpenClaw.')
    return this.save({ agent: { id, model, openclaw, chosenAt: new Date().toISOString() } })
  }

  /** GitHub CLI and account state, and whether the account can push to the PockPock repository. */
  async github() {
    const gh = this.gh()
    if (!gh) return { installed: false, loggedIn: false, install: paths.IS_WIN ? 'Install the GitHub CLI: winget install --id GitHub.cli' : 'Install the GitHub CLI: brew install gh' }
    const user = await run(gh, ['api', 'user', '--jq', '{login: .login, id: .id}'], { timeout: 20000 })
    if (!user.ok) return { installed: true, loggedIn: false }
    let login = ''; let id = 0
    try { ({ login, id } = JSON.parse(user.stdout)) } catch { return { installed: true, loggedIn: false } }
    const repo = await run(gh, ['api', `repos/${UPSTREAM}`, '--jq', '.permissions.push'], { timeout: 20000 })
    return { installed: true, loggedIn: true, login, id, canPush: repo.ok && repo.stdout.trim() === 'true' }
  }

  /** Signs in with `gh auth login --web`: emits the one-time code, then waits until the browser step is done. */
  githubLogin() {
    const gh = this.gh()
    if (!gh) return Promise.reject(new Error('The GitHub CLI is not installed.'))
    if (this.loginChild) return Promise.reject(new Error('Sign-in is already running.'))
    return new Promise((resolve, reject) => {
      const child = spawn(gh, ['auth', 'login', '--hostname', 'github.com', '--git-protocol', 'https', '--web', '--scopes', 'repo,workflow'], { windowsHide: true, env: { ...paths.cleanEnv(), GH_PROMPT_DISABLED: '' } })
      this.loginChild = child
      let output = ''
      let announced = false
      const onData = (chunk) => {
        output += chunk.toString('utf8')
        const code = parseDeviceCode(output)
        if (code && !announced) {
          announced = true
          this.emit({ type: 'github-code', code, url: 'https://github.com/login/device' })
          child.stdin.write('\n') // "Press Enter to open github.com in your browser"
        }
      }
      child.stdout.on('data', onData)
      child.stderr.on('data', onData)
      child.on('error', (error) => { this.loginChild = null; reject(error) })
      child.on('exit', async (code) => {
        this.loginChild = null
        if (code === 0) resolve(await this.github())
        else reject(new Error(output.trim().split('\n').pop() || 'GitHub sign-in did not finish.'))
      })
    })
  }

  cancelLogin() {
    this.loginChild?.kill()
    this.loginChild = null
  }

  /** Is `dir` a clone of the PockPock repository (or a fork of it)? */
  async isClone(dir) {
    const git = this.git()
    if (!git || !fs.existsSync(path.join(dir, '.git'))) return false
    const remotes = await run(git, ['-C', dir, 'remote', '-v'], { timeout: 15000 })
    return remotes.ok && /PockPockAgent(\.git)?\s/i.test(remotes.stdout)
  }

  /** Clones (or forks and clones) the repository into `dir`, after the user allowed it. */
  async clone(dir) {
    if (typeof dir !== 'string' || !path.isAbsolute(dir)) throw new Error('Choose a folder.')
    const target = path.resolve(dir)
    const gh = this.gh()
    const git = this.git()
    if (!gh || !git) throw new Error('The GitHub CLI and Git are needed. Install them first.')
    const account = await this.github()
    if (!account.loggedIn) throw new Error('Connect GitHub first.')
    const say = (line) => this.emit({ type: 'clone-log', line })

    if (await this.isClone(target)) {
      say(`Using the existing copy in ${target}.`)
    } else {
      if (fs.existsSync(target) && fs.readdirSync(target).length) throw new Error('That folder is not empty. Choose an empty or new folder.')
      fs.mkdirSync(path.dirname(target), { recursive: true })
      let source = UPSTREAM
      if (!account.canPush) {
        say(`Your account cannot push to ${UPSTREAM}, so fixes will come from your own fork.`)
        const fork = await run(gh, ['repo', 'fork', UPSTREAM, '--clone=false', '--default-branch-only'], { timeout: 120000 })
        if (!fork.ok && !/already exists/i.test(fork.stderr + fork.stdout)) throw new Error(`Forking failed: ${(fork.stderr || fork.stdout).trim().split('\n').pop()}`)
        source = `${account.login}/PockPockAgent`
      }
      say(`Cloning ${source} into ${target}…`)
      const cloned = await run(gh, ['repo', 'clone', source, target], { timeout: 600000 })
      if (!cloned.ok) throw new Error(`Cloning failed: ${(cloned.stderr || cloned.stdout).trim().split('\n').pop()}`)
    }
    // Commits made by the Maintenance Manager use the GitHub no-reply address, never a personal email.
    await run(git, ['-C', target, 'config', 'user.name', account.login], { timeout: 15000 })
    await run(git, ['-C', target, 'config', 'user.email', `${account.id}+${account.login}@users.noreply.github.com`], { timeout: 15000 })
    say('Done.')
    return this.save({ repo: { dir: target, fork: !account.canPush, owner: account.canPush ? UPSTREAM.split('/')[0] : account.login, upstream: UPSTREAM, clonedAt: new Date().toISOString() } })
  }

  /** Current setup, re-checked: the chosen AI, GitHub, and whether the copy still exists. */
  async status() {
    const config = this.config()
    const repoOk = config.repo?.dir ? await this.isClone(config.repo.dir) : false
    return {
      agent: config.agent ?? null,
      repo: config.repo ? { ...config.repo, present: repoOk } : null,
      defaultFolder: this.defaultFolder(),
      ready: Boolean(config.agent && config.repo && repoOk),
      auto: config.auto === true,
    }
  }

  /** Automatic mode: work through open reports one at a time. Fixes still wait for the user's approval. */
  setAuto(enabled) {
    return this.save({ auto: enabled === true })
  }

  /** Forgets the setup. The clone is left on disk; the user can delete it in Explorer or Finder. */
  forget() {
    fs.rmSync(this.file, { force: true })
    return true
  }
}

module.exports = { Maintenance, parseDeviceCode, suggestLocalModel, UPSTREAM, AGENT_IDS }
