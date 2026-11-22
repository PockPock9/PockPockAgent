// Toasts in the bottom-right corner: an update that is ready to install, and problems that block every
// task (the gateway stopped or failed, Ollama not running), and watched pages that changed (UI-01E). Each
// says what to do next; Later or the close button hides it until its situation changes.
import { useState } from 'react'
import { AlertTriangle, Download, Eye, RefreshCw, ServerCog, X } from 'lucide-react'
import type { Status } from '../lib/status'
import type { Updates } from '../lib/updates'
import { useWatchedSources } from '../lib/watch'

type Toast = { key: string; tone: 'info' | 'error'; icon?: 'watch'; title: string; detail: string; actions: Array<{ label: string; primary?: boolean; run: () => void }> }

export function Toasts({ status, updates, onOpenServices, onOpenResearch }: { status: Status; updates: Updates; onOpenServices: () => void; onOpenResearch: () => void }) {
  const [hidden, setHidden] = useState<Set<string>>(new Set())
  const watched = useWatchedSources(60_000, status.backend.phase === 'ready')
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
  const changed = watched.data?.sources.filter((item) => item.watch.unseen) ?? []
  if (changed.length) {
    // The key names every changed page and when, so a new change shows the toast again after Later.
    toasts.push({ key: `watch:${changed.map((item) => `${item.source_id}@${item.watch.changed_at}`).join(',')}`, tone: 'info', icon: 'watch',
      title: changed.length === 1 ? 'A watched page changed' : `${changed.length} watched pages changed`,
      detail: changed.length === 1 ? `${changed[0].title || changed[0].url}. The new version is saved with its task.` : changed.slice(0, 3).map((item) => item.title || item.url).join(', ') + (changed.length > 3 ? ', …' : ''),
      actions: [{ label: 'Open Research', primary: true, run: onOpenResearch }] })
  }
  const shown = toasts.filter((toast) => !hidden.has(toast.key))
  if (!shown.length) return null
  const hide = (key: string) => setHidden((current) => new Set(current).add(key))
  return (
    <div className="toasts" aria-label="Notifications">
      {shown.map((toast) => (
        <div key={toast.key} className={`toast toast--${toast.tone}`} role={toast.tone === 'error' ? 'alert' : 'status'}>
          <span className="toast__icon" aria-hidden="true">{toast.tone === 'error' ? <AlertTriangle size={16} /> : toast.icon === 'watch' ? <Eye size={16} /> : <Download size={16} />}</span>
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
