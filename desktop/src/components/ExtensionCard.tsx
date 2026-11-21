// Preview and approve a skill or MCP server found at a pasted link. Nothing is installed until
// the user presses Install or Connect.
import { useId, useState } from 'react'
import type { FormEvent } from 'react'
import { Check, LoaderCircle, Shield, X } from 'lucide-react'
import { formatBytes, sendJson } from '../lib/api'

export type Proposal = {
  id: string
  kind: 'skills' | 'mcp'
  source: string
  commit: string
  also: '' | 'skills' | 'mcp'
  /** Folders of a repository that each document their own MCP server. */
  mcp_folders?: Array<{ name: string; path: string; url: string }>
  skills?: Array<{ slug: string; name: string; description: string; files: number; size: number; has_scripts: boolean; installed: boolean; conflict: boolean; adds_header?: boolean }>
  mcp?: { name: string; transport: string; command: string; args: string[]; env_keys: string[]; url: string; origin: string; launcher_available: boolean; installed: boolean; args_hint?: string }
}

type Result = { kind: 'skills' | 'mcp'; installed?: Array<{ name: string }>; name?: string; verified?: boolean; tools?: Array<{ name: string }> }

const REQUEST = /\b(install|add|connect|set ?up|use|enable)\b[^\n]*\b(skills?|mcp)\b|\b(skills?|mcp)\b[^\n]*\b(install|add|connect|set ?up|use|enable)\b/i

/** A message that is only a GitHub link, or a short "install skill <link>" request. */
export function linkFromMessage(message: string): { url: string; explicit: boolean } | null {
  const trimmed = message.trim()
  if (trimmed.length > 400) return null
  const links = trimmed.match(/https?:\/\/[^\s<>"']+/g)
  if (links?.length !== 1) return null
  const url = links[0].replace(/[.,;:!?)\]]+$/, '')
  const rest = trimmed.replace(links[0], ' ').trim()
  if (!rest) return /^https:\/\/(www\.)?github\.com\/[^/]+\/[^/]+/i.test(url) ? { url, explicit: false } : null
  return REQUEST.test(rest) && rest.length <= 80 ? { url, explicit: true } : null
}

export function inspectLink(url: string, prefer?: 'skills' | 'mcp') {
  return sendJson<Proposal>('/api/extensions/inspect', { url, prefer })
}

