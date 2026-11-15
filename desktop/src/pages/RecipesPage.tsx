// Browser recipes: saved, versioned browser workflows that run only when started, with an
// approval before every step. Backed by /api/browser-recipes (browser-automation service).
import { useCallback, useEffect, useState } from 'react'
import type { FormEvent } from 'react'
import { Check, ChevronLeft, Globe, LoaderCircle, Play, Plus, Power, RefreshCw, Save, Trash2, X } from 'lucide-react'
import { Empty } from '../components/ui'
import { getJson, sendJson, stream, text, uid } from '../lib/api'
import type { StreamEvent } from '../lib/api'

type RecipeInput = { name: string; label: string; type: 'text' | 'url'; required: boolean }
type RecipeStep = {
  action: 'click' | 'type' | 'select' | 'scroll' | 'navigate'
  role?: 'link' | 'textbox' | 'searchbox' | 'combobox'
  target_name?: string
  input_ref?: string
  url?: string
  direction?: 'up' | 'down'
  checkpoint?: { title_contains?: string; text_contains?: string }
}
type Recipe = { recipe_id: string; name: string; version: number; enabled: boolean; allowed_domains: string[]; inputs: RecipeInput[]; steps: RecipeStep[]; approval_policy: 'each_run' }
type Draft = Omit<Recipe, 'recipe_id' | 'version' | 'enabled'>
type Version = { version: number; created_at: string; definition: Draft }

const blank = (): Draft => ({ name: '', allowed_domains: [], inputs: [], steps: [{ action: 'navigate', url: 'https://' }], approval_policy: 'each_run' })
const roleFor = (action: RecipeStep['action']): RecipeStep['role'] => action === 'click' ? 'link' : action === 'type' ? 'textbox' : action === 'select' ? 'combobox' : undefined
const message = (error: unknown, fallback: string) => error instanceof Error ? error.message : fallback

