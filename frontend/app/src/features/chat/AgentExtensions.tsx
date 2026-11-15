import { useId, useState } from 'react'
import type { FormEvent } from 'react'
import { Check, RefreshCw, Shield, X } from 'lucide-react'

type SkillOption = {
  slug: string
  name: string
  description: string
  path: string
  files: number
  size: number
  has_scripts: boolean
  installed: boolean
  conflict: boolean
}

type McpOption = {
  name: string
  transport: 'stdio' | 'streamable-http' | 'sse'
  command: string
  args: string[]
  env_keys: string[]
  url: string
  origin: string
  launcher_available: boolean
  installed: boolean
}

export type ExtensionProposal = {
  id: string
  kind: 'skills' | 'mcp'
  source: string
  commit: string
  also: '' | 'skills' | 'mcp'
  skills?: SkillOption[]
  mcp?: McpOption
}

type InstallResult = {
  kind: 'skills' | 'mcp'
  installed?: { slug: string; name: string }[]
  name?: string
  verified?: boolean
  tools?: { name: string; description: string }[]
}

const EXPLICIT_REQUEST = /\b(install|add|connect|set ?up|use|enable)\b[^\n]*\b(skills?|mcp)\b|\b(skills?|mcp)\b[^\n]*\b(install|add|connect|set ?up|use|enable)\b/i

/**
 * A message that is only a link, or a short request to install or connect one, is treated as an
 * extension request. `explicit` is false for a bare GitHub link, which may be meant for the agent.
 */
export function extensionLinkFromMessage(text: string): { url: string; explicit: boolean } | null {
  const trimmed = text.trim()
  if (trimmed.length > 400) return null
  const links = trimmed.match(/https?:\/\/[^\s<>"']+/g)
  if (links?.length !== 1) return null
  const url = links[0].replace(/[.,;:!?)\]]+$/, '')
  const rest = trimmed.replace(links[0], ' ').trim()
  if (!rest) return /^https:\/\/(www\.)?github\.com\/[^/]+\/[^/]+/i.test(url) ? { url, explicit: false } : null
  return EXPLICIT_REQUEST.test(rest) && rest.length <= 80 ? { url, explicit: true } : null
}

export async function postExtension<T = unknown>(path: string, body: unknown): Promise<T> {
  const response = await fetch(path, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) })
  const result = await response.json().catch(() => ({})) as T & { detail?: unknown }
  if (!response.ok) {
    throw Object.assign(new Error(typeof result.detail === 'string' ? result.detail : `The request failed (${response.status}).`), { status: response.status })
  }
  return result
}

/** Ask the server what a link would install. Nothing is installed or run by this call. */
export function inspectExtensionLink(url: string, prefer?: 'skills' | 'mcp') {
  return postExtension<ExtensionProposal>('/api/extensions/inspect', { url, prefer })
}

function formatSize(bytes: number) {
  return bytes < 1024 * 1024 ? `${Math.max(1, Math.round(bytes / 1024))} KB` : `${(bytes / 1024 / 1024).toFixed(1)} MB`
}

