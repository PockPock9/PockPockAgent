// Settings: how PockPock looks, runs and updates. Sections: Theme (a radio grid of the five themes),
// Smart Router, Ollama, OpenClaw, NemoClaw, Updates and Setup.
import { useEffect, useRef, useState } from 'react'
import type { KeyboardEvent, ReactNode } from 'react'
import { Clock, Cpu, Download, Globe, LoaderCircle, Plug, Power, RefreshCw, Server } from 'lucide-react'
import { PageFrame, Toggle } from '../components/page'
import { sendJson } from '../lib/api'
import type { Status } from '../lib/status'
import type { AppInfo, Settings } from '../lib/types'
import { bridge } from '../lib/types'
import { updateSummary } from '../lib/updates'
import { THEMES, validTheme } from '../lib/theme'
import type { Updates } from '../lib/updates'

function Section({ title, children }: { title: string; children: ReactNode }) {
  const id = `settings-${title.toLowerCase().replace(/\W+/g, '-')}`
  return <section className="settings-section" aria-labelledby={id}><h2 className="list-title" id={id}>{title}</h2><ul className="rows">{children}</ul></section>
}

/** The five themes as a radio group: arrow keys move and choose, like native radio buttons. */
function ThemePicker({ value, onChange }: { value: string; onChange: (id: string) => void }) {
  const refs = useRef<Array<HTMLButtonElement | null>>([])
  const current = THEMES.findIndex((theme) => theme.id === value)
  const onKey = (event: KeyboardEvent) => {
    const step = event.key === 'ArrowRight' || event.key === 'ArrowDown' ? 1 : event.key === 'ArrowLeft' || event.key === 'ArrowUp' ? -1 : 0
    if (!step) return
    event.preventDefault()
    const next = (current + step + THEMES.length) % THEMES.length
    onChange(THEMES[next].id)
    refs.current[next]?.focus()
  }
  return (
    <div className="theme-grid" role="radiogroup" aria-label="Theme" onKeyDown={onKey}>
      {THEMES.map((theme, index) => (
        <button key={theme.id} ref={(node) => { refs.current[index] = node }} type="button" role="radio" aria-checked={theme.id === value} tabIndex={theme.id === value ? 0 : -1}
          className={`theme-card${theme.id === value ? ' is-selected' : ''}`} onClick={() => onChange(theme.id)}>
          <span className="theme-card__preview" aria-hidden="true">{theme.swatches.map((colour, swatch) => <span key={swatch} style={{ background: colour }} />)}</span>
          <strong>{theme.name}</strong>
          <small>{theme.detail}</small>
        </button>
      ))}
    </div>
  )
}

function badge(ok: boolean, yes: string, no: string, off = false) {
  return <small className={`badge ${ok ? 'badge--ok' : off ? 'badge--off' : 'badge--warn'}`}>{ok ? yes : no}</small>
}

