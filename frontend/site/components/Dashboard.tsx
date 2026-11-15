'use client'

import { useEffect, useRef, useState, type FormEvent, type KeyboardEvent } from 'react'
import { Activity, AlertCircle, Bell, Bot, Check, ChevronDown, ChevronLeft, ChevronRight, CircleHelp, Clock3, Command, CreditCard, Ellipsis, FileClock, LayoutDashboard, Menu, Plus, Search, Settings2, SlidersHorizontal, Sparkles, Workflow, X } from 'lucide-react'
import { Area, AreaChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import { activity, kpis, trendData, workflows } from '@/data/mock-data'
import { CosmicBackground } from './CosmicBackground'
import { CosmicMotionToggle } from './CosmicMotionToggle'

const navItems = [
  { label: 'Overview', icon: LayoutDashboard }, { label: 'Workflows', icon: Workflow },
  { label: 'Activity', icon: Activity }, { label: 'Integrations', icon: Command },
]
const bottomItems = [
  { label: 'Usage & billing', icon: CreditCard }, { label: 'Settings', icon: Settings2 }, { label: 'Help center', icon: CircleHelp },
]

function Sidebar({ collapsed, setCollapsed, active, setActive, mobileOpen, setMobileOpen, onCreate }: { collapsed: boolean; setCollapsed: (v: boolean) => void; active: string; setActive: (v: string) => void; mobileOpen: boolean; setMobileOpen: (v: boolean) => void; onCreate: () => void }) {
  return <><button className={`dash-scrim${mobileOpen ? ' visible' : ''}`} onClick={() => setMobileOpen(false)} aria-label="Close dashboard navigation" /><aside className={`dash-sidebar${collapsed ? ' collapsed' : ''}${mobileOpen ? ' mobile-open' : ''}`}>
    <div className="workspace-switch"><span className="workspace-icon"><Sparkles size={16} /></span>{!collapsed && <><span><b>Northstar Studio</b><small>Workspace</small></span><ChevronDown size={13} className="workspace-chevron" /></>}</div>
    <div className="dash-nav-label">WORKSPACE</div>
    <nav className="dash-nav" aria-label="Dashboard navigation">{navItems.map(({ label, icon: Icon }) => <button className={active === label ? 'active' : ''} key={label} onClick={() => { setActive(label); setMobileOpen(false) }} title={collapsed ? label : undefined}><Icon size={17} />{!collapsed && <span>{label}</span>}{!collapsed && label === 'Activity' && <i className="nav-count">4</i>}</button>)}</nav>
    {!collapsed && <><div className="dash-nav-label automations-label">AUTOMATIONS <button aria-label="Add workflow" onClick={onCreate}><Plus size={14} /></button></div><button className="quick-workflow" onClick={onCreate}><span className="quick-workflow-icon"><Plus size={15} /></span><span>Create workflow</span></button></>}
    <div className="sidebar-spacer" />
    <nav className="dash-nav dash-nav-bottom" aria-label="Account navigation">{bottomItems.map(({ label, icon: Icon }) => <button key={label} onClick={() => setActive(label)} className={active === label ? 'active' : ''} title={collapsed ? label : undefined}><Icon size={16} />{!collapsed && <span>{label}</span>}</button>)}</nav>
    <div className="user-chip"><span className="user-avatar">AC</span>{!collapsed && <><span><b>Alex Carter</b><small>Admin</small></span><Ellipsis size={16} className="user-more" /></>}</div>
    <button className="collapse-side" onClick={() => setCollapsed(!collapsed)} aria-label={collapsed ? 'Expand sidebar' : 'Collapse sidebar'}>{collapsed ? <ChevronRight size={15} /> : <ChevronLeft size={15} />} {!collapsed && 'Collapse sidebar'}</button>
  </aside></>
}

function Sparkline({ index }: { index: number }) {
  const key = index % 2 === 0 ? 'runs' : 'saved'
  const id = `spark-${index}`
  return <div className="mini-spark" aria-hidden="true"><ResponsiveContainer width="100%" height="100%"><AreaChart data={trendData}><defs><linearGradient id={id} x1="0" y1="0" x2="0" y2="1"><stop offset="0%" stopColor={index === 1 ? '#58aeff' : '#76c5ff'} stopOpacity={.34} /><stop offset="100%" stopColor={index === 1 ? '#58aeff' : '#76c5ff'} stopOpacity={0} /></linearGradient></defs><Area type="monotone" dataKey={key} stroke={index === 1 ? '#58aeff' : '#76c5ff'} strokeWidth={1.8} fill={`url(#${id})`} isAnimationActive={false} /></AreaChart></ResponsiveContainer></div>
}

function Timeline() {
  const [expanded, setExpanded] = useState<number | null>(0)
  return <section className="timeline-panel"><div className="dash-section-title"><div><span className="dash-eyebrow">LIVE FEED</span><h2>Recent activity</h2></div><span className="timeline-more" aria-hidden="true"><Ellipsis size={17} /></span></div><div className="timeline">{activity.map((event, i) => <article className={`timeline-item state-${event.state}`} key={event.title}><button className="timeline-marker" onClick={() => setExpanded(expanded === i ? null : i)} aria-expanded={expanded === i} aria-label={`${expanded === i ? 'Collapse' : 'Expand'} ${event.title}`}>{event.state === 'success' ? <Check size={12} /> : event.state === 'error' ? <X size={12} /> : <span className="spinner" />}</button><div className="timeline-content"><button className="timeline-summary" onClick={() => setExpanded(expanded === i ? null : i)} aria-expanded={expanded === i}><strong>{event.title}</strong><small>{event.detail}</small></button><span className="timeline-time">{event.duration}</span>{expanded === i && <p className="timeline-expanded">{event.expanded}</p>}</div></article>)}</div><button className="activity-link" onClick={() => setExpanded(null)}>Collapse activity details <ArrowRightIcon /></button></section>
}

function ArrowRightIcon() { return <ChevronRight size={13} /> }

export function Dashboard() {
  const [collapsed, setCollapsed] = useState(false)
  const [mobileOpen, setMobileOpen] = useState(false)
  const [active, setActive] = useState('Overview')
  const [query, setQuery] = useState('')
  const [enabled, setEnabled] = useState<Record<string, boolean>>({ 'Inbound lead follow-up': true, 'Morning team brief': true, 'Support triage': true, 'Weekly client pulse': false })
  const [activeOnly, setActiveOnly] = useState(false)
  const [notice, setNotice] = useState(false)
  const [createOpen, setCreateOpen] = useState(false)
  const [draftName, setDraftName] = useState('')
  const createTriggerRef = useRef<HTMLButtonElement>(null)
  const dialogRef = useRef<HTMLFormElement>(null)
  const [extraWorkflows, setExtraWorkflows] = useState<Array<{ name: string; icon: string; trigger: string; status: string; lastRun: string; runs: string }>>([])
  const allWorkflows = [...workflows, ...extraWorkflows]
  const rows = allWorkflows.filter((flow) => `${flow.name} ${flow.trigger}`.toLowerCase().includes(query.toLowerCase())).filter((flow) => !activeOnly || enabled[flow.name])
  const createWorkflow = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    const name = draftName.trim()
    if (!name) return
    setExtraWorkflows((items) => [...items, { name, icon: '✦', trigger: 'Choose a trigger', status: 'Paused', lastRun: 'Not run yet', runs: '0' }])
    setEnabled((items) => ({ ...items, [name]: false }))
    setDraftName('')
    setCreateOpen(false)
  }
  useEffect(() => {
    if (!createOpen) return
    const input = dialogRef.current?.querySelector<HTMLInputElement>('input')
    input?.focus()
    return () => createTriggerRef.current?.focus()
  }, [createOpen])
  const handleDialogKeyDown = (event: KeyboardEvent<HTMLFormElement>) => {
    if (event.key === 'Escape') { event.preventDefault(); setCreateOpen(false); return }
    if (event.key !== 'Tab') return
    const controls = [...(dialogRef.current?.querySelectorAll<HTMLElement>('button:not(:disabled), input:not(:disabled)') ?? [])]
    if (!controls.length) return
    const first = controls[0], last = controls[controls.length - 1]
    if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last.focus() }
    else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first.focus() }
  }

  return <main className="dashboard"><CosmicBackground /><a className="skip-link" href="#dashboard-main">Skip to dashboard</a><Sidebar collapsed={collapsed} setCollapsed={setCollapsed} active={active} setActive={setActive} mobileOpen={mobileOpen} setMobileOpen={setMobileOpen} onCreate={() => setCreateOpen(true)} /><div className="dash-main"><header className="dash-topbar"><div className="dash-breadcrumb"><button className="mobile-dash-menu" aria-label="Toggle sidebar" aria-expanded={mobileOpen} onClick={() => setMobileOpen(!mobileOpen)}><Menu size={17} /></button><span className="crumb-muted">Northstar Studio</span><ChevronRight size={13} /><b>{active}</b></div><div className="dash-top-actions"><CosmicMotionToggle compact /><label className="dash-search"><Search size={14} /><input name="workflowSearch" autoComplete="off" value={query} onChange={(e) => setQuery(e.target.value)} placeholder="Search workflows…" aria-label="Search workflows" /><kbd>⌘&nbsp;K</kbd></label><button ref={createTriggerRef} className="button button-primary new-workflow" onClick={() => setCreateOpen(true)}><Plus size={15} /><span>New workflow</span></button><button className="notification-button" aria-label="Notifications" aria-expanded={notice} onClick={() => setNotice(!notice)}><Bell size={16} /><i /></button>{notice && <div className="dash-toast" role="status"><Check size={14} /> You’re all caught up.</div>}</div></header>
      <div className="dash-content" id="dashboard-main" tabIndex={-1}><div className="dash-welcome"><div><span className="eyebrow"><i className="eyebrow-dot" /> TODAY AT A GLANCE</span><h1>Good morning, Alex <span aria-hidden="true">✦</span></h1><p>Here’s what your agents have been up to.</p></div><div className="date-filter"><FileClock size={14} /> Last 7 days <ChevronDown size={13} /></div></div>
        <section className="kpi-grid" aria-label="Workspace metrics">{kpis.map((item, i) => <article className="kpi-card glass" key={item.key}><div className="kpi-top"><span>{item.label}</span><span className="kpi-hint" title={`${item.label} for this workspace`}><CircleHelp size={13} /></span></div><div className="kpi-bottom"><div><strong>{item.value}</strong><small><i /> {item.change} <em>vs. last week</em></small></div><Sparkline index={i} /></div></article>)}</section>
        <div className="dash-body-grid"><div className="dash-main-column"><section className="chart-card glass"><div className="dash-section-title"><div><span className="dash-eyebrow">WORKSPACE PULSE</span><h2>Workflow activity</h2></div><div className="chart-legend"><span><i className="legend-primary" /> Runs</span><span><i className="legend-blue" /> Hours saved</span><span className="chart-settings" title="Seven-day workflow activity"><SlidersHorizontal size={13} /></span></div></div><div className="chart-summary"><strong>1,284 <small>runs</small></strong><span><i /> 12.8% <em>this week</em></span></div><div className="main-chart" role="img" aria-label="Runs and hours saved over the last seven days"><ResponsiveContainer width="100%" height="100%"><AreaChart data={trendData} margin={{ top: 14, right: 6, bottom: 0, left: -17 }}><defs><linearGradient id="runs-fill" x1="0" y1="0" x2="0" y2="1"><stop offset="0%" stopColor="#4ba8ff" stopOpacity={.24} /><stop offset="100%" stopColor="#4ba8ff" stopOpacity={0} /></linearGradient><linearGradient id="saved-fill" x1="0" y1="0" x2="0" y2="1"><stop offset="0%" stopColor="#4aa3ff" stopOpacity={.12} /><stop offset="100%" stopColor="#4aa3ff" stopOpacity={0} /></linearGradient></defs><XAxis dataKey="day" tick={{ fill: '#79738e', fontSize: 10 }} tickLine={false} axisLine={false} /><YAxis tick={{ fill: '#79738e', fontSize: 10 }} tickLine={false} axisLine={false} /><Tooltip contentStyle={{ background: '#081a31', border: '1px solid rgba(70, 155, 255,.25)', borderRadius: 9, color: '#f2f8ff', fontSize: 11 }} /><Area type="monotone" dataKey="runs" stroke="#76c5ff" strokeWidth={2} fill="url(#runs-fill)" /><Area type="monotone" dataKey="saved" stroke="#4aa3ff" strokeWidth={1.5} fill="url(#saved-fill)" /></AreaChart></ResponsiveContainer></div></section>
          <section className="workflow-table-card glass" id="workflow-library"><div className="dash-section-title"><div><span className="dash-eyebrow">AUTOMATION LIBRARY</span><h2>Your workflows <span className="table-count">{String(allWorkflows.length).padStart(2,'0')}</span></h2></div><button className={`table-filter${activeOnly ? ' selected' : ''}`} aria-pressed={activeOnly} onClick={() => setActiveOnly(!activeOnly)}><SlidersHorizontal size={13} /> {activeOnly ? 'Active only' : 'Filter'}</button></div><div className="workflow-table-scroll"><table><thead><tr><th>WORKFLOW</th><th>TRIGGER</th><th>STATUS</th><th>LAST RUN</th><th>ON / OFF</th></tr></thead><tbody>{rows.map((flow) => <tr key={flow.name}><td><span className="table-flow-icon" aria-hidden="true">{flow.icon}</span><span className="table-flow-name">{flow.name}<small>{flow.runs} runs this week</small></span></td><td>{flow.trigger}</td><td><span className={`table-status ${enabled[flow.name] ? 'is-on' : 'is-off'}`}>{enabled[flow.name] ? 'Active' : 'Paused'}</span></td><td>{flow.lastRun}</td><td><button role="switch" aria-checked={enabled[flow.name]} aria-label={`${enabled[flow.name] ? 'Pause' : 'Start'} ${flow.name}`} className={`switch ${enabled[flow.name] ? 'checked' : ''}`} onClick={() => setEnabled((v) => ({ ...v, [flow.name]: !v[flow.name] }))}><i aria-hidden="true" /></button></td></tr>)}{rows.length === 0 && <tr><td colSpan={5} className="empty-table">No workflows match “{query}”.</td></tr>}</tbody></table></div><button className="activity-link table-view-all" onClick={() => setActive('Workflows')}>View all workflows <ChevronRight size={13} /></button></section>
        </div><aside className="dash-right-column"><Timeline /><div className="insight-card glass"><span className="insight-icon"><Sparkles size={16} /></span><span className="dash-eyebrow">A SMALL WIN</span><p>Your agents gave the team <strong>186 hours back</strong> this week. That’s nearly five full work weeks.</p><a href="#workflow-library">Explore workflows <ChevronRight size={13} /></a></div><div className="dash-help"><span>Need a hand?</span><a href="mailto:hello@yourbrand.ai">Chat with our team <ChevronRight size={12} /></a></div></aside></div>
      </div><footer className="dash-footer"><span>YOURBRAND · NORTHSTAR STUDIO</span><span><i /> ALL SYSTEMS OPERATIONAL</span></footer></div>{createOpen && <div className="modal-backdrop"><form ref={dialogRef} className="create-modal glass" role="dialog" aria-modal="true" aria-labelledby="create-title" onSubmit={createWorkflow} onKeyDown={handleDialogKeyDown}><button type="button" className="modal-close" aria-label="Close dialog" onClick={() => setCreateOpen(false)}><X size={16} /></button><span className="service-icon"><Workflow size={18} /></span><span className="dash-eyebrow">A GOOD PLACE TO START</span><h2 id="create-title">Create a workflow</h2><p>Give this workflow a name. You can add a trigger and actions next.</p><label htmlFor="workflow-name">Workflow name</label><input id="workflow-name" name="workflowName" autoComplete="off" required minLength={2} maxLength={60} value={draftName} onChange={(e) => setDraftName(e.target.value)} placeholder="e.g. Welcome new clients…" /><div className="modal-actions"><button type="button" className="button button-glass" onClick={() => setCreateOpen(false)}>Cancel</button><button type="submit" className="button button-primary">Create workflow <ChevronRight size={14} /></button></div></form></div>}</main>
}
