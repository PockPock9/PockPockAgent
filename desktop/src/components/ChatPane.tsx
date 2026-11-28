// The conversation and its composer: engine, permission and model pickers, attachments,
// workspace context, and the skill/MCP link approval flow.
import { useEffect, useLayoutEffect, useRef, useState } from 'react'
import type { KeyboardEvent } from 'react'
import { ArrowDown, ArrowUp, FileText, Folder, Image as ImageIcon, LoaderCircle, Monitor, NotebookPen, PanelRight, Puzzle, Shield, Sparkles, Square, X } from 'lucide-react'
import type { Status } from '../lib/status'
import { hasFailedCard } from '../lib/runState'
import { ENGINE_LABEL } from '../lib/types'
import type { AppState, Attachment, Engine, Message, Session, Settings } from '../lib/types'
import { ExtensionCard, inspectLink, linkFromMessage } from './ExtensionCard'
import type { Proposal } from './ExtensionCard'
import { MessageView } from './MessageView'
import { ModelPicker, PermissionPicker, PlusMenu } from './Pickers'
import type { Menu } from './Pickers'
import { ReportDialog } from './ReportDialog'
import { RunBar } from './RunBar'
import { Dot } from './ui'
import { sendRunNote } from '../lib/engines'
import { uid } from '../lib/api'
import { computer } from '../lib/platform'
import { AGENT_PERMISSION, CLAW_PERMISSION } from '../lib/permissions'

const MAX_CLAW_CHARS = 16_000

export type SendRequest = { prompt: string; attachments: Attachment[] }

type Props = {
  session: Session | null
  running: { sessionId: string; messageId: string } | null
  status: Status
  settings: Settings
  patchSettings: (change: Partial<Settings>) => void
  onSend: (request: SendRequest) => Promise<void> | void
  onStop: () => void
  onChangeMessage: (message: Message) => void
  onChooseFolder: () => void
  onOpenPage: (page: 'skills' | 'mcp' | 'maintenance') => void
  pendingAttachments: Attachment[]
  setPendingAttachments: (change: (previous: Attachment[]) => Attachment[]) => void
  focusSignal: number
  /** Sends the request behind an assistant turn again, optionally with another model. */
  onRetry: (message: Message, model?: string) => void
  /** A failed agent run: plan the remaining steps again from step N (a new turn). */
  onRetryFrom: (message: Message, step: number) => void
  /** Changes one message of this task in place (notes). */
  onPatchMessage: (messageId: string, change: (message: Message) => Message) => void
  /** The smallest enabled local model smaller than the one a turn used, for the slow run bar. */
  smallerModel: (message: Message) => string | undefined
  onOpenServices: () => void
  inspectorOpen: boolean
  onToggleInspector: () => void
}

function readinessError(engine: Engine, status: Status, settings: Settings, state: AppState | null): string {
  if (status.backend.phase !== 'ready') return status.backend.detail
  if (engine === 'chat' || engine === 'agent') {
    if (!state) return 'The PockPock backend is not answering.'
    if (!state.router_enabled) return 'The Smart Router is paused. Start it in Settings.'
    // A chat with a chosen cloud model needs nothing from Ollama. The agent still does: it classifies the task locally.
    const cloudChat = engine === 'chat' && Boolean(state.cloud_models?.some((model) => model.name === settings.chatModel))
    if (!state.connected && !cloudChat) return 'Ollama is not running. Start it in Settings.'
  }
  if (engine === 'openclaw') {
    if (!status.claw?.ready) return status.claw?.detail ? `OpenClaw is not ready: ${status.claw.detail}` : 'OpenClaw is still being checked.'
    if (!['full', 'full-auto'].includes(settings.clawPermission ?? 'ask') && !status.claw.plugin) return 'The PockPock permission plugin is not loaded in OpenClaw, so approvals cannot be enforced. Reinstall it or choose Full access.'
  }
  return ''
}

