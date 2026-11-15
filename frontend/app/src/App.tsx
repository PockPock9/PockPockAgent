import { useEffect, useState } from 'react'
import { BlackHoleBackground } from './blackhole/BlackHoleBackground'
import {
  Activity,
  ArrowDown,
  AudioLines,
  Bot,
  Check,
  ChevronRight,
  CircleHelp,
  Globe2,
  Menu,
  MessageSquareText,
  Play,
  Plug,
  Plus,
  Puzzle,
  Radio,
  Search,
  Server,
  Settings2,
  Shield,
  Sparkles,
  X,
  Zap,
} from 'lucide-react'
import { BrowserRecipes } from './BrowserRecipes'
import { MemorySettings } from './MemorySettings'
import { ExtensionsPage } from './features/extensions/ExtensionsPage'
import { ResearchSettings } from './ResearchSettings'
import { ChatWorkspace } from './features/chat/ChatWorkspace'
import type { Conversation } from './features/chat/chatTypes'
import { useConversations, useLocalState } from './shared/appData'
import { ModelRoom } from './features/models/ModelRoom'
import { OllamaActionButton, OllamaFeedback, StatusMark } from './features/models/ModelControls'
import { modelFamily } from './features/models/modelUtils'
import type { AppState, OllamaFeedbackState, Trace } from './features/models/modelTypes'
import './App.css'

function formatTime(value: string) {
  return new Date(value).toLocaleTimeString('en-US', { hour12: false })
}

function Header({ state, onOpenMenu }: { state: AppState; onOpenMenu: () => void }) {
  const [now, setNow] = useState(() => new Date())
  useEffect(() => {
    const timer = window.setInterval(() => setNow(new Date()), 1000)
    return () => window.clearInterval(timer)
  }, [])

  return (
    <header className="app-header">
      <div className="app-header__topline" aria-label="System context">
        <span>PockPock / Local inference</span>
        <span>Router control / Local only</span>
        <span>Node 01</span>
      </div>
      <div className="app-header__main">
        <div className="app-header__left">
          <div className="app-brand-mark">P<span>.</span></div>
          <div className="app-brand">PockPock<span>AI</span><small>Local intelligence / 01</small></div>
        </div>
        <div className="app-header__telemetry">
          <span><StatusMark online={state.connected} />Ollama <b>{state.connected ? 'Linked' : 'Offline'}</b></span>
          <span><Radio size={12} /> Router <b>{state.api_connected ? state.router_enabled ? 'Ready' : 'Paused' : 'Unknown'}</b></span>
          <span className="header-clock">{now.toLocaleTimeString('en-US', { hour12: false })}</span>
        </div>
        <button className="app-header__menu" onClick={onOpenMenu} aria-label="Open navigation"><Menu size={16} /></button>
      </div>
    </header>
  )
}