export function SettingsPage({ status, info, onOpen, updates, settings, patchSettings }: { status: Status; info: AppInfo | null; onOpen: (page: 'services' | 'setup') => void; updates: Updates; settings: Settings; patchSettings: (change: Partial<Settings>) => void }) {
  const update = updates.state
  const theme = validTheme(settings.theme)
  const [busy, setBusy] = useState('')
  const [message, setMessage] = useState('')
  const act = async (id: string, task: () => Promise<unknown>, done: string) => {
    setBusy(id); setMessage('')
    try { await task(); setMessage(done); await status.refreshState() } catch (actError) { setMessage(actError instanceof Error ? actError.message : 'That did not work.') } finally { setBusy('') }
  }
  const running = status.services.filter((service) => service.status === 'running').length
  const installed = status.services.filter((service) => service.available).length
  const loaded = status.state?.models.filter((model) => model.running && !model.embedding).length ?? 0
  const routerOn = status.state?.router_enabled !== false
  const nemoLabel = status.nemoChecking ? 'Checking' : status.nemo?.ready ? 'Ready' : status.nemo?.checked === false || !status.nemo ? 'Not checked' : 'Not ready'
  return (
    <PageFrame eyebrow="Settings" title="Settings" intro="How PockPock looks, runs and updates.">
      {message && <div className="banner" role="status"><span>{message}</span></div>}
      <section className="settings-section" aria-labelledby="settings-theme">
        <h2 className="list-title" id="settings-theme">Theme</h2>
        <ThemePicker value={theme} onChange={(id) => patchSettings({ theme: id })} />
      </section>
      <Section title="Smart Router">
        <li className="row">
          <RefreshCw size={16} className="row__icon" aria-hidden="true" />
          <div className="row__text"><strong>Smart Router {badge(routerOn, 'Running', 'Paused')}</strong><span>{routerOn ? 'Chooses a local model for each Chat and PockPock Agent request.' : 'Paused: Chat and PockPock Agent will not answer.'}</span></div>
          <Toggle checked={routerOn} busy={busy === 'router' || !status.state} label="Smart Router" onChange={(enabled) => void act('router', () => sendJson('/api/router', { enabled }, 'PUT'), enabled ? 'Router started.' : 'Router paused.')} />
        </li>
      </Section>
      <Section title="Ollama and services">
        <li className="row">
          <Cpu size={16} className="row__icon" aria-hidden="true" />
          <div className="row__text"><strong>Ollama {badge(Boolean(status.state?.connected), 'Connected', 'Not running')}</strong><span>{status.state?.connected ? `Models are served from here. ${loaded ? `${loaded} loaded now.` : 'None loaded now.'}` : status.state?.error || 'Start it from Services.'}</span></div>
        </li>
        <li className="row">
          <Server size={16} className="row__icon" aria-hidden="true" />
          <div className="row__text"><strong>Services</strong><span>{running} of {installed} installed services running · {status.backend.phase === 'ready' ? 'PockPock gateway ready' : status.backend.detail}</span></div>
          <button type="button" className="button" onClick={() => onOpen('services')}><Server size={13} /> Open Services</button>
        </li>
      </Section>
      <Section title="OpenClaw">
        <li className="row">
          <Plug size={16} className="row__icon" aria-hidden="true" />
          <div className="row__text"><strong>OpenClaw {badge(Boolean(status.claw?.ready), 'Ready', status.claw ? 'Not ready' : 'Checking', !status.claw)}</strong><span>{status.claw?.detail || 'Checking…'}{status.claw?.ready ? ` · default model ${status.claw.model?.replace('ollama/', '')}` : ''}</span></div>
          <button type="button" className="button" onClick={() => void status.refreshClaw(true)}><RefreshCw size={13} /> Check</button>
        </li>
        <OpenClawBrowserRow onMessage={setMessage} />
        <OpenClawSlowModelsRow onMessage={setMessage} />
      </Section>
      <Section title="NemoClaw">
        <li className="row">
          <Plug size={16} className="row__icon" aria-hidden="true" />
          <div className="row__text"><strong>NemoClaw sandbox check {badge(Boolean(status.nemo?.ready), 'Ready', nemoLabel, true)}</strong><span>{status.nemoChecking ? 'Checking the sandbox (this loads its model)…' : status.nemo?.detail || 'Confirms the isolated sandbox is ready. The check loads its model.'}</span></div>
          <button type="button" className="button" disabled={status.nemoChecking} onClick={() => void status.refreshNemo(true, true)}>{status.nemoChecking ? <LoaderCircle size={13} className="spin" /> : <RefreshCw size={13} />} Check</button>
        </li>
      </Section>
      <Section title="Updates">
        {update?.status === 'ready' && (
          <li className="row row--highlight">
            <Download size={16} className="row__icon" aria-hidden="true" />
            <div className="row__text"><strong>PockPock {update.version} is ready</strong><span>You are on {info?.version ?? 'an older version'}. Restarting installs it; your tasks and settings are kept.</span></div>
            <button type="button" className="button button--primary" onClick={() => void updates.install()}><RefreshCw size={13} /> Restart to update</button>
          </li>
        )}
        <li className="row">
          <Download size={16} className="row__icon" aria-hidden="true" />
          <div className="row__text"><strong>Updates</strong><span>{updateSummary(update)}</span>
            {update?.status === 'downloading' && <span className="progress" role="progressbar" aria-label="Download progress" aria-valuemin={0} aria-valuemax={100} aria-valuenow={Math.round(update.progress * 100)}><span style={{ width: `${Math.round(update.progress * 100)}%` }} /></span>}
          </div>
          {update?.status === 'available' && <button type="button" className="button button--primary" onClick={() => void updates.download()}><Download size={13} /> {update.canInstall ? 'Download update' : 'Open download page'}</button>}
          {update && !['ready', 'available', 'downloading', 'unsupported'].includes(update.status) && <button type="button" className="button" disabled={update.status === 'checking'} onClick={() => void updates.check()}>{update.status === 'checking' ? <LoaderCircle size={13} className="spin" /> : <RefreshCw size={13} />} Check for updates</button>}
        </li>
        {update?.canInstall && update.status !== 'unsupported' && (
          <li className="row">
            <Download size={16} className="row__icon" aria-hidden="true" />
            <div className="row__text"><strong>Download updates automatically</strong><span>New versions download in the background and install when PockPock restarts. Your tasks and settings are kept.</span></div>
            <Toggle checked={settings.updates?.autoDownload !== false} label="Download updates automatically" onChange={(autoDownload) => patchSettings({ updates: { ...settings.updates, autoDownload } })} />
          </li>
        )}
      </Section>
      <Section title="Setup">
        <li className="row">
          <Power size={16} className="row__icon" aria-hidden="true" />
          <div className="row__text"><strong>Setup</strong><span>Install missing components, repair them, or add OpenClaw and NemoClaw later.</span></div>
          <button type="button" className="button" onClick={() => onOpen('setup')}>Run setup</button>
        </li>
      </Section>
      {info && <p className="note">PockPock Agent {info.version} · Electron {info.electron} · backend {info.backendRoot} · Python {info.python}</p>}
    </PageFrame>
  )
}

