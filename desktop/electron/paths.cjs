// Where PockPock's pieces live, in development (repository checkout) and when installed, on Windows
// and macOS. Everything the app installs for itself goes under runtimeRoot(), so setup needs no
// administrator rights for Python, Node.js or OpenClaw.
const fs = require('node:fs')
const os = require('node:os')
const path = require('node:path')
const { app } = require('electron')

const IS_WIN = process.platform === 'win32'
const IS_MAC = process.platform === 'darwin'
const HOME = os.homedir()

/** Per-user application data: %LOCALAPPDATA% on Windows, ~/Library/Application Support on macOS. */
const LOCAL = IS_WIN
  ? process.env.LOCALAPPDATA || path.join(HOME, 'AppData', 'Local')
  : IS_MAC ? path.join(HOME, 'Library', 'Application Support') : process.env.XDG_DATA_HOME || path.join(HOME, '.local', 'share')

const exe = (name) => (IS_WIN ? `${name}.exe` : name)

function repoRoot() {
  return process.env.POCKPOCK_ROOT || path.resolve(__dirname, '..', '..')
}

/** The backend source: bundled next to the app when installed, the checkout's backend/ otherwise. */
function backendRoot() {
  if (app.isPackaged) return path.join(process.resourcesPath, 'backend')
  return path.join(repoRoot(), 'backend')
}

/** The app's own Python, Node.js, uv and npm packages, kept outside the (read-only) app bundle. */
function runtimeRoot() {
  return path.join(LOCAL, 'PockPock', 'runtime')
}

function venvRoot() {
  if (process.env.POCKPOCK_VENV) return process.env.POCKPOCK_VENV
  return app.isPackaged ? path.join(runtimeRoot(), 'venv') : path.join(repoRoot(), '.venv')
}

function venvPython() {
  return path.join(venvRoot(), IS_WIN ? 'Scripts\\python.exe' : 'bin/python')
}

/** The interpreter the venv was made from (pyvenv.cfg), or null. On Windows the venv's python.exe
 * is a launcher that starts this interpreter as a child; see backend/scripts/hidden_launch.py. */
function basePython() {
  try {
    const config = fs.readFileSync(path.join(venvRoot(), 'pyvenv.cfg'), 'utf8')
    const value = (key) => new RegExp(`^\\s*${key}\\s*=\\s*(.+?)\\s*$`, 'm').exec(config)?.[1]
    const candidates = [value('executable'), value('home') && path.join(value('home'), IS_WIN ? 'python.exe' : 'python3')]
    return candidates.find((file) => file && fs.existsSync(file)) || null
  } catch {
    return null
  }
}

/** Shared with the Python services (pockpock_paths.app_data_dir("PockPock")). */
function dataRoot() {
  return path.join(LOCAL, 'PockPock')
}

/**
 * Moves data from the folder used before the rename (FrogAI) into dataRoot(), once. Only entries
 * missing from the new folder are moved; anything that cannot be moved yet (a file held open by a
 * service from an older version) is retried on the next start. Mirrors pockpock_paths.migrate_legacy_data.
 */
function migrateLegacyData() {
  const legacy = path.join(LOCAL, 'FrogAI')
  if (!fs.existsSync(legacy)) return []
  fs.mkdirSync(dataRoot(), { recursive: true })
  const moved = []
  for (const name of fs.readdirSync(legacy)) {
    const target = path.join(dataRoot(), name)
    if (fs.existsSync(target)) continue
    try { fs.renameSync(path.join(legacy, name), target); moved.push(name) } catch { /* retried next start */ }
  }
  try { fs.rmdirSync(legacy) } catch { /* not empty yet */ }
  return moved
}

function logsRoot() {
  const folder = path.join(dataRoot(), 'logs')
  fs.mkdirSync(folder, { recursive: true })
  return folder
}

/** Node.js and global npm packages the app installed for itself (macOS; Windows uses winget). */
const runtimeNodeBin = () => path.join(runtimeRoot(), 'node', IS_WIN ? '' : 'bin')
const npmPrefix = () => path.join(runtimeRoot(), 'npm-global')
const npmPrefixBin = () => (IS_WIN ? npmPrefix() : path.join(npmPrefix(), 'bin'))

/**
 * Folders that hold the tools PockPock runs. An app opened from Finder gets only
 * /usr/bin:/bin:/usr/sbin:/sbin, so on macOS these are added to PATH explicitly.
 */
function toolDirs() {
  if (IS_WIN) return [path.join(LOCAL, 'Programs', 'Ollama'), path.join(process.env.APPDATA || '', 'npm'), npmPrefixBin()]
  return [
    runtimeNodeBin(),
    npmPrefixBin(),
    path.join(runtimeRoot(), 'bin'),
    path.join(HOME, '.local', 'bin'),
    '/opt/homebrew/bin',
    '/usr/local/bin',
    '/Applications/Docker.app/Contents/Resources/bin',
    path.join(HOME, '.docker', 'bin'),
  ]
}

/** Call once at startup: makes every later lookup and child process see the tool folders. */
function fixPath() {
  const key = Object.keys(process.env).find((name) => name.toLowerCase() === 'path') || 'PATH'
  const current = (process.env[key] || '').split(path.delimiter).filter(Boolean)
  const base = IS_MAC && !current.includes('/usr/sbin') ? [...current, '/usr/bin', '/bin', '/usr/sbin', '/sbin'] : current
  process.env[key] = [...new Set([...toolDirs(), ...base])].join(path.delimiter)
}

