// One message in the conversation: the user's prompt, or an assistant turn with its steps, plan,
// approvals, reply, sources, changed and produced files, notes, and actions.
import { AlertTriangle, Box, Bot, CircleCheck, FileText, FolderOpen, Image as ImageIcon, MessageSquare, NotebookPen, Play, Terminal } from 'lucide-react'
import { relativeTime } from '../lib/api'
import { bridge, ENGINE_LABEL } from '../lib/types'
import type { Engine, Message } from '../lib/types'
import { formatDuration, turnPhases, useNow } from '../lib/timing'
import { Markdown } from './ui'
import { Mark } from './Mark'
import { PlanCard } from './PlanCard'
import { ApprovalCard, FailedCard, MessageActions, ResearchCard, Steps } from './ThreadCards'

export function EngineIcon({ engine, size = 14 }: { engine: Engine; size?: number }) {
  if (engine === 'openclaw') return <Terminal size={size} />
  if (engine === 'nemoclaw') return <Box size={size} />
  if (engine === 'agent') return <Bot size={size} />
  return <MessageSquare size={size} />
}

const NOTE_STATUS = { sending: 'Sending…', queued: 'Joins at the next step', given: 'Given to the agent', failed: 'Not sent' }


const isAbsolute = (file: string) => /^([A-Za-z]:[\\/]|[\\/])/.test(file)
const baseName = (file: string) => file.split(/[\\/]/).filter(Boolean).at(-1) ?? file

/** The web page a finished task made, as a full path: index.html first, then any other .html file. */
function demoFile(message: Message, folder: string | undefined): string {
  const join = (file: string, base = folder) => (isAbsolute(file) || !base ? file : `${base}${base.includes('\\') ? '\\' : '/'}${file}`)
  const candidates = [
    ...(message.artifacts ?? []).map((artifact) => artifact.path),
    // Files changed in an open folder are recorded relative to it; others are full paths.
    ...(message.touched ?? []).filter((file) => file.kind !== 'read').map((file) => join(file.path, message.workspacePath || folder)),
  ].filter((file) => /\.html?$/i.test(file) && isAbsolute(file))
  return candidates.find((file) => /^index\.html?$/i.test(baseName(file))) ?? candidates[0] ?? ''
}
export function MessageView({ message, live, onChange, onReport, onRetry, onRetryFrom, permissionLabel }: {
  message: Message
  live: boolean
  onChange: (next: Message) => void
  onReport?: () => void
  onRetry?: () => void
  onRetryFrom?: (step: number) => void
  permissionLabel?: string
}) {
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
  const waiting = live && !message.content && !message.plan && !(message.steps?.length)
  const phases = live ? null : turnPhases(message)
  // The task folder holds the run's files; older runs only recorded the workspace (issue #76).
  const taskFolder = message.taskFolder || message.workspacePath
  const openFolder = () => { if (taskFolder) void bridge()?.openPath(taskFolder) }
  // A PockPock Agent task that finished and passed its checks offers its result: a web page it made
  // opens in the browser ("demo"), and the task folder opens in the file manager.
  const succeeded = !live && message.engine === 'agent' && message.status === 'done' && !message.notice
  const demo = succeeded ? demoFile(message, taskFolder) : ''
  const failed = !live && message.status === 'error'
  // The error is shown on the failed card; the reply keeps only what came before it.
  const marker = message.content.lastIndexOf('**Error:**')
  const content = failed && message.engine === 'agent' ? (marker >= 0 ? message.content.slice(0, marker).trim() : '') : message.content
  return (
    <article className="message message--assistant">
      <div className="message__meta">
        <span className="message__engine"><EngineIcon engine={message.engine} size={13} />{ENGINE_LABEL[message.engine]}</span>
        {message.model && <span className="message__model">{message.model}</span>}
        {live && message.timing && <time className="message__elapsed" aria-label="Elapsed time">{formatDuration(now - message.timing.startedAt)}</time>}
      </div>
      {message.steps?.length ? <Steps steps={message.steps} live={live} endedAt={message.timing?.endedAt} /> : null}
      {message.earlierPlans?.map((plan) => <PlanCard key={plan.planId} message={message} plan={plan} onChange={onChange} earlier />)}
      {message.plan && <PlanCard key={message.plan.planId} message={message} onChange={onChange} />}
      {message.approvals?.map((approval) => (
        <ApprovalCard key={approval.id} approval={approval} permissionLabel={permissionLabel} onChange={(next) => onChange({ ...message, approvals: message.approvals?.map((item) => item.id === next.id ? next : item) })} />
      ))}
      {message.notes?.length ? (
        <ul className="notes" aria-label="Your notes">
          {message.notes.map((note) => <li key={note.id} className={`note-item note-item--${note.status}`}><NotebookPen size={13} aria-hidden="true" /><span>{note.text}</span><small>{note.error || NOTE_STATUS[note.status]}</small></li>)}
        </ul>
      ) : null}
      {waiting && <div className="thinking" role="status"><Mark size={16} working /> Thinking{message.timing && <time>{formatDuration(now - message.timing.startedAt)}</time>}</div>}
      {content && <div className={`message__body${failed && message.engine !== 'agent' ? ' is-error' : ''}`}><Markdown content={content} /></div>}
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
      {succeeded && taskFolder ? (
        <section className="card card--result" aria-label="Result">
          <header><CircleCheck size={14} aria-hidden="true" /><strong>Done{message.plan?.checks?.length ? ', and the checks passed' : ''}</strong></header>
          <p className="card__sub">{demo ? `Open ${baseName(demo)} to try the result in your browser, or open the task folder to see every file.` : 'Open the task folder to see the files this task made.'}</p>
          <div className="card__actions">
            {demo && <button type="button" className="button button--primary" onClick={() => void bridge()?.openPath(demo)} title={demo}><Play size={13} /> Open demo</button>}
            <button type="button" className={demo ? 'button' : 'button button--primary'} onClick={openFolder} title={taskFolder}><FolderOpen size={13} /> Open task folder</button>
          </div>
        </section>
      ) : taskFolder && (
        <div className="artifacts">
          <button type="button" className="artifact" onClick={openFolder} title={taskFolder}><FolderOpen size={14} /><span>Task folder</span><small>Open</small></button>
        </div>
      )}
      {failed && message.engine === 'agent' && <FailedCard message={message} onRetryFrom={onRetryFrom} onReport={onReport} />}
      {!live && (
        <div className="message__footer">
          <MessageActions message={message} onRetry={onRetry} onReport={onReport} />
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