export function ExtensionProposalCard({ proposal, onClose, onSwitchKind }: {
  proposal: ExtensionProposal
  onClose: () => void
  onSwitchKind: (kind: 'skills' | 'mcp') => void
}) {
  const fieldId = useId()
  const skills = proposal.skills ?? []
  const mcp = proposal.mcp
  const [selected, setSelected] = useState<string[]>(() => {
    const allowed = skills.filter((skill) => !skill.conflict)
    return allowed.length <= 3 ? allowed.map((skill) => skill.slug) : []
  })
  const [argsText, setArgsText] = useState(() => (mcp?.args ?? []).join('\n'))
  const [env, setEnv] = useState<Record<string, string>>({})
  const [authorization, setAuthorization] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [result, setResult] = useState<InstallResult | null>(null)

  const cancel = () => {
    void postExtension('/api/extensions/cancel', { proposal_id: proposal.id }).catch(() => undefined)
    onClose()
  }

  const install = async (event: FormEvent) => {
    event.preventDefault()
    setBusy(true)
    setError('')
    try {
      const body = proposal.kind === 'skills'
        ? { proposal_id: proposal.id, skills: selected }
        : mcp?.transport === 'stdio'
          ? { proposal_id: proposal.id, args: argsText.split('\n').map((line) => line.trim()).filter(Boolean), env }
          : { proposal_id: proposal.id, authorization: authorization || undefined }
      setResult(await postExtension<InstallResult>('/api/extensions/install', body))
    } catch (installError) {
      setError(installError instanceof Error ? installError.message : 'The install failed.')
    } finally {
      setBusy(false)
    }
  }

  if (result) {
    const tools = result.tools ?? []
    return (
      <section className="chat-route-confirm ext-card" aria-live="polite">
        <div className="chat-route-confirm__head"><Check size={14} /><strong>{result.kind === 'skills' ? 'Skill installed · OpenClaw' : 'MCP server connected · OpenClaw'}</strong></div>
        {result.kind === 'skills'
          ? <p>Installed {result.installed?.map((skill) => skill.name).join(', ')}. The OpenClaw agent can use {result.installed?.length === 1 ? 'it' : 'them'} from the next message.</p>
          : result.verified
            ? <p><strong>{result.name}</strong> answered with {tools.length} tool{tools.length === 1 ? '' : 's'}{tools.length ? `: ${tools.slice(0, 8).map((tool) => tool.name).join(', ')}${tools.length > 8 ? ', …' : ''}` : ''}. The OpenClaw agent can use {tools.length === 1 ? 'it' : 'them'} from the next message.</p>
            : <p><strong>{result.name}</strong> was saved without a test connection, because this older connection type cannot be checked here. Ask the agent to use it to confirm it works.</p>}
        <div className="chat-route-confirm__actions"><button type="button" onClick={onClose}>Done</button></div>
      </section>
    )
  }

  const blocked = proposal.kind === 'skills' ? selected.length === 0 : mcp?.transport === 'stdio' && !mcp.launcher_available
  return (
    <form className="chat-route-confirm ext-card" aria-live="polite" onSubmit={(event) => void install(event)}>
      <div className="chat-route-confirm__head">
        <Shield size={14} />
        <strong>{proposal.kind === 'skills' ? 'Approval required · Install skill' : 'Approval required · Connect MCP server'}</strong>
      </div>
      <p className="ext-card__source">From <span>{proposal.source}</span>{proposal.commit ? <> at commit <code>{proposal.commit.slice(0, 7)}</code></> : null}</p>

      {proposal.kind === 'skills' ? (
        <>
          <p>A skill is a set of instructions the OpenClaw agent follows, sometimes with scripts it can run. Nothing is installed until you approve.</p>
          <ul className="ext-card__list">
            {skills.map((skill) => (
              <li key={skill.slug}>
                <label className={skill.conflict ? 'is-disabled' : ''}>
                  <input
                    type="checkbox"
                    checked={selected.includes(skill.slug)}
                    disabled={skill.conflict || busy}
                    onChange={(event) => setSelected((previous) => event.target.checked ? [...previous, skill.slug] : previous.filter((slug) => slug !== skill.slug))}
                  />
                  <span>
                    <strong>{skill.name}</strong>
                    <small>{skill.files} file{skill.files === 1 ? '' : 's'} · {formatSize(skill.size)}{skill.has_scripts ? ' · includes scripts' : ''}{skill.installed ? ' · installed, will be replaced' : ''}{skill.conflict ? ' · a skill with this name already exists in OpenClaw' : ''}</small>
                    <em>{skill.description}</em>
                  </span>
                </label>
              </li>
            ))}
          </ul>
        </>
      ) : mcp?.transport === 'stdio' ? (
        <>
          <p>Connecting starts this program on your PC with your account's access, first to list its tools and then whenever the OpenClaw agent uses them. The command comes from {mcp.origin}.</p>
          <blockquote>{[mcp.command, ...argsText.split('\n').map((line) => line.trim()).filter(Boolean)].join(' ')}</blockquote>
          {!mcp.launcher_available && <p className="ext-card__warning"><code>{mcp.command}</code> is not installed on this PC. Install it, then paste the link again.</p>}
          <label className="ext-card__field" htmlFor={`${fieldId}-args`}>Arguments, one per line<small>Replace placeholders such as folder paths before connecting.</small></label>
          <textarea id={`${fieldId}-args`} rows={Math.min(6, Math.max(2, argsText.split('\n').length))} value={argsText} onChange={(event) => setArgsText(event.target.value)} disabled={busy} spellCheck={false} />
          {mcp.env_keys.map((key) => (
            <div key={key}>
              <label className="ext-card__field" htmlFor={`${fieldId}-${key}`}>{key}<small>Saved in OpenClaw's config on this PC. Leave empty to skip.</small></label>
              <input id={`${fieldId}-${key}`} type="password" autoComplete="off" value={env[key] ?? ''} onChange={(event) => setEnv((previous) => ({ ...previous, [key]: event.target.value }))} disabled={busy} />
            </div>
          ))}
        </>
      ) : (
        <>
          <p>Connecting lets the OpenClaw agent call tools on this remote server, which will receive whatever the agent sends it.</p>
          <blockquote>{mcp?.url}</blockquote>
          <label className="ext-card__field" htmlFor={`${fieldId}-auth`}>Authorization header (optional)<small>For servers that need a key, for example “Bearer abc123”. Saved in OpenClaw's config on this PC.</small></label>
          <input id={`${fieldId}-auth`} type="password" autoComplete="off" value={authorization} onChange={(event) => setAuthorization(event.target.value)} disabled={busy} />
        </>
      )}

      {proposal.also && <button type="button" className="ext-card__switch" disabled={busy} onClick={() => onSwitchKind(proposal.also as 'skills' | 'mcp')}>This repository also has {proposal.also === 'skills' ? 'skills' : 'an MCP server'}. Show {proposal.also === 'skills' ? 'those' : 'that'} instead</button>}
      {error && <p className="ext-card__warning" role="alert">{error}</p>}
      <div className="chat-route-confirm__actions">
        <button type="submit" disabled={busy || blocked}>
          {busy ? <RefreshCw size={12} className="spin" /> : <Check size={12} />}
          {busy ? (proposal.kind === 'skills' ? 'Installing…' : 'Connecting… this can take a minute') : proposal.kind === 'skills' ? `Install ${selected.length || ''} skill${selected.length === 1 ? '' : 's'}`.replace('  ', ' ') : 'Connect'}
        </button>
        <button type="button" onClick={cancel} disabled={busy}><X size={12} /> Cancel</button>
      </div>
    </form>
  )
}

