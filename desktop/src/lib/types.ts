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
  lastEventAt?: number // the newest stream event; the run bar says how long ago, and calls a quiet run slow
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
  /** "Allow for this task" is offered: the gateway can grant this kind of action for the rest of the run. */
  grantable?: boolean
  /** How it was allowed: this action only, or this kind of action for the rest of the task. */
  scope?: 'once' | 'task'
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
  /** The run's task folder, known before it starts (<output_directory>/<run id>). */
  taskFolder?: string
  /** The gateway's fixed check of the plan (files, permission, research, open questions). */
  precheck?: PlanCheck[]
  /** Answer choices per question, in the same order; empty when the planner gave none. */
  questionOptions?: string[][]
  /** replaced: the user answered a question and the task was planned again. */
  status: 'pending' | 'approved' | 'rejected' | 'replaced'
  error?: string
}

export type PlanCheck = { id: string; status: 'pass' | 'warn'; label: string; detail: string }
/** A note the user added while a PockPock Agent run worked. */
export type RunNote = { id: string; text: string; status: 'sending' | 'queued' | 'given' | 'failed'; error?: string }

export type Artifact = { name: string; path: string; url: string; kind: string }

export type ResearchSource = { source_id: string; title: string; url: string; excerpt: string }
export type ResearchBlock = { taskId: string; query: string; sources: ResearchSource[]; errors: string[] }
export type FileChange = { path: string; summary: string }
/** A file the run used, for the inspector: read by a tool, changed by an approved patch, or saved as a new file. */
export type TouchedFile = { path: string; kind: 'read' | 'edited' | 'new' }
/** Token counts from the newest model call of a run (the gateway's `usage` event). */
export type Usage = { promptTokens: number; completionTokens?: number; contextWindow?: number }

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
  /** The folder where an agent run saved its files (its task folder). */
  taskFolder?: string
  notice?: string
  timing?: Timing
  usage?: Usage
  /** The agent stopped calling tools and is checking its answer against the success checks. */
  verifying?: boolean
  touched?: TouchedFile[]
  notes?: RunNote[]
  /** Plans this turn replaced after the user answered a question, oldest first. */
  earlierPlans?: PlanCard[]
}

export type Session = {
  id: string
  title: string
  createdAt: number
  updatedAt: number
  messages: Message[]
}

export type Model = { name: string; size: number; enabled: boolean; running: boolean; embedding?: boolean; details?: Record<string, unknown> }

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
  cloud_models?: CloudModelRef[]
  active: Array<{ model: string; role: string }>
  events?: Trace[]
  totals?: { requests?: number; calls?: number; avg_ms?: number | null }
  /** Where agent runs save files; a run's task folder is <output_directory>/<run id>. */
  output_directory?: string
}

export type ClawStatus = { available: boolean; ready: boolean; detail: string; plugin?: boolean; model?: string; models?: string[] }
/** One input of a connector's connect form. `only_when` is [other field, value]. */
export type ConnectorField = { key: string; label: string; secret: boolean; placeholder: string; help: string; options: Array<{ value: string; label: string }>; required: boolean; only_when: [string, string] | null }
/** An external app the agent can use as tools. Credentials never reach the page. */
export type Connector = {
  id: string; name: string; group: string; about: string; featured: boolean
  fields: ConnectorField[]; steps: string[]; key_url: string
  tools: Array<{ name: string; title: string; write: boolean }>
  connected: boolean; needsReconnect: boolean; account: string; connectedAt: string | null
}
/** A cloud model as a provider lists it. `tools` is null when the provider does not say. */
export type CloudModel = { id: string; name: string; contextWindow: number | null; tools?: boolean | null; free?: boolean }
export type CloudProviderId = 'nim' | 'openrouter' | 'alibaba'
/** A cloud provider on the Cloud page. The API key itself never reaches the page. */
export type CloudProvider = {
  id: CloudProviderId; name: string; about: string; keyUrl: string; keyHint: string
  regions: Array<{ id: string; name: string }>; region: string
  connected: boolean; needsKey: boolean; keyEnding: string; connectedAt: string | null
  models: CloudModel[]
}
/** A chosen cloud model in the gateway's state: `name` is "<provider>/<model id>". */
export type CloudModelRef = { name: string; provider: CloudProviderId; provider_label: string; context_window: number | null }
/** NemoClaw's sandbox-wide model: a cloud model, or the sandbox's own local model. */
export type NemoRoute = { cloud: boolean; model: string; provider: string; local: { provider?: string; model?: string }; cloud_models: string[] }
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
  inspectorTab?: 'context' | 'files' | 'terminal'
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
export type MaintenanceAgent = { id: 'local' | 'claude' | 'codex' | 'copilot'; name: string; vendor: string; installed: boolean; canConnect?: boolean; signedIn?: boolean | null; version?: string; models?: string[]; suggested?: string; openclaw?: boolean; dataNotice: string; install: string }
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
  branch: string; worktree: string; startedAt: number; endedAt?: number; reason?: string; warning?: string
  log: string[]; checks: Array<{ name: string; ok: boolean; output: string }>
  changed?: string[]; diff?: string; docsChanged?: boolean; title?: string; body?: string; prUrl?: string
}
export type MaintenanceEvent = { type: 'github-code'; code: string; url: string } | { type: 'clone-log'; line: string } | { type: 'agent-log'; id: MaintenanceAgent['id']; line: string } | { type: 'agent-url'; id: MaintenanceAgent['id']; url: string } | { type: 'fix'; run: FixRun } | { type: 'fix-log'; reportId: string; line: string }
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
  connectors: {
    list: () => Promise<Connector[]>
    connect: (id: string, values: Record<string, string>) => Promise<Connector[]>
    disconnect: (id: string) => Promise<Connector[]>
    onChange: (callback: () => void) => () => void
  }
  cloud: {
    list: () => Promise<CloudProvider[]>
    connect: (id: CloudProviderId, input: { key: string; region?: string }) => Promise<{ providers: CloudProvider[]; offered: CloudModel[] }>
    available: (id: CloudProviderId) => Promise<CloudModel[]>
    setModels: (id: CloudProviderId, models: CloudModel[]) => Promise<CloudProvider[]>
    disconnect: (id: CloudProviderId) => Promise<CloudProvider[]>
    onChange: (callback: (providers: CloudProvider[]) => void) => () => void
  }
  maintenance: {
    status: () => Promise<MaintenanceStatus>
    agents: () => Promise<MaintenanceAgent[]>
    setAgent: (choice: { id: MaintenanceAgent['id']; model?: string; openclaw?: boolean }) => Promise<unknown>
    connectAgent: (id: MaintenanceAgent['id']) => Promise<MaintenanceAgent[]>
    cancelConnect: () => Promise<boolean>
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
    slowModels: () => Promise<{ seconds: number | null; recommended: number }>
    allowSlowModels: () => Promise<{ seconds: number | null; recommended: number }>
  }
  setLoginItem: (enabled: boolean) => Promise<boolean>
  openExternal: (url: string) => Promise<void>
  openPath: (target: string) => Promise<boolean>
}

declare global {
  interface Window { pockpock?: DesktopBridge }
}

export const bridge = (): DesktopBridge | undefined => window.pockpock
