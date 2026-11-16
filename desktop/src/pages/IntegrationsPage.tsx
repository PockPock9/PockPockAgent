// Connectors: external services the agent can connect to (GitHub, email,
// calendars, ...), plus the integrations that run on this PC. The backend
// owns the catalog at /api/integrations; this page only renders it.
import { useCallback, useEffect, useRef, useState } from 'react'
import { ChevronDown, ChevronRight, LoaderCircle, Plug, RefreshCw, Search } from 'lucide-react'
import { getJson, sendJson } from '../lib/api'
import type { Status } from '../lib/status'
import { Empty } from '../components/ui'
import { PageFrame } from './Pages'

type IntegrationStatus = 'connected' | 'not_connected' | 'needs_setup' | 'disabled'
type IntegrationKind = 'external' | 'internal'
type AuthMethod = 'oauth' | 'api_token' | 'local'

type Integration = {
  id: string
  name: string
  category: string
  description: string
  capabilities: string[]
  status: IntegrationStatus
  detail: string
  enabled: boolean
  manage_hint: string
  setup_hint: string
  counts?: { models?: number; skills?: number; mcp_servers?: number }
  kind?: IntegrationKind
  auth?: AuthMethod
  scopes?: string[]
  connect_steps?: string[]
  account?: string | null
  auth_method?: string | null
  verified?: boolean
  featured?: boolean
  group?: string
  icon?: string
}

type IntegrationsResponse = { integrations: Integration[] }

// Ids the backend reports as external when an entry carries no kind yet.
const EXTERNAL_IDS = new Set([
  'github', 'gmail', 'outlook_mail', 'outlook_calendar', 'google_calendar',
  'slack', 'notion', 'google_drive', 'google_docs', 'google_sheets',
  'instagram', 'facebook', 'threads', 'spotify', 'messenger',
])

// Display order of the external groups; any group the backend adds later
// follows in first-seen order.
const GROUP_ORDER = ['Productivity', 'Developer', 'Communication', 'Social', 'Finance']

const TILE_TONES = 5
const COLLAPSED_ROWS = 4

const CATEGORIES = ['Models', 'Agents', 'Tools', 'Data'] as const

function categoryLabel(category: string) {
  const match = CATEGORIES.find((item) => item.toLowerCase() === category.trim().toLowerCase())
  return match ?? category
}

function isExternal(item: Integration) {
  return item.kind === 'external' || (item.kind !== 'internal' && EXTERNAL_IDS.has(item.id))
}

function authLabel(method: string | null | undefined) {
  if (method === 'oauth') return 'OAuth'
  if (method === 'api_token') return 'API token'
  if (method === 'local') return 'Local'
  return method ?? 'OAuth'
}

/** Letter mark for the icon tile. The backend's icon field is a short key
 * (usually the id, such as "github"), so initials come from the name; a
 * one- or two-letter icon is used as-is. No trademarked logo images. */
function initials(item: Integration) {
  const icon = (item.icon ?? '').trim()
  if (icon.length >= 1 && icon.length <= 2) return icon.toUpperCase()
  const words = item.name.split(/\s+/).filter(Boolean)
  if (words.length >= 2) return (words[0][0] + words[1][0]).toUpperCase()
  const caps = item.name.replace(/[^A-Z]/g, '')
  if (caps.length >= 2) return caps.slice(0, 2)
  return item.name.slice(0, 2).toUpperCase()
}

function tileTone(item: Integration) {
  const key = item.icon || item.id
  let hash = 0
  for (const char of key) hash = (hash * 31 + char.charCodeAt(0)) % 997
  return hash % TILE_TONES
}

const BADGE: Record<IntegrationStatus, { tone: 'ok' | 'warn' | 'off'; label: string }> = {
  connected: { tone: 'ok', label: 'Connected' },
  not_connected: { tone: 'off', label: 'Not connected' },
  needs_setup: { tone: 'warn', label: 'Needs setup' },
  disabled: { tone: 'off', label: 'Disabled' },
}

