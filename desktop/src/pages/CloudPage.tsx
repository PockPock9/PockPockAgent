// Cloud models: connect NVIDIA NIM, OpenRouter or Alibaba Cloud Model Studio with an API key and
// choose which of their models appear in the model pickers. The key goes to the main process once
// and is never read back; this page only ever sees its last four characters.
import { useCallback, useEffect, useMemo, useState } from 'react'
import { Check, Cloud, ExternalLink, KeyRound, ListChecks, LoaderCircle, Search, Unplug, X } from 'lucide-react'
import { PageFrame } from './Pages'
import { bridge } from '../lib/types'
import type { CloudModel, CloudProvider } from '../lib/types'
import type { Status } from '../lib/status'

const clean = (reason: unknown, fallback: string) => (reason instanceof Error ? reason.message.replace(/^Error invoking remote method '[^']+': (Error: )?/, '') : fallback)
const contextLabel = (tokens: number | null) => (tokens ? `${tokens >= 1_000_000 ? `${Number((tokens / 1_000_000).toFixed(1))}M` : `${Math.round(tokens / 1000)}K`} context` : '')
const MAX_CHOSEN = 40

export function CloudPage({ status }: { status: Status }) {
  const desktop = bridge()
  const [providers, setProviders] = useState<CloudProvider[] | null>(null)
  const [error, setError] = useState('')

  const load = useCallback(() => {
    if (!desktop) return
    desktop.cloud.list().then((list) => { setProviders(list); setError('') }, (reason: unknown) => setError(clean(reason, 'Cloud providers could not be loaded.')))
  }, [desktop])
  useEffect(() => { load() }, [load])
  useEffect(() => desktop?.cloud.onChange((list) => { setProviders(list); void status.refreshState(); void status.refreshClaw(true) }), [desktop, status])

  const chosen = providers?.reduce((sum, provider) => sum + provider.models.length, 0) ?? 0
  return (
    <PageFrame eyebrow="Customize · Cloud" title="Cloud models" intro="Connect a cloud service to use its models in PockPock Agent, OpenClaw and NemoClaw, next to the models on this PC. You use your own account and pay the service directly.">
      {error && <div className="banner banner--error" role="alert"><span>{error}</span></div>}
      <div className="banner" role="note"><Cloud size={14} /><span>A cloud model receives the messages, files and tool results of the chats that use it. Cloud models are used only when you pick one in a chat&rsquo;s model menu; <strong>Smart route</strong> keeps choosing local models. Keys are stored encrypted on this PC.</span></div>
      {!desktop && <p className="note">Cloud providers are set up in the desktop app.</p>}
      {desktop && !providers && !error && <p className="note"><LoaderCircle size={13} className="spin" /> Loading…</p>}
      {providers && <p className="note">{chosen ? `${chosen} cloud ${chosen === 1 ? 'model is' : 'models are'} in the model menus.` : 'No cloud models are in the model menus yet.'}</p>}
      <div className="cloud-list">
        {providers?.map((provider) => <ProviderCard key={provider.id} provider={provider} onChanged={setProviders} />)}
      </div>
    </PageFrame>
  )
}

function ProviderCard({ provider, onChanged }: { provider: CloudProvider; onChanged: (list: CloudProvider[]) => void }) {
  const desktop = bridge()
  const [key, setKey] = useState('')
  const [region, setRegion] = useState(provider.region)
  const [busy, setBusy] = useState<'' | 'connect' | 'disconnect' | 'models' | 'save'>('')
  const [error, setError] = useState('')
  const [message, setMessage] = useState('')
  const [offered, setOffered] = useState<CloudModel[] | null>(null) // set while the model chooser is open
  const [changingKey, setChangingKey] = useState(false)
  const titleId = `cloud-${provider.id}`

  const connect = async () => {
    if (!desktop || !key.trim()) return
    setBusy('connect'); setError(''); setMessage('')
    try {
      const result = await desktop.cloud.connect(provider.id, { key, region })
      setKey(''); setChangingKey(false)
      onChanged(result.providers)
      const now = result.providers.find((item) => item.id === provider.id)
      setMessage(now?.models.length ? `Connected. ${now.models.length} suggested ${now.models.length === 1 ? 'model was' : 'models were'} added to the model menus.` : 'Connected. Choose the models you want in the model menus.')
      if (!now?.models.length) setOffered(result.offered)
    } catch (reason) { setError(clean(reason, `${provider.name} could not be connected.`)) } finally { setBusy('') }
  }
  const disconnect = async () => {
    if (!desktop || !window.confirm(`Disconnect ${provider.name}? Its key is deleted from this PC and its models leave the model menus.`)) return
    setBusy('disconnect'); setError(''); setMessage('')
    try { onChanged(await desktop.cloud.disconnect(provider.id)); setOffered(null) } catch (reason) { setError(clean(reason, 'The provider could not be disconnected.')) } finally { setBusy('') }
  }
  const openChooser = async () => {
    if (!desktop) return
    setBusy('models'); setError(''); setMessage('')
    try { setOffered(await desktop.cloud.available(provider.id)) } catch (reason) { setError(clean(reason, 'The model list could not be loaded.')) } finally { setBusy('') }
  }
  const save = async (models: CloudModel[]) => {
    if (!desktop) return
    setBusy('save'); setError('')
    try { onChanged(await desktop.cloud.setModels(provider.id, models)); setOffered(null); setMessage('Saved.') } catch (reason) { setError(clean(reason, 'The models could not be saved.')) } finally { setBusy('') }
  }
  const showKeyForm = !provider.connected || changingKey

  return (
    <section className="card cloud-card" aria-labelledby={titleId}>
      <header className="cloud-card__head">
        <Cloud size={16} />
        <strong id={titleId}>{provider.name}</strong>
        <small className={`badge ${provider.connected ? 'badge--ok' : provider.needsKey ? 'badge--warn' : 'badge--off'}`}>{provider.connected ? 'Connected' : provider.needsKey ? 'Key needed again' : 'Not connected'}</small>
      </header>
      <p className="note">{provider.about}</p>
      {error && <div className="banner banner--error" role="alert"><span>{error}</span></div>}
      {message && !error && <div className="banner" role="status"><Check size={14} /><span>{message}</span></div>}
      {provider.needsKey && !changingKey && <p className="note">The saved key can no longer be read on this computer. Enter the key again.</p>}

      {showKeyForm && (
        <form className="cloud-form" onSubmit={(event) => { event.preventDefault(); void connect() }}>
          {provider.regions.length > 1 && (
            <label><span>Region of your key</span>
              <select className="input" value={region} onChange={(event) => setRegion(event.target.value)} disabled={busy !== ''}>
                {provider.regions.map((item) => <option key={item.id} value={item.id}>{item.name}</option>)}
              </select>
            </label>
          )}
          <label><span>API key</span>
            <input className="input" type="password" autoComplete="off" spellCheck={false} placeholder={provider.keyHint} value={key} onChange={(event) => setKey(event.target.value)} disabled={busy !== ''} aria-describedby={`${titleId}-keyhelp`} />
          </label>
          <p className="note" id={`${titleId}-keyhelp`}>PockPock checks the key with {provider.name}, then stores it encrypted on this PC. It is not shown again.</p>
          <div className="card__actions">
            <button type="submit" className="button button--primary" disabled={busy !== '' || !key.trim()}>{busy === 'connect' ? <LoaderCircle size={13} className="spin" /> : <KeyRound size={13} />} {busy === 'connect' ? 'Checking the key…' : provider.connected ? 'Replace key' : `Connect ${provider.name}`}</button>
            <button type="button" className="button" onClick={() => void desktop?.openExternal(provider.keyUrl)}><ExternalLink size={13} /> Get a key</button>
            {changingKey && <button type="button" className="button" onClick={() => { setChangingKey(false); setKey(''); setError('') }}>Cancel</button>}
          </div>
        </form>
      )}

      {provider.connected && !changingKey && (
        <>
          <dl className="setup-facts">
            <div><dt>Key</dt><dd>Ends in <code>{provider.keyEnding}</code>{provider.regions.length > 1 ? ` · ${provider.regions.find((item) => item.id === provider.region)?.name ?? provider.region}` : ''}</dd></div>
            <div><dt>In the model menus</dt><dd>{provider.models.length ? `${provider.models.length} ${provider.models.length === 1 ? 'model' : 'models'}` : 'None yet'}</dd></div>
          </dl>
          {provider.models.length > 0 && !offered && (
            <ul className="cloud-chosen">
              {provider.models.map((model) => <li key={model.id}><code>{model.id}</code>{contextLabel(model.contextWindow) && <small>{contextLabel(model.contextWindow)}</small>}</li>)}
            </ul>
          )}
          {offered && <ModelChooser provider={provider} offered={offered} saving={busy === 'save'} onSave={(models) => void save(models)} onCancel={() => setOffered(null)} />}
          {!offered && (
            <div className="card__actions">
              <button type="button" className="button button--primary" disabled={busy !== ''} onClick={() => void openChooser()}>{busy === 'models' ? <LoaderCircle size={13} className="spin" /> : <ListChecks size={13} />} {busy === 'models' ? 'Loading models…' : 'Choose models'}</button>
              <button type="button" className="button" disabled={busy !== ''} onClick={() => { setChangingKey(true); setMessage('') }}><KeyRound size={13} /> Replace key</button>
              <button type="button" className="button" disabled={busy !== ''} onClick={() => void disconnect()}>{busy === 'disconnect' ? <LoaderCircle size={13} className="spin" /> : <Unplug size={13} />} Disconnect</button>
            </div>
          )}
        </>
      )}
    </section>
  )
}

function ModelChooser({ provider, offered, saving, onSave, onCancel }: { provider: CloudProvider; offered: CloudModel[]; saving: boolean; onSave: (models: CloudModel[]) => void; onCancel: () => void }) {
  const [query, setQuery] = useState('')
  const [picked, setPicked] = useState<Map<string, CloudModel>>(() => new Map(provider.models.map((model) => [model.id, model])))
  const shown = useMemo(() => {
    const words = query.toLowerCase().split(/\s+/).filter(Boolean)
    // Chosen models first, then the rest in name order.
    return offered
      .filter((model) => words.every((word) => model.id.toLowerCase().includes(word) || model.name.toLowerCase().includes(word)))
      .sort((a, b) => Number(picked.has(b.id)) - Number(picked.has(a.id)))
      .slice(0, 200)
    // Sorting follows the saved choice, not each click, so rows do not jump while choosing.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [offered, query])
  const toggle = (model: CloudModel) => setPicked((current) => {
    const next = new Map(current)
    if (next.has(model.id)) next.delete(model.id)
    else next.set(model.id, model)
    return next
  })
  const over = picked.size > MAX_CHOSEN
  const listId = `cloud-${provider.id}-models`
  return (
    <div className="cloud-chooser">
      <label className="search cloud-chooser__search">
        <Search size={13} />
        <input type="search" placeholder={`Search ${offered.length} models`} value={query} onChange={(event) => setQuery(event.target.value)} aria-label={`Search ${provider.name} models`} aria-controls={listId} />
      </label>
      {offered.length === 0 ? <p className="note">{provider.name} listed no chat models for this key.</p> : (
        <ul className="cloud-chooser__list" id={listId} aria-label={`${provider.name} models`}>
          {shown.map((model) => (
            <li key={model.id}>
              <label>
                <input type="checkbox" checked={picked.has(model.id)} onChange={() => toggle(model)} />
                <span><strong>{model.name !== model.id ? model.name : model.id}</strong><em>{[model.name !== model.id ? model.id : '', contextLabel(model.contextWindow), model.free ? 'free' : '', model.tools === false ? 'no tool calls: chat only' : ''].filter(Boolean).join(' · ')}</em></span>
              </label>
            </li>
          ))}
          {shown.length === 0 && <li className="cloud-chooser__none">No model matches “{query}”.</li>}
        </ul>
      )}
      <p className={`note${over ? ' note--error' : ''}`} role={over ? 'alert' : undefined}>{picked.size} chosen{over ? `. Choose at most ${MAX_CHOSEN}.` : '. Chosen models appear in the model menus of every engine.'}</p>
      <div className="card__actions">
        <button type="button" className="button button--primary" disabled={saving || over} onClick={() => onSave([...picked.values()])}>{saving ? <LoaderCircle size={13} className="spin" /> : <Check size={13} />} Save models</button>
        <button type="button" className="button" disabled={saving} onClick={onCancel}><X size={13} /> Cancel</button>
      </div>
    </div>
  )
}