function RunPanel({ recipe, onClose }: { recipe: Recipe; onClose: () => void }) {
  const [inputs, setInputs] = useState<Record<string, string>>({})
  const [events, setEvents] = useState<StreamEvent[]>([])
  const [phase, setPhase] = useState<'ready' | 'running' | 'done' | 'failed'>('ready')
  const [error, setError] = useState('')
  const [busyApproval, setBusyApproval] = useState('')
  const [controller, setController] = useState<AbortController | null>(null)

  const start = async (event: FormEvent) => {
    event.preventDefault()
    const abort = new AbortController()
    setController(abort)
    setPhase('running')
    setError('')
    setEvents([])
    try {
      await stream(`/api/browser-recipes/${encodeURIComponent(recipe.recipe_id)}/run`, { conversation_id: `recipe-${uid()}`, version: recipe.version, inputs }, abort.signal, (item) => {
        setEvents((current) => [...current, item])
        if (item.type === 'done') setPhase('done')
        if (item.type === 'error' || item.type === 'cancelled' || item.type === 'timed_out') { setPhase('failed'); setError(text(item.message) || 'The run stopped.') }
      })
      setPhase((current) => current === 'running' ? 'done' : current)
    } catch (runError) {
      setPhase('failed')
      setError(runError instanceof DOMException ? 'Run stopped.' : message(runError, 'The run failed.'))
    } finally {
      setController(null)
      setInputs({})
    }
  }
  const decide = async (approval: StreamEvent, approved: boolean) => {
    const id = text(approval.approval_id)
    setBusyApproval(id)
    try {
      const result = await sendJson<{ accepted?: boolean; detail?: string }>(`/api/runs/${encodeURIComponent(text(approval.run_id))}/approvals/${encodeURIComponent(id)}`, { action_hash: approval.action_hash, decision: approved ? 'approved' : 'rejected' })
      if (!result.accepted) throw new Error(result.detail || 'This approval is no longer available.')
    } catch (approvalError) { setError(message(approvalError, 'Could not send the decision.')) } finally { setBusyApproval('') }
  }
  const resolved = new Set(events.filter((item) => ['approval_approved', 'approval_rejected', 'approval_expired'].includes(text(item.type))).map((item) => text(item.approval_id)))
  const pending = events.filter((item) => item.type === 'approval_requested' && !resolved.has(text(item.approval_id)))

  return (
    <section className="card run-panel" aria-label={`Run ${recipe.name}`}>
      <header><Play size={14} /><strong>Run “{recipe.name}”</strong><span>Version {recipe.version} · {recipe.allowed_domains.join(', ')}</span>
        <button type="button" className="icon-button icon-button--small" onClick={() => { controller?.abort(); onClose() }} aria-label="Close run"><X size={13} /></button></header>
      {phase === 'ready' && (
        <form onSubmit={(event) => void start(event)} className="run-panel__form">
          {recipe.inputs.map((input) => (
            <label key={input.name} className="field">{input.label || input.name}{input.required && <small>Required</small>}
              <input className="input" type={input.type === 'url' ? 'url' : 'text'} required={input.required} maxLength={1000} value={inputs[input.name] ?? ''} onChange={(event) => setInputs((current) => ({ ...current, [input.name]: event.target.value }))} />
            </label>
          ))}
          {!recipe.inputs.length && <p>This recipe has no inputs.</p>}
          <p className="note">Inputs are used for this run only and are not saved. Every step asks for your approval.</p>
          <div className="card__actions"><button type="submit" className="button button--primary" disabled={!recipe.enabled}><Play size={13} /> Start run</button>{!recipe.enabled && <span className="note">Switch the recipe on to run it.</span>}</div>
        </form>
      )}
      {phase !== 'ready' && <p className="note">{phase === 'running' ? <><LoaderCircle size={13} className="spin" /> Running…</> : phase === 'done' ? <><Check size={13} /> Finished</> : <><X size={13} /> {error || 'Stopped'}</>}{phase === 'running' && <button type="button" className="link-button" onClick={() => controller?.abort()}>Stop</button>}</p>}
      {pending.map((approval) => {
        const action = approval.action && typeof approval.action === 'object' ? approval.action as Record<string, unknown> : {}
        return (
          <div key={text(approval.approval_id)} className="card card--approval is-pending">
            <header><Check size={14} /><strong>Approve step {text(action.step) || String(action.step ?? '')}</strong><span>{text(action.action)}</span></header>
            <code className="card__detail">{text(action.target) || text(approval.message) || 'Next step'}</code>
            <div className="card__actions">
              <button type="button" className="button button--primary" disabled={busyApproval === text(approval.approval_id)} onClick={() => void decide(approval, true)}><Check size={13} /> Approve</button>
              <button type="button" className="button" disabled={busyApproval === text(approval.approval_id)} onClick={() => void decide(approval, false)}><X size={13} /> Reject</button>
            </div>
          </div>
        )
      })}
      {events.length > 0 && (
        <ol className="run-panel__events">
          {events.map((item, index) => {
            const type = text(item.type)
            if (type === 'recipe_step_result') return <li key={index}><b>Step {String(item.step)} · {text(item.status)}</b><span>{text(item.title)} {text(item.url)}</span></li>
            if (type === 'browser_screenshot' && text(item.url)) return <li key={index}><b>{text(item.name) || 'Screenshot'}</b><img src={text(item.url)} alt={`Screenshot: ${text(item.name) || 'recipe step'}`} loading="lazy" /></li>
            if (['recipe_run_started', 'recipe_run_finished', 'done', 'error', 'cancelled', 'timed_out', 'approval_approved', 'approval_rejected'].includes(type)) return <li key={index}><b>{type.replaceAll('_', ' ')}</b><span>{text(item.message)}</span></li>
            return null
          })}
        </ol>
      )}
    </section>
  )
}

