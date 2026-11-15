// Integrated terminal sessions backed by a pseudo-terminal, streamed to the renderer over IPC.
const fs = require('node:fs')
const path = require('node:path')

let pty = null
try {
  pty = require('@lydell/node-pty')
} catch {
  pty = null
}

function shell() {
  if (process.platform !== 'win32') return { file: process.env.SHELL || '/bin/bash', args: [] }
  const pwsh = path.join(process.env.ProgramFiles || 'C:\\Program Files', 'PowerShell', '7', 'pwsh.exe')
  return fs.existsSync(pwsh) ? { file: pwsh, args: ['-NoLogo'] } : { file: 'powershell.exe', args: ['-NoLogo'] }
}

class Terminals {
  constructor(send) {
    this.send = send
    this.sessions = new Map()
    this.next = 1
  }

  available() {
    return Boolean(pty)
  }

  create({ cwd, cols, rows }) {
    if (!pty) throw new Error('The terminal component could not be loaded.')
    const { file, args } = shell()
    const env = { ...process.env }
    delete env.ELECTRON_RUN_AS_NODE
    const id = this.next++
    const term = pty.spawn(file, args, {
      name: 'xterm-256color',
      cols: Math.max(20, Math.min(cols || 100, 500)),
      rows: Math.max(5, Math.min(rows || 24, 200)),
      cwd: cwd && fs.existsSync(cwd) ? cwd : process.env.USERPROFILE || process.cwd(),
      env,
      useConpty: true,
    })
    term.onData((data) => this.send('terminal:data', id, data))
    term.onExit(({ exitCode }) => {
      this.sessions.delete(id)
      this.send('terminal:exit', id, exitCode)
    })
    this.sessions.set(id, term)
    return { id, shell: path.basename(file) }
  }

  write(id, data) {
    const term = this.sessions.get(id)
    if (term && typeof data === 'string' && data.length < 100_000) term.write(data)
  }

  resize(id, cols, rows) {
    const term = this.sessions.get(id)
    if (term && Number.isInteger(cols) && Number.isInteger(rows) && cols > 0 && rows > 0) term.resize(Math.min(cols, 500), Math.min(rows, 200))
  }

  kill(id) {
    const term = this.sessions.get(id)
    if (term) { term.kill(); this.sessions.delete(id) }
  }

  killAll() {
    for (const id of [...this.sessions.keys()]) this.kill(id)
  }
}

module.exports = { Terminals }
