// One message in the conversation: the user's prompt, or an assistant turn with its activity,
// plan review, approvals, reply, and produced files.
import { useState } from 'react'
import { AlertTriangle, Bookmark, Flag, Box, Bot, Check, ChevronRight, CircleSlash, Copy, FileText, FolderOpen, Globe, Image as ImageIcon, LoaderCircle, MessageSquare, Pencil, RefreshCw, Shield, Terminal, X } from 'lucide-react'
import { relativeTime, sendJson } from '../lib/api'
import { decideApproval, decidePlan } from '../lib/engines'
import { bridge, ENGINE_LABEL } from '../lib/types'
import type { Approval, Engine, Message, ResearchBlock, ResearchSource, Step } from '../lib/types'
import { formatDuration, stepDuration, turnPhases, useNow } from '../lib/timing'
import { Markdown } from './ui'
import { Mark } from './Mark'

export function EngineIcon({ engine, size = 14 }: { engine: Engine; size?: number }) {
  if (engine === 'openclaw') return <Terminal size={size} />
  if (engine === 'nemoclaw') return <Box size={size} />
  if (engine === 'agent') return <Bot size={size} />
  return <MessageSquare size={size} />
}

function StepIcon({ status }: { status: Step['status'] }) {
  if (status === 'running') return <LoaderCircle size={13} className="spin" />
  if (status === 'done') return <Check size={13} />
  if (status === 'blocked') return <CircleSlash size={13} />
  return <X size={13} />
}

function Steps({ steps, live, endedAt }: { steps: Step[]; live: boolean; endedAt?: number }) {
  const [open, setOpen] = useState(false)
  const now = useNow(live)
  // After the turn, a step that never reported its end is timed up to the end of the turn.
  const at = live ? now : endedAt ?? now
  const running = [...steps].reverse().find((step) => step.status === 'running')
  const failed = steps.filter((step) => step.status === 'failed' || step.status === 'blocked').length
  const first = steps.find((step) => step.startedAt !== undefined)?.startedAt
  const last = Math.max(0, ...steps.map((step) => step.endedAt ?? (step.startedAt === undefined ? 0 : at)))
  const runningFor = running ? stepDuration(running, at) : null
  const summary = live && running
    ? `${running.label}${runningFor !== null ? ` · ${formatDuration(runningFor)}` : ''}`
    : `Worked through ${steps.length} ${steps.length === 1 ? 'step' : 'steps'}${first !== undefined && last > first ? ` in ${formatDuration(last - first)}` : ''}${failed ? ` · ${failed} did not succeed` : ''}`
  return (
    <div className={`steps${open ? ' is-open' : ''}`}>
      <button type="button" className="steps__summary" onClick={() => setOpen((value) => !value)} aria-expanded={open}>
        {live && running ? <Mark size={15} working /> : <ChevronRight size={13} className="steps__chevron" />}
        <span>{summary}</span>
      </button>
      {open && (
        <ol className="steps__list">
          {steps.map((step) => (
            <li key={step.id} className={`step step--${step.status}`} title={step.detail}>
              <StepIcon status={step.status} />
              <span>{step.label}</span>
              {step.status !== 'done' && step.status !== 'running' && <small>{step.status === 'blocked' ? 'Denied' : step.status === 'stopped' ? 'Stopped' : 'Failed'}</small>}
              <StepTime step={step} at={step.status === 'running' ? at : step.endedAt ?? at} />
            </li>
          ))}
        </ol>
      )}
    </div>
  )
}

/** A step's duration; hidden for steps that were instant (under 0.05 s) or have no timing. */
function StepTime({ step, at }: { step: Step; at: number }) {
  const ms = stepDuration(step, at)
  if (ms === null || (step.status !== 'running' && ms < 50)) return null
  return <time className="step__time">{formatDuration(ms)}</time>
}

