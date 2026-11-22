// Workshop → Memory: style preferences PockPock keeps between tasks, on this PC only.
import { useEffect, useState } from 'react'
import { Brain, Trash2 } from 'lucide-react'
import { Empty } from '../components/ui'
import { ErrorNote, Loading, PageFrame, Toggle } from '../components/page'
import { getJson, sendJson } from '../lib/api'

type MemoryState = { enabled: boolean; preferences: Array<{ id: string; category: string; preference: string; updated_at: string }> }

export function MemoryPage() {
  const [memory, setMemory] = useState<MemoryState | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const run = async (task: () => Promise<MemoryState>) => {
    setBusy(true); setError('')
    try { setMemory(await task()) } catch (memoryError) { setError(memoryError instanceof Error ? memoryError.message : 'Memory is unavailable.') } finally { setBusy(false) }
  }
  const load = () => void run(() => getJson<MemoryState>('/api/memory/preferences'))
  useEffect(load, [])
  const forgetAll = () => { if (window.confirm('Forget all saved preferences?')) void run(() => sendJson<MemoryState>('/api/memory/preferences', undefined, 'DELETE')) }
  return (
    <PageFrame eyebrow="Workshop · Knowledge" title="Memory" intro="Preferences PockPock keeps between tasks, such as how you like answers. They stay on this PC; the requests themselves are not stored."
      actions={memory?.preferences.length ? <button type="button" className="button" disabled={busy} onClick={forgetAll}><Trash2 size={13} /> Forget all</button> : undefined}>
      <ErrorNote message={error} onRetry={load} />
      {!memory && !error && <Loading>Loading…</Loading>}
      {memory && (
        <>
          <div className="card setting-card">
            <Brain size={16} aria-hidden="true" />
            <div className="row__text"><strong>Remember preferences</strong><span>PockPock saves what you ask it to remember, such as how you like answers.</span></div>
            <Toggle checked={memory.enabled} busy={busy} label="Remember preferences" onChange={(enabled) => void run(() => sendJson<MemoryState>('/api/memory/preferences/settings', { enabled }, 'PUT'))} />
          </div>
          <h2 className="list-title">Saved preferences <small>{memory.preferences.length}</small></h2>
          {!memory.preferences.length ? <Empty icon={<Brain size={20} />} title="Nothing saved yet"><p>Say “remember that I prefer short answers” in any task.</p></Empty> : (
            <ul className="rows">
              {memory.preferences.map((item) => (
                <li key={item.id} className="row">
                  <div className="row__text"><strong>{item.preference}</strong><span>{[item.category, item.updated_at ? `saved ${new Date(item.updated_at).toLocaleDateString()}` : ''].filter(Boolean).join(' · ')}</span></div>
                  <button type="button" className="button button--small" aria-label={`Forget ${item.preference}`} disabled={busy} onClick={() => void run(() => sendJson<MemoryState>(`/api/memory/preferences/${encodeURIComponent(item.id)}`, undefined, 'DELETE'))}><Trash2 size={13} /> Remove</button>
                </li>
              ))}
            </ul>
          )}
        </>
      )}
    </PageFrame>
  )
}
