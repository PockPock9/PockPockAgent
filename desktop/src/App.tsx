// PockPock Agent: the desktop workspace. Sidebar (chats, customize), chat or settings page,
// files panel, terminal, and status bar. Turns run one at a time.
import { useCallback, useEffect, useRef, useState } from 'react'
import { ChatPane } from './components/ChatPane'
import type { SendRequest } from './components/ChatPane'
import { FilesPanel } from './components/FilesPanel'
import { Sidebar, StatusBar, TitleBar } from './components/Shell'
import type { Page } from './components/Shell'
import { TerminalPanel } from './components/TerminalPanel'
import { McpPage, MemoryPage, ModelsPage, SettingsPage, SkillsPage } from './pages/Pages'
import { ActivityPage } from './pages/ActivityPage'
import { RecipesPage } from './pages/RecipesPage'
import { ResearchPage } from './pages/ResearchPage'
import { ServicesPage } from './pages/ServicesPage'
import { SetupPage } from './pages/SetupPage'
import { uid } from './lib/api'
import { cancelActiveRun, runTurn } from './lib/engines'
import { useStatus } from './lib/status'
import { titleFrom, useSessions, useSettings } from './lib/store'
import { bridge } from './lib/types'
import type { AppInfo, Attachment, Message } from './lib/types'

