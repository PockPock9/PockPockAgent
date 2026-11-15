// macOS installers used by setup.cjs. Python (through uv), Node.js and OpenClaw are installed into
// PockPock's own runtime folder, so they need no Homebrew and no administrator password. Ollama goes
// to Applications. Only NemoClaw's Docker Desktop asks for the password, once.
const crypto = require('node:crypto')
const fs = require('node:fs')
const os = require('node:os')
const path = require('node:path')
const paths = require('./paths.cjs')
const { run, nemoShell, dockerReady, dockerDesktopApp } = require('./platform.cjs')

const ARCH = os.arch() === 'arm64' ? 'arm64' : 'x64'
const UV_TARGET = ARCH === 'arm64' ? 'aarch64-apple-darwin' : 'x86_64-apple-darwin'
const UV_URL = `https://github.com/astral-sh/uv/releases/latest/download/uv-${UV_TARGET}.tar.gz`
const OLLAMA_RELEASE = 'https://github.com/ollama/ollama/releases/latest/download'
const NODE_INDEX = 'https://nodejs.org/dist/latest-v24.x'
const DOCKER_URL = `https://desktop.docker.com/mac/main/${ARCH === 'arm64' ? 'arm64' : 'amd64'}/Docker.dmg`

const binDir = () => path.join(paths.runtimeRoot(), 'bin')
const uvPath = () => path.join(binDir(), 'uv')

function fetchText(url) {
  return fetch(url, { headers: { 'User-Agent': 'PockPock-Agent-Setup' }, signal: AbortSignal.timeout(60000) }).then((response) => {
    if (!response.ok) throw new Error(`HTTP ${response.status} for ${url}`)
    return response.text()
  })
}

function sha256(file) {
  return new Promise((resolve, reject) => {
    const hash = crypto.createHash('sha256')
    fs.createReadStream(file).on('data', (chunk) => hash.update(chunk)).on('end', () => resolve(hash.digest('hex'))).on('error', reject)
  })
}

async function verify(file, expected, what, SetupError) {
  if (!expected) return
  const actual = await sha256(file)
  if (actual !== expected.toLowerCase()) throw new SetupError(`${what} did not match its published checksum. Run setup again.`)
}

function packageManager() {
  return true // nothing to detect: downloads are direct
}

async function refreshPath() {
  paths.fixPath()
}

async function pythonVersionOk(file) {
  const result = await run(file, ['-c', 'import sys; print("%d.%d" % sys.version_info[:2])'], { timeout: 20000 })
  const [major, minor] = result.stdout.trim().split('.').map(Number)
  return result.ok && major === 3 && minor >= 12
}

/** An existing Python 3.12+ (Homebrew or python.org), else one installed by uv into the runtime folder. */
async function ensurePython(setup, { download, SetupError }) {
  for (const candidate of ['/opt/homebrew/bin/python3.12', '/usr/local/bin/python3.12', '/Library/Frameworks/Python.framework/Versions/3.12/bin/python3', paths.findExecutable(['python3.12'])]) {
    if (candidate && fs.existsSync(candidate) && (await pythonVersionOk(candidate))) return candidate
  }
  const env = paths.cleanEnv({ UV_PYTHON_INSTALL_DIR: path.join(paths.runtimeRoot(), 'python'), UV_NO_MODIFY_PATH: '1' })
  if (!fs.existsSync(uvPath())) {
    fs.mkdirSync(binDir(), { recursive: true })
    const archive = path.join(os.tmpdir(), `uv-${UV_TARGET}.tar.gz`)
    await download(UV_URL, archive, (fraction) => setup.step('core', 'python', 'Downloading uv (Python installer)', 'running', '', fraction))
    const expected = (await fetchText(`${UV_URL}.sha256`).catch(() => '')).trim().split(/\s+/)[0]
    await verify(archive, expected, 'The uv download', SetupError)
    const unpack = fs.mkdtempSync(path.join(os.tmpdir(), 'pockpock-uv-'))
    await setup.must('/usr/bin/tar', ['-xzf', archive, '-C', unpack], 'Unpacking uv')
    fs.copyFileSync(path.join(unpack, `uv-${UV_TARGET}`, 'uv'), uvPath())
    fs.chmodSync(uvPath(), 0o755)
  }
  await setup.must(uvPath(), ['python', 'install', '3.12'], 'Installing Python 3.12', { env })
  const found = await run(uvPath(), ['python', 'find', '3.12'], { env, timeout: 30000 })
  const python = found.stdout.trim().split('\n').pop()
  if (!found.ok || !python || !fs.existsSync(python)) throw new SetupError('Python 3.12 could not be installed. See the setup log.')
  return python
}

