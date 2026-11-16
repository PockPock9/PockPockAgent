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

const UPSTREAM = 'PockPock9/PockPockAgent'
const AGENT_IDS = ['local', 'claude', 'codex', 'copilot']

const home = os.homedir()
const env = (name) => process.env[name] || ''

/** Where each coding agent's command-line tool is usually installed. */
const AGENTS = {
  claude: {
    name: 'Claude Code', vendor: 'Anthropic',
    names: paths.IS_WIN ? ['claude.exe', 'claude.cmd'] : ['claude'],
    dirs: [path.join(home, '.local', 'bin'), path.join(home, '.claude', 'local'), path.join(env('APPDATA'), 'npm'), '/opt/homebrew/bin', '/usr/local/bin'],
    install: 'Install Claude Code (https://claude.com/claude-code), then run `claude` once in a terminal to sign in.',
  },
  codex: {
    name: 'OpenAI Codex', vendor: 'OpenAI',
    names: paths.IS_WIN ? ['codex.exe', 'codex.cmd'] : ['codex'],
    dirs: [path.join(env('APPDATA'), 'npm'), path.join(home, '.local', 'bin'), '/opt/homebrew/bin', '/usr/local/bin'],
    install: 'Install the Codex CLI (`npm install -g @openai/codex`), then run `codex` once in a terminal to sign in.',
  },
  copilot: {
    name: 'GitHub Copilot', vendor: 'GitHub',
    names: paths.IS_WIN ? ['copilot.exe', 'copilot.cmd'] : ['copilot'],
    dirs: [path.join(env('LOCALAPPDATA'), 'GitHubCopilotCLI'), path.join(env('APPDATA'), 'npm'), path.join(home, '.local', 'bin'), '/opt/homebrew/bin', '/usr/local/bin'],
    install: 'Install the GitHub Copilot CLI (https://github.com/features/copilot/cli), then run `copilot` once in a terminal to sign in. It needs a Copilot subscription.',
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
      id: 'local', name: 'PockPock itself', vendor: '', installed: models.length > 0,
      models, suggested: suggestLocalModel(models),
      dataNotice: 'PockPock fixes itself with a model on this PC; nothing leaves it. Local models are slower and fix fewer problems, and a fix that fails the checks is not proposed.',
      install: tags === null ? 'Ollama is not running. Start it on the Services page.' : 'Ollama has no models. Run Setup to download one.',
    }
    const others = await Promise.all(Object.entries(AGENTS).map(async ([id, agent]) => {
      const file = paths.findExecutable(agent.names, agent.dirs)
      let version = ''
      if (file) {
        const result = await run(file, ['--version'], { timeout: 20000, shell: /\.cmd$/i.test(file) })
        version = (result.stdout || result.stderr).trim().split('\n')[0].slice(0, 80)
      }
      return {
        id, name: agent.name, vendor: agent.vendor, installed: Boolean(file), version,
        dataNotice: `Sends the report, the parts of the PockPock code it reads, and its changes to ${agent.vendor}. Uses your own ${agent.name} account.`,
        install: agent.install,
      }
    }))
    const order = ['local', 'copilot', 'claude', 'codex']
    return [local, ...others].sort((a, b) => order.indexOf(a.id) - order.indexOf(b.id))
  }

  /** The command-line tool of a cloud coding agent, or null when it is not installed. */
  agentPath(id) {
    const agent = AGENTS[id]
    return agent ? paths.findExecutable(agent.names, agent.dirs) : null
  }

  setAgent(choice) {
    const id = choice?.id
    if (!AGENT_IDS.includes(id)) throw new Error('Unknown AI.')
    const model = id === 'local' ? String(choice.model || '').slice(0, 120) : ''
    if (id === 'local' && !model) throw new Error('Choose a local model.')
    return this.save({ agent: { id, model, chosenAt: new Date().toISOString() } })
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
