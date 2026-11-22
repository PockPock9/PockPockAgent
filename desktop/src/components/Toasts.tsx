// Toasts in the bottom-right corner: an update that is ready to install, and problems that block every
// task (the gateway stopped or failed, Ollama not running). Each says what to do next; Later or the
// close button hides it until its situation changes.
import { useState } from 'react'
import { AlertTriangle, Download, RefreshCw, ServerCog, X } from 'lucide-react'
import type { Status } from '../lib/status'
import type { Updates } from '../lib/updates'

type Toast = { key: string; tone: 'info' | 'error'; title: string; detail: string; actions: Array<{ label: string; primary?: boolean; run: () => void }> }

export function Toasts({ status, updates, onOpenServices }: { status: Status; updates: Updates; onOpenServices: () => void }) {
  const [hidden, setHidden] = useState<Set<string>>(new Set())
  const toasts: Toast[] = []
  const update = updates.state
  if (update?.status === 'ready') {
    toasts.push({ key: `update:${update.version}`, tone: 'info', title: `PockPock ${update.version} is ready`, detail: 'Restart to update. Your tasks and settings are kept.',
      actions: [{ label: 'Restart to update', primary: true, run: () => void updates.install() }] })
  }
  if (status.backend.phase === 'failed' || status.backend.phase === 'stopped') {
    toasts.push({ key: `gateway:${status.backend.phase}`, tone: 'error', title: status.backend.phase === 'failed' ? 'The PockPock gateway could not start' : 'The PockPock gateway is stopped', detail: `${status.backend.detail} Tasks cannot run until it is running.`,
      actions: [{ label: 'Open Services', primary: true, run: onOpenServices }] })
  } else if (status.backend.phase === 'ready' && status.state && !status.state.connected) {
    toasts.push({ key: 'ollama:off', tone: 'error', title: 'Ollama is not running', detail: 'Start it in Services, then try again. Chat and PockPock Agent need it; cloud models still work in Chat.',
      actions: [{ label: 'Open Services', primary: true, run: onOpenServices }] })
  }
  const shown = toasts.filter((toast) => !hidden.has(toast.key))
  if (!shown.length) return null
  const hide = (key: string) => setHidden((current) => new Set(current).add(key))
  return (
    <div className="toasts" aria-label="Notifications">
      {shown.map((toast) => (
        <div key={toast.key} className={`toast toast--${toast.tone}`} role={toast.tone === 'error' ? 'alert' : 'status'}>
          <span className="toast__icon" aria-hidden="true">{toast.tone === 'error' ? <AlertTriangle size={16} /> : <Download size={16} />}</span>
          <div className="toast__text"><strong>{toast.title}</strong><span>{toast.detail}</span>
            <div className="toast__actions">
              {toast.actions.map((action) => (
                <button key={action.label} type="button" className={`button button--small${action.primary ? ' button--primary' : ''}`} onClick={action.run}>
                  {action.label === 'Open Services' ? <ServerCog size={12} /> : action.label.startsWith('Restart') ? <RefreshCw size={12} /> : null}{action.label}
                </button>
              ))}
              {toast.tone === 'info' && <button type="button" className="button button--small" onClick={() => hide(toast.key)}>Later</button>}
            </div>
          </div>
          <button type="button" className="icon-button toast__close" aria-label={`Dismiss: ${toast.title}`} onClick={() => hide(toast.key)}><X size={14} /></button>
        </div>
      ))}
    </div>
  )
}
