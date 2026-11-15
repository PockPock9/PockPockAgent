// Setup. First run: a welcome screen with one button that installs the recommended set with a model
// that fits this computer. Customize (and later runs from Settings): choose components, the model and
// OpenClaw skills. Either way everything is installed in one go, then started and checked.
import { useEffect, useRef, useState } from 'react'
import { AlertTriangle, Box, Check, ChevronDown, ChevronRight, CircleDashed, Cpu, HardDrive, LoaderCircle, MemoryStick, Puzzle, RotateCcw, Server, Settings2, Sparkles, Terminal, X } from 'lucide-react'
import { bridge } from '../lib/types'
import { computer, isMac } from '../lib/platform'
import type { SetupComponent, SetupEvent, SetupStatus } from '../lib/types'

type Step = Extract<SetupEvent, { type: 'step' }>

type ComponentInfo = { id: SetupComponent; title: string; icon: React.ReactNode; detail: string; size: string; locked?: boolean; warning?: string }

const COMPONENTS: ComponentInfo[] = isMac
  ? [
      { id: 'core', title: 'PockPock backend', icon: <Server size={16} />, detail: 'Python 3.12 (installed into PockPock’s own folder, no password needed), the PockPock services and an isolated browser for agent web tasks.', size: 'about 700 MB', locked: true },
      { id: 'ollama', title: 'Ollama and models', icon: <Cpu size={16} />, detail: 'Runs AI models on this Mac. Installs Ollama in Applications and downloads the model chosen below plus qwen2.5:1.5b, a small model that routes requests.', size: 'about 1 GB plus the model' },
      { id: 'openclaw', title: 'OpenClaw engine', icon: <Terminal size={16} />, detail: 'An agent that works directly on this Mac, with skills, MCP servers and the Ask first / Auto-approve / Full access permissions. Installs Node.js into PockPock’s folder if needed.', size: 'about 400 MB' },
      { id: 'nemoclaw', title: 'NemoClaw engine', icon: <Box size={16} />, detail: 'OpenClaw inside a Docker sandbox, so it cannot touch this Mac. Installs Docker Desktop and Apple’s Command Line Tools if missing.', size: 'about 8 GB', warning: 'macOS asks for your password once (to install Docker Desktop) and may ask to install the Command Line Tools. Takes 20 to 40 minutes.' },
    ]
  : [
      { id: 'core', title: 'PockPock backend', icon: <Server size={16} />, detail: 'Python 3.12, the PockPock services and an isolated browser for agent web tasks.', size: 'about 600 MB', locked: true },
      { id: 'ollama', title: 'Ollama and models', icon: <Cpu size={16} />, detail: 'Runs AI models on this PC. Downloads the model chosen below plus qwen2.5:1.5b, a small model that routes requests.', size: 'about 2 GB plus the model' },
      { id: 'openclaw', title: 'OpenClaw engine', icon: <Terminal size={16} />, detail: 'An agent that works directly on this PC, with skills, MCP servers and the Ask first / Auto-approve / Full access permissions. Installs Node.js if needed.', size: 'about 400 MB' },
      { id: 'nemoclaw', title: 'NemoClaw engine', icon: <Box size={16} />, detail: 'OpenClaw inside a sandbox, so it cannot touch this PC. Installs WSL with Ubuntu and Docker Desktop.', size: 'about 8 GB', warning: 'Windows asks for administrator permission, may need a restart, and Ubuntu asks you to create a username once. Takes 20 to 40 minutes.' },
    ]

