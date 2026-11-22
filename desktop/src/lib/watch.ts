// Watched research sources (UI-01E): saved sources the gateway re-reads in the background while
// PockPock runs. Off by default, per source. Backed by /api/research/watch and the per-source
// /watch route; see docs/features/agent-runs.md.
import { useCallback, useEffect, useState } from 'react'
import { getJson, relativeTime, sendJson } from './api'

export type SourceWatch = { watched: boolean; changed_at: string | null; unseen: boolean; error: string; error_at: string | null }
export type WatchedSource = { task_id: string; source_id: string; title: string; url: string; last_checked_at: string | null; next_check_at: string | null; watch: SourceWatch }
export type WatchList = { research_enabled: boolean; background: boolean; interval_minutes: number; sources: WatchedSource[] }

/** Sent after any change, so the Research page, the sources cards and the toast reload together. */
const CHANGED = 'pockpock:watch-changed'
export const announceWatchChange = () => window.dispatchEvent(new Event(CHANGED))

export async function setWatched(taskId: string, sourceId: string, watched: boolean): Promise<SourceWatch | undefined> {
  const result = await sendJson<{ source?: { watch?: SourceWatch } }>(`/api/agents/${encodeURIComponent(taskId)}/research-collection/sources/${encodeURIComponent(sourceId)}/watch`, { watched }, 'PUT')
  announceWatchChange()
  return result.source?.watch
}

export async function markSeen(taskId: string, sourceId: string) {
  await sendJson(`/api/research/watch/${encodeURIComponent(taskId)}/${encodeURIComponent(sourceId)}/seen`)
  announceWatchChange()
}

/** Checks the page now (the same check as "Check for changes"). */
export async function checkNow(taskId: string, sourceId: string): Promise<{ changed?: boolean; previous?: unknown }> {
  const result = await sendJson<{ changed?: boolean; previous?: unknown }>(`/api/agents/${encodeURIComponent(taskId)}/research-collection/sources/${encodeURIComponent(sourceId)}/refresh`)
  announceWatchChange()
  return result
}

/** The watched sources, reloaded every `pollMs` (0: only on changes) while `enabled`. */
export function useWatchedSources(pollMs: number, enabled = true) {
  const [data, setData] = useState<WatchList | null>(null)
  const [error, setError] = useState('')
  const reload = useCallback(() => {
    if (!enabled) return
    getJson<WatchList>('/api/research/watch').then((next) => { setData(next); setError('') }, (reason: unknown) => setError(reason instanceof Error ? reason.message : 'Watched pages are unavailable.'))
  }, [enabled])
  useEffect(() => {
    reload()
    window.addEventListener(CHANGED, reload)
    const timer = pollMs > 0 && enabled ? window.setInterval(reload, pollMs) : 0
    return () => { window.removeEventListener(CHANGED, reload); if (timer) window.clearInterval(timer) }
  }, [reload, pollMs, enabled])
  return { data, error, reload }
}

/** "every 6 hours", "every 30 minutes", "every day". */
export function intervalText(minutes: number): string {
  if (minutes % 1440 === 0) return minutes === 1440 ? 'every day' : `every ${minutes / 1440} days`
  if (minutes % 60 === 0) return minutes === 60 ? 'every hour' : `every ${minutes / 60} hours`
  return `every ${minutes} minutes`
}

/** "just now", "5m ago", "3h ago". */
export function ago(iso: string | null | undefined, now = Date.now()): string {
  const time = iso ? Date.parse(iso) : NaN
  if (!Number.isFinite(time)) return 'never'
  const text = relativeTime(time, now)
  return text === 'now' ? 'just now' : /^\d/.test(text) ? `${text} ago` : `on ${text}`
}

/** "in 3h", "soon". */
export function until(iso: string | null | undefined, now = Date.now()): string {
  const time = iso ? Date.parse(iso) : NaN
  if (!Number.isFinite(time) || time <= now + 60_000) return 'soon'
  return `in ${relativeTime(now, time)}`
}
