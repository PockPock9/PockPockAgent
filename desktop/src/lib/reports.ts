// Builds the capture for a problem report from one assistant reply and the user message before it.
// The main process sanitizes and redacts it (electron/reports.cjs); the dialog shows the result.
import { turnPhases } from './timing'
import type { Message, ReportCapture, ReportCategory, ReportStatus, Session } from './types'

export const CATEGORY_LABEL: Record<ReportCategory, { title: string; detail: string }> = {
  hang: { title: 'It hung or never finished', detail: 'Stopped responding, kept working forever, or ended mid-task.' },
  failed: { title: 'It failed', detail: 'Showed an error, a step failed, or it could not do the task.' },
  wrong: { title: 'The result was wrong', detail: 'It finished, but the answer or the change was inaccurate.' },
  other: { title: 'Something else', detail: 'Slow, confusing, or anything not listed here.' },
}

export const STATUS_LABEL: Record<ReportStatus, string> = {
  open: 'Open',
  'in-progress': 'Being fixed',
  fixed: 'Fixed',
  'wont-fix': 'Won’t fix',
}

export function buildCapture(session: Session, message: Message, app: { version: string; platform: string }): ReportCapture {
  const index = session.messages.findIndex((item) => item.id === message.id)
  const user = [...session.messages.slice(0, Math.max(0, index))].reverse().find((item) => item.role === 'user')
  return {
    appVersion: app.version,
    platform: app.platform,
    engine: message.engine,
    model: message.model ?? '',
    chatTitle: session.title,
    createdAt: message.createdAt,
    userMessage: user?.content ?? '',
    attachments: (user?.attachments ?? []).map((file) => file.name), // names only, never contents
    reply: message.content,
    status: message.status ?? '',
    notice: message.notice ?? '',
    plan: message.plan ? { goal: message.plan.goal, steps: message.plan.steps, status: message.plan.status } : undefined,
    steps: (message.steps ?? []).map((step) => ({
      label: step.label,
      status: step.status,
      detail: step.detail ?? '',
      ms: step.startedAt !== undefined && step.endedAt !== undefined ? step.endedAt - step.startedAt : undefined,
    })),
    approvals: (message.approvals ?? []).map((approval) => ({ title: approval.title, description: approval.description, status: approval.status })),
    timing: turnPhases(message) ?? [],
  }
}

/** "2 folder paths and 1 user name" — what redaction hid, for the dialog. */
export function describeRedactions(redactions: { path: number; user: number; email: number; token: number }): string {
  const parts = [
    [redactions.path, 'folder path', 'folder paths'],
    [redactions.user, 'user name', 'user names'],
    [redactions.email, 'email address', 'email addresses'],
    [redactions.token, 'key or token', 'keys or tokens'],
  ].filter(([count]) => Number(count) > 0).map(([count, one, many]) => `${count} ${Number(count) === 1 ? one : many}`)
  if (!parts.length) return 'Nothing personal was found to hide.'
  return `Hidden before saving: ${parts.length === 1 ? parts[0] : `${parts.slice(0, -1).join(', ')} and ${parts[parts.length - 1]}`}.`
}

/** The capture as plain text, for "What will be saved" and the Maintenance page. */
export function captureText(capture: ReportCapture): string {
  const lines: string[] = [
    `PockPock Agent ${capture.appVersion} on ${capture.platform} · ${capture.engine}${capture.model ? ` · ${capture.model}` : ''}`,
    capture.chatTitle ? `Chat: ${capture.chatTitle}` : '',
    '',
    'You asked:',
    capture.userMessage || '(empty)',
    capture.attachments.length ? `Attached: ${capture.attachments.join(', ')} (names only)` : '',
  ]
  if (capture.plan) lines.push('', `Plan (${capture.plan.status}): ${capture.plan.goal}`, ...capture.plan.steps.map((step, index) => `  ${index + 1}. ${step}`))
  if (capture.steps.length) {
    lines.push('', 'Steps:')
    for (const step of capture.steps) lines.push(`  [${step.status}] ${step.label}${step.ms !== undefined ? ` (${(step.ms / 1000).toFixed(1)} s)` : ''}${step.detail ? `\n      ${step.detail}` : ''}`)
  }
  if (capture.approvals.length) {
    lines.push('', 'Approvals:')
    for (const approval of capture.approvals) lines.push(`  [${approval.status}] ${approval.title}: ${approval.description}`)
  }
  lines.push('', `Reply (${capture.status || 'unknown'}):`, capture.reply || '(no reply)')
  if (capture.notice) lines.push('', `Notice: ${capture.notice}`)
  if (capture.timing.length) lines.push('', `Time: ${capture.timing.map((phase) => `${phase.label} ${((phase.ms ?? 0) / 1000).toFixed(1)} s`).join(' · ')}`)
  return lines.filter((line, index, all) => line !== '' || (all[index - 1] !== '' && index > 0)).join('\n')
}
