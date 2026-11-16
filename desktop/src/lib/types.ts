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
  startedAt?: number // ms since epoch, recorded by the app when the step's event arrived
  endedAt?: number
}

/** When each phase of an assistant turn happened (ms since epoch). See lib/timing.ts. */
export type Timing = {
  startedAt: number
  firstOutputAt?: number // first token, step, plan or approval
  planReadyAt?: number // PockPock Agent: the plan card appeared
  planDecidedAt?: number // ...and was approved, declined or stopped
  endedAt?: number
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
  requestedAt?: number
  resolvedAt?: number
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

export type ResearchSource = { source_id: string; title: string; url: string; excerpt: string }
export type ResearchBlock = { taskId: string; query: string; sources: ResearchSource[]; errors: string[] }
export type FileChange = { path: string; summary: string }

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
  research?: ResearchBlock[]
  changes?: FileChange[]
  runId?: string
  taskId?: string
  workspacePath?: string
  notice?: string
  timing?: Timing
}

export type Session = {
  id: string
  title: string
  createdAt: number
  updatedAt: number
  messages: Message[]
}

export type Model = { name: string; size: number; enabled: boolean; running: boolean; details?: Record<string, unknown> }

export type Trace = {
  id: number
  created_at: string
  event: string
  model: string
  automatic_model: string
  role: string
  status: string
  category: string
  source: string
  reason: string
  error: string
  duration_ms: number | null
}

export type AppState = {
  api_connected: boolean
  connected: boolean
  error: string
  router_enabled: boolean
  classifier?: string
  models: Array<Model & { calls?: number; successes?: number; avg_ms?: number | null }>
  active: Array<{ model: string; role: string }>
  events?: Trace[]
  totals?: { requests?: number; calls?: number; avg_ms?: number | null }
}

export type ClawStatus = { available: boolean; ready: boolean; detail: string; plugin?: boolean; model?: string; models?: string[] }
export type NemoStatus = { available: boolean; ready: boolean; checked?: boolean; detail: string; model?: string; sandbox?: string }

export type BackendPhase = { phase: 'checking' | 'starting' | 'ready' | 'missing' | 'failed' | 'stopped'; detail: string; startedByApp: boolean }

export type ServiceState = {
  id: string
  name: string
  group: string
  port: number
  description: string
  status: 'checking' | 'running' | 'stopped' | 'starting' | 'stopping' | 'unavailable' | 'error'
  detail: string
  startedByApp: boolean
  available: boolean
}

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
  services?: { autoStart?: boolean; stopOnQuit?: boolean; nemoclaw?: boolean }
  updates?: { autoDownload?: boolean }
  theme?: string // a ThemeId from lib/theme.ts
}

export type AppInfo = { version: string; electron: string; platform: string; arch: string; repoRoot: string; backendRoot: string; python: string; packaged: boolean; backendUrl: string; terminal: boolean; backend: BackendPhase; loginItem: boolean }

export type SetupComponent = 'core' | 'ollama' | 'openclaw' | 'nemoclaw'
export type UpdateState = {
  status: 'idle' | 'checking' | 'none' | 'available' | 'downloading' | 'ready' | 'error' | 'unsupported'
  current: string
  version: string
  progress: number
  error: string
  checkedAt: string
  canInstall: boolean // Windows installs updates itself; macOS links to the download page
  releaseUrl: string
}
export type MaintenanceAgent = { id: 'local' | 'claude' | 'codex' | 'copilot'; name: string; vendor: string; installed: boolean; version?: string; models?: string[]; suggested?: string; openclaw?: boolean; dataNotice: string; install: string }
export type GitHubAccount = { installed: boolean; loggedIn: boolean; login?: string; id?: number; canPush?: boolean; install?: string }
export type MaintenanceStatus = {
  agent: { id: MaintenanceAgent['id']; model: string; openclaw?: boolean; chosenAt: string } | null
  repo: { dir: string; fork: boolean; owner: string; upstream: string; clonedAt: string; present: boolean } | null
  defaultFolder: string
  ready: boolean
  auto: boolean
}
export type FixRun = {
  reportId: string
  state: 'running' | 'ready' | 'failed' | 'cancelled' | 'proposed' | 'none'
  agent: { id: MaintenanceAgent['id']; model: string; openclaw?: boolean }
  branch: string; worktree: string; startedAt: number; endedAt?: number; reason?: string
  log: string[]; checks: Array<{ name: string; ok: boolean; output: string }>
  changed?: string[]; diff?: string; docsChanged?: boolean; title?: string; body?: string; prUrl?: string
}
export type MaintenanceEvent = { type: 'github-code'; code: string; url: string } | { type: 'clone-log'; line: string } | { type: 'fix'; run: FixRun } | { type: 'fix-log'; reportId: string; line: string }
export type ReportCategory = 'hang' | 'failed' | 'wrong' | 'other'
export type ReportStatus = 'open' | 'in-progress' | 'fixed' | 'wont-fix'
export type Redactions = { path: number; user: number; email: number; token: number }
/** One reported exchange, as captured by lib/reports.ts and redacted by electron/reports.cjs. */
export type ReportCapture = {
  appVersion: string; platform: string; engine: string; model: string; chatTitle: string; createdAt?: number
  userMessage: string; attachments: string[]; reply: string; status: string; notice: string
  plan?: { goal: string; steps: string[]; status: string }
  steps: Array<{ label: string; status: string; detail: string; ms?: number }>
  approvals: Array<{ title: string; description: string; status: string }>
  timing: Array<{ label: string; ms?: number }>
}
export type Report = { id: string; createdAt: number; updatedAt: number; category: ReportCategory; description: string; status: ReportStatus; capture: ReportCapture; redactions: Redactions }
export type ReportSummary = Omit<Report, 'capture'> & { engine: string; chatTitle: string }
export type ModelChoice = { name: string; downloadGB: number; summary: string }
export type SetupStatus = {
  platform: string
  arch: string
  hardware: { ramGB: number; gpu: { name: string; memoryGB: number; shared: boolean } | null; freeDiskGB: number | null; cpu: string }
  model: { name: string; reason: string; choices: ModelChoice[]; missing: string[] }
  recommended: { components: SetupComponent[]; downloadGB: number; neededGB: number }
  core: { installed: boolean }
  ollama: { installed: boolean; running: boolean; models: Record<string, boolean> }
  openclaw: { installed: boolean; cli: boolean; node: boolean }
  nemoclaw: { installed: boolean; supported: boolean; reason: string; docker: boolean }
  winget: boolean
  skills: Array<{ key: string; name: string; description: string }>
  pending: { components: SetupComponent[]; disabledSkills: string[]; model?: string } | null
  lastRun: { result?: string; message?: string } | null
  verified: { at: string; ok: boolean; problems: string[] } | null
  needsSetup: boolean
}
export type SetupEvent =
  | { type: 'started'; components: SetupComponent[] }
  | { type: 'log'; line: string }
  | { type: 'step'; component: SetupComponent | 'verify'; id: string; label: string; status: 'running' | 'done' | 'waiting' | 'failed'; detail?: string; progress?: number }
  | { type: 'finished'; outcome: 'done' | 'failed' | 'cancelled' | 'restart' | 'action'; message: string }

