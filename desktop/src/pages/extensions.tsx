// Shared by the Skills and MCP servers pages: the extension list from /api/extensions, the add-from-link
// box, and the inspection proposal shown before anything is installed.
import { useCallback, useEffect, useState } from 'react'
import { LoaderCircle } from 'lucide-react'
import { inspectLink } from '../components/ExtensionCard'
import type { Proposal } from '../components/ExtensionCard'
import { getJson, sendJson } from '../lib/api'

export type ExtensionList = {
  skills: Array<{ slug: string; key?: string; name: string; description: string; source: string; missing: boolean; enabled: boolean }>
  builtin_skills: Array<{ key: string; name: string; description: string; enabled: boolean; ready: boolean; needs: string[] }>
  mcp: Array<{
    name: string; transport: string; target: string; source: string; managed: boolean; enabled: boolean
    /** Runs in Local MCP; state: running, stopped (starts on first use), error, off, or unavailable (Local MCP is not running). */
    local?: boolean; state?: string; state_detail?: string; tools?: number | null
  }>
  local_mcp?: { running: boolean; detail: string }
  openclaw_ready: boolean
  detail: string
}

export function useExtensions(onChanged: () => void) {
  const [list, setList] = useState<ExtensionList | null>(null)
  const [error, setError] = useState('')
  const [pending, setPending] = useState('')
  const load = useCallback(async () => {
    try { setList(await getJson<ExtensionList>('/api/extensions')); setError('') } catch (loadError) { setError(loadError instanceof Error ? loadError.message : 'Could not load the list.') }
  }, [])
  useEffect(() => { void load() }, [load])
  const act = async (id: string, path: string, body: unknown) => {
    setPending(id)
    setError('')
    try { await sendJson(path, body); await load(); onChanged() } catch (actError) { setError(actError instanceof Error ? actError.message : 'That did not work.') } finally { setPending('') }
  }
  return { list, error, setError, pending, load, act }
}

export function AddLink({ kind, onPreview, busy }: { kind: 'skills' | 'mcp'; onPreview: (url: string) => void; busy: boolean }) {
  const [link, setLink] = useState('')
  return (
    <form className="add-link" onSubmit={(event) => { event.preventDefault(); if (link.trim()) { onPreview(link.trim()); setLink('') } }}>
      <label htmlFor={`add-${kind}`}>{kind === 'skills' ? 'Add a skill from a GitHub link' : 'Paste a GitHub link, a server address, or a command that starts one on this PC'}</label>
      <div>
        <input id={`add-${kind}`} className="input" type={kind === 'skills' ? 'url' : 'text'} placeholder={kind === 'skills' ? 'https://github.com/owner/repo/tree/main/skills/name' : 'https://github.com/owner/repo  ·  https://server.example/mcp  ·  python3 server.py'} value={link} onChange={(event) => setLink(event.target.value)} spellCheck={false} />
        <button type="submit" className="button button--primary" disabled={!link.trim() || busy}>{busy && <LoaderCircle size={13} className="spin" />}{busy ? 'Reading…' : kind === 'skills' ? 'Preview' : 'Add'}</button>
      </div>
      <small>You will see exactly what it installs and approve it first. Only add {kind === 'skills' ? 'skills' : 'servers'} from sources you trust.</small>
    </form>
  )
}

export function useProposal(kind: 'skills' | 'mcp', setError: (message: string) => void) {
  const [proposal, setProposal] = useState<Proposal | null>(null)
  const [busy, setBusy] = useState(false)
  /** Shows the preview card. `inline`: the caller shows a failure itself (search results); returns it. */
  const preview = async (url: string, prefer: 'skills' | 'mcp' = kind, inline = false): Promise<string> => {
    setBusy(true)
    setError('')
    try {
      setProposal(await inspectLink(url, prefer))
      // A preview started from search results below: bring the card into view.
      window.requestAnimationFrame(() => document.querySelector('.card--extension')?.scrollIntoView({ behavior: 'smooth', block: 'start' }))
      return ''
    } catch (previewError) {
      const message = previewError instanceof Error ? previewError.message : 'Could not read that link.'
      if (!inline) setError(message)
      return message
    } finally { setBusy(false) }
  }
  return { proposal, setProposal, busy, preview }
}
