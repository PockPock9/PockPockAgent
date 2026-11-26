// Runs one turn on one engine and reports progress by patching the assistant message.
// Engines: Chat (/api/chat), PockPock Agent (/api/agents/plan + /api/agents/run),
// OpenClaw (/api/openclaw/chat), NemoClaw (/api/nemoclaw/chat).
import { sendJson, stream, text, uid } from './api'
import type { StreamEvent } from './api'
import { stampTiming } from './timing'
import type { AgentPermission, Approval, Artifact, Attachment, ClawPermission, Engine, Message, PlanCard, PlanCheck, Step, ToolDetail, TouchedFile } from './types'

export type TurnOptions = {
  engine: Engine
  sessionId: string
  messageId: string // the assistant message this turn fills in
  history: Message[] // earlier messages in the session, oldest first
  prompt: string
  attachments: Attachment[]
  signal: AbortSignal
  patch: (change: (message: Message) => Message) => void
  chatModel?: string
  clawModel?: string
  agentPermission: AgentPermission
  clawPermission: ClawPermission
  workspacePath?: string
  /** Where agent runs save files (/api/state output_directory), for the plan card's task folder. */
  outputDirectory?: string
  /** Plan in steps: this model writes the plan; chatModel (or the default) does each step. */
  plannerModel?: string
}

type PlanAnswer = { question: string; answer: string }
type PlanDecision = { approved: boolean; plan: string[]; checks: string[]; planHash?: string; versionHash?: string; answers?: PlanAnswer[] }

/** Plan cards resolve the waiting agent turn through this registry, keyed by message id. */
const planWaiters = new Map<string, (decision: PlanDecision) => void>()
export function resolvePlan(messageId: string, decision: PlanDecision) {
  planWaiters.get(messageId)?.(decision)
  planWaiters.delete(messageId)
}

/** The run currently executing on the PockPock agent, so Stop can cancel it in the backend. */
let activeRunId = ''
export async function cancelActiveRun() {
  if (!activeRunId) return
  await sendJson(`/api/runs/${encodeURIComponent(activeRunId)}/cancel`).catch(() => undefined)
}

function withDocuments(prompt: string, attachments: Attachment[] = []) {
  const docs = attachments.filter((file) => file.kind === 'document')
  return [prompt, ...docs.map((file) => `\n\n[Attached file: ${file.name}]\n${file.text ?? ''}`)].filter(Boolean).join('\n')
}

function addStep(message: Message, step: Omit<Step, 'id'> & { id?: string }, finishRunning = true): Message {
  const steps = (message.steps ?? []).map((item) => finishRunning && item.status === 'running' && !item.id.startsWith('tool:') ? { ...item, status: 'done' as const } : item)
  const id = step.id ?? uid()
  const index = steps.findIndex((item) => item.id === id)
  const next = { ...step, id } as Step
  // An update to an existing step (same id) keeps its start time; its end time is kept while it stays finished.
  if (index >= 0) steps[index] = { ...next, startedAt: steps[index].startedAt, endedAt: next.status === 'running' ? undefined : steps[index].endedAt }
  else steps.push(next)
  return { ...message, steps: steps.slice(-80) }
}

/** Records a file the run used. A later, stronger use (read → edited) replaces the earlier one. */
function touch(message: Message, path: string, kind: TouchedFile['kind']): Message {
  if (!path) return message
  const rank = { read: 0, edited: 1, new: 2 }
  const touched = [...(message.touched ?? [])]
  const index = touched.findIndex((item) => item.path === path)
  if (index >= 0) { if (rank[kind] > rank[touched[index].kind]) touched[index] = { path, kind } }
  else touched.push({ path, kind })
  return { ...message, touched: touched.slice(-200) }
}

/** A flat record of short strings from an event field (tool inputs or results), or undefined. */
function stringRecord(value: unknown): Record<string, string> | undefined {
  if (!value || typeof value !== 'object' || Array.isArray(value)) return undefined
  const entries = Object.entries(value as Record<string, unknown>).slice(0, 16).map(([key, item]) => [key, typeof item === 'string' ? item : JSON.stringify(item) ?? ''] as const)
  return entries.length ? Object.fromEntries(entries.map(([key, item]) => [key, item.length > 600 ? `${item.slice(0, 599)}…` : item])) : undefined
}

/** Adds what a tool call did to its step line (OpenClaw sends it separately from the step itself). */
function withToolDetail(message: Message, stepId: string, detail: ToolDetail): Message {
  const steps = message.steps ?? []
  const index = steps.findIndex((step) => step.id === stepId)
  if (index < 0) return message
  const merged: ToolDetail = { ...steps[index].tool, ...Object.fromEntries(Object.entries(detail).filter(([, value]) => value !== undefined)) } as ToolDetail
  const next = [...steps]
  next[index] = { ...steps[index], tool: merged }
  return { ...message, steps: next }
}

