// Window chrome: title bar, sidebar (chats and customizations), and status bar.
import { useMemo, useState } from 'react'
import { Activity, Brain, Download, Folder, Globe, Globe2, MessageSquarePlus, PanelBottom, PanelLeft, PanelRight, Plug, Puzzle, Search, Server, ServerCog, Settings as SettingsIcon, Trash2 } from 'lucide-react'
import { relativeTime } from '../lib/api'
import type { Status } from '../lib/status'
import type { Session, Settings } from '../lib/types'
import type { Updates } from '../lib/updates'
import { Dot, IconButton } from './ui'
import { mod } from '../lib/platform'

export type Page = 'chat' | 'skills' | 'mcp' | 'models' | 'memory' | 'research' | 'recipes' | 'activity' | 'services' | 'settings'

export function TitleBar({ settings, onToggle, onChooseFolder }: {
  settings: Settings
  onToggle: (panel: 'sidebar' | 'files' | 'terminal') => void
  onChooseFolder: () => void
}) {
  const folder = settings.workspace?.split(/[\\/]/).filter(Boolean).at(-1)
  return (
    <header className="titlebar">
      <div className="titlebar__left">
        <IconButton label={`Toggle sidebar (${mod}B)`} active={settings.sidebar !== false} onClick={() => onToggle('sidebar')}><PanelLeft size={16} /></IconButton>
        <span className="brand"><span className="brand__mark">P</span>PockPock <b>Agent</b></span>
      </div>
      <button type="button" className="titlebar__folder" onClick={onChooseFolder} title={settings.workspace || 'Open a folder'}>
        <Folder size={13} /><span>{folder || 'Open a folder'}</span>
      </button>
      <div className="titlebar__right">
        <IconButton label={`Toggle terminal (${mod}J)`} active={Boolean(settings.terminal)} onClick={() => onToggle('terminal')}><PanelBottom size={16} /></IconButton>
        <IconButton label={`Toggle files (${mod}Shift+E)`} active={settings.files !== false} onClick={() => onToggle('files')}><PanelRight size={16} /></IconButton>
      </div>
    </header>
  )
}

function groupOf(timestamp: number) {
  const age = Date.now() - timestamp
  if (age < 86_400_000 && new Date(timestamp).getDate() === new Date().getDate()) return 'Today'
  if (age < 7 * 86_400_000) return 'This week'
  return 'Older'
}

