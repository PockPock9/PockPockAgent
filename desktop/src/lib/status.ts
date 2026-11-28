// Live status of the backend, Ollama and OpenClaw for the status bar and pickers.
// Nothing here makes a model load.
import { useCallback, useEffect, useState } from 'react'
import { getJson } from './api'
import { bridge } from './types'
import type { AppState, BackendPhase, ClawStatus, ServiceState } from './types'

export type ExtensionCounts = { skills: number; mcp: number }

export function useStatus() {
  const [backend, setBackend] = useState<BackendPhase>({ phase: 'checking', detail: 'Checking the PockPock backend…', startedByApp: false })
  const [state, setState] = useState<AppState | null>(null)
  const [claw, setClaw] = useState<ClawStatus | null>(null)
  const [counts, setCounts] = useState<ExtensionCounts | null>(null)
  const [services, setServices] = useState<ServiceState[]>([])

  useEffect(() => {
    const desktop = bridge()
    if (!desktop) { setBackend({ phase: 'ready', detail: 'Browser preview', startedByApp: false }); return }
    void desktop.info().then((info) => setBackend(info.backend))
    void desktop.services.list().then(setServices)
    const offStatus = desktop.backend.onStatus(setBackend)
    const offServices = desktop.services.onChange(setServices)
    return () => { offStatus(); offServices() }
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
  const refreshClaw = useCallback(async (force = false): Promise<ClawStatus> => {
    let next: ClawStatus
    try { next = await getJson<ClawStatus>(`/api/openclaw/status${force ? '?refresh=1' : ''}`) } catch { next = { available: false, ready: false, detail: 'The PockPock backend is not reachable.' } }
    setClaw(next)
    return next
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

  // When OpenClaw comes up after the app started, its status follows without waiting for the next poll.
  const clawUp = services.find((item) => item.id === 'openclaw')?.status === 'running'
  useEffect(() => { if (ready) void refreshClaw(true) }, [ready, clawUp, refreshClaw])

  return { backend, state, claw, counts, services, refreshState, refreshClaw, refreshCounts }
}

export type Status = ReturnType<typeof useStatus>