function settleSteps(message: Message, status: Step['status']): Message {
  return { ...message, steps: message.steps?.map((step) => step.status === 'running' ? { ...step, status } : step) }
}

function upsertApproval(message: Message, approval: Approval): Message {
  const approvals = [...(message.approvals ?? [])]
  const index = approvals.findIndex((item) => item.id === approval.id)
  if (index >= 0) approvals[index] = { ...approvals[index], ...approval }
  else approvals.push(approval)
  return { ...message, approvals }
}

function setApprovalStatus(message: Message, id: string, status: Approval['status']): Message {
  return { ...message, approvals: message.approvals?.map((item) => item.id === id ? { ...item, status } : item) }
}

/** Buffers streamed tokens so the UI updates at most every 50 ms. The first token's arrival time is
 * recorded exactly, not when the buffer is flushed. */
function tokenBuffer(patch: TurnOptions['patch']) {
  let pending = ''
  let timer: number | undefined
  let firstAt = 0
  const flush = () => {
    if (timer !== undefined) { window.clearTimeout(timer); timer = undefined }
    if (!pending) return
    const chunk = pending
    const at = firstAt
    pending = ''
    patch((message) => ({
      ...message,
      content: message.content + chunk,
      timing: message.timing && message.timing.firstOutputAt === undefined ? { ...message.timing, firstOutputAt: at } : message.timing,
    }))
  }
  return {
    push(chunk: string) {
      if (!firstAt && chunk) firstAt = Date.now()
      pending += chunk
      if (timer === undefined) timer = window.setTimeout(flush, 50)
    },
    flush,
  }
}

export async function runTurn(options: TurnOptions): Promise<void> {
  // Every change is stamped with the time it was made (captured here, not inside React's state
  // updater, which may run later), so steps, approvals and phases get precise start and end times.
  const patch: TurnOptions['patch'] = (change) => {
    const at = Date.now()
    options.patch((message) => {
      const next = stampTiming(change(message), at)
      // The run bar's "signal" and its slow state count from the newest event.
      return next.timing ? { ...next, timing: { ...next.timing, lastEventAt: at } } : next
    })
  }
  const startedAt = Date.now()
  options.patch((message) => ({ ...message, timing: { startedAt } }))
  const turn = { ...options, patch }
  try {
    if (options.engine === 'chat') return await runChat(turn)
    if (options.engine === 'openclaw') return await runOpenClaw(turn)
    if (options.engine === 'nemoclaw') return await runNemoClaw(turn)
    return await runAgent(turn)
  } finally {
    const endedAt = Date.now()
    options.patch((message) => {
      const settled = stampTiming(message, endedAt)
      return settled.timing ? { ...settled, timing: { ...settled.timing, endedAt } } : settled
    })
  }
}

async function runChat({ history, prompt, attachments, signal, patch, chatModel }: TurnOptions) {
  const messages = [...history.filter((message) => message.role === 'user' || (message.engine === 'chat' && message.content)), { role: 'user', content: prompt, attachments } as Message]
    .slice(-40)
    .map((message) => {
      const images = (message.attachments ?? []).filter((file) => file.kind === 'image' && file.data).map((file) => file.data as string)
      return { role: message.role, content: withDocuments(message.content, message.attachments), ...(images.length ? { images } : {}) }
    })
  const tokens = tokenBuffer(patch)
  try {
    await stream('/api/chat', { messages, model: chatModel || 'auto' }, signal, (event) => {
      if (event.type !== 'token') tokens.flush()
      if (event.type === 'token') tokens.push(text(event.content))
      else if (event.type === 'decision') patch((message) => ({ ...message, model: [text(event.model), text(event.category)].filter(Boolean).join(' · ') }))
      else if (event.type === 'notice') patch((message) => ({ ...message, notice: text(event.message) || message.notice }))
      else if (event.type === 'error') throw new Error(text(event.message) || 'Chat request failed.')
    })
  } finally {
    tokens.flush()
  }
}

function clawStepStatus(status: unknown): Step['status'] {
  return status === 'completed' ? 'done' : status === 'blocked' ? 'blocked' : status === 'running' ? 'running' : 'failed'
}

