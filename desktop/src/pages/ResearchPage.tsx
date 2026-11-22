// Workshop → Research: whether PockPock Agent tasks may read public websites. Backed by
// /api/research/provider (named_host_fetcher = on, disabled = off).
import { useEffect, useState } from 'react'
import { Bookmark, Globe2, ShieldOff } from 'lucide-react'
import { ErrorNote, Loading, PageFrame, Toggle } from '../components/page'
import { getJson, sendJson } from '../lib/api'

type Provider = { provider: 'disabled' | 'named_host_fetcher'; enabled: boolean; destination: string; supports_search: boolean }

export function ResearchPage() {
  const [state, setState] = useState<Provider | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const load = () => { getJson<Provider>('/api/research/provider').then((next) => { setState(next); setError('') }, (loadError: unknown) => setError(loadError instanceof Error ? loadError.message : 'Research settings are unavailable.')) }
  useEffect(load, [])
  const choose = async (provider: Provider['provider']) => {
    setBusy(true); setError('')
    try { setState(await sendJson<Provider>('/api/research/provider', { provider }, 'PUT')) } catch (saveError) { setError(saveError instanceof Error ? saveError.message : 'Could not save.') } finally { setBusy(false) }
  }
  const on = state?.provider === 'named_host_fetcher'
  return (
    <PageFrame eyebrow="Workshop · Capabilities" title="Research" intro="Whether PockPock Agent tasks may read public websites. Sources it reads appear under its reply, where you can save them and check them for changes later.">
      <ErrorNote message={error} onRetry={load} />
      {!state && !error && <Loading>Loading…</Loading>}
      {state && (
        <>
          <div className="card setting-card">
            {on ? <Globe2 size={16} aria-hidden="true" /> : <ShieldOff size={16} aria-hidden="true" />}
            <div className="row__text"><strong>Allow reading public websites</strong>
              <span>{on ? 'On: tasks may read text from public sites they name by hostname. No general web search; private and local addresses are blocked, with time and size limits.' : 'Off: research tools make no network requests.'}</span></div>
            <Toggle checked={on} busy={busy} label="Allow reading public websites" onChange={(next) => void choose(next ? 'named_host_fetcher' : 'disabled')} />
          </div>
          <p className="note">Requests go to: {state.destination}. No API keys are used or stored. The OpenClaw engine has its own web access, controlled by its permission setting.</p>
          <p className="note note--text"><Bookmark size={13} aria-hidden="true" />Saved sources are kept with each task: open the task and use <strong>Check for changes</strong> on its sources card.</p>
        </>
      )}
    </PageFrame>
  )
}
