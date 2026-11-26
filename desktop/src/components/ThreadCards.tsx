// Cards inside an assistant turn: the collapsed step list, approval cards (Allow once, Allow for this
// task, Deny), saved research sources (Save, Check for changes, Watch for changes), the failed-step card (Retry from step N) and message actions.
import { useEffect, useState } from 'react'
import { AlertTriangle, Bookmark, Check, ChevronRight, CircleSlash, Copy, ExternalLink, Flag, Globe, LoaderCircle, RefreshCw, RotateCcw, Shield, X } from 'lucide-react'
import { getJson, sendJson } from '../lib/api'
import { announceWatchChange, setWatched, type SourceWatch } from '../lib/watch'
import { Toggle } from './page'
import { decideApproval } from '../lib/engines'
import type { Approval, Message, ResearchBlock, ResearchSource, Step } from '../lib/types'
import { errorText } from '../lib/runState'
import { formatDuration, stepDuration, useNow } from '../lib/timing'
import { Mark } from './Mark'

function StepIcon({ status }: { status: Step['status'] }) {
  if (status === 'running') return <LoaderCircle size={13} className="spin" aria-label="Running" />
  if (status === 'done') return <Check size={13} aria-label="Done" />
  if (status === 'blocked') return <CircleSlash size={13} aria-label="Denied" />
  return <X size={13} aria-label={status === 'stopped' ? 'Stopped' : 'Failed'} />
}

/** A step's duration; hidden for steps that were instant (under 0.05 s) or have no timing. */
function StepTime({ step, at }: { step: Step; at: number }) {
  const ms = stepDuration(step, at)
  if (ms === null || (step.status !== 'running' && ms < 50)) return null
  return <time className="step__time">{formatDuration(ms)}</time>
}

