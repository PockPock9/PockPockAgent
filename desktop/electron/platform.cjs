// Operating-system specific process control and the shell NemoClaw runs in. Windows: taskkill,
// netstat, and NemoClaw inside WSL. macOS: process groups, lsof, and NemoClaw in a login shell.
const fs = require('node:fs')
const os = require('node:os')
const path = require('node:path')
const { execFile, spawn, spawnSync } = require('node:child_process')
const paths = require('./paths.cjs')

const NEMO_PATH_PREFIX = 'export PATH="$HOME/.local/bin:$PATH"; '

function run(file, args, options = {}) {
  return new Promise((resolve) => {
    execFile(file, args, { windowsHide: true, timeout: options.timeout ?? 120000, maxBuffer: 4 * 1024 * 1024, env: options.env ?? paths.cleanEnv(), cwd: options.cwd, shell: options.shell }, (error, stdout, stderr) => {
      resolve({ ok: !error, code: error?.code ?? 0, stdout: String(stdout || ''), stderr: String(stderr || '') })
    })
  })
}

const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms))

/** Process IDs listening on a local TCP port. */
async function pidsOnPort(port) {
  const pids = new Set()
  if (paths.IS_WIN) {
    const result = await run('netstat.exe', ['-ano', '-p', 'tcp'], { timeout: 10000 })
    for (const line of result.stdout.split(/\r?\n/)) {
      const parts = line.trim().split(/\s+/)
      if (parts[0] === 'TCP' && parts[3] === 'LISTENING' && parts[1].endsWith(`:${port}`)) pids.add(Number(parts[4]))
    }
  } else {
    const result = await run('/usr/sbin/lsof', ['-nP', `-iTCP:${port}`, '-sTCP:LISTEN', '-t'], { timeout: 10000 })
    for (const line of result.stdout.split(/\n/)) if (/^\d+$/.test(line.trim())) pids.add(Number(line.trim()))
  }
  return [...pids].filter((pid) => pid > 0 && pid !== process.pid)
}

function alive(pid) {
  try { process.kill(pid, 0); return true } catch { return false }
}

/** Ends a process and its children. Services are spawned detached, so on macOS each leads its own
 * process group and the whole group is signalled. */
async function killTree(pid) {
  if (paths.IS_WIN) return run('taskkill.exe', ['/PID', String(pid), '/T', '/F'], { timeout: 20000 })
  const signal = (sig) => { try { process.kill(-pid, sig) } catch { try { process.kill(pid, sig) } catch { /* gone */ } } }
  signal('SIGTERM')
  for (let waited = 0; waited < 5000 && alive(pid); waited += 250) await sleep(250)
  if (alive(pid)) signal('SIGKILL')
  return { ok: true }
}

function killTreeSync(pid) {
  if (paths.IS_WIN) { spawnSync('taskkill.exe', ['/PID', String(pid), '/T', '/F'], { windowsHide: true }); return }
  try { process.kill(-pid, 'SIGTERM') } catch { try { process.kill(pid, 'SIGTERM') } catch { /* gone */ } }
}

/** Ollama's desktop app restarts its server, so stopping Ollama closes the app too. */
async function stopOllamaApp() {
  if (paths.IS_WIN) {
    await run('taskkill.exe', ['/IM', 'ollama app.exe', '/T', '/F'], { timeout: 15000 })
    await run('taskkill.exe', ['/IM', 'ollama.exe', '/T', '/F'], { timeout: 15000 })
  } else if (paths.IS_MAC) {
    await run('/usr/bin/osascript', ['-e', 'if application "Ollama" is running then tell application "Ollama" to quit'], { timeout: 15000 })
  }
}

// ---------- NemoClaw host ----------

/** Whether this computer can run NemoClaw at all (before anything is installed). */
function nemoSupported() {
  if (paths.IS_WIN) return { supported: true, reason: '' }
  if (paths.IS_MAC) return os.arch() === 'arm64' ? { supported: true, reason: '' } : { supported: false, reason: 'NemoClaw needs a Mac with Apple silicon.' }
  return { supported: false, reason: 'NemoClaw is set up by PockPock only on Windows and macOS.' }
}

/** Whether the shell NemoClaw runs in exists (WSL on Windows, bash on macOS). */
function nemoHostReady() {
  if (paths.IS_WIN) return Boolean(paths.findExecutable(['wsl.exe']))
  return paths.IS_MAC && os.arch() === 'arm64' && fs.existsSync('/bin/bash')
}

/** Runs a bash script where NemoClaw lives: inside WSL on Windows, a login shell on macOS. */
function nemoShell(script, timeout = 180000) {
  if (paths.IS_WIN) return run('wsl.exe', ['-e', 'bash', '-lc', NEMO_PATH_PREFIX + script], { timeout })
  return run('/bin/bash', ['-lc', NEMO_PATH_PREFIX + script], { timeout })
}

/** Spawn arguments for a long NemoClaw command whose output setup streams to its log. */
function nemoSpawn(script, distro) {
  if (paths.IS_WIN) return { file: 'wsl.exe', args: [...(distro ? ['-d', distro] : []), '-e', 'bash', '-lc', NEMO_PATH_PREFIX + script] }
  return { file: '/bin/bash', args: ['-lc', NEMO_PATH_PREFIX + script] }
}

// ---------- Docker ----------

async function dockerReady() {
  const docker = paths.dockerCli()
  if (!docker) return false
  return (await run(docker, ['info', '--format', '{{.ServerVersion}}'], { timeout: 15000 })).ok
}

function dockerDesktopApp() {
  if (paths.IS_WIN) {
    const file = path.join(process.env.ProgramFiles || 'C:\\Program Files', 'Docker', 'Docker', 'Docker Desktop.exe')
    return fs.existsSync(file) ? file : null
  }
  return ['/Applications/Docker.app', path.join(paths.HOME, 'Applications', 'Docker.app')].find((dir) => fs.existsSync(dir)) || null
}

/** Starts Docker (Docker Desktop, or Colima on a Mac that uses it) and waits up to 3 minutes. */
async function ensureDocker() {
  if (await dockerReady()) return
  const desktop = dockerDesktopApp()
  const colima = paths.IS_MAC ? paths.findExecutable(['colima']) : null
  if (desktop) {
    if (paths.IS_WIN) spawn(desktop, [], { detached: true, stdio: 'ignore', windowsHide: true }).unref()
    else await run('/usr/bin/open', ['-g', '-a', desktop], { timeout: 30000 })
  } else if (colima) {
    await run(colima, ['start', '--cpu', '4', '--memory', '8'], { timeout: 300000 })
  } else {
    throw new Error('Docker Desktop is not installed. NemoClaw needs it.')
  }
  for (let attempt = 0; attempt < 60; attempt += 1) {
    await sleep(3000)
    if (await dockerReady()) return
  }
  throw new Error('Docker did not start within 3 minutes. Open Docker Desktop, finish any prompt it shows, then try again.')
}

module.exports = { run, sleep, pidsOnPort, killTree, killTreeSync, stopOllamaApp, nemoSupported, nemoHostReady, nemoShell, nemoSpawn, dockerReady, dockerDesktopApp, ensureDocker }
