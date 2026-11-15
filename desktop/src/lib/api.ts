// Small helpers for the PockPock backend API (reached through the app's own origin at /api).

export class ApiError extends Error {
  status: number
  constructor(message: string, status: number) {
    super(message)
    this.status = status
  }
}

async function parse<T>(response: Response): Promise<T> {
  const body = await response.json().catch(() => ({})) as T & { detail?: unknown }
  if (!response.ok) {
    const detail = typeof body.detail === 'string' ? body.detail : Array.isArray(body.detail) ? 'The request was not valid.' : `Request failed (${response.status})`
    throw new ApiError(detail, response.status)
  }
  return body
}

export async function getJson<T>(path: string, signal?: AbortSignal): Promise<T> {
  return parse<T>(await fetch(path, { cache: 'no-store', signal }))
}

export async function sendJson<T>(path: string, body?: unknown, method = 'POST', signal?: AbortSignal): Promise<T> {
  return parse<T>(await fetch(path, {
    method,
    headers: body === undefined ? undefined : { 'Content-Type': 'application/json' },
    body: body === undefined ? undefined : JSON.stringify(body),
    signal,
  }))
}

export type StreamEvent = Record<string, unknown> & { type?: string }

/** POSTs JSON and calls `onEvent` for each server-sent `data:` event until the stream ends. */
export async function stream(path: string, body: unknown, signal: AbortSignal, onEvent: (event: StreamEvent) => void) {
  const response = await fetch(path, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body), signal })
  if (!response.ok) await parse(response)
  if (!response.body) throw new Error('The backend did not open a response stream.')
  const reader = response.body.getReader()
  const decoder = new TextDecoder()
  let buffer = ''
  while (true) {
    const { done, value } = await reader.read()
    buffer += decoder.decode(value, { stream: !done })
    const chunks = buffer.split('\n\n')
    buffer = chunks.pop() ?? ''
    for (const chunk of chunks) {
      const data = chunk.split('\n').filter((line) => line.startsWith('data:')).map((line) => line.slice(5).trimStart()).join('\n')
      if (!data) continue
      let event: StreamEvent
      try { event = JSON.parse(data) as StreamEvent } catch { continue } // ignore malformed events
      onEvent(event)
    }
    if (done) break
  }
}

export function uid() {
  return crypto.randomUUID().replaceAll('-', '').slice(0, 20)
}

export const text = (value: unknown) => (typeof value === 'string' ? value : '')

export function formatBytes(bytes: number) {
  if (!Number.isFinite(bytes) || bytes <= 0) return '0 B'
  const units = ['B', 'KB', 'MB', 'GB']
  const index = Math.min(units.length - 1, Math.floor(Math.log(bytes) / Math.log(1024)))
  return `${(bytes / 1024 ** index).toFixed(index ? 1 : 0)} ${units[index]}`
}

export function relativeTime(timestamp: number, now = Date.now()) {
  const seconds = Math.max(0, Math.round((now - timestamp) / 1000))
  if (seconds < 60) return 'now'
  const minutes = Math.round(seconds / 60)
  if (minutes < 60) return `${minutes}m`
  const hours = Math.round(minutes / 60)
  if (hours < 24) return `${hours}h`
  const days = Math.round(hours / 24)
  return days < 30 ? `${days}d` : new Date(timestamp).toLocaleDateString()
}
