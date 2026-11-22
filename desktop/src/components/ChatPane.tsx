// The conversation and its composer: engine, permission and model pickers, attachments,
// workspace context, and the skill/MCP link approval flow.
import { useEffect, useLayoutEffect, useRef, useState } from 'react'
import type { KeyboardEvent } from 'react'
import { ArrowDown, ArrowUp, Box, Bot, ChevronDown, Cloud, FileText, Folder, Image as ImageIcon, LoaderCircle, MessageSquare, Monitor, PanelRight, Paperclip, Plug, Plus, Puzzle, Shield, Sparkles, Square, Terminal, X } from 'lucide-react'
import type { Status } from '../lib/status'
import { ENGINE_LABEL } from '../lib/types'
import type { AgentPermission, AppState, Attachment, ClawPermission, Engine, Message, NemoRoute, Session, Settings } from '../lib/types'
import { getJson, sendJson } from '../lib/api'
import { ExtensionCard, inspectLink, linkFromMessage } from './ExtensionCard'
import type { Proposal } from './ExtensionCard'
import { EngineIcon, MessageView } from './MessageView'
import { ReportDialog } from './ReportDialog'
import { RunBar } from './RunBar'
import { Dot, MenuItem, Popover } from './ui'
import { computer, isMac } from '../lib/platform'
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
    if ((settings.clawPermission ?? 'ask') !== 'full' && !status.claw.plugin) return 'The PockPock permission plugin is not loaded in OpenClaw, so approvals cannot be enforced. Reinstall it or choose Full access.'
  }
  if (engine === 'nemoclaw' && !status.nemo?.ready) return status.nemoChecking ? 'The NemoClaw sandbox is still being checked.' : status.nemo?.detail || 'NemoClaw is not ready.'
  return ''
}

