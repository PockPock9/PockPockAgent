import { useCallback, useEffect, useRef, useState } from 'react'
import type { FormEvent } from 'react'
import {
  Activity,
  ArrowDown,
  Bot,
  CircleHelp,
  FileImage,
  FileText,
  Globe2,
  Paperclip,
  Play,
  RefreshCw,
  Shield,
  Sparkles,
  X,
} from 'lucide-react'
import ReactMarkdown, { type Components } from 'react-markdown'
import remarkGfm from 'remark-gfm'
import { StatusMark } from '../models/ModelControls'
import type { AppState } from '../models/modelTypes'
import { formatBytes } from '../models/modelUtils'
import type {
  AgentArtifact,
  AgentFile,
  AgentStatus,
  PlanDecision,
  RoutedTask,
} from './agentTypes'
import type { Attachment } from '../chat/chatTypes'

function uid() {
  return crypto.randomUUID()
}

type CriticReview = {
  contract_version: 1
  status: 'approved' | 'revised'
  revision_count: number
  findings: string[]
  summary: string
}

function isCriticReview(value: unknown): value is CriticReview {
  if (!value || typeof value !== 'object' || Array.isArray(value)) return false
  const review = value as Record<string, unknown>
  return review.contract_version === 1
    && (review.status === 'approved' || review.status === 'revised')
    && Number.isInteger(review.revision_count)
    && typeof review.summary === 'string'
    && Array.isArray(review.findings)
    && review.findings.every((finding) => typeof finding === 'string')
}