export function Steps({ steps, live, endedAt }: { steps: Step[]; live: boolean; endedAt?: number }) {
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
    : `Worked through ${steps.length} ${steps.length === 1 ? 'step' : 'steps'}`
  const meta = live && running ? `${steps.length - 1} done` : [failed ? `${failed} did not succeed` : '', first !== undefined && last > first ? formatDuration(last - first) : ''].filter(Boolean).join(' · ')
  return (
    <div className={`steps${open ? ' is-open' : ''}`}>
      <button type="button" className="steps__summary" onClick={() => setOpen((value) => !value)} aria-expanded={open}>
        {live && running ? <Mark size={15} working /> : <ChevronRight size={13} className="steps__chevron" aria-hidden="true" />}
        <span className="steps__label">{summary}</span>
        {meta && <small>{meta}</small>}
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

export function ApprovalCard({ approval, permissionLabel, onChange }: { approval: Approval; permissionLabel?: string; onChange: (next: Approval) => void }) {
  const decide = async (allow: boolean, scope: 'once' | 'task' = 'once') => {
    const decidedAt = Date.now()
    onChange({ ...approval, status: 'busy', error: undefined })
    try {
      await decideApproval(approval, allow, scope)
      // The stream confirms the outcome; show it now so the buttons do not linger.
      onChange({ ...approval, status: allow ? 'approved' : 'rejected', scope: allow ? scope : undefined, resolvedAt: approval.resolvedAt ?? decidedAt })
    } catch (error) {
      onChange({ ...approval, status: 'pending', error: error instanceof Error ? error.message : 'The decision was not accepted.' })
    }
  }
  const pending = approval.status === 'pending' || approval.status === 'busy'
  const outcome = approval.status === 'approved' ? (approval.scope === 'task' ? 'Allowed for this task' : 'Allowed once') : approval.status === 'rejected' ? 'Denied' : approval.status === 'expired' ? 'Expired' : 'Waiting for you'
  return (
    <section className={`card card--approval${pending ? ' is-pending' : ''}`} aria-live="polite" aria-label="Approval">
      <header>
        <Shield size={14} aria-hidden="true" />
        <strong>{approval.title}</strong>
        <span className={`badge${pending ? ' badge--accent' : approval.status === 'approved' ? ' badge--ok' : ''}`}>{outcome}</span>
      </header>
      {permissionLabel && <p className="card__sub">{approval.source === 'openclaw' ? 'OpenClaw' : 'PockPock Agent'} · {permissionLabel}</p>}
      {approval.untrusted && pending && <p className="card__warn" role="note"><AlertTriangle size={13} aria-hidden="true" /> This task has read web or MCP content since it started. Text there can contain instructions from someone else. If you did not ask for this action, deny it.</p>}
      {approval.description && <code className="card__detail">{approval.description}</code>}
      {approval.diff && <pre className="card__diff">{approval.diff}</pre>}
      {approval.error && <p className="card__error" role="alert">{approval.error}</p>}
      {pending && (
        <div className="card__actions">
          <button type="button" className="button button--primary" disabled={approval.status === 'busy'} onClick={() => void decide(true)}>{approval.status === 'busy' ? <LoaderCircle size={13} className="spin" /> : <Check size={13} />} Allow once</button>
          {approval.grantable && <button type="button" className="button" disabled={approval.status === 'busy'} onClick={() => void decide(true, 'task')} title={approval.source === 'openclaw' ? 'Allow this exact command (or this tool) for the rest of this turn' : 'Allow this kind of action for the rest of this task'}>Allow for this task</button>}
          <button type="button" className="button button--quiet-end" disabled={approval.status === 'busy'} onClick={() => void decide(false)}><X size={13} /> Deny</button>
        </div>
      )}
    </section>
  )
}

type SavedState = { status: 'saving' | 'saved' | 'error'; watch?: SourceWatch; watchBusy?: boolean }
type CollectionReply = { collection: { sources: Array<{ source: { source_id: string }; watch?: SourceWatch }> } | null }

export function ResearchCard({ block }: { block: ResearchBlock }) {
  const [saved, setSaved] = useState<Record<string, SavedState>>({})
  const [note, setNote] = useState('')
  // What this task already saved and watches, so a reopened task shows it (not Save again).
  useEffect(() => {
    if (!block.taskId) return
    let live = true
    getJson<CollectionReply>(`/api/agents/${encodeURIComponent(block.taskId)}/research-collection`).then((reply) => {
      if (!live || !reply.collection) return
      const known: Record<string, SavedState> = {}
      for (const item of reply.collection.sources) known[item.source.source_id] = { status: 'saved', watch: item.watch }
      setSaved((current) => ({ ...known, ...current }))
    }, () => undefined)
    return () => { live = false }
  }, [block.taskId])
  const patch = (id: string, change: Partial<SavedState>) => setSaved((current) => ({ ...current, [id]: { ...(current[id] ?? { status: 'saved' }), ...change } }))
  const save = async (source: ResearchSource) => {
    patch(source.source_id, { status: 'saving' })
    try {
      await sendJson(`/api/agents/${encodeURIComponent(block.taskId)}/research-collection/sources`, { source_id: source.source_id, notes: '' })
      patch(source.source_id, { status: 'saved' })
    } catch (error) {
      patch(source.source_id, { status: 'error' })
      setNote(error instanceof Error ? error.message : 'Could not save the source.')
    }
  }
  const refresh = async (source: ResearchSource) => {
    try {
      const result = await sendJson<{ changed?: boolean; previous?: unknown }>(`/api/agents/${encodeURIComponent(block.taskId)}/research-collection/sources/${encodeURIComponent(source.source_id)}/refresh`)
      announceWatchChange()
      setNote(result.changed && result.previous ? `${source.title} has changed since it was last checked.` : `${source.title} has not changed.`)
    } catch (error) { setNote(error instanceof Error ? error.message : 'Could not check the source.') }
  }
  const watch = async (source: ResearchSource, next: boolean) => {
    patch(source.source_id, { watchBusy: true })
    try {
      const state = await setWatched(block.taskId, source.source_id, next)
      patch(source.source_id, { watch: state, watchBusy: false })
      setNote(next
        ? `Watching ${source.title}. PockPock re-reads it in the background while it runs and research is on, and tells you when it changes. Manage watched pages in Workshop → Research.`
        : `Stopped watching ${source.title}.`)
    } catch (error) {
      patch(source.source_id, { watchBusy: false })
      setNote(error instanceof Error ? error.message : 'Could not change watching.')
    }
  }
  return (
    <section className="card card--sources" aria-label="Sources">
      <header><Globe size={14} aria-hidden="true" /><strong>Sources</strong><span className="card__sub">{block.sources.length} {block.sources.length === 1 ? 'page' : 'pages'} read{block.query ? ` · ${block.query}` : ''}</span></header>
      <ul className="sources">
        {block.sources.map((source) => {
          const state = saved[source.source_id]
          return (
            <li key={source.source_id}>
              <div><a href={source.url} target="_blank" rel="noreferrer">{source.title} <ExternalLink size={11} aria-hidden="true" /></a><small>{source.url}</small>{source.excerpt && <p>{source.excerpt}</p>}</div>
              {block.taskId && (state?.status === 'saved'
                ? (
                  <span className="sources__actions">
                    <span className="badge badge--ok"><Check size={12} aria-hidden="true" />Saved</span>
                    <button type="button" className="button button--small" onClick={() => void refresh(source)}><RefreshCw size={12} /> Check for changes</button>
                    <span className="sources__watch">
                      <Toggle checked={Boolean(state.watch?.watched)} busy={state.watchBusy} label={`Watch for changes: ${source.title}`} onChange={(next) => void watch(source, next)} />
                      <span aria-hidden="true">Watch for changes</span>
                    </span>
                  </span>
                )
                : <button type="button" className="button button--small" disabled={state?.status === 'saving'} onClick={() => void save(source)}><Bookmark size={12} /> Save</button>)}
            </li>
          )
        })}
      </ul>
      {!block.sources.length && <p>No page could be read.</p>}
      {block.errors.map((error, index) => <p key={index} className="card__error">{error}</p>)}
      {note && <p className="note" role="status">{note}</p>}
    </section>
  )
}

/** A failed agent turn: what happened, what is kept, and Retry from step N (a new run of the remaining steps). */
export function FailedCard({ message, onRetryFrom, onReport }: { message: Message; onRetryFrom?: (step: number) => void; onReport?: () => void }) {
  const planSteps = message.plan?.status === 'approved' ? message.plan.steps : []
  const done = (message.steps ?? []).filter((step) => step.status === 'done').length
  const [from, setFrom] = useState(1)
  return (
    <section className="card card--failed" aria-label="The run stopped">
      <header><X size={14} aria-hidden="true" /><strong>Stopped: {errorText(message)}</strong></header>
      <p>{[message.plan ? 'The plan' : '', done ? `${done} finished ${done === 1 ? 'step' : 'steps'}` : '', message.artifacts?.length ? `${message.artifacts.length} saved ${message.artifacts.length === 1 ? 'file' : 'files'}` : ''].filter(Boolean).join(', ') || 'Nothing'} {done || message.plan || message.artifacts?.length ? 'are kept.' : 'was changed.'}</p>
      <div className="card__actions">
        {onRetryFrom && planSteps.length > 1 && (
          <span className="retry-from">
            <label htmlFor={`retry-${message.id}`}>Retry from step</label>
            <select id={`retry-${message.id}`} className="input input--inline" value={from} onChange={(event) => setFrom(Number(event.target.value))}>
              {planSteps.map((step, index) => <option key={index} value={index + 1}>{index + 1}. {step.slice(0, 60)}</option>)}
            </select>
            <button type="button" className="button button--primary" onClick={() => onRetryFrom(from)}><RotateCcw size={13} /> Retry from step {from}</button>
          </span>
        )}
        {onRetryFrom && planSteps.length <= 1 && <button type="button" className="button button--primary" onClick={() => onRetryFrom(1)}><RotateCcw size={13} /> Retry</button>}
        {onReport && <button type="button" className="button" onClick={onReport}><Flag size={13} /> Report</button>}
      </div>
      {onRetryFrom && planSteps.length > 1 && <small className="card__hint">Retrying plans the remaining steps again, with the earlier steps marked as done, and shows you the new plan first.</small>}
    </section>
  )
}

export function MessageActions({ message, onRetry, onReport }: { message: Message; onRetry?: () => void; onReport?: () => void }) {
  const [copied, setCopied] = useState(false)
  const copy = () => void navigator.clipboard.writeText(message.content).then(() => { setCopied(true); window.setTimeout(() => setCopied(false), 1400) })
  return (
    <span className="message__actions">
      {message.content && <button type="button" className="icon-button icon-button--small" onClick={copy} aria-label="Copy reply" title="Copy reply">{copied ? <Check size={13} /> : <Copy size={13} />}</button>}
      {onRetry && <button type="button" className="icon-button icon-button--small" onClick={onRetry} aria-label="Retry" title="Send the same request again"><RotateCcw size={13} /></button>}
      {onReport && <button type="button" className="icon-button icon-button--small" onClick={onReport} aria-label="Report a problem" title="Report a problem with this reply"><Flag size={13} /></button>}
    </span>
  )
}
