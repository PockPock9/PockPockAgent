// Connecting a cloud coding agent (Claude Code, OpenAI Codex, GitHub Copilot) for the Maintenance Manager: install
// its command-line tool when it is missing, then sign in with the tool's own browser flow. Both steps
// start only when the user presses Connect. No token passes through PockPock: each tool keeps its own
// credentials in the system credential store.
const { spawn } = require('node:child_process')
const paths = require('./paths.cjs')

/** Install commands to try in order. Every argument is a constant; nothing here comes from user input. */
const INSTALLERS = {
  claude: {
    winget: 'Anthropic.ClaudeCode',
    brew: ['install', '--cask', 'claude-code'],
    npm: '@anthropic-ai/claude-code',
  },
  codex: {
    brew: ['install', '--cask', 'codex'],
    npm: '@openai/codex',
  },
  copilot: {
    winget: 'GitHub.Copilot',
    brew: ['install', 'copilot-cli'],
    npm: '@github/copilot',
  },
}

/** Sign-in commands. Each opens the vendor's page in the browser and waits for the user there. */
const LOGIN = {
  claude: ['auth', 'login'],
  codex: ['login'],
  copilot: ['login'],
}

/** Sign-in status commands: exit code 0 when the tool is signed in. Copilot has none. */
const STATUS = {
  claude: ['auth', 'status'],
  codex: ['login', 'status'],
}

/**
 * Which account a signed-in tool uses, from its status output, so the user sees it before connecting.
 * Claude Code prints JSON (email, plan); Codex prints a line such as "Logged in using ChatGPT".
 */
function parseAccount(id, output) {
  const text = plain(output).trim()
  if (id === 'claude') {
    try {
      const json = JSON.parse(text.slice(text.indexOf('{'), text.lastIndexOf('}') + 1))
      const tier = typeof json.subscriptionType === 'string' ? json.subscriptionType : ''
      const plan = tier ? `Claude ${tier[0].toUpperCase()}${tier.slice(1)}` : json.authMethod === 'apiKey' ? 'API key' : ''
      return { email: typeof json.email === 'string' ? json.email.slice(0, 120) : '', plan }
    } catch { return { email: '', plan: '' } }
  }
  const line = text.split('\n').map((item) => item.trim()).find((item) => /logged in|signed in/i.test(item)) || ''
  return { email: '', plan: line.slice(0, 120) }
}

/**
 * The install attempts for one agent on this machine: winget (Windows) or Homebrew (macOS) first,
 * npm as the fallback. `tools` holds the paths of the installers that exist.
 */
function installPlan(id, { platform = process.platform, tools = {} } = {}) {
  const spec = INSTALLERS[id]
  if (!spec) return []
  const plan = []
  if (platform === 'win32' && tools.winget && spec.winget) plan.push({ label: 'winget', file: tools.winget, args: ['install', '-e', '--id', spec.winget, '--silent', '--accept-package-agreements', '--accept-source-agreements', '--disable-interactivity'], shell: false })
  if (platform === 'darwin' && tools.brew && spec.brew) plan.push({ label: 'Homebrew', file: tools.brew, args: spec.brew, shell: false })
  if (tools.npm) {
    const shell = /\.(cmd|bat)$/i.test(tools.npm)
    plan.push({ label: 'npm', file: shell ? `"${tools.npm}"` : tools.npm, args: ['install', '-g', spec.npm], shell })
  }
  return plan
}

/** The first https link in a line of CLI output (sign-in pages), without trailing punctuation. */
function parseUrl(line) {
  const match = /https:\/\/[^\s"'<>]+/.exec(String(line))
  return match ? match[0].replace(/[).,;]+$/, '') : ''
}

/** Removes terminal colour and cursor codes so CLI output reads as plain text. */
function plain(text) {
  // eslint-disable-next-line no-control-regex
  return String(text).replace(/\u001b\[[0-9;?]*[ -/]*[@-~]/g, '').replace(/\u001b\][^\u0007]*\u0007/g, '').replace(/\r/g, '\n')
}

/** Runs a command, passing each output line to onLine. Resolves with { ok, code, output }. */
function stream(file, args, { onLine, onSpawn, shell = false, timeout = 15 * 60 * 1000 } = {}) {
  return new Promise((resolve) => {
    let output = ''
    let child
    try { child = spawn(file, args, { windowsHide: true, shell, env: paths.cleanEnv(), stdio: ['pipe', 'pipe', 'pipe'] }) } catch (error) { resolve({ ok: false, code: -1, output: error.message }); return }
    const timer = setTimeout(() => child.kill(), timeout)
    const onData = (chunk) => {
      const text = plain(chunk.toString('utf8'))
      output = (output + text).slice(-20_000)
      for (const line of text.split('\n')) if (line.trim()) onLine?.(line.trim().slice(0, 300))
    }
    child.stdout.on('data', onData)
    child.stderr.on('data', onData)
    child.on('error', (error) => { clearTimeout(timer); resolve({ ok: false, code: -1, output: `${output}\n${error.message}` }) })
    child.on('exit', (code) => { clearTimeout(timer); resolve({ ok: code === 0, code, output }) })
    onSpawn?.(child)
  })
}

module.exports = { INSTALLERS, LOGIN, STATUS, installPlan, parseAccount, parseUrl, plain, stream }
