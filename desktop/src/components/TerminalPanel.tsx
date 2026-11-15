// Integrated terminal (PowerShell) in the open folder, rendered with xterm.js.
import { useEffect, useRef, useState } from 'react'
import { Terminal as XTerm } from '@xterm/xterm'
import { FitAddon } from '@xterm/addon-fit'
import '@xterm/xterm/css/xterm.css'
import { RotateCcw, X } from 'lucide-react'
import { bridge } from '../lib/types'
import { IconButton } from './ui'
import { mod } from '../lib/platform'
import { terminalTheme, THEME_EVENT } from '../lib/theme'

export function TerminalPanel({ workspace, onClose }: { workspace?: string; onClose: () => void }) {
  const hostRef = useRef<HTMLDivElement>(null)
  const [generation, setGeneration] = useState(0)
  const [label, setLabel] = useState('Terminal')
  const [error, setError] = useState('')
  const desktop = bridge()

  useEffect(() => {
    if (!desktop || !hostRef.current) return
    const term = new XTerm({
      fontFamily: '"Cascadia Code", "Cascadia Mono", Consolas, monospace',
      fontSize: 13,
      cursorBlink: true,
      allowProposedApi: false,
      theme: terminalTheme(),
    })
    const onTheme = () => { term.options.theme = terminalTheme() }
    window.addEventListener(THEME_EVENT, onTheme)
    const fit = new FitAddon()
    term.loadAddon(fit)
    term.open(hostRef.current)
    fit.fit()
    let id = 0
    let disposed = false
    const offData = desktop.terminal.onData((terminalId, data) => { if (terminalId === id) term.write(data) })
    const offExit = desktop.terminal.onExit((terminalId, code) => { if (terminalId === id) term.write(`\r\n\x1b[90m[process exited with code ${code}]\x1b[0m\r\n`) })
    desktop.terminal.create({ cols: term.cols, rows: term.rows }).then((created) => {
      if (disposed) { void desktop.terminal.kill(created.id); return }
      id = created.id
      setLabel(created.shell.replace(/\.exe$/i, ''))
      setError('')
    }, (reason: unknown) => setError(reason instanceof Error ? reason.message : 'The terminal could not start.'))
    const input = term.onData((data) => { if (id) void desktop.terminal.write(id, data) })
    const observer = new ResizeObserver(() => {
      try { fit.fit() } catch { return }
      if (id) void desktop.terminal.resize(id, term.cols, term.rows)
    })
    observer.observe(hostRef.current)
    term.focus()
    return () => {
      disposed = true
      window.removeEventListener(THEME_EVENT, onTheme)
      observer.disconnect()
      input.dispose()
      offData()
      offExit()
      if (id) void desktop.terminal.kill(id)
      term.dispose()
    }
  }, [desktop, generation, workspace])

  return (
    <section className="terminal" aria-label="Terminal">
      <div className="panel-head">
        <span className="panel-head__title">Terminal <small>{label}</small></span>
        <span className="panel-head__actions">
          <IconButton label="Restart terminal" onClick={() => setGeneration((value) => value + 1)}><RotateCcw size={13} /></IconButton>
          <IconButton label={`Close panel (${mod}J)`} onClick={onClose}><X size={14} /></IconButton>
        </span>
      </div>
      {!desktop ? <p className="terminal__note">The terminal is available in the desktop app.</p>
        : error ? <p className="terminal__note terminal__note--error">{error}</p> : null}
      <div ref={hostRef} className="terminal__host" />
    </section>
  )
}
