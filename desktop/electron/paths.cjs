// Where PockPock's pieces live, in development (repository checkout) and when installed.
const fs = require('node:fs')
const os = require('node:os')
const path = require('node:path')
const { app } = require('electron')

const LOCAL = process.env.LOCALAPPDATA || path.join(os.homedir(), 'AppData', 'Local')

function repoRoot() {
  return process.env.POCKPOCK_ROOT || path.resolve(__dirname, '..', '..')
}

/** The backend source: bundled next to the app when installed, the checkout's backend/ otherwise. */
function backendRoot() {
  if (app.isPackaged) return path.join(process.resourcesPath, 'backend')
  return path.join(repoRoot(), 'backend')
}

/** The installed app keeps its Python environment outside Program Files so it can be updated. */
function runtimeRoot() {
  return path.join(LOCAL, 'PockPock', 'runtime')
}

function venvRoot() {
  if (process.env.POCKPOCK_VENV) return process.env.POCKPOCK_VENV
  return app.isPackaged ? path.join(runtimeRoot(), 'venv') : path.join(repoRoot(), '.venv')
}

function venvPython() {
  return path.join(venvRoot(), process.platform === 'win32' ? 'Scripts\\python.exe' : 'bin/python')
}

/** Shared with the Python services (pockpock_paths.app_data_dir("FrogAI")). */
function dataRoot() {
  return path.join(LOCAL, 'FrogAI')
}

function logsRoot() {
  const folder = path.join(dataRoot(), 'logs')
  fs.mkdirSync(folder, { recursive: true })
  return folder
}

/** First match for an executable on PATH or in known install folders. */
function findExecutable(names, extra = []) {
  const dirs = (process.env.PATH || '').split(path.delimiter).filter(Boolean)
  for (const dir of [...extra, ...dirs]) {
    for (const name of names) {
      const candidate = path.join(dir, name)
      try { if (fs.statSync(candidate).isFile()) return candidate } catch {
        // App execution aliases (such as winget.exe in WindowsApps) cannot be stat'ed, only lstat'ed.
        try { fs.lstatSync(candidate); return candidate } catch { /* keep looking */ }
      }
    }
  }
  return null
}

function ollamaExe() {
  return findExecutable(['ollama.exe', 'ollama'], [path.join(LOCAL, 'Programs', 'Ollama')])
}

function openclawCmd() {
  return findExecutable(['openclaw.cmd', 'openclaw'], [path.join(process.env.APPDATA || '', 'npm')])
}

/** OpenClaw's JavaScript entry point, run with node directly: no shell quoting, no PowerShell
 * execution policy, and arguments (including JSON) arrive exactly as given. */
function openclawEntry() {
  const cmd = openclawCmd()
  const node = findExecutable(['node.exe', 'node'])
  if (!cmd || !node) return null
  for (const script of [path.join(path.dirname(cmd), 'node_modules', 'openclaw', 'openclaw.mjs'), path.join(path.dirname(cmd), '..', 'lib', 'node_modules', 'openclaw', 'openclaw.mjs')]) {
    if (fs.existsSync(script)) return { node, script }
  }
  return null
}

/** PATH without Git for Windows' Unix tools, which shadow Windows programs such as notepad. */
function cleanEnv(extra = {}) {
  const env = { ...process.env, ...extra }
  delete env.ELECTRON_RUN_AS_NODE
  const key = Object.keys(env).find((name) => name.toLowerCase() === 'path') || 'PATH'
  env[key] = (env[key] || '').split(path.delimiter).filter((dir) => !/\\Git\\(usr|mingw64)\\bin/i.test(dir)).join(path.delimiter)
  return env
}

module.exports = { LOCAL, repoRoot, backendRoot, runtimeRoot, venvRoot, venvPython, dataRoot, logsRoot, findExecutable, ollamaExe, openclawCmd, openclawEntry, cleanEnv }