export function ChatPane(props: Props) {
  const { session, running, status, settings, patchSettings, onSend, onStop, onChangeMessage, onChooseFolder, onOpenPage, pendingAttachments, setPendingAttachments, focusSignal, onRetry, onRetryFrom, onPatchMessage, smallerModel, onOpenServices, inspectorOpen, onToggleInspector } = props
  const engine: Engine = settings.engine ?? 'agent'
  const clawPermission = settings.clawPermission ?? 'ask'
  const agentPermission = settings.agentPermission ?? 'auto-review'
  const [draft, setDraft] = useState('')
  const [menu, setMenu] = useState<Menu>(null)
  const imageRef = useRef<HTMLInputElement>(null)
  const [reporting, setReporting] = useState<Message | null>(null)
  const [error, setError] = useState('')
  const [uploading, setUploading] = useState(false)
  const [proposal, setProposal] = useState<Proposal | null>(null)
  const [inspecting, setInspecting] = useState(false)
  const [atBottom, setAtBottom] = useState(true)
  const listRef = useRef<HTMLDivElement>(null)
  const inputRef = useRef<HTMLTextAreaElement>(null)
  const fileRef = useRef<HTMLInputElement>(null)
  const busy = Boolean(running)
  const runningHere = running && session && running.sessionId === session.id
  const messages = session?.messages ?? []
  const last = messages.at(-1)
  const lastReply = [...messages].reverse().find((message) => message.role === 'assistant')
  // While an approved PockPock Agent run works in this task, the composer sends notes to it.
  const noteMode = Boolean(runningHere && lastReply && running?.messageId === lastReply.id && lastReply.engine === 'agent' && lastReply.plan?.status === 'approved' && !lastReply.plan.sequence && lastReply.status === 'streaming')

  useEffect(() => { inputRef.current?.focus() }, [focusSignal, session?.id])

  // Stay pinned to the newest message while the reader is at the bottom.
  useLayoutEffect(() => {
    const list = listRef.current
    if (list && atBottom) list.scrollTop = list.scrollHeight
  }, [messages.length, last?.content, last?.steps?.length, last?.approvals?.length, last?.plan?.status, proposal, atBottom])
  useEffect(() => { setAtBottom(true) }, [session?.id])

  useLayoutEffect(() => {
    const input = inputRef.current
    if (!input) return
    input.style.height = 'auto'
    input.style.height = `${Math.min(input.scrollHeight, 260)}px`
  }, [draft])

  const upload = async (files: FileList | File[]) => {
    if (!files.length) return
    setUploading(true)
    setError('')
    const form = new FormData()
    Array.from(files).forEach((file) => form.append('files', file))
    try {
      const response = await fetch('/api/files', { method: 'POST', body: form })
      const result = await response.json() as { files?: Attachment[]; detail?: string }
      if (!response.ok) throw new Error(result.detail || 'Upload failed.')
      setPendingAttachments((previous) => [...previous, ...(result.files ?? [])])
    } catch (uploadError) {
      setError(uploadError instanceof Error ? uploadError.message : 'Upload failed.')
    } finally {
      setUploading(false)
      if (fileRef.current) fileRef.current.value = ''
    }
  }

  const preview = async (url: string, prefer?: 'skills' | 'mcp', quiet = false) => {
    setInspecting(true)
    setError('')
    try {
      setProposal(await inspectLink(url, prefer))
      return true
    } catch (inspectError) {
      if (quiet) return false
      setError(inspectError instanceof Error ? inspectError.message : 'Could not read that link.')
      return true
    } finally {
      setInspecting(false)
    }
  }

  const sendNote = async () => {
    const text = draft.trim()
    if (!text || !lastReply) return
    const id = uid()
    const replyId = lastReply.id
    setDraft('')
    onPatchMessage(replyId, (message) => ({ ...message, notes: [...(message.notes ?? []), { id, text, status: 'sending' }] }))
    const mark = (status: 'queued' | 'failed', error?: string) => onPatchMessage(replyId, (message) => ({ ...message, notes: message.notes?.map((note) => note.id === id ? { ...note, status: note.status === 'given' ? note.status : status, error } : note) }))
    try { await sendRunNote(text); mark('queued') } catch (reason) { mark('failed', reason instanceof Error ? reason.message : 'The note was not sent.') }
  }

  const send = async () => {
    if (noteMode) { await sendNote(); return }
    const prompt = draft.trim()
    if (busy || uploading || inspecting || (!prompt && !pendingAttachments.length)) return
    setError('')
    const link = !pendingAttachments.length ? linkFromMessage(prompt) : null
    if (link && engine !== 'chat' && await preview(link.url, undefined, !link.explicit)) { setDraft(''); return }
    // Right after launch the first status poll may not have returned yet; ask now instead.
    const state = status.state ?? (status.backend.phase === 'ready' ? await status.refreshState() : null)
    // A not-ready engine may have come up since the last check (a sandbox loading its model, a
    // gateway just started), so check again before refusing.
    let fresh = status
    if (engine === 'openclaw' && !status.claw?.ready) fresh = { ...status, claw: await status.refreshClaw(true) }
    const problem = readinessError(engine, fresh, settings, state)
    if (problem) { setError(problem); return }
    if (engine === 'openclaw' && pendingAttachments.some((file) => file.kind === 'image')) {
      setError(`${ENGINE_LABEL[engine]} accepts text and documents only. Remove the image or switch to Chat.`)
      return
    }
    const size = prompt.length + pendingAttachments.reduce((total, file) => total + (file.text?.length ?? 0) + 40, 0)
    if (engine === 'openclaw' && size > MAX_CLAW_CHARS) {
      setError(`${ENGINE_LABEL[engine]} messages are limited to ${MAX_CLAW_CHARS.toLocaleString()} characters including attached files.`)
      return
    }
    setDraft('')
    setAtBottom(true)
    await onSend({ prompt, attachments: pendingAttachments })
  }

  const onKeyDown = (event: KeyboardEvent<HTMLTextAreaElement>) => {
    if (event.key === 'Enter' && !event.shiftKey && !event.nativeEvent.isComposing) { event.preventDefault(); void send() }
  }

  const chooseEngine = (next: Engine) => {
    patchSettings({ engine: next })
    setMenu(null)
    if (next === 'openclaw' && !status.claw?.ready) void status.refreshClaw(true)
  }

  // Embedding models (nomic-embed-text, used for tool retrieval) cannot chat, so they are not offered.
  const models = (status.state?.models ?? []).filter((model) => model.enabled && !model.embedding).map((model) => model.name)
  // Cloud models are named "<provider>/<model id>"; the menus show the model id and the provider.
  const cloudModels = status.state?.cloud_models ?? []
  const cloudNames = new Set(cloudModels.map((model) => model.name))
  const cloudTitle = (name: string) => name.slice(name.indexOf('/') + 1)
  const clawAll = status.claw?.models ?? []
  const chatModelKnown = settings.chatModel && settings.chatModel !== 'auto' && (models.includes(settings.chatModel) || cloudNames.has(settings.chatModel))
  const shortName = (name: string) => (cloudNames.has(name) ? cloudTitle(name) : name)
  const modelLabel = engine === 'openclaw'
    ? (settings.clawModel && clawAll.includes(settings.clawModel) ? shortName(settings.clawModel) : `${status.claw?.model?.replace('ollama/', '') || 'Default'}`)
    : `${chatModelKnown ? shortName(settings.chatModel as string) : 'Smart route'}${engine === 'agent' && settings.agentPlanner ? ` · steps planned by ${shortName(settings.agentPlanner)}` : ''}`
  const folderName = settings.workspace?.split(/[\\/]/).filter(Boolean).at(-1)
  const engineTone = engine === 'openclaw' ? (status.claw?.ready ? 'ok' : 'off') : (status.state?.connected ? 'ok' : 'off')

  const lastLive = Boolean(runningHere && lastReply && running?.messageId === lastReply.id)
  const permissionTitle = engine === 'openclaw' ? CLAW_PERMISSION[clawPermission].title : engine === 'agent' ? AGENT_PERMISSION[agentPermission].title : ''
  const riskyPermission = engine === 'openclaw' ? clawPermission === 'full' : engine === 'agent' && agentPermission === 'full-access'
  const smaller = lastReply && lastLive && (lastReply.engine === 'chat' || lastReply.engine === 'agent') ? smallerModel(lastReply) : undefined
  const ENGINES: Engine[] = ['chat', 'agent', 'openclaw']
  const engineUnavailable = (item: Engine) => (item === 'openclaw' && status.claw ? !status.claw.available : false)

  return (
    <div className="chat">
      <header className="chat__head">
        <div className="chat__title">
          <h1 title={session?.title}>{session?.messages.length ? session.title : 'New task'}</h1>
          <p>{ENGINE_LABEL[engine]} · {settings.workspace ? <span className="mono" title={settings.workspace}>{settings.workspace}</span> : `This ${computer}`}</p>
        </div>
        <div className="segmented" role="radiogroup" aria-label="Engine">
          {ENGINES.map((item) => (
            <button key={item} type="button" role="radio" aria-checked={engine === item} className={engine === item ? 'is-active' : ''} disabled={busy || engineUnavailable(item)}
              title={engineUnavailable(item) ? status.claw?.detail : undefined} onClick={() => chooseEngine(item)}>{ENGINE_LABEL[item]}</button>
          ))}
        </div>
        <button type="button" className={`button button--small${inspectorOpen ? ' is-pressed' : ''}`} aria-pressed={inspectorOpen} onClick={onToggleInspector} aria-label="Inspector" title="Context, files and terminal"><PanelRight size={14} /> <span className="chat__inspector-label">Inspector</span></button>
      </header>
      {lastReply && (
        <RunBar message={lastReply} live={lastLive} onStop={onStop} onOpenServices={onOpenServices}
          onRetry={!busy && !hasFailedCard(lastReply, lastLive) ? () => onRetry(lastReply) : undefined}
          onReport={hasFailedCard(lastReply, lastLive) ? undefined : () => setReporting(lastReply)}
          smallerModel={smaller} onSmaller={smaller ? () => onRetry(lastReply, smaller) : undefined} />
      )}
      <div ref={listRef} className="chat__scroll" onScroll={(event) => { const el = event.currentTarget; setAtBottom(el.scrollHeight - el.scrollTop - el.clientHeight < 80) }}
        onDragOver={(event) => event.preventDefault()} onDrop={(event) => { event.preventDefault(); void upload(event.dataTransfer.files) }}>
        <div className="chat__thread">
          {!messages.length && !proposal && (
            <div className="welcome">
              <h1>What are we building?</h1>
              <p>{engine === 'chat' ? 'Chat answers directly with the best local model.'
                : engine === 'agent' ? 'PockPock Agent plans the task, shows you the plan, then runs its tools inside the task folder.'
                  : `OpenClaw runs on this ${computer} with no sandbox, using your skills and MCP servers. The permission setting controls what it may do without asking.`}</p>
              <div className="welcome__tips">
                <button type="button" onClick={() => { setDraft('Summarize the files in this folder and suggest what to work on next.'); inputRef.current?.focus() }}><Folder size={14} /> Explore the open folder</button>
                <button type="button" onClick={() => { setDraft('Research '); inputRef.current?.focus() }}><Sparkles size={14} /> Research a topic</button>
                <button type="button" onClick={() => onOpenPage('skills')}><Puzzle size={14} /> Add a skill from GitHub</button>
              </div>
            </div>
          )}
          {messages.map((message) => (
            <MessageView key={message.id} message={message} live={Boolean(runningHere && running?.messageId === message.id)} onChange={onChangeMessage}
              onReport={message.role === 'assistant' ? () => setReporting(message) : undefined}
              onRetry={message.role === 'assistant' && !busy ? () => onRetry(message) : undefined}
              onRetryFrom={message.role === 'assistant' && message.engine === 'agent' && !busy ? (step) => onRetryFrom(message, step) : undefined}
              permissionLabel={message.engine === 'openclaw' ? CLAW_PERMISSION[clawPermission].title : message.engine === 'agent' ? AGENT_PERMISSION[agentPermission].title : undefined} />
          ))}
          {proposal && (
            <ExtensionCard key={proposal.id} proposal={proposal} onClose={() => { setProposal(null); void status.refreshCounts() }} onSwitch={(kind) => void preview(proposal.source, kind)} onOpen={(url) => void preview(url, 'mcp')} onInstalled={() => void status.refreshCounts()} />
          )}
        </div>
      </div>
      {!atBottom && <button type="button" className="scroll-down" onClick={() => { setAtBottom(true) }} aria-label="Scroll to newest"><ArrowDown size={15} /></button>}

      <div className="composer-wrap">
        {error && <div className="banner banner--error" role="alert"><span>{error}</span><button type="button" className="icon-button icon-button--small" onClick={() => setError('')} aria-label="Dismiss"><X size={13} /></button></div>}
        <div className="context-chips">
          <span className="context-chip"><Monitor size={13} /> This {computer}</span>
          <button type="button" className="context-chip" onClick={onChooseFolder} title={settings.workspace || 'Open a folder'}><Folder size={13} /> {folderName || 'Open folder'}</button>
          {permissionTitle && <span className={`context-chip${riskyPermission ? ' context-chip--warn' : ''}`}><Shield size={13} /> {permissionTitle}</span>}
          <span className="context-chip"><Dot tone={engineTone} /> Mode: {ENGINE_LABEL[engine]} · {engineTone === 'ok' ? 'ready' : 'not ready'}</span>
        </div>
        <div className={`composer${busy ? ' is-busy' : ''}`}>
          {pendingAttachments.length > 0 && (
            <div className="chips chips--composer">
              {pendingAttachments.map((file, index) => (
                <span className="chip" key={`${file.name}-${index}`}>{file.kind === 'image' ? <ImageIcon size={12} /> : <FileText size={12} />}{file.name}
                  <button type="button" onClick={() => setPendingAttachments((previous) => previous.filter((_, position) => position !== index))} aria-label={`Remove ${file.name}`}><X size={11} /></button>
                </span>
              ))}
            </div>
          )}
          <textarea ref={inputRef} className="composer__input" rows={1} value={draft} onChange={(event) => setDraft(event.target.value)} onKeyDown={onKeyDown}
            placeholder={noteMode ? 'Add a note while it works. It joins the plan at the next step.' : engine === 'chat' ? 'Ask anything' : 'Describe a task, or paste a skill or MCP link'} aria-label={noteMode ? 'Note for the running task' : 'Message'} />
          <div className="composer__bar">
            <div className="composer__left">
              <PlusMenu menu={menu} onToggle={setMenu} busy={uploading} counts={status.counts ?? undefined} workspace={settings.workspace}
                onAttach={() => fileRef.current?.click()} onImage={() => imageRef.current?.click()} onChooseFolder={onChooseFolder} onOpenPage={onOpenPage} />
              <PermissionPicker menu={menu} onToggle={setMenu} engine={engine} settings={settings} status={status} patchSettings={patchSettings} />
            </div>
            <div className="composer__right">
              {noteMode && <span className="composer__note"><NotebookPen size={13} aria-hidden="true" /> Notes join at the next step</span>}
              <ModelPicker menu={menu} onToggle={setMenu} engine={engine} settings={settings} status={status} patchSettings={patchSettings} label={modelLabel} />
              {noteMode
                ? <>
                  <button type="button" className="send" onClick={() => void sendNote()} disabled={!draft.trim()} aria-label="Send note" title="Send the note (Enter)"><ArrowUp size={16} /></button>
                  <button type="button" className="send send--stop" onClick={onStop} aria-label="Stop"><Square size={12} /></button>
                </>
                : busy && runningHere
                ? <button type="button" className="send send--stop" onClick={onStop} aria-label="Stop"><Square size={12} /></button>
                : <button type="button" className="send" onClick={() => void send()} disabled={busy || uploading || inspecting || (!draft.trim() && !pendingAttachments.length)} aria-label={busy ? 'Another task is running' : 'Send'} title={busy ? 'Another chat is still working' : 'Send (Enter)'}>
                  {inspecting ? <LoaderCircle size={15} className="spin" /> : <ArrowUp size={16} />}
                </button>}
            </div>
          </div>
        </div>
        <input ref={fileRef} type="file" multiple hidden accept=".pdf,.docx,.xlsx,.pptx,.txt,.md,.csv,.json,.xml,.html,.log,.py,.ts,.tsx,.js" onChange={(event) => void upload(event.target.files ?? [])} />
        <input ref={imageRef} type="file" multiple hidden accept="image/png,image/jpeg" onChange={(event) => void upload(event.target.files ?? [])} />
      </div>
      {reporting && session && <ReportDialog session={session} message={reporting} onClose={() => setReporting(null)} onOpenMaintenance={() => { setReporting(null); onOpenPage('maintenance') }} />}
    </div>
  )
}