export function ChatPane(props: Props) {
  const { session, running, status, settings, patchSettings, onSend, onStop, onChangeMessage, onChooseFolder, onOpenPage, pendingAttachments, setPendingAttachments, focusSignal, onRetry, smallerModel, onOpenServices, inspectorOpen, onToggleInspector } = props
  const engine: Engine = settings.engine ?? 'agent'
  const clawPermission = settings.clawPermission ?? 'ask'
  const agentPermission = settings.agentPermission ?? 'auto-review'
  const [draft, setDraft] = useState('')
  const [menu, setMenu] = useState<'attach' | 'engine' | 'permission' | 'model' | null>(null)
  // NemoClaw's model belongs to its sandbox, not to a chat: it is read when NemoClaw is the engine
  // and changed with one call. `nemoBusy` is the model being switched to ('' = the local model).
  const [nemoRoute, setNemoRoute] = useState<NemoRoute | null>(null)
  const [nemoBusy, setNemoBusy] = useState<string | null>(null)
  const [nemoError, setNemoError] = useState('')
  const nemoEngine = settings.engine === 'nemoclaw'
  const nemoAvailable = status.nemo?.available === true
  useEffect(() => {
    if (!nemoEngine || !nemoAvailable) return
    let live = true
    getJson<NemoRoute>('/api/nemoclaw/model').then((route) => { if (live) setNemoRoute(route) }, () => undefined)
    return () => { live = false }
  }, [nemoEngine, nemoAvailable])
  const chooseNemoModel = async (name: string) => {
    setNemoBusy(name); setNemoError('')
    try { setNemoRoute(await sendJson<NemoRoute>('/api/nemoclaw/model', { model: name }, 'PUT')); setMenu(null) } catch (reason) { setNemoError(reason instanceof Error ? reason.message : 'The sandbox model could not be changed.') } finally { setNemoBusy(null) }
  }
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

  const send = async () => {
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
    if (engine === 'nemoclaw' && !status.nemo?.ready) fresh = { ...status, nemo: await status.refreshNemo(true, true), nemoChecking: false }
    if (engine === 'openclaw' && !status.claw?.ready) fresh = { ...status, claw: await status.refreshClaw(true) }
    const problem = readinessError(engine, fresh, settings, state)
    if (problem) { setError(problem); return }
    if ((engine === 'openclaw' || engine === 'nemoclaw') && pendingAttachments.some((file) => file.kind === 'image')) {
      setError(`${ENGINE_LABEL[engine]} accepts text and documents only. Remove the image or switch to Chat.`)
      return
    }
    const size = prompt.length + pendingAttachments.reduce((total, file) => total + (file.text?.length ?? 0) + 40, 0)
    if ((engine === 'openclaw' || engine === 'nemoclaw') && size > MAX_CLAW_CHARS) {
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
  const cloudDetail = (name: string) => cloudModels.find((model) => model.name === name)?.provider_label ?? 'Cloud'
  const clawAll = status.claw?.models ?? []
  const clawModels = clawAll.filter((name) => !cloudNames.has(name))
  const clawCloud = clawAll.filter((name) => cloudNames.has(name))
  const chatModelKnown = settings.chatModel && settings.chatModel !== 'auto' && (models.includes(settings.chatModel) || cloudNames.has(settings.chatModel))
  const shortName = (name: string) => (cloudNames.has(name) ? cloudTitle(name) : name)
  const modelLabel = engine === 'openclaw'
    ? (settings.clawModel && clawAll.includes(settings.clawModel) ? shortName(settings.clawModel) : `${status.claw?.model?.replace('ollama/', '') || 'Default'}`)
    : engine === 'nemoclaw' ? (nemoRoute?.cloud ? shortName(nemoRoute.model) : nemoRoute?.model || status.nemo?.model || 'Sandbox model')
      : chatModelKnown ? shortName(settings.chatModel as string) : 'Smart route'
  const folderName = settings.workspace?.split(/[\\/]/).filter(Boolean).at(-1)
  const engineTone = engine === 'openclaw' ? (status.claw?.ready ? 'ok' : 'off') : engine === 'nemoclaw' ? (status.nemoChecking ? 'busy' : status.nemo?.ready ? 'ok' : 'off') : (status.state?.connected ? 'ok' : 'off')

  const lastReply = [...messages].reverse().find((message) => message.role === 'assistant')
  const lastLive = Boolean(runningHere && lastReply && running?.messageId === lastReply.id)
  const smaller = lastReply && lastLive && (lastReply.engine === 'chat' || lastReply.engine === 'agent') ? smallerModel(lastReply) : undefined
  const ENGINES: Engine[] = ['chat', 'agent', 'openclaw', 'nemoclaw']
  const engineUnavailable = (item: Engine) => (item === 'openclaw' && status.claw ? !status.claw.available : item === 'nemoclaw' && status.nemo ? !status.nemo.available : false)

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
              title={engineUnavailable(item) ? (item === 'openclaw' ? status.claw?.detail : status.nemo?.detail) : undefined} onClick={() => chooseEngine(item)}>{ENGINE_LABEL[item]}</button>
          ))}
        </div>
        <button type="button" className={`button button--small${inspectorOpen ? ' is-pressed' : ''}`} aria-pressed={inspectorOpen} onClick={onToggleInspector} aria-label="Inspector" title="Context, files and terminal"><PanelRight size={14} /> <span className="chat__inspector-label">Inspector</span></button>
      </header>
      {lastReply && (
        <RunBar message={lastReply} live={lastLive} onStop={onStop} onOpenServices={onOpenServices}
          onRetry={!busy ? () => onRetry(lastReply) : undefined} onReport={() => setReporting(lastReply)}
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
                  : engine === 'openclaw' ? 'OpenClaw runs on this PC with no sandbox, using your skills and MCP servers. The permission setting controls what it may do without asking.'
                    : `NemoClaw runs OpenClaw inside a sandbox${isMac ? '' : ' in WSL'}. It cannot touch files or programs on this ${computer}.`}</p>
              <div className="welcome__tips">
                <button type="button" onClick={() => { setDraft('Summarize the files in this folder and suggest what to work on next.'); inputRef.current?.focus() }}><Folder size={14} /> Explore the open folder</button>
                <button type="button" onClick={() => { setDraft('Research '); inputRef.current?.focus() }}><Sparkles size={14} /> Research a topic</button>
                <button type="button" onClick={() => onOpenPage('skills')}><Puzzle size={14} /> Add a skill from GitHub</button>
              </div>
            </div>
          )}
          {messages.map((message) => (
            <MessageView key={message.id} message={message} live={Boolean(runningHere && running?.messageId === message.id)} onChange={onChangeMessage}
              onReport={message.role === 'assistant' ? () => setReporting(message) : undefined} />
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
          <span className="context-chip"><Dot tone={engineTone} /> {ENGINE_LABEL[engine]}</span>
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
            placeholder={engine === 'chat' ? 'Ask anything' : 'Describe a task, or paste a skill or MCP link'} aria-label="Message" />
          <div className="composer__bar">
            <div className="composer__left">
              <div className="anchor">
                <button type="button" className="icon-button" aria-label="Add context" title="Add context" data-popover-toggle={menu === 'attach' ? 'open' : undefined} onClick={() => setMenu(menu === 'attach' ? null : 'attach')} disabled={uploading}>
                  {uploading ? <LoaderCircle size={15} className="spin" /> : <Plus size={16} />}
                </button>
                <Popover open={menu === 'attach'} onClose={() => setMenu(null)}>
                  <MenuItem icon={<Paperclip size={14} />} title="Upload files…" detail="Documents or images" onSelect={() => { setMenu(null); fileRef.current?.click() }} />
                  <MenuItem icon={<Folder size={14} />} title={settings.workspace ? 'Change folder…' : 'Open folder…'} detail="Files panel and agent task folder" onSelect={() => { setMenu(null); onChooseFolder() }} />
                  <MenuItem icon={<Puzzle size={14} />} title="Skills…" detail="Add or switch skills" onSelect={() => { setMenu(null); onOpenPage('skills') }} />
                  <MenuItem icon={<Plug size={14} />} title="MCP servers…" detail="Connect tool servers" onSelect={() => { setMenu(null); onOpenPage('mcp') }} />
                </Popover>
              </div>
              <div className="anchor">
                <button type="button" className="pill" data-popover-toggle={menu === 'engine' ? 'open' : undefined} onClick={() => setMenu(menu === 'engine' ? null : 'engine')} aria-label={`Mode: ${ENGINE_LABEL[engine]}`}>
                  <EngineIcon engine={engine} size={13} /> {ENGINE_LABEL[engine]} <ChevronDown size={12} />
                </button>
                <Popover open={menu === 'engine'} onClose={() => setMenu(null)} className="popover--wide">
                  <div className="popover__label">Respond with</div>
                  <MenuItem icon={<MessageSquare size={14} />} title="Chat" detail="Direct answer from a local model. No tools." selected={engine === 'chat'} onSelect={() => chooseEngine('chat')} />
                  <div className="popover__label">Agent</div>
                  <MenuItem icon={<Bot size={14} />} title="PockPock Agent" detail="Plans first, then runs built-in tools in a task folder." selected={engine === 'agent'} onSelect={() => chooseEngine('agent')} />
                  <MenuItem icon={<Terminal size={14} />} title="OpenClaw" detail={status.claw && !status.claw.available ? status.claw.detail : 'On this PC, no sandbox. Uses your skills and MCP servers.'} selected={engine === 'openclaw'} disabled={Boolean(status.claw && !status.claw.available)} onSelect={() => chooseEngine('openclaw')} />
                  <MenuItem icon={<Box size={14} />} title="NemoClaw" detail={status.nemo && !status.nemo.available ? status.nemo.detail : `OpenClaw in a ${isMac ? 'Docker' : 'WSL'} sandbox. Cannot touch this ${computer}.`} selected={engine === 'nemoclaw'} disabled={Boolean(status.nemo && !status.nemo.available)} onSelect={() => chooseEngine('nemoclaw')} />
                </Popover>
              </div>
              {(engine === 'openclaw' || engine === 'agent') && (
                <div className="anchor">
                  <button type="button" className={`pill${(engine === 'openclaw' ? clawPermission === 'full' : agentPermission === 'full-access') ? ' pill--danger' : ''}`} data-popover-toggle={menu === 'permission' ? 'open' : undefined} onClick={() => setMenu(menu === 'permission' ? null : 'permission')} aria-label="Permission">
                    <Shield size={13} /> {engine === 'openclaw' ? CLAW_PERMISSION[clawPermission].title : AGENT_PERMISSION[agentPermission].title} <ChevronDown size={12} />
                  </button>
                  <Popover open={menu === 'permission'} onClose={() => setMenu(null)} className="popover--wide">
                    {engine === 'openclaw'
                      ? (Object.keys(CLAW_PERMISSION) as ClawPermission[]).map((key) => (
                        <MenuItem key={key} icon={<Shield size={14} />} title={CLAW_PERMISSION[key].title} detail={CLAW_PERMISSION[key].detail} danger={key === 'full'} selected={clawPermission === key}
                          disabled={key !== 'full' && status.claw?.plugin === false} onSelect={() => { patchSettings({ clawPermission: key }); setMenu(null) }} />
                      ))
                      : <>
                        {(Object.keys(AGENT_PERMISSION) as AgentPermission[]).map((key) => (
                          <MenuItem key={key} icon={<Shield size={14} />} title={AGENT_PERMISSION[key].title} detail={AGENT_PERMISSION[key].detail} danger={key === 'full-access'} selected={agentPermission === key} onSelect={() => { patchSettings({ agentPermission: key }); setMenu(null) }} />
                        ))}
                        <div className="popover__label">Task folder</div>
                        <MenuItem icon={<Folder size={14} />} title={settings.workspace ? `Work in ${folderName}` : 'Work in the open folder'} detail={settings.workspace ? 'The agent reads and edits files in this folder.' : 'Open a folder first.'} disabled={!settings.workspace}
                          selected={Boolean(settings.workspace && settings.useWorkspaceForAgent !== false)} onSelect={() => { patchSettings({ useWorkspaceForAgent: true }); setMenu(null) }} />
                        <MenuItem icon={<Folder size={14} />} title="Use a new temporary folder" detail="Each task gets an empty folder." selected={!settings.workspace || settings.useWorkspaceForAgent === false} onSelect={() => { patchSettings({ useWorkspaceForAgent: false }); setMenu(null) }} />
                      </>}
                  </Popover>
                </div>
              )}
            </div>
            <div className="composer__right">
              {(engine !== 'nemoclaw' || cloudModels.length > 0 || nemoRoute?.cloud) && (
                <div className="anchor">
                  <button type="button" className="pill pill--quiet" data-popover-toggle={menu === 'model' ? 'open' : undefined} onClick={() => setMenu(menu === 'model' ? null : 'model')} aria-label={`Model: ${modelLabel}`}>
                    <Sparkles size={13} /> <span className="pill__text">{modelLabel}</span> <ChevronDown size={12} />
                  </button>
                  <Popover open={menu === 'model'} onClose={() => setMenu(null)} align="right" className="popover--wide popover--scroll">
                    {engine === 'nemoclaw' ? <>
                      <div className="popover__label">Sandbox model · applies to every NemoClaw chat</div>
                      {nemoError && <div className="popover__note" role="alert">{nemoError}</div>}
                      <MenuItem icon={nemoBusy === '' ? <LoaderCircle size={14} className="spin" /> : <Bot size={14} />} title={nemoRoute?.local?.model || status.nemo?.model || 'Local model'} detail="On this PC" disabled={nemoBusy !== null} selected={nemoRoute ? !nemoRoute.cloud : true} onSelect={() => void chooseNemoModel('')} />
                      {cloudModels.length > 0 && <div className="popover__label">Cloud models · sent to the provider</div>}
                      {cloudModels.map((model) => (
                        <MenuItem key={model.name} icon={nemoBusy === model.name ? <LoaderCircle size={14} className="spin" /> : <Cloud size={14} />} title={cloudTitle(model.name)} detail={model.provider_label} disabled={nemoBusy !== null} selected={nemoRoute?.cloud === true && nemoRoute.model === model.name} onSelect={() => void chooseNemoModel(model.name)} />
                      ))}
                    </> : engine === 'openclaw' ? <>
                      <div className="popover__label">OpenClaw model · loads when used</div>
                      <MenuItem icon={<Sparkles size={14} />} title="Default" detail={status.claw?.model?.replace('ollama/', '') || 'OpenClaw default'} selected={!settings.clawModel || !clawAll.includes(settings.clawModel)} onSelect={() => { patchSettings({ clawModel: '' }); setMenu(null) }} />
                      {clawModels.filter((name) => `ollama/${name}` !== status.claw?.model && name !== status.claw?.model).map((name) => (
                        <MenuItem key={name} icon={<Bot size={14} />} title={name} selected={settings.clawModel === name} onSelect={() => { patchSettings({ clawModel: name }); setMenu(null) }} />
                      ))}
                      {clawCloud.length > 0 && <div className="popover__label">Cloud models · sent to the provider</div>}
                      {clawCloud.map((name) => (
                        <MenuItem key={name} icon={<Cloud size={14} />} title={cloudTitle(name)} detail={cloudDetail(name)} selected={settings.clawModel === name} onSelect={() => { patchSettings({ clawModel: name }); setMenu(null) }} />
                      ))}
                    </> : <>
                      <div className="popover__label">Local models · load when used</div>
                      <MenuItem icon={<Sparkles size={14} />} title="Smart route" detail="Pick a local model for each request" selected={!chatModelKnown} onSelect={() => { patchSettings({ chatModel: 'auto' }); setMenu(null) }} />
                      {models.map((name) => <MenuItem key={name} icon={<Bot size={14} />} title={name} selected={settings.chatModel === name} onSelect={() => { patchSettings({ chatModel: name }); setMenu(null) }} />)}
                      {cloudModels.length > 0 && <div className="popover__label">Cloud models · sent to the provider</div>}
                      {cloudModels.map((model) => (
                        <MenuItem key={model.name} icon={<Cloud size={14} />} title={cloudTitle(model.name)} detail={model.provider_label} selected={settings.chatModel === model.name} onSelect={() => { patchSettings({ chatModel: model.name }); setMenu(null) }} />
                      ))}
                    </>}
                  </Popover>
                </div>
              )}
              {busy && runningHere
                ? <button type="button" className="send send--stop" onClick={onStop} aria-label="Stop"><Square size={12} /></button>
                : <button type="button" className="send" onClick={() => void send()} disabled={busy || uploading || inspecting || (!draft.trim() && !pendingAttachments.length)} aria-label={busy ? 'Another task is running' : 'Send'} title={busy ? 'Another chat is still working' : 'Send (Enter)'}>
                  {inspecting ? <LoaderCircle size={15} className="spin" /> : <ArrowUp size={16} />}
                </button>}
            </div>
          </div>
        </div>
        <input ref={fileRef} type="file" multiple hidden accept="image/*,.pdf,.docx,.xlsx,.pptx,.txt,.md,.csv,.json,.xml,.html,.log,.py,.ts,.tsx,.js" onChange={(event) => void upload(event.target.files ?? [])} />
      </div>
      {reporting && session && <ReportDialog session={session} message={reporting} onClose={() => setReporting(null)} onOpenMaintenance={() => { setReporting(null); onOpenPage('maintenance') }} />}
    </div>
  )
}
