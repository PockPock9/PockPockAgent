// When a cloud provider is disconnected, or one of its models is switched off, the app's own model
// choices that named it are cleared: the chat model (PockPock Agent and Chat), OpenClaw's model and
// the Plan in steps planner. Each then falls back to its default (smart route, OpenClaw's default
// model, one model plans and works). The main process handles the rest: the gateway's copy,
// OpenClaw's pockpock-cloud provider and NemoClaw's sandbox model (electron/cloud.cjs disconnect).
import { useEffect, useState } from 'react'
import { bridge } from './types'
import type { CloudProvider, Settings } from './types'

/** Cloud model names start with a provider id. `openrouter/` was a provider up to 0.2.8. */
const CLOUD_NAME = /^(nim|openai|anthropic|alibaba|openrouter)\//
const KEYS = ['chatModel', 'clawModel', 'agentPlanner'] as const

/** "<provider>/<model id>" for every model that is switched on for a connected provider. */
export function chosenCloudNames(providers: CloudProvider[]): Set<string> {
  return new Set(providers.filter((provider) => provider.connected).flatMap((provider) => provider.models.map((model) => `${provider.id}/${model.id}`)))
}

/** The settings to clear: those naming a cloud model that is no longer chosen. Empty when none. */
export function staleCloudChoices(settings: Settings, chosen: Set<string>): Partial<Settings> {
  const change: Partial<Settings> = {}
  for (const key of KEYS) {
    const value = settings[key]
    if (typeof value === 'string' && CLOUD_NAME.test(value) && !chosen.has(value)) change[key] = undefined
  }
  return change
}

/** Keeps the saved model choices in step with the Cloud page, at start and after every change. */
export function useCloudCleanup(settings: Settings, patch: (change: Partial<Settings>) => void, loaded: boolean) {
  const [chosen, setChosen] = useState<Set<string> | null>(null)
  useEffect(() => {
    const cloud = bridge()?.cloud
    if (!cloud) return
    let live = true
    void cloud.list().then((providers) => { if (live) setChosen(chosenCloudNames(providers)) }, () => undefined)
    const stop = cloud.onChange((providers) => setChosen(chosenCloudNames(providers)))
    return () => { live = false; stop() }
  }, [])
  const { chatModel, clawModel, agentPlanner } = settings
  useEffect(() => {
    if (!loaded || !chosen) return
    const change = staleCloudChoices({ chatModel, clawModel, agentPlanner }, chosen)
    if (Object.keys(change).length) patch(change)
  }, [loaded, chosen, chatModel, clawModel, agentPlanner, patch])
}