export function RecipesPage() {
  const [recipes, setRecipes] = useState<Recipe[] | null>(null)
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')
  const [busy, setBusy] = useState(false)
  const [editing, setEditing] = useState<{ id: string; version: number } | null>(null)
  const [draft, setDraft] = useState<Draft | null>(null)
  const [versions, setVersions] = useState<Version[]>([])
  const [running, setRunning] = useState<Recipe | null>(null)

  const refresh = useCallback(async () => {
    try { setRecipes((await getJson<{ recipes: Recipe[] }>('/api/browser-recipes')).recipes); setError('') } catch (loadError) { setError(message(loadError, 'Browser recipes are unavailable. Start the browser automation service from Services.')) }
  }, [])
  useEffect(() => { void refresh() }, [refresh])

  const open = async (recipe: Recipe | null) => {
    setNotice('')
    setRunning(null)
    if (!recipe) { setEditing(null); setDraft(blank()); setVersions([]); return }
    setEditing({ id: recipe.recipe_id, version: recipe.version })
    setDraft({ name: recipe.name, allowed_domains: recipe.allowed_domains, inputs: recipe.inputs, steps: recipe.steps, approval_policy: 'each_run' })
    try { setVersions((await getJson<{ versions: Version[] }>(`/api/browser-recipes/${recipe.recipe_id}/versions`)).versions) } catch { setVersions([]) }
  }
  const save = async (event: FormEvent) => {
    event.preventDefault()
    if (!draft) return
    setBusy(true)
    setError('')
    try {
      const body = { ...draft, name: draft.name.trim(), allowed_domains: draft.allowed_domains.map((host) => host.trim()).filter(Boolean) }
      const saved = editing
        ? await sendJson<Recipe>(`/api/browser-recipes/${editing.id}`, { ...body, expected_version: editing.version }, 'PUT')
        : await sendJson<Recipe>('/api/browser-recipes', body)
      await refresh()
      await open(saved)
      setNotice(`Saved version ${saved.version}.`)
    } catch (saveError) { setError(message(saveError, 'Could not save the recipe.')) } finally { setBusy(false) }
  }
  const toggle = async (recipe: Recipe) => {
    setBusy(true)
    try { await sendJson(`/api/browser-recipes/${recipe.recipe_id}/enabled`, { enabled: !recipe.enabled }); await refresh() } catch (toggleError) { setError(message(toggleError, 'Could not change the recipe.')) } finally { setBusy(false) }
  }
  const remove = async (recipe: Recipe) => {
    if (!window.confirm(`Delete “${recipe.name}” and all its versions?`)) return
    setBusy(true)
    try { await sendJson(`/api/browser-recipes/${recipe.recipe_id}`, undefined, 'DELETE'); await refresh(); setDraft(null); setEditing(null) } catch (removeError) { setError(message(removeError, 'Could not delete the recipe.')) } finally { setBusy(false) }
  }
  const setStep = (index: number, change: Partial<RecipeStep>) => setDraft((current) => current && { ...current, steps: current.steps.map((step, position) => position === index ? { ...step, ...change } : step) })
  const setInput = (index: number, change: Partial<RecipeInput>) => setDraft((current) => current && { ...current, inputs: current.inputs.map((input, position) => position === index ? { ...input, ...change } : input) })

  return (
    <div className="page">
      <div className="page__inner">
        <header className="page__head">
          <div><span className="eyebrow">Workspace</span><h1>Browser recipes</h1><p>Saved browser workflows for repeated web tasks. They run only when you start them, in an isolated browser, and every step asks for approval.</p></div>
          <div className="page__actions"><button type="button" className="button button--primary" onClick={() => void open(null)}><Plus size={13} /> New recipe</button></div>
        </header>
        {error && <div className="banner banner--error" role="alert"><span>{error}</span><button type="button" className="icon-button icon-button--small" onClick={() => setError('')} aria-label="Dismiss"><X size={13} /></button></div>}
        {notice && <div className="banner" role="status"><span>{notice}</span></div>}
        {running && <RunPanel key={running.recipe_id + running.version} recipe={running} onClose={() => setRunning(null)} />}

        {draft ? (
          <form className="card recipe-editor" onSubmit={(event) => void save(event)}>
            <header><button type="button" className="icon-button icon-button--small" onClick={() => setDraft(null)} aria-label="Back to recipes"><ChevronLeft size={14} /></button><strong>{editing ? `Edit “${draft.name}” · version ${editing.version}` : 'New recipe'}</strong><span>{editing ? `Saving creates version ${editing.version + 1}` : 'Not run until you start it'}</span></header>
            <label className="field">Name<input className="input" required maxLength={120} value={draft.name} onChange={(event) => setDraft({ ...draft, name: event.target.value })} placeholder="Check order status" /></label>
            <label className="field">Allowed sites<small>Exact public hostnames, separated by commas. No wildcards.</small><input className="input" required value={draft.allowed_domains.join(', ')} onChange={(event) => setDraft({ ...draft, allowed_domains: event.target.value.split(',') })} placeholder="example.com" /></label>
            <div className="recipe-editor__section"><h4>Inputs <small>asked for when the recipe runs; not saved</small></h4><button type="button" className="button" onClick={() => setDraft({ ...draft, inputs: [...draft.inputs, { name: `input_${draft.inputs.length + 1}`, label: '', type: 'text', required: true }] })}><Plus size={13} /> Input</button></div>
            {draft.inputs.map((input, index) => (
              <div key={index} className="recipe-editor__row">
                <input className="input" aria-label={`Input ${index + 1} name`} pattern="[a-z][a-z0-9_]{0,39}" required value={input.name} onChange={(event) => setInput(index, { name: event.target.value })} />
                <input className="input" aria-label={`Input ${index + 1} label`} placeholder="Label shown when running" value={input.label} onChange={(event) => setInput(index, { label: event.target.value })} />
                <select className="input" aria-label={`Input ${index + 1} type`} value={input.type} onChange={(event) => setInput(index, { type: event.target.value as 'text' | 'url' })}><option value="text">Text</option><option value="url">Web address</option></select>
                <button type="button" className="icon-button" aria-label={`Remove input ${index + 1}`} onClick={() => setDraft({ ...draft, inputs: draft.inputs.filter((_, position) => position !== index) })}><Trash2 size={14} /></button>
              </div>
            ))}
            <div className="recipe-editor__section"><h4>Steps <small>targets use the element's accessible name</small></h4><button type="button" className="button" onClick={() => setDraft({ ...draft, steps: [...draft.steps, { action: 'click', role: 'link', target_name: '' }] })}><Plus size={13} /> Step</button></div>
            {draft.steps.map((step, index) => (
              <fieldset key={index} className="recipe-step">
                <legend>Step {index + 1}</legend>
                <div className="recipe-editor__row">
                  <select className="input" aria-label={`Step ${index + 1} action`} value={step.action} onChange={(event) => { const action = event.target.value as RecipeStep['action']; setStep(index, { action, role: roleFor(action), target_name: action === 'navigate' || action === 'scroll' ? undefined : '', url: action === 'navigate' ? 'https://' : undefined, input_ref: action === 'type' ? '' : undefined }) }}>
                    <option value="navigate">Open page</option><option value="click">Click link</option><option value="type">Type into field</option><option value="select">Choose option</option><option value="scroll">Scroll</option>
                  </select>
                  {step.action === 'navigate' && <input className="input" type="url" required aria-label={`Step ${index + 1} address`} value={step.url ?? ''} onChange={(event) => setStep(index, { url: event.target.value })} />}
                  {['click', 'type', 'select'].includes(step.action) && <input className="input" required aria-label={`Step ${index + 1} target`} placeholder="Accessible name, e.g. Order number" value={step.target_name ?? ''} onChange={(event) => setStep(index, { target_name: event.target.value })} />}
                  {step.action === 'type' && <select className="input" aria-label={`Step ${index + 1} input`} value={step.input_ref ?? ''} onChange={(event) => setStep(index, { input_ref: event.target.value })}><option value="">Choose an input</option>{draft.inputs.map((input) => <option key={input.name} value={input.name}>{input.label || input.name}</option>)}</select>}
                  {step.action === 'scroll' && <select className="input" aria-label={`Step ${index + 1} direction`} value={step.direction ?? 'down'} onChange={(event) => setStep(index, { direction: event.target.value as 'up' | 'down' })}><option value="down">Down</option><option value="up">Up</option></select>}
                  <button type="button" className="icon-button" aria-label={`Remove step ${index + 1}`} disabled={draft.steps.length === 1} onClick={() => setDraft({ ...draft, steps: draft.steps.filter((_, position) => position !== index) })}><Trash2 size={14} /></button>
                </div>
                <div className="recipe-editor__row">
                  <input className="input" aria-label={`Step ${index + 1} expected title`} placeholder="Then the page title contains… (optional)" value={step.checkpoint?.title_contains ?? ''} onChange={(event) => setStep(index, { checkpoint: { ...step.checkpoint, title_contains: event.target.value } })} />
                  <input className="input" aria-label={`Step ${index + 1} expected text`} placeholder="…or the page shows text (optional)" value={step.checkpoint?.text_contains ?? ''} onChange={(event) => setStep(index, { checkpoint: { ...step.checkpoint, text_contains: event.target.value } })} />
                </div>
              </fieldset>
            ))}
            {versions.length > 0 && <details className="recipe-versions"><summary>Version history ({versions.length})</summary>{versions.map((version) => <details key={version.version}><summary>Version {version.version} · {new Date(version.created_at).toLocaleString()}</summary><pre>{JSON.stringify(version.definition, null, 2)}</pre></details>)}</details>}
            <div className="card__actions"><button type="submit" className="button button--primary" disabled={busy}>{busy ? <LoaderCircle size={13} className="spin" /> : <Save size={13} />} {editing ? 'Save new version' : 'Save recipe'}</button><button type="button" className="button" onClick={() => setDraft(null)}>Cancel</button></div>
          </form>
        ) : recipes === null && !error ? <p className="note"><LoaderCircle size={13} className="spin" /> Loading recipes…</p>
          : recipes && !recipes.length ? <Empty icon={<Globe size={20} />} title="No recipes yet"><p>Create one for a web task you repeat, such as checking an order status.</p><button type="button" className="button button--primary" onClick={() => void open(null)}><Plus size={13} /> New recipe</button></Empty>
            : (
              <ul className="rows">
                {recipes?.map((recipe) => (
                  <li key={recipe.recipe_id} className="row">
                    <Globe size={16} className="row__icon" />
                    <div className="row__text"><strong>{recipe.name}</strong><span>Version {recipe.version} · {recipe.steps.length} steps · {recipe.allowed_domains.join(', ')}{recipe.enabled ? '' : ' · switched off'}</span></div>
                    <div className="row__actions">
                      <button type="button" className="button" disabled={!recipe.enabled} onClick={() => { setDraft(null); setRunning(recipe) }}><Play size={12} /> Run</button>
                      <button type="button" className="button" onClick={() => void open(recipe)}>Edit</button>
                      <button type="button" className="icon-button" aria-label={recipe.enabled ? `Switch off ${recipe.name}` : `Switch on ${recipe.name}`} title={recipe.enabled ? 'Switch off' : 'Switch on'} disabled={busy} onClick={() => void toggle(recipe)}><Power size={14} /></button>
                      <button type="button" className="icon-button" aria-label={`Delete ${recipe.name}`} title="Delete" disabled={busy} onClick={() => void remove(recipe)}><Trash2 size={14} /></button>
                    </div>
                  </li>
                ))}
              </ul>
            )}
        {!draft && recipes && <p className="note"><button type="button" className="link-button" onClick={() => void refresh()}><RefreshCw size={12} /> Refresh</button></p>}
      </div>
    </div>
  )
}
