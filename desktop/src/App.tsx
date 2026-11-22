// PockPock Agent Studio: the desktop workspace. Icon rail (Tasks, Workshop, Activity, Services,
// Settings), the task list or Workshop navigation, the conversation or a page, the inspector
// (Context, Files, Terminal), the terminal panel, and the status bar. Turns run one at a time.
import { useCallback, useEffect, useRef, useState } from 'react'
import { ChatPane } from './components/ChatPane'
import type { SendRequest } from './components/ChatPane'
import { CommandPalette } from './components/CommandPalette'
import { Inspector } from './components/Inspector'
import type { InspectorTab } from './components/Inspector'
import { Rail, sectionOf, StatusBar, TitleBar, WorkshopNav } from './components/Shell'
import type { Page, Section } from './components/Shell'
import { TaskPanel } from './components/TaskPanel'
import { TerminalPanel } from './components/TerminalPanel'
import { Toasts } from './components/Toasts'
import { SettingsPage } from './pages/SettingsPage'
import { SkillsPage } from './pages/SkillsPage'
import { McpPage } from './pages/McpPage'
import { ModelsPage } from './pages/ModelsPage'
import { MemoryPage } from './pages/MemoryPage'
import { MaintenancePage } from './pages/MaintenancePage'
import { CloudPage } from './pages/CloudPage'
import { ConnectorsPage } from './pages/ConnectorsPage'
import { ActivityPage } from './pages/ActivityPage'
import { RecipesPage } from './pages/RecipesPage'
import { ResearchPage } from './pages/ResearchPage'
import { ServicesPage } from './pages/ServicesPage'
import { SetupPage } from './pages/SetupPage'
import { uid } from './lib/api'
import { cancelActiveRun, runTurn } from './lib/engines'
import { useStatus } from './lib/status'
import { titleFrom, useSessions, useSettings } from './lib/store'
import { useUpdates } from './lib/updates'
import { useTheme, validTheme } from './lib/theme'
import { bridge } from './lib/types'
import type { AppInfo, Attachment, Engine, Message } from './lib/types'
import { hasMod } from './lib/platform'

type Running = { sessionId: string; messageId: string; controller: AbortController }
type Overrides = { engine?: Engine; model?: string }

function useNarrow(query: string) {
  const [match, setMatch] = useState(() => window.matchMedia(query).matches)
  useEffect(() => {
    const list = window.matchMedia(query)
    const onChange = () => setMatch(list.matches)
    list.addEventListener('change', onChange)
    return () => list.removeEventListener('change', onChange)
  }, [query])
  return match
}

