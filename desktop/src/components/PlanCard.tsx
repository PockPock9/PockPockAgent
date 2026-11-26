// The PockPock Agent plan card: what it delivers, where it works, the reviewer's notes, the
// gateway's fixed pre-check, open questions (answered in a paged dialog; the answers plan the task again),
// an editable step list (reorder, remove, add) and the success checks. Nothing runs before Approve.
import { useEffect, useRef, useState } from 'react'
import type { ReactNode } from 'react'
import { AlertTriangle, ArrowDown, ArrowUp, Check, Circle, CircleCheck, LoaderCircle, MessageCircleQuestion, Pencil, Plus, Trash2, X } from 'lucide-react'
import { answerPlan, decidePlan } from '../lib/engines'
import type { Message, PlanCard as Plan } from '../lib/types'
import { formatDuration } from '../lib/timing'
import { Mark } from './Mark'
import { QuestionsDialog, type QuestionsDraft } from './QuestionsDialog'

/** Yes/No buttons for a question that reads as one, when the planner gave no choices. */
export function choicesFor(question: string, options?: string[]): string[] {
  if (options?.length) return options
  return /^(is|are|do|does|did|should|shall|can|could|would|will|may|include|keep|use|add|want|must)\b/i.test(question.trim()) ? ['Yes', 'No'] : []
}

function EditableList({ label, items, onChange, editing, current }: { label: string; items: string[]; onChange: (items: string[]) => void; editing: boolean; current?: number }) {
  if (!editing) {
    // `current`: the step the running agent said it is on (1-based); marked, never inferred.
    return (
      <ol className="plan__list">
        {items.map((item, index) => (
          <li key={index} className={current === index + 1 ? 'is-current' : undefined} aria-current={current === index + 1 ? 'step' : undefined}>
            <span className="plan__number" aria-hidden="true">{index + 1}</span><span>{item}</span>
            {current === index + 1 && <span className="plan__now">Now</span>}
          </li>
        ))}
      </ol>
    )
  }
  const move = (index: number, by: number) => {
    const next = [...items]
    const [item] = next.splice(index, 1)
    next.splice(index + by, 0, item)
    onChange(next)
  }
  return (
    <ol className="plan__list plan__list--edit">
      {items.map((item, index) => (
        <li key={index}>
          <span className="plan__number" aria-hidden="true">{index + 1}</span>
          <input className="input" aria-label={`${label} ${index + 1}`} value={item} onChange={(event) => onChange(items.map((value, position) => position === index ? event.target.value : value))} />
          <span className="plan__row-actions">
            <button type="button" className="icon-button icon-button--small" aria-label={`Move ${label.toLowerCase()} ${index + 1} up`} title="Move up" disabled={index === 0} onClick={() => move(index, -1)}><ArrowUp size={13} /></button>
            <button type="button" className="icon-button icon-button--small" aria-label={`Move ${label.toLowerCase()} ${index + 1} down`} title="Move down" disabled={index === items.length - 1} onClick={() => move(index, 1)}><ArrowDown size={13} /></button>
            <button type="button" className="icon-button icon-button--small" aria-label={`Remove ${label.toLowerCase()} ${index + 1}`} title="Remove" onClick={() => onChange(items.filter((_, position) => position !== index))}><Trash2 size={13} /></button>
          </span>
        </li>
      ))}
      <li className="plan__add"><button type="button" className="link-button" onClick={() => onChange([...items, ''])}><Plus size={13} /> Add {label === 'Step' ? 'a step' : 'a check'}</button></li>
    </ol>
  )
}

function Row({ label, children }: { label: string; children: ReactNode }) {
  return <div className="plan__row"><dt>{label}</dt><dd>{children}</dd></div>
}