async function runOpenClaw({ sessionId, prompt, attachments, signal, patch, clawPermission, clawModel, workspacePath }: TurnOptions) {
  const tokens = tokenBuffer(patch)
  try {
    await stream('/api/openclaw/chat', {
      session_id: `pockpock-${sessionId}`,
      message: withDocuments(prompt, attachments),
      permission_mode: clawPermission,
      model: clawModel || undefined,
      workspace_path: workspacePath || undefined,
    }, signal, (event) => {
      if (event.type !== 'token') tokens.flush()
      switch (event.type) {
        case 'token': tokens.push(text(event.content)); break
        case 'replace': patch((message) => ({ ...message, content: text(event.content) || message.content })); break
        case 'decision': patch((message) => ({ ...message, model: text(event.model) })); break
        case 'tool':
          patch((message) => addStep(message, {
            id: `tool:${text(event.id)}`,
            label: text(event.title) || text(event.name) || 'Tool',
            status: event.phase === 'start' ? 'running' : clawStepStatus(event.status),
            detail: text(event.error) || undefined,
          }, false))
          break
        case 'tool_detail':
          patch((message) => withToolDetail(message, `tool:${text(event.id)}`, {
            name: text(event.name),
            command: text(event.command) || undefined,
            input: stringRecord(event.input),
            output: text(event.output) || undefined,
            exitCode: typeof event.exitCode === 'number' ? event.exitCode : undefined,
            durationMs: typeof event.durationMs === 'number' ? event.durationMs : undefined,
            cwd: text(event.cwd) || undefined,
            diff: text(event.diff) || undefined,
          }))
          break
        case 'approval':
          patch((message) => upsertApproval(message, {
            id: text(event.id), source: 'openclaw', title: text(event.title) || 'Approval required', description: text(event.description), status: 'pending',
            // After the turn read web or MCP content, each action is decided on its own (no "Allow for this task").
            grantable: event.untrusted !== true, untrusted: event.untrusted === true,
          }))
          break
        case 'approval_auto':
          patch((message) => addStep(message, { label: `Allowed for this task: ${text(event.title)} ${text(event.description)}`.trim().slice(0, 160), status: 'done' }, false))
          break
        case 'approval_resolved':
          patch((message) => setApprovalStatus(message, text(event.id), event.decision === 'deny' ? 'rejected' : 'approved'))
          break
        case 'approval_error':
          patch((message) => ({ ...message, notice: text(event.message) || 'OpenClaw could not record that decision.' }))
          break
        case 'error':
          if (event.code !== 'aborted') throw new Error(text(event.message) || 'OpenClaw request failed.')
          break
      }
    })
    // A reply that ends normally can still hide actions that failed or were blocked along the way
    // (report 2026-11-22: "some failed but it still shows as succeeded"). Say so under the reply.
    patch((message) => {
      const failed = (message.steps ?? []).filter((step) => step.id.startsWith('tool:') && step.status === 'failed').length
      const blocked = (message.steps ?? []).filter((step) => step.id.startsWith('tool:') && step.status === 'blocked').length
      if (!failed && !blocked) return message
      const parts = [failed ? `${failed} action${failed === 1 ? '' : 's'} failed` : '', blocked ? `${blocked} ${blocked === 1 ? 'was' : 'were'} blocked` : ''].filter(Boolean)
      return { ...message, notice: message.notice || `Finished, but ${parts.join(' and ')} along the way. Check the steps above before relying on the result.` }
    })
  } finally {
    tokens.flush()
    patch((message) => ({ ...settleSteps(message, 'stopped'), approvals: message.approvals?.map((item) => item.status === 'pending' || item.status === 'busy' ? { ...item, status: 'expired' as const } : item) }))
  }
}

async function runNemoClaw({ sessionId, prompt, attachments, signal, patch }: TurnOptions) {
  const tokens = tokenBuffer(patch)
  try {
    await stream('/api/nemoclaw/chat', { session_id: `pockpock-${sessionId}`, message: withDocuments(prompt, attachments) }, signal, (event) => {
      if (event.type !== 'token') tokens.flush()
      if (event.type === 'token') tokens.push(text(event.content))
      else if (event.type === 'decision') patch((message) => ({ ...message, model: text(event.model) }))
      else if (event.type === 'status') patch((message) => addStep(message, { id: 'nemoclaw', label: text(event.message) || 'Working in the sandbox', status: 'running' }))
      else if (event.type === 'done' && event.truncated === true) patch((message) => ({ ...message, notice: 'The reply was cut off at the model output limit. Ask it to continue.' }))
      else if (event.type === 'error') throw new Error(text(event.message) || 'NemoClaw request failed.')
    })
  } finally {
    tokens.flush()
    patch((message) => settleSteps(message, 'done'))
  }
}

type Prepared = {
  plan: string[]
  step_details?: unknown[]
  execution_prompt: string
  selected_model: string
  task_brief: Record<string, unknown>
  critic_review?: { summary?: string; findings?: string[] }
  precheck?: PlanCheck[]
  delegation_plan: unknown
  plan_id: string
  plan_hash: string
  plan_version_hash: string
}