function ApprovalCard({ approval, onChange }: { approval: Approval; onChange: (next: Approval) => void }) {
  const decide = async (allow: boolean) => {
    const decidedAt = Date.now()
    onChange({ ...approval, status: 'busy', error: undefined })
    try {
      await decideApproval(approval, allow)
      // The stream confirms the outcome; show it now so the buttons do not linger.
      onChange({ ...approval, status: allow ? 'approved' : 'rejected', resolvedAt: approval.resolvedAt ?? decidedAt })
    } catch (error) {
      onChange({ ...approval, status: 'pending', error: error instanceof Error ? error.message : 'The decision was not accepted.' })
    }
  }
  const pending = approval.status === 'pending' || approval.status === 'busy'
  return (
    <section className={`card card--approval${pending ? ' is-pending' : ''}`} aria-live="polite">
      <header><Shield size={14} /><strong>{pending ? 'Approval needed' : approval.status === 'approved' ? 'Allowed' : approval.status === 'rejected' ? 'Denied' : 'Expired'}</strong><span>{approval.source === 'openclaw' ? 'OpenClaw' : 'PockPock Agent'}</span></header>
      <p className="card__title">{approval.title}</p>
      {approval.description && <code className="card__detail">{approval.description}</code>}
      {approval.diff && <pre className="card__diff">{approval.diff}</pre>}
      {approval.error && <p className="card__error" role="alert">{approval.error}</p>}
      {pending && (
        <div className="card__actions">
          <button type="button" className="button button--primary" disabled={approval.status === 'busy'} onClick={() => void decide(true)}>{approval.status === 'busy' ? <LoaderCircle size={13} className="spin" /> : <Check size={13} />} Allow once</button>
          <button type="button" className="button" disabled={approval.status === 'busy'} onClick={() => void decide(false)}><X size={13} /> Deny</button>
        </div>
      )}
    </section>
  )
}

function PlanReview({ message, onChange }: { message: Message; onChange: (next: Message) => void }) {
  const plan = message.plan!
  const [editing, setEditing] = useState(false)
  const [steps, setSteps] = useState(plan.steps)
  const [checks, setChecks] = useState(plan.checks)
  const [busy, setBusy] = useState(false)
  const pending = plan.status === 'pending'
  const planningMs = message.timing?.planReadyAt ? message.timing.planReadyAt - message.timing.startedAt : null
  const decide = async (approved: boolean) => {
    const keptSteps = steps.map((step) => step.trim()).filter(Boolean)
    const keptChecks = checks.map((check) => check.trim()).filter(Boolean)
    if (approved && (!keptSteps.length || !keptChecks.length)) { onChange({ ...message, plan: { ...plan, error: 'Keep at least one step and one success check.' } }); return }
    setBusy(true)
    try {
      await decidePlan(message.id, plan, approved, keptSteps, keptChecks)
      onChange({ ...message, plan: { ...plan, steps: keptSteps, checks: keptChecks, status: approved ? 'approved' : 'rejected', error: undefined } })
    } catch (error) {
      onChange({ ...message, plan: { ...plan, error: error instanceof Error ? error.message : 'The decision was not accepted.' } })
    } finally {
      setBusy(false)
      setEditing(false)
    }
  }
  const editList = (items: string[], set: (items: string[]) => void, label: string) => items.map((item, index) => (
    <input key={index} className="input" aria-label={`${label} ${index + 1}`} value={item} onChange={(event) => set(items.map((value, position) => position === index ? event.target.value : value))} />
  ))
  return (
    <section className={`card card--plan${pending ? ' is-pending' : ''}`}>
      <header><Bot size={14} /><strong>{pending ? 'Review the plan before it runs' : plan.status === 'approved' ? 'Plan approved' : 'Plan declined'}</strong><span>{plan.model}{planningMs !== null && ` · planned in ${formatDuration(planningMs)}`}</span></header>
      {plan.goal && <p className="card__title">{plan.goal}</p>}
      <div className="plan__grid">
        <div>
          <h4>Steps</h4>
          {editing ? editList(steps, setSteps, 'Step') : <ol>{steps.map((step, index) => <li key={index}>{step}</li>)}</ol>}
        </div>
        <div>
          <h4>Success checks</h4>
          {editing ? editList(checks, setChecks, 'Success check') : <ul>{checks.map((check, index) => <li key={index}>{check}</li>)}</ul>}
        </div>
      </div>
      {plan.deliverables.length > 0 && <p className="plan__meta"><b>Delivers</b> {plan.deliverables.join(' · ')}</p>}
      <p className="plan__meta"><b>Workspace</b> {plan.workspace}</p>
      {plan.critic && <p className="plan__meta"><b>Reviewer</b> {plan.critic}</p>}
      {plan.questions.length > 0 && <div className="plan__questions" role="note"><AlertTriangle size={13} /><span>{plan.questions.join(' ')}</span></div>}
      {plan.error && <p className="card__error" role="alert">{plan.error}</p>}
      {pending && (
        <div className="card__actions">
          <button type="button" className="button button--primary" disabled={busy} onClick={() => void decide(true)}>{busy ? <LoaderCircle size={13} className="spin" /> : <Check size={13} />} Approve and run</button>
          <button type="button" className="button" disabled={busy} onClick={() => setEditing((value) => !value)}><Pencil size={13} /> {editing ? 'Done editing' : 'Edit plan'}</button>
          <button type="button" className="button" disabled={busy} onClick={() => void decide(false)}><X size={13} /> Decline</button>
        </div>
      )}
    </section>
  )
}

