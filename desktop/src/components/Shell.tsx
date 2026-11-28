// Window chrome: title bar (with the command palette search), the icon rail, the Workshop
// sub-navigation, and the status bar. The task list is in TaskPanel.tsx.
import { Activity, Blocks, Brain, Cable, Cloud, Download, Globe, Globe2, ListTodo, Menu, Plug, Puzzle, Search, Server, ServerCog, Settings as SettingsIcon, Wrench } from 'lucide-react'
import type { ReactNode } from 'react'
import type { Status } from '../lib/status'
import type { Updates } from '../lib/updates'
import { Dot } from './ui'
import { Mark } from './Mark'
import { mod } from '../lib/platform'

export type Page = 'chat' | 'skills' | 'mcp' | 'connectors' | 'models' | 'cloud' | 'memory' | 'research' | 'recipes' | 'activity' | 'maintenance' | 'services' | 'settings'

/** The rail's sections. Workshop holds every page except the conversation and Settings. */
export type Section = 'tasks' | 'workshop' | 'activity' | 'services' | 'settings'

export function sectionOf(page: Page | 'setup'): Section {
  if (page === 'chat') return 'tasks'
  if (page === 'settings' || page === 'setup') return 'settings'
  if (page === 'activity') return 'activity'
  if (page === 'services') return 'services'
  return 'workshop'
}

type WorkshopItem = { page: Page; label: string; icon: ReactNode }
/** The Workshop sub-navigation: every page id stays the same; only where it is listed changed. */
export const WORKSHOP_GROUPS: Array<{ label: string; items: WorkshopItem[] }> = [
  { label: 'Capabilities', items: [
    { page: 'skills', label: 'Skills', icon: <Puzzle size={15} /> },
    { page: 'mcp', label: 'MCP servers', icon: <Plug size={15} /> },
    { page: 'connectors', label: 'Connectors', icon: <Cable size={15} /> },
    { page: 'recipes', label: 'Browser recipes', icon: <Globe size={15} /> },
    { page: 'research', label: 'Research', icon: <Globe2 size={15} /> },
  ] },
  { label: 'Models', items: [
    { page: 'models', label: 'Local models', icon: <Server size={15} /> },
    { page: 'cloud', label: 'Cloud models', icon: <Cloud size={15} /> },
  ] },
  { label: 'Knowledge', items: [
    { page: 'memory', label: 'Memory', icon: <Brain size={15} /> },
  ] },
  { label: 'System', items: [
    { page: 'services', label: 'Services', icon: <ServerCog size={15} /> },
    { page: 'maintenance', label: 'Maintenance', icon: <Wrench size={15} /> },
    { page: 'activity', label: 'Activity', icon: <Activity size={15} /> },
  ] },
]

export const PAGE_LABEL: Record<Page, string> = {
  chat: 'Tasks', settings: 'Settings',
  ...Object.fromEntries(WORKSHOP_GROUPS.flatMap((group) => group.items.map((item) => [item.page, item.label]))),
} as Record<Page, string>

export function TitleBar({ onPalette, onMenu, showMenu }: { onPalette: () => void; onMenu: () => void; showMenu: boolean }) {
  return (
    <header className="titlebar">
      <div className="titlebar__left">
        {showMenu && <button type="button" className="icon-button" aria-label="Open tasks and Workshop" title="Open tasks and Workshop" onClick={onMenu}><Menu size={16} /></button>}
        <span className="brand"><Mark size={20} className="brand__mark" /><b>PockPock</b> Agent Studio</span>
      </div>
      <button type="button" className="titlebar__search" onClick={onPalette} aria-label={`Search tasks, pages and settings (${mod}K)`}>
        <Search size={13} /><span>Search tasks, pages and settings</span><kbd>{mod}K</kbd>
      </button>
      <div className="titlebar__right" />
    </header>
  )
}