function list(value: unknown) {
  return Array.isArray(value) ? value.map(String) : []
}

type PreparedSequence = {
  plan_id: string
  plan_hash: string
  sequence_plan: { steps: Array<{ id: string; goal: string; tools_allowed?: string[]; done_condition?: Record<string, unknown> }> }
  selected_model: string
  executor_model: string
  step_checks?: string[]
  planner_cloud?: boolean
  executor_cloud?: boolean
}

/**
 * Plan in steps: the planner model writes a checked 2–15 step plan, the step model does one step at a
 * time with only that step's tools, and each step is checked in code before the next starts. The plan
 * is approved or declined as a whole (it cannot be edited: its hash binds the exact steps).
 */
async function runAgentSequence(options: TurnOptions) {
  const { messageId, prompt, signal, patch, agentPermission, chatModel, workspacePath, plannerModel } = options
  const runId = crypto.randomUUID().replaceAll('-', '')
  patch((message) => addStep({ ...message, runId }, { label: `Planning in steps with ${plannerModel}`, status: 'running' }))
  const prepared = await sendJson<PreparedSequence>('/api/agents/plan-sequence', {
    task: prompt,
    source_task: prompt,
    permission_mode: agentPermission,
    preferred_model: chatModel && chatModel !== 'auto' ? chatModel : undefined,
    planner_model: plannerModel,
    workspace_path: workspacePath || undefined,
  }, 'POST', signal)
  const steps = prepared.sequence_plan.steps.map((step) => step.goal)
  const checks = (prepared.step_checks ?? []).map((check, index) => `Step ${index + 1}: ${check}`)
  // Plan in steps: under each step, the tools it may use and how it is checked.
  const stepDetails = prepared.sequence_plan.steps.map((step, index) => [
    step.tools_allowed?.length ? `Uses ${step.tools_allowed.map((tool) => tool.replaceAll('_', ' ')).join(', ')}` : '',
    prepared.step_checks?.[index] ? `Checked by: ${prepared.step_checks[index]}` : '',
  ].filter(Boolean))
  const card: PlanCard = {
    planId: prepared.plan_id,
    planHash: prepared.plan_hash,
    goal: '',
    steps,
    stepDetails,
    checks,
    deliverables: [],
    questions: [],
    critic: '',
    criticFindings: [],
    model: prepared.selected_model,
    workspace: workspacePath || 'A new temporary folder for this task',
    taskFolder: options.outputDirectory ? `${options.outputDirectory}${options.outputDirectory.includes('\\') ? '\\' : '/'}${runId}` : undefined,
    sequence: { planner: prepared.selected_model, executor: prepared.executor_model, cloud: Boolean(prepared.planner_cloud || prepared.executor_cloud) },
    status: 'pending',
  }
  const planReadyAt = Date.now()
  patch((message) => addStep({ ...message, plan: card, model: prepared.executor_model, timing: message.timing && { ...message.timing, planReadyAt: message.timing.planReadyAt ?? planReadyAt } }, { label: `Planned ${steps.length} steps with ${prepared.selected_model}`, status: 'done' }))
  const decision = await new Promise<PlanDecision>((resolve) => {
    const onAbort = () => resolve({ approved: false, plan: steps, checks })
    signal.addEventListener('abort', onAbort, { once: true })
    planWaiters.set(messageId, (result) => { signal.removeEventListener('abort', onAbort); resolve(result) })
  })
  const planDecidedAt = Date.now()
  patch((message) => ({ ...message, timing: message.timing && { ...message.timing, planDecidedAt } }))
  if (signal.aborted) throw new DOMException('Stopped', 'AbortError')
  if (!decision.approved) {
    patch((message) => ({ ...message, content: 'Plan declined. No agent tools were run and nothing was changed.', status: 'done' }))
    return
  }
  patch((message) => addStep(message, { label: `Starting step 1 with ${prepared.executor_model}`, status: 'running' }))
  activeRunId = runId
  const tokens = tokenBuffer(patch)
  try {
    await stream('/api/agents/run-sequence', { plan_id: prepared.plan_id, plan_hash: decision.planHash, run_id: runId }, signal, (raw) => {
      if (raw.type !== 'token') tokens.flush()
      handleAgentEvent(raw, patch, tokens.push)
    })
  } finally {
    tokens.flush()
    activeRunId = ''
  }
}

