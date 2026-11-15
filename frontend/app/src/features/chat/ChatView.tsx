import { memo, useEffect, useRef, useState } from 'react'
import type { Dispatch, FormEvent, KeyboardEvent, SetStateAction } from 'react'
import { ArrowDown, ArrowUp, Bot, Box, Check, ChevronDown, CircleHelp, Copy, FileImage, FileSpreadsheet, FileText, FolderOpen, GitPullRequest, Globe2, MessageSquareText, Monitor, Plug, Plus, Puzzle, RefreshCw, Search, Shield, Sparkles, Terminal, Trash2, Upload, X, Zap } from 'lucide-react'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import type { PlanDecision } from '../agents/agentTypes'
import { formatBytes, modelFamily } from '../models/modelUtils'
import type { AppState } from '../models/modelTypes'
import { ExtensionProposalCard, extensionLinkFromMessage, inspectExtensionLink } from './AgentExtensions'
import type { ExtensionProposal } from './AgentExtensions'
import { AgentChecks, CodeBlock, RunTimeline, ThinkingIndicator } from './ChatTimeline'
import type { Attachment, ChatMessage, ClawStep, Conversation, PendingToolAction } from './chatTypes'
import { conversationTitle, copyText, createId, splitAgentReport } from './chatUtils'

const markdownComponents = { pre: CodeBlock }
const markdownPlugins = [remarkGfm]
const ChatMarkdown = memo(function ChatMarkdown({ content }: { content: string }) {
  return <ReactMarkdown remarkPlugins={markdownPlugins} components={markdownComponents}>{content}</ReactMarkdown>
})

type ResponseMode = 'chat' | 'agent' | 'nemoclaw' | 'openclaw'
/** Agent mode runs on one of three engines; the mode value doubles as the engine id. */
type AgentEngine = Exclude<ResponseMode, 'chat'>

const ENGINE_LABEL: Record<AgentEngine, string> = { agent: 'PockPock', openclaw: 'OpenClaw', nemoclaw: 'NemoClaw' }

const NEMOCLAW_MAX_CHARS = 16_000
const OPENCLAW_MAX_CHARS = 16_000

type OpenClawStatus = {
  available: boolean
  ready: boolean
  detail: string
  plugin?: boolean
  model?: string
  models?: string[]
}

type ClawPermission = 'ask' | 'auto' | 'full'

type ClawApproval = {
  id: string
  title: string
  description: string
  severity: string
  busy?: boolean
}

const CLAW_PERMISSION_LABEL: Record<ClawPermission, string> = {
  ask: 'Ask first',
  auto: 'Auto-approve safe',
  full: 'Full access',
}

function clawStepStatus(status: unknown): ClawStep['status'] {
  return status === 'completed' || status === 'blocked' || status === 'running' ? status : 'failed'
}

type NemoClawStatus = {
  available: boolean
  ready: boolean
  checked?: boolean
  detail: string
  sandbox?: string
  model?: string
  agent_version?: string
}

function eventTimestamp(event: { timeStamp: number }) {
  return Math.round(performance.timeOrigin + event.timeStamp)
}

function AttachmentGlyph({ name, kind }: { name: string; kind: Attachment['kind'] }) {
  if (kind === 'image') return <FileImage size={15} />
  if (/\.(xlsx?|csv)$/i.test(name)) return <FileSpreadsheet size={15} />
  return <FileText size={15} />
}

function FileChip({ attachment, onRemove }: { attachment: Attachment; onRemove?: () => void }) {
  return (
    <div className="file-chip">
      <AttachmentGlyph name={attachment.name} kind={attachment.kind} />
      <span>{attachment.name}<small>{formatBytes(attachment.size)}</small></span>
      {onRemove && <button onClick={onRemove} aria-label={`Remove ${attachment.name}`}><X size={13} /></button>}
    </div>
  )
}

