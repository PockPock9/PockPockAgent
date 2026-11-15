// Timing for assistant turns: when each step, approval and phase started and ended.
// Times are recorded in the app when each stream event arrives (Date.now(), milliseconds), so they
// measure what the user experienced, including network and model load time.
import { useEffect, useState } from 'react'
import type { Message, Step } from './types'

/** "0.4 s", "12.3 s", "2 min 5.0 s", "1 h 2 min 5.0 s": tenths of a second, never rounded to whole minutes. */
export function formatDuration(ms: number): string {
  const tenths = Math.max(0, Math.round(ms / 100))
  const seconds = (tenths % 600) / 10
  const minutes = Math.floor(tenths / 600) % 60
  const hours = Math.floor(tenths / 36000)
  if (!hours && !minutes) return `${seconds.toFixed(1)} s`
  return [hours ? `${hours} h` : '', minutes || hours ? `${minutes} min` : '', `${seconds.toFixed(1)} s`].filter(Boolean).join(' ')
}

/** Fills in missing start and end times on steps and approvals, and the first-output time, at `now`. */
export function stampTiming(message: Message, now: number): Message {
  const steps = message.steps?.map((step) => {
    let next = step
    if (next.startedAt === undefined) next = { ...next, startedAt: now }
    if (next.status === 'running' && next.endedAt !== undefined) next = { ...next, endedAt: undefined }
    if (next.status !== 'running' && next.endedAt === undefined) next = { ...next, endedAt: now }
    return next
  })
  const approvals = message.approvals?.map((approval) => {
    let next = approval
    if (next.requestedAt === undefined) next = { ...next, requestedAt: now }
    const open = next.status === 'pending' || next.status === 'busy'
    if (!open && next.resolvedAt === undefined) next = { ...next, resolvedAt: now }
    return next
  })
  let timing = message.timing
  const output = Boolean(message.content || steps?.length || message.plan || approvals?.length)
  if (timing && output && timing.firstOutputAt === undefined) timing = { ...timing, firstOutputAt: now }
  return { ...message, steps, approvals, timing }
}

export function stepDuration(step: Step, now: number): number | null {
  if (step.startedAt === undefined) return null
  return (step.endedAt ?? now) - step.startedAt
}

export type Phase = { label: string; ms: number }

/** The finished turn split into phases. Time spent waiting for the user (plan review and approval
 * cards) is its own phase, so it is not counted as the model's time. Null for turns without timing. */
export function turnPhases(message: Message): Phase[] | null {
  const timing = message.timing
  if (!timing?.endedAt) return null
  const end = timing.endedAt
  const total = end - timing.startedAt
  const planWait = timing.planReadyAt ? (timing.planDecidedAt ?? end) - timing.planReadyAt : 0
  const approvalWait = (message.approvals ?? []).reduce((sum, approval) => sum + (approval.requestedAt === undefined ? 0 : Math.max(0, (approval.resolvedAt ?? end) - approval.requestedAt)), 0)
  const waiting = planWait + approvalWait
  const phases: Phase[] = []
  if (message.engine === 'agent') {
    const planning = (timing.planReadyAt ?? end) - timing.startedAt
    phases.push({ label: 'Planning', ms: planning })
    if (waiting) phases.push({ label: 'Waiting for you', ms: waiting })
    phases.push({ label: 'Working', ms: Math.max(0, total - planning - waiting) })
  } else {
    const thinking = (timing.firstOutputAt ?? end) - timing.startedAt
    phases.push({ label: 'Thinking', ms: thinking })
    if (waiting) phases.push({ label: 'Waiting for you', ms: waiting })
    phases.push({ label: message.engine === 'chat' ? 'Writing' : 'Working', ms: Math.max(0, total - thinking - waiting) })
  }
  return [...phases.filter((phase) => phase.ms >= 50), { label: 'Total', ms: total }]
}

/** The current time, updated every `interval` ms while `active`; for live counters. */
export function useNow(active: boolean, interval = 100): number {
  const [now, setNow] = useState(() => Date.now())
  useEffect(() => {
    if (!active) return
    setNow(Date.now())
    const timer = window.setInterval(() => setNow(Date.now()), interval)
    return () => window.clearInterval(timer)
  }, [active, interval])
  return now
}