/** Ollama.app in /Applications (or ~/Applications when that is not writable). Its command-line
 * server is run directly, so the app's own first-run window never appears. */
async function ensureOllama(setup, { download, SetupError }) {
  if (paths.ollamaExe()) return
  const archive = path.join(os.tmpdir(), 'Ollama-darwin.zip')
  await download(`${OLLAMA_RELEASE}/Ollama-darwin.zip`, archive, (fraction) => setup.step('ollama', 'ollama', 'Downloading Ollama', 'running', '', fraction))
  const sums = await fetchText(`${OLLAMA_RELEASE}/sha256sum.txt`).catch(() => '')
  const expected = ollamaArchiveSum(sums)
  await verify(archive, expected, 'The Ollama download', SetupError)
  let target = '/Applications'
  try { fs.accessSync(target, fs.constants.W_OK) } catch { target = path.join(paths.HOME, 'Applications'); fs.mkdirSync(target, { recursive: true }) }
  await setup.must('/usr/bin/ditto', ['-x', '-k', archive, target], 'Installing Ollama')
  if (!paths.ollamaExe()) throw new SetupError('Ollama was unpacked but its command was not found. Install Ollama from ollama.com and run setup again.')
}

/** Makes a variable visible to apps started later in this login session (Ollama.app included). */
async function setUserEnv(name, value) {
  if (process.env[name] === value) return false
  await run('/bin/launchctl', ['setenv', name, value], { timeout: 10000 })
  process.env[name] = value
  return true
}

