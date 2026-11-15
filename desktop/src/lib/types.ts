// Shared data shapes for the desktop renderer.

export type Engine = 'chat' | 'agent' | 'openclaw' | 'nemoclaw'

export const ENGINE_LABEL: Record<Engine, string> = {
  chat: 'Chat',
  agent: 'PockPock Agent',
  openclaw: 'OpenClaw',
  nemoclaw: 'NemoClaw',
}

/** PockPock agent permission levels, as the backend names them. */
export type AgentPermission = 'default' | 'auto-review' | 'full-access'
/** OpenClaw permission modes enforced by the PockPock permission plugin. */
export type ClawPermission = 'ask' | 'auto' | 'full'

export type Attachment = {
  name: string
  kind: 'image' | 'document'
  mime?: string
  data?: string
  text?: string
  size: number
}

export type Step = {
  id: string
  label: string
  status: 'running' | 'done' | 'failed' | 'blocked' | 'stopped'
  detail?: string
}

export type Approval = {
  id: string
  source: 'openclaw' | 'agent'
  title: string
  description: string
  diff?: string
  runId?: string
  actionHash?: string
  status: 'pending' | 'busy' | 'approved' | 'rejected' | 'expired'
  error?: string
}

export type PlanCard = {
  planId: string
  planHash: string
  goal: string
  steps: string[]
  checks: string[]
  deliverables: string[]
  questions: string[]
  critic: string
  criticFindings: string[]
  model: string
  workspace: string
  status: 'pending' | 'approved' | 'rejected'
  error?: string
}

export type Artifact = { name: string; path: string; url: string; kind: string }

export type Message = {
  id: string
  role: 'user' | 'assistant'
  content: string
  createdAt: number
  engine: Engine
  model?: string
  status?: 'streaming' | 'done' | 'stopped' | 'error'
  attachments?: Attachment[]
  steps?: Step[]
  approvals?: Approval[]
  plan?: PlanCard
  artifacts?: Artifact[]
  runId?: string
  taskId?: string
  workspacePath?: string
  notice?: string
}

export type Session = {
  id: string
  title: string
  createdAt: number
  updatedAt: number
  messages: Message[]
}

export type Model = { name: string; size: number; enabled: boolean; running: boolean; details?: Record<string, unknown> }

export type AppState = {
  api_connected: boolean
  connected: boolean
  error: string
  router_enabled: boolean
  models: Model[]
  active: Array<{ model: string; role: string }>
}

export type ClawStatus = { available: boolean; ready: boolean; detail: string; plugin?: boolean; model?: string; models?: string[] }
export type NemoStatus = { available: boolean; ready: boolean; checked?: boolean; detail: string; model?: string; sandbox?: string }

export type BackendPhase = { phase: 'checking' | 'starting' | 'ready' | 'missing' | 'failed'; detail: string; startedByApp: boolean }

export type FileEntry = { name: string; path: string; directory: boolean; muted: boolean }

export type Settings = {
  workspace?: string
  engine?: Engine
  agentPermission?: AgentPermission
  clawPermission?: ClawPermission
  chatModel?: string
  clawModel?: string
  sidebar?: boolean
  files?: boolean
  terminal?: boolean
  useWorkspaceForAgent?: boolean
}

/** The preload bridge. Absent when the renderer runs in a plain browser (tests, Vite preview). */
export type DesktopBridge = {
  info: () => Promise<{ version: string; electron: string; repoRoot: string; backendUrl: string; terminal: boolean; backend: BackendPhase }>
  store: { get: <T>(key: 'sessions' | 'settings') => Promise<T | null>; set: (key: 'sessions' | 'settings', value: unknown) => Promise<boolean> }
  workspace: {
    choose: () => Promise<string | null>
    list: (relative?: string) => Promise<{ items: FileEntry[]; truncated: boolean }>
    read: (relative: string) => Promise<{ name: string; text: string; size: number }>
    open: (relative: string) => Promise<boolean>
    reveal: (relative: string) => Promise<boolean>
  }
  terminal: {
    create: (options: { cols: number; rows: number }) => Promise<{ id: number; shell: string }>
    write: (id: number, data: string) => Promise<void>
    resize: (id: number, cols: number, rows: number) => Promise<void>
    kill: (id: number) => Promise<void>
    onData: (callback: (id: number, data: string) => void) => () => void
    onExit: (callback: (id: number, code: number) => void) => () => void
  }
  backend: { retry: () => Promise<boolean>; onStatus: (callback: (state: BackendPhase) => void) => () => void }
  openExternal: (url: string) => Promise<void>
  openPath: (target: string) => Promise<boolean>
}

declare global {
  interface Window { pockpock?: DesktopBridge }
}

export const bridge = (): DesktopBridge | undefined => window.pockpock
