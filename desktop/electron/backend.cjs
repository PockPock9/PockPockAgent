// Checks the PockPock backend and starts it when it is not running. A backend this app started
// is stopped when the app quits; one that was already running is left alone.
const { spawn, spawnSync } = require('node:child_process')
const fs = require('node:fs')
const http = require('node:http')
const path = require('node:path')

function ping(backendUrl, timeoutMs = 2500) {
  return new Promise((resolve) => {
    const request = http.get(new URL('/api/state', backendUrl), { timeout: timeoutMs }, (response) => {
      response.resume()
      resolve(response.statusCode === 200)
    })
    request.on('timeout', () => { request.destroy(); resolve(false) })
    request.on('error', () => resolve(false))
  })
}

class Backend {
  constructor({ backendUrl, repoRoot, onStatus }) {
    this.backendUrl = backendUrl
    this.repoRoot = repoRoot
    this.onStatus = onStatus
    this.child = null
    this.state = { phase: 'checking', detail: 'Checking the PockPock backend…', startedByApp: false }
  }

  set(phase, detail) {
    this.state = { phase, detail, startedByApp: Boolean(this.child) }
    this.onStatus(this.state)
  }

  python() {
    const venv = path.join(this.repoRoot, '.venv', process.platform === 'win32' ? 'Scripts\\python.exe' : 'bin/python')
    return fs.existsSync(venv) ? venv : null
  }

  async ensure() {
    this.set('checking', 'Checking the PockPock backend…')
    if (await ping(this.backendUrl)) { this.set('ready', 'Connected'); return true }
    const python = this.python()
    const script = path.join(this.repoRoot, 'backend', 'scripts', 'pockpock.py')
    if (!python || !fs.existsSync(script)) {
      this.set('missing', `PockPock was not found next to this app (${this.repoRoot}). Start the backend yourself.`)
      return false
    }
    this.set('starting', 'Starting the PockPock backend…')
    const env = { ...process.env, PYTHONUNBUFFERED: '1' }
    delete env.ELECTRON_RUN_AS_NODE
    this.child = spawn(python, [script, 'start'], { cwd: this.repoRoot, env, windowsHide: true, stdio: 'ignore' })
    this.child.on('exit', () => { this.child = null })
    for (let attempt = 0; attempt < 90; attempt += 1) {
      await new Promise((resolve) => setTimeout(resolve, 1000))
      if (await ping(this.backendUrl)) { this.set('ready', 'Started by PockPock Agent'); return true }
      if (!this.child) break
    }
    this.set('failed', 'The backend did not start. Run backend\\scripts\\pockpock.py start in a terminal to see why.')
    return false
  }

  stop() {
    if (!this.child) return
    const pid = this.child.pid
    if (process.platform === 'win32') spawnSync('taskkill', ['/PID', String(pid), '/T', '/F'], { windowsHide: true })
    else this.child.kill('SIGTERM')
    this.child = null
  }
}

module.exports = { Backend, ping }
