import { Children, isValidElement, memo, useEffect, useRef, useState } from 'react'
import type { ComponentPropsWithoutRef } from 'react'
import { Activity, ArrowDown, Check, ChevronDown, CircleHelp, Copy, FileText, FolderOpen, Sparkles, X } from 'lucide-react'
import type { ExtraProps } from 'react-markdown'
import type { PlanDecision } from '../agents/agentTypes'
import type { ResearchSnapshot, SavedResearchCollection, SavedResearchSource } from './chatTypes'
import { copyText } from './chatUtils'

function timelineSentenceCase(text: string) {
  return text ? text.charAt(0).toUpperCase() + text.slice(1).toLowerCase() : text
}

function researchTextDiff(previous: string, current: string) {
  const before = previous.split('\n')
  const after = current.split('\n')
  let prefix = 0
  while (prefix < before.length && prefix < after.length && before[prefix] === after[prefix]) prefix += 1
  let suffix = 0
  while (suffix < before.length - prefix && suffix < after.length - prefix && before[before.length - 1 - suffix] === after[after.length - 1 - suffix]) suffix += 1
  const limit = 120
  const removed = before.slice(prefix, before.length - suffix)
  const added = after.slice(prefix, after.length - suffix)
  return {
    removed: removed.slice(0, limit),
    added: added.slice(0, limit),
    removedMore: Math.max(0, removed.length - limit),
    addedMore: Math.max(0, added.length - limit),
  }
}

function announceResearchCollectionChange(taskId: string) {
  window.dispatchEvent(new CustomEvent('research-collection-changed', { detail: { taskId } }))
}

function ResearchSourceCard({ taskId, source, excerpt, saved, onCollectionChange }: {
  taskId: string
  source: Record<string, unknown>
  excerpt?: Record<string, unknown>
  saved?: SavedResearchSource
  onCollectionChange: (collection: SavedResearchCollection | null) => void
}) {
  const [notes, setNotes] = useState(saved?.notes || '')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [refreshResult, setRefreshResult] = useState<{ changed: boolean; previous?: ResearchSnapshot | null; current?: ResearchSnapshot | null } | null>(null)
  const [selectedVersion, setSelectedVersion] = useState<ResearchSnapshot | null>(null)
  const sourceId = String(source.source_id || '')
  const rawUrl = String(source.canonical_url || '')
  let safeUrl = ''
  try { const parsed = new URL(rawUrl); if (parsed.protocol === 'http:' || parsed.protocol === 'https:') safeUrl = parsed.href } catch { /* malformed historic records remain plain text */ }

  useEffect(() => { setNotes(saved?.notes || '') }, [saved?.notes, sourceId])

  const reloadCollection = async () => {
    const response = await fetch(`/api/agents/${encodeURIComponent(taskId)}/research-collection`)
    const result = await response.json() as { detail?: string; collection?: SavedResearchCollection | null }
    if (!response.ok) throw new Error(result.detail || 'Could not load the saved research collection.')
    onCollectionChange(result.collection || null)
  }

  const save = async () => {
    setBusy(true); setError(''); setRefreshResult(null)
    try {
      const response = await fetch(`/api/agents/${encodeURIComponent(taskId)}/research-collection/sources`, {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ source_id: sourceId, notes }),
      })
      const result = await response.json() as { detail?: string; collection?: SavedResearchCollection }
      if (!response.ok || !result.collection) throw new Error(result.detail || 'Could not save this source.')
      onCollectionChange(result.collection)
      announceResearchCollectionChange(taskId)
    } catch (reason) { setError(reason instanceof Error ? reason.message : 'Could not save this source.') }
    finally { setBusy(false) }
  }

  const updateNotes = async () => {
    setBusy(true); setError('')
    try {
      const response = await fetch(`/api/agents/${encodeURIComponent(taskId)}/research-collection/sources/${encodeURIComponent(sourceId)}`, {
        method: 'PATCH', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ notes }),
      })
      const result = await response.json() as { detail?: string }
      if (!response.ok) throw new Error(result.detail || 'Could not update source notes.')
      await reloadCollection()
      announceResearchCollectionChange(taskId)
    } catch (reason) { setError(reason instanceof Error ? reason.message : 'Could not update source notes.') }
    finally { setBusy(false) }
  }

  const refresh = async () => {
    setBusy(true); setError(''); setSelectedVersion(null)
    try {
      const response = await fetch(`/api/agents/${encodeURIComponent(taskId)}/research-collection/sources/${encodeURIComponent(sourceId)}/refresh`, { method: 'POST' })
      const result = await response.json() as { detail?: string; changed?: boolean; previous?: ResearchSnapshot | null; current?: ResearchSnapshot | null }
      if (!response.ok || typeof result.changed !== 'boolean') throw new Error(result.detail || 'Could not refresh this source.')
      setRefreshResult({ changed: result.changed, previous: result.previous, current: result.current })
      await reloadCollection()
      announceResearchCollectionChange(taskId)
    } catch (reason) { setError(reason instanceof Error ? reason.message : 'Could not refresh this source.') }
    finally { setBusy(false) }
  }

  const loadVersion = async (version: ResearchSnapshot) => {
    setBusy(true); setError('')
    try {
      const response = await fetch(`/api/agents/${encodeURIComponent(taskId)}/research-collection/sources/${encodeURIComponent(sourceId)}/snapshots/${version.snapshot_id}`)
      const result = await response.json() as { detail?: string; snapshot?: ResearchSnapshot }
      if (!response.ok || !result.snapshot) throw new Error(result.detail || 'Could not load this snapshot.')
      setSelectedVersion(result.snapshot)
    } catch (reason) { setError(reason instanceof Error ? reason.message : 'Could not load this snapshot.') }
    finally { setBusy(false) }
  }

  const diff = refreshResult?.changed && refreshResult.previous?.text !== undefined && refreshResult.current?.text !== undefined
    ? researchTextDiff(refreshResult.previous.text, refreshResult.current.text)
    : null

  return <article className="research-source" key={sourceId || rawUrl}>
    <a href={safeUrl || undefined} target="_blank" rel="noreferrer">{String(source.title || rawUrl || 'Untitled source')}</a>
    <small>{rawUrl} · {String(source.retrieved_at || '')}</small>
    {typeof source.snippet === 'string' && <p>{source.snippet}</p>}
    {excerpt && <blockquote>{String(excerpt.excerpt || '')}</blockquote>}
    {saved ? <div className="research-source__collection">
      <label>Notes<textarea value={notes} maxLength={2000} onChange={(change) => setNotes(change.target.value)} /></label>
      <div className="research-source__actions">
        <button type="button" disabled={busy || notes === saved.notes} onClick={() => void updateNotes()}>Save notes</button>
        <button type="button" disabled={busy} onClick={() => void refresh()}>Refresh now</button>
      </div>
      <small>{saved.version_count} saved {saved.version_count === 1 ? 'version' : 'versions'} · Last checked {saved.last_checked_at}</small>
      {refreshResult && <div className="research-source__diff" role="status">
        <b>{refreshResult.changed ? 'Source changed since the previous snapshot' : 'No content changes detected'}</b>
        {diff && <><div><b>Removed</b><pre>{diff.removed.join('\n') || '(none)'}{diff.removedMore > 0 ? `\n… ${diff.removedMore} more lines` : ''}</pre></div><div><b>Added</b><pre>{diff.added.join('\n') || '(none)'}{diff.addedMore > 0 ? `\n… ${diff.addedMore} more lines` : ''}</pre></div></>}
        {refreshResult.current && <small>Latest version captured {refreshResult.current.captured_at}{refreshResult.current.truncated ? ' · snapshot truncated at 200 KB' : ''}</small>}
      </div>}
      {saved.versions.length > 0 && <details className="research-source__versions"><summary>Version history</summary><ol>{saved.versions.map((version, index) => <li key={version.snapshot_id}><button type="button" disabled={busy} onClick={() => void loadVersion(version)}>Version {index + 1}{index === saved.versions.length - 1 ? ' · latest' : ''} · {version.captured_at}{version.truncated ? ' · truncated' : ''}</button></li>)}</ol></details>}
      {selectedVersion?.text !== undefined && <details open><summary>Snapshot text · {selectedVersion.captured_at}</summary><pre>{selectedVersion.text}</pre></details>}
    </div> : <div className="research-source__collection">
      <label>Notes (optional)<textarea value={notes} maxLength={2000} onChange={(change) => setNotes(change.target.value)} /></label>
      <button type="button" disabled={busy} onClick={() => void save()}>{busy ? 'Saving…' : 'Save source snapshot'}</button>
      <small>Fetches and saves up to 200 KB of extracted text only when you choose Save.</small>
    </div>}
    {error && <small className="research-source__error" role="alert">{error}</small>}
  </article>
}

