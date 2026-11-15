import { useEffect, useState } from 'react'
import { Sparkles, Trash2 } from 'lucide-react'

type Preference = {
  id: string
  category: string
  preference: string
  updated_at: string
}

type MemoryState = {
  enabled: boolean
  preferences: Preference[]
}

async function readMemoryState(response: Response): Promise<MemoryState> {
  const payload = await response.json()
  if (!response.ok) throw new Error(payload.detail || 'Local memory settings are unavailable.')
  return payload as MemoryState
}

export function MemorySettings() {
  const [state, setState] = useState<MemoryState | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')

  async function load() {
    const response = await fetch('/api/memory/preferences', { cache: 'no-store' })
    setState(await readMemoryState(response))
  }

  useEffect(() => { void load().catch((reason) => setError(String(reason))) }, [])

  async function update(enabled: boolean) {
    setBusy(true)
    setError('')
    try {
      const response = await fetch('/api/memory/preferences/settings', {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ enabled }),
      })
      setState(await readMemoryState(response))
    } catch (reason) {
      setError(String(reason))
    } finally {
      setBusy(false)
    }
  }

  async function remove(preferenceId?: string) {
    setBusy(true)
    setError('')
    try {
      const response = await fetch(
        preferenceId ? `/api/memory/preferences/${encodeURIComponent(preferenceId)}` : '/api/memory/preferences',
        { method: 'DELETE' },
      )
      setState(await readMemoryState(response))
    } catch (reason) {
      setError(String(reason))
    } finally {
      setBusy(false)
    }
  }

  return <section className="memory-settings">
    <div className="memory-settings__heading">
      <div>
        <span className="eyebrow">Local personalization / Memory</span>
        <h1>Preference memory</h1>
        <p>Remember a small set of reusable response preferences on this PC.</p>
      </div>
    </div>
    {error && <div className="research-settings__error" role="alert">{error}</div>}
    {!state ? <p>Loading local memory…</p> : <>
      <div className="research-settings__disclosure">
        <Sparkles size={17} />
        <div>
          <strong>Local and minimized</strong>
          <p>Only allowlisted style preferences, such as concise replies or a preferred code-example language, are stored in the local app database. Requests, conversation text, secrets, and personal details are not saved as memories.</p>
          <p>Saved preferences may be included in local model prompts as optional style guidance. They never change task scope, permissions, or safety behavior.</p>
        </div>
      </div>
      <button
        className={`research-provider-card${state.enabled ? ' research-provider-card--selected' : ' research-provider-card--disable'}`}
        disabled={busy}
        aria-pressed={state.enabled}
        onClick={() => void update(!state.enabled)}
      >
        <Sparkles size={18} />
        <span><strong>Automatic preference memory</strong><small>Detect only explicit preferences from your latest request. You can review or remove every saved item below.</small></span>
        <b>{state.enabled ? 'Enabled' : 'Disabled'}</b>
      </button>
      <div className="memory-settings__list-heading">
        <div><h2>Saved preferences</h2><span>{state.preferences.length} stored</span></div>
        <button className="memory-settings__clear" disabled={busy || state.preferences.length === 0} onClick={() => void remove()}>
          <Trash2 size={14} /> Clear all
        </button>
      </div>
      {state.preferences.length === 0
        ? <p className="research-settings__note">No preferences saved. Memory stores only supported, reusable style choices; it does not retain your requests.</p>
        : <ul className="memory-settings__list">
          {state.preferences.map((preference) => <li key={preference.id}>
            <div><span>{preference.category.replace(/_/g, ' ')}</span><strong>{preference.preference}</strong></div>
            <button aria-label={`Remove ${preference.preference}`} disabled={busy} onClick={() => void remove(preference.id)}>
              <Trash2 size={15} />
            </button>
          </li>)}
        </ul>}
    </>}
  </section>
}