async function runAgent(options: TurnOptions) {
  const { sessionId, messageId, prompt, attachments, signal, patch, agentPermission, chatModel, workspacePath } = options
  // Plan in steps reads the open folder and the web, but not attached files yet: those turns keep the one-model plan.
  if (options.plannerModel && !attachments.some((file) => file.kind === 'document')) return runAgentSequence(options)
  // The gateway requires a 32-character hex run id.
  const runId = crypto.randomUUID().replaceAll('-', '')
  const files = attachments.filter((file) => file.kind === 'document').map((file) => ({ name: file.name, text: file.text ?? '', size: file.size }))
  patch((message) => addStep({ ...message, runId }, { label: 'Planning and reviewing the task', status: 'running' }))

  // Answering one of the planner's questions plans the task again with the answer; each new plan
  // is reviewed like the first. The request the run is approved for includes the answers.
  const answers: Array<{ question: string; answer: string }> = []
  let request = prompt
  let prepared: Prepared
  let card: PlanCard
  let decision: PlanDecision
  for (;;) {
    request = answers.length ? `${prompt}\n\nAnswers to the planner's questions:\n${answers.map((item) => `- ${item.question} ${item.answer}`).join('\n')}` : prompt
    prepared = await sendJson<Prepared>('/api/agents/plan', {
      task: [request, files.length ? `Attached files: ${files.map((file) => file.name).join(', ')}` : ''].filter(Boolean).join('\n\n'),
      source_task: request,
      permission_mode: agentPermission,
      preferred_model: chatModel && chatModel !== 'auto' ? chatModel : undefined,
      workspace_path: workspacePath || undefined,
    }, 'POST', signal)

    const brief = prepared.task_brief ?? {}
    const questions = brief.requires_clarification === true ? list(brief.clarifying_questions) : []
    card = {
      planId: prepared.plan_id,
      planHash: prepared.plan_hash,
      goal: text(brief.desired_outcome),
      steps: prepared.plan,
      stepDetails: Array.isArray(prepared.step_details) ? prepared.step_details.map((row) => list(row)) : undefined,
      checks: list(brief.success_checks),
      deliverables: list(brief.deliverables),
      questions,
      questionOptions: Array.isArray(brief.question_options) ? (brief.question_options as unknown[]).map((options) => list(options)) : [],
      critic: text(prepared.critic_review?.summary),
      criticFindings: list(prepared.critic_review?.findings),
      model: prepared.selected_model,
      workspace: workspacePath || 'A new temporary folder for this task',
      taskFolder: options.outputDirectory ? `${options.outputDirectory}${options.outputDirectory.includes('\\') ? '\\' : '/'}${runId}` : undefined,
      precheck: Array.isArray(prepared.precheck) ? prepared.precheck : [],
      status: 'pending',
    }
    const planReadyAt = Date.now()
    const shown = card
    patch((message) => addStep({ ...message, plan: shown, model: prepared.selected_model, timing: message.timing && { ...message.timing, planReadyAt: message.timing.planReadyAt ?? planReadyAt } }, { label: `Planned ${shown.steps.length} steps with ${prepared.selected_model}`, status: 'done' }))

    decision = await new Promise<PlanDecision>((resolve) => {
      const onAbort = () => resolve({ approved: false, plan: shown.steps, checks: shown.checks })
      signal.addEventListener('abort', onAbort, { once: true })
      planWaiters.set(messageId, (result) => { signal.removeEventListener('abort', onAbort); resolve(result) })
    })
    if (!decision.answers?.length || signal.aborted) break
    answers.push(...decision.answers)
    const answered = decision.answers
    const label = answered.length === 1 ? `Planning again with your answer: ${answered[0].answer}` : `Planning again with your ${answered.length} answers`
    patch((message) => addStep({ ...message, plan: undefined, earlierPlans: [...(message.earlierPlans ?? []), { ...shown, status: 'replaced' }] }, { label: label.slice(0, 160), status: 'running' }))
  }
  const planDecidedAt = Date.now()
  patch((message) => ({ ...message, timing: message.timing && { ...message.timing, planDecidedAt } }))
  if (signal.aborted) throw new DOMException('Stopped', 'AbortError')
  if (!decision.approved) {
    patch((message) => ({ ...message, content: 'Plan declined. No agent tools were run and nothing was changed.', status: 'done' }))
    return
  }

  const planHistory = [
    { version: 1, status: 'proposed', plan: prepared.plan, success_checks: list(prepared.task_brief?.success_checks), rationale: card.critic.slice(0, 240), plan_hash: prepared.plan_version_hash },
    { version: 2, status: 'approved', plan: decision.plan, success_checks: decision.checks, rationale: 'User approved the plan in PockPock Agent.', plan_hash: decision.versionHash },
  ]
  const executionPrompt = `${prepared.execution_prompt}\n\nApproved plan:\n${decision.plan.map((step, index) => `${index + 1}. ${step}`).join('\n')}\n\nApproved success checks:\n${decision.checks.map((check) => `- ${check}`).join('\n')}`
  patch((message) => addStep(message, { label: 'Starting the approved task', status: 'running' }))
  activeRunId = runId
  const tokens = tokenBuffer(patch)
  try {
    await stream('/api/agents/run', {
      task: executionPrompt,
      source_task: request,
      preferred_model: prepared.selected_model,
      files,
      conversation_id: sessionId,
      run_id: runId,
      permission_mode: agentPermission,
      workspace_path: workspacePath || undefined,
      plan: decision.plan,
      success_checks: decision.checks,
      task_brief: prepared.task_brief,
      plan_history: planHistory,
      plan_id: prepared.plan_id,
      plan_hash: decision.planHash,
      delegation_plan: prepared.delegation_plan,
    }, signal, (raw) => {
      if (raw.type !== 'token') tokens.flush()
      const event: StreamEvent = raw.type === 'delegate_event' && raw.child_event && typeof raw.child_event === 'object' ? raw.child_event as StreamEvent : raw
      handleAgentEvent(event, patch, tokens.push)
    })
  } finally {
    tokens.flush()
    activeRunId = ''
  }
}