function Sidebar({
  page,
  setPage,
  conversations,
  activeId,
  onSelectConversation,
  onNewChat,
  mobileOpen,
  closeMobile,
}: {
  page: string
  setPage: (page: string) => void
  conversations: Conversation[]
  activeId: string
  onSelectConversation: (id: string) => void
  onNewChat: () => void
  mobileOpen: boolean
  closeMobile: () => void
}) {
  const selectPage = (next: string) => {
    setPage(next)
    closeMobile()
  }

  return (
    <>
      {mobileOpen && <button className="mobile-backdrop" onClick={closeMobile} aria-label="Close navigation" />}
      <aside className={`sidebar${mobileOpen ? ' sidebar--open' : ''}`}>
        <div className="sidebar__section-label">Workspace</div>
        <nav className="main-nav" aria-label="Workspace pages">
          <button className={page === 'overview' ? 'nav-item nav-item--active' : 'nav-item'} aria-current={page === 'overview' ? 'page' : undefined} onClick={() => selectPage('overview')}>
            <Activity size={18} strokeWidth={1.7} /> <span>Overview</span>
          </button>
          <button className={page === 'chat' ? 'nav-item nav-item--active' : 'nav-item'} aria-current={page === 'chat' ? 'page' : undefined} onClick={() => selectPage('chat')}>
            <MessageSquareText size={18} strokeWidth={1.7} /> <span>Conversations</span>
          </button>
          <button className={page === 'models' ? 'nav-item nav-item--active' : 'nav-item'} aria-current={page === 'models' ? 'page' : undefined} onClick={() => selectPage('models')}>
            <Server size={18} strokeWidth={1.7} /> <span>Models</span>
          </button>
          <button className={page === 'browser-recipes' ? 'nav-item nav-item--active' : 'nav-item'} aria-current={page === 'browser-recipes' ? 'page' : undefined} onClick={() => selectPage('browser-recipes')}>
            <Globe2 size={18} strokeWidth={1.7} /> <span>Browser</span>
          </button>
          <button className={page === 'research-settings' ? 'nav-item nav-item--active' : 'nav-item'} aria-current={page === 'research-settings' ? 'page' : undefined} onClick={() => selectPage('research-settings')}>
            <Search size={18} strokeWidth={1.7} /> <span>Research</span>
          </button>
          <button className={page === 'memory-settings' ? 'nav-item nav-item--active' : 'nav-item'} aria-current={page === 'memory-settings' ? 'page' : undefined} onClick={() => selectPage('memory-settings')}>
            <Sparkles size={18} strokeWidth={1.7} /> <span>Memory</span>
          </button>
          <button className={page === 'skills' ? 'nav-item nav-item--active' : 'nav-item'} aria-current={page === 'skills' ? 'page' : undefined} onClick={() => selectPage('skills')}>
            <Puzzle size={18} strokeWidth={1.7} /> <span>Skills</span>
          </button>
          <button className={page === 'mcp-servers' ? 'nav-item nav-item--active' : 'nav-item'} aria-current={page === 'mcp-servers' ? 'page' : undefined} onClick={() => selectPage('mcp-servers')}>
            <Plug size={18} strokeWidth={1.7} /> <span>MCP servers</span>
          </button>
        </nav>

        {page === 'chat' && (
          <div className="conversation-list">
            <div className="sidebar__section-heading"><span>Recent threads</span><button onClick={onNewChat} aria-label="New conversation"><Plus size={14} /></button></div>
            {conversations.length === 0 && <div className="sidebar-empty">No conversations yet.</div>}
            {[...conversations].sort((a, b) => b.updatedAt - a.updatedAt).map((conversation) => (
              <button
                key={conversation.id}
                className={`thread-link${activeId === conversation.id ? ' thread-link--active' : ''}`}
                onClick={() => onSelectConversation(conversation.id)}
              >
                <span>{conversation.title}</span><small>{conversation.messages.length}</small>
              </button>
            ))}
          </div>
        )}

      </aside>
    </>
  )
}

function Metric({
  label,
  value,
  note,
  accent,
}: {
  label: string
  value: string
  note: string
  accent?: boolean
}) {
  return (
    <div className="metric-card">
      <div className="metric-card__label">{label}</div>
      <div className={`metric-card__value${accent ? ' metric-card__value--accent' : ''}`}>{value}</div>
      <div className="metric-card__note">{note}</div>
    </div>
  )
}

function sentenceCase(text: string) {
  return text ? text.charAt(0).toUpperCase() + text.slice(1).toLowerCase() : text
}

function tracePresentation(trace: Trace) {
  if (trace.event === 'request_received') return { label: 'Request received', icon: <ArrowDown size={13} />, tone: 'muted' }
  if (trace.event === 'agent_task_started') return { label: 'Agent task started', icon: <Bot size={13} />, tone: 'active' }
  if (trace.event === 'agent_task_completed') return { label: `Agent ${String(trace.status)}`, icon: trace.status === 'success' ? <Check size={13} /> : <X size={13} />, tone: trace.status === 'success' ? 'success' : 'error' }
  if (trace.event === 'agent_tool_started') return { label: 'Agent tool started', icon: <Play size={12} />, tone: 'active' }
  if (trace.event === 'agent_tool_completed') return { label: `Tool ${String(trace.status)}`, icon: trace.status === 'success' ? <Check size={13} /> : <X size={13} />, tone: trace.status === 'success' ? 'success' : 'error' }
  if (trace.event === 'route_decision') return { label: trace.source === 'manual' ? 'Manual route' : 'Route decision', icon: <ChevronRight size={14} />, tone: 'route' }
  if (trace.event === 'model_call_started') return { label: trace.role === 'classifier' ? 'Classifier started' : sentenceCase(`${trace.role || 'Model'} call started`), icon: <Play size={12} />, tone: 'active' }
  if (trace.event === 'model_call_completed') return { label: trace.status === 'success' ? 'Call completed' : 'Call interrupted', icon: trace.status === 'success' ? <Check size={13} /> : <X size={13} />, tone: trace.status === 'success' ? 'success' : 'error' }
  if (trace.event === 'router_state') return { label: `Router ${String(trace.status)}`, icon: <Zap size={13} />, tone: 'route' }
  if (trace.event === 'model_management') return { label: `Model ${String(trace.status)}`, icon: <Settings2 size={13} />, tone: 'muted' }
  return { label: sentenceCase(trace.event.replaceAll('_', ' ')), icon: <Activity size={13} />, tone: 'muted' }
}