export function ChatView({
  state,
  conversations,
  setConversations,
  activeId,
  setActiveId,
  newChat,
  toolBusy,
  onStopTool,
  onApproveToolAction,
  onPlanDecision,
  onClearAllChats,
  onOpenExtensions,
}: {
  state: AppState
  conversations: Conversation[]
  setConversations: Dispatch<SetStateAction<Conversation[]>>
  activeId: string
  setActiveId: (id: string) => void
  newChat: () => void
  toolBusy: boolean
  onStopTool: () => void
  onApproveToolAction: (action: PendingToolAction) => void
  onPlanDecision: (runId: string, decision: PlanDecision) => void
  onClearAllChats: () => void
  onOpenExtensions: (kind: 'skills' | 'mcp') => void
}) {
  const [draft, setDraft] = useState('')
  const [files, setFiles] = useState<Attachment[]>([])
  const [selectedModel, setSelectedModel] = useState('auto')
  const [agentMode, setAgentMode] = useState<ResponseMode>(() => {
    try {
      const saved = localStorage.getItem('frog-ai-chat-agent-mode')
      return saved === 'chat' || saved === 'nemoclaw' || saved === 'openclaw' ? saved : 'agent'
    } catch { return 'agent' }
  })
  // The engine Agent mode returns to after a visit to Chat mode.
  const [agentEngine, setAgentEngine] = useState<AgentEngine>(() => {
    try {
      const saved = localStorage.getItem('frog-ai-chat-agent-engine')
      return saved === 'nemoclaw' || saved === 'openclaw' ? saved : 'agent'
    } catch { return 'agent' }
  })
  const [extensionProposal, setExtensionProposal] = useState<ExtensionProposal | null>(null)
  const [inspecting, setInspecting] = useState(false)
  const [nemoclaw, setNemoclaw] = useState<NemoClawStatus | null>(null)
  const [nemoclawChecking, setNemoclawChecking] = useState(true)
  const [openclaw, setOpenclaw] = useState<OpenClawStatus | null>(null)
  const [openclawChecking, setOpenclawChecking] = useState(true)
  // OpenClaw runs on this PC without a sandbox, so its permission is kept apart from Agent mode's
  // and starts at the most cautious setting.
  const [clawPermission, setClawPermission] = useState<ClawPermission>(() => {
    try {
      const saved = localStorage.getItem('frog-ai-chat-openclaw-permission')
      return saved === 'auto' || saved === 'full' ? saved : 'ask'
    } catch { return 'ask' }
  })
  const [clawApprovals, setClawApprovals] = useState<ClawApproval[]>([])
  // The model OpenClaw uses for this browser's chats; empty means OpenClaw's own default.
  const [clawModel, setClawModel] = useState(() => {
    try { return localStorage.getItem('frog-ai-chat-openclaw-model') ?? '' } catch { return '' }
  })
  const [permissionMode, setPermissionMode] = useState<'default' | 'auto-review' | 'full-access'>(() => {
    try {
      const saved = localStorage.getItem('frog-ai-chat-permission-mode')
      return saved === 'default' || saved === 'full-access' ? saved : 'auto-review'
    } catch { return 'auto-review' }
  })
  const [workspacePath, setWorkspacePath] = useState('')
  const [choosingWorkspace, setChoosingWorkspace] = useState(false)
  const [agentToolsEnabled, setAgentToolsEnabled] = useState(true)
  const [openComposerMenu, setOpenComposerMenu] = useState<'attach' | 'mode' | 'engine' | 'permission' | 'model' | null>(null)
  // Close an open composer menu on any press outside it (or its own toggle), or on Escape.
  useEffect(() => {
    if (!openComposerMenu) return
    const onPointerDown = (event: PointerEvent) => {
      const target = event.target as Element | null
      if (target?.closest('.composer-popover, .composer [aria-expanded="true"]')) return
      setOpenComposerMenu(null)
    }
    const onKeyDown = (event: globalThis.KeyboardEvent) => {
      if (event.key === 'Escape') setOpenComposerMenu(null)
    }
    document.addEventListener('pointerdown', onPointerDown, true)
    document.addEventListener('keydown', onKeyDown)
    return () => {
      document.removeEventListener('pointerdown', onPointerDown, true)
      document.removeEventListener('keydown', onKeyDown)
    }
  }, [openComposerMenu])
  const [modelSearch, setModelSearch] = useState('')
  const [attachmentSearch, setAttachmentSearch] = useState('')
  const [sending, setSending] = useState(false)
  const [uploading, setUploading] = useState(false)
  const [error, setError] = useState('')
  const [dragging, setDragging] = useState(false)
  const [scrolled, setScrolled] = useState(false)
  const [notice, setNotice] = useState('')
  const [pendingToolAction, setPendingToolAction] = useState<PendingToolAction | null>(null)
  const listRef = useRef<HTMLDivElement>(null)
  const textareaRef = useRef<HTMLTextAreaElement>(null)
  const uploadRef = useRef<HTMLInputElement>(null)
  const abortRef = useRef<AbortController | null>(null)
  const conversation = conversations.find((item) => item.id === activeId)
  const messages = conversation?.messages ?? []
  const latestMessageContent = messages.at(-1)?.content
  const enabledModels = state.models.filter((model) => model.enabled)

  // Stay pinned to the newest message while the reader is at the bottom: covers opening a thread,
  // the chat page becoming visible, and replies growing as they stream. Scrolling up releases the pin.
  const stickToBottomRef = useRef(true)
  useEffect(() => {
    stickToBottomRef.current = true
    setScrolled(false)
  }, [activeId])
  useEffect(() => {
    const element = listRef.current
    if (!element) return
    const pin = () => {
      if (stickToBottomRef.current && element.clientHeight > 0) element.scrollTop = element.scrollHeight
      setScrolled(element.clientHeight > 0 && element.scrollHeight - element.scrollTop - element.clientHeight > 160)
    }
    const observer = new ResizeObserver(pin)
    observer.observe(element)
    const thread = element.querySelector('.chat-thread')
    if (thread) observer.observe(thread)
    pin()
    return () => observer.disconnect()
  }, [activeId, messages.length, latestMessageContent])

  useEffect(() => () => abortRef.current?.abort(), [])

  // The sandbox check makes NemoClaw test its model, which loads it into memory. `probe` false
  // only asks whether NemoClaw is installed, so opening the page does not load a model.
  const refreshNemoclaw = async (force = false, probe = true) => {
    setNemoclawChecking(true)
    try {
      const response = await fetch(`/api/nemoclaw/status${force ? '?refresh=1' : probe ? '' : '?probe=0'}`)
      const result = await response.json() as NemoClawStatus & { detail?: string }
      setNemoclaw(response.ok ? result : { available: false, ready: false, detail: result.detail || 'NemoClaw status is unavailable.' })
    } catch {
      setNemoclaw({ available: false, ready: false, detail: 'Could not reach the PockPock AI server to check NemoClaw.' })
    } finally {
      setNemoclawChecking(false)
    }
  }

  // eslint-disable-next-line react-hooks/exhaustive-deps -- runs once with the saved mode
  useEffect(() => { void refreshNemoclaw(false, agentMode === 'nemoclaw') }, [])

  const refreshOpenclaw = async (force = false) => {
    setOpenclawChecking(true)
    try {
      const response = await fetch(`/api/openclaw/status${force ? '?refresh=1' : ''}`)
      const result = await response.json() as OpenClawStatus & { detail?: string }
      setOpenclaw(response.ok ? result : { available: false, ready: false, detail: result.detail || 'OpenClaw status is unavailable.' })
    } catch {
      setOpenclaw({ available: false, ready: false, detail: 'Could not reach the PockPock AI server to check OpenClaw.' })
    } finally {
      setOpenclawChecking(false)
    }
  }

  useEffect(() => { void refreshOpenclaw() }, [])

  useEffect(() => {
    try { localStorage.setItem('frog-ai-chat-openclaw-model', clawModel) } catch { /* Keep the current selection for this chat if storage is unavailable. */ }
  }, [clawModel])
  // A saved model that OpenClaw no longer lists falls back to the default.
  const clawModels = openclaw?.models ?? []
  const activeClawModel = clawModel && clawModels.includes(clawModel) ? clawModel : ''

  useEffect(() => {
    try { localStorage.setItem('frog-ai-chat-openclaw-permission', clawPermission) } catch { /* Keep the current selection for this chat if storage is unavailable. */ }
  }, [clawPermission])

  const decideApproval = async (id: string, decision: 'allow-once' | 'deny') => {
    setClawApprovals((previous) => previous.map((item) => item.id === id ? { ...item, busy: true } : item))
    try {
      const response = await fetch('/api/openclaw/approvals', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ approval_id: id, decision }),
      })
      if (response.ok) return
      const result = await response.json().catch(() => ({})) as { detail?: unknown }
      setError(typeof result.detail === 'string' ? result.detail : 'OpenClaw did not accept that decision.')
      setClawApprovals((previous) => response.status === 404
        ? previous.filter((item) => item.id !== id)
        : previous.map((item) => item.id === id ? { ...item, busy: false } : item))
    } catch {
      setError('Could not reach the PockPock AI server to send your decision.')
      setClawApprovals((previous) => previous.map((item) => item.id === id ? { ...item, busy: false } : item))
    }
  }

  useEffect(() => {
    try { localStorage.setItem('frog-ai-chat-permission-mode', permissionMode) } catch { /* Keep the current selection for this chat if storage is unavailable. */ }
  }, [permissionMode])

  useEffect(() => {
    try { localStorage.setItem('frog-ai-chat-agent-mode', agentMode) } catch { /* Keep the current mode for this chat if storage is unavailable. */ }
  }, [agentMode])

  useEffect(() => {
    if (agentMode === 'chat') return
    setAgentEngine(agentMode)
    try { localStorage.setItem('frog-ai-chat-agent-engine', agentMode) } catch { /* Keep the current engine for this chat if storage is unavailable. */ }
  }, [agentMode])

  const chooseEngine = (engine: AgentEngine) => {
    setAgentMode(engine)
    setOpenComposerMenu(null)
    if (engine === 'agent') setAgentToolsEnabled(true)
    if (engine === 'nemoclaw' && !nemoclaw?.ready) void refreshNemoclaw(true)
    if (engine === 'openclaw' && !openclaw?.ready) void refreshOpenclaw(true)
  }

  // Shows the approval card for a skill or MCP link. Returns false when a quiet check found
  // nothing installable, so the caller can send the link to the agent as a normal message.
  const previewExtension = async (url: string, prefer?: 'skills' | 'mcp', quiet = false) => {
    setInspecting(true)
    setError('')
    try {
      setExtensionProposal(await inspectExtensionLink(url, prefer))
      setOpenComposerMenu(null)
      return true
    } catch (inspectError) {
      if (quiet) return false
      setError(inspectError instanceof Error ? inspectError.message : 'Could not read that link.')
      return true
    } finally {
      setInspecting(false)
    }
  }

  const updateConversation = (id: string, update: (current: Conversation) => Conversation) => {
    setConversations((previous) => previous.map((item) => item.id === id ? update(item) : item))
  }

  const upload = async (incoming: FileList | File[]) => {
    if (!incoming.length) return
    setUploading(true)
    setError('')
    const form = new FormData()
    Array.from(incoming).forEach((file) => form.append('files', file))
    try {
      const response = await fetch('/api/files', { method: 'POST', body: form })
      const result = await response.json()
      if (!response.ok) throw new Error(result.detail || 'File upload failed')
      setFiles((previous) => [...previous, ...result.files as Attachment[]])
    } catch (uploadError) {
      setError(uploadError instanceof Error ? uploadError.message : 'File upload failed')
    } finally {
      setUploading(false)
      if (uploadRef.current) uploadRef.current.value = ''
    }
  }

  const addClipboardImage = async () => {
    setOpenComposerMenu(null)
    try {
      if (!navigator.clipboard?.read) throw new Error('Clipboard image access is not available in this browser.')
      const items = await navigator.clipboard.read()
      for (const item of items) {
        const mime = item.types.find((type) => type.startsWith('image/'))
        if (!mime) continue
        const blob = await item.getType(mime)
        await upload([new File([blob], `clipboard-image.${mime.split('/')[1] || 'png'}`, { type: mime })])
        return
      }
      throw new Error('There is no image in the clipboard.')
    } catch (clipboardError) {
      setError(clipboardError instanceof Error ? clipboardError.message : 'Could not read an image from the clipboard.')
    }
  }

  const captureScreenshot = async () => {
    setOpenComposerMenu(null)
    try {
      if (!navigator.mediaDevices?.getDisplayMedia) throw new Error('Screen capture is not available in this browser.')
      const stream = await navigator.mediaDevices.getDisplayMedia({ video: true })
      try {
        const video = document.createElement('video')
        video.srcObject = stream
        await video.play()
        await new Promise<void>((resolve) => { if (video.videoWidth) resolve(); else video.onloadedmetadata = () => resolve() })
        const canvas = document.createElement('canvas')
        canvas.width = video.videoWidth
        canvas.height = video.videoHeight
        const context = canvas.getContext('2d')
        if (!context) throw new Error('Could not capture the selected screen.')
        context.drawImage(video, 0, 0)
        const image = await new Promise<Blob>((resolve, reject) => canvas.toBlob((blob) => blob ? resolve(blob) : reject(new Error('Could not encode the screenshot.')), 'image/png'))
        await upload([new File([image], 'screenshot.png', { type: 'image/png' })])
      } finally {
        stream.getTracks().forEach((track) => track.stop())
      }
    } catch (captureError) {
      if (captureError instanceof DOMException && captureError.name === 'AbortError') return
      setError(captureError instanceof Error ? captureError.message : 'Could not capture a screenshot.')
    }
  }

  const attachConversation = (selected: Conversation) => {
    const content = selected.messages.slice(-12).map((message) => `${message.role.toUpperCase()}\n${message.content}`).join('\n\n').slice(0, 80_000)
    setFiles((previous) => [...previous, { name: `session-${selected.title.replace(/[^a-z0-9_-]+/gi, '-').slice(0, 48) || selected.id}.txt`, kind: 'document', text: content, size: content.length }])
    setOpenComposerMenu(null)
  }

  const chooseAgentWorkspace = async () => {
    setChoosingWorkspace(true)
    setError('')
    try {
      const response = await fetch('/api/agents/pick-workspace', { method: 'POST' })
      const result = await response.json() as { path?: string; cancelled?: boolean; detail?: string }
      if (!response.ok) throw new Error(result.detail || 'Could not open the workspace folder picker.')
      if (!result.cancelled && result.path) setWorkspacePath(result.path)
    } catch (workspaceError) {
      setError(workspaceError instanceof Error ? workspaceError.message : 'Could not choose a workspace folder.')
    } finally {
      setChoosingWorkspace(false)
    }
  }

  const send = async (timestamp: number, event?: FormEvent, forceChat = false) => {
    event?.preventDefault()
    const taskText = draft.trim()
    if (sending || uploading || inspecting || (!taskText && files.length === 0)) return
    if (!forceChat && agentMode !== 'chat' && files.length === 0) {
      // A pasted skill or MCP link opens an approval card instead of going to the agent.
      const link = extensionLinkFromMessage(taskText)
      if (link && await previewExtension(link.url, undefined, !link.explicit)) {
        setDraft('')
        return
      }
    }
    const useNemoclaw = !forceChat && agentMode === 'nemoclaw'
    const useOpenclaw = !forceChat && agentMode === 'openclaw'
    const clawName = useOpenclaw ? 'OpenClaw' : 'NemoClaw'
    if (useNemoclaw || useOpenclaw) {
      const clawStatus = useOpenclaw ? openclaw : nemoclaw
      if (!clawStatus?.ready) {
        setError(clawStatus?.detail ? `${clawName} is not ready: ${clawStatus.detail}` : `${clawName} is still being checked. Try again in a moment.`)
        return
      }
      if (useOpenclaw && clawPermission !== 'full' && !openclaw?.plugin) {
        setError('The PockPock permission plugin is not loaded in OpenClaw, so approvals cannot be enforced. Reinstall it or choose Full access.')
        return
      }
      if (files.some((file) => file.kind === 'image')) {
        setError(`${clawName} mode accepts text and documents only. Remove images or switch to Chat mode.`)
        return
      }
      const outgoingChars = taskText.length + files.reduce((total, file) => total + (file.text?.length ?? 0) + file.name.length + 24, 0)
      const maxChars = useOpenclaw ? OPENCLAW_MAX_CHARS : NEMOCLAW_MAX_CHARS
      if (outgoingChars > maxChars) {
        setError(`${clawName} messages are limited to ${maxChars.toLocaleString()} characters including attached documents.`)
        return
      }
    } else if (!state.router_enabled) {
      setError('Smart Router is paused. Start it from the sidebar before sending.')
      return
    }
    if (!state.connected) {
      setError('Ollama is offline. Start Ollama before sending a message.')
      return
    }
    if (pendingToolAction && !forceChat) return
    if (!forceChat && agentMode === 'agent' && !agentToolsEnabled) {
      setError('Agent mode is selected but agent tools are off. Turn them on in Add context or switch to Chat mode.')
      return
    }
    if (!forceChat && agentMode === 'agent') {
      if (toolBusy) {
        setNotice('An agent run is still working in this thread. Continue it in a follow-up after it finishes.')
        return
      }
      const action: PendingToolAction = {
        target: 'agent',
        summary: 'The local planner will translate this request into an execution plan, select a tool-capable model, and run the available agent tools.',
        request: {
          id: createId().replaceAll('-', ''),
          task: taskText,
          sourceTask: taskText,
          conversationId: conversation?.id,
          permissionMode,
          workspacePath: workspacePath || undefined,
          preferredModel: selectedModel === 'auto' ? undefined : selectedModel,
          files: files.filter((file) => file.kind === 'document').map((file) => ({ name: file.name, text: file.text ?? '', size: file.size })),
        },
      }
      if (permissionMode === 'default') {
        setPendingToolAction(action)
        return
      }
      onApproveToolAction(action)
      setPendingToolAction(null)
      setDraft('')
      setFiles([])
      setWorkspacePath('')
      return
    }
    setPendingToolAction(null)
    let target = conversation
    if (!target) {
      target = { id: createId(), title: 'New conversation', updatedAt: timestamp, messages: [] }
      setConversations((previous) => [target!, ...previous])
      setActiveId(target.id)
    }

    const current = target
    const userMessage: ChatMessage = { role: 'user', content: taskText, attachments: files }
    const assistantMessage: ChatMessage = { role: 'assistant', content: '' }
    const outgoing = [...current.messages, userMessage]
    updateConversation(current.id, (item) => ({
      ...item,
      title: item.messages.length ? item.title : (conversationTitle(taskText) || files[0]?.name || 'Attachment review'),
      updatedAt: timestamp,
      messages: [...outgoing, assistantMessage],
    }))
    setDraft('')
    setFiles([])
    setError('')
    setSending(true)
    abortRef.current = new AbortController()
    const requestMessages = outgoing.map((message) => {
      const docs = message.attachments?.filter((attachment) => attachment.kind === 'document') ?? []
      const content = [
        message.content,
        ...docs.map((file) => `\n\n[Attached file: ${file.name}]\n${file.text ?? ''}`),
      ].filter(Boolean).join('\n')
      const result: { role: string; content: string; images?: string[] } = {
        role: message.role,
        content,
      }
      const images = message.attachments?.filter((attachment) => attachment.kind === 'image') ?? []
      if (images.length) result.images = images.map((image) => image.data ?? '').filter(Boolean)
      return result
    })
    let routedModel = ''
    let routedCategory = ''
    let pendingText = ''
    let flushTimer: number | undefined
    const flushTokens = () => {
      if (flushTimer !== undefined) {
        window.clearTimeout(flushTimer)
        flushTimer = undefined
      }
      if (!pendingText) return
      const text = pendingText
      pendingText = ''
      updateConversation(current.id, (item) => {
        const next = [...item.messages]
        const last = next.at(-1)
        if (last?.role === 'assistant') next[next.length - 1] = {
          ...last,
          content: last.content + text,
          model: routedModel,
          category: routedCategory,
        }
        return { ...item, updatedAt: Date.now(), messages: next }
      })
    }
    try {
      // NemoClaw and OpenClaw keep their own session history, so only the newest turn is sent.
      const response = useOpenclaw
        ? await fetch('/api/openclaw/chat', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          signal: abortRef.current.signal,
          body: JSON.stringify({ session_id: `pockpock-${current.id}`, message: requestMessages.at(-1)?.content ?? taskText, permission_mode: clawPermission, model: activeClawModel || undefined }),
        })
        : useNemoclaw
        ? await fetch('/api/nemoclaw/chat', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          signal: abortRef.current.signal,
          body: JSON.stringify({ session_id: `pockpock-${current.id}`, message: requestMessages.at(-1)?.content ?? taskText }),
        })
        : await fetch('/api/chat', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          signal: abortRef.current.signal,
          body: JSON.stringify({ messages: requestMessages, model: selectedModel }),
        })
      if (!response.ok) {
        const result = await response.json().catch(() => ({})) as { detail?: unknown }
        throw new Error(typeof result.detail === 'string' ? result.detail : `${useNemoclaw || useOpenclaw ? clawName : 'Chat'} request failed (${response.status})`)
      }
      if (!response.body) throw new Error('The local API did not open a response stream')
      const reader = response.body.getReader()
      const decoder = new TextDecoder()
      let buffer = ''

      const handleEvent = (data: string) => {
        if (!data) return
        let chunk: Record<string, unknown>
        try {
          chunk = JSON.parse(data)
        } catch (parseError) {
          console.error('Invalid local response event:', parseError)
          return
        }
        if (chunk.type !== 'token') flushTokens()
        if (chunk.type === 'token' && typeof chunk.content === 'string') {
          pendingText += chunk.content
          if (flushTimer === undefined) flushTimer = window.setTimeout(flushTokens, 50)
        } else if (chunk.type === 'decision') {
          routedModel = String(chunk.model || '')
          routedCategory = String(chunk.category || '')
          updateConversation(current.id, (item) => {
            const next = [...item.messages]
            const last = next.at(-1)
            if (last?.role === 'assistant') next[next.length - 1] = { ...last, model: routedModel, category: routedCategory }
            return { ...item, messages: next }
          })
        } else if (chunk.type === 'replace' && typeof chunk.content === 'string') {
          // OpenClaw sends the authoritative text after tool calls and at the end of the turn.
          const content = chunk.content
          updateConversation(current.id, (item) => {
            const next = [...item.messages]
            const last = next.at(-1)
            if (last?.role === 'assistant') next[next.length - 1] = { ...last, content, model: routedModel, category: routedCategory }
            return { ...item, updatedAt: Date.now(), messages: next }
          })
        } else if (chunk.type === 'tool' && typeof chunk.id === 'string') {
          const step: ClawStep = {
            id: chunk.id,
            title: String(chunk.title || chunk.name || 'Tool'),
            status: chunk.phase === 'start' ? 'running' : clawStepStatus(chunk.status),
            error: typeof chunk.error === 'string' ? chunk.error : undefined,
          }
          updateConversation(current.id, (item) => {
            const next = [...item.messages]
            const last = next.at(-1)
            if (last?.role !== 'assistant') return item
            const steps = [...(last.clawSteps ?? [])]
            const existing = steps.findIndex((entry) => entry.id === step.id)
            if (existing === -1) steps.push(step)
            else steps[existing] = step
            next[next.length - 1] = { ...last, clawSteps: steps.slice(-40) }
            return { ...item, messages: next }
          })
        } else if (chunk.type === 'approval' && typeof chunk.id === 'string') {
          const approval: ClawApproval = {
            id: chunk.id,
            title: String(chunk.title || 'Approval required'),
            description: String(chunk.description || ''),
            severity: String(chunk.severity || 'warning'),
          }
          setClawApprovals((previous) => previous.some((item) => item.id === approval.id) ? previous : [...previous, approval])
        } else if (chunk.type === 'approval_resolved' && typeof chunk.id === 'string') {
          const resolvedId = chunk.id
          setClawApprovals((previous) => previous.filter((item) => item.id !== resolvedId))
        } else if (chunk.type === 'approval_error') {
          setError(String(chunk.message || 'OpenClaw could not record that decision.'))
        } else if (chunk.type === 'done' && chunk.truncated === true) {
          setNotice('The NemoClaw reply was cut off at the model output limit. Ask it to continue.')
        } else if (chunk.type === 'error') {
          if (useNemoclaw) void refreshNemoclaw(true)
          if (useOpenclaw && chunk.code !== 'aborted') void refreshOpenclaw(true)
          const message = String(chunk.message || 'Chat request failed')
          setError(message)
          updateConversation(current.id, (item) => {
            const next = [...item.messages]
            const last = next.at(-1)
            if (last?.role === 'assistant' && !last.content) next[next.length - 1] = { ...last, content: message, error: true }
            return { ...item, messages: next }
          })
        }
      }
      while (true) {
        const { done, value } = await reader.read()
        buffer += decoder.decode(value, { stream: !done })
        const events = buffer.split('\n\n')
        buffer = events.pop() ?? ''
        for (const raw of events) {
          const data = raw.split('\n').filter((line) => line.startsWith('data:')).map((line) => line.slice(5).trimStart()).join('\n')
          handleEvent(data)
        }
        if (done) break
      }
    } catch (chatError) {
      flushTokens()
      if (chatError instanceof DOMException && chatError.name === 'AbortError') {
        setNotice('Generation stopped.')
      } else {
        const message = chatError instanceof Error ? chatError.message : 'Chat request failed'
        setError(message)
        updateConversation(current.id, (item) => {
          const next = [...item.messages]
          const last = next.at(-1)
          if (last?.role === 'assistant' && !last.content) next[next.length - 1] = { ...last, content: message, error: true }
          return { ...item, messages: next }
        })
      }
    } finally {
      flushTokens()
      abortRef.current = null
      setSending(false)
      if (useOpenclaw) {
        // The turn is over: nothing can still be approved, and no step is still running.
        setClawApprovals([])
        updateConversation(current.id, (item) => {
          const next = [...item.messages]
          const last = next.at(-1)
          if (last?.role !== 'assistant' || !last.clawSteps?.some((step) => step.status === 'running')) return item
          next[next.length - 1] = { ...last, clawSteps: last.clawSteps.map((step) => step.status === 'running' ? { ...step, status: 'stopped' } : step) }
          return { ...item, messages: next }
        })
      }
    }
  }

  const stop = () => abortRef.current?.abort()
  const clearAllChats = () => {
    if (!conversations.length || !window.confirm('Clear all saved chats from this browser? This cannot be undone. Active responses will be stopped; task files and run records will remain.')) return
    abortRef.current?.abort()
    setPendingToolAction(null)
    setDraft('')
    setFiles([])
    setError('')
    setNotice('')
    onClearAllChats()
  }

  const onKeyDown = (event: KeyboardEvent<HTMLTextAreaElement>) => {
    if (event.key === 'Enter' && !event.shiftKey) {
      event.preventDefault()
      void send(eventTimestamp(event))
    }
  }

  return (
    <div className={`page chat-page${messages.length ? '' : ' chat-page--empty'}`}>
      {notice && <button className="notice-inline" onClick={() => setNotice('')}>{notice} <X size={13} /></button>}
      <div className="chat-surface panel">
        <div className="chat-toolbar">
          <div className="chat-toolbar__session"><strong title={conversation?.title}>{conversation?.title || 'New conversation'}</strong>{(toolBusy || conversation) && <span className="live-label"><span />{toolBusy ? 'Agent working' : agentMode === 'chat' ? 'Chat' : `Agent · ${ENGINE_LABEL[agentMode]}`}</span>}</div>
          <div className="chat-toolbar__actions">{conversations.length > 0 && <button className="chat-new-thread chat-clear-all" type="button" onClick={clearAllChats} aria-label="Clear all chats" title="Clear all chats"><Trash2 size={14} /><span>Clear all</span></button>}<button className="chat-new-thread" type="button" onClick={newChat}><Plus size={14} /><span>New chat</span></button></div>
        </div>

        <div
          ref={listRef}
          className={`chat-messages${dragging ? ' chat-messages--dragging' : ''}`}
          onScroll={(event) => { const element = event.currentTarget; const distance = element.scrollHeight - element.scrollTop - element.clientHeight; stickToBottomRef.current = distance < 80; setScrolled(distance > 160) }}
          onDragOver={(event) => { event.preventDefault(); setDragging(true) }}
          onDragLeave={(event) => { if (!event.currentTarget.contains(event.relatedTarget as Node)) setDragging(false) }}
          onDrop={(event) => { event.preventDefault(); setDragging(false); void upload(event.dataTransfer.files) }}
        >
          <div className="chat-thread">
          {!messages.length ? (
            <div className="chat-welcome">
              <h2><span className="chat-welcome__mark" aria-hidden="true"><Sparkles size={22} strokeWidth={1.6} /></span>What are we working through?</h2>
              <p>{agentMode === 'agent'
                ? 'Agent mode plans the task, picks a capable local model, and shows each step. Switch the engine below to run it with OpenClaw or NemoClaw instead.'
                : agentMode === 'nemoclaw'
                  ? 'The NemoClaw engine sends each message to the sandboxed OpenClaw agent in WSL. It remembers this thread and works only inside its sandbox.'
                  : agentMode === 'openclaw'
                    ? 'The OpenClaw engine runs an agent directly on this PC with no sandbox, with any skills and MCP servers you have added. The permission setting below controls what it may do without asking you.'
                    : 'Chat mode answers directly with the best local model.'}</p>
            </div>
          ) : messages.map((message, index) => (
            <article key={`${activeId}-${index}`} className={`chat-message chat-message--${message.role}`}>
              <div className={`chat-message__body${message.error ? ' chat-message__body--error' : ''}${sending && index === messages.length - 1 && message.role === 'assistant' && message.content ? ' chat-message__body--streaming' : ''}`}>
                {message.runEvents?.length ? <RunTimeline events={message.runEvents} onPlanDecision={onPlanDecision} /> : null}
                {message.clawSteps?.length ? (
                  <ul className="claw-steps" aria-label="Agent activity">
                    {message.clawSteps.map((step) => (
                      <li key={step.id} className={`claw-step claw-step--${step.status}`} title={step.error}>
                        {step.status === 'running' ? <RefreshCw size={12} className="spin" aria-hidden="true" /> : step.status === 'completed' ? <Check size={12} aria-hidden="true" /> : <X size={12} aria-hidden="true" />}
                        <span>{step.title}</span>
                        {step.status !== 'completed' && <small>{step.status === 'running' ? 'Running' : step.status === 'blocked' ? 'Denied' : step.status === 'stopped' ? 'Stopped' : 'Failed'}</small>}
                      </li>
                    ))}
                  </ul>
                ) : null}
                {message.content.trim() ? (
                  message.role === 'assistant'
                    ? message.toolRunId ? (() => { const report = splitAgentReport(message.content); return <><ChatMarkdown content={report.answer} /><AgentChecks checks={report.checks} /></> })() : <ChatMarkdown content={message.content} />
                    : <p>{message.content}</p>
                ) : message.role === 'assistant' && !message.runEvents?.length && (sending || toolBusy) && index === messages.length - 1 ? (
                  <ThinkingIndicator label={message.toolRunId ? 'Planning the task' : clawApprovals.length ? 'Waiting for your approval' : message.clawSteps?.some((step) => step.status === 'running') ? 'Running a tool' : message.model ? `Writing with ${message.model}` : 'Thinking'} />
                ) : null}
                {message.attachments?.length ? (
                  <div className="message-attachments">
                    {message.attachments.map((attachment) => attachment.kind === 'image' && attachment.data
                      ? <a href={`data:${attachment.mime};base64,${attachment.data}`} target="_blank" rel="noreferrer" key={attachment.name}><img src={`data:${attachment.mime};base64,${attachment.data}`} alt={attachment.name} /></a>
                      : <FileChip key={attachment.name} attachment={attachment} />)}
                  </div>
                ) : null}
              </div>
              {message.role === 'assistant' && message.content && !(sending && index === messages.length - 1) && (
                <div className="chat-message__actions">
                  <button type="button" className="chat-message__action" onClick={() => void copyText(message.content)} aria-label="Copy response" title="Copy"><Copy size={14} /></button>
                  {message.model && <span className="message-route"><Zap size={11} /> {message.model}{message.category ? <> · {message.category}</> : null}</span>}
                </div>
              )}
            </article>
          ))}
          {pendingToolAction && (
            <section className="chat-route-confirm" aria-live="polite">
              <div className="chat-route-confirm__head">
                <Shield size={14} />
                <strong>Approval required · Agent chat</strong>
              </div>
              <p>{pendingToolAction.summary}</p>
              <blockquote>{pendingToolAction.request.sourceTask ?? pendingToolAction.request.task}</blockquote>
              <div className="chat-route-confirm__actions">
                <button type="button" onClick={() => { onApproveToolAction(pendingToolAction); setPendingToolAction(null); setDraft(''); setFiles([]); setWorkspacePath('') }}>
                  <Check size={12} /> Approve &amp; run
                </button>
                <button type="button" onClick={() => void send(Date.now(), undefined, true)}>Send as chat</button>
                <button type="button" onClick={() => setPendingToolAction(null)}>Cancel</button>
              </div>
            </section>
          )}
          {clawApprovals.map((approval) => (
            <section className="chat-route-confirm claw-approval" aria-live="polite" key={approval.id}>
              <div className="chat-route-confirm__head">
                <Shield size={14} />
                <strong>Approval required · OpenClaw</strong>
              </div>
              <p>{approval.title}</p>
              <blockquote>{approval.description || 'No details were provided for this action.'}</blockquote>
              <div className="chat-route-confirm__actions">
                <button type="button" disabled={approval.busy} onClick={() => void decideApproval(approval.id, 'allow-once')}>
                  {approval.busy ? <RefreshCw size={12} className="spin" /> : <Check size={12} />} Allow once
                </button>
                <button type="button" disabled={approval.busy} onClick={() => void decideApproval(approval.id, 'deny')}><X size={12} /> Deny</button>
              </div>
            </section>
          ))}
          {extensionProposal && (
            <ExtensionProposalCard
              key={extensionProposal.id}
              proposal={extensionProposal}
              onClose={() => setExtensionProposal(null)}
              onSwitchKind={(kind) => void previewExtension(extensionProposal.source, kind)}
            />
          )}
          </div>
          <button type="button" className={`scroll-bottom${scrolled ? ' is-visible' : ''}`} tabIndex={scrolled ? 0 : -1} aria-hidden={!scrolled} onClick={() => { stickToBottomRef.current = true; listRef.current?.scrollTo({ top: listRef.current.scrollHeight, behavior: 'smooth' }) }} aria-label="Scroll to newest message"><ArrowDown size={16} />{sending && <span className="scroll-bottom__live" aria-hidden="true" />}</button>
          {dragging && <div className="drop-overlay"><Upload size={20} /> Drop files to attach</div>}
        </div>

        {files.length > 0 && <div className="pending-files">{files.map((file, index) => <FileChip key={`${file.name}-${index}`} attachment={file} onRemove={() => setFiles((previous) => previous.filter((_, itemIndex) => itemIndex !== index))} />)}</div>}
        {error && <div className="chat-error"><CircleHelp size={14} /><span>{error}</span><button onClick={() => setError('')} aria-label="Dismiss error"><X size={13} /></button></div>}

        <form className="composer" onSubmit={(event) => void send(Date.now(), event)}>
          <input
            ref={uploadRef}
            type="file"
            multiple
            accept="image/*,.pdf,.docx,.xlsx,.pptx,.txt,.md,.csv,.json,.xml,.html,.log"
            onChange={(event) => void upload(event.target.files ?? [])}
            hidden
          />
          <textarea
            ref={textareaRef}
            value={draft}
            onChange={(event) => setDraft(event.target.value)}
            onKeyDown={onKeyDown}
            placeholder={pendingToolAction ? 'Approve, send as chat, or cancel the proposed task above…' : agentMode === 'chat' ? 'Chat with PockPock AI' : 'Give the agent a task, or paste a skill or MCP link'}
            rows={2}
            aria-label="Message"
            disabled={Boolean(pendingToolAction)}
          />
          <div className="composer__bottom">
            <div className="composer__tools">
              <div className="composer-menu-anchor">
                <button type="button" className="icon-button" onClick={() => setOpenComposerMenu(openComposerMenu === 'attach' ? null : 'attach')} disabled={uploading || Boolean(pendingToolAction)} aria-label="Add context" aria-expanded={openComposerMenu === 'attach'}>
                  {uploading ? <RefreshCw size={15} className="spin" /> : <Plus size={17} />}
                </button>
                {openComposerMenu === 'attach' && <div className="composer-popover composer-popover--attach" role="menu">
                  <div className="composer-popover__search"><Search size={13} /><input aria-label="Search attachments" placeholder="Search attachments" value={attachmentSearch} onChange={(event) => setAttachmentSearch(event.target.value)} /></div>
                  <button type="button" role="menuitem" onClick={() => { setAgentToolsEnabled((enabled) => !enabled); setOpenComposerMenu(null) }}><Bot size={14} /><span>{agentToolsEnabled ? 'Agent tools on' : 'Agent tools off'}<small>Let supported tasks run with local tools</small></span></button>
                  <button type="button" role="menuitem" onClick={() => { setOpenComposerMenu(null); onOpenExtensions('skills') }}><Puzzle size={14} /><span>Skills…<small>Add, switch on or off, or remove agent skills</small></span></button>
                  <button type="button" role="menuitem" onClick={() => { setOpenComposerMenu(null); onOpenExtensions('mcp') }}><Plug size={14} /><span>MCP servers…<small>Connect, switch on or off, or disconnect tool servers</small></span></button>
                  <button type="button" role="menuitem" onClick={() => { setOpenComposerMenu(null); uploadRef.current?.click() }}><FileText size={14} /><span>Files…<small>Attach documents or images</small></span></button>
                  <button type="button" role="menuitem" onClick={() => void addClipboardImage()}><FileImage size={14} /><span>Image from clipboard</span></button>
                  <button type="button" role="menuitem" onClick={() => void captureScreenshot()}><Monitor size={14} /><span>Screenshot window<small>Choose a screen or window to capture</small></span></button>
                  {conversations.length > 0 && <div className="composer-popover__section">Recent sessions</div>}
                  {conversations.filter((item) => item.id !== activeId && (!attachmentSearch || item.title.toLowerCase().includes(attachmentSearch.toLowerCase()))).slice(0, 5).map((item) => <button type="button" role="menuitem" key={item.id} onClick={() => attachConversation(item)}><MessageSquareText size={14} /><span>{item.title}<small>Attach recent conversation context</small></span></button>)}
                  <button type="button" role="menuitem" disabled title="Connect a source control integration to enable this action"><CircleHelp size={14} /><span>Issue…<small>Source control integration unavailable</small></span></button>
                  <button type="button" role="menuitem" disabled title="Connect a source control integration to enable this action"><GitPullRequest size={14} /><span>Pull request…<small>Source control integration unavailable</small></span></button>
                </div>}
              </div>
              <div className="chat-agent-switch" role="group" aria-label="Response mode">
                <button type="button" aria-pressed={agentMode === 'chat'} className={agentMode === 'chat' ? 'is-active' : ''} onClick={() => { setAgentMode('chat'); setOpenComposerMenu(null) }}><MessageSquareText size={11} /> Chat</button>
                <button type="button" aria-pressed={agentMode !== 'chat'} className={agentMode !== 'chat' ? 'is-active' : ''} onClick={() => chooseEngine(agentEngine)}><Bot size={11} /> Agent</button>
              </div>
              {agentMode !== 'chat' && <div className="composer-menu-anchor">
                <button type="button" className="chat-mode-chip" onClick={() => setOpenComposerMenu(openComposerMenu === 'engine' ? null : 'engine')} aria-expanded={openComposerMenu === 'engine'} aria-label={`Agent engine: ${ENGINE_LABEL[agentMode]}`}>
                  {agentMode === 'openclaw' ? <Terminal size={11} /> : agentMode === 'nemoclaw' ? <Box size={11} /> : <Bot size={11} />} {ENGINE_LABEL[agentMode]} <ChevronDown size={11} />
                </button>
                {openComposerMenu === 'engine' && <div className="composer-popover composer-popover--permission" role="menu">
                  <div className="composer-popover__section">Run agent tasks with</div>
                  <button type="button" role="menuitemradio" aria-checked={agentMode === 'agent'} className={agentMode === 'agent' ? 'is-selected' : ''} onClick={() => chooseEngine('agent')}><Bot size={14} /><span>PockPock<small>Plans the task and runs the built-in tools inside a task workspace.</small></span></button>
                  <button type="button" role="menuitemradio" aria-checked={agentMode === 'openclaw'} className={agentMode === 'openclaw' ? 'is-selected' : ''} disabled={!openclaw?.available && agentMode !== 'openclaw'} onClick={() => chooseEngine('openclaw')}><Terminal size={14} /><span>OpenClaw<small>{!openclaw ? 'Checking whether OpenClaw is installed…' : !openclaw.available ? openclaw.detail : 'Runs on this PC with no sandbox. Uses your skills and MCP servers, with the permission you choose.'}</small></span></button>
                  <button type="button" role="menuitemradio" aria-checked={agentMode === 'nemoclaw'} className={agentMode === 'nemoclaw' ? 'is-selected' : ''} disabled={!nemoclaw?.available && agentMode !== 'nemoclaw'} onClick={() => chooseEngine('nemoclaw')}><Box size={14} /><span>NemoClaw<small>{!nemoclaw ? 'Checking the sandbox. This can take a minute after a restart…' : !nemoclaw.available ? nemoclaw.detail : 'Runs OpenClaw inside a sandbox in WSL. It cannot touch files or programs on this PC.'}</small></span></button>
                </div>}
              </div>}
              {agentMode === 'openclaw' && (
                <button
                  type="button"
                  className={`chat-mode-chip nemoclaw-status nemoclaw-status--${openclawChecking ? 'checking' : openclaw?.ready ? 'ready' : 'offline'}`}
                  onClick={() => void refreshOpenclaw(true)}
                  disabled={openclawChecking}
                  aria-label={`OpenClaw status: ${openclawChecking ? 'checking' : openclaw?.ready ? 'ready' : 'not ready'}. Recheck`}
                  title={openclaw?.detail || 'Recheck OpenClaw'}
                >
                  {openclawChecking ? <RefreshCw size={11} className="spin" /> : <span className="nemoclaw-status__dot" aria-hidden="true" />}
                  <span className="nemoclaw-status__label">{openclawChecking ? 'Checking OpenClaw…' : openclaw?.ready ? 'This PC' : 'OpenClaw offline · Recheck'}</span>
                </button>
              )}
              {agentMode === 'openclaw' && <div className="composer-menu-anchor">
                <button type="button" className={`chat-mode-chip${clawPermission === 'full' ? ' chat-mode-chip--danger' : ''}`} onClick={() => setOpenComposerMenu(openComposerMenu === 'permission' ? null : 'permission')} aria-expanded={openComposerMenu === 'permission'} aria-label={`OpenClaw permission: ${CLAW_PERMISSION_LABEL[clawPermission]}`}><Shield size={11} /> {CLAW_PERMISSION_LABEL[clawPermission]}</button>
                {openComposerMenu === 'permission' && <div className="composer-popover composer-popover--permission" role="menu">
                  <button type="button" role="menuitemradio" aria-checked={clawPermission === 'ask'} className={clawPermission === 'ask' ? 'is-selected' : ''} disabled={openclaw?.plugin === false} onClick={() => { setClawPermission('ask'); setOpenComposerMenu(null) }}><Shield size={14} /><span>Ask first<small>Every action waits for your approval here before it runs.</small></span></button>
                  <button type="button" role="menuitemradio" aria-checked={clawPermission === 'auto'} className={clawPermission === 'auto' ? 'is-selected' : ''} disabled={openclaw?.plugin === false} onClick={() => { setClawPermission('auto'); setOpenComposerMenu(null) }}><Check size={14} /><span>Auto-approve safe<small>Reading files and read-only commands run on their own. Changes, other commands, and web access ask first.</small></span></button>
                  <button type="button" role="menuitemradio" aria-checked={clawPermission === 'full'} className={clawPermission === 'full' ? 'is-selected' : ''} onClick={() => { setClawPermission('full'); setOpenComposerMenu(null) }}><Terminal size={14} /><span>Full access<small>Nothing asks. The agent can run any command and change any file on this PC.</small></span></button>
                  {openclaw?.plugin === false && <div className="composer-popover__section">Permission plugin not loaded. Only Full access can run.</div>}
                </div>}
              </div>}
              {agentMode === 'nemoclaw' && (
                <button
                  type="button"
                  className={`chat-mode-chip nemoclaw-status nemoclaw-status--${nemoclawChecking ? 'checking' : nemoclaw?.ready ? 'ready' : 'offline'}`}
                  onClick={() => void refreshNemoclaw(true)}
                  disabled={nemoclawChecking}
                  aria-label={`NemoClaw status: ${nemoclawChecking ? 'checking' : nemoclaw?.ready ? 'ready' : 'not ready'}. Recheck`}
                  title={nemoclaw?.detail || 'Recheck NemoClaw'}
                >
                  {nemoclawChecking ? <RefreshCw size={11} className="spin" /> : <span className="nemoclaw-status__dot" aria-hidden="true" />}
                  <span className="nemoclaw-status__label">{nemoclawChecking ? 'Checking sandbox…' : nemoclaw?.ready ? `Sandbox · ${nemoclaw.model || nemoclaw.sandbox}` : 'Sandbox offline · Recheck'}</span>
                </button>
              )}
              {agentMode === 'agent' && <div className="composer-menu-anchor">
                <button type="button" className="chat-mode-chip" onClick={() => void chooseAgentWorkspace()} disabled={choosingWorkspace || Boolean(pendingToolAction)} title={workspacePath || 'Choose a folder for this task; otherwise a temporary workspace is created'} aria-label="Choose agent task workspace">
                  {choosingWorkspace ? <RefreshCw size={11} className="spin" /> : <FolderOpen size={11} />}
                  {workspacePath ? `Workspace · ${workspacePath.split(/[\\/]/).filter(Boolean).at(-1)}` : choosingWorkspace ? 'Choose folder…' : 'Temp workspace'}
                </button>
                {workspacePath && <button type="button" className="chat-mode-chip workspace-clear-button" onClick={() => setWorkspacePath('')} disabled={Boolean(pendingToolAction)} aria-label="Use a temporary workspace instead" title="Use a new temporary workspace instead"><X size={11} /></button>}
              </div>}
              {agentMode !== 'nemoclaw' && agentMode !== 'openclaw' && <div className="composer-menu-anchor">
                <button type="button" className="chat-mode-chip" onClick={() => setOpenComposerMenu(openComposerMenu === 'permission' ? null : 'permission')} aria-expanded={openComposerMenu === 'permission'}><Shield size={11} /> {permissionMode === 'default' ? 'Default permissions' : permissionMode === 'full-access' ? 'Full access' : 'Auto-review'}</button>
                {openComposerMenu === 'permission' && <div className="composer-popover composer-popover--permission" role="menu">
                  <button type="button" role="menuitemradio" aria-checked={permissionMode === 'default'} className={permissionMode === 'default' ? 'is-selected' : ''} onClick={() => { setPermissionMode('default'); setOpenComposerMenu(null) }}><Shield size={14} /><span>Default permissions<small>Ask before starting an agent task. Local tools stay within their built-in limits.</small></span></button>
                  <button type="button" role="menuitemradio" aria-checked={permissionMode === 'auto-review'} className={permissionMode === 'auto-review' ? 'is-selected' : ''} onClick={() => { setPermissionMode('auto-review'); setOpenComposerMenu(null) }}><Check size={14} /><span>Auto-review<small>Start supported tasks automatically. File tools stay inside your chosen folder or a new temporary workspace.</small></span></button>
                  <button type="button" role="menuitemradio" aria-checked={permissionMode === 'full-access'} className={permissionMode === 'full-access' ? 'is-selected' : ''} onClick={() => { setPermissionMode('full-access'); setOpenComposerMenu(null) }}><Shield size={14} /><span>Full access<small>Run automatically with file read and edit access inside the selected or temporary task workspace; no arbitrary shell.</small></span></button>
                </div>}
              </div>}
            </div>
            <div className="composer__controls">
              {agentMode === 'openclaw' && clawModels.length > 0 && <div className="composer-menu-anchor">
                <button type="button" className="model-picker-button" onClick={() => setOpenComposerMenu(openComposerMenu === 'model' ? null : 'model')} aria-expanded={openComposerMenu === 'model'} aria-label={`OpenClaw model: ${activeClawModel || openclaw?.model || 'default'}`}>
                  <Sparkles size={13} /><span>{activeClawModel || openclaw?.model || 'Default model'}</span><small>{activeClawModel ? 'Local' : 'Default'}</small><ChevronDown size={12} />
                </button>
                {openComposerMenu === 'model' && <div className="composer-popover composer-popover--models" role="menu">
                  <div className="composer-popover__section">Model for the OpenClaw engine</div>
                  <button type="button" role="menuitemradio" aria-checked={!activeClawModel} className={!activeClawModel ? 'is-selected' : ''} onClick={() => { setClawModel(''); setOpenComposerMenu(null) }}><Sparkles size={14} /><span>Default<small>{openclaw?.model || 'OpenClaw default'} · quicker replies</small></span>{!activeClawModel && <Check size={13} />}</button>
                  {clawModels.filter((name) => name !== openclaw?.model).map((name) => <button type="button" role="menuitemradio" aria-checked={activeClawModel === name} className={activeClawModel === name ? 'is-selected' : ''} key={name} onClick={() => { setClawModel(name); setOpenComposerMenu(null) }}><Bot size={14} /><span>{name}<small>{modelFamily(name)} · On this PC · loads when used</small></span>{activeClawModel === name && <Check size={13} />}</button>)}
                </div>}
              </div>}
              {agentMode !== 'nemoclaw' && agentMode !== 'openclaw' && <div className="composer-menu-anchor">
                <button type="button" className="model-picker-button" onClick={() => setOpenComposerMenu(openComposerMenu === 'model' ? null : 'model')} aria-expanded={openComposerMenu === 'model'} aria-label="Choose a local model">
                  <Sparkles size={13} /><span>{selectedModel === 'auto' ? 'Smart route' : selectedModel}</span><small>{selectedModel === 'auto' ? 'Auto' : 'Local'}</small><ChevronDown size={12} />
                </button>
                {openComposerMenu === 'model' && <div className="composer-popover composer-popover--models" role="menu">
                  <div className="composer-popover__search"><Search size={13} /><input aria-label="Search local models" placeholder="Search models" value={modelSearch} onChange={(event) => setModelSearch(event.target.value)} /></div>
                  <div className="composer-popover__section">Local Ollama models</div>
                  <button type="button" role="menuitemradio" aria-checked={selectedModel === 'auto'} className={selectedModel === 'auto' ? 'is-selected' : ''} onClick={() => { setSelectedModel('auto'); setOpenComposerMenu(null) }}><Sparkles size={14} /><span>Smart route<small>Choose a model for each request</small></span>{selectedModel === 'auto' && <Check size={13} />}</button>
                  {enabledModels.filter((model) => !modelSearch || model.name.toLowerCase().includes(modelSearch.toLowerCase())).map((model) => <button type="button" role="menuitemradio" aria-checked={selectedModel === model.name} className={selectedModel === model.name ? 'is-selected' : ''} key={model.name} onClick={() => { setSelectedModel(model.name); setOpenComposerMenu(null) }}><Bot size={14} /><span>{model.name}<small>{modelFamily(model.name)} · On this PC</small></span>{selectedModel === model.name && <Check size={13} />}</button>)}
                </div>}
              </div>}
              <button type={sending || toolBusy ? 'button' : 'submit'} className={`send-button${sending || toolBusy ? ' send-button--stop' : ''}`} onClick={sending ? stop : toolBusy ? onStopTool : undefined} disabled={!sending && !toolBusy && (uploading || inspecting || Boolean(pendingToolAction) || (!draft.trim() && files.length === 0))} aria-label={sending || toolBusy ? 'Stop current run' : 'Send message'}>
                {sending || toolBusy ? <X size={15} /> : <ArrowUp size={16} />}
              </button>
            </div>
          </div>
        </form>
        {!messages.length && (
          <div className="chat-capabilities">
            {agentMode !== 'nemoclaw' && agentMode !== 'openclaw' && <button type="button" onClick={() => { setOpenComposerMenu(null); uploadRef.current?.click() }}><FileImage size={14} /> Analyze an image</button>}
            <button type="button" onClick={() => { setDraft('Research '); textareaRef.current?.focus() }}><Globe2 size={14} /> Research a website</button>
            <button type="button" onClick={() => { setOpenComposerMenu(null); uploadRef.current?.click() }}><FileText size={14} /> Summarize a file</button>
          </div>
        )}
        <div className="chat-disclaimer"><Shield size={11} /> {agentMode === 'nemoclaw' ? 'Runs locally in the NemoClaw sandbox. Messages are not included in router telemetry.' : agentMode === 'openclaw' ? 'Runs on this PC with no sandbox. Messages are not included in router telemetry.' : 'Runs locally. Prompts are not included in router telemetry.'}</div>
      </div>
    </div>
  )
}

