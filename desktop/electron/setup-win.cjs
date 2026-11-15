// Windows installers used by setup.cjs: winget first, direct downloads as the fallback, and NemoClaw
// inside WSL (Ubuntu) with Docker Desktop.
const fs = require('node:fs')
const os = require('node:os')
const path = require('node:path')
const { spawn } = require('node:child_process')
const paths = require('./paths.cjs')
const { run, nemoShell } = require('./platform.cjs')

const PYTHON_VERSION = '3.12.10'
const PYTHON_URL = `https://www.python.org/ftp/python/${PYTHON_VERSION}/python-${PYTHON_VERSION}-amd64.exe`
const OLLAMA_URL = 'https://ollama.com/download/OllamaSetup.exe'
const DISTRO = 'Ubuntu-24.04'

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

function packageManager() {
  return Boolean(paths.findExecutable(['winget.exe']))
}

async function winget(setup, id, extra = []) {
  if (!packageManager()) return false
  const result = await setup.exec('winget.exe', ['install', '-e', '--id', id, '--silent', '--accept-package-agreements', '--accept-source-agreements', '--disable-interactivity', ...extra])
  await refreshPath()
  return result.code === 0 || result.code === -1978335189 || result.code === 2316632107 // already installed
}

async function findPython() {
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

/** Returns a Python 3.12+ interpreter, installing Python 3.12 for this user if needed. */
async function ensurePython(setup, { download, SetupError }) {
  let python = await findPython()
  if (python) return python
  if (!(await winget(setup, 'Python.Python.3.12', ['--scope', 'user']))) {
    const installer = path.join(os.tmpdir(), `python-${PYTHON_VERSION}-amd64.exe`)
    await download(PYTHON_URL, installer, (fraction) => setup.step('core', 'python', 'Downloading Python 3.12', 'running', '', fraction))
    await setup.must(installer, ['/quiet', 'InstallAllUsers=0', 'PrependPath=0', 'Include_test=0', 'Include_launcher=0'], 'Installing Python')
  }
  python = await findPython()
  if (!python) throw new SetupError('Python 3.12 could not be installed. Install it from python.org and run setup again.')
  return python
}

async function ensureOllama(setup, { download, SetupError }) {
  if (paths.ollamaExe()) return
  if (!(await winget(setup, 'Ollama.Ollama'))) {
    const installer = path.join(os.tmpdir(), 'OllamaSetup.exe')
    await download(OLLAMA_URL, installer, (fraction) => setup.step('ollama', 'ollama', 'Downloading Ollama', 'running', '', fraction))
    await setup.must(installer, ['/VERYSILENT', '/NORESTART', '/SUPPRESSMSGBOXES'], 'Installing Ollama')
  }
  await refreshPath()
  if (!paths.ollamaExe()) throw new SetupError('Ollama could not be installed. Install it from ollama.com and run setup again.')
}

/** Sets a per-user environment variable for programs started later. Returns true if it changed. */
async function setUserEnv(name, value) {
  const current = await run('reg.exe', ['query', 'HKCU\\Environment', '/v', name], { timeout: 10000 })
  if (current.ok && current.stdout.includes(value)) return false
  await run('reg.exe', ['add', 'HKCU\\Environment', '/v', name, '/t', 'REG_SZ', '/d', value, '/f'], { timeout: 10000 })
  process.env[name] = value
  return true
}

async function ensureNode(setup, { SetupError }) {
  if (paths.nodeExe()) return
  if (!(await winget(setup, 'OpenJS.NodeJS.LTS'))) throw new SetupError('Node.js could not be installed. Install Node.js 24 LTS from nodejs.org and run setup again.')
  if (!paths.nodeExe()) throw new SetupError('Node.js was installed but is not on PATH yet. Restart Windows and run setup again.')
}

/** npm on Windows is a .cmd script, which must run through the shell. */
function npmInvocation(args) {
  const npm = paths.npmCmd()
  return npm ? { file: npm, args, options: { shell: true } } : null
}

/** Returns 'done', 'restart' (Windows must restart) or 'action' (the user has to do something). */
async function installNemoClaw(setup, { NEMOCLAW_ENV, SetupError, services }) {
  const C = 'nemoclaw'
  setup.step(C, 'wsl', 'WSL and Ubuntu', 'running')
  const status = await run('wsl.exe', ['--status'], { timeout: 30000 })
  if (!status.ok) {
    setup.log('WSL is not installed. Windows will ask for administrator permission.')
    await setup.exec('powershell.exe', ['-NoProfile', '-Command', `Start-Process wsl.exe -ArgumentList '--install','-d','${DISTRO}','--no-launch' -Verb RunAs -Wait`])
    setup.step(C, 'wsl', 'WSL and Ubuntu', 'waiting', 'Restart Windows to finish')
    setup.restartMessage = 'Restart Windows to finish installing WSL, then open PockPock Agent. Setup continues where it stopped.'
    return 'restart'
  }
  const distros = (await run('wsl.exe', ['-l', '-q'], { timeout: 30000 })).stdout.replace(/\0/g, '').split(/\r?\n/).map((line) => line.trim()).filter(Boolean)
  if (!distros.includes(DISTRO)) await setup.must('wsl.exe', ['--install', '-d', DISTRO, '--no-launch'], 'Installing Ubuntu')
  const probe = await run('wsl.exe', ['-d', DISTRO, '-e', 'id', '-un'], { timeout: 60000 })
  if (!probe.ok || probe.stdout.replace(/\0/g, '').trim() === 'root' || !probe.stdout.trim()) {
    // Ubuntu asks for a username and password on first launch; that cannot be done silently.
    spawn('cmd.exe', ['/c', 'start', 'Ubuntu first run', 'wsl.exe', '-d', DISTRO], { detached: true, stdio: 'ignore' }).unref()
    setup.actionMessage = 'A terminal opened to finish setting up Ubuntu. Choose a username and password there, close it, then press Continue setup.'
    setup.step(C, 'wsl', 'WSL and Ubuntu', 'waiting', 'Create your Ubuntu user in the window that opened')
    return 'action'
  }
  await run('wsl.exe', ['--set-default', DISTRO], { timeout: 30000 })
  setup.step(C, 'wsl', 'WSL and Ubuntu', 'done')
  const wslConfig = path.join(os.homedir(), '.wslconfig')
  if (fs.existsSync(wslConfig) && /networkingMode\s*=\s*mirrored/i.test(fs.readFileSync(wslConfig, 'utf8'))) {
    setup.log('Warning: .wslconfig uses networkingMode=mirrored, which breaks the NemoClaw dashboard port. Remove that line if onboarding fails.')
  }
  setup.step(C, 'docker', 'Docker Desktop', 'running')
  if (!paths.dockerCli()) {
    setup.log('Installing Docker Desktop. Windows will ask for administrator permission.')
    if (!(await winget(setup, 'Docker.DockerDesktop'))) throw new SetupError('Docker Desktop could not be installed. Install it from docker.com and run setup again.')
  }
  await services.ensureDocker()
  setup.step(C, 'docker', 'Docker Desktop', 'done')
  setup.step(C, 'install', 'NemoClaw', 'running', 'This can take 15 to 30 minutes')
  const installed = await nemoShell('command -v nemoclaw >/dev/null 2>&1 && echo yes', 30000)
  if (!installed.stdout.includes('yes')) {
    await setup.must('wsl.exe', ['-d', DISTRO, '-e', 'bash', '-lc', `curl -fsSL https://www.nvidia.com/nemoclaw.sh | env ${NEMOCLAW_ENV} bash`], 'Installing NemoClaw')
  }
  return 'installed'
}

module.exports = { refreshPath, packageManager, ensurePython, ensureOllama, setUserEnv, ensureNode, npmInvocation, installNemoClaw, DISTRO }
