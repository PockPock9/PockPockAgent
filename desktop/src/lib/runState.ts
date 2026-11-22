// What a turn is doing right now, for the run bar and the task list: its phase (Understand, Plan,
// Act, Verify), whether it is working, slow, waiting for the user, failed or finished, and the
// text and times to show. Derived only from the message's own events and timing, so a finished or
// reloaded chat shows the same thing it showed live.
import type { Message } from './types'
import { formatDuration } from './timing'

export type RunPhaseId = 'understand' | 'plan' | 'act' | 'verify'
export type RunState = 'working' | 'slow' | 'waiting' | 'failed' | 'stopped' | 'done'
export type RunPhase = { id: RunPhaseId; label: string; status: 'done' | 'now' | 'todo' }

export type RunView = {
  state: RunState
  phases: RunPhase[]
  /** One line saying what is happening, always shown next to the mark. */
  label: string
  /** For failed runs: what is kept. For slow runs: why it may be slow. */
  detail?: string
  elapsedMs: number
  /** Time since the newest event; 0 when the turn is not live. */
  quietMs: number
  /** When the turn started waiting for the user (plan card or approval). */
  waitingSince?: number
  doneSteps: number
}

/** After this long without any event a live turn is shown as slow, with a way out. */
export const SLOW_AFTER_MS = 10_000

const AGENT_PHASES: Array<[RunPhaseId, string]> = [['understand', 'Understand'], ['plan', 'Plan'], ['act', 'Act'], ['verify', 'Verify']]
const CHAT_PHASES: Array<[RunPhaseId, string]> = [['understand', 'Understand'], ['act', 'Write']]
const CLAW_PHASES: Array<[RunPhaseId, string]> = [['understand', 'Understand'], ['act', 'Act']]

function currentPhase(message: Message): RunPhaseId {
  if (message.engine === 'agent') {
    if (message.verifying) return 'verify'
    if (message.plan?.status === 'approved') return 'act'
    if (message.plan || message.steps?.length) return 'plan'
    return 'understand'
  }
  return message.timing?.firstOutputAt || message.content || message.steps?.length ? 'act' : 'understand'
}

/** The error text of a failed turn: what App appended as "**Error:** …", or the whole reply. */
export function errorText(message: Message): string {
  const marker = message.content.lastIndexOf('**Error:**')
  const text = marker >= 0 ? message.content.slice(marker + '**Error:**'.length) : message.content
  return text.trim().split('\n')[0].slice(0, 240) || 'The run stopped on an error.'
}

export function runView(message: Message, live: boolean, now: number): RunView {
  const timing = message.timing
  const startedAt = timing?.startedAt ?? message.createdAt
  const end = live ? now : timing?.endedAt ?? timing?.lastEventAt ?? now
  const elapsedMs = Math.max(0, end - startedAt)
  const quietMs = live ? Math.max(0, now - (timing?.lastEventAt ?? startedAt)) : 0
  const steps = message.steps ?? []
  const doneSteps = steps.filter((step) => step.status === 'done').length
  const now_ = currentPhase(message)
  const list = message.engine === 'agent' ? AGENT_PHASES : message.engine === 'chat' ? CHAT_PHASES : CLAW_PHASES
  const index = list.findIndex(([id]) => id === now_)
  const finished = !live && message.status !== 'error' && message.status !== 'stopped' && message.status !== 'streaming'
  // A declined plan ends the turn at Plan; a finished run has every phase it reached done.
  const declined = message.plan?.status === 'rejected'
  const phases: RunPhase[] = list.map(([id, label], position) => ({
    id,
    label,
    status: finished && !declined ? 'done' : position < index ? 'done' : position === index ? (finished ? 'done' : 'now') : 'todo',
  }))
  const base = { phases, elapsedMs, quietMs, doneSteps }

  if (!live) {
    if (message.status === 'error') {
      const kept = [message.plan ? 'the plan' : '', doneSteps ? `${doneSteps} finished ${doneSteps === 1 ? 'step' : 'steps'}` : '', message.artifacts?.length ? `${message.artifacts.length} saved ${message.artifacts.length === 1 ? 'file' : 'files'}` : ''].filter(Boolean)
      return { ...base, state: 'failed', label: `Stopped: ${errorText(message)}`, detail: kept.length ? `Kept: ${kept.join(', ')}.` : 'Nothing was changed.' }
    }
    if (message.status === 'stopped' || message.status === 'streaming') {
      return { ...base, state: 'stopped', label: message.status === 'streaming' ? 'Interrupted: the app closed while this ran' : 'Stopped by you', detail: doneSteps ? `${doneSteps} ${doneSteps === 1 ? 'step' : 'steps'} finished before it stopped.` : undefined }
    }
    if (declined) return { ...base, state: 'done', label: 'Plan declined. Nothing ran.' }
    return { ...base, state: 'done', label: `Finished in ${formatDuration(elapsedMs)}` }
  }

  const pendingApproval = message.approvals?.find((approval) => approval.status === 'pending' || approval.status === 'busy')
  if (message.plan?.status === 'pending') {
    return { ...base, state: 'waiting', label: 'Plan ready for your review', waitingSince: timing?.planReadyAt }
  }
  if (pendingApproval) {
    return { ...base, state: 'waiting', label: `Paused: ${pendingApproval.title}`, waitingSince: pendingApproval.requestedAt }
  }
  const running = [...steps].reverse().find((step) => step.status === 'running')
  const label = running?.label || (message.content ? 'Writing the reply' : now_ === 'understand' ? 'Reading the request' : 'Working')
  if (quietMs >= SLOW_AFTER_MS) {
    const loading = !timing?.firstOutputAt || now_ === 'understand'
    return {
      ...base,
      state: 'slow',
      label: `No new output for ${Math.floor(quietMs / 1000)} s`,
      detail: loading
        ? 'The model may still be loading. Large models can take a minute the first time.'
        : `${label}. Long steps and large models can go quiet for a while.`,
    }
  }
  return { ...base, state: 'working', label }
}

/** "1 s ago", "42 s ago", "3 min ago": how long since the run last sent anything. */
export function signalAge(ms: number): string {
  const seconds = Math.floor(ms / 1000)
  return seconds < 60 ? `${seconds} s ago` : `${Math.floor(seconds / 60)} min ago`
}

/** "Waiting for approval · 4 min", "Agent · 3 steps · 0:42", "Chat · Done · 11:20" for the task list. */
export function taskSubtitle(message: Message | undefined, live: boolean, now: number, engineLabel: string): { text: string; tone: 'busy' | 'warn' | 'err' | 'ok' | 'off' } {
  if (!message || message.role !== 'assistant') return { text: engineLabel, tone: 'off' }
  const view = runView(message, live, now)
  const clock = new Date(message.timing?.endedAt ?? message.createdAt).toLocaleTimeString([], { hour: 'numeric', minute: '2-digit' })
  if (view.state === 'waiting') return { text: `Waiting for you · ${formatDuration(now - (view.waitingSince ?? now))}`, tone: 'warn' }
  if (view.state === 'working' || view.state === 'slow') return { text: `${engineLabel} · ${view.doneSteps ? `${view.doneSteps} ${view.doneSteps === 1 ? 'step' : 'steps'} · ` : ''}${formatDuration(view.elapsedMs)}`, tone: 'busy' }
  if (view.state === 'failed') return { text: `${engineLabel} · Failed · ${clock}`, tone: 'err' }
  if (view.state === 'stopped') return { text: `${engineLabel} · Stopped · ${clock}`, tone: 'off' }
  return { text: `${engineLabel} · Done · ${clock}`, tone: 'ok' }
}