export function Sidebar({ overlay, sessions, activeId, page, running, status, onSelect, onNew, onDelete, onPage }: {
  overlay?: boolean
  sessions: Session[]
  activeId: string
  page: Page
  running: { sessionId: string } | null
  status: Status
  onSelect: (id: string) => void
  onNew: () => void
  onDelete: (id: string) => void
  onPage: (page: Page) => void
}) {
  const [query, setQuery] = useState('')
  const groups = useMemo(() => {
    const needle = query.trim().toLowerCase()
    const sorted = [...sessions]
      .filter((session) => !needle || session.title.toLowerCase().includes(needle) || session.messages.some((message) => message.content.toLowerCase().includes(needle)))
      .sort((a, b) => b.updatedAt - a.updatedAt)
    const result: Array<[string, Session[]]> = []
    for (const session of sorted) {
      const label = groupOf(session.updatedAt)
      const group = result.find(([name]) => name === label)
      if (group) group[1].push(session)
      else result.push([label, [session]])
    }
    return result
  }, [sessions, query])
  const enabledModels = status.state?.models.filter((model) => model.enabled).length
  const servicesUp = status.services.filter((service) => service.status === 'running').length
  const installed = status.services.filter((service) => service.available).length
  const nav: Array<{ page: Page; icon: React.ReactNode; label: string; count?: number | string; tone?: string }> = [
    { page: 'recipes', icon: <Globe size={15} />, label: 'Browser recipes' },
    { page: 'activity', icon: <Activity size={15} />, label: 'Activity' },
    { page: 'skills', icon: <Puzzle size={15} />, label: 'Skills', count: status.counts?.skills },
    { page: 'mcp', icon: <Plug size={15} />, label: 'MCP servers', count: status.counts?.mcp },
    { page: 'models', icon: <Server size={15} />, label: 'Models', count: enabledModels },
    { page: 'memory', icon: <Brain size={15} />, label: 'Memory' },
    { page: 'research', icon: <Globe2 size={15} />, label: 'Research' },
    { page: 'services', icon: <ServerCog size={15} />, label: 'Services', count: installed ? `${servicesUp}/${installed}` : undefined, tone: installed && servicesUp < installed ? 'warn' : undefined },
    { page: 'settings', icon: <SettingsIcon size={15} />, label: 'Settings' },
  ]
  return (
    <aside className={`sidebar${overlay ? ' is-overlay' : ''}`} aria-label="Chats and settings">
      <div className="sidebar__top">
        <button type="button" className="new-chat" onClick={onNew}><MessageSquarePlus size={15} /> New chat <kbd>{mod}N</kbd></button>
        <label className="search">
          <Search size={13} />
          <input type="search" placeholder="Search chats" value={query} onChange={(event) => setQuery(event.target.value)} aria-label="Search chats" />
        </label>
      </div>
      <nav className="sessions" aria-label="Chats">
        {!sessions.length && <p className="sessions__empty">No chats yet. Start one with New chat.</p>}
        {sessions.length > 0 && !groups.length && <p className="sessions__empty">No chats match “{query}”.</p>}
        {groups.map(([label, items]) => (
          <div key={label} className="sessions__group">
            <div className="section-label">{label}</div>
            {items.map((session) => (
              <div key={session.id} className={`session${page === 'chat' && session.id === activeId ? ' is-active' : ''}`}>
                <button type="button" className="session__open" onClick={() => onSelect(session.id)} aria-current={page === 'chat' && session.id === activeId ? 'page' : undefined}>
                  {running?.sessionId === session.id ? <Dot tone="busy" /> : <span className="session__bullet" aria-hidden="true" />}
                  <span className="session__title">{session.title}</span>
                  <small>{relativeTime(session.updatedAt)}</small>
                </button>
                <button type="button" className="session__delete" onClick={() => onDelete(session.id)} aria-label={`Delete chat ${session.title}`} title="Delete chat" disabled={running?.sessionId === session.id}><Trash2 size={13} /></button>
              </div>
            ))}
          </div>
        ))}
      </nav>
      <nav className="customize" aria-label="Customize">
        <div className="section-label">Customize</div>
        {nav.map((item) => (
          <button type="button" key={item.page} className={`nav-item${page === item.page ? ' is-active' : ''}`} aria-current={page === item.page ? 'page' : undefined} onClick={() => onPage(item.page)}>
            {item.icon}<span>{item.label}</span>{item.count !== undefined && <small className={item.tone ? `nav-item__count--${item.tone}` : ''}>{item.count}</small>}
          </button>
        ))}
      </nav>
    </aside>
  )
}

export function StatusBar({ status, version, onOpenServices, updates, onOpenSettings }: { status: Status; version: string; onOpenServices: () => void; updates: Updates; onOpenSettings: () => void }) {
  const update = updates.state
  const backendTone = status.backend.phase === 'ready' ? 'ok' : status.backend.phase === 'checking' || status.backend.phase === 'starting' ? 'busy' : 'off'
  const running = status.state?.models.filter((model) => model.running).map((model) => model.name) ?? []
  return (
    <footer className="statusbar">
      <button type="button" className="statusbar__services" onClick={onOpenServices} title="Open Services">
      <span title={status.backend.detail}><Dot tone={backendTone} /> {status.backend.phase === 'ready' ? 'Backend ready' : status.backend.detail}</span>
      <span title={status.state?.error || ''}><Dot tone={status.state?.connected ? 'ok' : 'off'} /> Ollama</span>
      <span><Dot tone={status.state?.router_enabled ? 'ok' : 'warn'} /> Router {status.state?.router_enabled === false ? 'paused' : ''}</span>
      <span title={status.claw?.detail}><Dot tone={status.claw?.ready ? 'ok' : 'off'} /> OpenClaw</span>
      <span title={status.nemo?.detail}><Dot tone={status.nemoChecking ? 'busy' : status.nemo?.ready ? 'ok' : status.nemo?.checked === false ? 'warn' : 'off'} /> NemoClaw{status.nemo?.checked === false ? ' · not checked' : ''}</span>
      </button>
      <span className="statusbar__spacer" />
      <span title="Models loaded in memory">{running.length ? `Loaded: ${running.join(', ')}` : 'No model loaded'}</span>
      {update?.status === 'ready' && (
        <button type="button" className="statusbar__update" onClick={() => void updates.install()} title={`Restart PockPock to install version ${update.version}`}>
          <Download size={12} /> Restart to update to {update.version}
        </button>
      )}
      {update?.status === 'available' && (
        <button type="button" className="statusbar__update" onClick={onOpenSettings} title="Open Settings to update">
          <Download size={12} /> Version {update.version} available
        </button>
      )}
      {update?.status === 'downloading' && <span title="Downloading the new version in the background">Downloading update · {Math.round(update.progress * 100)}%</span>}
      <span>v{version}</span>
    </footer>
  )
}