export function PlanCard({ message, plan: given, onChange, earlier }: { message: Message; plan?: Plan; onChange: (next: Message) => void; earlier?: boolean }) {
  const plan = given ?? message.plan!
  const [editing, setEditing] = useState(false)
  const [steps, setSteps] = useState(plan.steps)
  const [checks, setChecks] = useState(plan.checks)
  const [busy, setBusy] = useState<'approve' | 'decline' | 'answer' | null>(null)
  // The questions dialog opens by itself once for a new plan with questions; the card can open it again.
  const [asking, setAsking] = useState(false)
  const askedFor = useRef('')
  const [draft, setDraft] = useState<QuestionsDraft>({ page: 0, answers: [] })
  const pending = plan.status === 'pending' && !earlier
  const planningMs = message.timing?.planReadyAt ? message.timing.planReadyAt - message.timing.startedAt : null
  const setError = (error: string | undefined) => onChange({ ...message, plan: { ...plan, error } })

  const decide = async (approved: boolean) => {
    const keptSteps = steps.map((step) => step.trim()).filter(Boolean)
    const keptChecks = checks.map((check) => check.trim()).filter(Boolean)
    if (approved && (!keptSteps.length || !keptChecks.length)) { setError('Keep at least one step and one success check.'); return }
    setBusy(approved ? 'approve' : 'decline')
    try {
      await decidePlan(message.id, plan, approved, keptSteps, keptChecks)
      onChange({ ...message, plan: { ...plan, steps: keptSteps, checks: keptChecks, status: approved ? 'approved' : 'rejected', error: undefined } })
    } catch (error) {
      setError(error instanceof Error ? error.message : 'The decision was not accepted.')
    } finally {
      setBusy(null)
      setEditing(false)
    }
  }
  const submitAnswers = async (answers: { question: string; answer: string }[]) => {
    setBusy('answer')
    try { await answerPlan(message.id, plan, answers); setAsking(false) } catch (error) { setError(error instanceof Error ? error.message : 'The answers were not sent.') } finally { setBusy(null) }
  }
  useEffect(() => {
    if (pending && plan.questions.length > 0 && askedFor.current !== plan.planId) { askedFor.current = plan.planId; setAsking(true) }
  }, [pending, plan.planId, plan.questions.length])

  const status = plan.status === 'pending' ? 'Waiting for you' : plan.status === 'approved' ? 'Approved' : plan.status === 'replaced' ? 'Replaced after your answer' : 'Declined'
  // An open question is answered in the question box below, so it is not repeated as a warning.
  const warnings = (plan.precheck ?? []).filter((check) => check.status === 'warn' && check.id !== 'questions')
  return (
    <section className={`card card--plan${pending ? ' is-pending' : ''}${plan.status === 'replaced' ? ' is-muted' : ''}`} aria-label="Plan">
      <header>
        <Mark size={16} />
        <strong>{plan.sequence ? 'Plan in steps' : 'Plan'}</strong>
        <span className="card__sub">{plan.steps.length} {plan.steps.length === 1 ? 'step' : 'steps'} · {plan.sequence ? `planned by ${plan.sequence.planner}, done by ${plan.sequence.executor}` : plan.model}{planningMs !== null && !earlier ? ` · planned in ${formatDuration(planningMs)}` : ''}</span>
        <span className={`badge${pending ? ' badge--accent' : plan.status === 'approved' ? ' badge--ok' : ''}`}>{status}</span>
      </header>
      {plan.goal && <p className="card__title">{plan.goal}</p>}
      {plan.sequence && pending && (
        <p className="plan__sequence-note">
          Each step is done by {plan.sequence.executor} with only the tools that step needs, and checked before the next one starts; a step that fails is tried again, then the run stops with the earlier steps kept.
          {plan.sequence.cloud && <> <strong>A cloud model is used:</strong> your request, this plan and each step’s results (file names and short excerpts) are sent to that service.</>}
        </p>
      )}
      {plan.precheck?.length ? (
        <div className="plan__checks" aria-label="Plan checked before it was shown">
          <span className="plan__checks-label">Plan checked:</span>
          {plan.precheck.map((check) => (
            <span key={check.id} className={`badge${check.status === 'pass' ? ' badge--ok' : ' badge--warn'}`} title={check.detail}>
              {check.status === 'pass' ? <CircleCheck size={12} aria-hidden="true" /> : <AlertTriangle size={12} aria-hidden="true" />}{check.label}
            </span>
          ))}
        </div>
      ) : null}
      {warnings.length > 0 && pending && <ul className="plan__warnings">{warnings.map((check) => <li key={check.id}><AlertTriangle size={13} aria-hidden="true" />{check.detail}</li>)}</ul>}
      <dl className="plan__rows">
        {plan.deliverables.length > 0 && <Row label="Delivers"><span className="mono">{plan.deliverables.join(' · ')}</span></Row>}
        <Row label="Workspace"><span className="mono">{plan.workspace}</span></Row>
        <Row label="Task folder">{plan.taskFolder ? <span className="mono" title={plan.taskFolder}>{plan.taskFolder}</span> : 'Created when the run starts'}{plan.taskFolder && pending ? <small> · created when the run starts</small> : null}</Row>
        {(plan.critic || plan.criticFindings.length > 0) && (
          <Row label="Reviewer">{plan.critic}{plan.criticFindings.length > 0 && <ul className="plan__findings">{plan.criticFindings.map((finding, index) => <li key={index}>{finding}</li>)}</ul>}</Row>
        )}
      </dl>
      {plan.questions.length > 0 && (
        <div className="plan__questions" role="group" aria-label={plan.questions.length === 1 ? 'One question before it runs' : `${plan.questions.length} questions before it runs`}>
          <strong>{plan.questions.length === 1 ? 'One question before it runs.' : `${plan.questions.length} questions before it runs.`}</strong>
          <ol className="plan__question-list">{plan.questions.map((question, index) => <li key={index}>{question}</li>)}</ol>
          {pending && (
            <div className="card__actions">
              <button type="button" className="button button--primary" disabled={busy !== null} onClick={() => setAsking(true)}><MessageCircleQuestion size={13} /> Answer {plan.questions.length === 1 ? 'the question' : 'questions'}</button>
              <small>Or approve the plan and let the agent decide.</small>
            </div>
          )}
          {asking && pending && (
            <QuestionsDialog questions={plan.questions} options={plan.questionOptions} busy={busy === 'answer'} error={plan.error} draft={draft} onDraft={setDraft}
              onSubmit={(answers) => void submitAnswers(answers)} onClose={() => setAsking(false)} />
          )}
        </div>
      )}
      <div className="plan__section">
        <h4>{editing ? 'Steps, editable' : 'Steps'}</h4>
        <EditableList label="Step" items={steps} onChange={setSteps} editing={editing}
          current={!earlier && plan.status === 'approved' && message.status === 'streaming' && message.planStep?.total === plan.steps.length ? message.planStep.step : undefined} />
      </div>
      <div className="plan__section">
        <h4>{plan.sequence ? 'Each step’s check' : 'Success checks'}</h4>
        {editing ? <EditableList label="Success check" items={checks} onChange={setChecks} editing />
          : <ul className="plan__checklist">{checks.map((check, index) => {
            // A check is shown as passed or failed only after it ran (Plan in steps reports each step's
            // check); before that, and for checks no result is known for, it is a plain bullet.
            const result = plan.sequence && !earlier ? message.stepChecks?.[index + 1] : undefined
            return <li key={index} className={result === true ? 'is-pass' : result === false ? 'is-fail' : undefined}>
              {result === true ? <Check size={13} aria-label="Passed" /> : result === false ? <X size={13} aria-label="Failed" /> : <Circle size={9} aria-hidden="true" />}{check}
            </li>
          })}</ul>}
      </div>
      {plan.error && <p className="card__error" role="alert">{plan.error}</p>}
      {pending && (
        <div className="card__actions">
          <button type="button" className="button button--primary" disabled={busy !== null} onClick={() => void decide(true)}>{busy === 'approve' ? <LoaderCircle size={13} className="spin" /> : <Check size={13} />} Approve and run</button>
          {!plan.sequence && <button type="button" className="button" disabled={busy !== null} aria-pressed={editing} onClick={() => setEditing((value) => !value)}><Pencil size={13} /> {editing ? 'Done editing' : 'Edit plan'}</button>}
          <button type="button" className="button" disabled={busy !== null} onClick={() => void decide(false)}>{busy === 'decline' ? <LoaderCircle size={13} className="spin" /> : <X size={13} />} Decline</button>
          <span className="card__hint">Nothing runs until you approve.</span>
        </div>
      )}
    </section>
  )
}
