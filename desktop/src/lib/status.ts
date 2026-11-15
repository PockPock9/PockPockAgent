// Live status of the backend, Ollama, OpenClaw and NemoClaw for the status bar and pickers.
// Nothing here makes a model load: the NemoClaw sandbox check (which tests inference) runs only
// when NemoClaw is the selected engine.
import { useCallback, useEffect, useState } from 'react'
import { getJson } from './api'
import { bridge } from './types'
import type { AppState, BackendPhase, ClawStatus, NemoStatus } from './types'

export type ExtensionCounts = { skills: number; mcp: number }

export function useStatus(nemoSelected: boolean) {
  const [backend, setBackend] = useState<BackendPhase>({ phase: 'checking', detail: 'Checking the PockPock backend…', startedByApp: false })
  const [state, setState] = useState<AppState | null>(null)
  const [claw, setClaw] = useState<ClawStatus | null>(null)
  const [nemo, setNemo] = useState<NemoStatus | null>(null)
  const [nemoChecking, setNemoChecking] = useState(false)
  const [counts, setCounts] = useState<ExtensionCounts | null>(null)

  useEffect(() => {
    const desktop = bridge()
    if (!desktop) { setBackend({ phase: 'ready', detail: 'Browser preview', startedByApp: false }); return }
    void desktop.info().then((info) => setBackend(info.backend))
    return desktop.backend.onStatus(setBackend)
  }, [])

  const refreshState = useCallback(async (): Promise<AppState | null> => {
    try {
      const next = await getJson<AppState>('/api/state')
      setState(next)
      return next
    } catch {
      setState(null)
      return null
    }
  }, [])
  const refreshClaw = useCallback(async (force = false) => {
    try { setClaw(await getJson<ClawStatus>(`/api/openclaw/status${force ? '?refresh=1' : ''}`)) } catch { setClaw({ available: false, ready: false, detail: 'The PockPock backend is not reachable.' }) }
  }, [])
  const refreshNemo = useCallback(async (probe: boolean, force = false) => {
    if (probe) setNemoChecking(true)
    try {
      setNemo(await getJson<NemoStatus>(`/api/nemoclaw/status${force ? '?refresh=1' : probe ? '' : '?probe=0'}`))
    } catch {
      setNemo({ available: false, ready: false, detail: 'The PockPock backend is not reachable.' })
    } finally {
      if (probe) setNemoChecking(false)
    }
  }, [])
  const refreshCounts = useCallback(async () => {
    try {
      const list = await getJson<{ skills: unknown[]; builtin_skills: Array<{ enabled: boolean; ready: boolean }>; mcp: Array<{ enabled: boolean }> }>('/api/extensions')
      setCounts({
        skills: list.skills.length + list.builtin_skills.filter((skill) => skill.ready && skill.enabled).length,
        mcp: list.mcp.filter((server) => server.enabled).length,
      })
    } catch { setCounts(null) }
  }, [])

  const ready = backend.phase === 'ready'
  useEffect(() => {
    if (!ready) return
    void refreshState()
    void refreshClaw()
    void refreshCounts()
    const fast = window.setInterval(() => void refreshState(), 4000)
    const slow = window.setInterval(() => { void refreshClaw(); void refreshCounts() }, 30000)
    return () => { window.clearInterval(fast); window.clearInterval(slow) }
  }, [ready, refreshState, refreshClaw, refreshCounts])

  useEffect(() => {
    if (!ready) return
    void refreshNemo(nemoSelected)
  }, [ready, nemoSelected, refreshNemo])

  return { backend, state, claw, nemo, nemoChecking, counts, refreshState, refreshClaw, refreshNemo, refreshCounts }
}

export type Status = ReturnType<typeof useStatus>
