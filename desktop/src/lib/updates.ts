// The app's self-update state (electron/updater.cjs), kept current through the bridge.
import { useEffect, useState } from 'react'
import { bridge } from './types'
import type { UpdateState } from './types'

export function useUpdates() {
  const desktop = bridge()
  const [state, setState] = useState<UpdateState | null>(null)
  useEffect(() => {
    if (!desktop) return
    void desktop.updates.state().then(setState)
    return desktop.updates.onChange(setState)
  }, [desktop])
  return {
    state,
    check: () => desktop?.updates.check().then(setState),
    download: () => desktop?.updates.download().then(setState),
    install: () => desktop?.updates.install(),
  }
}

export type Updates = ReturnType<typeof useUpdates>

/** One plain sentence for the Settings page. */
export function updateSummary(state: UpdateState | null): string {
  if (!state) return 'Checking…'
  switch (state.status) {
    case 'unsupported': return state.error
    case 'checking': return 'Checking for a new version…'
    case 'none': return `You have the newest version (${state.current}).`
    case 'available': return state.canInstall ? `Version ${state.version} is available.` : `Version ${state.version} is available. Download it and install it like the first time.`
    case 'downloading': return `Downloading version ${state.version}… ${Math.round(state.progress * 100)}%`
    case 'ready': return `Version ${state.version} is ready. It installs when you restart PockPock, or the next time you quit it.`
    case 'error': return state.error
    default: return `Version ${state.current}. PockPock checks for updates shortly after it opens and every few hours.`
  }
}
