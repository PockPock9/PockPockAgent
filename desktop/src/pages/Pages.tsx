// Settings. (The Workshop pages each have their own file; the shared page pieces are in components/page.tsx.)
import { useEffect, useState } from 'react'
import { ChevronDown, Clock, Download, Globe, LoaderCircle, Palette, Plug, Power, RefreshCw, Server } from 'lucide-react'
import { MenuItem, Popover } from '../components/ui'
import { PageFrame, Toggle } from '../components/page'
import { sendJson } from '../lib/api'
import type { Status } from '../lib/status'
import type { AppInfo, Settings } from '../lib/types'
import { bridge } from '../lib/types'
import { updateSummary } from '../lib/updates'
import { THEMES, validTheme } from '../lib/theme'
import type { Updates } from '../lib/updates'

export function SettingsPage({ status, info, onOpen, updates, settings, patchSettings }: { status: Status; info: AppInfo | null; onOpen: (page: 'services' | 'setup') => void; updates: Updates; settings: Settings; patchSettings: (change: Partial<Settings>) => void }) {
  const update = updates.state
  const [themeOpen, setThemeOpen] = useState(false)
  const theme = THEMES.find((item) => item.id === validTheme(settings.theme)) ?? THEMES[0]
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
          <Palette size={16} className="row__icon" />
          <div className="row__text"><strong id="theme-label">Theme</strong><span>{theme.detail}</span></div>
          <div className="anchor">
            <button type="button" className="button theme-button" aria-haspopup="menu" aria-expanded={themeOpen} aria-labelledby="theme-label theme-current" data-popover-toggle={themeOpen ? 'open' : undefined} onClick={() => setThemeOpen((value) => !value)}>
              <Swatches colours={theme.swatches} /> <span id="theme-current">{theme.name}</span> <ChevronDown size={12} />
            </button>
            <Popover open={themeOpen} onClose={() => setThemeOpen(false)} align="right" className="popover--wide popover--down">
              <div className="popover__label">Theme</div>
              {THEMES.map((item) => (
                <MenuItem key={item.id} icon={<Swatches colours={item.swatches} />} title={item.name} detail={item.detail} selected={item.id === theme.id}
                  onSelect={() => { patchSettings({ theme: item.id }); setThemeOpen(false) }} />
              ))}
            </Popover>
          </div>
        </li>
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
        <OpenClawBrowserRow onMessage={setMessage} />
        <OpenClawSlowModelsRow onMessage={setMessage} />
        <li className="row">
          <Plug size={16} className="row__icon" />
          <div className="row__text"><strong>NemoClaw sandbox check</strong><span>{status.nemoChecking ? 'Checking the sandbox (this loads its model)…' : status.nemo?.detail || 'Not checked'}</span></div>
          <button type="button" className="button" disabled={status.nemoChecking} onClick={() => void status.refreshNemo(true, true)}>{status.nemoChecking ? <LoaderCircle size={13} className="spin" /> : <RefreshCw size={13} />} Check sandbox</button>
        </li>
        <li className="row">
          <Download size={16} className="row__icon" />
          <div className="row__text"><strong>Updates</strong><span>{updateSummary(update)}</span>
            {update?.status === 'downloading' && <span className="progress" aria-label="Download progress"><span style={{ width: `${Math.round(update.progress * 100)}%` }} /></span>}
          </div>
          {update?.status === 'ready' && <button type="button" className="button button--primary" onClick={() => void updates.install()}><RefreshCw size={13} /> Restart to update</button>}
          {update?.status === 'available' && <button type="button" className="button button--primary" onClick={() => void updates.download()}><Download size={13} /> {update.canInstall ? 'Download update' : 'Open download page'}</button>}
          {update && !['ready', 'available', 'downloading', 'unsupported'].includes(update.status) && <button type="button" className="button" disabled={update.status === 'checking'} onClick={() => void updates.check()}>{update.status === 'checking' ? <LoaderCircle size={13} className="spin" /> : <RefreshCw size={13} />} Check for updates</button>}
        </li>
        {update?.canInstall && update.status !== 'unsupported' && (
          <li className="row">
            <Download size={16} className="row__icon" />
            <div className="row__text"><strong>Download updates automatically</strong><span>New versions download in the background and install when PockPock restarts. Your chats and settings are kept.</span></div>
            <Toggle checked={settings.updates?.autoDownload !== false} label="Download updates automatically" onChange={(autoDownload) => patchSettings({ updates: { ...settings.updates, autoDownload } })} />
          </li>
        )}
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

/** A small preview of a theme: canvas, panel, accent and text colours. Decorative: the name is next to it. */
function Swatches({ colours }: { colours: string[] }) {
  return <span className="swatches" aria-hidden="true">{colours.map((colour, index) => <span key={index} style={{ background: colour }} />)}</span>
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