type Running = { sessionId: string; messageId: string; controller: AbortController }

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
  const { settings, patch } = useSettings()
  const sessions = useSessions()
  const engine = settings.engine ?? 'agent'
  const status = useStatus(engine === 'nemoclaw')
  const [page, setPage] = useState<Page | 'setup'>('chat')
  const [running, setRunning] = useState<Running | null>(null)
  const runningRef = useRef<Running | null>(null)
  const [attachments, setAttachments] = useState<Attachment[]>([])
  const [focusSignal, setFocusSignal] = useState(0)
  // Below these widths the sidebar and files panel open over the content instead of beside it.
  const narrowSidebar = useNarrow('(max-width: 860px)')
  const narrowFiles = useNarrow('(max-width: 1100px)')
  const [overlay, setOverlay] = useState<'sidebar' | 'files' | null>(null)
  const [info, setInfo] = useState<AppInfo | null>(null)
  const [loginItem, setLoginItemState] = useState(false)

  useEffect(() => {
    const desktop = bridge()
    if (!desktop) return
    void desktop.info().then((next) => { setInfo(next); setLoginItemState(next.loginItem) })
    // First launch, or a setup that stopped part-way (for example for a Windows restart).
    void desktop.setup.status().then((setup) => { if (setup.needsSetup || setup.pending) setPage('setup') })
  }, [])
  const setLoginItem = (enabled: boolean) => { void bridge()?.setLoginItem(enabled).then(setLoginItemState) }
  const active = sessions.sessions.find((session) => session.id === sessions.activeId) ?? null

  const newChat = useCallback(() => {
    sessions.create()
    setPage('chat')
    setAttachments([])
    setFocusSignal((value) => value + 1)
  }, [sessions])

  const chooseFolder = useCallback(async () => {
    const desktop = bridge()
    if (!desktop) return
    const folder = await desktop.workspace.choose()
    if (folder) patch({ workspace: folder, files: true })
  }, [patch])

  const toggle = useCallback((panel: 'sidebar' | 'files' | 'terminal') => {
    if ((panel === 'sidebar' && narrowSidebar) || (panel === 'files' && narrowFiles)) { setOverlay((current) => current === panel ? null : panel); return }
    if (panel === 'sidebar') patch({ sidebar: settings.sidebar === false })
    if (panel === 'files') patch({ files: settings.files === false })
    if (panel === 'terminal') patch({ terminal: !settings.terminal })
  }, [patch, settings.sidebar, settings.files, settings.terminal, narrowSidebar, narrowFiles])

  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (!event.ctrlKey || event.altKey) return
      const key = event.key.toLowerCase()
      if (key === 'n' && !event.shiftKey) { event.preventDefault(); newChat() }
      else if (key === 'b' && !event.shiftKey) { event.preventDefault(); toggle('sidebar') }
      else if ((key === 'j' || key === '`') && !event.shiftKey) { event.preventDefault(); toggle('terminal') }
      else if (key === 'e' && event.shiftKey) { event.preventDefault(); toggle('files') }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [newChat, toggle])

  const send = async ({ prompt, attachments: files }: SendRequest) => {
    if (runningRef.current) return
    const sessionId = active?.id ?? sessions.create()
    const history = active?.messages ?? []
    const now = Date.now()
    const user: Message = { id: uid(), role: 'user', content: prompt, createdAt: now, engine, attachments: files }
    const reply: Message = { id: uid(), role: 'assistant', content: '', createdAt: now, engine, status: 'streaming' }
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
        engine,
        sessionId,
        messageId: reply.id,
        history,
        prompt,
        attachments: files,
        signal: controller.signal,
        patch: patchReply,
        chatModel: settings.chatModel,
        clawModel: settings.clawModel,
        agentPermission: settings.agentPermission ?? 'auto-review',
        clawPermission: settings.clawPermission ?? 'ask',
        workspacePath: settings.workspace && settings.useWorkspaceForAgent !== false ? settings.workspace : undefined,
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
      if (!stopped && engine === 'openclaw') void status.refreshClaw(true)
    } finally {
      runningRef.current = null
      setRunning(null)
      void status.refreshState()
    }
  }

  const stop = () => {
    runningRef.current?.controller.abort()
    void cancelActiveRun()
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

  const openPage = (next: 'skills' | 'mcp') => setPage(next)
  const sidebarOverlay = narrowSidebar && overlay === 'sidebar'
  const filesOverlay = narrowFiles && overlay === 'files' && page === 'chat'
  const showSidebar = narrowSidebar ? sidebarOverlay : settings.sidebar !== false
  const showFiles = page === 'chat' && (narrowFiles ? filesOverlay : settings.files !== false)
  const sidebarInGrid = showSidebar && !sidebarOverlay
  const filesInGrid = showFiles && !filesOverlay
  const showTerminal = Boolean(settings.terminal)

  return (
    <div className={`shell${sidebarInGrid ? '' : ' no-sidebar'}${filesInGrid ? '' : ' no-files'}${showTerminal ? ' has-terminal' : ''}`}>
      <TitleBar settings={{ ...settings, sidebar: showSidebar, files: showFiles }} onToggle={toggle} onChooseFolder={() => void chooseFolder()} />
      {showSidebar && (
        <Sidebar overlay={sidebarOverlay} sessions={sessions.sessions} activeId={sessions.activeId} page={page === 'setup' ? 'settings' : page} running={running} status={status}
          onSelect={(id) => { sessions.setActiveId(id); setPage('chat'); setOverlay(null) }} onNew={() => { newChat(); setOverlay(null) }} onDelete={deleteSession} onPage={(next) => { setPage(next); setOverlay(null) }} />
      )}
      {(sidebarOverlay || filesOverlay) && <button type="button" className="overlay-backdrop" aria-label="Close panel" onClick={() => setOverlay(null)} />}
      <main className="main" id="main">
        {page === 'chat' && (status.backend.phase === 'starting' || status.backend.phase === 'stopped' || status.backend.phase === 'failed') && (
          <div className={`banner${status.backend.phase === 'starting' ? '' : ' banner--error'}`} role="status">
            <span>{status.backend.phase === 'starting' ? `Starting services… ${status.services.filter((item) => item.status === 'running').length} of ${status.services.filter((item) => item.available).length} running` : status.backend.detail}</span>
            <button type="button" className="link-button" onClick={() => setPage('services')}>Services</button>
          </div>
        )}
        {sessions.saveError && <div className="banner banner--error" role="alert"><span>Chats could not be saved: {sessions.saveError}</span></div>}
        {page === 'chat' && (
          <ChatPane session={active} running={running} status={status} settings={settings} patchSettings={patch} onSend={send} onStop={stop}
            onChangeMessage={changeMessage} onChooseFolder={() => void chooseFolder()} onOpenPage={openPage}
            pendingAttachments={attachments} setPendingAttachments={setAttachments} focusSignal={focusSignal} />
        )}
        {page === 'skills' && <SkillsPage status={status} />}
        {page === 'mcp' && <McpPage status={status} />}
        {page === 'models' && <ModelsPage status={status} />}
        {page === 'memory' && <MemoryPage />}
        {page === 'settings' && <SettingsPage status={status} info={info} onOpen={(next) => setPage(next)} />}
        {page === 'recipes' && <RecipesPage />}
        {page === 'activity' && <ActivityPage status={status} />}
        {page === 'research' && <ResearchPage />}
        {page === 'services' && <ServicesPage status={status} settings={settings} patchSettings={patch} loginItem={loginItem} setLoginItem={setLoginItem} />}
        {page === 'setup' && <SetupPage onDone={() => setPage('chat')} />}
      </main>
      {showFiles && (
        <FilesPanel overlay={filesOverlay} workspace={settings.workspace} onChooseFolder={() => void chooseFolder()}
          onAttach={(file) => setAttachments((previous) => [...previous, { name: file.name, kind: 'document', text: file.text, size: file.size }])} />
      )}
      {showTerminal && <TerminalPanel workspace={settings.workspace} onClose={() => patch({ terminal: false })} />}
      <StatusBar status={status} version={info?.version ?? '0.1.0'} onOpenServices={() => setPage('services')} />
    </div>
  )
}