/** The preload bridge. Absent when the renderer runs in a plain browser (tests, Vite preview). */
export type DesktopBridge = {
  info: () => Promise<AppInfo>
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
  services: {
    list: () => Promise<ServiceState[]>
    start: (id: string) => Promise<unknown>
    stop: (id: string) => Promise<unknown>
    restart: (id: string) => Promise<unknown>
    logs: (id: string) => Promise<{ file: string; text: string }>
    openLogs: () => Promise<string>
    onChange: (callback: (list: ServiceState[]) => void) => () => void
  }
  setup: {
    status: () => Promise<SetupStatus>
    start: (plan: { components: SetupComponent[]; disabledSkills: string[]; model?: string }) => Promise<boolean>
    cancel: () => Promise<boolean>
    onEvent: (callback: (event: SetupEvent) => void) => () => void
  }
  updates: {
    state: () => Promise<UpdateState>
    check: () => Promise<UpdateState>
    download: () => Promise<UpdateState>
    install: () => Promise<boolean>
    onChange: (callback: (state: UpdateState) => void) => () => void
  }
  maintenance: {
    status: () => Promise<MaintenanceStatus>
    agents: () => Promise<MaintenanceAgent[]>
    setAgent: (choice: { id: MaintenanceAgent['id']; model?: string; openclaw?: boolean }) => Promise<unknown>
    github: () => Promise<GitHubAccount>
    githubLogin: () => Promise<GitHubAccount>
    cancelLogin: () => Promise<boolean>
    chooseFolder: (current?: string) => Promise<string>
    clone: (dir: string) => Promise<unknown>
    forget: () => Promise<boolean>
    setAuto: (enabled: boolean) => Promise<unknown>
    fixGet: (reportId: string) => Promise<FixRun | null>
    fixStart: (reportId: string) => Promise<FixRun>
    fixCancel: (reportId: string) => Promise<boolean>
    fixApprove: (reportId: string, text: { title: string; body: string }) => Promise<FixRun>
    fixDiscard: (reportId: string) => Promise<boolean>
    onEvent: (callback: (event: MaintenanceEvent) => void) => () => void
  }
  reports: {
    preview: (capture: ReportCapture) => Promise<{ capture: ReportCapture; redactions: Redactions }>
    create: (input: { category: ReportCategory; description: string; capture: ReportCapture }) => Promise<Report>
    list: () => Promise<ReportSummary[]>
    get: (id: string) => Promise<Report>
    update: (id: string, change: Partial<Pick<Report, 'category' | 'description' | 'status'>>) => Promise<Report>
    delete: (id: string) => Promise<boolean>
  }
  theme: {
    set: (id: string) => Promise<string>
  }
  openclaw: {
    browsers: () => Promise<{ available: Array<{ id: string; name: string }>; current: string; currentPath: string }>
    setBrowser: (id: string) => Promise<string>
  }
  setLoginItem: (enabled: boolean) => Promise<boolean>
  openExternal: (url: string) => Promise<void>
  openPath: (target: string) => Promise<boolean>
}

declare global {
  interface Window { pockpock?: DesktopBridge }
}

export const bridge = (): DesktopBridge | undefined => window.pockpock
