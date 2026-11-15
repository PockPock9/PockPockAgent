// Customize pages: Skills, MCP servers, Models, Memory, Settings.
import { useCallback, useEffect, useState } from 'react'
import type { ReactNode } from 'react'
import { Brain, LoaderCircle, Plug, Power, Puzzle, RefreshCw, Server, Trash2 } from 'lucide-react'
import { ExtensionCard, inspectLink } from '../components/ExtensionCard'
import type { Proposal } from '../components/ExtensionCard'
import { Empty } from '../components/ui'
import { formatBytes, getJson, sendJson } from '../lib/api'
import type { Status } from '../lib/status'
import type { AppInfo } from '../lib/types'

function PageFrame({ title, eyebrow, intro, children, actions }: { title: string; eyebrow: string; intro: string; children: ReactNode; actions?: ReactNode }) {
  return (
    <div className="page">
      <div className="page__inner">
        <header className="page__head">
          <div><span className="eyebrow">{eyebrow}</span><h1>{title}</h1><p>{intro}</p></div>
          {actions}
        </header>
        {children}
      </div>
    </div>
  )
}

function Toggle({ checked, busy, label, onChange }: { checked: boolean; busy?: boolean; label: string; onChange: (next: boolean) => void }) {
  return <button type="button" role="switch" aria-checked={checked} aria-label={label} className="switch" disabled={busy} onClick={() => onChange(!checked)}><span /></button>
}

function ErrorNote({ message }: { message: string }) {
  return message ? <div className="banner banner--error" role="alert"><span>{message}</span></div> : null
}

type ExtensionList = {
  skills: Array<{ slug: string; key?: string; name: string; description: string; source: string; missing: boolean; enabled: boolean }>
  builtin_skills: Array<{ key: string; name: string; description: string; enabled: boolean; ready: boolean; needs: string[] }>
  mcp: Array<{ name: string; transport: string; target: string; source: string; managed: boolean; enabled: boolean }>
  openclaw_ready: boolean
  detail: string
}