export function SetupPage({ onDone }: { onDone: () => void }) {
  const desktop = bridge()
  const [status, setStatus] = useState<SetupStatus | null>(null)
  const [chosen, setChosen] = useState<Set<SetupComponent>>(new Set(['core', 'ollama', 'openclaw']))
  const [model, setModel] = useState('')
  const [customize, setCustomize] = useState(false)
  const [disabledSkills, setDisabledSkills] = useState<Set<string>>(new Set())
  const [showSkills, setShowSkills] = useState(false)
  const [phase, setPhase] = useState<'choose' | 'running' | 'finished'>('choose')
  const [steps, setSteps] = useState<Step[]>([])
  const [log, setLog] = useState<string[]>([])
  const [showLog, setShowLog] = useState(false)
  const [outcome, setOutcome] = useState<{ outcome: string; message: string } | null>(null)
  const logRef = useRef<HTMLPreElement>(null)

  const load = () => desktop?.setup.status().then((current) => {
    setStatus(current)
    setModel((value) => value || current.pending?.model || current.model.name)
    if (current.pending) {
      setChosen(new Set(current.pending.components))
      setDisabledSkills(new Set(current.pending.disabledSkills))
    } else if (current.needsSetup) {
      setChosen(new Set(current.recommended.components))
    } else {
      // Repair: tick what is missing. NemoClaw is never ticked for you: it needs administrator
      // approval, Docker and (on Windows) a restart.
      setChosen(new Set((['core', 'ollama', 'openclaw'] as SetupComponent[]).filter((id) => id === 'core' || !current[id].installed || (id === 'ollama' && Object.values(current.ollama.models).some((ok) => !ok)))))
    }
  })

  useEffect(() => {
    if (!desktop) return
    void load()
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

  const start = (plan?: { components: SetupComponent[] }) => {
    setPhase('running')
    void desktop?.setup.start({ components: plan?.components ?? [...chosen], disabledSkills: [...disabledSkills], model: model || undefined })
  }
  const unsupported = (id: SetupComponent) => id === 'nemoclaw' && status !== null && !status.nemoclaw.supported
  const installed = (id: SetupComponent) => Boolean(status?.[id].installed) && !(id === 'ollama' && status && Object.values(status.ollama.models).some((ok) => !ok))

  if (!desktop) return <div className="page"><div className="page__inner"><p className="note">Setup runs in the desktop app.</p></div></div>
  if (status && phase === 'choose' && status.needsSetup && !status.pending && !customize) return <Welcome status={status} onStart={() => start({ components: status.recommended.components })} onCustomize={() => setCustomize(true)} onRecheck={() => void load()} />
  return (
    <div className="page setup">
      <div className="page__inner">
        <header className="page__head">
          <div><span className="eyebrow">Setup</span><h1>{status?.needsSetup ? 'Set up PockPock' : 'Install or repair components'}</h1>
            <p>{phase === 'running' ? `PockPock is installing everything it needs. Keep the ${computer} connected to the internet; it stays awake while setup runs, and you can keep using it.` : 'Choose what to install, then PockPock installs and configures everything in one go.'} Anything already on this {computer} is kept and skipped. At the end every service is started and checked.</p></div>
        </header>
        {!status && <p className="note"><LoaderCircle size={13} className="spin" /> Checking this PC…</p>}
        {status && phase === 'choose' && (
          <>
            {status.pending && <div className="banner" role="status"><span>The last setup stopped before it finished{status.lastRun?.message ? `: ${status.lastRun.message}` : '.'} Press Install to continue.</span></div>}
            {status.platform === 'win32' && !status.winget && <div className="banner" role="status"><span>The Windows package manager (winget) is not available, so installers are downloaded directly instead.</span></div>}
            <ul className="setup-components">
              {COMPONENTS.map((component) => (
                <li key={component.id} className={`setup-component${chosen.has(component.id) ? ' is-chosen' : ''}${unsupported(component.id) ? ' is-unsupported' : ''}`}>
                  <label>
                    <input type="checkbox" checked={chosen.has(component.id)} disabled={component.locked || unsupported(component.id)} onChange={(event) => setChosen((current) => { const next = new Set(current); if (event.target.checked) next.add(component.id); else next.delete(component.id); return next })} />
                    <span className="setup-component__icon">{component.icon}</span>
                    <span className="setup-component__text">
                      <strong>{component.title} {installed(component.id) && <small className="badge badge--ok">Installed</small>}</strong>
                      <span>{component.detail}</span>
                      {unsupported(component.id) && <em><AlertTriangle size={12} /> {status.nemoclaw.reason}</em>}
                      <small>{installed(component.id) ? 'Checked and repaired if needed' : `Download: ${component.size}`}</small>
                      {component.warning && chosen.has(component.id) && !installed(component.id) && <em><AlertTriangle size={12} /> {component.warning}</em>}
                    </span>
                  </label>
                  {component.id === 'ollama' && chosen.has('ollama') && (
                    <fieldset className="setup-models">
                      <legend>AI model</legend>
                      {status.model.choices.map((choice) => (
                        <label key={choice.name} className={model === choice.name ? 'is-chosen' : undefined}>
                          <input type="radio" name="setup-model" value={choice.name} checked={model === choice.name} onChange={() => setModel(choice.name)} />
                          <span><strong>{choice.name}{choice.name === status.model.name && <small className="badge badge--ok">Recommended</small>}</strong><em>{choice.summary} Download: about {choice.downloadGB} GB.</em></span>
                        </label>
                      ))}
                      <p className="note">{status.model.reason}</p>
                    </fieldset>
                  )}
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
              <button type="button" className="button button--primary" onClick={() => start()}><Check size={13} /> Install</button>
              {status.needsSetup && customize && <button type="button" className="button" onClick={() => setCustomize(false)}>Back</button>}
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
                <span>{outcome.outcome === 'done' ? 'Everything is installed, running and checked. PockPock is ready.' : outcome.message || 'Setup did not finish.'}</span>
              </div>
            )}
            <div className="card__actions">
              {phase === 'running' && <button type="button" className="button" onClick={() => void desktop.setup.cancel()}><X size={13} /> Cancel</button>}
              {outcome?.outcome === 'done' && <button type="button" className="button button--primary" onClick={onDone}><Check size={13} /> Start using PockPock</button>}
              {outcome && outcome.outcome !== 'done' && outcome.outcome !== 'restart' && <button type="button" className="button button--primary" onClick={() => start()}><RotateCcw size={13} /> {outcome.outcome === 'action' ? 'Continue setup' : 'Try again'}</button>}
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

/** First run: what this computer has, what will be installed, and one button. */
function Welcome({ status, onStart, onCustomize, onRecheck }: { status: SetupStatus; onStart: () => void; onCustomize: () => void; onRecheck: () => void }) {
  const { hardware: specs, recommended } = status
  const lowSpace = specs.freeDiskGB !== null && specs.freeDiskGB < recommended.neededGB
  const graphics = specs.gpu ? (specs.gpu.shared ? `${specs.gpu.name}` : `${specs.gpu.name} (${specs.gpu.memoryGB} GB)`) : 'No graphics card for AI found'
  const verb = (missing: string) => (status.model.missing.includes(missing) ? 'Install' : 'Use')
  // Download time between a fast (100 Mbit/s) and a slow (25 Mbit/s) connection, plus a few
  // minutes for installing and checking.
  const gb = recommended.downloadGB
  const minutes = [Math.ceil(gb / 0.75 + 3), Math.ceil(gb / 0.19 + 5)]
  const duration = gb < 1.5 ? 'Usually a few minutes.' : `Usually ${minutes[0]} to ${minutes[1]} minutes, depending on your internet connection.`
  return (
    <div className="page setup">
      <div className="page__inner">
        <header className="page__head">
          <div><span className="eyebrow">Welcome</span><h1>Set up PockPock</h1>
            <p>PockPock runs AI on this {computer}, so your chats and files stay on it. Setup downloads everything PockPock needs and checks that it works. You do not need to install anything else.</p></div>
        </header>
        <section className="card setup-welcome" aria-labelledby="setup-welcome-title">
          <h2 id="setup-welcome-title">What setup will do</h2>
          <ul className="setup-includes">
            <li><Cpu size={15} /><span><strong>{verb('model')} the AI model {status.model.name}</strong> and Ollama, which runs it.</span></li>
            <li><Server size={15} /><span><strong>Install PockPock’s services</strong> and a private browser the agent uses for web tasks.</span></li>
            <li><Terminal size={15} /><span><strong>{verb('openclaw')} OpenClaw</strong>, an agent that can work on this {computer}. It asks before it does anything.</span></li>
            <li><Check size={15} /><span><strong>Check that everything works</strong>, with a short test reply from a model.</span></li>
          </ul>
          <dl className="setup-facts">
            <div><dt><MemoryStick size={13} /> This {computer}</dt><dd>{specs.ramGB} GB memory · {graphics}</dd></div>
            <div><dt><Sparkles size={13} /> AI model</dt><dd><strong>{status.model.name}</strong> · {status.model.reason}</dd></div>
            <div><dt><HardDrive size={13} /> Download</dt><dd>{recommended.downloadGB ? `About ${gb} GB. ${duration}` : 'Nothing to download.'}</dd></div>
            <div><dt><HardDrive size={13} /> Free space</dt><dd className={lowSpace ? 'is-warning' : undefined}>{specs.freeDiskGB === null ? 'Unknown' : `${specs.freeDiskGB} GB free${recommended.neededGB ? `, about ${recommended.neededGB} GB needed` : ''}`}</dd></div>
          </dl>
          {lowSpace && (
            <div className="banner banner--error" role="alert"><AlertTriangle size={14} /><span>There is not enough free space. Free up about {Math.ceil(recommended.neededGB - (specs.freeDiskGB ?? 0))} GB (for example by emptying the {isMac ? 'Trash' : 'Recycle Bin'}), then press Check again.</span></div>
          )}
          <p className="note">Keep the {computer} connected to the internet. It stays awake while setup runs, and you can keep using it.</p>
          <div className="card__actions">
            {lowSpace
              ? <button type="button" className="button button--primary" onClick={onRecheck}><RotateCcw size={13} /> Check again</button>
              : <button type="button" className="button button--primary button--large" onClick={onStart}><Check size={14} /> Set up PockPock</button>}
            <button type="button" className="button" onClick={onCustomize}><Settings2 size={13} /> Customize</button>
          </div>
        </section>
      </div>
    </div>
  )
}
