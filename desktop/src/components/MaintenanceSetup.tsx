// Maintenance Manager setup: 1) choose the AI, 2) connect GitHub, 3) allow a copy of PockPock to be
// cloned to a folder. Each step is an explicit choice; nothing is cloned or sent before the user acts.
import { useCallback, useEffect, useState } from 'react'
import { Check, ExternalLink, FolderOpen, GitBranch, LoaderCircle, RotateCcw, Sparkles } from 'lucide-react'
import { bridge } from '../lib/types'
import type { GitHubAccount, MaintenanceAgent, MaintenanceStatus } from '../lib/types'

const clean = (reason: unknown, fallback: string) => (reason instanceof Error ? reason.message.replace(/^Error invoking remote method '[^']+': (Error: )?/, '') : fallback)
const UPSTREAM = 'PockPock9/PockPockAgent'

export function MaintenanceSetup({ status, onChange }: { status: MaintenanceStatus; onChange: () => void }) {
  const desktop = bridge()
  const [editing, setEditing] = useState(!status.ready)
  const [agents, setAgents] = useState<MaintenanceAgent[] | null>(null)
  const [choice, setChoice] = useState<{ id: MaintenanceAgent['id']; model: string } | null>(status.agent ? { id: status.agent.id, model: status.agent.model } : null)
  const [github, setGithub] = useState<GitHubAccount | null>(null)
  const [deviceCode, setDeviceCode] = useState<{ code: string; url: string } | null>(null)
  const [signingIn, setSigningIn] = useState(false)
  const [folder, setFolder] = useState(status.repo?.dir || status.defaultFolder)
  const [cloneLog, setCloneLog] = useState<string[]>([])
  const [cloning, setCloning] = useState(false)
  const [error, setError] = useState('')

  const refresh = useCallback(() => {
    if (!desktop) return
    void desktop.maintenance.agents().then((list) => {
      setAgents(list)
      setChoice((current) => current ?? (() => { const local = list.find((agent) => agent.id === 'local'); return local?.installed ? { id: 'local', model: local.suggested || '' } : null })())
    })
    void desktop.maintenance.github().then(setGithub)
  }, [desktop])
  useEffect(() => { if (editing) refresh() }, [editing, refresh])
  useEffect(() => desktop?.maintenance.onEvent((event) => {
    if (event.type === 'github-code') setDeviceCode({ code: event.code, url: event.url })
    if (event.type === 'clone-log') setCloneLog((lines) => [...lines.slice(-30), event.line])
  }), [desktop])

  const agentChosen = Boolean(status.agent)
  const githubReady = Boolean(github?.loggedIn)

  const saveAgent = async () => {
    if (!desktop || !choice) return
    setError('')
    try { await desktop.maintenance.setAgent(choice); onChange() } catch (reason) { setError(clean(reason, 'The AI could not be saved.')) }
  }
  const signIn = async () => {
    if (!desktop) return
    setSigningIn(true); setError(''); setDeviceCode(null)
    try { setGithub(await desktop.maintenance.githubLogin()) } catch (reason) { setError(clean(reason, 'GitHub sign-in did not finish.')) } finally { setSigningIn(false); setDeviceCode(null) }
  }
  const chooseFolder = async () => {
    const picked = await desktop?.maintenance.chooseFolder(folder)
    if (picked) setFolder(picked)
  }
  const clone = async () => {
    if (!desktop) return
    setCloning(true); setError(''); setCloneLog([])
    try { await desktop.maintenance.clone(folder); onChange(); setEditing(false) } catch (reason) { setError(clean(reason, 'Cloning failed.')) } finally { setCloning(false) }
  }
  const chosenAgent = agents?.find((agent) => agent.id === status.agent?.id)

  if (!editing && status.ready) {
    return (
      <section className="card maint-summary" aria-labelledby="maint-title">
        <header><Sparkles size={15} /><strong id="maint-title">Maintenance Manager is set up</strong></header>
        <dl className="setup-facts">
          <div><dt>AI</dt><dd>{status.agent?.id === 'local' ? `Local model ${status.agent.model}` : chosenAgent?.name ?? status.agent?.id}</dd></div>
          <div><dt>Copy of PockPock</dt><dd><code>{status.repo?.dir}</code>{status.repo?.fork ? ` (your fork of ${UPSTREAM})` : ''}</dd></div>
        </dl>
        <div className="card__actions">
          <button type="button" className="button" onClick={() => void desktop?.openPath(status.repo?.dir ?? '')}><FolderOpen size={13} /> Open folder</button>
          <button type="button" className="button" onClick={() => setEditing(true)}>Change setup</button>
        </div>
      </section>
    )
  }

  return (
    <section className="card maint-setup" aria-labelledby="maint-setup-title">
      <header><Sparkles size={15} /><strong id="maint-setup-title">Set up the Maintenance Manager</strong></header>
      <p className="note">The Maintenance Manager works through your reports: it finds the cause in a copy of the PockPock code, writes a fix with a documentation update, runs the checks, and shows you the change. A pull request is opened only after you approve it, as a draft for the project owner to review.</p>
      {error && <div className="banner banner--error" role="alert"><span>{error}</span></div>}
      <ol className="maint-steps">
        <li className={agentChosen ? 'is-done' : 'is-current'}>
          <h3><span className="maint-steps__n">{agentChosen ? <Check size={13} /> : 1}</span> Choose the AI</h3>
          {!agents ? <p className="note"><LoaderCircle size={13} className="spin" /> Looking for installed AI tools…</p> : (
            <fieldset className="report-categories">
              <legend className="visually-hidden">AI for maintenance</legend>
              {agents.map((agent) => (
                <label key={agent.id} className={`${choice?.id === agent.id ? 'is-chosen' : ''}${agent.installed ? '' : ' is-disabled'}`}>
                  <input type="radio" name="maint-agent" value={agent.id} disabled={!agent.installed} checked={choice?.id === agent.id}
                    onChange={() => setChoice({ id: agent.id, model: agent.id === 'local' ? (choice?.model || agent.suggested || '') : '' })} />
                  <span>
                    <strong>{agent.name}{agent.installed ? <small className="badge badge--ok">{agent.version || 'Ready'}</small> : <small className="badge badge--off">Not installed</small>}</strong>
                    <em>{agent.installed ? agent.dataNotice : agent.install}</em>
                    {agent.id === 'local' && agent.installed && choice?.id === 'local' && (
                      <select className="input input--inline" aria-label="Local model" value={choice.model} onChange={(event) => setChoice({ id: 'local', model: event.target.value })}>
                        {agent.models?.map((model) => <option key={model} value={model}>{model}{model === agent.suggested ? ' (suggested)' : ''}</option>)}
                      </select>
                    )}
                  </span>
                </label>
              ))}
            </fieldset>
          )}
          <div className="card__actions">
            <button type="button" className="button button--primary" disabled={!choice || (choice.id === 'local' && !choice.model)} onClick={() => void saveAgent()}>{agentChosen ? 'Save choice' : 'Use this AI'}</button>
          </div>
        </li>

        <li className={!agentChosen ? 'is-locked' : githubReady ? 'is-done' : 'is-current'} aria-disabled={!agentChosen}>
          <h3><span className="maint-steps__n">{githubReady && agentChosen ? <Check size={13} /> : 2}</span> Connect GitHub</h3>
          {!agentChosen ? <p className="note">Choose the AI first.</p> : !github ? <p className="note"><LoaderCircle size={13} className="spin" /> Checking GitHub…</p> : !github.installed ? (
            <p className="note">{github.install} Then press <strong>Check again</strong>.</p>
          ) : github.loggedIn ? (
            <p className="note">Connected as <strong>{github.login}</strong>. {github.canPush ? `Fixes will be pushed to ${UPSTREAM} as draft pull requests.` : `You cannot push to ${UPSTREAM}, so fixes will come from your own fork.`}</p>
          ) : (
            <>
              <p className="note">PockPock signs in through the GitHub CLI. GitHub asks you to confirm in your browser.</p>
              {deviceCode && (
                <div className="maint-code" role="status">
                  <span>Enter this code on GitHub:</span> <code>{deviceCode.code}</code>
                  <button type="button" className="button" onClick={() => void desktop?.openExternal(deviceCode.url)}><ExternalLink size={13} /> Open github.com/login/device</button>
                </div>
              )}
            </>
          )}
          {agentChosen && (
            <div className="card__actions">
              {github?.installed && !github.loggedIn && <button type="button" className="button button--primary" disabled={signingIn} onClick={() => void signIn()}>{signingIn ? <LoaderCircle size={13} className="spin" /> : <GitBranch size={13} />} {signingIn ? 'Waiting for GitHub…' : 'Connect GitHub'}</button>}
              {signingIn && <button type="button" className="button" onClick={() => void desktop?.maintenance.cancelLogin()}>Cancel</button>}
              <button type="button" className="button" onClick={refresh}><RotateCcw size={13} /> Check again</button>
            </div>
          )}
        </li>

        <li className={!agentChosen || !githubReady ? 'is-locked' : status.repo?.present ? 'is-done' : 'is-current'} aria-disabled={!agentChosen || !githubReady}>
          <h3><span className="maint-steps__n">{status.repo?.present ? <Check size={13} /> : 3}</span> Copy of PockPock</h3>
          {!agentChosen || !githubReady ? <p className="note">Connect GitHub first.</p> : (
            <>
              <p className="note">The Maintenance Manager needs its own copy of the PockPock code ({github?.canPush ? UPSTREAM : `a fork of ${UPSTREAM} in your account`}). It downloads about 25 MB from GitHub into this folder. Fixes are made in separate working copies inside it, so your other files are never touched.</p>
              <div className="maint-folder">
                <code>{folder}</code>
                <button type="button" className="button" onClick={() => void chooseFolder()} disabled={cloning}>Change…</button>
              </div>
              {cloneLog.length > 0 && <pre className="setup-log" aria-live="polite">{cloneLog.join('\n')}</pre>}
              <div className="card__actions">
                <button type="button" className="button button--primary" disabled={cloning} onClick={() => void clone()}>{cloning ? <LoaderCircle size={13} className="spin" /> : <Check size={13} />} {status.repo?.present && status.repo.dir === folder ? 'Use this copy' : 'Allow and clone'}</button>
                {status.ready && <button type="button" className="button" onClick={() => setEditing(false)}>Done</button>}
              </div>
            </>
          )}
        </li>
      </ol>
    </section>
  )
}