function handleAgentEvent(event: StreamEvent, patch: TurnOptions['patch'], pushToken: (chunk: string) => void) {
  const type = text(event.type)
  if (type.startsWith('approval_') && type !== 'approval_requested' && event.approval_id) {
    const outcome = type.replace('approval_', '')
    patch((message) => setApprovalStatus(message, text(event.approval_id), outcome === 'approved' ? 'approved' : outcome === 'rejected' ? 'rejected' : 'expired'))
    return
  }
  switch (type) {
    case 'token': pushToken(text(event.content)); break
    case 'usage': {
      const promptTokens = Number(event.prompt_tokens)
      if (!Number.isFinite(promptTokens)) break
      const completion = Number(event.completion_tokens)
      const window = Number(event.context_window)
      patch((message) => ({ ...message, usage: { promptTokens, completionTokens: Number.isFinite(completion) ? completion : undefined, contextWindow: Number.isFinite(window) && window > 0 ? window : message.usage?.contextWindow } }))
      break
    }
    case 'note': patch((message) => {
      const notes = [...(message.notes ?? [])]
      const index = notes.findIndex((note) => note.status === 'queued' && note.text === text(event.text))
      if (index >= 0) notes[index] = { ...notes[index], status: 'given' }
      return addStep({ ...message, notes }, { label: `Your note was given to the agent: ${text(event.text)}`.slice(0, 160), status: 'done' }, false)
    }); break
    case 'plan_step': {
      const step = Number(event.step)
      const total = Number(event.total)
      if (!Number.isInteger(step) || !Number.isInteger(total) || step < 1 || step > total || total > 50) break
      patch((message) => ({ ...message, planStep: { step, total, label: text(event.label).slice(0, 160) } }))
      break
    }
    case 'sequence_check': {
      // The attempt is over: what was running for it ends as the check says, not as done regardless.
      const stepNumber = Number(event.step)
      patch((message) => addStep({
        ...settleSteps(message, event.passed ? 'done' : 'failed'),
        stepChecks: Number.isInteger(stepNumber) && stepNumber > 0 ? { ...message.stepChecks, [stepNumber]: event.passed === true } : message.stepChecks,
      }, { label: text(event.message) || `Step ${stepNumber} checked`, status: event.passed ? 'done' : 'failed' }, false))
      break
    }
    case 'sequence_retry':
      // Added without finishing other lines: a retry is not proof that the earlier attempt worked.
      patch((message) => addStep(message, { label: text(event.message) || `Trying step ${Number(event.step)} again`, status: 'running' }, false))
      break
    case 'tool_selection': {
      // OpenClaw tool retrieval: how many skills (and MCP servers) this message was offered.
      const offered = Number(event.skills_offered)
      const total = Number(event.skills_total)
      const servers = Number(event.servers_total) > 1 ? ` and ${Number(event.servers_offered)} of ${Number(event.servers_total)} MCP servers` : ''
      if (Number.isFinite(offered) && Number.isFinite(total)) patch((message) => addStep(message, { label: `Offered OpenClaw ${offered} of ${total} skills${servers} that fit this request`, status: 'done' }, false))
      break
    }
    case 'approval_auto': patch((message) => addStep(message, { label: text(event.message) || 'Allowed for this task', status: 'done' }, false)); break
    case 'verifying': patch((message) => ({ ...addStep(message, { label: text(event.message) || 'Checking the success checks', status: 'running' }), verifying: true })); break
    case 'status': patch((message) => addStep(message, { label: text(event.message) || 'Working', status: 'running' })); break
    case 'decision': patch((message) => ({ ...addStep(message, { label: `Using ${text(event.model) || 'a local model'}`, status: 'done' }), model: text(event.model) || message.model })); break
    case 'tool_start': patch((message) => addStep(message, {
      id: `tool:${text(event.tool)}:${text(event.sequence) || uid()}`, label: text(event.message) || text(event.tool).replaceAll('_', ' ') || 'Running a tool', status: 'running',
      tool: { name: text(event.tool), input: stringRecord(event.input) },
    })); break
    case 'tool_result':
      if (event.status === 'success' && text(event.tool) === 'read_project_file') {
        const details = event.details && typeof event.details === 'object' ? event.details as Record<string, unknown> : {}
        if (text(details.path)) patch((message) => touch(message, text(details.path), 'read'))
      }
      patch((message) => {
        const steps = [...(message.steps ?? [])]
        const tool = text(event.tool)
        for (let index = steps.length - 1; index >= 0; index -= 1) {
          if (steps[index].status === 'running' && steps[index].id.startsWith(`tool:${tool}:`)) {
            const details = stringRecord(event.details)
            const error = event.error && typeof event.error === 'object' ? text((event.error as Record<string, unknown>).message) : text(event.error)
            steps[index] = {
              ...steps[index], label: text(event.message) || steps[index].label, status: event.status === 'success' ? 'done' : 'failed',
              tool: { ...(steps[index].tool ?? { name: tool }), output: details ? Object.entries(details).map(([key, value]) => `${key}: ${value}`).join('\n').slice(0, 2000) : undefined, error: error || undefined },
            }
            return { ...message, steps }
          }
        }
        return addStep(message, { label: text(event.message) || tool, status: event.status === 'success' ? 'done' : 'failed' }, false)
      })
      break
    case 'browser_open': patch((message) => addStep(message, { label: `Opened ${text(event.url)}`, status: 'done' }, false)); break
    case 'browser_action': patch((message) => addStep(message, { label: `Browser ${text(event.action) || 'action'} ${text(event.name)}`.trim(), status: 'done' }, false)); break
    case 'browser_observation': patch((message) => addStep(message, { label: `Read ${text(event.title) || text(event.url)}`, status: 'done' }, false)); break
    case 'command_start': patch((message) => addStep(message, { label: `Ran ${text(event.command) || 'a command'}`, status: 'done' }, false)); break
    case 'plan_revision': patch((message) => addStep(message, { label: event.status === 'stopped' ? 'Stopped replanning' : `Revised the plan: ${text(event.rationale)}`.slice(0, 160), status: 'done' }, false)); break
    case 'delegate_status': patch((message) => addStep(message, { id: `delegate:${text(event.child_run_id) || text(event.role)}`, label: `${text(event.role) || 'Helper'}: ${text(event.purpose)}`.slice(0, 160), status: event.status === 'completed' ? 'done' : event.status === 'failed' ? 'failed' : 'running' }, false)); break
    case 'approval_requested': {
      const action = event.action && typeof event.action === 'object' ? event.action as Record<string, unknown> : {}
      const browser = action.tool === 'browser_action' || action.tool === 'browser_recipe_step'
      patch((message) => upsertApproval(message, {
        id: text(event.approval_id),
        source: 'agent',
        runId: text(event.run_id),
        actionHash: text(event.action_hash),
        title: text(event.message) || (browser ? 'Browser action' : 'File change'),
        description: browser
          ? `${text(action.action) || 'action'} → ${text(action.target) || 'current page'}${text(action.summary) ? ` · ${text(action.summary)}` : ''}`
          : `${text(action.path) || 'Workspace change'}${text(action.summary) ? ` · ${text(action.summary)}` : ''}`,
        diff: text(action.diff) || undefined,
        grantable: event.grantable === true,
        status: 'pending',
      }))
      break
    }
    case 'research_sources': {
      const evidence = Array.isArray(event.evidence) ? event.evidence as Array<Record<string, unknown>> : []
      const sources = (Array.isArray(event.sources) ? event.sources as Array<Record<string, unknown>> : []).map((source) => ({
        source_id: text(source.source_id),
        title: text(source.title) || text(source.canonical_url),
        url: text(source.canonical_url),
        excerpt: text(evidence.find((item) => item.source_id === source.source_id)?.excerpt).slice(0, 400),
      }))
      const errors = (Array.isArray(event.errors) ? event.errors as Array<Record<string, unknown>> : []).map((item) => text(item.message) || 'A source could not be retrieved.')
      patch((message) => ({ ...message, research: [...(message.research ?? []), { taskId: text(event.task_id), query: text(event.query), sources, errors }] }))
      break
    }
    case 'patch':
      if (event.status === 'applied' && text(event.path)) {
        patch((message) => touch(message.changes?.some((item) => item.path === text(event.path)) ? message : { ...message, changes: [...(message.changes ?? []), { path: text(event.path), summary: text(event.summary) || text(event.message) }] }, text(event.path), 'edited'))
      }
      break
    case 'command_result':
      patch((message) => addStep(message, { label: `${event.status === 'success' || event.exit_code === 0 ? 'Command finished' : 'Command failed'}: ${text(event.command)}`.slice(0, 160), status: event.status === 'success' || event.exit_code === 0 ? 'done' : 'failed' }, false))
      break
    case 'artifact': {
      const artifact: Artifact = { name: text(event.name), path: text(event.path), url: text(event.url), kind: text(event.kind) }
      if (['answer.md', 'run_report.md', 'task_brief.json'].includes(artifact.name)) break
      patch((message) => touch(message.artifacts?.some((item) => item.path === artifact.path) ? message : { ...message, artifacts: [...(message.artifacts ?? []), artifact] }, artifact.name || artifact.path, 'new'))
      break
    }
    case 'done':
      patch((message) => ({
        ...settleSteps(message, 'done'),
        workspacePath: text(event.workspace_path) || message.workspacePath,
        taskFolder: text(event.task_folder) || message.taskFolder,
        taskId: text(event.task_id) || message.taskId,
        notice: event.status === 'partial' ? 'Finished, but not every success check was met.' : message.notice,
      }))
      break
    case 'error': case 'timed_out': case 'interrupted':
      throw new Error(text(event.message) || (type === 'timed_out' ? 'The agent run timed out.' : 'The agent run failed.'))
    case 'cancelled':
      throw new DOMException('Stopped', 'AbortError')
  }
}