function ActivityFeed({ events, compact = false }: { events: Trace[]; compact?: boolean }) {
  const visible = compact ? events.slice(0, 9) : events
  if (!visible.length) {
    return <div className="empty-feed"><AudioLines size={21} /><span>Waiting for the first route.</span><small>Send a message through PockPock AI to start the trace.</small></div>
  }
  return (
    <div className="activity-feed">
      {visible.map((trace) => {
        const presentation = tracePresentation(trace)
        return (
          <article className={`trace-row trace-row--${presentation.tone}`} key={trace.id}>
            <div className="trace-row__icon">{presentation.icon}</div>
            <div className="trace-row__body">
              <div className="trace-row__top"><strong>{presentation.label}</strong><time>{formatTime(trace.created_at)}</time></div>
              <div className="trace-row__model">{trace.model || trace.reason || trace.category || 'Router'}</div>
              {trace.event === 'route_decision' && trace.reason && <div className="trace-row__reason">{trace.reason}</div>}
              <div className="trace-tags">
                {trace.category && <span>{trace.category}</span>}
                {trace.confidence !== null && trace.confidence !== undefined && <span>{Math.round(trace.confidence * 100)}% CONF</span>}
                {trace.complexity !== null && trace.complexity !== undefined && <span>Complexity {trace.complexity}/10</span>}
                {trace.duration_ms !== null && trace.duration_ms !== undefined && <span>{trace.duration_ms} ms</span>}
                {trace.source && <span>{trace.source}</span>}
                {trace.error && <span className="trace-tags__error">{trace.error}</span>}
              </div>
            </div>
          </article>
        )
      })}
    </div>
  )
}

function ModelHealth({ state, onNavigate }: { state: AppState; onNavigate: () => void }) {
  const models = state.models
  return (
    <section className="panel model-health">
      <div className="panel-heading">
        <div><span className="panel-kicker">01 / Inventory</span><h2>Model health</h2></div>
        <button className="text-action" onClick={onNavigate}>All models <ChevronRight size={13} /></button>
      </div>
      {!models.length ? (
        <div className="inline-empty"><CircleHelp size={15} /> Ollama is offline. Start it to load the model inventory.</div>
      ) : (
        <div className="model-health__list">
          {models.slice(0, 7).map((model) => (
            <div className="health-row" key={model.name}>
              <StatusMark online={model.running} />
              <span className="health-row__name">{model.name}<small>{model.calls ?? 0} calls · {model.decisions ?? 0} decisions</small></span>
              <span className="health-row__family">{modelFamily(model.name)}</span>
              <span className={`health-row__status${model.enabled ? '' : ' health-row__status--off'}`}>
                {model.running ? 'In memory' : model.enabled ? 'Ready' : 'Disabled'}
              </span>
            </div>
          ))}
          {models.length > 7 && <button className="health-more" onClick={onNavigate}>+ {models.length - 7} more models</button>}
        </div>
      )}
    </section>
  )
}

