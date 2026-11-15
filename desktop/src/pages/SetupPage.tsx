// First-run setup: choose components (and OpenClaw skills), then install everything in one go.
import { useEffect, useRef, useState } from 'react'
import { AlertTriangle, Box, Check, ChevronDown, ChevronRight, CircleDashed, Cpu, LoaderCircle, Puzzle, RotateCcw, Server, Terminal, X } from 'lucide-react'
import { bridge } from '../lib/types'
import type { SetupComponent, SetupEvent, SetupStatus } from '../lib/types'

type Step = Extract<SetupEvent, { type: 'step' }>

const COMPONENTS: Array<{ id: SetupComponent; title: string; icon: React.ReactNode; detail: string; size: string; locked?: boolean; warning?: string }> = [
  { id: 'core', title: 'PockPock backend', icon: <Server size={16} />, detail: 'Python 3.12, the PockPock services and an isolated browser for agent web tasks.', size: 'about 600 MB', locked: true },
  { id: 'ollama', title: 'Ollama and models', icon: <Cpu size={16} />, detail: 'Runs AI models on this PC. Downloads qwen3.5:9b (the default model) and qwen2.5:1.5b (used to route requests).', size: 'about 8 GB' },
  { id: 'openclaw', title: 'OpenClaw engine', icon: <Terminal size={16} />, detail: 'An agent that works directly on this PC, with skills, MCP servers and the Ask first / Auto-approve / Full access permissions. Installs Node.js if needed.', size: 'about 400 MB' },
  { id: 'nemoclaw', title: 'NemoClaw engine', icon: <Box size={16} />, detail: 'OpenClaw inside a sandbox, so it cannot touch this PC. Installs WSL with Ubuntu and Docker Desktop.', size: 'about 8 GB', warning: 'Windows asks for administrator permission, may need a restart, and Ubuntu asks you to create a username once. Takes 20 to 40 minutes.' },
]

