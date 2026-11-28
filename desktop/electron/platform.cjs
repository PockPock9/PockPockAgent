// Operating-system specific process control. Windows: taskkill and netstat. macOS: process groups and lsof.
const { execFile, spawnSync } = require('node:child_process')
const paths = require('./paths.cjs')

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

module.exports = { run, sleep, pidsOnPort, killTree, killTreeSync, stopOllamaApp }
