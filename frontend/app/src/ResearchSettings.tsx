import { useEffect, useState } from 'react'
import { Globe2, ShieldOff } from 'lucide-react'

type ProviderState = {
  provider: 'disabled' | 'named_host_fetcher'
  enabled: boolean
  destination: string
  supports_search: boolean
  credentials_configured: boolean
}

export function ResearchSettings() {
  const [state, setState] = useState<ProviderState | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')

  async function load() {
    const response = await fetch('/api/research/provider', { cache: 'no-store' })
    const payload = await response.json()
    if (!response.ok) throw new Error(payload.detail || 'Research configuration is unavailable.')
    setState(payload as ProviderState)
  }

  useEffect(() => { void load().catch((reason) => setError(String(reason))) }, [])

  async function choose(provider: ProviderState['provider']) {
    setBusy(true)
    setError('')
    try {
      const response = await fetch('/api/research/provider', {
        method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ provider }),
      })
      const payload = await response.json()
      if (!response.ok) throw new Error(payload.detail || 'Could not save research configuration.')
      setState(payload as ProviderState)
    } catch (reason) { setError(String(reason)) } finally { setBusy(false) }
  }

  return <section className="research-settings">
    <div className="research-settings__heading"><div><span className="eyebrow">Agent capabilities / Research</span><h1>Research provider</h1><p>Choose whether agent tasks may fetch public websites.</p></div></div>
    {error && <div className="research-settings__error" role="alert">{error}</div>}
    {!state ? <p>Loading local configuration…</p> : <>
      <div className="research-settings__disclosure"><Globe2 size={17}/><div><strong>Network disclosure</strong><p>{state.destination}</p><p>Only hostnames explicitly included in the task are eligible. Private and local network destinations are blocked. Requests use bounded time, page, and response limits.</p></div></div>
      <button className={`research-provider-card${state.provider === 'named_host_fetcher' ? ' research-provider-card--selected' : ''}`} disabled={busy} onClick={() => void choose('named_host_fetcher')}>
        <Globe2 size={18}/><span><strong>Named public websites</strong><small>Fetch text from a public hostname the user explicitly names. General search is not included.</small></span><b>{state.provider === 'named_host_fetcher' ? 'Enabled' : 'Enable'}</b>
      </button>
      <button className={`research-provider-card research-provider-card--disable${state.provider === 'disabled' ? ' research-provider-card--selected' : ''}`} disabled={busy} onClick={() => void choose('disabled')}>
        <ShieldOff size={18}/><span><strong>Disabled</strong><small>Prevent research fetch tools from making network requests.</small></span><b>{state.provider === 'disabled' ? 'Active' : 'Disable'}</b>
      </button>
      <p className="research-settings__note">This setting is stored in the local app database. No API keys are supported or stored by this provider.</p>
    </>}
  </section>
}