function Overview({
  state,
  onNavigate,
  onOllamaAction,
  ollamaPending,
  ollamaFeedback,
  onDismissOllamaFeedback,
}: {
  state: AppState
  onNavigate: () => void
  onOllamaAction: () => void
  ollamaPending: boolean
  ollamaFeedback: OllamaFeedbackState
  onDismissOllamaFeedback: () => void
}) {
  const calls = state.totals.calls ?? 0
  const avg = state.totals.avg_ms
  const recentDecision = state.events.find((event) => event.event === 'route_decision')
  const enabledCount = state.models.filter((model) => model.enabled).length
  const runningCount = state.models.filter((model) => model.running).length

  return (
    <div className="page overview-page">
      <div className="page-title">
        <div><div className="eyebrow"><span className="eyebrow__rule" />Your local AI workspace</div><h1>Overview</h1><p>Check your connection, see which models are ready, and follow recent activity.</p></div>
        <div className="overview-ollama-controls">
          <div className={`connection-chip${state.connected ? ' connection-chip--on' : ''}`}><StatusMark online={state.connected} />{state.connected ? 'Ollama connected' : 'Ollama offline'}</div>
          <OllamaActionButton connected={state.connected} pending={ollamaPending} disabled={!state.api_connected} onClick={onOllamaAction} />
        </div>
      </div>
      {!state.connected && <div className="notice-banner"><CircleHelp size={15} /><span>{!state.api_connected ? 'The local service is unavailable. Start PockPock AI on this computer to reconnect.' : `${state.error || 'Ollama is not responding.'} Start Ollama to enable chat and model management.`}</span></div>}
      <OllamaFeedback feedback={ollamaFeedback} onDismiss={onDismissOllamaFeedback} />
      <div className="metric-grid">
        <Metric label="Requests handled" value={String(calls)} note="Total routed requests" accent />
        <Metric label="Models ready" value={`${enabledCount} of ${state.models.length}`} note="Available for local responses" />
        <Metric label="Models running" value={String(runningCount)} note="Currently using memory" />
        <Metric label="Average response" value={avg == null ? '—' : `${(avg / 1000).toFixed(1)}s`} note="Across completed requests" />
      </div>

      <section className="route-strip panel">
        <div className="route-strip__head"><div><span className="panel-kicker">How a request is handled</span><strong>From your message to a local response</strong></div><span className="route-strip__request">Router model: {state.classifier}</span></div>
        <div className="route-pipeline">
          <div className="pipeline-node"><span>Your message</span></div>
          <div className="pipeline-connector"><i /></div>
          <div className="pipeline-node pipeline-node--classifier"><span>Router<br /><b>{state.classifier}</b></span></div>
          <div className="pipeline-connector"><i /></div>
          <div className="pipeline-node pipeline-node--target"><span>Selected model<br /><b>{recentDecision?.model || 'Waiting for a request'}</b></span></div>
          <div className="pipeline-connector"><i /></div>
          <div className="pipeline-node"><span>Response</span></div>
        </div>
      </section>

      <div className="overview-columns">
        <section className="panel">
          <div className="panel-heading"><div><span className="panel-kicker">Recent activity</span><h2>Request history</h2></div><span className="live-label"><span />Updates automatically</span></div>
          <ActivityFeed events={state.events} compact />
        </section>
        <ModelHealth state={state} onNavigate={onNavigate} />
      </div>
      <div className="overview-footnote"><Shield size={13} /> Your prompts and responses stay out of telemetry. Services run on this computer.</div>
    </div>
  )
}