export function Rail({ section, needsYou, servicesTone, onSection }: {
  section: Section
  needsYou: boolean
  servicesTone: 'ok' | 'warn' | 'off'
  onSection: (section: Section) => void
}) {
  const item = (id: Section, label: string, icon: ReactNode, badge?: ReactNode) => (
    <button type="button" className={`rail__item${section === id ? ' is-active' : ''}`} aria-current={section === id ? 'page' : undefined}
      aria-label={label} title={label} onClick={() => onSection(id)}>
      {icon}{badge}
    </button>
  )
  return (
    <nav className="rail" aria-label="Sections">
      {item('tasks', needsYou ? 'Tasks: one needs you' : 'Tasks', <ListTodo size={18} />, needsYou ? <span className="rail__badge" aria-hidden="true" /> : undefined)}
      {item('workshop', 'Workshop', <Blocks size={18} />)}
      {item('activity', 'Activity', <Activity size={18} />)}
      <span className="rail__spacer" />
      {item('services', servicesTone === 'warn' ? 'Services: not all running' : 'Services', <ServerCog size={18} />, servicesTone === 'warn' ? <span className="rail__badge rail__badge--warn" aria-hidden="true" /> : undefined)}
      {item('settings', 'Settings', <SettingsIcon size={18} />)}
    </nav>
  )
}

export function WorkshopNav({ page, status, overlay, onPage }: { page: Page; status: Status; overlay?: boolean; onPage: (page: Page) => void }) {
  const enabledModels = status.state?.models.filter((model) => model.enabled && !model.embedding).length
  const servicesUp = status.services.filter((service) => service.status === 'running').length
  const installed = status.services.filter((service) => service.available).length
  const counts: Partial<Record<Page, { value: string | number; tone?: 'warn' }>> = {
    ...(status.counts?.skills !== undefined ? { skills: { value: status.counts.skills } } : {}),
    ...(status.counts?.mcp !== undefined ? { mcp: { value: status.counts.mcp } } : {}),
    ...(enabledModels !== undefined ? { models: { value: enabledModels } } : {}),
    ...(status.state?.cloud_models?.length ? { cloud: { value: status.state.cloud_models.length } } : {}),
    ...(installed ? { services: { value: `${servicesUp}/${installed}`, tone: servicesUp < installed ? 'warn' as const : undefined } } : {}),
  }
  return (
    <aside className={`panel${overlay ? ' is-overlay' : ''}`} aria-label="Workshop">
      <div className="panel__head"><h2>Workshop</h2></div>
      <nav className="workshop-nav" aria-label="Workshop pages">
        {WORKSHOP_GROUPS.map((group) => (
          <div key={group.label} className="workshop-nav__group">
            <div className="section-label">{group.label}</div>
            {group.items.map((item) => (
              <button type="button" key={item.page} className={`nav-item${page === item.page ? ' is-active' : ''}`} aria-current={page === item.page ? 'page' : undefined} onClick={() => onPage(item.page)}>
                {item.icon}<span>{item.label}</span>
                {counts[item.page] && <small className={counts[item.page]?.tone ? `nav-item__count--${counts[item.page]?.tone}` : ''}>{counts[item.page]?.value}</small>}
              </button>
            ))}
          </div>
        ))}
      </nav>
    </aside>
  )
}

export function StatusBar({ status, version, onOpenServices, updates, onOpenSettings }: { status: Status; version: string; onOpenServices: () => void; updates: Updates; onOpenSettings: () => void }) {
  const update = updates.state
  const backendTone = status.backend.phase === 'ready' ? 'ok' : status.backend.phase === 'checking' || status.backend.phase === 'starting' ? 'busy' : 'off'
  const running = status.state?.models.filter((model) => model.running && !model.embedding).map((model) => model.name) ?? []
  return (
    <footer className="statusbar">
      <button type="button" className="statusbar__services" onClick={onOpenServices} title="Open Services">
        <span title={status.backend.detail}><Dot tone={backendTone} /> {status.backend.phase === 'ready' ? 'Gateway ready' : status.backend.detail}</span>
        <span title={status.state?.error || ''}><Dot tone={status.state?.connected ? 'ok' : 'off'} /> Ollama{status.state?.connected ? ` · ${running.length ? `${running.length} ${running.length === 1 ? 'model' : 'models'} loaded` : 'no model loaded'}` : ' · not running'}</span>
        <span><Dot tone={status.state?.router_enabled ? 'ok' : 'warn'} /> Smart router {status.state?.router_enabled === false ? 'paused' : 'on'}</span>
        <span title={status.claw?.detail}><Dot tone={status.claw?.ready ? 'ok' : 'off'} /> OpenClaw</span>
      </button>
      <span className="statusbar__spacer" />
      {running.length > 0 && <span className="statusbar__models" title="Models loaded in memory">{running.join(', ')}</span>}
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