function ResearchCard({ block }: { block: ResearchBlock }) {
  const [saved, setSaved] = useState<Record<string, 'saving' | 'saved' | 'error'>>({})
  const [note, setNote] = useState('')
  const save = async (source: ResearchSource) => {
    setSaved((current) => ({ ...current, [source.source_id]: 'saving' }))
    try {
      await sendJson(`/api/agents/${encodeURIComponent(block.taskId)}/research-collection/sources`, { source_id: source.source_id, notes: '' })
      setSaved((current) => ({ ...current, [source.source_id]: 'saved' }))
    } catch (error) {
      setSaved((current) => ({ ...current, [source.source_id]: 'error' }))
      setNote(error instanceof Error ? error.message : 'Could not save the source.')
    }
  }
  const refresh = async (source: ResearchSource) => {
    try {
      const result = await sendJson<{ changed?: boolean }>(`/api/agents/${encodeURIComponent(block.taskId)}/research-collection/sources/${encodeURIComponent(source.source_id)}/refresh`)
      setNote(result.changed ? `${source.title} has changed since it was saved.` : `${source.title} has not changed.`)
    } catch (error) { setNote(error instanceof Error ? error.message : 'Could not check the source.') }
  }
  return (
    <section className="card card--sources">
      <header><Globe size={14} /><strong>{block.sources.length} {block.sources.length === 1 ? 'source' : 'sources'} read</strong><span>{block.query}</span></header>
      <ul className="sources">
        {block.sources.map((source) => (
          <li key={source.source_id}>
            <div><a href={source.url} target="_blank" rel="noreferrer">{source.title}</a><small>{source.url}</small>{source.excerpt && <p>{source.excerpt}</p>}</div>
            {block.taskId && (saved[source.source_id] === 'saved'
              ? <button type="button" className="button" onClick={() => void refresh(source)}><RefreshCw size={12} /> Check for changes</button>
              : <button type="button" className="button" disabled={saved[source.source_id] === 'saving'} onClick={() => void save(source)}><Bookmark size={12} /> Save</button>)}
          </li>
        ))}
      </ul>
      {block.errors.map((error, index) => <p key={index} className="card__error">{error}</p>)}
      {note && <p className="note">{note}</p>}
    </section>
  )
}

