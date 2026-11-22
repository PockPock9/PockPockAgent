// Start, stop and inspect every local service, all at once or one by one.
import { useState } from 'react'
import { FileText, FolderOpen, LoaderCircle, Play, RotateCcw, Square, X } from 'lucide-react'
import { Dot } from '../components/ui'
import { PageFrame, Toggle } from '../components/page'
import type { Status } from '../lib/status'
import { bridge } from '../lib/types'
import type { ServiceState, Settings } from '../lib/types'
import { isMac } from '../lib/platform'

const TONE: Record<ServiceState['status'], 'ok' | 'warn' | 'off' | 'busy'> = {
  running: 'ok', starting: 'busy', stopping: 'busy', checking: 'busy', stopped: 'off', unavailable: 'off', error: 'warn',
}
const LABEL: Record<ServiceState['status'], string> = {
  running: 'Running', starting: 'Starting', stopping: 'Stopping', checking: 'Checking', stopped: 'Stopped', unavailable: 'Not installed', error: 'Problem',
}


export function ServicesPage({ status, settings, patchSettings, loginItem, setLoginItem }: {
  status: Status
  settings: Settings
  patchSettings: (change: Partial<Settings>) => void
  loginItem: boolean
  setLoginItem: (enabled: boolean) => void
}) {
  const desktop = bridge()
  const [busy, setBusy] = useState('')
  const [error, setError] = useState('')
  const [log, setLog] = useState<{ id: string; name: string; file: string; text: string } | null>(null)
  const services = status.services
  const groups = [...new Set(services.map((service) => service.group))]
  const running = services.filter((service) => service.status === 'running').length
  const installed = services.filter((service) => service.available).length
  const serviceSettings = settings.services ?? {}

  const act = async (id: string, action: 'start' | 'stop' | 'restart') => {
    if (!desktop) return
    setBusy(`${action}:${id}`)
    setError('')
    try { await desktop.services[action](id) } catch (actionError) { setError(actionError instanceof Error ? actionError.message.replace(/^Error invoking remote method '[^']+': (Error: )?/, '') : 'That did not work.') } finally { setBusy('') }
  }
  const showLog = async (service: ServiceState) => {
    if (!desktop) return
    const result = await desktop.services.logs(service.id)
    setLog({ id: service.id, name: service.name, ...result })
  }

  if (!desktop) return <PageFrame eyebrow="Workshop · System" title="Services" intro="Everything PockPock runs on this PC."><p className="note">Services are managed by the desktop app.</p></PageFrame>
  return (
    <PageFrame eyebrow="Workshop · System" title="Services" intro="Everything PockPock runs on this PC. They start with the app; start, stop or restart any of them here." actions={<>
            <button type="button" className="button button--primary" disabled={Boolean(busy)} onClick={() => void act('all', 'start')}>{busy === 'start:all' ? <LoaderCircle size={13} className="spin" /> : <Play size={13} />} Start all</button>
            <button type="button" className="button" disabled={Boolean(busy)} onClick={() => { if (window.confirm('Stop every running PockPock service, including ones started outside this app?')) void act('all', 'stop') }}>{busy === 'stop:all' ? <LoaderCircle size={13} className="spin" /> : <Square size={12} />} Stop all</button>
          </>}>
        <p className="note"><Dot tone={running === installed && installed ? 'ok' : running ? 'warn' : 'off'} /> {running} of {installed} installed services running</p>
        {error && <div className="banner banner--error" role="alert"><span>{error}</span><button type="button" className="icon-button icon-button--small" onClick={() => setError('')} aria-label="Dismiss"><X size={13} /></button></div>}
        {!services.length && <p className="note"><LoaderCircle size={13} className="spin" /> Checking services…</p>}
        {groups.map((group) => (
          <section key={group}>
            <h2 className="list-title">{group}</h2>
            <ul className="rows">
              {services.filter((service) => service.group === group).map((service) => {
                const working = service.status === 'starting' || service.status === 'stopping' || busy.endsWith(`:${service.id}`)
                return (
                  <li key={service.id} className="row service-row">
                    <Dot tone={TONE[service.status]} />
                    <div className="row__text">
                      <strong>{service.name} <small className={`badge badge--${TONE[service.status]}`}>{LABEL[service.status]}</small></strong>
                      <span>{service.description} · port {service.port}</span>
                      {service.status !== 'running' && service.detail && <p className={service.status === 'error' ? 'row__error' : ''}>{service.detail}</p>}
                      {service.status === 'running' && <p>{service.detail}</p>}
                    </div>
                    <div className="row__actions">
                      {service.status === 'running'
                        ? <>
                          <button type="button" className="icon-button" aria-label={`Restart ${service.name}`} title="Restart" disabled={working} onClick={() => void act(service.id, 'restart')}><RotateCcw size={14} /></button>
                          <button type="button" className="button" disabled={working} onClick={() => void act(service.id, 'stop')}>{working ? <LoaderCircle size={13} className="spin" /> : <Square size={11} />} Stop</button>
                        </>
                        : <button type="button" className="button" disabled={working || !service.available} onClick={() => void act(service.id, 'start')}>{working ? <LoaderCircle size={13} className="spin" /> : <Play size={12} />} Start</button>}
                      <button type="button" className="icon-button" aria-label={`Show ${service.name} log`} title="Log" onClick={() => void showLog(service)}><FileText size={14} /></button>
                    </div>
                  </li>
                )
              })}
            </ul>
          </section>
        ))}

        {log && (
          <section className="log-view" aria-label={`${log.name} log`}>
            <header><strong>{log.name} log</strong><code>{log.file}</code><button type="button" className="icon-button icon-button--small" onClick={() => void showLog(services.find((item) => item.id === log.id)!)} aria-label="Reload log"><RotateCcw size={13} /></button><button type="button" className="icon-button icon-button--small" onClick={() => setLog(null)} aria-label="Close log"><X size={13} /></button></header>
            <pre>{log.text}</pre>
          </section>
        )}

        <h2 className="list-title">Startup</h2>
        <ul className="rows">
          <li className="row">
            <div className="row__text"><strong>Start services when the app opens</strong><span>Starts Ollama, the backend, OpenClaw and (if switched on below) NemoClaw. Models load only when a message needs them.</span></div>
            <Toggle checked={serviceSettings.autoStart !== false} label="Start services when the app opens" onChange={(next) => patchSettings({ services: { ...serviceSettings, autoStart: next } })} />
          </li>
          <li className="row">
            <div className="row__text"><strong>Include NemoClaw</strong><span>Also starts Docker Desktop and the NemoClaw sandbox. Uses about 2 GB of memory while running.</span></div>
            <Toggle checked={serviceSettings.nemoclaw !== false} label="Include NemoClaw" onChange={(next) => patchSettings({ services: { ...serviceSettings, nemoclaw: next } })} />
          </li>
          <li className="row">
            <div className="row__text"><strong>Stop services when the app closes</strong><span>Only services this app started. Turn off to keep agents reachable after closing the window.</span></div>
            <Toggle checked={serviceSettings.stopOnQuit !== false} label="Stop services when the app closes" onChange={(next) => patchSettings({ services: { ...serviceSettings, stopOnQuit: next } })} />
          </li>
          <li className="row">
            <div className="row__text"><strong>Open PockPock Agent when I sign in</strong><span>Starts the app (and its services) after you sign in{isMac ? ' to your Mac' : ' to Windows'}.</span></div>
            <Toggle checked={loginItem} label="Open PockPock Agent when I sign in" onChange={setLoginItem} />
          </li>
        </ul>
        <p className="note"><button type="button" className="link-button" onClick={() => void desktop.services.openLogs()}><FolderOpen size={13} /> Open the logs folder</button></p>
    </PageFrame>
  )
}
