// The run bar above every conversation: phases, what is happening now, time since the last event,
// elapsed time and Stop, over a 2 px track. Working sweeps the track and pulses the mark's bolt;
// waiting for the user is a solid accent track and a still bolt; failed is an error track with
// what was kept and what to do next; a live run quiet for 10 s says so and offers a way out.
// Status text and elapsed time are always shown, so the app never looks hung (reduced motion too).
import { useState } from 'react'
import { Check, Eye, Flag, RotateCcw, ServerCog, Square, Timer, Zap } from 'lucide-react'
import type { Message } from '../lib/types'
import { runView, signalAge } from '../lib/runState'
import { formatDuration, useNow } from '../lib/timing'
import { Mark } from './Mark'

const SNOOZE_MS = 30_000

export function RunBar({ message, live, onStop, onRetry, onSmaller, smallerModel, onOpenServices, onReport }: {
  message: Message
  live: boolean
  onStop: () => void
  onRetry?: () => void
  /** Stops the run and sends the same request with a smaller local model. */
  onSmaller?: () => void
  smallerModel?: string
  onOpenServices: () => void
  onReport?: () => void
}) {
  const now = useNow(live, 250)
  const [snoozedUntil, setSnoozedUntil] = useState(0)
  const view = runView(message, live, now)
  const slow = view.state === 'slow' && now >= snoozedUntil
  // A snoozed slow run keeps the working look; the label still says how long it has been quiet.
  const state = view.state === 'slow' && !slow ? 'working' : view.state
  const review = () => {
    const card = document.querySelector<HTMLElement>('.card.is-pending')
    card?.scrollIntoView({ behavior: 'smooth', block: 'center' })
    card?.querySelector<HTMLButtonElement>('button:not(:disabled)')?.focus({ preventScroll: true })
  }
  return (
    <div className={`runbar runbar--${state}`}>
      <div className="runbar__row">
        <ol className="runbar__phases" aria-label="Phases">
          {view.phases.map((phase, index) => (
            <li key={phase.id} className={`runbar__phase is-${phase.status}`} aria-current={phase.status === 'now' ? 'step' : undefined}>
              <span className="runbar__marker" aria-hidden="true">{phase.status === 'done' ? <Check size={11} strokeWidth={3} /> : index + 1}</span>
              <span>{phase.label}</span>
              <span className="visually-hidden">{phase.status === 'done' ? ' (done)' : phase.status === 'now' ? ' (current)' : ''}</span>
            </li>
          ))}
        </ol>
        <div className="runbar__now">
          <Mark size={16} working={state === 'working'} />
          <span className="runbar__label" title={view.label} aria-hidden="true">{view.label}</span>
          {/* Announced text stays stable while a slow run's seconds count up. */}
          <span role="status" aria-live="polite" className="visually-hidden">{slow ? 'Still working, but no new output for a while' : view.label}</span>
        </div>
        <div className="runbar__controls">
        {live && state !== 'waiting' && <span className="runbar__signal" title="Time since the run last sent anything"><span className={`runbar__pulse${view.quietMs < 2000 ? ' is-fresh' : ''}`} aria-hidden="true" />Signal {signalAge(view.quietMs)}</span>}
        {state === 'waiting' && view.waitingSince && <span className="runbar__signal" title="Nothing runs until you answer">Waiting {formatDuration(now - view.waitingSince)}</span>}
        <time className="runbar__elapsed" aria-label="Elapsed time"><Timer size={13} aria-hidden="true" />{formatDuration(view.elapsedMs)}</time>
        {state === 'waiting' && <button type="button" className="button button--small button--primary" onClick={review}><Eye size={13} /> Review</button>}
        {live && <button type="button" className="button button--small runbar__stop" onClick={onStop}><Square size={11} /> Stop</button>}
        </div>
      </div>
      <div className="runbar__track" aria-hidden="true" />
      {slow && (
        <div className="runbar__note" role="alert">
          <span>{view.detail}</span>
          <span className="runbar__actions">
            <button type="button" className="button button--small" onClick={() => setSnoozedUntil(now + SNOOZE_MS)}>Keep waiting</button>
            {onSmaller && smallerModel && <button type="button" className="button button--small" onClick={onSmaller} title={`Stop, then send the same request with ${smallerModel}`}><Zap size={12} /> Use {smallerModel}</button>}
            <button type="button" className="button button--small" onClick={onStop}><Square size={11} /> Stop</button>
          </span>
        </div>
      )}
      {view.state === 'failed' && (
        <div className="runbar__note runbar__note--error">
          <span>{view.detail}</span>
          <span className="runbar__actions">
            {onRetry && <button type="button" className="button button--small button--primary" onClick={onRetry}><RotateCcw size={12} /> Retry</button>}
            <button type="button" className="button button--small" onClick={onOpenServices}><ServerCog size={12} /> Open Services</button>
            {onReport && <button type="button" className="button button--small" onClick={onReport}><Flag size={12} /> Report</button>}
          </span>
        </div>
      )}
    </div>
  )
}