function App() {
  const { state, refresh } = useLocalState()
  const [ollamaPending, setOllamaPending] = useState(false)
  const [ollamaFeedback, setOllamaFeedback] = useState<OllamaFeedbackState>(null)
  const { conversations, setConversations, activeId, setActiveId, storageError, setStorageError, createConversation } = useConversations()
  const [page, setPage] = useState('overview')
  const [mobileOpen, setMobileOpen] = useState(false)
  const newChat = () => {
    createConversation()
    setPage('chat')
    setMobileOpen(false)
  }

  const connectOrRefreshOllama = async () => {
    if (ollamaPending) return
    setOllamaPending(true)
    setOllamaFeedback(null)
    try {
      const response = await fetch('/api/ollama/start', { method: 'POST' })
      const result = await response.json() as { detail?: string; started?: boolean }
      if (!response.ok) throw new Error(result.detail || 'Could not connect to Ollama')

      const nextState = await refresh()
      if (!nextState?.connected) {
        throw new Error(nextState?.error || 'Ollama started, but PockPock AI could not load its model inventory.')
      }
      setOllamaFeedback({
        message: `${result.started ? 'Ollama started' : 'Connected to Ollama'} · ${nextState.models.length} installed models loaded`,
        error: false,
      })
    } catch (error) {
      setOllamaFeedback({
        message: error instanceof Error ? error.message : 'Could not connect to Ollama',
        error: true,
      })
    } finally {
      setOllamaPending(false)
    }
  }

  const ensureRecipeConversation = () => activeId || createConversation('Browser recipe')

  const onRecipeRunStarted = (conversationId: string, runId: string, recipeName: string) => {
    setConversations((previous) => previous.map((conversation) => conversation.id !== conversationId ? conversation : {
      ...conversation,
      title: conversation.title === 'New conversation' || conversation.title === 'Browser recipe' ? `Browser recipe: ${recipeName}` : conversation.title,
      updatedAt: Date.now(),
      messages: [
        ...conversation.messages,
        { role: 'user', content: `Run browser recipe: ${recipeName}` },
        { role: 'assistant', content: '', toolRunId: runId, runEvents: [] },
      ],
    }))
  }

  const onRecipeRunEvent = (conversationId: string, runId: string, event: Record<string, unknown> & { sequence?: number }) => {
    setConversations((previous) => previous.map((conversation) => conversation.id !== conversationId ? conversation : {
      ...conversation,
      updatedAt: Date.now(),
      messages: conversation.messages.map((message) => {
        if (message.toolRunId !== runId) return message
        const sequence = Number(event.sequence)
        const current = message.runEvents ?? []
        if (Number.isFinite(sequence) && current.some((item) => item.sequence === sequence)) return message
        return { ...message, runEvents: [...current, event].sort((left, right) => (left.sequence ?? 0) - (right.sequence ?? 0)) }
      }),
    }))
  }

  return (
    <div className={`app-frame${page === 'chat' ? ' app-frame--chat' : ''}`}>
      <BlackHoleBackground palette="blue" />
      <Header state={state} onOpenMenu={() => setMobileOpen(true)} />
      <div className="app-layout">
        <Sidebar
          page={page}
          setPage={(next) => {
            setPage(next)
          }}
          conversations={conversations}
          activeId={activeId}
          onSelectConversation={(id) => { setActiveId(id); setPage('chat'); setMobileOpen(false) }}
          onNewChat={newChat}
          mobileOpen={mobileOpen}
          closeMobile={() => setMobileOpen(false)}
        />
        <a className="skip-link" href="#main-content">Skip to main content</a>
        <main className="main-content" id="main-content" tabIndex={-1}>
          <div hidden={page !== 'overview'}><Overview state={state} onNavigate={() => setPage('models')} onOllamaAction={() => void connectOrRefreshOllama()} ollamaPending={ollamaPending} ollamaFeedback={ollamaFeedback} onDismissOllamaFeedback={() => setOllamaFeedback(null)} /></div>
          <div hidden={page !== 'chat'}>
            <ChatWorkspace
              state={state}
              conversations={conversations}
              setConversations={setConversations}
              activeId={activeId}
              setActiveId={setActiveId}
              newChat={newChat}
              onOpenExtensions={(kind) => setPage(kind === 'skills' ? 'skills' : 'mcp-servers')}
            />
          </div>
          <div hidden={page !== 'models'}><ModelRoom state={state} refresh={refresh} onOllamaAction={() => void connectOrRefreshOllama()} ollamaPending={ollamaPending} ollamaFeedback={ollamaFeedback} onDismissOllamaFeedback={() => setOllamaFeedback(null)} /></div>
          <div hidden={page !== 'browser-recipes'}><BrowserRecipes ensureConversation={ensureRecipeConversation} onRunStarted={onRecipeRunStarted} onRunEvent={onRecipeRunEvent} /></div>
          <div hidden={page !== 'research-settings'}><ResearchSettings /></div>
          <div hidden={page !== 'memory-settings'}><MemorySettings /></div>
          <div hidden={page !== 'skills'}><ExtensionsPage kind="skills" visible={page === 'skills'} /></div>
          <div hidden={page !== 'mcp-servers'}><ExtensionsPage kind="mcp" visible={page === 'mcp-servers'} /></div>
          <footer className="app-footer"><span>PockPock AI / Local router</span><span>No cloud · No prompt logging</span><span>Build 01</span></footer>
        </main>
      </div>
      {storageError && <div className="storage-warning" role="status">{storageError}<button onClick={() => setStorageError('')}><X size={12} /></button></div>}
    </div>
  )
}

export default App