/** How long OpenClaw waits for a slow local model. Without a provider timeout it stops after 300 s. */
function OpenClawSlowModelsRow({ onMessage }: { onMessage: (text: string) => void }) {
  const desktop = bridge()
  const [state, setState] = useState<{ seconds: number | null; recommended: number } | null>(null)
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  const clean = (reason: unknown, fallback: string) => reason instanceof Error ? reason.message.replace(/^Error invoking remote method '[^']+': (Error: )?/, '') : fallback
  useEffect(() => {
    if (!desktop) return
    desktop.openclaw.slowModels().then(setState, (reason: unknown) => setError(clean(reason, 'OpenClaw is not available.')))
  }, [desktop])
  const allow = async () => {
    if (!desktop) return
    setBusy(true)
    try {
      setState(await desktop.openclaw.allowSlowModels())
      onMessage('OpenClaw now waits up to 30 minutes for a local model. Its gateway restarted.')
    } catch (reason) { onMessage(clean(reason, 'The setting could not be changed.')) } finally { setBusy(false) }
  }
  const enough = state && state.seconds !== null && state.seconds >= state.recommended
  return (
    <li className="row">
      <Clock size={16} className="row__icon" />
      <div className="row__text"><strong>Slow local models in OpenClaw</strong>
        <span>{error || (!state ? 'Checking…' : enough
          ? `OpenClaw waits up to ${Math.round((state.seconds ?? 0) / 60)} minutes for a local model.`
          : 'OpenClaw stops waiting for a local model after 5 minutes, which a small model on a computer without a graphics card can need just to read its instructions. Allowing more time restarts the OpenClaw gateway and stops any running OpenClaw chat.')}</span></div>
      {state && !enough && <button type="button" className="button" disabled={busy} onClick={() => void allow()}>{busy && <LoaderCircle size={13} className="spin" />}Allow slow models</button>}
    </li>
  )
}

/** Which browser OpenClaw drives: its default, or an installed Chromium browser such as Brave. */
function OpenClawBrowserRow({ onMessage }: { onMessage: (text: string) => void }) {
  const desktop = bridge()
  const [state, setState] = useState<{ available: Array<{ id: string; name: string }>; current: string } | null>(null)
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  useEffect(() => {
    if (!desktop) return
    desktop.openclaw.browsers().then(setState, (reason: unknown) => setError(reason instanceof Error ? reason.message.replace(/^Error invoking remote method '[^']+': (Error: )?/, '') : 'OpenClaw is not available.'))
  }, [desktop])
  const choose = async (id: string) => {
    if (!desktop || !state) return
    setBusy(true)
    try {
      await desktop.openclaw.setBrowser(id)
      setState({ ...state, current: id })
      onMessage(id === 'default' ? 'OpenClaw uses its default browser again.' : `OpenClaw now uses ${state.available.find((browser) => browser.id === id)?.name}. Its browser restarts at the next browser action.`)
    } catch (reason) {
      onMessage(reason instanceof Error ? reason.message.replace(/^Error invoking remote method '[^']+': (Error: )?/, '') : 'The browser could not be changed.')
    } finally { setBusy(false) }
  }
  return (
    <li className="row">
      <Globe size={16} className="row__icon" />
      <div className="row__text"><strong id="claw-browser-label">OpenClaw browser</strong>
        <span>{error || (state ? 'The browser OpenClaw opens and controls for web tasks. Any installed Chromium browser works, such as Brave for its ad blocking.' : 'Checking installed browsers…')}</span></div>
      {state && (
        <select className="input input--inline" aria-labelledby="claw-browser-label" value={state.current === 'custom' ? 'default' : state.current} disabled={busy} onChange={(event) => void choose(event.target.value)}>
          <option value="default">OpenClaw default</option>
          {state.available.map((browser) => <option key={browser.id} value={browser.id}>{browser.name}</option>)}
        </select>
      )}
    </li>
  )
}
