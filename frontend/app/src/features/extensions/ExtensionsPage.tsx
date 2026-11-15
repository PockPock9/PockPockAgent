import { useEffect, useState } from 'react'
import { Plug, Puzzle, RefreshCw, Trash2 } from 'lucide-react'
import { ExtensionProposalCard, inspectExtensionLink, postExtension } from '../chat/AgentExtensions'
import type { ExtensionProposal } from '../chat/AgentExtensions'

type InstalledSkill = { slug: string; key?: string; name: string; description: string; source: string; missing: boolean; enabled: boolean }
type BuiltinSkill = { key: string; name: string; description: string; enabled: boolean; ready: boolean; needs: string[] }
type McpServer = { name: string; transport: string; target: string; source: string; managed: boolean; enabled: boolean }
type ExtensionList = {
  skills: InstalledSkill[]
  builtin_skills: BuiltinSkill[]
  mcp: McpServer[]
  openclaw_ready: boolean
  detail: string
}

function Switch({ checked, busy, label, onChange }: { checked: boolean; busy: boolean; label: string; onChange: (next: boolean) => void }) {
  return (
    <button type="button" role="switch" aria-checked={checked} aria-label={label} className="ext-switch" disabled={busy} onClick={() => onChange(!checked)}>
      <span aria-hidden="true" />
    </button>
  )
}

/**
 * One page per kind, so skills and MCP servers are managed separately. Both act on the OpenClaw
 * engine; `visible` reloads the list whenever the page is opened.
 */
