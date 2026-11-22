// Sessions and settings, saved through the desktop bridge to the app's data folder (or to
// localStorage when the renderer runs in a plain browser).
import { useCallback, useEffect, useRef, useState } from 'react'
import { bridge } from './types'
import type { Message, Session, Settings } from './types'
import { uid } from './api'

const MAX_SESSIONS = 200

async function load<T>(key: 'sessions' | 'settings'): Promise<T | null> {
  const desktop = bridge()
  if (desktop) return desktop.store.get<T>(key)
  try { return JSON.parse(localStorage.getItem(`pockpock-desktop-${key}`) || 'null') as T | null } catch { return null }
}

async function save(key: 'sessions' | 'settings', value: unknown) {
  const desktop = bridge()
  if (desktop) return desktop.store.set(key, value)
  localStorage.setItem(`pockpock-desktop-${key}`, JSON.stringify(value))
  return true
}

/** A stored task that can be shown: an id and a list of message objects. */
function isSession(value: unknown): value is Session {
  const item = value as Session | null
  return Boolean(item && typeof item === 'object' && typeof item.id === 'string' && Array.isArray(item.messages) && item.messages.every((message) => message && typeof message === 'object'))
}

/** Image bytes and partial streaming state are not worth saving. */
function forStorage(sessions: Session[]): Session[] {
  return sessions.slice(0, MAX_SESSIONS).map((session) => ({
    ...session,
    messages: session.messages.map((message) => ({
      ...message,
      status: message.status === 'streaming' ? 'stopped' : message.status,
      attachments: message.attachments?.map(({ data: _data, ...rest }) => rest),
      approvals: message.approvals?.map((approval) => approval.status === 'pending' || approval.status === 'busy' ? { ...approval, status: 'expired' as const } : approval),
      steps: message.steps?.map((step) => step.status === 'running' ? { ...step, status: 'stopped' as const } : step),
      plan: message.plan?.status === 'pending' ? { ...message.plan, status: 'rejected' as const, error: 'The app closed before this plan was approved.' } : message.plan,
    })),
  }))
}

export function titleFrom(text: string) {
  const line = text.replace(/\s+/g, ' ').trim()
  return line.length > 60 ? `${line.slice(0, 57)}…` : line || 'New chat'
}

export function useSessions() {
  const [sessions, setSessions] = useState<Session[]>([])
  const [activeId, setActiveId] = useState('')
  const [loaded, setLoaded] = useState(false)
  const [saveError, setSaveError] = useState('')

  useEffect(() => {
    void load<Session[]>('sessions').then((stored) => {
      // One damaged entry must not hide (and on the next save, drop) every other task.
      const list = Array.isArray(stored) ? forStorage(stored.filter(isSession)) : []
      setSessions(list)
      setActiveId([...list].sort((a, b) => b.updatedAt - a.updatedAt)[0]?.id ?? '')
      setLoaded(true)
    })
  }, [])

  useEffect(() => {
    if (!loaded) return
    const timer = window.setTimeout(() => {
      save('sessions', forStorage(sessions)).then(() => setSaveError(''), (error: unknown) => setSaveError(error instanceof Error ? error.message : 'Chats could not be saved.'))
    }, 400)
    return () => window.clearTimeout(timer)
  }, [sessions, loaded])

  const create = useCallback(() => {
    const now = Date.now()
    const session: Session = { id: uid(), title: 'New chat', createdAt: now, updatedAt: now, messages: [] }
    setSessions((previous) => [session, ...previous])
    setActiveId(session.id)
    return session.id
  }, [])

  const update = useCallback((id: string, change: (session: Session) => Session) => {
    setSessions((previous) => previous.map((session) => session.id === id ? change(session) : session))
  }, [])

  /** Applies `change` to one message of one session. */
  const updateMessage = useCallback((sessionId: string, messageId: string, change: (message: Message) => Message) => {
    setSessions((previous) => previous.map((session) => session.id !== sessionId ? session : {
      ...session,
      updatedAt: Date.now(),
      messages: session.messages.map((message) => message.id === messageId ? change(message) : message),
    }))
  }, [])

  const remove = useCallback((id: string) => {
    setSessions((previous) => previous.filter((session) => session.id !== id))
    setActiveId((current) => current === id ? '' : current)
  }, [])

  const rename = useCallback((id: string, title: string) => {
    setSessions((previous) => previous.map((session) => session.id === id ? { ...session, title: title.trim() || session.title } : session))
  }, [])

  return { sessions, activeId, setActiveId, loaded, saveError, create, update, updateMessage, remove, rename }
}

export function useSettings() {
  const [settings, setSettings] = useState<Settings>({})
  const [loaded, setLoaded] = useState(false)
  const first = useRef(true)

  useEffect(() => {
    void load<Settings>('settings').then((stored) => {
      setSettings(stored && typeof stored === 'object' ? stored : {})
      setLoaded(true)
    })
  }, [])

  useEffect(() => {
    if (!loaded) return
    if (first.current) { first.current = false; return }
    void save('settings', settings)
  }, [settings, loaded])

  const patch = useCallback((change: Partial<Settings>) => setSettings((previous) => ({ ...previous, ...change })), [])
  return { settings, patch, loaded }
}