export function AgentWorkbench({
  state,
  autoStartTask,
  onTranscriptUpdate,
  onTranscriptEvent,
  onStopChange,
  onPlanDecisionRequest,
  markdownComponents,
}: {
  state: AppState
  autoStartTask: RoutedTask | null
  onTranscriptUpdate: (runId: string, text: string, sequence?: number, final?: boolean) => void
  onTranscriptEvent: (runId: string, event: Record<string, unknown>) => void
  onStopChange: (stop: (() => void) | null) => void
  onPlanDecisionRequest: (runId: string, resolver: (decision: PlanDecision) => void) => void
  markdownComponents: Components
}) {
  const [task, setTask] = useState('')
  const [files, setFiles] = useState<AgentFile[]>([])
  const [artifacts, setArtifacts] = useState<AgentArtifact[]>([])
  const [activity, setActivity] = useState<Array<{ id: string; label: string; status: string }>>([])
  const [answer, setAnswer] = useState('')
  const [error, setError] = useState('')
  const [running, setRunning] = useState(false)
  const [uploading, setUploading] = useState(false)
  const [model, setModel] = useState('')
  const [imageEngine, setImageEngine] = useState('Checking')
  const [localAccess, setLocalAccess] = useState<'checking' | 'allowed' | 'denied'>('checking')
  const uploadRef = useRef<HTMLInputElement>(null)
  const abortRef = useRef<AbortController | null>(null)
  const activeRunIdRef = useRef<string | null>(null)
  const autoStartedTaskId = useRef('')

  const stopRun = useCallback(async () => {
    const runId = activeRunIdRef.current
    if (!runId) {
      abortRef.current?.abort()
      return
    }
    try {
      const response = await fetch(`/api/runs/${encodeURIComponent(runId)}/cancel`, { method: 'POST' })
      if (!response.ok) throw new Error('The run could not be cancelled through the local API')
      const result = await response.json() as { accepted?: boolean; status?: string }
      if (!result.accepted && ['running', 'cancelling'].includes(String(result.status)) && activeRunIdRef.current === runId) {
        abortRef.current?.abort()
      }
    } catch {
      abortRef.current?.abort()
    } finally {
      if (activeRunIdRef.current === runId) abortRef.current?.abort()
    }
  }, [])

  useEffect(() => {
    onStopChange(running ? () => { void stopRun() } : null)
    return () => onStopChange(null)
  }, [onStopChange, running, stopRun])

  useEffect(() => {
    let active = true
    void fetch('/api/agents/status', { cache: 'no-store' }).then(async (response) => {
      if (!response.ok) throw new Error('Local-only agent access is unavailable in this browser')
      const status = await response.json() as AgentStatus
      if (!active) return
      setLocalAccess('allowed')
      setImageEngine(status.image_engine.available ? status.image_engine.engine ?? 'Available' : 'Not running')
    }).catch(() => {
      if (!active) return
      setLocalAccess('denied')
      setImageEngine('Local check required')
    })
    return () => {
      active = false
      abortRef.current?.abort()
    }
  }, [])

  const uploadFiles = async (incoming: FileList | File[]) => {
    if (!incoming.length) return
    if (files.length + incoming.length > 5) {
      setError('Attach no more than five files to one task.')
      return
    }
    setUploading(true)
    setError('')
    const form = new FormData()
    Array.from(incoming).forEach((file) => form.append('files', file))
    try {
      const response = await fetch('/api/files', { method: 'POST', body: form })
      const result = await response.json()
      if (!response.ok) throw new Error(result.detail || 'File upload failed')
      const received = result.files as Attachment[]
      if (received.some((file) => file.kind !== 'document')) {
        throw new Error('Agent tasks accept documents and text files. Use Conversations to analyze images.')
      }
      setFiles((previous) => [...previous, ...received.map((file) => ({
        name: file.name,
        text: file.text ?? '',
        size: file.size,
      }))])
    } catch (uploadError) {
      setError(uploadError instanceof Error ? uploadError.message : 'File upload failed')
    } finally {
      setUploading(false)
      if (uploadRef.current) uploadRef.current.value = ''
    }
  }

  const runTask = useCallback(async (event?: FormEvent, routedTask?: RoutedTask) => {
    event?.preventDefault()
    const taskText = routedTask?.task ?? task
    const taskFiles = routedTask?.files ?? files
    if (running || !taskText.trim()) return
    if (localAccess !== 'allowed') {
      setError('Agent tasks can only be started from the local dashboard on this PC.')
      return
    }
    if (!state.router_enabled || !state.connected) {
      setError('Start the Smart Router and connect Ollama before running an agent task.')
      return
    }

    const runId = routedTask?.id ?? uid().replaceAll('-', '')
    activeRunIdRef.current = runId
    setRunning(true)
    setError('')
    setAnswer('')
    setModel('')
    setArtifacts([])
    setActivity([])
    abortRef.current = new AbortController()
    let terminalEventReported = false
    let pendingTokens = ''
    let pendingTokenSequence: number | undefined
    let tokenFlushTimer: number | undefined
    const flushTokens = () => {
      if (tokenFlushTimer !== undefined) {
        window.clearTimeout(tokenFlushTimer)
        tokenFlushTimer = undefined
      }
      if (!pendingTokens) return
      const content = pendingTokens
      const sequence = pendingTokenSequence
      pendingTokens = ''
      pendingTokenSequence = undefined
      if (routedTask) onTranscriptUpdate(runId, content, sequence)
      else setAnswer((previous) => previous + content)
    }
    if (routedTask) {
      onTranscriptEvent(runId, { type: 'planning_started', run_id: runId })
    }
    try {
      let executionPrompt = taskText.trim()
      let chosenModel = routedTask?.preferredModel
      const planningResponse = await fetch('/api/agents/plan', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        signal: abortRef.current.signal,
        body: JSON.stringify({
          task: [taskText.trim(), taskFiles.length ? `Attached files: ${taskFiles.map((file) => file.name).join(', ')}` : ''].filter(Boolean).join('\n\n'),
          source_task: taskText.trim(),
          permission_mode: routedTask?.permissionMode ?? 'auto-review',
          preferred_model: chosenModel,
          workspace_path: routedTask?.workspacePath,
        }),
      })
      if (!planningResponse.ok) {
        const result = await planningResponse.json()
        throw new Error(result.detail || `Planning failed (${planningResponse.status})`)
      }
      const prepared = await planningResponse.json() as {
        plan: string[]
        execution_prompt: string
        selected_model: string
        reason: string
        task_brief: Record<string, unknown>
        critic_review?: unknown
        delegation_plan: { contract_version: 1; subtasks: Array<Record<string, unknown>> }
        plan_id: string
        plan_hash: string
        plan_version_hash: string
      }
      if (!isCriticReview(prepared.critic_review)) {
        throw new Error('The planner response is missing its critic review. Restart the PockPock AI backend and start a new task.')
      }
      let approvedPlan = prepared.plan
      let approvedChecks = Array.isArray(prepared.task_brief?.success_checks) ? prepared.task_brief.success_checks.map(String) : []
      let approvedPlanId = ''
      let approvedPlanHash = ''
      let approvedPlanVersionHash = ''
      chosenModel = prepared.selected_model
      if (routedTask) {
        onTranscriptEvent(runId, { type: 'plan', run_id: runId, plan_pending: true, ...prepared, workspace: routedTask.workspacePath || 'Temporary workspace for this task' })
        const decision = await new Promise<PlanDecision>((resolve) => {
          const abort = () => resolve({ decision: 'rejected', plan: prepared.plan, successChecks: approvedChecks })
          abortRef.current?.signal.addEventListener('abort', abort, { once: true })
          onPlanDecisionRequest(runId, (result) => {
            abortRef.current?.signal.removeEventListener('abort', abort)
            resolve(result)
          })
        })
        if (abortRef.current?.signal.aborted) {
          onTranscriptEvent(runId, { type: 'plan_rejected', run_id: runId, plan: prepared.plan, success_checks: approvedChecks, message: 'Plan review stopped; no agent tools were run.' })
          throw new DOMException('Plan review stopped', 'AbortError')
        }
        approvedPlan = decision.plan
        approvedChecks = decision.successChecks
        const accepted = decision.decision === 'approved'
        onTranscriptEvent(runId, { type: accepted ? 'plan_approved' : 'plan_rejected', run_id: runId, plan: approvedPlan, success_checks: approvedChecks, message: accepted ? 'Approved plan will be executed.' : 'Plan declined; no agent tools were run.' })
        if (!accepted) {
          onTranscriptUpdate(runId, '**Plan declined. No agent tools were run and no workspace changes were made.**', undefined, true)
          return
        }
        if (!decision.planId || !decision.planHash || !decision.versionHash) throw new Error('The approved plan did not return a valid execution ticket. Create and approve a fresh plan.')
        approvedPlanId = decision.planId
        approvedPlanHash = decision.planHash
        approvedPlanVersionHash = decision.versionHash
      }
      executionPrompt = `${prepared.execution_prompt}\n\nApproved plan:\n${approvedPlan.map((step, index) => `${index + 1}. ${step}`).join('\n')}\n\nApproved success checks:\n${approvedChecks.map((check) => `- ${check}`).join('\n')}`
      const criticRationale = [prepared.critic_review.summary, ...prepared.critic_review.findings].join(' ').slice(0, 240)
      const planHistory = [
        { version: 1, status: 'proposed', plan: prepared.plan, success_checks: Array.isArray(prepared.task_brief?.success_checks) ? prepared.task_brief.success_checks.map(String) : [], rationale: criticRationale, plan_hash: prepared.plan_version_hash },
        { version: 2, status: 'approved', plan: approvedPlan, success_checks: approvedChecks, rationale: JSON.stringify(approvedPlan) === JSON.stringify(prepared.plan) && JSON.stringify(approvedChecks) === JSON.stringify(prepared.task_brief?.success_checks) ? 'User approved the proposed plan.' : 'User edited and approved the plan.', plan_hash: approvedPlanVersionHash },
      ]
      setActivity([{ id: uid(), label: `Planned task with ${prepared.selected_model}`, status: 'success' }])
      if (routedTask) onTranscriptEvent(runId, { type: 'execution_started', run_id: runId })
      const response = await fetch('/api/agents/run', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        signal: abortRef.current.signal,
        body: JSON.stringify({ task: executionPrompt, source_task: routedTask?.sourceTask ?? taskText.trim(), preferred_model: chosenModel, files: taskFiles, conversation_id: routedTask?.conversationId, run_id: runId, permission_mode: routedTask?.permissionMode ?? 'auto-review', workspace_path: routedTask?.workspacePath, plan: approvedPlan, success_checks: approvedChecks, task_brief: prepared.task_brief, plan_history: planHistory, plan_id: approvedPlanId, plan_hash: approvedPlanHash, delegation_plan: prepared.delegation_plan }),
      })
      if (!response.ok) {
        const result = await response.json()
        throw new Error(result.detail || `Agent task failed (${response.status})`)
      }
      if (!response.body) throw new Error('The local API did not open an agent task stream')
      const reader = response.body.getReader()
      const decoder = new TextDecoder()
      let buffer = ''
      const handleEvent = (data: string) => {
        if (!data) return
        let chunk: Record<string, unknown>
        try {
          chunk = JSON.parse(data) as Record<string, unknown>
        } catch (parseError) {
          console.error('Invalid local agent event:', parseError)
          setError('The local agent returned an invalid progress event.')
          return
        }
        if (chunk.type !== 'token') flushTokens()
        if (['done', 'error', 'cancelled', 'timed_out', 'interrupted'].includes(String(chunk.type))) {
          terminalEventReported = true
        }
        if (routedTask && chunk.type !== 'token') onTranscriptEvent(runId, chunk)
        if (chunk.type === 'status' && typeof chunk.message === 'string') {
          setActivity((previous) => [...previous, { id: uid(), label: chunk.message as string, status: 'active' }])
        } else if (chunk.type === 'decision') {
          setModel(String(chunk.model || ''))
          setActivity((previous) => previous.map((item) => item.status === 'active' ? { ...item, status: 'success' } : item))
          setActivity((previous) => [...previous, { id: uid(), label: `Smart route · ${String(chunk.model || 'local model')}`, status: 'success' }])
        } else if (chunk.type === 'tool_start') {
          setActivity((previous) => [...previous, { id: uid(), label: String(chunk.message || chunk.tool || 'Running local tool'), status: 'active' }])
        } else if (chunk.type === 'tool_result') {
          setActivity((previous) => {
            const next = [...previous]
            let index = -1
            for (let itemIndex = next.length - 1; itemIndex >= 0; itemIndex -= 1) {
              if (next[itemIndex].status === 'active' && next[itemIndex].label.toLowerCase().includes(String(chunk.tool || '').replaceAll('_', ' '))) {
                index = itemIndex
                break
              }
            }
            if (index >= 0) next[index] = {
              ...next[index],
              label: String(chunk.message || next[index].label),
              status: chunk.status === 'success' ? 'success' : 'error',
            }
            return next
          })
        } else if (chunk.type === 'token' && typeof chunk.content === 'string') {
          pendingTokens += chunk.content
          const sequence = Number(chunk.sequence)
          if (Number.isFinite(sequence)) pendingTokenSequence = sequence
          if (tokenFlushTimer === undefined) tokenFlushTimer = window.setTimeout(flushTokens, 50)
        } else if (chunk.type === 'artifact') {
          const artifact = chunk as unknown as AgentArtifact
          setArtifacts((previous) => previous.some((item) => item.path === artifact.path) ? previous : [...previous, artifact])
        } else if (chunk.type === 'error') {
          setError(String(chunk.message || 'Agent task failed'))
          setActivity((previous) => [
            ...previous.map((item) => item.status === 'active' ? { ...item, status: 'error' } : item),
            { id: uid(), label: String(chunk.message || 'Task failed'), status: 'error' },
          ])
        } else if (chunk.type === 'cancelled') {
          setActivity((previous) => [
            ...previous.map((item) => item.status === 'active' ? { ...item, status: 'error' } : item),
            { id: uid(), label: 'Task cancelled', status: 'error' },
          ])
          if (routedTask) onTranscriptUpdate(runId, '**Agent stopped.**', Number(chunk.sequence), true)
        } else if (chunk.type === 'timed_out' || chunk.type === 'interrupted') {
          const message = String(chunk.message || (chunk.type === 'timed_out' ? 'The agent run timed out.' : 'The agent run was interrupted.'))
          setError(message)
          setActivity((previous) => [
            ...previous.map((item) => item.status === 'active' ? { ...item, status: 'error' } : item),
            { id: uid(), label: message, status: 'error' },
          ])
          if (routedTask) onTranscriptUpdate(runId, `**Task failed:** ${message}`, Number(chunk.sequence), true)
        } else if (chunk.type === 'done') {
          setActivity((previous) => [
            ...previous.map((item) => item.status === 'active' ? { ...item, status: 'success' } : item),
            { id: uid(), label: chunk.status === 'partial' ? 'Task complete · Partial' : 'Task complete', status: chunk.status === 'partial' ? 'error' : 'success' },
          ])
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
    } catch (taskError) {
      flushTokens()
      if (taskError instanceof DOMException && taskError.name === 'AbortError') {
        if (routedTask && !terminalEventReported) {
          onTranscriptEvent(runId, { type: 'cancelled', run_id: runId, message: 'Task stopped.' })
          terminalEventReported = true
        }
        setActivity((previous) => [
          ...previous.map((item) => item.status === 'active' ? { ...item, status: 'error' } : item),
          { id: uid(), label: 'Task stopped', status: 'error' },
        ])
        if (routedTask) onTranscriptUpdate(runId, '**Agent stopped.**', undefined, true)
      } else {
        const message = taskError instanceof Error ? taskError.message : 'Agent task failed'
        if (routedTask && !terminalEventReported) {
          onTranscriptEvent(runId, { type: 'error', run_id: runId, message })
          terminalEventReported = true
        }
        setError(message)
        if (routedTask) onTranscriptUpdate(runId, `**Task failed:** ${message}`, undefined, true)
      }
    } finally {
      flushTokens()
      abortRef.current = null
      activeRunIdRef.current = null
      setRunning(false)
    }
  }, [files, localAccess, onPlanDecisionRequest, onTranscriptEvent, onTranscriptUpdate, running, state.connected, state.router_enabled, task])

  useEffect(() => {
    if (!autoStartTask || localAccess !== 'allowed' || autoStartedTaskId.current === autoStartTask.id) return
    autoStartedTaskId.current = autoStartTask.id
    setTask(autoStartTask.task)
    setFiles(autoStartTask.files)
    void runTask(undefined, autoStartTask)
  }, [autoStartTask, localAccess, runTask])

  useEffect(() => {
    if (!autoStartTask || localAccess !== 'denied' || autoStartedTaskId.current === autoStartTask.id) return
    autoStartedTaskId.current = autoStartTask.id
    onTranscriptUpdate(autoStartTask.id, '**Agent unavailable:** open this local dashboard in a browser on this PC to start local tools.', undefined, true)
  }, [autoStartTask, localAccess, onTranscriptUpdate])

  return (
    <div className="page agent-page">
      <div className="page-title">
        <div>
          <div className="eyebrow"><span className="eyebrow__rule" />Local / Bounded execution</div>
          <h1>Agent workbench<span>.</span></h1>
          <p>Describe the outcome. A routed local model plans, uses approved tools, and reports what it did.</p>
        </div>
        <div className={`agent-access-chip${localAccess === 'allowed' ? ' agent-access-chip--on' : ''}`}>
          <StatusMark online={localAccess === 'allowed'} />{localAccess === 'allowed' ? 'This PC' : localAccess === 'denied' ? 'Local browser required' : 'Checking local access'}
        </div>
      </div>

      <div className="agent-capability-grid">
        <article className="panel agent-capability">
          <Globe2 size={16} />
          <div><strong>Public web research</strong><small>Up to 5 same-site text pages · no media downloads</small></div>
          <span className="agent-capability__state">Ready</span>
        </article>
        <article className="panel agent-capability">
          <FileText size={16} />
          <div><strong>FILES &amp; OFFICE</strong><small>Selected documents · isolated output folder</small></div>
          <span className="agent-capability__state">Ready</span>
        </article>
        <article className="panel agent-capability">
          <FileImage size={16} />
          <div><strong>Local image engine</strong><small>{imageEngine === 'Not running' ? 'No compatible local engine detected' : imageEngine}</small></div>
          <span className={`agent-capability__state${imageEngine === 'Not running' ? ' agent-capability__state--off' : ''}`}>{imageEngine === 'Not running' ? 'Offline' : imageEngine === 'Checking' ? 'Checking' : 'Local'}</span>
        </article>
      </div>

      <form className="agent-composer panel" onSubmit={(event) => void runTask(event)}>
        <div className="agent-composer__head">
          <div><Bot size={15} /><span>New task</span></div>
          <span>Smart model · Approved tools only</span>
        </div>
        <textarea
          value={task}
          onChange={(event) => setTask(event.target.value)}
          placeholder={'Example: Search example.com for its return policy and summarize the relevant pages.\nOr: Turn the attached spreadsheet into a summary and a new Word report.'}
          aria-label="Describe an agent task"
          rows={5}
          disabled={running}
        />
        {files.length > 0 && (
          <div className="agent-files">
            {files.map((file, index) => (
              <div className="agent-file" key={`${file.name}-${index}`}>
                <FileText size={13} /><span>{file.name}</span><small>{formatBytes(file.size)}</small>
                <button type="button" onClick={() => setFiles((previous) => previous.filter((_, itemIndex) => itemIndex !== index))} aria-label={`Remove ${file.name}`}><X size={12} /></button>
              </div>
            ))}
          </div>
        )}
        {error && <div className="agent-error" role="alert"><CircleHelp size={13} /><span>{error}</span><button type="button" onClick={() => setError('')} aria-label="Dismiss error"><X size={12} /></button></div>}
        <div className="agent-composer__foot">
          <input
            ref={uploadRef}
            type="file"
            multiple
            accept=".pdf,.docx,.xlsx,.pptx,.txt,.md,.csv,.json,.xml,.html,.log"
            hidden
            onChange={(event) => void uploadFiles(event.target.files ?? [])}
          />
          <div className="agent-composer__tools">
            <button type="button" className="icon-button" onClick={() => uploadRef.current?.click()} disabled={uploading || running} aria-label="Attach documents">
              {uploading ? <RefreshCw size={14} className="spin" /> : <Paperclip size={14} />}
            </button>
            <span>PDF · DOCX · XLSX · PPTX · Text</span>
            {model && <span className="agent-model-label"><Sparkles size={11} />{model}</span>}
          </div>
          <button type={running ? 'button' : 'submit'} className={`agent-run-button${running ? ' agent-run-button--stop' : ''}`} onClick={running ? () => abortRef.current?.abort() : undefined} disabled={!running && (uploading || !task.trim() || localAccess !== 'allowed')}>
            {running ? <><X size={13} /> Stop task</> : <><Play size={13} /> Run task</>}
          </button>
        </div>
      </form>

      <section className="agent-results panel" aria-live="polite">
        <div className="panel-heading">
          <div><h2>Task trace</h2><span className="panel-kicker">Live plan · Tool calls · Deliverables</span></div>
          {running && <span className="live-label"><span />Running</span>}
        </div>
        <div className="agent-activity">
          {!activity.length && <div className="agent-empty"><Activity size={18} /><span>No task run yet.</span><small>Every model choice and tool action will appear here.</small></div>}
          {activity.map((item) => (
            <div className={`agent-activity__row agent-activity__row--${item.status}`} key={item.id}>
              <StatusMark online={item.status === 'success' || item.status === 'active'} /><span>{item.label}</span>
              {item.status === 'active' && <RefreshCw size={12} className="spin" />}
            </div>
          ))}
        </div>
        {answer && <div className="agent-answer"><div className="panel-kicker">Agent report</div><ReactMarkdown remarkPlugins={[remarkGfm]} components={markdownComponents}>{answer}</ReactMarkdown></div>}
        {artifacts.length > 0 && (
          <div className="agent-artifacts">
            <div className="panel-kicker">Task outputs</div>
            {artifacts.map((artifact) => <a key={artifact.path} href={artifact.url} download={artifact.name}><FileText size={13} /><span>{artifact.name}</span><small>{artifact.kind.toUpperCase()}</small><ArrowDown size={13} /></a>)}
          </div>
        )}
        <div className="agent-safety-note"><Shield size={12} />Local browser only · No shell access · No overwrites · Outputs stay in the task folder</div>
      </section>
    </div>
  )
}