/** Sends an approval decision for an OpenClaw tool call or a PockPock agent action. */
export async function decideApproval(approval: Approval, allow: boolean, scope: 'once' | 'task' = 'once') {
  if (approval.source === 'openclaw') {
    await sendJson('/api/openclaw/approvals', { approval_id: approval.id, decision: !allow ? 'deny' : scope === 'task' ? 'allow-task' : 'allow-once' })
    return
  }
  const result = await sendJson<{ accepted?: boolean; detail?: string }>(
    `/api/runs/${encodeURIComponent(approval.runId ?? '')}/approvals/${encodeURIComponent(approval.id)}`,
    { action_hash: approval.actionHash, decision: allow ? 'approved' : 'rejected', scope },
  )
  if (!result.accepted) throw new Error(result.detail || 'This approval is no longer available.')
}

/** Answers the planner's questions: declines this plan in the backend, then the turn plans again with all the answers. */
/** Sends the answers to the planner's questions together; the task is planned again once, with all of them. */
export async function answerPlan(messageId: string, plan: PlanCard, answers: PlanAnswer[]) {
  const given = answers.map((item) => ({ question: item.question, answer: item.answer.trim() })).filter((item) => item.answer)
  if (!given.length) return
  try {
    await sendJson(`/api/agents/plans/${encodeURIComponent(plan.planId)}/decision`, { action_hash: plan.planHash, decision: 'rejected', plan: plan.steps, success_checks: plan.checks })
  } catch { /* An expired plan needs no decline; the new plan replaces it either way. */ }
  resolvePlan(messageId, { approved: false, plan: plan.steps, checks: plan.checks, answers: given })
}