export default function App() {
  const { settings, patch, loaded: settingsLoaded } = useSettings()
  useTheme(settings.theme, settingsLoaded)
  const updates = useUpdates()
  const sessions = useSessions()
  const engine = settings.engine ?? 'agent'
  const status = useStatus(engine === 'nemoclaw')
  const [page, setPage] = useState<Page | 'setup'>('chat')
  const [workshopPage, setWorkshopPage] = useState<Page>('skills')
  const [running, setRunning] = useState<Running | null>(null)
  const runningRef = useRef<Running | null>(null)
  const retryRef = useRef<{ request: SendRequest; overrides: Overrides } | null>(null)
  const [attachments, setAttachments] = useState<Attachment[]>([])
  const [focusSignal, setFocusSignal] = useState(0)
  const [palette, setPalette] = useState(false)
  // Below 860 px the rail and the task panel open from a menu button; below 1100 px the inspector
  // opens over the content instead of beside it.
  const narrowNav = useNarrow('(max-width: 860px)')
  const narrowInspector = useNarrow('(max-width: 1100px)')
  const [overlay, setOverlay] = useState<'nav' | 'inspector' | null>(null)
  const [info, setInfo] = useState<AppInfo | null>(null)
  const [loginItem, setLoginItemState] = useState(false)
  const section = sectionOf(page)

  useEffect(() => {
    const desktop = bridge()
    if (!desktop) return
    void desktop.info().then((next) => { setInfo(next); setLoginItemState(next.loginItem) })
    // First launch, or a setup that stopped part-way (for example for a Windows restart).
    void desktop.setup.status().then((setup) => { if (setup.needsSetup || setup.pending) setPage('setup') })
  }, [])
  const setLoginItem = (enabled: boolean) => { void bridge()?.setLoginItem(enabled).then(setLoginItemState) }
  const active = sessions.sessions.find((session) => session.id === sessions.activeId) ?? null

  const openPage = useCallback((next: Page) => {
    setPage(next)
    if (sectionOf(next) === 'workshop') setWorkshopPage(next)
    setOverlay(null)
  }, [])

  const newChat = useCallback(() => {
    sessions.create()
    setPage('chat')
    setAttachments([])
    setOverlay(null)
    setFocusSignal((value) => value + 1)
  }, [sessions])

  const chooseFolder = useCallback(async () => {
    const desktop = bridge()
    if (!desktop) return
    const folder = await desktop.workspace.choose()
    if (folder) patch({ workspace: folder, files: true })
  }, [patch])

  const toggle = useCallback((panel: 'sidebar' | 'inspector' | 'terminal') => {
    if (panel === 'sidebar' && narrowNav) { setOverlay((current) => current === 'nav' ? null : 'nav'); return }
    if (panel === 'inspector' && narrowInspector) { setOverlay((current) => current === 'inspector' ? null : 'inspector'); return }
    if (panel === 'sidebar') patch({ sidebar: settings.sidebar === false })
    if (panel === 'inspector') patch({ files: settings.files === false })
    if (panel === 'terminal') patch({ terminal: !settings.terminal })
  }, [patch, settings.sidebar, settings.files, settings.terminal, narrowNav, narrowInspector])

  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (!hasMod(event) || event.altKey) return
      const key = event.key.toLowerCase()
      if (key === 'k' && !event.shiftKey) { event.preventDefault(); setPalette((open) => !open) }
      else if (key === 'n' && !event.shiftKey) { event.preventDefault(); newChat() }
      else if (key === 'b' && !event.shiftKey) { event.preventDefault(); toggle('sidebar') }
      else if ((key === 'j' || key === '`') && !event.shiftKey) { event.preventDefault(); toggle('terminal') }
      else if (key === 'e' && event.shiftKey) { event.preventDefault(); toggle('inspector') }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [newChat, toggle])

  // Escape closes an open overlay panel.
  useEffect(() => {
    if (!overlay) return
    const onKey = (event: KeyboardEvent) => { if (event.key === 'Escape') setOverlay(null) }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [overlay])

  const send = async ({ prompt, attachments: files }: SendRequest, overrides: Overrides = {}) => {
    if (runningRef.current) return
    const turnEngine = overrides.engine ?? engine
    const sessionId = active?.id ?? sessions.create()
    const history = active?.messages ?? []
    const now = Date.now()
    const user: Message = { id: uid(), role: 'user', content: prompt, createdAt: now, engine: turnEngine, attachments: files }
    const reply: Message = { id: uid(), role: 'assistant', content: '', createdAt: now, engine: turnEngine, status: 'streaming' }
    sessions.update(sessionId, (session) => ({
      ...session,
      title: session.messages.length ? session.title : titleFrom(prompt || files[0]?.name || 'New chat'),
      updatedAt: now,
      messages: [...session.messages, user, reply],
    }))
    setAttachments([])
    const controller = new AbortController()
    const current = { sessionId, messageId: reply.id, controller }
    runningRef.current = current
    setRunning(current)
    const patchReply = (change: (message: Message) => Message) => sessions.updateMessage(sessionId, reply.id, change)
    try {
      await runTurn({
        engine: turnEngine,
        sessionId,
        messageId: reply.id,
        history,
        prompt,
        attachments: files,
        signal: controller.signal,
        patch: patchReply,
        chatModel: overrides.model ?? settings.chatModel,
        clawModel: settings.clawModel,
        agentPermission: settings.agentPermission ?? 'auto-review',
        clawPermission: settings.clawPermission ?? 'ask',
        workspacePath: settings.workspace && settings.useWorkspaceForAgent !== false ? settings.workspace : undefined,
        outputDirectory: status.state?.output_directory,
      })
      patchReply((message) => ({ ...message, status: message.status === 'streaming' ? 'done' : message.status }))
    } catch (error) {
      const stopped = error instanceof DOMException && error.name === 'AbortError'
      const text = error instanceof Error ? error.message : 'The request failed.'
      patchReply((message) => ({
        ...message,
        status: stopped ? 'stopped' : 'error',
        content: stopped ? message.content : message.content ? `${message.content}\n\n**Error:** ${text}` : text,
        steps: message.steps?.map((step) => step.status === 'running' ? { ...step, status: stopped ? 'stopped' : 'failed' } : step),
        plan: message.plan?.status === 'pending' ? { ...message.plan, status: 'rejected' } : message.plan,
      }))
      if (!stopped && turnEngine === 'openclaw') void status.refreshClaw(true)
    } finally {
      runningRef.current = null
      setRunning(null)
      void status.refreshState()
      // "Use a smaller model" stops this run first; the retry starts once it has ended.
      const retry = retryRef.current
      retryRef.current = null
      if (retry) window.setTimeout(() => void send(retry.request, retry.overrides), 0)
    }
  }

  const stop = () => {
    runningRef.current?.controller.abort()
    void cancelActiveRun()
  }

  /** Sends the request behind `message` again, as a new turn, optionally with another model. */
  const retry = (message: Message, model?: string) => {
    if (!active) return
    const index = active.messages.findIndex((item) => item.id === message.id)
    const request = [...active.messages.slice(0, index)].reverse().find((item) => item.role === 'user')
    if (!request) return
    const next = { request: { prompt: request.content, attachments: request.attachments ?? [] }, overrides: { engine: message.engine, model } }
    if (runningRef.current) { retryRef.current = next; stop(); return }
    void send(next.request, next.overrides)
  }

  /** A failed agent run: a new PockPock Agent task for the remaining steps, from step `step` of its
   * approved plan. It is planned and approved like any task; the earlier steps are named as done. */
  const retryFrom = (message: Message, step: number) => {
    if (!active || runningRef.current) return
    const index = active.messages.findIndex((item) => item.id === message.id)
    const request = [...active.messages.slice(0, index)].reverse().find((item) => item.role === 'user')
    const steps = message.plan?.steps ?? []
    if (!request) return
    if (step <= 1 || !steps.length) { retry(message); return }
    const done = steps.slice(0, step - 1).map((item, position) => `${position + 1}. ${item}`).join('\n')
    const rest = steps.slice(step - 1).map((item, position) => `${step + position}. ${item}`).join('\n')
    const prompt = `${request.content}\n\nThis continues an earlier attempt that stopped with an error. These steps were already done; do not repeat them:\n${done}\n\nDo the remaining steps:\n${rest}`
    void send({ prompt, attachments: request.attachments ?? [] }, { engine: 'agent' })
  }

  /** The smallest enabled chat model smaller than the one `message` used; a loaded one first. */
  const smallerModel = (message: Message) => {
    const models = (status.state?.models ?? []).filter((model) => model.enabled && !model.embedding)
    const name = message.model?.split(' · ')[0]
    const currentSize = models.find((model) => model.name === name || model.name === `${name}:latest`)?.size
    if (!currentSize) return undefined
    const smaller = models.filter((model) => model.size < currentSize).sort((a, b) => Number(b.running) - Number(a.running) || a.size - b.size)
    return smaller[0]?.name
  }

  /** Cards inside a message change their own approval or plan; merge so streamed updates are kept. */
  const changeMessage = (next: Message) => {
    if (!active) return
    sessions.updateMessage(active.id, next.id, (current) => ({
      ...current,
      plan: next.plan ?? current.plan,
      approvals: current.approvals?.map((approval) => next.approvals?.find((item) => item.id === approval.id) ?? approval),
    }))
  }

  const deleteSession = (id: string) => {
    const session = sessions.sessions.find((item) => item.id === id)
    if (session?.messages.length && !window.confirm(`Delete “${session.title}”? This cannot be undone.`)) return
    sessions.remove(id)
  }

  const chooseSection = (next: Section) => {
    if (next === 'tasks') openPage('chat')
    else if (next === 'workshop') openPage(workshopPage)
    else openPage(next)
  }

  // The running turn waits for the user when its plan or an approval is pending.
  const runningMessage = running ? sessions.sessions.find((session) => session.id === running.sessionId)?.messages.find((message) => message.id === running.messageId) : undefined
  const needsYou = Boolean(runningMessage && (runningMessage.plan?.status === 'pending' || runningMessage.approvals?.some((approval) => approval.status === 'pending')))
  const servicesUp = status.services.filter((service) => service.status === 'running').length
  const servicesInstalled = status.services.filter((service) => service.available).length
  const servicesTone = !servicesInstalled ? 'off' : servicesUp < servicesInstalled ? 'warn' : 'ok'

  const navOverlay = narrowNav && overlay === 'nav'
  const inspectorOverlay = narrowInspector && overlay === 'inspector' && page === 'chat'
  const showPanel = narrowNav ? navOverlay : settings.sidebar !== false
  const showInspector = page === 'chat' && (narrowInspector ? inspectorOverlay : settings.files !== false)
  const panelInGrid = showPanel && !navOverlay
  const inspectorInGrid = showInspector && !inspectorOverlay
  const showTerminal = Boolean(settings.terminal)
  const lastReply = active ? [...active.messages].reverse().find((message) => message.role === 'assistant') : undefined
  const inspectorTab: InspectorTab = settings.inspectorTab ?? 'context'

  const panel = section === 'tasks' || section === 'settings'
    ? <TaskPanel overlay={navOverlay} sessions={sessions.sessions} activeId={sessions.activeId} isChat={page === 'chat'} running={running}
      onSelect={(id) => { sessions.setActiveId(id); setPage('chat'); setOverlay(null) }} onNew={newChat} onDelete={deleteSession} />
    : <WorkshopNav overlay={navOverlay} page={page === 'setup' ? 'settings' : page} status={status} onPage={openPage} />
  const rail = <Rail section={section} needsYou={needsYou} servicesTone={servicesTone} onSection={chooseSection} />

  return (
    <div className={`shell${narrowNav ? ' no-rail' : ''}${panelInGrid ? '' : ' no-panel'}${inspectorInGrid ? '' : ' no-inspector'}`}>
      <TitleBar onPalette={() => setPalette(true)} showMenu={narrowNav} onMenu={() => toggle('sidebar')} />
      {!narrowNav && rail}
      {panelInGrid && panel}
      {navOverlay && <div className="nav-overlay">{rail}{panel}</div>}
      {(navOverlay || inspectorOverlay) && <button type="button" className="overlay-backdrop" aria-label="Close panel" onClick={() => setOverlay(null)} />}
      <main className="main" id="main">
        {/* Starting is shown here; a stopped or failed gateway is a toast (components/Toasts.tsx). */}
        {page === 'chat' && (status.backend.phase === 'starting' || status.backend.phase === 'checking') && (
          <div className="banner" role="status">
            <span>{status.backend.phase === 'starting'
              ? `Starting the gateway… ${status.services.filter((item) => item.status === 'running').length} of ${status.services.filter((item) => item.available).length} services running`
              : 'Checking the gateway and Ollama…'}</span>
            <button type="button" className="link-button" onClick={() => openPage('services')}>Services</button>
          </div>
        )}
        {sessions.saveError && <div className="banner banner--error" role="alert"><span>Tasks could not be saved: {sessions.saveError}</span></div>}
        {page === 'chat' && (
          <ChatPane session={active} running={running} status={status} settings={settings} patchSettings={patch} onSend={(request) => send(request)} onStop={stop}
            onChangeMessage={changeMessage} onChooseFolder={() => void chooseFolder()} onOpenPage={openPage}
            pendingAttachments={attachments} setPendingAttachments={setAttachments} focusSignal={focusSignal}
            onRetry={retry} onRetryFrom={retryFrom} smallerModel={smallerModel}
            onPatchMessage={(messageId, change) => { if (active) sessions.updateMessage(active.id, messageId, change) }} onOpenServices={() => openPage('services')}
            inspectorOpen={showInspector} onToggleInspector={() => toggle('inspector')} />
        )}
        {page === 'skills' && <SkillsPage status={status} />}
        {page === 'mcp' && <McpPage status={status} />}
        {page === 'models' && <ModelsPage status={status} onOpenTerminal={() => patch({ terminal: true })} />}
        {page === 'cloud' && <CloudPage status={status} />}
        {page === 'connectors' && <ConnectorsPage />}
        {page === 'memory' && <MemoryPage />}
        {page === 'settings' && <SettingsPage status={status} info={info} onOpen={(next) => (next === 'setup' ? setPage(next) : openPage(next))} updates={updates} settings={settings} patchSettings={patch} />}
        {page === 'recipes' && <RecipesPage />}
        {page === 'activity' && <ActivityPage status={status} />}
        {page === 'research' && <ResearchPage />}
        {page === 'maintenance' && <MaintenancePage />}
        {page === 'services' && <ServicesPage status={status} settings={settings} patchSettings={patch} loginItem={loginItem} setLoginItem={setLoginItem} />}
        {page === 'setup' && <SetupPage onDone={() => setPage('chat')} />}
        {showTerminal && <TerminalPanel workspace={settings.workspace} onClose={() => patch({ terminal: false })} />}
      </main>
      {showInspector && (
        <Inspector tab={inspectorTab} onTab={(tab) => patch({ inspectorTab: tab })} overlay={inspectorOverlay} message={lastReply} settings={settings} status={status}
          terminalOpen={showTerminal} onToggleTerminal={() => toggle('terminal')} onChooseFolder={() => void chooseFolder()} onClose={() => toggle('inspector')}
          onAttach={(file) => setAttachments((previous) => [...previous, { name: file.name, kind: 'document', text: file.text, size: file.size }])} />
      )}
      <Toasts status={status} updates={updates} onOpenServices={() => openPage('services')} onOpenResearch={() => openPage('research')} />
      <StatusBar status={status} version={info?.version ?? '0.1.0'} onOpenServices={() => openPage('services')} updates={updates} onOpenSettings={() => openPage('settings')} />
      {palette && (
        <CommandPalette sessions={sessions.sessions} theme={validTheme(settings.theme)} onClose={() => setPalette(false)} onNew={newChat}
          onOpenTask={(id) => { sessions.setActiveId(id); setPage('chat') }} onPage={openPage} onTheme={(id) => patch({ theme: id })}
          onToggle={(panel) => toggle(panel)} />
      )}
    </div>
  )
}