function useExtensions(onChanged: () => void) {
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

function AddLink({ kind, onPreview, busy }: { kind: 'skills' | 'mcp'; onPreview: (url: string) => void; busy: boolean }) {
  const [link, setLink] = useState('')
  return (
    <form className="add-link" onSubmit={(event) => { event.preventDefault(); if (link.trim()) { onPreview(link.trim()); setLink('') } }}>
      <label htmlFor={`add-${kind}`}>{kind === 'skills' ? 'Add a skill from a GitHub link' : 'Add an MCP server from a GitHub link or server address'}</label>
      <div>
        <input id={`add-${kind}`} className="input" type="url" placeholder={kind === 'skills' ? 'https://github.com/owner/repo/tree/main/skills/name' : 'https://github.com/owner/repo  or  https://server.example/mcp'} value={link} onChange={(event) => setLink(event.target.value)} spellCheck={false} />
        <button type="submit" className="button button--primary" disabled={!link.trim() || busy}>{busy && <LoaderCircle size={13} className="spin" />}{busy ? 'Reading…' : 'Preview'}</button>
      </div>
      <small>You will see exactly what it installs and approve it first. Only add {kind === 'skills' ? 'skills' : 'servers'} from sources you trust.</small>
    </form>
  )
}

function useProposal(kind: 'skills' | 'mcp', setError: (message: string) => void) {
  const [proposal, setProposal] = useState<Proposal | null>(null)
  const [busy, setBusy] = useState(false)
  const preview = async (url: string, prefer: 'skills' | 'mcp' = kind) => {
    setBusy(true)
    setError('')
    try { setProposal(await inspectLink(url, prefer)) } catch (previewError) { setError(previewError instanceof Error ? previewError.message : 'Could not read that link.') } finally { setBusy(false) }
  }
  return { proposal, setProposal, busy, preview }
}

export function SkillsPage({ status }: { status: Status }) {
  const { list, error, setError, pending, load, act } = useExtensions(() => void status.refreshCounts())
  const { proposal, setProposal, busy, preview } = useProposal('skills', setError)
  const [showAll, setShowAll] = useState(false)
  // OpenClaw notices a new skill after a short delay; recheck until it has a switch.
  const settling = Boolean(list?.openclaw_ready && list.skills.some((skill) => !skill.key && !skill.missing))
  useEffect(() => {
    if (!settling) return
    const timer = window.setInterval(() => void load(), 5000)
    return () => window.clearInterval(timer)
  }, [settling, load])
  const ready = list?.builtin_skills.filter((skill) => skill.ready) ?? []
  const unavailable = list?.builtin_skills.filter((skill) => !skill.ready) ?? []
  return (
    <PageFrame eyebrow="Customize · OpenClaw" title="Skills" intro="Instructions the OpenClaw agent follows for a kind of task. Switch one off to stop the agent using it without removing it.">
      <AddLink kind="skills" busy={busy} onPreview={(url) => void preview(url)} />
      {proposal && <ExtensionCard key={proposal.id} proposal={proposal} onClose={() => { setProposal(null); void load(); void status.refreshCounts() }} onSwitch={(next) => void preview(proposal.source, next)} />}
      <ErrorNote message={error} />
      {!list && !error && <p className="note"><LoaderCircle size={13} className="spin" /> Loading skills…</p>}
      {list && !list.openclaw_ready && <ErrorNote message={`${list.detail || 'OpenClaw is not reachable.'} Skills cannot be switched until it is running.`} />}
      {list && (
        <>
          <h2 className="list-title">Added from links <small>{list.skills.length}</small></h2>
          {!list.skills.length ? <p className="note">None yet. Paste a GitHub link above or into a chat.</p> : (
            <ul className="rows">
              {list.skills.map((skill) => (
                <li key={skill.slug} className="row">
                  <Puzzle size={16} className="row__icon" />
                  <div className="row__text"><strong>{skill.name}</strong><span>{skill.missing ? 'Files are missing. Remove it and add it again.' : skill.source.replace('https://github.com/', '')}</span>{skill.description && <p>{skill.description}</p>}</div>
                  {skill.key ? <Toggle checked={skill.enabled} busy={pending === `skill:${skill.key}`} label={`Use skill ${skill.name}`} onChange={(next) => void act(`skill:${skill.key}`, '/api/extensions/toggle', { kind: 'skill', name: skill.key, enabled: next })} />
                    : !skill.missing && <em className="row__hint">Getting ready…</em>}
                  <button type="button" className="icon-button" aria-label={`Remove skill ${skill.name}`} title="Remove" disabled={pending === `remove:${skill.slug}`}
                    onClick={() => { if (window.confirm(`Remove the skill “${skill.name}”? Its files will be deleted.`)) void act(`remove:${skill.slug}`, '/api/extensions/remove', { kind: 'skill', name: skill.slug }) }}><Trash2 size={14} /></button>
                </li>
              ))}
            </ul>
          )}
          <h2 className="list-title">Built into OpenClaw <small>{ready.length} ready</small></h2>
          <ul className="rows">
            {ready.map((skill) => (
              <li key={skill.key} className="row">
                <Puzzle size={16} className="row__icon" />
                <div className="row__text"><strong>{skill.name}</strong>{skill.description && <p>{skill.description}</p>}</div>
                <Toggle checked={skill.enabled} busy={pending === `skill:${skill.key}`} label={`Use skill ${skill.name}`} onChange={(next) => void act(`skill:${skill.key}`, '/api/extensions/toggle', { kind: 'skill', name: skill.key, enabled: next })} />
              </li>
            ))}
          </ul>
          {unavailable.length > 0 && <button type="button" className="link-button" aria-expanded={showAll} onClick={() => setShowAll((value) => !value)}>{showAll ? 'Hide' : 'Show'} {unavailable.length} skills that need extra software</button>}
          {showAll && (
            <ul className="rows rows--muted">
              {unavailable.map((skill) => (
                <li key={skill.key} className="row">
                  <Puzzle size={16} className="row__icon" />
                  <div className="row__text"><strong>{skill.name}</strong><span>Needs {skill.needs.join(', ') || 'setup in OpenClaw'}</span>{skill.description && <p>{skill.description}</p>}</div>
                </li>
              ))}
            </ul>
          )}
        </>
      )}
    </PageFrame>
  )
}

export function McpPage({ status }: { status: Status }) {
  const { list, error, setError, pending, load, act } = useExtensions(() => void status.refreshCounts())
  const { proposal, setProposal, busy, preview } = useProposal('mcp', setError)
  return (
    <PageFrame eyebrow="Customize · OpenClaw" title="MCP servers" intro="Tool servers the OpenClaw agent can call. Every call still follows the permission you pick in the chat.">
      <AddLink kind="mcp" busy={busy} onPreview={(url) => void preview(url)} />
      {proposal && <ExtensionCard key={proposal.id} proposal={proposal} onClose={() => { setProposal(null); void load(); void status.refreshCounts() }} onSwitch={(next) => void preview(proposal.source, next)} />}
      <ErrorNote message={error} />
      {!list && !error && <p className="note"><LoaderCircle size={13} className="spin" /> Loading servers…</p>}
      {list && !list.openclaw_ready && <ErrorNote message={`${list.detail || 'OpenClaw is not reachable.'} Servers cannot be listed until it is running.`} />}
      {list?.openclaw_ready && (
        <>
          <h2 className="list-title">Connected <small>{list.mcp.length}</small></h2>
          {!list.mcp.length ? <Empty icon={<Plug size={20} />} title="No MCP servers yet"><p>Paste a GitHub link to an MCP server, or a server address, above.</p></Empty> : (
            <ul className="rows">
              {list.mcp.map((server) => (
                <li key={server.name} className="row">
                  <Plug size={16} className="row__icon" />
                  <div className="row__text"><strong>{server.name}</strong><span>{server.managed ? server.source || 'Added from a link' : 'Added outside PockPock'}</span><code>{server.target}</code></div>
                  <Toggle checked={server.enabled} busy={pending === `mcp:${server.name}`} label={`Use MCP server ${server.name}`} onChange={(next) => void act(`mcp:${server.name}`, '/api/extensions/toggle', { kind: 'mcp', name: server.name, enabled: next })} />
                  {server.managed && <button type="button" className="icon-button" aria-label={`Disconnect ${server.name}`} title="Disconnect" disabled={pending === `remove:${server.name}`}
                    onClick={() => { if (window.confirm(`Disconnect the MCP server “${server.name}”?`)) void act(`remove:${server.name}`, '/api/extensions/remove', { kind: 'mcp', name: server.name }) }}><Trash2 size={14} /></button>}
                </li>
              ))}
            </ul>
          )}
        </>
      )}
    </PageFrame>
  )
}

export function ModelsPage({ status }: { status: Status }) {
  const [pending, setPending] = useState('')
  const [error, setError] = useState('')
  const models = status.state?.models ?? []
  const toggle = async (name: string, enabled: boolean) => {
    setPending(name)
    setError('')
    try { await sendJson(`/api/models/${encodeURIComponent(name)}`, { enabled }, 'PUT'); await status.refreshState() } catch (toggleError) { setError(toggleError instanceof Error ? toggleError.message : 'Could not change that model.') } finally { setPending('') }
  }
  return (
    <PageFrame eyebrow="Customize · Ollama" title="Models" intro="Local models on this PC. Switched-on models are offered by Smart route and the model pickers. A model loads into memory only when a message uses it.">
      <ErrorNote message={error} />
      {!status.state ? <ErrorNote message="The PockPock backend is not answering, so models cannot be listed." />
        : !status.state.connected ? <ErrorNote message={status.state.error || 'Ollama is not running. Start it in Settings.'} />
          : !models.length ? <Empty icon={<Server size={20} />} title="No models installed"><p>Install one with <code>ollama pull qwen3.5:9b</code> in the terminal.</p></Empty>
            : (
              <ul className="rows">
                {models.map((model) => (
                  <li key={model.name} className="row">
                    <Server size={16} className="row__icon" />
                    <div className="row__text"><strong>{model.name}</strong><span>{formatBytes(model.size)}{model.running ? ' · loaded now' : ''}{typeof model.details?.parameter_size === 'string' ? ` · ${model.details.parameter_size}` : ''}{typeof model.details?.quantization_level === 'string' ? ` · ${model.details.quantization_level}` : ''}</span></div>
                    <Toggle checked={model.enabled} busy={pending === model.name} label={`Use ${model.name}`} onChange={(next) => void toggle(model.name, next)} />
                  </li>
                ))}
              </ul>
            )}
    </PageFrame>
  )
}

type MemoryState = { enabled: boolean; preferences: Array<{ id: string; category: string; preference: string; updated_at: string }> }

export function MemoryPage() {
  const [memory, setMemory] = useState<MemoryState | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const run = async (task: () => Promise<MemoryState>) => {
    setBusy(true)
    setError('')
    try { setMemory(await task()) } catch (memoryError) { setError(memoryError instanceof Error ? memoryError.message : 'Memory is unavailable.') } finally { setBusy(false) }
  }
  useEffect(() => { void run(() => getJson<MemoryState>('/api/memory/preferences')) }, [])
  return (
    <PageFrame eyebrow="Customize" title="Memory" intro="Reusable style preferences PockPock learns from your requests, such as preferred formats. It does not store the requests themselves.">
      <ErrorNote message={error} />
      {!memory && !error && <p className="note"><LoaderCircle size={13} className="spin" /> Loading…</p>}
      {memory && (
        <>
          <div className="row row--setting">
            <Brain size={16} className="row__icon" />
            <div className="row__text"><strong>Remember preferences</strong><span>{memory.enabled ? 'On' : 'Off'}</span></div>
            <Toggle checked={memory.enabled} busy={busy} label="Remember preferences" onChange={(enabled) => void run(() => sendJson<MemoryState>('/api/memory/preferences/settings', { enabled }, 'PUT'))} />
          </div>
          <h2 className="list-title">Saved preferences <small>{memory.preferences.length}</small>
            {memory.preferences.length > 0 && <button type="button" className="link-button" disabled={busy} onClick={() => { if (window.confirm('Forget all saved preferences?')) void run(() => sendJson<MemoryState>('/api/memory/preferences', undefined, 'DELETE')) }}>Forget all</button>}
          </h2>
          {!memory.preferences.length ? <p className="note">Nothing saved yet.</p> : (
            <ul className="rows">
              {memory.preferences.map((item) => (
                <li key={item.id} className="row">
                  <div className="row__text"><strong>{item.preference}</strong><span>{item.category}</span></div>
                  <button type="button" className="icon-button" aria-label={`Forget ${item.preference}`} disabled={busy} onClick={() => void run(() => sendJson<MemoryState>(`/api/memory/preferences/${encodeURIComponent(item.id)}`, undefined, 'DELETE'))}><Trash2 size={14} /></button>
                </li>
              ))}
            </ul>
          )}
        </>
      )}
    </PageFrame>
  )
}

export function SettingsPage({ status, info, onOpen }: { status: Status; info: AppInfo | null; onOpen: (page: 'services' | 'setup') => void }) {
  const [busy, setBusy] = useState('')
  const [message, setMessage] = useState('')
  const act = async (id: string, task: () => Promise<unknown>, done: string) => {
    setBusy(id)
    setMessage('')
    try { await task(); setMessage(done); await status.refreshState() } catch (actError) { setMessage(actError instanceof Error ? actError.message : 'That did not work.') } finally { setBusy('') }
  }
  const running = status.services.filter((service) => service.status === 'running').length
  const installed = status.services.filter((service) => service.available).length
  return (
    <PageFrame eyebrow="System" title="Settings" intro="How PockPock runs on this PC.">
      {message && <div className="banner" role="status"><span>{message}</span></div>}
      <ul className="rows">
        <li className="row">
          <Server size={16} className="row__icon" />
          <div className="row__text"><strong>Services</strong><span>{running} of {installed} installed services running · {status.backend.phase === 'ready' ? 'PockPock gateway ready' : status.backend.detail}</span></div>
          <button type="button" className="button" onClick={() => onOpen('services')}>Open Services</button>
        </li>
        <li className="row">
          <RefreshCw size={16} className="row__icon" />
          <div className="row__text"><strong>Smart Router</strong><span>{status.state?.router_enabled === false ? 'Paused: Chat and PockPock Agent will not answer.' : 'On. Picks a local model for each Chat and PockPock Agent request.'}</span></div>
          <Toggle checked={status.state?.router_enabled !== false} busy={busy === 'router' || !status.state} label="Smart Router" onChange={(enabled) => void act('router', () => sendJson('/api/router', { enabled }, 'PUT'), enabled ? 'Router started.' : 'Router paused.')} />
        </li>
        <li className="row">
          <Plug size={16} className="row__icon" />
          <div className="row__text"><strong>OpenClaw</strong><span>{status.claw?.detail || 'Checking…'}{status.claw?.ready ? ` · default model ${status.claw.model?.replace('ollama/', '')}` : ''}</span></div>
          <button type="button" className="button" onClick={() => void status.refreshClaw(true)}><RefreshCw size={13} /> Check</button>
        </li>
        <li className="row">
          <Plug size={16} className="row__icon" />
          <div className="row__text"><strong>NemoClaw sandbox check</strong><span>{status.nemoChecking ? 'Checking the sandbox (this loads its model)…' : status.nemo?.detail || 'Not checked'}</span></div>
          <button type="button" className="button" disabled={status.nemoChecking} onClick={() => void status.refreshNemo(true, true)}>{status.nemoChecking ? <LoaderCircle size={13} className="spin" /> : <RefreshCw size={13} />} Check sandbox</button>
        </li>
        <li className="row">
          <Power size={16} className="row__icon" />
          <div className="row__text"><strong>Setup</strong><span>Install missing components, repair them, or add OpenClaw and NemoClaw later.</span></div>
          <button type="button" className="button" onClick={() => onOpen('setup')}>Run setup</button>
        </li>
      </ul>
      {info && <p className="note">PockPock Agent {info.version} · Electron {info.electron} · backend {info.backendRoot} · Python {info.python}</p>}
    </PageFrame>
  )
}
