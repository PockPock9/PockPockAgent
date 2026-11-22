// Ctrl/Cmd K: one search box for tasks, pages, themes and panel commands. Arrow keys move,
// Enter runs, Escape closes and gives focus back to where it was.
import { useEffect, useMemo, useRef, useState } from 'react'
import type { KeyboardEvent, ReactNode } from 'react'
import { ListTodo, Palette, PanelBottom, PanelRight, Plus, Search } from 'lucide-react'
import type { Session } from '../lib/types'
import { THEMES } from '../lib/theme'
import { PAGE_LABEL, WORKSHOP_GROUPS } from './Shell'
import type { Page } from './Shell'

type Command = { id: string; group: string; title: string; detail?: string; icon: ReactNode; run: () => void }

export function CommandPalette({ sessions, theme, onClose, onNew, onOpenTask, onPage, onTheme, onToggle }: {
  sessions: Session[]
  theme: string
  onClose: () => void
  onNew: () => void
  onOpenTask: (id: string) => void
  onPage: (page: Page) => void
  onTheme: (id: string) => void
  onToggle: (panel: 'inspector' | 'terminal') => void
}) {
  const [query, setQuery] = useState('')
  const [index, setIndex] = useState(0)
  const inputRef = useRef<HTMLInputElement>(null)
  const listRef = useRef<HTMLUListElement>(null)
  const returnTo = useRef<Element | null>(document.activeElement)

  useEffect(() => {
    inputRef.current?.focus()
    const target = returnTo.current
    return () => { if (target instanceof HTMLElement) target.focus() }
  }, [])

  const commands = useMemo<Command[]>(() => {
    const all: Command[] = [
      { id: 'new', group: 'Actions', title: 'New task', icon: <Plus size={14} />, run: onNew },
      { id: 'inspector', group: 'Actions', title: 'Show or hide the inspector', icon: <PanelRight size={14} />, run: () => onToggle('inspector') },
      { id: 'terminal', group: 'Actions', title: 'Show or hide the terminal', icon: <PanelBottom size={14} />, run: () => onToggle('terminal') },
      { id: 'page:chat', group: 'Go to', title: 'Tasks', icon: <ListTodo size={14} />, run: () => onPage('chat') },
      ...WORKSHOP_GROUPS.flatMap((group) => group.items.map((item) => ({ id: `page:${item.page}`, group: 'Go to', title: `Workshop · ${item.label}`, detail: group.label, icon: item.icon, run: () => onPage(item.page) }))),
      { id: 'page:settings', group: 'Go to', title: PAGE_LABEL.settings, icon: <Palette size={14} />, run: () => onPage('settings') },
      ...THEMES.map((item) => ({ id: `theme:${item.id}`, group: 'Settings · Theme', title: item.name, detail: item.id === theme ? 'Current theme' : item.detail, icon: <Palette size={14} />, run: () => onTheme(item.id) })),
      ...[...sessions].sort((a, b) => b.updatedAt - a.updatedAt).slice(0, 30).map((session) => ({ id: `task:${session.id}`, group: 'Tasks', title: session.title, icon: <ListTodo size={14} />, run: () => onOpenTask(session.id) })),
    ]
    const needle = query.trim().toLowerCase()
    if (!needle) return all
    const words = needle.split(/\s+/)
    return all.filter((command) => words.every((word) => `${command.title} ${command.group} ${command.detail ?? ''}`.toLowerCase().includes(word)))
  }, [query, sessions, theme, onNew, onOpenTask, onPage, onTheme, onToggle])

  useEffect(() => { setIndex(0) }, [query])
  useEffect(() => { listRef.current?.querySelector('[aria-selected="true"]')?.scrollIntoView({ block: 'nearest' }) }, [index])

  const run = (command: Command | undefined) => { if (!command) return; onClose(); command.run() }
  const onKey = (event: KeyboardEvent) => {
    if (event.key === 'Escape') { event.preventDefault(); onClose() }
    else if (event.key === 'ArrowDown') { event.preventDefault(); setIndex((value) => Math.min(commands.length - 1, value + 1)) }
    else if (event.key === 'ArrowUp') { event.preventDefault(); setIndex((value) => Math.max(0, value - 1)) }
    else if (event.key === 'Enter') { event.preventDefault(); run(commands[index]) }
  }
  let lastGroup = ''
  return (
    <div className="modal-backdrop modal-backdrop--top" onMouseDown={(event) => { if (event.target === event.currentTarget) onClose() }}>
      <div className="palette" role="dialog" aria-modal="true" aria-label="Command palette" onKeyDown={onKey}>
        <label className="palette__search">
          <Search size={15} aria-hidden="true" />
          <input ref={inputRef} type="text" role="combobox" aria-expanded="true" aria-controls="palette-list" aria-activedescendant={commands[index] ? `palette-${commands[index].id}` : undefined}
            placeholder="Type a task, page or setting" value={query} onChange={(event) => setQuery(event.target.value)} aria-label="Search" />
          <kbd>Esc</kbd>
        </label>
        <ul ref={listRef} id="palette-list" role="listbox" className="palette__list" aria-label="Results">
          {!commands.length && <li className="palette__empty">Nothing matches “{query}”.</li>}
          {commands.map((command, position) => {
            const header = command.group !== lastGroup ? command.group : ''
            lastGroup = command.group
            return [
              header ? <li key={`group:${header}`} className="palette__group" role="presentation">{header}</li> : null,
              <li key={command.id} id={`palette-${command.id}`} role="option" aria-selected={position === index} className={`palette__item${position === index ? ' is-active' : ''}`}
                onMouseMove={() => setIndex(position)} onClick={() => run(command)}>
                <span className="palette__icon">{command.icon}</span>
                <span className="palette__title">{command.title}</span>
                {command.detail && <small>{command.detail}</small>}
              </li>,
            ]
          })}
        </ul>
      </div>
    </div>
  )
}