export function SetupPage({ onDone }: { onDone: () => void }) {
  const desktop = bridge()
  const [status, setStatus] = useState<SetupStatus | null>(null)
  const [chosen, setChosen] = useState<Set<SetupComponent>>(new Set(['core', 'ollama', 'openclaw', 'nemoclaw']))
  const [disabledSkills, setDisabledSkills] = useState<Set<string>>(new Set())
  const [showSkills, setShowSkills] = useState(false)
  const [phase, setPhase] = useState<'choose' | 'running' | 'finished'>('choose')
  const [steps, setSteps] = useState<Step[]>([])
  const [log, setLog] = useState<string[]>([])
  const [showLog, setShowLog] = useState(false)
  const [outcome, setOutcome] = useState<{ outcome: string; message: string } | null>(null)
  const logRef = useRef<HTMLPreElement>(null)

  useEffect(() => {
    if (!desktop) return
    void desktop.setup.status().then((current) => {
      setStatus(current)
      if (current.pending) {
        setChosen(new Set(current.pending.components))
        setDisabledSkills(new Set(current.pending.disabledSkills))
      } else {
        // Leave out components that are already installed.
        setChosen(new Set((['core', 'ollama', 'openclaw', 'nemoclaw'] as SetupComponent[]).filter((id) => id === 'core' || !current[id].installed || (id === 'ollama' && Object.values(current.ollama.models).some((ok) => !ok)))))
      }
    })
    return desktop.setup.onEvent((event) => {
      if (event.type === 'started') { setPhase('running'); setSteps([]); setLog([]); setOutcome(null) }
      if (event.type === 'log') setLog((current) => [...current.slice(-1500), event.line])
      if (event.type === 'step') setSteps((current) => {
        const index = current.findIndex((item) => item.component === event.component && item.id === event.id)
        if (index === -1) return [...current, event]
        const next = [...current]
        next[index] = event
        return next
      })
      if (event.type === 'finished') { setPhase('finished'); setOutcome(event); void desktop.setup.status().then(setStatus) }
    })
  }, [desktop])

  useEffect(() => { if (showLog && logRef.current) logRef.current.scrollTop = logRef.current.scrollHeight }, [log, showLog])

  const start = () => {
    setPhase('running')
    void desktop?.setup.start({ components: [...chosen], disabledSkills: [...disabledSkills] })
  }
  const installed = (id: SetupComponent) => Boolean(status?.[id].installed) && !(id === 'ollama' && status && Object.values(status.ollama.models).some((ok) => !ok))

  if (!desktop) return <div className="page"><div className="page__inner"><p className="note">Setup runs in the desktop app.</p></div></div>
  return (
    <div className="page setup">
      <div className="page__inner">
        <header className="page__head">
          <div><span className="eyebrow">Setup</span><h1>{status?.needsSetup ? 'Set up PockPock' : 'Install or repair components'}</h1>
            <p>Choose what to install, then PockPock installs and configures everything in one go. Anything already on this PC is kept and skipped.</p></div>
        </header>
        {!status && <p className="note"><LoaderCircle size={13} className="spin" /> Checking this PC…</p>}
        {status && phase === 'choose' && (
          <>
            {status.pending && <div className="banner" role="status"><span>The last setup stopped before it finished{status.lastRun?.message ? `: ${status.lastRun.message}` : '.'} Press Install to continue.</span></div>}
            {!status.winget && <div className="banner" role="status"><span>The Windows package manager (winget) is not available, so installers are downloaded directly instead.</span></div>}
            <ul className="setup-components">
              {COMPONENTS.map((component) => (
                <li key={component.id} className={`setup-component${chosen.has(component.id) ? ' is-chosen' : ''}`}>
                  <label>
                    <input type="checkbox" checked={chosen.has(component.id)} disabled={component.locked} onChange={(event) => setChosen((current) => { const next = new Set(current); if (event.target.checked) next.add(component.id); else next.delete(component.id); return next })} />
                    <span className="setup-component__icon">{component.icon}</span>
                    <span className="setup-component__text">
                      <strong>{component.title} {installed(component.id) && <small className="badge badge--ok">Installed</small>}</strong>
                      <span>{component.detail}</span>
                      <small>{installed(component.id) ? 'Checked and repaired if needed' : `Download: ${component.size}`}</small>
                      {component.warning && chosen.has(component.id) && !installed(component.id) && <em><AlertTriangle size={12} /> {component.warning}</em>}
                    </span>
                  </label>
                  {component.id === 'openclaw' && chosen.has('openclaw') && (
                    <div className="setup-skills">
                      <button type="button" className="link-button" aria-expanded={showSkills} onClick={() => setShowSkills((value) => !value)}>
                        {showSkills ? <ChevronDown size={13} /> : <ChevronRight size={13} />} <Puzzle size={13} /> Skills: {status.skills.length - disabledSkills.size} of {status.skills.length} included
                      </button>
                      {showSkills && (
                        <>
                          <div className="setup-skills__actions"><button type="button" className="link-button" onClick={() => setDisabledSkills(new Set())}>Include all</button><button type="button" className="link-button" onClick={() => setDisabledSkills(new Set(status.skills.map((skill) => skill.key)))}>Include none</button></div>
                          <ul className="choice-list">
                            {status.skills.map((skill) => (
                              <li key={skill.key}><label>
                                <input type="checkbox" checked={!disabledSkills.has(skill.key)} onChange={(event) => setDisabledSkills((current) => { const next = new Set(current); if (event.target.checked) next.delete(skill.key); else next.add(skill.key); return next })} />
                                <span><strong>{skill.name}</strong><em>{skill.description}</em></span>
                              </label></li>
                            ))}
                          </ul>
                          <p className="note">Left-out skills stay installed but switched off. Switch them on later on the Skills page.</p>
                        </>
                      )}
                    </div>
                  )}
                </li>
              ))}
            </ul>
            <div className="card__actions">
              <button type="button" className="button button--primary" onClick={start}><Check size={13} /> Install</button>
              {!status.needsSetup && <button type="button" className="button" onClick={onDone}>Not now</button>}
            </div>
          </>
        )}
        {phase !== 'choose' && (
          <section className="setup-progress" aria-live="polite">
            <ol className="setup-steps">
              {steps.map((step) => (
                <li key={`${step.component}:${step.id}`} className={`setup-step setup-step--${step.status}`}>
                  {step.status === 'running' ? <LoaderCircle size={14} className="spin" /> : step.status === 'done' ? <Check size={14} /> : step.status === 'waiting' ? <CircleDashed size={14} /> : <X size={14} />}
                  <span><strong>{step.label}</strong>{step.detail && <small>{step.detail}</small>}
                    {step.status === 'running' && typeof step.progress === 'number' && <span className="progress"><span style={{ width: `${Math.round(step.progress * 100)}%` }} /></span>}
                  </span>
                </li>
              ))}
              {phase === 'running' && !steps.length && <li className="setup-step"><LoaderCircle size={14} className="spin" /><span><strong>Preparing…</strong></span></li>}
            </ol>
            {outcome && (
              <div className={`banner${outcome.outcome === 'done' ? '' : ' banner--error'}`} role="status">
                <span>{outcome.outcome === 'done' ? 'Everything is installed and running.' : outcome.message || 'Setup did not finish.'}</span>
              </div>
            )}
            <div className="card__actions">
              {phase === 'running' && <button type="button" className="button" onClick={() => void desktop.setup.cancel()}><X size={13} /> Cancel</button>}
              {outcome?.outcome === 'done' && <button type="button" className="button button--primary" onClick={onDone}><Check size={13} /> Start using PockPock</button>}
              {outcome && outcome.outcome !== 'done' && outcome.outcome !== 'restart' && <button type="button" className="button button--primary" onClick={start}><RotateCcw size={13} /> {outcome.outcome === 'action' ? 'Continue setup' : 'Try again'}</button>}
              {outcome && outcome.outcome !== 'done' && <button type="button" className="button" onClick={() => { setPhase('choose'); setOutcome(null) }}>Change choices</button>}
              {outcome && outcome.outcome !== 'done' && !status?.needsSetup && <button type="button" className="button" onClick={onDone}>Use PockPock now</button>}
            </div>
            <button type="button" className="link-button" aria-expanded={showLog} onClick={() => setShowLog((value) => !value)}>{showLog ? 'Hide' : 'Show'} details ({log.length} lines)</button>
            {showLog && <pre ref={logRef} className="setup-log">{log.join('\n')}</pre>}
          </section>
        )}
      </div>
    </div>
  )
}