/** Splits a checksum list ("<sha256>  <file>" per line) into entries. */
function checksumEntries(sums) {
  return sums.split('\n').map((line) => line.trim().split(/\s+/)).filter(([sha256, file]) => /^[a-f0-9]{64}$/.test(sha256 || '') && file).map(([sha256, file]) => ({ sha256, file: file.replace(/^\.\//, '') }))
}

/** The macOS .tar.gz entry in Node.js's SHASUMS256.txt for one architecture. */
function nodeArchive(sums, arch) {
  return checksumEntries(sums).find((entry) => /^node-v[\d.]+-darwin-(arm64|x64)\.tar\.gz$/.test(entry.file) && entry.file.endsWith(`-darwin-${arch}.tar.gz`)) || null
}

/** The Ollama.app archive's checksum in Ollama's sha256sum.txt. */
function ollamaArchiveSum(sums) {
  return checksumEntries(sums).find((entry) => entry.file === 'Ollama-darwin.zip')?.sha256
}

async function nodeVersionOk(file) {
  const result = await run(file, ['--version'], { timeout: 20000 })
  return result.ok && Number(/^v(\d+)/.exec(result.stdout.trim())?.[1] || 0) >= 22
}

/** Node.js 22+ already on this Mac, else Node.js 24 LTS unpacked into the runtime folder. */
async function ensureNode(setup, { download, SetupError }) {
  const existing = paths.nodeExe()
  if (existing && (await nodeVersionOk(existing))) return
  const sums = await fetchText(`${NODE_INDEX}/SHASUMS256.txt`)
  const match = nodeArchive(sums, ARCH)
  if (!match) throw new SetupError('Could not find a Node.js 24 download for this Mac.')
  const archive = path.join(os.tmpdir(), match.file)
  await download(`${NODE_INDEX}/${match.file}`, archive, (fraction) => setup.step('openclaw', 'node', 'Downloading Node.js', 'running', '', fraction))
  await verify(archive, match.sha256, 'The Node.js download', SetupError)
  const target = path.join(paths.runtimeRoot(), 'node')
  fs.rmSync(target, { recursive: true, force: true })
  fs.mkdirSync(target, { recursive: true })
  await setup.must('/usr/bin/tar', ['-xzf', archive, '-C', target, '--strip-components', '1'], 'Unpacking Node.js')
  paths.fixPath()
  if (!paths.nodeExe()) throw new SetupError('Node.js was unpacked but could not be found. See the setup log.')
}

/** Global npm packages go to the runtime folder (npm_config_prefix in cleanEnv), so no sudo. */
function npmInvocation(args) {
  const npm = paths.npmCmd()
  return npm ? { file: npm, args, options: {} } : null
}

function consoleUser() {
  return os.userInfo().username
}

/** Installs Docker Desktop from Docker's disk image. macOS asks for the administrator password once,
 * in its own dialog; the install also accepts Docker's licence so its first-run window is skipped. */
async function installDockerDesktop(setup, { download, SetupError }) {
  const image = path.join(os.tmpdir(), 'Docker.dmg')
  await download(DOCKER_URL, image, (fraction) => setup.step('nemoclaw', 'docker', 'Downloading Docker Desktop', 'running', '', fraction))
  const mount = fs.mkdtempSync(path.join(os.tmpdir(), 'pockpock-docker-'))
  await setup.must('/usr/bin/hdiutil', ['attach', image, '-nobrowse', '-readonly', '-mountpoint', mount], 'Opening the Docker Desktop image')
  try {
    const installer = path.join(mount, 'Docker.app', 'Contents', 'MacOS', 'install')
    if (!fs.existsSync(installer)) throw new SetupError('The Docker Desktop image did not contain its installer.')
    const quote = (value) => `'${value.replace(/'/g, `'\\''`)}'`
    const shell = `${quote(installer)} --accept-license --user=${quote(consoleUser())}`
    const script = `do shell script ${JSON.stringify(shell)} with prompt "PockPock Agent needs your password to install Docker Desktop for the NemoClaw engine." with administrator privileges`
    const result = await setup.exec('/usr/bin/osascript', ['-e', script])
    if (result.code !== 0) throw new SetupError(/User canceled|-128/.test(result.tail) ? 'Docker Desktop was not installed because the password prompt was cancelled.' : 'Docker Desktop could not be installed. See the setup log.')
  } finally {
    await run('/usr/bin/hdiutil', ['detach', mount, '-quiet'], { timeout: 60000 })
  }
}

/** Returns 'installed' when NemoClaw's command is present, or 'action' when the user must act. */
async function installNemoClaw(setup, context) {
  const { NEMOCLAW_ENV, SetupError, services } = context
  const C = 'nemoclaw'
  if (ARCH !== 'arm64') throw new SetupError('NemoClaw needs a Mac with Apple silicon.')
  setup.step(C, 'tools', 'Xcode Command Line Tools', 'running')
  if (!(await run('/usr/bin/xcode-select', ['-p'], { timeout: 20000 })).ok) {
    await run('/usr/bin/xcode-select', ['--install'], { timeout: 20000 })
    setup.actionMessage = 'macOS opened a window to install the Command Line Tools that NemoClaw needs. Press Install there, wait for it to finish, then press Continue setup.'
    setup.step(C, 'tools', 'Xcode Command Line Tools', 'waiting', 'Finish the installation in the window macOS opened')
    return 'action'
  }
  setup.step(C, 'tools', 'Xcode Command Line Tools', 'done')
  setup.step(C, 'docker', 'Docker Desktop', 'running')
  if (!(await dockerReady())) {
    if (!dockerDesktopApp() && !paths.findExecutable(['colima'])) await installDockerDesktop(setup, context)
    try {
      await services.ensureDocker()
    } catch {
      setup.actionMessage = 'Docker Desktop is starting for the first time. If it shows a window, finish it (sign-in is optional), then press Continue setup.'
      setup.step(C, 'docker', 'Docker Desktop', 'waiting', 'Finish Docker Desktop\'s first start')
      return 'action'
    }
  }
  setup.step(C, 'docker', 'Docker Desktop', 'done')
  setup.step(C, 'install', 'NemoClaw', 'running', 'This can take 15 to 30 minutes')
  const installed = await nemoShell('command -v nemoclaw >/dev/null 2>&1 && echo yes', 30000)
  if (!installed.stdout.includes('yes')) {
    await setup.must('/bin/bash', ['-lc', `curl -fsSL https://www.nvidia.com/nemoclaw.sh | env ${NEMOCLAW_ENV} bash`], 'Installing NemoClaw')
  }
  return 'installed'
}

module.exports = { nodeArchive, ollamaArchiveSum, refreshPath, packageManager, ensurePython, ensureOllama, setUserEnv, ensureNode, npmInvocation, installNemoClaw, DISTRO: '' }
