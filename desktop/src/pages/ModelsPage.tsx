// Workshop → Local models: Smart route, then every model Ollama has on this PC with what it is good
// for (from Ollama's own details), how it has done (calls, success, average time), whether it is
// loaded, and a switch that offers it to Smart route and the model menus.
import { useState } from 'react'
import { RefreshCw, Server, Sparkles, SquareTerminal } from 'lucide-react'
import { Empty } from '../components/ui'
import { ErrorNote, PageFrame, Toggle } from '../components/page'
import { formatBytes, sendJson } from '../lib/api'
import type { Status } from '../lib/status'
import type { Model } from '../lib/types'

/** What a model is for, from Ollama's details: never a guess from its name. */
function tags(model: Model): string[] {
  const details = model.details ?? {}
  const families = Array.isArray(details.families) ? details.families.map(String) : [String(details.family ?? '')]
  const result: string[] = []
  if (model.embedding) result.push('Embeddings')
  if (families.some((family) => /clip|mllama|vision/i.test(family))) result.push('Images')
  if (typeof details.parameter_size === 'string') result.push(details.parameter_size)
  if (typeof details.quantization_level === 'string') result.push(details.quantization_level)
  return result
}

export function ModelsPage({ status, onOpenTerminal }: { status: Status; onOpenTerminal: () => void }) {
  const [pending, setPending] = useState('')
  const [error, setError] = useState('')
  const [refreshing, setRefreshing] = useState(false)
  const models = status.state?.models ?? []
  const toggle = async (name: string, enabled: boolean) => {
    setPending(name); setError('')
    try { await sendJson(`/api/models/${encodeURIComponent(name)}`, { enabled }, 'PUT'); await status.refreshState() } catch (toggleError) { setError(toggleError instanceof Error ? toggleError.message : 'Could not change that model.') } finally { setPending('') }
  }
  const router = async (enabled: boolean) => {
    setPending('router'); setError('')
    try { await sendJson('/api/router', { enabled }, 'PUT'); await status.refreshState() } catch (routerError) { setError(routerError instanceof Error ? routerError.message : 'Could not change Smart route.') } finally { setPending('') }
  }
  const refresh = async () => { setRefreshing(true); try { await status.refreshState() } finally { setRefreshing(false) } }
  const stats = (model: Model & { calls?: number; successes?: number; avg_ms?: number | null }) => [
    formatBytes(model.size),
    model.calls ? `${model.calls} ${model.calls === 1 ? 'call' : 'calls'}` : 'not used yet',
    model.calls ? `${Math.round(((model.successes ?? 0) / model.calls) * 100)}% succeeded` : '',
    model.avg_ms ? `${(model.avg_ms / 1000).toFixed(1)} s average` : '',
  ].filter(Boolean).join(' · ')
  return (
    <PageFrame eyebrow="Workshop · Models" title="Local models" intro="Models served by Ollama on this PC. A model loads into memory only when a task uses it."
      actions={<button type="button" className="button" onClick={() => void refresh()} disabled={refreshing}><RefreshCw size={13} className={refreshing ? 'spin' : undefined} /> Refresh</button>}>
      <ErrorNote message={error} />
      {status.state && (
        <div className="card setting-card">
          <Sparkles size={16} aria-hidden="true" />
          <div className="row__text"><strong>Smart route</strong><span>{status.state.router_enabled === false ? 'Paused: Chat and PockPock Agent will not answer until it is on.' : 'Picks the best switched-on local model for each request. Cloud models are never chosen automatically.'}</span></div>
          <span className="badge badge--off">Local only</span>
          <Toggle checked={status.state.router_enabled !== false} busy={pending === 'router'} label="Smart route" onChange={(next) => void router(next)} />
        </div>
      )}
      {!status.state ? <ErrorNote message="The PockPock gateway is not answering, so models cannot be listed. Start it from Services." />
        : !status.state.connected ? <ErrorNote message={status.state.error || 'Ollama is not running. Start it from Services.'} />
          : !models.length ? <Empty icon={<Server size={20} />} title="No models installed"><p>Install one with <code>ollama pull qwen3.5:9b</code> in the terminal.</p><button type="button" className="button" onClick={onOpenTerminal}><SquareTerminal size={13} /> Open terminal</button></Empty>
            : (
              <>
                <h2 className="list-title">Installed on this PC <small>{models.length}</small></h2>
                <ul className="rows">
                  {models.map((model) => (
                    <li key={model.name} className={`row${model.enabled ? '' : ' row--off'}`}>
                      <Server size={16} className="row__icon" aria-hidden="true" />
                      <div className="row__text">
                        <strong>{model.name} <small className={`badge ${model.running ? 'badge--ok' : model.enabled ? 'badge--off' : 'badge--warn'}`}>{model.running ? 'Loaded' : model.enabled ? 'Idle' : 'Switched off'}</small></strong>
                        <span>{stats(model)}</span>
                        {tags(model).length > 0 && <span className="tags">{tags(model).map((tag) => <em key={tag}>{tag}</em>)}</span>}
                      </div>
                      <Toggle checked={model.enabled} busy={pending === model.name} label={`Use ${model.name}`} onChange={(next) => void toggle(model.name, next)} />
                    </li>
                  ))}
                </ul>
                <p className="note">Switched-off models are not offered by Smart route or the model menus. Embedding models answer no chat; PockPock uses them for search and memory.</p>
              </>
            )}
    </PageFrame>
  )
}