export function MessageView({ message, live, onChange, onReport }: { message: Message; live: boolean; onChange: (next: Message) => void; onReport?: () => void }) {
  const [copied, setCopied] = useState(false)
  const now = useNow(live)
  if (message.role === 'user') {
    return (
      <article className="message message--user">
        <div className="message__bubble">
          <p>{message.content}</p>
          {message.attachments?.length ? (
            <div className="chips">{message.attachments.map((file) => <span className="chip" key={file.name}>{file.kind === 'image' ? <ImageIcon size={12} /> : <FileText size={12} />}{file.name}</span>)}</div>
          ) : null}
        </div>
      </article>
    )
  }
  const copy = () => void navigator.clipboard.writeText(message.content).then(() => { setCopied(true); window.setTimeout(() => setCopied(false), 1400) })
  const waiting = live && !message.content && !message.plan && !(message.steps?.length)
  const phases = live ? null : turnPhases(message)
  // The task folder holds the run's files; older runs only recorded the workspace (issue #76).
  const taskFolder = message.taskFolder || message.workspacePath
  const openFolder = () => { if (taskFolder) void bridge()?.openPath(taskFolder) }
  return (
    <article className="message message--assistant">
      <div className="message__meta">
        <span className="message__engine"><EngineIcon engine={message.engine} size={13} />{ENGINE_LABEL[message.engine]}</span>
        {message.model && <span className="message__model">{message.model}</span>}
        {live && message.timing && <time className="message__elapsed" aria-label="Elapsed time">{formatDuration(now - message.timing.startedAt)}</time>}
      </div>
      {message.steps?.length ? <Steps steps={message.steps} live={live} endedAt={message.timing?.endedAt} /> : null}
      {message.plan && <PlanReview message={message} onChange={onChange} />}
      {message.approvals?.map((approval) => (
        <ApprovalCard key={approval.id} approval={approval} onChange={(next) => onChange({ ...message, approvals: message.approvals?.map((item) => item.id === next.id ? next : item) })} />
      ))}
      {waiting && <div className="thinking" role="status"><Mark size={16} working /> Thinking{message.timing && <time>{formatDuration(now - message.timing.startedAt)}</time>}</div>}
      {message.content && <div className={`message__body${message.status === 'error' ? ' is-error' : ''}`}><Markdown content={message.content} /></div>}
      {message.notice && <p className="message__notice"><AlertTriangle size={13} />{message.notice}</p>}
      {message.research?.map((block, index) => <ResearchCard key={index} block={block} />)}
      {message.changes?.length ? (
        <section className="card card--changes"><header><FileText size={14} /><strong>Changed {message.changes.length} {message.changes.length === 1 ? 'file' : 'files'}</strong></header>
          <ul className="changes">{message.changes.map((change) => <li key={change.path}><code>{change.path}</code>{change.summary && <span>{change.summary}</span>}</li>)}</ul>
        </section>
      ) : null}
      {message.artifacts?.length ? (
        <div className="artifacts">
          {message.artifacts.map((artifact) => (
            <button type="button" key={artifact.path} className="artifact" onClick={() => void bridge()?.openPath(artifact.path)} title={artifact.path}>
              <FileText size={14} /><span>{artifact.name}</span><small>{artifact.kind}</small>
            </button>
          ))}
        </div>
      ) : null}
      {taskFolder && (
        <div className="artifacts">
          <button type="button" className="artifact" onClick={openFolder} title={taskFolder}><FolderOpen size={14} /><span>Task folder</span><small>Open</small></button>
        </div>
      )}
      {!live && (
        <div className="message__footer">
          {message.content && <button type="button" className="icon-button icon-button--small" onClick={copy} aria-label="Copy reply" title="Copy reply">{copied ? <Check size={13} /> : <Copy size={13} />}</button>}
          {onReport && <button type="button" className="icon-button icon-button--small" onClick={onReport} aria-label="Report a problem with this reply" title="Report a problem with this reply"><Flag size={13} /></button>}
          <span>{message.status === 'stopped' ? 'Stopped · ' : ''}{relativeTime(message.createdAt)}</span>
          {phases && (
            <span className="message__timing" aria-label="Time taken">
              {phases.map((phase) => <span key={phase.label} className={phase.label === 'Total' ? 'is-total' : undefined}>{phase.label} <time>{formatDuration(phase.ms)}</time></span>)}
            </span>
          )}
        </div>
      )}
    </article>
  )
}