export function ExtensionCard({ proposal, onClose, onSwitch, onOpen, onInstalled }: {
  proposal: Proposal
  onClose: () => void
  onSwitch: (kind: 'skills' | 'mcp') => void
  /** Preview another link, such as one server folder of a repository that holds several. */
  onOpen?: (url: string) => void
  onInstalled?: () => void
}) {
  const folders = proposal.mcp_folders ?? []
  const id = useId()
  const skills = proposal.skills ?? []
  const mcp = proposal.mcp
  const [selected, setSelected] = useState(() => skills.filter((skill) => !skill.conflict).length <= 3 ? skills.filter((skill) => !skill.conflict).map((skill) => skill.slug) : [])
  const [args, setArgs] = useState((mcp?.args ?? []).join('\n'))
  const [env, setEnv] = useState<Record<string, string>>({})
  const [authorization, setAuthorization] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [result, setResult] = useState<Result | null>(null)

  const cancel = () => { void sendJson('/api/extensions/cancel', { proposal_id: proposal.id }).catch(() => undefined); onClose() }
  const submit = async (event: FormEvent) => {
    event.preventDefault()
    setBusy(true)
    setError('')
    try {
      const body = proposal.kind === 'skills'
        ? { proposal_id: proposal.id, skills: selected }
        : mcp?.transport === 'stdio'
          ? { proposal_id: proposal.id, args: args.split('\n').map((line) => line.trim()).filter(Boolean), env }
          : { proposal_id: proposal.id, authorization: authorization || undefined }
      setResult(await sendJson<Result>('/api/extensions/install', body))
      onInstalled?.()
    } catch (installError) {
      setError(installError instanceof Error ? installError.message : 'The install failed.')
    } finally {
      setBusy(false)
    }
  }

  if (result) {
    const tools = result.tools ?? []
    return (
      <section className="card card--extension" aria-live="polite">
        <header><Check size={14} /><strong>{result.kind === 'skills' ? 'Skill installed' : 'MCP server connected'}</strong><span>OpenClaw</span></header>
        <p>{result.kind === 'skills'
          ? `Installed ${result.installed?.map((skill) => skill.name).join(', ')}. The OpenClaw agent can use it from the next message.`
          : result.verified
            ? `${result.name} answered with ${tools.length} tool${tools.length === 1 ? '' : 's'}${tools.length ? `: ${tools.slice(0, 8).map((tool) => tool.name).join(', ')}` : ''}.`
            : `${result.name} was saved without a test connection. Ask the agent to use it to confirm it works.`}</p>
        <div className="card__actions"><button type="button" className="button" onClick={onClose}>Done</button></div>
      </section>
    )
  }

  const blocked = proposal.kind === 'skills' ? selected.length === 0 : mcp?.transport === 'stdio' && !mcp.launcher_available
  return (
    <form className="card card--extension is-pending" onSubmit={(event) => void submit(event)}>
      <header><Shield size={14} /><strong>{proposal.kind === 'skills' ? 'Install skill' : 'Connect MCP server'}</strong><span>Approval needed</span></header>
      <p className="card__source">From <b>{proposal.source}</b>{proposal.commit && <> at <code>{proposal.commit.slice(0, 7)}</code></>}</p>
      {proposal.kind === 'skills' ? (
        <>
          <p>A skill is a set of instructions the OpenClaw agent follows, sometimes with scripts it can run.</p>
          <ul className="choice-list">
            {skills.map((skill) => (
              <li key={skill.slug}>
                <label className={skill.conflict ? 'is-disabled' : ''}>
                  <input type="checkbox" checked={selected.includes(skill.slug)} disabled={skill.conflict || busy} onChange={(event) => setSelected((previous) => event.target.checked ? [...previous, skill.slug] : previous.filter((slug) => slug !== skill.slug))} />
                  <span>
                    <strong>{skill.name}</strong>
                    <small>{skill.files} files · {formatBytes(skill.size)}{skill.has_scripts ? ' · includes scripts' : ''}{skill.installed ? ' · will replace installed copy' : ''}{skill.conflict ? ' · name already used in OpenClaw' : ''}{skill.adds_header ? ' · PockPock adds the name and description OpenClaw needs' : ''}</small>
                    <em>{skill.description}</em>
                  </span>
                </label>
              </li>
            ))}
          </ul>
        </>
      ) : mcp?.transport === 'stdio' ? (
        <>
          <p>Connecting starts this program on your PC with your account's access. {mcp.origin === 'the command you entered' ? 'PockPock tests it first, then saves it.' : `The command comes from ${mcp.origin}.`}</p>
          <code className="card__detail">{[mcp.command, ...args.split('\n').map((line) => line.trim()).filter(Boolean)].join(' ')}</code>
          {!mcp.launcher_available && <p className="card__error">{mcp.command} is not installed on this PC. Install it, then paste it again.</p>}
          <label className="field" htmlFor={`${id}-args`}>Arguments, one per line<small>{mcp.args_hint || 'Replace placeholders such as folder paths.'}</small></label>
          <textarea id={`${id}-args`} className="input" rows={Math.min(6, Math.max(2, args.split('\n').length))} value={args} onChange={(event) => setArgs(event.target.value)} disabled={busy} spellCheck={false} />
          {mcp.env_keys.map((key) => (
            <div key={key}>
              <label className="field" htmlFor={`${id}-${key}`}>{key}<small>Saved in OpenClaw's config on this PC. Leave empty to skip.</small></label>
              <input id={`${id}-${key}`} className="input" type="password" autoComplete="off" value={env[key] ?? ''} onChange={(event) => setEnv((previous) => ({ ...previous, [key]: event.target.value }))} disabled={busy} />
            </div>
          ))}
        </>
      ) : (
        <>
          <p>The OpenClaw agent will be able to call tools on this server, which receives whatever the agent sends it.</p>
          <code className="card__detail">{mcp?.url}</code>
          <label className="field" htmlFor={`${id}-auth`}>Authorization header (optional)<small>For example “Bearer abc123”.</small></label>
          <input id={`${id}-auth`} className="input" type="password" autoComplete="off" value={authorization} onChange={(event) => setAuthorization(event.target.value)} disabled={busy} />
        </>
      )}
      {proposal.also && <button type="button" className="link-button" disabled={busy} onClick={() => onSwitch(proposal.also as 'skills' | 'mcp')}>This repository also has {proposal.also === 'skills' ? 'skills' : 'an MCP server'}. Show {proposal.also === 'skills' ? 'those' : 'that'} instead</button>}
      {folders.length > 0 && onOpen && (
        <div className="card__folders">
          <p>This repository also has {folders.length} MCP server{folders.length === 1 ? '' : 's'}, each in its own folder:</p>
          <ul>
            {folders.slice(0, 12).map((folder) => (
              <li key={folder.path}><button type="button" className="link-button" disabled={busy} onClick={() => onOpen(folder.url)}>{folder.name}</button> <small>{folder.path}</small></li>
            ))}
          </ul>
        </div>
      )}
      {error && <p className="card__error" role="alert">{error}</p>}
      <div className="card__actions">
        <button type="submit" className="button button--primary" disabled={busy || blocked}>{busy ? <LoaderCircle size={13} className="spin" /> : <Check size={13} />}{busy ? (proposal.kind === 'skills' ? 'Installing…' : 'Connecting… this can take a minute') : proposal.kind === 'skills' ? `Install ${selected.length || ''} skill${selected.length === 1 ? '' : 's'}`.replace('  ', ' ') : 'Connect'}</button>
        <button type="button" className="button" onClick={cancel} disabled={busy}><X size={13} /> Cancel</button>
      </div>
    </form>
  )
}
