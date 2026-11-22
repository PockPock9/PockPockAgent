// The task list beside the conversation: New task, search, and tasks grouped as Needs you, Running,
// Today, This week and Older. Each row says what its newest turn is doing (lib/runState.ts).
import { useMemo, useState } from 'react'
import { Plus, Search, Trash2 } from 'lucide-react'
import { ENGINE_LABEL } from '../lib/types'
import type { Session } from '../lib/types'
import { runView, taskSubtitle } from '../lib/runState'
import { useNow } from '../lib/timing'
import { mod } from '../lib/platform'
import { Dot } from './ui'

function groupOf(timestamp: number) {
  const age = Date.now() - timestamp
  if (age < 86_400_000 && new Date(timestamp).getDate() === new Date().getDate()) return 'Today'
  if (age < 7 * 86_400_000) return 'This week'
  return 'Older'
}

export function TaskPanel({ overlay, sessions, activeId, isChat, running, onSelect, onNew, onDelete }: {
  overlay?: boolean
  sessions: Session[]
  activeId: string
  isChat: boolean
  running: { sessionId: string; messageId: string } | null
  onSelect: (id: string) => void
  onNew: () => void
  onDelete: (id: string) => void
}) {
  const [query, setQuery] = useState('')
  const now = useNow(Boolean(running), 1000)
  const groups = useMemo(() => {
    const needle = query.trim().toLowerCase()
    const sorted = [...sessions]
      .filter((session) => !needle || session.title.toLowerCase().includes(needle) || session.messages.some((message) => message.content.toLowerCase().includes(needle)))
      .sort((a, b) => b.updatedAt - a.updatedAt)
    const result: Array<[string, Session[]]> = []
    const add = (label: string, session: Session) => {
      const group = result.find(([name]) => name === label)
      if (group) group[1].push(session)
      else result.push([label, [session]])
    }
    for (const session of sorted) {
      const last = session.messages.at(-1)
      const live = running?.sessionId === session.id && running.messageId === last?.id
      if (live && last) add(runView(last, true, Date.now()).state === 'waiting' ? 'Needs you' : 'Running', session)
    }
    for (const session of sorted) if (running?.sessionId !== session.id) add(groupOf(session.updatedAt), session)
    const order = ['Needs you', 'Running', 'Today', 'This week', 'Older']
    return result.sort((a, b) => order.indexOf(a[0]) - order.indexOf(b[0]))
    // `now` refreshes the Needs you / Running split while a task runs.
  }, [sessions, query, running, now]) // eslint-disable-line react-hooks/exhaustive-deps

  return (
    <aside className={`panel${overlay ? ' is-overlay' : ''}`} aria-label="Tasks">
      <div className="panel__top">
        <button type="button" className="new-task" onClick={onNew}><Plus size={15} /> New task <kbd>{mod}N</kbd></button>
        <label className="search">
          <Search size={13} />
          <input type="search" placeholder="Search tasks" value={query} onChange={(event) => setQuery(event.target.value)} aria-label="Search tasks" />
        </label>
      </div>
      <nav className="tasks" aria-label="Tasks">
        {!sessions.length && <p className="tasks__empty">No tasks yet. Describe one in the box on the right, or press New task.</p>}
        {sessions.length > 0 && !groups.length && <p className="tasks__empty">No tasks match “{query}”.</p>}
        {groups.map(([label, items]) => (
          <div key={label} className="tasks__group">
            <div className="section-label">{label}</div>
            {items.map((session) => {
              const last = session.messages.at(-1)
              const live = running?.sessionId === session.id && running.messageId === last?.id
              const engine = last?.engine ?? 'agent'
              const subtitle = taskSubtitle(last, live, now, ENGINE_LABEL[engine])
              const current = isChat && session.id === activeId
              return (
                <div key={session.id} className={`task${current ? ' is-active' : ''}`}>
                  <button type="button" className="task__open" onClick={() => onSelect(session.id)} aria-current={current ? 'page' : undefined}>
                    <span className="task__icon"><Dot tone={subtitle.tone} /></span>
                    <span className="task__text">
                      <span className="task__title">{session.title}</span>
                      <small>{session.messages.length ? subtitle.text : 'Empty'}</small>
                    </span>
                  </button>
                  <button type="button" className="task__delete" onClick={() => onDelete(session.id)} aria-label={`Delete task ${session.title}`} title="Delete task" disabled={running?.sessionId === session.id}><Trash2 size={13} /></button>
                </div>
              )
            })}
          </div>
        ))}
      </nav>
    </aside>
  )
}
