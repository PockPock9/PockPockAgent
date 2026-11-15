// Whether PockPock Agent may fetch public websites that a task names. Backed by /api/research/provider.
import { useEffect, useState } from 'react'
import { Globe2, LoaderCircle, ShieldOff } from 'lucide-react'
import { getJson, sendJson } from '../lib/api'

type Provider = { provider: 'disabled' | 'named_host_fetcher'; enabled: boolean; destination: string; supports_search: boolean }

export function ResearchPage() {
  const [state, setState] = useState<Provider | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  useEffect(() => { getJson<Provider>('/api/research/provider').then(setState, (loadError: unknown) => setError(loadError instanceof Error ? loadError.message : 'Research settings are unavailable.')) }, [])
  const choose = async (provider: Provider['provider']) => {
    setBusy(true)
    setError('')
    try { setState(await sendJson<Provider>('/api/research/provider', { provider }, 'PUT')) } catch (saveError) { setError(saveError instanceof Error ? saveError.message : 'Could not save.') } finally { setBusy(false) }
  }
  return (
    <div className="page">
      <div className="page__inner">
        <header className="page__head"><div><span className="eyebrow">Customize · PockPock Agent</span><h1>Research</h1><p>Whether PockPock Agent tasks may read public websites. Sources it reads appear under its reply, where you can save them to check for changes later.</p></div></header>
        {error && <div className="banner banner--error" role="alert"><span>{error}</span></div>}
        {!state && !error && <p className="note"><LoaderCircle size={13} className="spin" /> Loading…</p>}
        {state && (
          <>
            <div className="choice-cards" role="radiogroup" aria-label="Research access">
              <button type="button" role="radio" aria-checked={state.provider === 'named_host_fetcher'} className={`choice-card${state.provider === 'named_host_fetcher' ? ' is-selected' : ''}`} disabled={busy} onClick={() => void choose('named_host_fetcher')}>
                <Globe2 size={18} /><span><strong>Named public websites</strong><small>Read text from public sites the task names by hostname. No general web search. Private and local addresses are blocked, with time and size limits.</small></span>
              </button>
              <button type="button" role="radio" aria-checked={state.provider === 'disabled'} className={`choice-card${state.provider === 'disabled' ? ' is-selected' : ''}`} disabled={busy} onClick={() => void choose('disabled')}>
                <ShieldOff size={18} /><span><strong>Off</strong><small>Research tools make no network requests.</small></span>
              </button>
            </div>
            <p className="note">Requests go to: {state.destination}. No API keys are used or stored. The OpenClaw engine has its own web access, controlled by its permission setting.</p>
          </>
        )}
      </div>
    </div>
  )
}