/** Sends a note to the running PockPock Agent task; it reaches the model before its next step. */
export async function sendRunNote(text: string) {
  if (!activeRunId) throw new Error('The task is not running any more. Send it as a new message.')
  await sendJson(`/api/runs/${encodeURIComponent(activeRunId)}/notes`, { text })
}

/** Approves or declines a PockPock plan in the backend, then releases the waiting turn. */
export async function decidePlan(messageId: string, plan: PlanCard, approved: boolean, steps: string[], checks: string[]) {
  const result = await sendJson<{ accepted?: boolean; approved_plan_hash?: string; approved_version_hash?: string; detail?: string }>(
    `/api/agents/plans/${encodeURIComponent(plan.planId)}/decision`,
    { action_hash: plan.planHash, decision: approved ? 'approved' : 'rejected', plan: steps, success_checks: checks },
  )
  if (!result.accepted) throw new Error(result.detail || 'This plan can no longer be approved.')
  // A plan in steps has no version history, so only its approved hash comes back.
  if (approved && (!result.approved_plan_hash || (!plan.sequence && !result.approved_version_hash))) throw new Error('The approved plan did not return a valid execution ticket. Send the task again.')
  resolvePlan(messageId, { approved, plan: steps, checks, planHash: result.approved_plan_hash, versionHash: result.approved_version_hash })
}