function RunEventCard({ event, onPlanDecision }: { event: Record<string, unknown>; onPlanDecision?: (runId: string, decision: PlanDecision) => void }) {
  const [openingWorkspace, setOpeningWorkspace] = useState(false)
  const [workspaceOpenError, setWorkspaceOpenError] = useState('')
  const [approvalPending, setApprovalPending] = useState(false)
  const [approvalError, setApprovalError] = useState('')
  const [researchCollection, setResearchCollection] = useState<SavedResearchCollection | null>(null)
  const [researchCollectionError, setResearchCollectionError] = useState('')
  const [confirmDeleteResearchCollection, setConfirmDeleteResearchCollection] = useState(false)
  const briefInitial = event.task_brief && typeof event.task_brief === 'object' ? event.task_brief as Record<string, unknown> : {}
  const [editingPlan, setEditingPlan] = useState(false)
  const [planSteps, setPlanSteps] = useState(Array.isArray(event.plan) ? event.plan.map(String) : [])
  const [checks, setChecks] = useState(Array.isArray(briefInitial.success_checks) ? briefInitial.success_checks.map(String) : [])
  const type = String(event.type || 'activity')
  const tool = String(event.tool || '')
  const detail = String(event.message || event.model || event.path || event.status || '')
  useEffect(() => {
    const taskId = typeof event.task_id === 'string' ? event.task_id : ''
    if (type !== 'research_sources' || !taskId) return
    let active = true
    const loadCollection = () => {
      void fetch(`/api/agents/${encodeURIComponent(taskId)}/research-collection`)
        .then(async (response) => {
        const result = await response.json() as { detail?: string; collection?: SavedResearchCollection | null }
        if (!response.ok) throw new Error(result.detail || 'Could not load saved sources.')
        if (active) { setResearchCollection(result.collection || null); setResearchCollectionError('') }
        })
        .catch((reason) => { if (active) setResearchCollectionError(reason instanceof Error ? reason.message : 'Could not load saved sources.') })
    }
    const onCollectionChange = (change: Event) => {
      if ((change as CustomEvent<{ taskId?: string }>).detail?.taskId === taskId) loadCollection()
    }
    window.addEventListener('research-collection-changed', onCollectionChange)
    loadCollection()
    return () => { active = false; window.removeEventListener('research-collection-changed', onCollectionChange) }
  }, [event.task_id, type])
  if (type === 'token') return null
  if (type === 'browser_open') return <div className="run-event-status run-event-status--active"><span className="run-event-status__icon"><Activity size={13} /></span><span>{event.visible === true ? 'Opening page in a visible browser window' : 'Opening public page in an isolated headless browser'}</span><small>{String(event.url || '')}</small></div>
  if (type === 'browser_action') return <div className="run-event-status run-event-status--active"><span className="run-event-status__icon"><Activity size={13} /></span><span>{`Browser ${String(event.action || 'action')}: ${String(event.name || event.url || event.direction || '')}`}</span><small>{`Observation ${String(event.observation_id || '').slice(0, 8)} · ${String(event.reason || '')}`}</small></div>
  if (type === 'browser_observation') return <details className="run-event run-event--browser"><summary><span>{String(event.title || 'Page observed')}</span><small>{String(event.url || '')}</small></summary><div className="run-event__details"><p><b>Retrieved</b>{String(event.retrieved_at || '')}</p><p><b>Reason</b>Read visible page content in an isolated, read-only browser context.</p><details className="browser-page-text"><summary>Visible page text</summary><pre>{String(event.visible_text || '')}</pre></details></div></details>
  if (type === 'research_sources') {
    const sources = Array.isArray(event.sources) ? event.sources as Array<Record<string, unknown>> : []
    const evidence = Array.isArray(event.evidence) ? event.evidence as Array<Record<string, unknown>> : []
    const errors = Array.isArray(event.errors) ? event.errors as Array<Record<string, unknown>> : []
    const taskId = typeof event.task_id === 'string' ? event.task_id : ''
    const deleteCollection = async () => {
      if (!confirmDeleteResearchCollection || !taskId) { setConfirmDeleteResearchCollection(true); return }
      setResearchCollectionError('')
      try {
        const response = await fetch(`/api/agents/${encodeURIComponent(taskId)}/research-collection`, { method: 'DELETE' })
        const result = await response.json() as { detail?: string; deleted?: boolean }
        if (!response.ok || !result.deleted) throw new Error(result.detail || 'Could not delete the research collection.')
        setResearchCollection(null); setConfirmDeleteResearchCollection(false)
        announceResearchCollectionChange(taskId)
      } catch (reason) { setResearchCollectionError(reason instanceof Error ? reason.message : 'Could not delete the research collection.') }
    }
    return <details className="run-event run-event--research"><summary><span>{sources.length} research {sources.length === 1 ? 'source' : 'sources'}</span><small>{String(event.query || '')}</small></summary><div className="run-event__details"><p><b>Provider</b>{String(event.provider || '')}</p>{researchCollection && <div className="research-collection__actions"><b>Saved sources in this task workspace</b>{confirmDeleteResearchCollection ? <><button type="button" onClick={() => void deleteCollection()}>Confirm delete collection</button><button type="button" onClick={() => setConfirmDeleteResearchCollection(false)}>Cancel</button></> : <button type="button" onClick={() => void deleteCollection()}>Delete collection</button>}</div>}{researchCollectionError && <p className="research-source__error" role="alert">{researchCollectionError}</p>}{sources.map((source) => {
      const sourceId = String(source.source_id || '')
      const excerpt = evidence.find((item) => item.source_id === sourceId)
      const saved = researchCollection?.sources.find((item) => item.source.source_id === sourceId)
      return <ResearchSourceCard key={sourceId || String(source.canonical_url || '')} taskId={taskId} source={source} excerpt={excerpt} saved={saved} onCollectionChange={setResearchCollection} />
    })}{errors.map((item, index) => <p className="research-source__error" key={index}>{String(item.message || 'A source could not be retrieved.')}</p>)}{sources.length === 0 && errors.length === 0 && <p>No source evidence was returned.</p>}</div></details>
  }
  if (type === 'browser_screenshot') return <details className="run-event run-event--browser-screenshot"><summary><span>Screenshot captured</span><small>{String(event.name || event.path || '')}</small></summary><div className="run-event__details"><p><b>Saved</b>{String(event.path || '')}</p><p><b>Size</b>{`${String(event.screenshot_bytes || 0)} bytes`}</p>{typeof event.url === 'string' && <a href={event.url} target="_blank" rel="noreferrer">Open screenshot</a>}{typeof event.url === 'string' && <a href={event.url} target="_blank" rel="noreferrer"><img className="browser-evidence-image" src={event.url} alt={`Browser screenshot of ${String(event.name || 'the observed page')}`} loading="lazy" /></a>}</div></details>
  if (type === 'plan_version') {
    const plan = Array.isArray(event.plan) ? event.plan.map(String) : []
    const checks = Array.isArray(event.success_checks) ? event.success_checks.map(String) : []
    return <details className="run-event run-event--plan-version"><summary><span>Plan version {String(event.version || '')} · {String(event.status || '')}</span><small>{String(event.plan_hash || '').slice(0, 12)}</small></summary><div className="run-event__details"><p><b>Rationale</b>{String(event.rationale || '')}</p><p><b>Permission</b>{String(event.permission_level || '')}</p><ol>{plan.map((step, index) => <li key={`${index}-${step}`}>{step}</li>)}</ol><b>Success checks</b><ul>{checks.map((check, index) => <li key={`${index}-${check}`}>{check}</li>)}</ul></div></details>
  }
  if (type === 'plan') {
    const brief = event.task_brief && typeof event.task_brief === 'object' ? event.task_brief as Record<string, unknown> : {}
    const criticReview = event.critic_review && typeof event.critic_review === 'object' ? event.critic_review as Record<string, unknown> : null
    const criticFindings = criticReview && Array.isArray(criticReview.findings) ? criticReview.findings.map(String) : []
    const steps = planSteps
    const deliverables = Array.isArray(brief.deliverables) ? brief.deliverables.map(String) : []
    const questions = Array.isArray(brief.clarifying_questions) ? brief.clarifying_questions.map(String) : []
    const decide = async (decision: PlanDecision['decision']) => {
      const currentPlan = steps.filter((step) => step.trim())
      const currentChecks = checks.filter((check) => check.trim())
      if (decision === 'approved' && (!currentPlan.length || !currentChecks.length)) { setApprovalError('Keep at least one plan step and one success check.'); return }
      if (typeof event.run_id !== 'string' || typeof event.plan_id !== 'string' || typeof event.plan_hash !== 'string') return
      setApprovalPending(true)
      setApprovalError('')
      try {
        const response = await fetch(`/api/agents/plans/${encodeURIComponent(event.plan_id)}/decision`, {
          method: 'POST', headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ action_hash: event.plan_hash, decision, plan: currentPlan, success_checks: currentChecks }),
        })
        const result = await response.json() as { detail?: string; accepted?: boolean; approved_plan_hash?: string; approved_version_hash?: string }
        if (!response.ok || !result.accepted) throw new Error(result.detail || 'This plan can no longer be approved.')
        onPlanDecision?.(event.run_id, { decision, plan: currentPlan, successChecks: currentChecks, planId: event.plan_id, planHash: result.approved_plan_hash, versionHash: result.approved_version_hash })
      } catch (error) {
        setApprovalError(error instanceof Error ? error.message : 'Could not submit plan decision.')
      } finally { setApprovalPending(false) }
    }
    return <details className="run-event run-event--plan" open={event.plan_pending === true}><summary><span>{event.plan_pending === true ? 'Review the plan before I start' : event.plan_decision === 'approved' ? `Planned ${steps.length} ${steps.length === 1 ? 'step' : 'steps'}` : event.plan_decision === 'rejected' ? 'Plan declined' : `Planned ${steps.length} ${steps.length === 1 ? 'step' : 'steps'}`}</span></summary><div className="run-event__details">{event.plan_pending === true && brief.permission_level === 'default' && Array.isArray(brief.required_capabilities) && brief.required_capabilities.some((item) => String(item).startsWith('workspace_')) && <p className="run-event__warning" role="note">This task reads and writes files, which Default permissions don't allow. Decline, choose Auto-review in the composer, and send it again.</p>}{typeof brief.desired_outcome === 'string' && <p><b>Goal</b>{brief.desired_outcome}</p>}{criticReview && <div role="status"><p><b>Critic review</b>{String(criticReview.summary || '')}</p>{criticFindings.length > 0 && <ul>{criticFindings.map((finding, index) => <li key={`${index}-${finding}`}>{finding}</li>)}</ul>}</div>}{steps.length > 0 && <><b>Steps</b>{editingPlan ? steps.map((step, index) => <input key={index} aria-label={`Plan step ${index + 1}`} value={step} onChange={(change) => setPlanSteps((previous) => previous.map((item, itemIndex) => itemIndex === index ? change.target.value : item))} />) : <ol>{steps.map((step, index) => <li key={`${index}-${step}`}>{step}</li>)}</ol>}</>}{checks.length > 0 && <><b>Success checks</b>{editingPlan ? checks.map((check, index) => <input key={index} aria-label={`Success check ${index + 1}`} value={check} onChange={(change) => setChecks((previous) => previous.map((item, itemIndex) => itemIndex === index ? change.target.value : item))} />) : <ul>{checks.map((check, index) => <li key={`${index}-${check}`}>{check}</li>)}</ul>}</>}{deliverables.length > 0 && <><b>Expected deliverables</b><ul>{deliverables.map((item, index) => <li key={`${index}-${item}`}>{item}</li>)}</ul></>}{brief.requires_clarification === true && <div role="status"><b>Needs clarification</b>{questions.map((question, index) => <p key={`${index}-${question}`}>{question}</p>)}</div>}{event.plan_pending === true && <div className="approval-actions"><button type="button" disabled={approvalPending} onClick={() => editingPlan ? setEditingPlan(false) : setEditingPlan(true)}>{editingPlan ? 'Done editing' : 'Edit plan'}</button><button type="button" disabled={approvalPending} onClick={() => void decide('approved')}>Approve &amp; run</button><button type="button" disabled={approvalPending} onClick={() => void decide('rejected')}>Decline</button></div>}{approvalError && <small role="alert">{approvalError}</small>}</div></details>
  }
  if (type === 'done') {
    const workspacePath = typeof event.workspace_path === 'string' ? event.workspace_path : ''
    const openWorkspace = async () => {
      if (typeof event.task_id !== 'string') return
      setOpeningWorkspace(true)
      setWorkspaceOpenError('')
      try {
        const response = await fetch(`/api/agents/workspace/${encodeURIComponent(event.task_id)}/open`, { method: 'POST' })
        const result = await response.json() as { detail?: string }
        if (!response.ok) throw new Error(result.detail || 'Could not open the task workspace.')
      } catch (error) {
        setWorkspaceOpenError(error instanceof Error ? error.message : 'Could not open the task workspace.')
      } finally {
        setOpeningWorkspace(false)
      }
    }
    if (!workspacePath) return null
    return <div className="run-completion">{workspacePath && <div className="run-completion__workspace"><FolderOpen size={14} /><span title={workspacePath}>Task files saved</span><button type="button" onClick={() => void openWorkspace()} disabled={openingWorkspace} title={workspacePath}><FolderOpen size={13} />{openingWorkspace ? 'Opening…' : 'Open folder'}</button></div>}{workspaceOpenError && <small className="run-completion__error" role="alert">{workspaceOpenError}</small>}</div>
  }
  if (type === 'approval_requested') {
    const decide = async (decision: 'approved' | 'rejected') => {
      if (typeof event.run_id !== 'string' || typeof event.approval_id !== 'string' || typeof event.action_hash !== 'string') return
      setApprovalPending(true)
      setApprovalError('')
      try {
        const response = await fetch(`/api/runs/${encodeURIComponent(event.run_id)}/approvals/${encodeURIComponent(event.approval_id)}`, {
          method: 'POST', headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ action_hash: event.action_hash, decision }),
        })
        const result = await response.json() as { detail?: string; accepted?: boolean }
        if (!response.ok || !result.accepted) throw new Error(result.detail || 'This approval is no longer available.')
      } catch (error) {
        setApprovalError(error instanceof Error ? error.message : 'Could not submit approval.')
      } finally { setApprovalPending(false) }
    }
    const action = event.action && typeof event.action === 'object' ? event.action as Record<string, unknown> : {}
    const resolved = typeof event.resolved_status === 'string' ? event.resolved_status : ''
    const browserAction = action.tool === 'browser_action' || action.tool === 'browser_recipe_step'
    return <details className="run-event run-event--approval" open><summary><span>{resolved ? `Approval ${resolved}` : 'Approval required'}</span><small>{String(event.message || 'Review proposed action')}</small></summary><div className="run-event__details">{browserAction ? <><p><b>Browser action</b>{String(action.action || 'action')}</p><p><b>Target</b>{String(action.target || 'Current observed page')}</p>{action.value === '[redacted]' && <p><b>Input</b>Value hidden for privacy</p>}{action.recipe_id && <p><b>Recipe</b>{String(action.recipe_id)} · version {String(action.recipe_version || '')} · step {String(action.step || '')}</p>}</> : <p><b>File</b>{String(action.path || 'Workspace change')}</p>}<p><b>Reason</b>{String(action.summary || '')}</p>{typeof action.diff === 'string' && <pre>{action.diff}</pre>}{!resolved && <div className="approval-actions"><button type="button" disabled={approvalPending} onClick={() => void decide('approved')}>{browserAction ? 'Approve action' : 'Approve change'}</button><button type="button" disabled={approvalPending} onClick={() => void decide('rejected')}>Reject</button></div>}{approvalError && <small role="alert">{approvalError}</small>}</div></details>
  }
  if (type === 'status' || type === 'decision' || type === 'error' || type === 'cancelled' || type === 'timed_out' || type === 'interrupted') {
    const label = detail || (type === 'decision' ? 'Selected model' : 'Working')
    const icon = type === 'error' || type === 'timed_out' || type === 'interrupted' ? <CircleHelp size={13} /> : type === 'decision' ? <Sparkles size={13} /> : <Activity size={13} />
    return <div className={`run-event-status run-event-status--${type}`}><span className="run-event-status__icon">{icon}</span><span>{label}</span>{type === 'decision' && typeof event.model === 'string' && <small>{event.model}</small>}</div>
  }
  if (type === 'plan_revision') return <details className="run-event run-event--tool"><summary><span>{event.status === 'stopped' ? 'Replanning stopped' : `Plan revised · ${String(event.trigger || 'new evidence').replaceAll('_', ' ')}`}</span><small>{String(event.rationale || '')}</small></summary><div className="run-event__details">{Array.isArray(event.completed_steps) && event.completed_steps.length > 0 && <><b>Completed tool steps</b><ul>{event.completed_steps.map((step, index) => <li key={`${index}-${String(step)}`}>{String(step)}</li>)}</ul></>}{Array.isArray(event.changed_steps) && event.changed_steps.length > 0 && <><b>Remaining plan</b><ul>{event.changed_steps.map((step, index) => <li key={`${index}-${String(step)}`}>{String(step)}</li>)}</ul></>}{typeof event.rationale === 'string' && <p>{event.rationale}</p>}</div></details>
  if (type === 'delegation_plan') {
    const subtasks = Array.isArray(event.subtasks) ? event.subtasks as Array<Record<string, unknown>> : []
    return <details className="run-event run-event--plan-version"><summary><span>Approved delegation plan · {subtasks.length} subtasks</span><small>{String(event.dispatch_status || 'pending')}</small></summary><div className="run-event__details">{subtasks.map((subtask, index) => <article key={String(subtask.id || index)}><b>{String(subtask.role || 'Delegate')}: {String(subtask.purpose || '')}</b><p>Expected result: {String(subtask.expected_result || '')}</p><small>Dependencies: {Array.isArray(subtask.depends_on) && subtask.depends_on.length ? subtask.depends_on.map(String).join(', ') : 'none'} · Tools: {Array.isArray(subtask.allowed_tools) ? subtask.allowed_tools.map(String).join(', ') : ''} · Limits: {String(subtask.max_tool_calls || 0)} calls / {String(subtask.max_duration_seconds || 0)} seconds</small></article>)}<p>{String(event.message || '')}</p></div></details>
  }
  if (type === 'delegate_status') {
    const contextScope = Array.isArray(event.context_scope) ? event.context_scope.map(String) : []
    const dependencyIds = Array.isArray(event.dependency_ids) ? event.dependency_ids.map(String) : []
    const tools = Array.isArray(event.allowed_tools) ? event.allowed_tools.map(String) : []
    return <div className="run-event-status run-event-status--active"><span className="run-event-status__icon"><Activity size={13} /></span><span>{String(event.role || 'Delegate')}: {String(event.status || 'queued')} · {String(event.purpose || '')}</span><small>Model: {String(event.model || 'not selected')} · Context: {contextScope.join(', ') || 'not available'} · Workspace: {String(event.workspace_scope || 'not available')} · Permission: {String(event.permission_level || 'not available')}</small><small>Tools: {tools.join(', ')} · {String(event.max_tool_calls || '')} calls / {String(event.max_duration_seconds || '')} seconds · Dependencies: {dependencyIds.join(', ') || 'none'} · {String(event.child_run_id || '')}</small></div>
  }
  if (type === 'delegate_task_result') {
    const result = event.result && typeof event.result === 'object' ? event.result as Record<string, unknown> : {}
    const evidence = Array.isArray(result.evidence) ? result.evidence.map(String) : []
    const artifacts = Array.isArray(result.artifact_ids) ? result.artifact_ids.map(String) : []
    const incomplete = Array.isArray(result.incomplete_checks) ? result.incomplete_checks.map(String) : []
    return <details className="run-event run-event--delegate-result" open={result.status !== 'completed'}><summary><span>{String(event.subtask_id || 'Delegate')} · {String(result.status || event.status || 'result')}</span><small>{String(event.child_run_id || '')}{event.reused === true ? ' · replayed existing result' : ''}</small></summary><div className="run-event__details">{typeof result.summary === 'string' && <p>{result.summary}</p>}{evidence.length > 0 && <><b>Evidence</b><ul>{evidence.map((item, index) => <li key={`${index}-${item}`}>{item}</li>)}</ul></>}{artifacts.length > 0 && <><b>Artifacts</b><ul>{artifacts.map((item, index) => <li key={`${index}-${item}`}>{item}</li>)}</ul></>}{incomplete.length > 0 && <><b>Incomplete checks</b><ul>{incomplete.map((item, index) => <li key={`${index}-${item}`}>{item}</li>)}</ul></>}</div></details>
  }
  if (type === 'delegate_event') {
    const childEvent = event.child_event && typeof event.child_event === 'object' ? event.child_event as Record<string, unknown> : null
    if (!childEvent || childEvent.type === 'token') return null
    return <details className="run-event run-event--delegate-event"><summary><span>{String(event.subtask_id || 'Delegate')} activity</span><small>{String(childEvent.type || 'event').replaceAll('_', ' ')}</small></summary><div className="run-event__details"><RunEventCard event={childEvent} onPlanDecision={onPlanDecision} /></div></details>
  }
  if (type === 'artifact') return <div className="run-artifact"><div className="run-artifact__icon"><FileText size={16} /></div><div className="run-artifact__info"><strong>{String(event.name || 'Created file')}</strong><small>{/^([a-z]:[\\/]|\/)/i.test(String(event.path || '')) || !event.path ? 'Saved in the task folder' : `Saved to ${String(event.path)}`}</small></div>{typeof event.url === 'string' && <a href={event.url} download={String(event.name || '')} aria-label={`Download ${String(event.name || 'file')}`}><ArrowDown size={15} /> Download</a>}</div>
  if (type === 'command_start' || type === 'command_result') return <details className="run-event run-event--command"><summary><span>{event.success === false ? 'Command failed' : 'Ran a command'}</span><small>{String(event.command || event.check || event.tool || '')}</small></summary><div className="run-event__details"><pre>{String(event.command || event.tool || 'Allowlisted check')}</pre>{typeof event.output === 'string' && <pre>{event.output || '(no output)'}</pre>}</div></details>
  const title = type === 'patch' ? (event.status === 'applied' ? `Edited ${baseName(String(event.path || 'file'))}` : `Proposed an edit to ${baseName(String(event.path || 'file'))}`) : timelineSentenceCase(type.replaceAll('_', ' '))
  return <details className={`run-event${type === 'tool_start' || type === 'tool_result' ? ' run-event--tool' : ''}`}><summary><span>{title}</span>{type !== 'patch' && (tool || detail) && <small>{tool || detail}</small>}</summary><div className="run-event__details">{typeof event.reason === 'string' && <p>{event.reason}</p>}{typeof event.diff === 'string' && <pre>{event.diff}</pre>}{typeof event.content === 'string' && !event.diff && <pre>{event.content}</pre>}</div></details>
}

