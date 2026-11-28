// macOS installers used by setup.cjs. Python (through uv), Node.js and OpenClaw are installed into
// PockPock's own runtime folder, so they need no Homebrew and no administrator password. Ollama goes
// to Applications.
const crypto = require('node:crypto')
const fs = require('node:fs')
const os = require('node:os')
const path = require('node:path')
const paths = require('./paths.cjs')
const { run } = require('./platform.cjs')

const ARCH = os.arch() === 'arm64' ? 'arm64' : 'x64'
const UV_TARGET = ARCH === 'arm64' ? 'aarch64-apple-darwin' : 'x86_64-apple-darwin'
const UV_URL = `https://github.com/astral-sh/uv/releases/latest/download/uv-${UV_TARGET}.tar.gz`
const OLLAMA_RELEASE = 'https://github.com/ollama/ollama/releases/latest/download'
const NODE_INDEX = 'https://nodejs.org/dist/latest-v24.x'

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

module.exports = { nodeArchive, ollamaArchiveSum, refreshPath, packageManager, ensurePython, ensureOllama, setUserEnv, ensureNode, npmInvocation }
