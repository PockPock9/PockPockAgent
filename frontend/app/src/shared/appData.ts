// State shared by the web dashboard (App.tsx) and the desktop app (desktop/DesktopApp.tsx):
// the polled local API state and the conversation list kept in browser storage.
import { useCallback, useEffect, useState } from 'react'
import type { Attachment, Conversation } from '../features/chat/chatTypes'
import { createId } from '../features/chat/chatUtils'
import type { AppState } from '../features/models/modelTypes'

export const STORAGE_KEY = 'frog-ai-conversations-v1'

export const EMPTY_STATE: AppState = {
  api_connected: false,
  connected: false,
  error: '',
  router_enabled: true,
  classifier: 'qwen2.5:1.5b',
  models: [],
  events: [],
  active: [],
  totals: {},
}

export function withoutAttachmentData(attachment: Attachment): Attachment {
  const { data: _data, ...saved } = attachment
  return saved
}

export function readConversations(): Conversation[] {
  try {
    const stored = localStorage.getItem(STORAGE_KEY)
    if (!stored) return []
    const parsed: Conversation[] = JSON.parse(stored)
    return parsed.map((conversation) => ({
      ...conversation,
      messages: conversation.messages.map((message) => ({
        ...message,
        attachments: message.attachments?.map(withoutAttachmentData),
      })),
    }))
  } catch (error) {
    console.error('Could not restore local chat history:', error)
    return []
  }
}

/** Polls `/api/state` every 1.8 s. `refresh` forces an immediate read and returns the result. */
export function useLocalState() {
  const [state, setState] = useState<AppState>(EMPTY_STATE)
  const refresh = useCallback(async () => {
    try {
      const response = await fetch('/api/state', { cache: 'no-store' })
      if (!response.ok) throw new Error(`Local API returned ${response.status}`)
      const nextState = await response.json() as AppState
      setState(nextState)
      return nextState
    } catch (error) {
      setState((previous) => ({
        ...previous,
        api_connected: false,
        connected: false,
        error: error instanceof Error ? error.message : 'Local API is unreachable',
      }))
      return null
    }
  }, [])

  useEffect(() => {
    const initialRefresh = window.setTimeout(() => void refresh(), 0)
    const timer = window.setInterval(() => void refresh(), 1800)
    return () => {
      window.clearTimeout(initialRefresh)
      window.clearInterval(timer)
    }
  }, [refresh])

  return { state, refresh }
}

/** The conversation list, restored from and saved to browser storage (attachment bytes are not saved). */
export function useConversations() {
  const [initial] = useState(() => {
    const saved = readConversations()
    const active = [...saved].sort((a, b) => b.updatedAt - a.updatedAt)[0]
    return { conversations: saved, activeId: active?.id ?? '' }
  })
  const [conversations, setConversations] = useState<Conversation[]>(initial.conversations)
  const [activeId, setActiveId] = useState(initial.activeId)
  const [storageError, setStorageError] = useState('')

  useEffect(() => {
    if (conversations.length === 0) {
      try {
        localStorage.removeItem(STORAGE_KEY)
      } catch (error) {
        console.error('Could not clear local chat history in this browser:', error)
        // oxlint-disable-next-line react/set-state-in-effect -- Surface storage failures when clearing is requested.
        setStorageError('Local chat history could not be cleared in this browser.')
      }
      return
    }
    const timeout = window.setTimeout(() => {
      try {
        const serializable = conversations.map((conversation) => ({
          ...conversation,
          messages: conversation.messages.map((message) => ({
            ...message,
            attachments: message.attachments?.map(withoutAttachmentData),
          })),
        }))
        localStorage.setItem(STORAGE_KEY, JSON.stringify(serializable))
      } catch (error) {
        console.error('Could not persist chat history in this browser:', error)
        setStorageError('Local chat history could not be saved. Browser storage may be full.')
      }
    }, 250)
    return () => window.clearTimeout(timeout)
  }, [conversations])

  /** Adds an empty conversation at the top, selects it, and returns its id. */
  const createConversation = useCallback((title = 'New conversation') => {
    const id = createId()
    const updatedAt = Date.now()
    setConversations((previous) => [{ id, title, updatedAt, messages: [] }, ...previous])
    setActiveId(id)
    return id
  }, [])

  return { conversations, setConversations, activeId, setActiveId, storageError, setStorageError, createConversation }
}
