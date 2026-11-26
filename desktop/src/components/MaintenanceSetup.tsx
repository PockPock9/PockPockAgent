// Maintenance Manager setup: 1) choose the AI, 2) connect GitHub, 3) allow a copy of PockPock to be
// cloned to a folder. Each step is an explicit choice; nothing is cloned or sent before the user acts.
// PockPock itself (a local model) is the default AI. Connecting a Claude, OpenAI or Copilot account is
// optional: a tool that is only signed in on this PC is not used until the user connects it here.
import { useCallback, useEffect, useState } from 'react'
import { AlertTriangle, Check, ExternalLink, FolderOpen, GitBranch, HeartHandshake, LoaderCircle, Plug, RotateCcw, Sparkles, Unplug } from 'lucide-react'
import { bridge } from '../lib/types'
import type { GitHubAccount, MaintenanceAgent, MaintenanceStatus } from '../lib/types'

const clean = (reason: unknown, fallback: string) => (reason instanceof Error ? reason.message.replace(/^Error invoking remote method '[^']+': (Error: )?/, '') : fallback)
const UPSTREAM = 'PockPock9/PockPockAgent'

export function MaintenanceSetup({ status, onChange }: { status: MaintenanceStatus; onChange: () => void }) {
  const desktop = bridge()
  const [editing, setEditing] = useState(!status.ready)
  const [agents, setAgents] = useState<MaintenanceAgent[] | null>(null)
  const initial = status.chosen ?? status.agent
  const [choice, setChoice] = useState<{ id: MaintenanceAgent['id']; model: string; openclaw?: boolean } | null>(initial ? { id: initial.id, model: initial.model, openclaw: initial.openclaw === true } : null)
  const [github, setGithub] = useState<GitHubAccount | null>(null)
  const [deviceCode, setDeviceCode] = useState<{ code: string; url: string } | null>(null)
  const [signingIn, setSigningIn] = useState(false)
  const [folder, setFolder] = useState(status.repo?.dir || status.defaultFolder)
  const [cloneLog, setCloneLog] = useState<string[]>([])
  const [cloning, setCloning] = useState(false)
  const [error, setError] = useState('')
  // Saving the AI choice: shown next to its button, since the dialog's top banner is usually out of view there.
  const [agentSave, setAgentSave] = useState<{ phase: 'idle' | 'saving' | 'saved' | 'error'; text: string }>({ phase: 'idle', text: '' })
  // Connect (install and sign in) for a cloud AI: which one is running, its progress lines and sign-in page.
  const [confirming, setConfirming] = useState<MaintenanceAgent['id'] | null>(null)
  const [connecting, setConnecting] = useState<MaintenanceAgent['id'] | null>(null)
  const [connectLog, setConnectLog] = useState<{ id: MaintenanceAgent['id']; lines: string[]; url: string; error: string } | null>(null)

  const refresh = useCallback(() => {
    if (!desktop) return
    void desktop.maintenance.agents().then((list) => {
      setAgents(list)
      // PockPock itself is the default; a chosen account that is not connected here is not kept.
      setChoice((current) => {
        const usable = current && list.find((agent) => agent.id === current.id && (agent.id === 'local' ? agent.installed : agent.connected))
        if (usable) return current
        const local = list.find((agent) => agent.id === 'local')
        return local?.installed ? { id: 'local', model: local.suggested || '' } : null
      })
    })
    void desktop.maintenance.github().then(setGithub)
  }, [desktop])
  useEffect(() => { if (editing) refresh() }, [editing, refresh])
  useEffect(() => desktop?.maintenance.onEvent((event) => {
    if (event.type === 'github-code') setDeviceCode({ code: event.code, url: event.url })
    if (event.type === 'clone-log') setCloneLog((lines) => [...lines.slice(-30), event.line])
    if (event.type === 'agent-log') setConnectLog((log) => (log?.id === event.id ? { ...log, lines: [...log.lines.slice(-30), event.line] } : log))
    if (event.type === 'agent-url') setConnectLog((log) => (log?.id === event.id ? { ...log, url: event.url } : log))
  }), [desktop])

  // Usable: PockPock itself when Ollama has a model; an account only after Connect here.
  const ready = (agent: MaintenanceAgent) => (agent.id === 'local' ? agent.installed : agent.canConnect ? agent.connected === true : agent.installed && agent.signedIn !== false)
  const accountText = (agent: MaintenanceAgent) => [agent.account?.email, agent.account?.plan].filter(Boolean).join(', ')
  const disconnect = async (agent: MaintenanceAgent) => {
    if (!desktop) return
    setError('')
    try {
      setAgents(await desktop.maintenance.disconnectAgent(agent.id))
      setChoice((current) => (current?.id === agent.id ? null : current))
      onChange()
      refresh()
    } catch (reason) { setError(clean(reason, `${agent.name} could not be disconnected.`)) }
  }
  const connect = async (agent: MaintenanceAgent, useSignedIn = false) => {
    if (!desktop) return
    // An account already signed in on this PC (for example Claude Code from an editor) is used only
    // after the user confirms it; the main process refuses it otherwise.
    if (!useSignedIn && agent.installed && agent.signedIn) { setConfirming(agent.id); return }
    setConfirming(null); setConnecting(agent.id); setError(''); setConnectLog({ id: agent.id, lines: [], url: '', error: '' })
    try {
      const list = await desktop.maintenance.connectAgent(agent.id, { useSignedIn })
      setAgents(list)
      setConnectLog(null)
      if (list.find((item) => item.id === agent.id && ready(item))) setChoice({ id: agent.id, model: '' })
    } catch (reason) {
      const message = clean(reason, `${agent.name} could not be connected.`)
      // Installed just now and found already signed in: ask, as for an account signed in before.
      if (/already signed in on this PC/.test(message)) { setConnectLog(null); setConfirming(agent.id) }
      else setConnectLog((log) => (log ? { ...log, error: message } : log))
      void desktop.maintenance.agents().then(setAgents)
    } finally { setConnecting(null) }
  }

  // Step 1 is done once the user chose an AI here; until then PockPock itself would be used.
  const agentChosen = Boolean(status.chosen ?? status.agent)
  const githubReady = Boolean(github?.loggedIn)

  // The saved choice matches what is selected: the button shows Saved instead of asking to save again.
  const saved = status.chosen ?? status.agent
  const unchanged = Boolean(saved && choice && saved.id === choice.id && (choice.id !== 'local' || (saved.model === choice.model && Boolean(saved.openclaw) === Boolean(choice.openclaw))))
  useEffect(() => { setAgentSave((current) => (current.phase === 'saving' ? current : { phase: 'idle', text: '' })) }, [choice?.id, choice?.model, choice?.openclaw])
  const saveAgent = async () => {
    if (!desktop || !choice) return
    setError(''); setAgentSave({ phase: 'saving', text: '' })
    try {
      await desktop.maintenance.setAgent(choice)
      const name = agents?.find((agent) => agent.id === choice.id)?.name ?? choice.id
      setAgentSave({ phase: 'saved', text: choice.id === 'local' ? `Saved. PockPock itself fixes your reports with ${choice.model}${choice.openclaw ? ', through OpenClaw' : ''}.` : `Saved. ${name} fixes your reports from now on.` })
      onChange()
    } catch (reason) { setAgentSave({ phase: 'error', text: clean(reason, 'The AI could not be saved.') }) }
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
  const fallbackNote = status.fallback ? <div className="banner banner--warn" role="status"><AlertTriangle size={14} aria-hidden="true" /><span>{status.fallback} To use the account, connect it in <strong>Change setup</strong>; otherwise nothing needs doing.</span></div> : null

  if (!editing && status.ready) {
    return (
      <section className="card maint-summary" aria-labelledby="maint-title">
        <header><Sparkles size={15} /><strong id="maint-title">Maintenance Manager is set up</strong></header>
        {fallbackNote}
        <dl className="setup-facts">
          <div><dt>AI</dt><dd>{status.agent?.id === 'local' ? `PockPock itself, with ${status.agent.model}${status.agent.openclaw ? ', running commands through OpenClaw' : ' (reads and edits files only)'}` : `${chosenAgent?.name ?? status.agent?.id}, with your account${chosenAgent && accountText(chosenAgent) ? ` (${accountText(chosenAgent)})` : ''}`}</dd></div>
          <div><dt>Copy of PockPock</dt><dd><code>{status.repo?.dir}</code>{status.repo?.fork ? ` (your fork of ${UPSTREAM})` : ''}</dd></div>
        </dl>
        <div className="row maint-auto">
          <div className="row__text"><strong id="maint-auto-label">Keep fixing reports automatically</strong><span>PockPock works through open reports one at a time in the background. Each fix waits for your approval before a pull request is opened; a report whose fix failed is not retried automatically.</span></div>
          <button type="button" role="switch" aria-checked={status.auto} aria-labelledby="maint-auto-label" className="switch" onClick={() => void desktop?.maintenance.setAuto(!status.auto).then(onChange)}><span /></button>
        </div>
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
          {fallbackNote}
          <div className="maint-help">
            <p><strong>PockPock itself</strong> is the default: it fixes your reports with a model on this PC, and nothing leaves it.</p>
            <p><HeartHandshake size={14} aria-hidden="true" /> <strong>Optional: help with your own account.</strong> If you have a Claude, ChatGPT (OpenAI) or Copilot plan, you can connect it so a stronger model fixes the problems you report, which makes PockPock better for everyone. It uses your plan's usage, and sends the report, the parts of the PockPock code it reads and its changes to that company. Every fix still waits for your approval and goes to the project owner as a draft pull request. If the account is not connected or stops working, PockPock itself takes over. You can disconnect at any time.</p>
          </div>
          {!agents ? <p className="note"><LoaderCircle size={13} className="spin" /> Looking for installed AI tools…</p> : (
            <fieldset className="report-categories">
              <legend className="visually-hidden">AI for maintenance</legend>
              {agents.map((agent) => (
                <div key={agent.id} className="maint-agent">
                  <label className={`${choice?.id === agent.id ? 'is-chosen' : ''}${ready(agent) ? '' : ' is-disabled'}`}>
                    <input type="radio" name="maint-agent" value={agent.id} disabled={!ready(agent)} checked={choice?.id === agent.id}
                      onChange={() => setChoice({ id: agent.id, model: agent.id === 'local' ? (choice?.model || agent.suggested || '') : '', openclaw: agent.id === 'local' ? choice?.openclaw : undefined })} />
                    <span>
                      <strong>{agent.id === 'local' ? `${agent.name} (default)` : agent.name}{ready(agent) ? <small className="badge badge--ok">{agent.canConnect ? 'Connected' : agent.version || 'Ready'}</small> : agent.installed && agent.signedIn ? <small className="badge badge--off">Not connected</small> : agent.installed ? <small className="badge badge--warn">Not signed in</small> : <small className="badge badge--off">Not installed</small>}</strong>
                      <em>{ready(agent)
                        ? `${agent.canConnect ? `Your account${accountText(agent) ? `: ${accountText(agent)}` : ''}. ` : ''}${agent.dataNotice}`
                        : agent.installed && agent.signedIn
                          ? `${agent.name} is signed in on this PC${accountText(agent) ? ` as ${accountText(agent)}` : ''}, for example from your editor. PockPock does not use it until you connect it here.`
                          : agent.installed ? `Installed${agent.version ? ` (${agent.version})` : ''}, but not signed in. Connect opens the ${agent.vendor} sign-in page in your browser.` : agent.install}</em>
                    </span>
                  </label>
                  {agent.canConnect && (
                    <div className="maint-agent__options maint-connect">
                      {ready(agent) ? (
                        <div className="card__actions">
                          <button type="button" className="button" disabled={connecting !== null} onClick={() => void disconnect(agent)}><Unplug size={13} /> Disconnect</button>
                          <span className="note">PockPock stops using this account. {agent.name} stays signed in on this PC.</span>
                        </div>
                      ) : confirming === agent.id ? (
                        <div className="maint-confirm" role="group" aria-label={`Use this ${agent.vendor} account?`}>
                          <p><strong>Use the {agent.vendor} account signed in on this PC{accountText(agent) ? ` (${accountText(agent)})` : ''}?</strong> {agent.name} is already signed in here, for example from your editor, so there is no sign-in page. If you use it, fixes count against that account's plan, and the report, the parts of the PockPock code it reads and its changes are sent to {agent.vendor}.</p>
                          <div className="card__actions">
                            <button type="button" className="button button--primary" onClick={() => void connect(agent, true)}><Plug size={13} /> Use this account</button>
                            <button type="button" className="button" onClick={() => setConfirming(null)}>Cancel</button>
                          </div>
                        </div>
                      ) : (
                        <div className="card__actions">
                          <button type="button" className="button" disabled={connecting !== null} onClick={() => void connect(agent)}>
                            {connecting === agent.id ? <LoaderCircle size={13} className="spin" /> : <Plug size={13} />} {connecting === agent.id ? (agent.installed ? 'Signing in…' : 'Connecting…') : agent.installed && agent.signedIn ? 'Connect this account' : agent.installed ? `Sign in to ${agent.name}` : `Install and connect ${agent.name}`}
                          </button>
                          {connecting === agent.id && <button type="button" className="button" onClick={() => void desktop?.maintenance.cancelConnect()}>Cancel</button>}
                        </div>
                      )}
                      {connectLog?.id === agent.id && connectLog.url && connecting === agent.id && (
                        <div className="maint-code" role="status">
                          <span>If your browser did not open, use the sign-in page:</span>
                          <button type="button" className="button" onClick={() => void desktop?.openExternal(connectLog.url)}><ExternalLink size={13} /> Open sign-in page</button>
                        </div>
                      )}
                      {connectLog?.id === agent.id && connectLog.lines.length > 0 && <pre className="setup-log" aria-live="polite">{connectLog.lines.join('\n')}</pre>}
                      {connectLog?.id === agent.id && connectLog.error && <div className="banner banner--error" role="alert"><span>{connectLog.error}</span></div>}
                    </div>
                  )}
                  {agent.id === 'local' && agent.installed && choice?.id === 'local' && (
                    <div className="maint-agent__options">
                      <select className="input input--inline" aria-label="Local model" value={choice.model} onChange={(event) => setChoice({ ...choice, model: event.target.value })}>
                        {agent.models?.map((model) => <option key={model} value={model}>{model}{model === agent.suggested ? ' (suggested)' : ''}</option>)}
                      </select>
                      <span className="maint-openclaw">
                        <input type="checkbox" id="maint-openclaw" checked={choice.openclaw === true} disabled={!agent.openclaw} onChange={(event) => setChoice({ ...choice, openclaw: event.target.checked })} />
                        <label htmlFor="maint-openclaw"><strong>Use OpenClaw, so PockPock can run commands</strong>
                          <em>{agent.openclaw ? 'It can build, run the tests and try the app while fixing, with full access inside the working copy. Without OpenClaw it only reads and edits files; the checks still run afterwards either way.' : 'OpenClaw is not installed. Run Setup and include OpenClaw to allow this.'}</em></label>
                      </span>
                    </div>
                  )}
                </div>
              ))}
            </fieldset>
          )}
          <div className="card__actions">
            <button type="button" className="button button--primary" disabled={!choice || (choice.id === 'local' && !choice.model) || agentSave.phase === 'saving' || (agentChosen && unchanged)} onClick={() => void saveAgent()}>
              {agentSave.phase === 'saving' ? <LoaderCircle size={13} className="spin" /> : agentChosen && unchanged ? <Check size={13} /> : null} {agentChosen && unchanged && agentSave.phase !== 'saving' ? 'Saved' : agentChosen ? 'Save choice' : 'Use this AI'}
            </button>
            {agentSave.phase === 'saved' && <span className="note" role="status">{agentSave.text}</span>}
            {agentSave.phase === 'error' && <span className="note note--error" role="alert">{agentSave.text}</span>}
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