export function ExtensionsPage({ kind, visible }: { kind: 'skills' | 'mcp'; visible: boolean }) {
  const [list, setList] = useState<ExtensionList | null>(null)
  const [error, setError] = useState('')
  const [link, setLink] = useState('')
  const [previewing, setPreviewing] = useState(false)
  const [proposal, setProposal] = useState<ExtensionProposal | null>(null)
  const [pending, setPending] = useState('')
  const [showUnavailable, setShowUnavailable] = useState(false)
  const isSkills = kind === 'skills'

  const load = async () => {
    try {
      const response = await fetch('/api/extensions')
      const result = await response.json() as ExtensionList & { detail?: string }
      if (!response.ok) throw new Error(typeof result.detail === 'string' ? result.detail : 'Could not load the list.')
      setList(result)
      setError('')
    } catch (loadError) {
      setError(loadError instanceof Error ? loadError.message : 'Could not load the list.')
    }
  }
  useEffect(() => { if (visible) void load() }, [visible])

  // OpenClaw notices a newly installed skill after a short delay; until then it has no switch.
  // Recheck a few times so the switch appears without a manual reload.
  const settling = Boolean(visible && list?.openclaw_ready && list.skills.some((skill) => !skill.key && !skill.missing))
  const [settleTries, setSettleTries] = useState(0)
  useEffect(() => {
    if (!settling) { setSettleTries(0); return }
    if (settleTries >= 12) return
    const timer = window.setTimeout(() => { setSettleTries((tries) => tries + 1); void load() }, 5000)
    return () => window.clearTimeout(timer)
  }, [settling, settleTries])

  const preview = async (url: string, prefer: 'skills' | 'mcp' = kind) => {
    if (!url.trim() || previewing) return
    setPreviewing(true)
    setError('')
    try {
      setProposal(await inspectExtensionLink(url.trim(), prefer))
      setLink('')
    } catch (previewError) {
      setError(previewError instanceof Error ? previewError.message : 'Could not read that link.')
    } finally {
      setPreviewing(false)
    }
  }

  const change = async (id: string, path: string, body: unknown, failure: string) => {
    setPending(id)
    setError('')
    try {
      await postExtension(path, body)
      await load()
    } catch (changeError) {
      setError(changeError instanceof Error ? changeError.message : failure)
    } finally {
      setPending('')
    }
  }
  const toggle = (itemKind: 'skill' | 'mcp', name: string, enabled: boolean) => change(`${itemKind}:${name}`, '/api/extensions/toggle', { kind: itemKind, name, enabled }, 'Could not change that setting.')
  const remove = (itemKind: 'skill' | 'mcp', name: string, label: string) => {
    if (!window.confirm(itemKind === 'skill' ? `Remove the skill “${label}” from OpenClaw? Its files will be deleted.` : `Disconnect the MCP server “${label}” from OpenClaw?`)) return
    void change(`${itemKind}:${name}`, '/api/extensions/remove', { kind: itemKind, name }, 'Could not remove it.')
  }

  const ready = list?.builtin_skills.filter((skill) => skill.ready) ?? []
  const unavailable = list?.builtin_skills.filter((skill) => !skill.ready) ?? []
  const inputId = `ext-link-${kind}`

  return (
    <section className="memory-settings ext-page">
      <div className="memory-settings__heading">
        <span className="eyebrow">Agent / OpenClaw engine / {isSkills ? 'Skills' : 'MCP servers'}</span>
        <h1>{isSkills ? 'Skills' : 'MCP servers'}</h1>
        <p>{isSkills
          ? 'Skills are instructions the OpenClaw agent follows for a kind of task, sometimes with scripts. Add one from a GitHub link, and switch any skill off without removing it.'
          : 'MCP servers give the OpenClaw agent extra tools. Add one from a GitHub link or a server address. Each tool call still follows the permission you choose in the chat.'}</p>
      </div>

      <form className="ext-page__add" onSubmit={(event) => { event.preventDefault(); void preview(link) }}>
        <label htmlFor={inputId}>{isSkills ? 'Add a skill from a GitHub link' : 'Add an MCP server from a link'}</label>
        <div>
          <input id={inputId} type="url" inputMode="url" placeholder={isSkills ? 'https://github.com/owner/repo/tree/main/skills/name' : 'https://github.com/owner/repo or https://server.example/mcp'} value={link} onChange={(event) => setLink(event.target.value)} autoComplete="off" spellCheck={false} />
          <button type="submit" disabled={!link.trim() || previewing}>{previewing ? <RefreshCw size={13} className="spin" /> : null}{previewing ? 'Reading…' : 'Preview'}</button>
        </div>
        <small>Nothing is installed until you approve the preview. Only add {isSkills ? 'skills' : 'servers'} from sources you trust.</small>
      </form>

      {error && <div className="research-settings__error" role="alert">{error}</div>}
      {proposal && (
        <ExtensionProposalCard
          key={proposal.id}
          proposal={proposal}
          onClose={() => { setProposal(null); void load() }}
          onSwitchKind={(next) => void preview(proposal.source, next)}
        />
      )}
      {proposal && proposal.kind !== kind && <p className="research-settings__note">That link is {proposal.kind === 'mcp' ? 'an MCP server' : 'a skill'}, so it will appear on the {proposal.kind === 'mcp' ? 'MCP servers' : 'Skills'} page.</p>}

      {!list && !error && <p className="research-settings__note"><RefreshCw size={13} className="spin" /> Loading…</p>}
      {list && !list.openclaw_ready && <div className="research-settings__error" role="alert">{list.detail || 'OpenClaw is not reachable.'} {isSkills ? 'Skills cannot be switched on or off until it is running.' : 'MCP servers cannot be listed until it is running.'}</div>}

      {list && isSkills && (
        <>
          <div className="memory-settings__list-heading"><div><h2>Added from links</h2><span>{list.skills.length}</span></div></div>
          {list.skills.length === 0
            ? <p className="research-settings__note">No skills added yet. Paste a GitHub link above, or paste it into an Agent chat.</p>
            : <ul className="memory-settings__list ext-page__list">
              {list.skills.map((skill) => (
                <li key={skill.slug}>
                  <Puzzle size={16} aria-hidden="true" />
                  <div><strong>{skill.name}</strong><span>{skill.missing ? 'Files are missing. Remove it and add it again.' : skill.source.replace('https://github.com/', '')}</span>{skill.description && <p>{skill.description}</p>}</div>
                  {!skill.key && !skill.missing && <em className="ext-page__settling">{settleTries >= 12 ? 'Not picked up by OpenClaw yet' : 'Getting ready…'}</em>}
                  {skill.key && <Switch checked={skill.enabled} busy={pending === `skill:${skill.key}`} label={`Use skill ${skill.name}`} onChange={(next) => void toggle('skill', skill.key!, next)} />}
                  <button type="button" onClick={() => remove('skill', skill.slug, skill.name)} disabled={pending === `skill:${skill.slug}`} aria-label={`Remove skill ${skill.name}`}><Trash2 size={14} /></button>
                </li>
              ))}
            </ul>}

          <div className="memory-settings__list-heading"><div><h2>Built into OpenClaw</h2><span>{ready.length} ready</span></div></div>
          {list.openclaw_ready && ready.length === 0 && <p className="research-settings__note">No built-in skills are ready.</p>}
          <ul className="memory-settings__list ext-page__list">
            {ready.map((skill) => (
              <li key={skill.key}>
                <Puzzle size={16} aria-hidden="true" />
                <div><strong>{skill.name}</strong>{skill.description && <p>{skill.description}</p>}</div>
                <Switch checked={skill.enabled} busy={pending === `skill:${skill.key}`} label={`Use skill ${skill.name}`} onChange={(next) => void toggle('skill', skill.key, next)} />
              </li>
            ))}
          </ul>
          {unavailable.length > 0 && (
            <>
              <button type="button" className="ext-page__more" aria-expanded={showUnavailable} onClick={() => setShowUnavailable((shown) => !shown)}>{showUnavailable ? 'Hide' : 'Show'} {unavailable.length} skills that need extra software</button>
              {showUnavailable && <ul className="memory-settings__list ext-page__list">
                {unavailable.map((skill) => (
                  <li key={skill.key} className="is-muted">
                    <Puzzle size={16} aria-hidden="true" />
                    <div><strong>{skill.name}</strong><span>Needs: {skill.needs.join(', ') || 'setup in OpenClaw'}</span>{skill.description && <p>{skill.description}</p>}</div>
                  </li>
                ))}
              </ul>}
            </>
          )}
        </>
      )}

      {list && !isSkills && list.openclaw_ready && (
        <>
          <div className="memory-settings__list-heading"><div><h2>Connected servers</h2><span>{list.mcp.length}</span></div></div>
          {list.mcp.length === 0
            ? <p className="research-settings__note">No MCP servers connected yet. Paste a link above, or paste it into an Agent chat.</p>
            : <ul className="memory-settings__list ext-page__list">
              {list.mcp.map((server) => (
                <li key={server.name}>
                  <Plug size={16} aria-hidden="true" />
                  <div><strong>{server.name}</strong><span>{server.managed ? (server.source || 'Added from a link') : 'Added outside PockPock'}</span><p className="ext-page__target">{server.target}</p></div>
                  <Switch checked={server.enabled} busy={pending === `mcp:${server.name}`} label={`Use MCP server ${server.name}`} onChange={(next) => void toggle('mcp', server.name, next)} />
                  {server.managed && <button type="button" onClick={() => remove('mcp', server.name, server.name)} disabled={pending === `mcp:${server.name}`} aria-label={`Disconnect MCP server ${server.name}`}><Trash2 size={14} /></button>}
                </li>
              ))}
            </ul>}
        </>
      )}
    </section>
  )
}