/** Fenced code (or prompt) block with a language label and a copy button that copies only the block's text. */
export function CodeBlock({ node, children, ...props }: ComponentPropsWithoutRef<'pre'> & ExtraProps) {
  void node
  const preRef = useRef<HTMLPreElement>(null)
  const [copied, setCopied] = useState(false)
  const child = Children.toArray(children)[0]
  const className = isValidElement<{ className?: string }>(child) ? child.props.className ?? '' : ''
  const language = /language-([\w+#.-]+)/.exec(className)?.[1] ?? ''
  useEffect(() => {
    if (!copied) return
    const timer = window.setTimeout(() => setCopied(false), 1600)
    return () => window.clearTimeout(timer)
  }, [copied])
  const copy = async () => {
    const text = preRef.current?.querySelector('code')?.textContent ?? preRef.current?.textContent ?? ''
    await copyText(text.replace(/\n$/, ''))
    setCopied(true)
  }
  return (
    <div className="code-block">
      <div className="code-block__bar">
        <span className="code-block__lang">{language || 'code'}</span>
        <button type="button" className={`code-block__copy${copied ? ' is-copied' : ''}`} onClick={() => void copy()} aria-label={copied ? 'Copied to clipboard' : `Copy ${language || 'code'}`}>
          {copied ? <Check size={13} /> : <Copy size={13} />}<span>{copied ? 'Copied' : 'Copy'}</span>
        </button>
      </div>
      <pre ref={preRef} {...props}>{children}</pre>
    </div>
  )
}

export function AgentChecks({ checks }: { checks: Array<{ passed: boolean; text: string }> }) {
  if (!checks.length) return null
  return (
    <div className="agent-checks" aria-label="Success checks">
      <span className="agent-checks__title">Checks</span>
      <ul>{checks.map((check, index) => <li key={index} className={check.passed ? 'is-passed' : 'is-open'}>{check.passed ? <Check size={13} /> : <CircleHelp size={13} />}<span>{check.text}{check.passed ? '' : ' (not verified)'}</span></li>)}</ul>
    </div>
  )
}

/** Internal bookkeeping files the agent writes for itself, not deliverables. */
const INTERNAL_ARTIFACTS = new Set(['task-memory.md'])

const RICH_STEP_TYPES = new Set(['plan', 'patch', 'command_result', 'research_sources', 'browser_screenshot', 'delegate_task_result'])

function baseName(path: string) {
  return path.split(/[\\/]/).filter(Boolean).at(-1) || path
}

function hostName(url: unknown) {
  try { return new URL(String(url)).hostname.replace(/^www\./, '') } catch { return String(url || 'page') }
}

/** One short, human sentence per agent event, or null for internal bookkeeping. */
function stepSummary(event: Record<string, unknown>): { label: string; tone: 'info' | 'error' } | null {
  const type = String(event.type || '')
  const text = (value: unknown) => (typeof value === 'string' && value.trim() ? value.trim() : '')
  switch (type) {
    case 'planning_started': return { label: 'Planning and reviewing the task', tone: 'info' }
    case 'execution_started': return { label: 'Starting the approved task', tone: 'info' }
    case 'status': {
      const message = text(event.message)
      if (!message) return null
      if (/^agent reasoning/i.test(message)) return { label: 'Thinking', tone: 'info' }
      if (/^classifying task/i.test(message)) return { label: 'Choosing a model', tone: 'info' }
      return { label: message, tone: 'info' }
    }
    case 'decision': return { label: text(event.model) ? `Chose ${text(event.model)}` : 'Chose a model', tone: 'info' }
    case 'tool_start': {
      // File edits are shown by their resulting "Edited …" step instead.
      if (/^propose_project_(patch|edit)$/.test(String(event.tool))) return null
      const input = event.input && typeof event.input === 'object' ? event.input as Record<string, unknown> : {}
      const target = text(event.path) || text(input.path)
      return { label: timelineSentenceCase(String(event.tool || 'tool').replaceAll('_', ' ')) + (target ? ` · ${baseName(target)}` : ''), tone: 'info' }
    }
    case 'tool_result': return event.status === 'error' ? { label: `${timelineSentenceCase(String(event.tool || 'tool').replaceAll('_', ' '))} failed: ${text(event.message)}`, tone: 'error' } : null
    case 'browser_open': return { label: event.visible === true ? `Opened ${hostName(event.url)} in the visible browser` : `Observed ${hostName(event.url)} headlessly`, tone: 'info' }
    case 'browser_action': return { label: `Browser ${String(event.action || 'action')}${text(event.name) ? ` · ${text(event.name)}` : ''}`, tone: 'info' }
    case 'browser_observation': return { label: `Read ${text(event.title) || hostName(event.url)}`, tone: 'info' }
    case 'command_start': return { label: `Running ${text(event.command) || 'a command'}`, tone: 'info' }
    case 'plan_revision': return { label: event.status === 'stopped' ? 'Stopped replanning' : event.trigger === 'failed_completion_check' ? 'Some checks not met yet' : event.trigger === 'review_found_gaps' ? `Review found missing features${Array.isArray(event.changed_steps) && event.changed_steps.length ? `: ${event.changed_steps.map((step) => String(step).replace(/^Implement:\s*/, '')).join(', ')}` : ''}` : 'Revised the plan', tone: 'info' }
    case 'delegate_status': return { label: `${text(event.role) || 'Helper'} ${text(event.status) || 'queued'}`, tone: 'info' }
    case 'approval_requested': return event.resolved_status && event.resolved_status !== 'approved' ? { label: `Change ${String(event.resolved_status)}`, tone: 'error' } : null
    case 'error': case 'timed_out': case 'interrupted': return { label: text(event.message) || 'Something went wrong', tone: 'error' }
    case 'cancelled': return { label: 'Stopped', tone: 'error' }
    default: return null
  }
}

export function ThinkingIndicator({ label }: { label: string }) {
  return <span className="ai-status" role="status"><span className="ai-pulse" aria-hidden="true"><i /></span><span className="ai-status__text">{label}</span></span>
}

export const RunTimeline = memo(function RunTimeline({ events, onPlanDecision }: { events: Array<Record<string, unknown> & { sequence?: number }>; onPlanDecision?: (runId: string, decision: PlanDecision) => void }) {
  const [open, setOpen] = useState(false)
  const completion = events.findLast((event) => ['done', 'error', 'cancelled', 'timed_out', 'interrupted', 'plan_rejected'].includes(String(event.type)))
  const changes = events.filter((event) => event.type === 'patch' && event.status === 'applied')
  const changedFiles = [...new Set(changes.map((event) => String(event.path || '')).filter(Boolean))]
  const additions = changes.reduce((total, event) => total + (String(event.diff || '').match(/^\+(?!\+).+/gm)?.length ?? 0), 0)
  const deletions = changes.reduce((total, event) => total + (String(event.diff || '').match(/^-(?!-).+/gm)?.length ?? 0), 0)
  const duration = Number(completion?.duration_ms)
  const durationText = Number.isFinite(duration) && duration > 0
    ? duration < 60_000 ? `${Math.ceil(duration / 1000)}s` : `${Math.floor(duration / 60_000)}m ${Math.floor(duration / 1000) % 60}s`
    : ''
  const failed = Boolean(completion && !['done', 'plan_rejected'].includes(String(completion.type)))
  const partial = completion?.type === 'error' && completion.status === 'partial'
  const permissionBlocked = events.some((event) => event.type === 'tool_result' && event.error && typeof event.error === 'object' && (event.error as Record<string, unknown>).code === 'permission_required')
  const heading = completion?.type === 'plan_rejected' ? 'Plan declined' : completion?.type === 'cancelled' ? 'Stopped' : completion?.type === 'timed_out' ? 'Timed out' : completion?.type === 'interrupted' ? 'Interrupted' : permissionBlocked ? 'Blocked' : partial ? 'Incomplete' : completion?.type === 'error' ? 'Failed' : 'Worked'
  const approvalOutcomes = new Map(events
    .map((event) => event.type === 'delegate_event' && event.child_event && typeof event.child_event === 'object' ? event.child_event as Record<string, unknown> : event)
    .filter((event) => ['approval_approved', 'approval_rejected', 'approval_expired'].includes(String(event.type)))
    .map((event) => [String(event.approval_id), String(event.type).replace('approval_', '')]))
  const planDecision = events.findLast((event) => ['plan_approved', 'plan_rejected'].includes(String(event.type)))
  const rendered = events.map((event) => {
    const childEvent = event.type === 'delegate_event' && event.child_event && typeof event.child_event === 'object' ? event.child_event as Record<string, unknown> : null
    if (childEvent?.type === 'approval_requested') return { ...childEvent, resolved_status: approvalOutcomes.get(String(childEvent.approval_id)) } as Record<string, unknown>
    if (event.type === 'approval_requested') return { ...event, resolved_status: approvalOutcomes.get(String(event.approval_id)) } as Record<string, unknown>
    if (event.type === 'plan' && planDecision) return { ...event, plan_pending: false, plan_decision: planDecision.type === 'plan_approved' ? 'approved' : 'rejected', plan: Array.isArray(planDecision.plan) ? planDecision.plan : event.plan, task_brief: event.task_brief && typeof event.task_brief === 'object' ? { ...(event.task_brief as Record<string, unknown>), success_checks: Array.isArray(planDecision.success_checks) ? planDecision.success_checks : (event.task_brief as Record<string, unknown>).success_checks } : event.task_brief } as Record<string, unknown>
    return event as Record<string, unknown>
  })
  // Things that need the person, or that they came for, stay visible outside the collapsed log.
  const needsAttention = rendered.filter((event) => (event.type === 'plan' && event.plan_pending === true) || (event.type === 'approval_requested' && !event.resolved_status))
  const artifacts = rendered.filter((event) => event.type === 'artifact' && !INTERNAL_ARTIFACTS.has(baseName(String(event.name || event.path || ''))))
  const steps = rendered
    .filter((event) => !needsAttention.includes(event) && event.type !== 'artifact' && event !== completion)
    .map((event) => ({ event, summary: stepSummary(event) }))
    .filter((step) => step.summary || RICH_STEP_TYPES.has(String(step.event.type)))
    .filter((step, index, all) => !step.summary || index === 0 || all[index - 1].summary?.label !== step.summary.label)
  const current = [...steps].reverse().find((step) => step.summary)?.summary?.label
  const running = !completion
  const label = running ? (needsAttention.length ? 'Waiting for your approval' : current || 'Working') : `${heading}${durationText ? ` for ${durationText}` : ''}`
  const errorText = permissionBlocked
    ? 'File tools are blocked under Default permissions. Choose Auto-review or Full access in the composer, then send the task again.'
    : typeof completion?.message === 'string' ? completion.message : ''
  return <section className={`run-timeline${running ? ' run-timeline--running' : ''}${failed ? (partial ? ' run-timeline--partial' : ' run-timeline--failed') : ''}`} aria-label="Agent activity">
    {steps.length > 0 || running ? <button type="button" className="run-timeline__toggle" aria-expanded={open} onClick={() => setOpen((value) => !value)} disabled={!steps.length}>
      {running ? <ThinkingIndicator label={label} /> : <><span className="run-timeline__icon">{partial ? <CircleHelp size={13} /> : failed ? <X size={13} /> : <Check size={13} />}</span><span>{label}</span></>}
      {steps.length > 0 && <small>{steps.length} {steps.length === 1 ? 'step' : 'steps'}</small>}
      {steps.length > 0 && <ChevronDown size={14} className="run-timeline__chevron" />}
    </button> : null}
    {open && <ol className="run-steps">{steps.map(({ event, summary }, index) => <li key={`${String(event.sequence ?? index)}-${index}`} className={`run-step${summary?.tone === 'error' ? ' run-step--error' : ''}`}>{RICH_STEP_TYPES.has(String(event.type)) ? <RunEventCard event={event} onPlanDecision={onPlanDecision} /> : <span>{summary?.label}</span>}</li>)}</ol>}
    {changedFiles.length > 0 && <div className="run-change-summary"><span>{changedFiles.length} {changedFiles.length === 1 ? 'file' : 'files'} changed</span><b>+{additions}</b><i>−{deletions}</i></div>}
    {needsAttention.map((event, index) => <RunEventCard key={`attention-${String(event.sequence ?? index)}`} event={event} onPlanDecision={onPlanDecision} />)}
    {failed && errorText && <p className={`run-timeline__error${partial && !permissionBlocked ? ' run-timeline__error--partial' : ''}`} role="alert">{errorText}</p>}
    {artifacts.map((event, index) => <RunEventCard key={`artifact-${String(event.sequence ?? index)}`} event={event} />)}
    {completion?.type === 'done' && (artifacts.length > 0 || changedFiles.length > 0) && <RunEventCard event={completion} />}
  </section>
})