/** First match for an executable on PATH or in known install folders. */
function findExecutable(names, extra = []) {
  const dirs = (process.env.PATH || '').split(path.delimiter).filter(Boolean)
  for (const dir of [...extra, ...toolDirs(), ...dirs]) {
    for (const name of names) {
      const candidate = path.join(dir, name)
      try {
        const stat = fs.statSync(candidate)
        if (stat.isFile() && (IS_WIN || (stat.mode & 0o111))) return candidate
      } catch {
        // App execution aliases (such as winget.exe in WindowsApps) cannot be stat'ed, only lstat'ed.
        if (IS_WIN) { try { fs.lstatSync(candidate); return candidate } catch { /* keep looking */ } }
      }
    }
  }
  return null
}

/** Where Ollama.app is (or will be) installed on macOS. */
function ollamaAppDirs() {
  return ['/Applications/Ollama.app', path.join(HOME, 'Applications', 'Ollama.app')]
}

function ollamaExe() {
  if (IS_MAC) return findExecutable(['ollama'], ollamaAppDirs().map((dir) => path.join(dir, 'Contents', 'Resources')))
  return findExecutable([exe('ollama'), 'ollama'], [path.join(LOCAL, 'Programs', 'Ollama')])
}

/** Ollama's own server log when something other than this app started it. */
function ollamaServerLog() {
  return IS_WIN ? path.join(LOCAL, 'Ollama', 'server.log') : path.join(HOME, '.ollama', 'logs', 'server.log')
}

function nodeExe() {
  return findExecutable([exe('node')])
}

function npmCmd() {
  return findExecutable(IS_WIN ? ['npm.cmd'] : ['npm'])
}

function openclawCmd() {
  return findExecutable(IS_WIN ? ['openclaw.cmd', 'openclaw'] : ['openclaw'])
}

/** OpenClaw's JavaScript entry point, run with node directly: no shell quoting, no PowerShell
 * execution policy, and arguments (including JSON) arrive exactly as given. */
function openclawEntry() {
  const cmd = openclawCmd()
  const node = nodeExe()
  if (!cmd || !node) return null
  let real = cmd
  try { real = fs.realpathSync(cmd) } catch { /* keep the link */ }
  const candidates = [
    path.join(path.dirname(cmd), 'node_modules', 'openclaw', 'openclaw.mjs'), // Windows npm prefix
    path.join(path.dirname(cmd), '..', 'lib', 'node_modules', 'openclaw', 'openclaw.mjs'), // Unix npm prefix
    path.join(path.dirname(real), 'openclaw.mjs'), // bin symlink resolved into the package
  ]
  for (const script of candidates) {
    if (fs.existsSync(script)) return { node, script }
  }
  return null
}

/** OpenClaw writes its gateway log to a dated file in its temp folder. */
function openclawLog() {
  const day = new Date().toISOString().slice(0, 10)
  const dirs = IS_WIN ? [path.join(os.tmpdir(), 'openclaw')] : ['/tmp/openclaw', path.join(os.tmpdir(), 'openclaw')]
  const files = dirs.map((dir) => path.join(dir, `openclaw-${day}.log`))
  return files.find((file) => fs.existsSync(file)) || files[0]
}

function dockerCli() {
  return findExecutable([exe('docker')], IS_WIN ? [path.join(process.env.ProgramFiles || 'C:\\Program Files', 'Docker', 'Docker', 'resources', 'bin')] : [])
}

/** Environment for child processes: tool folders on PATH, and on Windows without Git's Unix tools,
 * which would otherwise shadow Windows programs such as notepad. */
function cleanEnv(extra = {}) {
  const env = { ...process.env, ...extra }
  delete env.ELECTRON_RUN_AS_NODE
  const key = Object.keys(env).find((name) => name.toLowerCase() === 'path') || 'PATH'
  let dirs = (env[key] || '').split(path.delimiter).filter(Boolean)
  if (IS_WIN) dirs = dirs.filter((dir) => !/\\Git\\(usr|mingw64)\\bin/i.test(dir))
  env[key] = [...new Set([...toolDirs(), ...dirs])].join(path.delimiter)
  if (IS_MAC) {
    env.npm_config_prefix = env.npm_config_prefix || npmPrefix()
    // The installed backend sits inside the signed app bundle; writing __pycache__ there would
    // break the bundle's signature seal.
    if (backendRoot().includes(`.app${path.sep}Contents`)) env.PYTHONDONTWRITEBYTECODE = '1'
  }
  return env
}

module.exports = {
  IS_WIN, IS_MAC, HOME, LOCAL, exe,
  repoRoot, backendRoot, runtimeRoot, venvRoot, venvPython, basePython, dataRoot, migrateLegacyData, logsRoot,
  runtimeNodeBin, npmPrefix, npmPrefixBin, toolDirs, fixPath, findExecutable,
  ollamaAppDirs, ollamaExe, ollamaServerLog, nodeExe, npmCmd, openclawCmd, openclawEntry, openclawLog, dockerCli, cleanEnv,
}
