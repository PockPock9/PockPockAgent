// Connectors: external apps (GitHub, email, Telegram, ...) the agent can use as tools.
// Only apps outside PockPock are listed here. A credential is typed once, checked with the app by
// the backend, and stored encrypted by the main process; this page never gets it back.
import { useCallback, useEffect, useMemo, useState } from 'react'
import type { ReactNode } from 'react'
import { Cable, Check, ExternalLink, GitBranch, Hash, LoaderCircle, Mail, MessagesSquare, NotebookText, RotateCcw, Search, Send, ShieldAlert, Unplug } from 'lucide-react'
import { Empty } from '../components/ui'
import { Drawer, PageFrame } from '../components/page'
import { bridge } from '../lib/types'
import type { Connector } from '../lib/types'
import { relativeTime } from '../lib/api'

const clean = (reason: unknown, fallback: string) => (reason instanceof Error ? reason.message.replace(/^Error invoking remote method '[^']+': (Error: )?/, '') : fallback)

// Neutral pictograms, not the apps' trademarked logos.
const ICONS: Record<string, ReactNode> = {
  github: <GitBranch size={18} />, email: <Mail size={18} />, telegram: <Send size={18} />,
  slack: <Hash size={18} />, discord: <MessagesSquare size={18} />, notion: <NotebookText size={18} />,
}
const Tile = ({ id }: { id: string }) => <span className={`connector-tile connector-tile--${id}`} aria-hidden="true">{ICONS[id] ?? <Cable size={18} />}</span>

export function ConnectorsPage() {
  const desktop = bridge()
  const [connectors, setConnectors] = useState<Connector[] | null>(null)
  const [error, setError] = useState('')
  const [tab, setTab] = useState<'available' | 'connected'>('available')
  const [query, setQuery] = useState('')
  const [open, setOpen] = useState<string | null>(null)

  const load = useCallback(() => {
    if (!desktop) return
    desktop.connectors.list().then((list) => { setConnectors(list); setError('') }, (reason: unknown) => { setConnectors(null); setError(clean(reason, 'The connectors could not be loaded.')) })
  }, [desktop])
  useEffect(() => { load() }, [load])
  useEffect(() => desktop?.connectors.onChange(load), [desktop, load])

  const selected = connectors?.find((connector) => connector.id === open) ?? null

  const connectedCount = connectors?.filter((connector) => connector.connected).length ?? 0
  const words = query.toLowerCase().split(/\s+/).filter(Boolean)
  const shown = (connectors ?? []).filter((connector) => (tab === 'connected' ? connector.connected : true) && words.every((word) => `${connector.name} ${connector.about} ${connector.group}`.toLowerCase().includes(word)))
  const featured = tab === 'available' && !words.length ? shown.filter((connector) => connector.featured) : []
  // Featured apps are shown once, as cards; the groups below list the rest.
  const rows = shown.filter((connector) => !featured.includes(connector))
  const groups = [...new Set(rows.map((connector) => connector.group))]

  return (
    <PageFrame eyebrow="Workshop · Capabilities" title="Connectors" intro="Connect the apps you use, so the agent can read from them and act in them for you. Each connection uses a key you create in that app and can be removed at any time.">
      {error && <div className="banner banner--error" role="alert"><span>{error}</span><button type="button" className="button" onClick={load}><RotateCcw size={13} /> Try again</button></div>}
      {!desktop && <p className="note">Connectors are set up in the desktop app.</p>}
      {desktop && !connectors && !error && <p className="note"><LoaderCircle size={13} className="spin" /> Loading…</p>}
      {connectors && (
        <>
          <label className="search connectors-search">
            <Search size={13} />
            <input type="search" placeholder="Search connectors" value={query} onChange={(event) => setQuery(event.target.value)} aria-label="Search connectors" />
          </label>
          <div className="tabs" role="tablist" aria-label="Connectors">
            <button type="button" role="tab" id="connectors-tab-available" aria-selected={tab === 'available'} aria-controls="connectors-panel" className={tab === 'available' ? 'is-active' : ''} onClick={() => setTab('available')}>Available <small>{connectors.length}</small></button>
            <button type="button" role="tab" id="connectors-tab-connected" aria-selected={tab === 'connected'} aria-controls="connectors-panel" className={tab === 'connected' ? 'is-active' : ''} onClick={() => setTab('connected')}>Connected <small>{connectedCount}</small></button>
          </div>
          <div id="connectors-panel" role="tabpanel" aria-labelledby={`connectors-tab-${tab}`}>
            {shown.length === 0 && (
              tab === 'connected' && !words.length
                ? <Empty icon={<Cable size={20} />} title="Nothing connected yet"><p>Open <strong>Available</strong> and connect an app to give the agent its tools.</p></Empty>
                : <Empty icon={<Search size={20} />} title="No connector matches"><p>Try another word, or clear the search.</p></Empty>
            )}
            {featured.length > 0 && (
              <ul className="connectors-featured" aria-label="Featured">
                {featured.map((connector) => (
                  <li key={connector.id}>
                    <button type="button" className="connector-card" onClick={() => setOpen(connector.id)} aria-label={`${connector.name}: ${connector.connected ? 'connected, view' : 'connect'}`}>
                      <Tile id={connector.id} />
                      <span className="connector-card__text"><strong>{connector.name}</strong><span>{connector.about}</span></span>
                      <span className={`connector-action${connector.connected ? ' is-connected' : ''}`}>{connector.connected ? <><Check size={12} /> {connector.account || 'Connected'}</> : connector.needsReconnect ? 'Reconnect' : 'Connect'}</span>
                    </button>
                  </li>
                ))}
              </ul>
            )}
            {groups.map((group) => (
              <section key={group} aria-labelledby={`connectors-group-${group}`}>
                <h2 className="section-title" id={`connectors-group-${group}`}>{group}</h2>
                <ul className="rows">
                  {rows.filter((connector) => connector.group === group).map((connector) => (
                    <li key={connector.id} className="row connector-row">
                      <Tile id={connector.id} />
                      <div className="row__text">
                        <strong>{connector.name}{connector.needsReconnect && <small className="badge badge--warn">Reconnect needed</small>}</strong>
                        <span>{connector.connected ? `Connected as ${connector.account}` : connector.about}</span>
                      </div>
                      <button type="button" className={`button${connector.connected ? '' : ' button--primary'}`} onClick={() => setOpen(connector.id)} aria-label={`${connector.connected ? 'View' : 'Connect'} ${connector.name}`}>{connector.connected ? 'View' : 'Connect'}</button>
                    </li>
                  ))}
                </ul>
              </section>
            ))}
          </div>
          <p className="note connectors-foot">Connected apps give their tools to the <strong>OpenClaw</strong> engine. Reading runs as your permission setting allows; anything that sends, posts or creates asks you first unless you chose Full access.</p>
        </>
      )}
      {selected && (
        <Drawer title={selected.name} onClose={() => setOpen(null)}>
          <ConnectorDetail connector={selected} onChanged={setConnectors} />
        </Drawer>
      )}
    </PageFrame>
  )
}

function ConnectorDetail({ connector, onChanged }: { connector: Connector; onChanged: (list: Connector[]) => void }) {
  const desktop = bridge()
  const [values, setValues] = useState<Record<string, string>>(() => Object.fromEntries(connector.fields.filter((field) => field.options.length).map((field) => [field.key, field.options[0].value])))
  const [busy, setBusy] = useState<'' | 'connect' | 'disconnect'>('')
  const [error, setError] = useState('')
  const [message, setMessage] = useState('')
  const [replacing, setReplacing] = useState(false)
  const fields = useMemo(() => connector.fields.filter((field) => !field.only_when || values[field.only_when[0]] === field.only_when[1]), [connector.fields, values])
  const complete = fields.every((field) => !field.required || (values[field.key] ?? '').trim())
  const showForm = !connector.connected || replacing
  const reads = connector.tools.filter((tool) => !tool.write)
  const writes = connector.tools.filter((tool) => tool.write)

  const connect = async () => {
    if (!desktop || !complete) return
    setBusy('connect'); setError(''); setMessage('')
    try {
      const list = await desktop.connectors.connect(connector.id, values)
      // Secrets leave the page as soon as they are saved.
      setValues((current) => Object.fromEntries(Object.entries(current).filter(([key]) => !connector.fields.find((field) => field.key === key)?.secret)))
      setReplacing(false)
      onChanged(list)
      setMessage(`Connected as ${list.find((item) => item.id === connector.id)?.account ?? connector.name}. The agent can use these tools now.`)
    } catch (reason) { setError(clean(reason, `${connector.name} could not be connected.`)) } finally { setBusy('') }
  }
  const disconnect = async () => {
    if (!desktop || !window.confirm(`Disconnect ${connector.name}? Its key is deleted from this computer and the agent loses its tools.`)) return
    setBusy('disconnect'); setError(''); setMessage('')
    try { onChanged(await desktop.connectors.disconnect(connector.id)); setMessage('Disconnected.') } catch (reason) { setError(clean(reason, 'The connector could not be disconnected.')) } finally { setBusy('') }
  }

  return (
    <div className="connector-detail">
        <p className="card__sub">{connector.about}</p>
        <header className="connector-detail__head">
          <Tile id={connector.id} />
          <div className="row__text"><strong>{connector.name}</strong><span>{connector.connected ? `Connected as ${connector.account}${connector.connectedAt ? ` · ${relativeTime(Date.parse(connector.connectedAt))}` : ''}` : connector.needsReconnect ? 'The saved key can no longer be read on this computer. Connect again.' : 'Not connected'}</span></div>
          <small className={`badge ${connector.connected ? 'badge--ok' : connector.needsReconnect ? 'badge--warn' : 'badge--off'}`}>{connector.connected ? 'Connected' : connector.needsReconnect ? 'Reconnect needed' : 'Not connected'}</small>
        </header>
        {error && <div className="banner banner--error" role="alert"><span>{error}</span></div>}
        {message && !error && <div className="banner" role="status"><Check size={14} /><span>{message}</span></div>}

        <section className="card" aria-labelledby="connector-tools">
          <h2 className="connector-h" id="connector-tools">What the agent can do</h2>
          <ul className="connector-tools">
            {reads.map((tool) => <li key={tool.name}><Check size={13} /> {tool.title}</li>)}
            {writes.map((tool) => <li key={tool.name} className="is-write"><ShieldAlert size={13} /> {tool.title} <small>asks you first</small></li>)}
          </ul>
        </section>

        {showForm && (
          <section className="card" aria-labelledby="connector-connect">
            <h2 className="connector-h" id="connector-connect">{connector.connected ? 'Replace the key' : `Connect ${connector.name}`}</h2>
            <ol className="connector-steps">{connector.steps.map((step) => <li key={step}>{step}</li>)}</ol>
            <form className="cloud-form" onSubmit={(event) => { event.preventDefault(); void connect() }}>
              {fields.map((field) => (
                <label key={field.key}><span>{field.label}</span>
                  {field.options.length > 0 ? (
                    <select className="input" value={values[field.key] ?? ''} disabled={busy !== ''} onChange={(event) => setValues({ ...values, [field.key]: event.target.value })}>
                      {field.options.map((option) => <option key={option.value} value={option.value}>{option.label}</option>)}
                    </select>
                  ) : (
                    <input className="input" type={field.secret ? 'password' : 'text'} autoComplete="off" spellCheck={false} placeholder={field.placeholder} value={values[field.key] ?? ''} disabled={busy !== ''}
                      aria-describedby={field.help ? `connector-help-${field.key}` : undefined} onChange={(event) => setValues({ ...values, [field.key]: event.target.value })} />
                  )}
                  {field.help && <small className="connector-help" id={`connector-help-${field.key}`}>{field.help}</small>}
                </label>
              ))}
              <p className="note">PockPock checks this with {connector.name}, then stores it encrypted on this computer. It is not shown again, and the agent never sees it.</p>
              <div className="card__actions">
                <button type="submit" className="button button--primary" disabled={busy !== '' || !complete}>{busy === 'connect' ? <LoaderCircle size={13} className="spin" /> : <Cable size={13} />} {busy === 'connect' ? `Checking with ${connector.name}…` : connector.connected ? 'Replace key' : 'Connect'}</button>
                <button type="button" className="button" onClick={() => void desktop?.openExternal(connector.key_url)}><ExternalLink size={13} /> Open {connector.name}</button>
                {replacing && <button type="button" className="button" onClick={() => { setReplacing(false); setError('') }}>Cancel</button>}
              </div>
            </form>
          </section>
        )}

        {connector.connected && !replacing && (
          <div className="card__actions">
            <button type="button" className="button" disabled={busy !== ''} onClick={() => { setReplacing(true); setMessage('') }}><RotateCcw size={13} /> Replace key</button>
            <button type="button" className="button" disabled={busy !== ''} onClick={() => void disconnect()}>{busy === 'disconnect' ? <LoaderCircle size={13} className="spin" /> : <Unplug size={13} />} Disconnect</button>
          </div>
        )}
    </div>
  )
}