function countsText(counts: Integration['counts']) {
  if (!counts) return ''
  const parts: string[] = []
  if (counts.models) parts.push(`${counts.models} model${counts.models === 1 ? '' : 's'}`)
  if (counts.skills) parts.push(`${counts.skills} skill${counts.skills === 1 ? '' : 's'}`)
  if (counts.mcp_servers) parts.push(`${counts.mcp_servers} MCP server${counts.mcp_servers === 1 ? '' : 's'}`)
  return parts.join(' · ')
}

function Toggle({ checked, busy, label, onChange }: { checked: boolean; busy?: boolean; label: string; onChange: (next: boolean) => void }) {
  return <button type="button" role="switch" aria-checked={checked} aria-label={label} className="switch" disabled={busy} onClick={() => onChange(!checked)}><span /></button>
}

type ConnectForm = { account: string; authMethod: string; credential: string }

function formFor(item: Integration): ConnectForm {
  return { account: item.account ?? '', authMethod: item.auth_method ?? item.auth ?? 'oauth', credential: '' }
}

type ConnectBody = { account?: string; auth_method?: string; credential?: string }

export function IntegrationsPage({ status, onOpen, onBack }: { status: Status; onOpen: (page: 'skills' | 'mcp') => void; onBack: () => void }) {
  const [list, setList] = useState<Integration[] | null>(null)
  const [error, setError] = useState('')
  const [message, setMessage] = useState('')
  const [pending, setPending] = useState('')
  const [openId, setOpenId] = useState<string | null>(null)
  const [query, setQuery] = useState('')
  const [tab, setTab] = useState<'available' | 'connected'>('available')
  const [expandedGroups, setExpandedGroups] = useState<ReadonlySet<string>>(new Set())
  const [form, setForm] = useState<ConnectForm>({ account: '', authMethod: 'oauth', credential: '' })
  const noticeRef = useRef<HTMLDivElement>(null)

  const load = useCallback(async () => {
    try {
      const data = await getJson<IntegrationsResponse>('/api/integrations')
      setList(data.integrations)
      setError('')
      return data.integrations
    } catch (loadError) {
      setError(loadError instanceof Error ? loadError.message : 'Could not load integrations.')
      return null
    }
  }, [])
  useEffect(() => { void load() }, [load])

  // A Connect/Disconnect result used to land in a banner above the viewport
  // while the list kept its scroll position; bring the notice into view.
  useEffect(() => {
    if ((message || error) && noticeRef.current) noticeRef.current.scrollIntoView({ block: 'nearest' })
  }, [message, error])

  const act = async (integration: Integration, action: 'toggle' | 'connect' | 'disconnect', enabled?: boolean, body?: ConnectBody) => {
    const key = `${action}:${integration.id}`
    setPending(key)
    setError('')
    setMessage('')
    try {
      if (action === 'toggle') {
        await sendJson<{ ok: boolean; enabled: boolean }>(`/api/integrations/${encodeURIComponent(integration.id)}/toggle`, { enabled: Boolean(enabled) })
      } else if (action === 'connect' && isExternal(integration)) {
        const result = await sendJson<{ ok: boolean; status: IntegrationStatus; detail: string; note?: string }>(`/api/integrations/${encodeURIComponent(integration.id)}/connect`, body ?? {})
        setMessage(result.note ?? result.detail)
      } else {
        const result = await sendJson<{ ok: boolean; status: IntegrationStatus; detail: string; note?: string }>(`/api/integrations/${encodeURIComponent(integration.id)}/${action}`)
        setMessage(result.note ?? result.detail)
      }
      const fresh = await load()
      const updated = fresh?.find((item) => item.id === integration.id)
      if (updated && isExternal(updated)) setForm(formFor(updated))
      void status.refreshCounts()
    } catch (actError) {
      // A 409 (for example, skills and MCP servers are managed on their own pages,
      // or a GitHub token was rejected) leaves the list untouched.
      setError(actError instanceof Error ? actError.message : 'That did not work.')
    } finally {
      setPending('')
    }
  }

  const openRow = (item: Integration) => {
    if (openId === item.id) { setOpenId(null); return }
    setOpenId(item.id)
    if (isExternal(item)) setForm(formFor(item))
  }
  const showRow = (item: Integration) => {
    setOpenId(item.id)
    if (isExternal(item)) setForm(formFor(item))
  }

  const search = query.trim().toLowerCase()
  const matches = (item: Integration) => !search || item.name.toLowerCase().includes(search) || item.description.toLowerCase().includes(search)
  const external = (list ?? []).filter(isExternal)
  const internal = (list ?? []).filter((item) => !isExternal(item) && matches(item))
  const available = external.filter((item) => matches(item) && item.status !== 'connected')
  const connected = external.filter((item) => matches(item) && item.status === 'connected')
  const shown = tab === 'available' ? available : connected
  const featured = tab === 'available' && !search ? shown.filter((item) => item.featured) : []
  // While searching, the Featured section is hidden, so featured matches
  // must appear in their groups instead of disappearing.
  const groupedItems = search ? shown : shown.filter((item) => !item.featured)
  const groupNames = [...new Set(groupedItems.map((item) => item.group || categoryLabel(item.category) || 'Other'))]
  const orderedGroups = [...GROUP_ORDER.filter((name) => groupNames.includes(name)), ...groupNames.filter((name) => !GROUP_ORDER.includes(name))]
  const groups = orderedGroups.map((name) => ({ name, items: groupedItems.filter((item) => (item.group || categoryLabel(item.category) || 'Other') === name) }))

  const renderDetail = (item: Integration) => {
    const busy = pending !== '' && pending.endsWith(`:${item.id}`)
    if (isExternal(item)) {
      const scopes = item.scopes?.length ? item.scopes : item.capabilities
      const connectedNow = item.status === 'connected'
      const authOptions = item.auth === 'oauth' ? ['oauth'] : item.auth === 'api_token' ? ['api_token'] : ['oauth', 'api_token']
      return (
        <div className="integration-detail">
          {scopes.length > 0 && (
            <>
              <strong>What the agent can do</strong>
              <ul>{scopes.map((scope) => <li key={scope}>{scope}</li>)}</ul>
            </>
          )}
          {!connectedNow && item.connect_steps && item.connect_steps.length > 0 && (
            <>
              <strong>How to connect</strong>
              <ol>{item.connect_steps.map((step) => <li key={step}>{step}</li>)}</ol>
            </>
          )}
          {connectedNow && (
            <>
              <p>Connected as <strong>{item.account ?? 'an account'}</strong> via {authLabel(item.auth_method)}</p>
              {!item.verified && <p className="row__error">Not verified against {item.name} in this build.</p>}
            </>
          )}
          {!connectedNow && (
            <form className="connect-form" onSubmit={(event) => {
              event.preventDefault()
              void act(item, 'connect', undefined, {
                account: form.account.trim() || undefined,
                auth_method: form.authMethod,
                credential: form.authMethod === 'api_token' ? form.credential || undefined : undefined,
              })
            }}>
              <label className="field" htmlFor={`${item.id}-account`}>Account
                <input id={`${item.id}-account`} className="input" type="text" autoComplete="username" value={form.account}
                  placeholder={item.auth === 'api_token' ? 'Optional — taken from your token' : 'you@example.com'}
                  onChange={(event) => setForm({ ...form, account: event.target.value })} />
              </label>
              <label className="field" htmlFor={`${item.id}-auth`}>Auth method
                <select id={`${item.id}-auth`} className="input" value={form.authMethod} onChange={(event) => setForm({ ...form, authMethod: event.target.value })}>
                  {authOptions.map((option) => <option key={option} value={option}>{authLabel(option)}</option>)}
                </select>
              </label>
              {form.authMethod === 'api_token' && (
                <label className="field" htmlFor={`${item.id}-credential`}>API token
                  <small>Stored only on this PC and never sent anywhere else.</small>
                  <input id={`${item.id}-credential`} className="input" type="password" autoComplete="off" value={form.credential}
                    placeholder="Paste your token" onChange={(event) => setForm({ ...form, credential: event.target.value })} />
                </label>
              )}
              <div className="row__actions">
                <button type="submit" className="button button--primary" disabled={busy}>
                  {pending === `connect:${item.id}` && <LoaderCircle size={13} className="spin" />} Connect
                </button>
              </div>
            </form>
          )}
          {connectedNow && (
            <div className="row__actions">
              <button type="button" className="button" disabled={busy} onClick={() => void act(item, 'disconnect')}>
                {pending === `disconnect:${item.id}` && <LoaderCircle size={13} className="spin" />} Disconnect
              </button>
            </div>
          )}
        </div>
      )
    }
    return (
      <div className="integration-detail">
        {item.capabilities.length > 0 && (
          <>
            <strong>What it can do</strong>
            <ul>{item.capabilities.map((capability) => <li key={capability}>{capability}</li>)}</ul>
          </>
        )}
        {item.setup_hint && <p><strong>Setup:</strong> {item.setup_hint}</p>}
        {item.manage_hint && <p><strong>Manage:</strong> {item.manage_hint}</p>}
        <div className="row__actions">
          {(item.status === 'not_connected' || item.status === 'needs_setup') && (
            <button type="button" className="button button--primary" disabled={busy} onClick={() => void act(item, 'connect')}>
              {pending === `connect:${item.id}` && <LoaderCircle size={13} className="spin" />} Connect
            </button>
          )}
          {item.status === 'connected' && (
            <button type="button" className="button" disabled={busy} onClick={() => void act(item, 'disconnect')}>
              {pending === `disconnect:${item.id}` && <LoaderCircle size={13} className="spin" />} Disconnect
            </button>
          )}
        </div>
      </div>
    )
  }

  const renderRow = (item: Integration) => {
    const badge = BADGE[item.status]
    const open = openId === item.id
    const busy = pending !== '' && pending.endsWith(`:${item.id}`)
    const counts = countsText(item.counts)
    return (
      <li key={item.id} className="row">
        <div className="row__text">
          <button type="button" className="integration-row" aria-expanded={open} onClick={() => openRow(item)}>
            <span className={`tile tile--${tileTone(item)}`} aria-hidden="true">{initials(item)}</span>
            <span className="integration-row__text">
              <strong>{item.name} <small className={`badge badge--${badge.tone}`}>{badge.label}</small></strong>
              <span>{item.description}</span>
              {counts && <span>{counts}</span>}
              {item.status !== 'connected' && item.detail && <span className="row__error">{item.detail}</span>}
            </span>
            <ChevronDown size={14} className={`integration-row__chevron${open ? ' is-open' : ''}`} />
          </button>
          {open && renderDetail(item)}
        </div>
        <div className="row__actions">
          <button type="button" className="button button--primary" disabled={busy} onClick={() => showRow(item)}>
            {item.status === 'connected' ? 'View' : 'Connect'}
          </button>
          {(!isExternal(item) || item.status === 'disabled') && (
            <Toggle checked={item.enabled} busy={busy} label={`Enable ${item.name}`} onChange={(next) => void act(item, 'toggle', next)} />
          )}
        </div>
      </li>
    )
  }

  const renderFeatured = (item: Integration) => {
    const open = openId === item.id
    return (
      <li key={item.id} className="connector-featured">
        <button type="button" className="connector-featured__head" aria-expanded={open} onClick={() => openRow(item)}>
          <span className="connector-featured__text">
            <strong>{item.name}</strong>
            <span>{item.description}</span>
          </span>
          <span className={`tile tile--lg tile--${tileTone(item)}`} aria-hidden="true">{initials(item)}</span>
        </button>
        {open && renderDetail(item)}
      </li>
    )
  }

  return (
    <PageFrame eyebrow="Customize" title="Connectors" onBack={onBack}
      intro="Connectors are external services the agent can connect to — GitHub, email, calendars and more. Your credentials stay on this PC and are never sent anywhere else."
      actions={<div className="page__actions"><button type="button" className="button" disabled={Boolean(pending) || !list} onClick={() => void load()}><RefreshCw size={13} /> Refresh</button></div>}>
      <div ref={noticeRef}>
        {message && <div className="banner" role="status"><span>{message}</span></div>}
        {error && <div className="banner banner--error" role="alert"><span>{error}</span></div>}
      </div>
      {!list && !error && <p className="note"><LoaderCircle size={13} className="spin" /> Loading connectors…</p>}
      {list && (
        <>
          <label className="search connectors-search">
            <Search size={14} aria-hidden="true" />
            <input type="search" value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Search connectors" aria-label="Search connectors" />
          </label>
          <div className="segmented" role="tablist" aria-label="Connectors">
            <button type="button" role="tab" aria-selected={tab === 'available'} className={tab === 'available' ? 'is-active' : undefined} onClick={() => setTab('available')}>Available <small>{available.length}</small></button>
            <button type="button" role="tab" aria-selected={tab === 'connected'} className={tab === 'connected' ? 'is-active' : undefined} onClick={() => setTab('connected')}>Connected <small>{connected.length}</small></button>
          </div>
          {external.length === 0 && <p className="note">No external connectors are listed by the backend yet.</p>}
          {featured.length > 0 && (
            <section>
              <h2 className="list-title">Featured</h2>
              <ul className="connectors-featured">{featured.map(renderFeatured)}</ul>
            </section>
          )}
          {groups.map((group) => {
            const expanded = expandedGroups.has(group.name)
            const visible = expanded ? group.items : group.items.slice(0, COLLAPSED_ROWS)
            return (
              <section key={group.name}>
                <h2 className="list-title">{group.name} <small>{group.items.length}</small>
                  {group.items.length > COLLAPSED_ROWS && (
                    <button type="button" className="see-all" aria-expanded={expanded} onClick={() => setExpandedGroups((current) => {
                      const next = new Set(current)
                      if (expanded) next.delete(group.name); else next.add(group.name)
                      return next
                    })}>
                      {expanded ? 'Show less' : <>See all <ChevronRight size={12} /></>}
                    </button>
                  )}
                </h2>
                <ul className="rows">{visible.map(renderRow)}</ul>
              </section>
            )
          })}
          {external.length > 0 && shown.length === 0 && tab === 'available' && !search && <p className="note">Everything is connected.</p>}
          {external.length > 0 && shown.length === 0 && tab === 'connected' && !search && (
            <Empty icon={<Plug size={20} />} title="No connectors connected yet"><p>Connect one from the Available tab.</p></Empty>
          )}
          {external.length > 0 && shown.length === 0 && search && <p className="note">No connectors match “{query.trim()}”.</p>}
          <section>
            <h2 className="list-title">On this PC <small>{internal.length}</small></h2>
            <p className="note">On-device integrations — models, agents and tools that run on this PC.</p>
            {!internal.length ? <p className="note">{search ? `No on-device integrations match “${query.trim()}”.` : 'No on-device integrations found.'}</p> : (
              <ul className="rows">{internal.map(renderRow)}</ul>
            )}
          </section>
          <h2 className="list-title">Add an integration</h2>
          <ul className="rows">
            <li className="row">
              <Plug size={16} className="row__icon" />
              <div className="row__text"><strong>Add a skill or an MCP server</strong><span>New integrations arrive through Skills and MCP links — there is no separate add form here.</span></div>
              <div className="row__actions">
                <button type="button" className="button" onClick={() => onOpen('skills')}>Add a skill</button>
                <button type="button" className="button" onClick={() => onOpen('mcp')}>Add an MCP server</button>
              </div>
            </li>
          </ul>
        </>
      )}
    </PageFrame>
  )
}
