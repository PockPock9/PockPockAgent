import { useCallback, useEffect, useState } from 'react'
import type { FormEvent } from 'react'
import { Check, ChevronRight, Plus, RefreshCw, Save, Trash2, X } from 'lucide-react'

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
type Recipe = {
  recipe_id: string
  name: string
  version: number
  enabled: boolean
  allowed_domains: string[]
  inputs: RecipeInput[]
  steps: RecipeStep[]
  approval_policy: 'each_run'
}
type RecipeVersion = { version: number; created_at: string; definition: Omit<Recipe, 'recipe_id' | 'version' | 'enabled' | 'created_at' | 'updated_at'> }
type Draft = Omit<Recipe, 'recipe_id' | 'version' | 'enabled'>
type RunEvent = Record<string, unknown> & { sequence?: number }
type BrowserRecipesProps = {
  ensureConversation: () => string
  onRunStarted: (conversationId: string, runId: string, recipeName: string) => void
  onRunEvent: (conversationId: string, runId: string, event: RunEvent) => void
}

const blankDraft = (): Draft => ({ name: '', allowed_domains: [], inputs: [], steps: [{ action: 'navigate', url: 'https://' }], approval_policy: 'each_run' })
const roleFor = (action: RecipeStep['action']): RecipeStep['role'] => action === 'click' ? 'link' : action === 'type' ? 'textbox' : action === 'select' ? 'combobox' : undefined

export function BrowserRecipes({ ensureConversation, onRunStarted, onRunEvent }: BrowserRecipesProps) {
  const [recipes, setRecipes] = useState<Recipe[]>([])
  const [selectedId, setSelectedId] = useState('')
  const [draft, setDraft] = useState<Draft>(blankDraft)
  const [editingId, setEditingId] = useState('')
  const [expectedVersion, setExpectedVersion] = useState(1)
  const [versions, setVersions] = useState<RecipeVersion[]>([])
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')
  const [runRecipe, setRunRecipe] = useState<Recipe | null>(null)
  const [runInputs, setRunInputs] = useState<Record<string, string>>({})
  const [runEvents, setRunEvents] = useState<RunEvent[]>([])
  const [runStatus, setRunStatus] = useState('')
  const [runBusy, setRunBusy] = useState(false)
  const [approvalBusy, setApprovalBusy] = useState('')

  const request = useCallback(async (path: string, init?: RequestInit) => {
    const response = await fetch(`/api/browser-recipes${path}`, init)
    const payload = await response.json() as { detail?: string }
    if (!response.ok) throw new Error(payload.detail || 'Browser recipes are unavailable.')
    return payload
  }, [])

  const refresh = useCallback(async () => {
    const result = await request('') as { recipes: Recipe[] }
    setRecipes(result.recipes)
    setError('')
  }, [request])

  useEffect(() => { void refresh().catch((err: unknown) => setError(err instanceof Error ? err.message : 'Could not load recipes.')) }, [refresh])

  const reset = () => { setDraft(blankDraft()); setEditingId(''); setExpectedVersion(1); setVersions([]); setSelectedId(''); setRunRecipe(null); setRunEvents([]); setRunStatus('') }
  const edit = async (recipe: Recipe) => {
    setSelectedId(recipe.recipe_id)
    setEditingId(recipe.recipe_id)
    setExpectedVersion(recipe.version)
    setDraft({ name: recipe.name, allowed_domains: recipe.allowed_domains, inputs: recipe.inputs, steps: recipe.steps, approval_policy: 'each_run' })
    setRunRecipe(null)
    setRunEvents([])
    setRunStatus('')
    try {
      const result = await request(`/${recipe.recipe_id}/versions`) as { versions: RecipeVersion[] }
      setVersions(result.versions)
      const savedRunId = localStorage.getItem(`frog-browser-recipe-run:${recipe.recipe_id}`)
      if (savedRunId) {
        const replayResponse = await fetch(`/api/runs/${encodeURIComponent(savedRunId)}/events?limit=1000`)
        const replay = await replayResponse.json() as { detail?: string; run?: { status: string }; events?: Array<{ sequence: number; event: RunEvent }> }
        if (replayResponse.ok && replay.events) {
          setRunRecipe(recipe)
          setRunEvents(replay.events.map((item) => ({ ...item.event, sequence: item.sequence })))
          setRunStatus(replay.run?.status || '')
        }
      }
    } catch (err) { setError(err instanceof Error ? err.message : 'Could not load recipe history.') }
  }

  const startRun = async (event: FormEvent) => {
    event.preventDefault()
    if (!runRecipe || !runRecipe.enabled || runBusy) return
    setRunBusy(true); setError(''); setNotice(''); setRunEvents([]); setRunStatus('Starting')
    const conversationId = ensureConversation()
    let streamRunId = ''
    try {
      const response = await fetch(`/api/browser-recipes/${encodeURIComponent(runRecipe.recipe_id)}/run`, {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ conversation_id: conversationId, version: runRecipe.version, inputs: runInputs }),
      })
      if (!response.ok) {
        const payload = await response.json() as { detail?: string }
        throw new Error(payload.detail || 'Could not start the browser recipe.')
      }
      if (!response.body) throw new Error('The browser recipe run did not return a progress stream.')
      const reader = response.body.getReader()
      const decoder = new TextDecoder()
      let buffer = ''
      const acceptEvent = (event: RunEvent) => {
        const runId = typeof event.run_id === 'string' ? event.run_id : streamRunId
        if (event.type === 'recipe_run_started' && runId) {
          streamRunId = runId
          localStorage.setItem(`frog-browser-recipe-run:${runRecipe.recipe_id}`, runId)
          onRunStarted(conversationId, runId, runRecipe.name)
        }
        setRunEvents((current) => {
          const sequence = Number(event.sequence)
          if (Number.isFinite(sequence) && current.some((item) => item.sequence === sequence)) return current
          return [...current, event].sort((left, right) => (left.sequence ?? 0) - (right.sequence ?? 0))
        })
        if (typeof event.type === 'string' && ['done', 'error', 'cancelled', 'timed_out'].includes(event.type)) setRunStatus(event.type === 'done' ? 'completed' : event.type)
        else if (event.type === 'recipe_run_started') setRunStatus('running')
        if (runId) onRunEvent(conversationId, runId, event)
      }
      while (true) {
        const { value, done } = await reader.read()
        buffer += decoder.decode(value || new Uint8Array(), { stream: !done })
        const frames = buffer.split('\n\n')
        buffer = frames.pop() || ''
        for (const frame of frames) {
          const data = frame.split('\n').filter((line) => line.startsWith('data:')).map((line) => line.slice(5).trim()).join('\n')
          if (!data) continue
          try { acceptEvent(JSON.parse(data) as RunEvent) } catch { /* Ignore malformed stream frames; durable replay remains available. */ }
        }
        if (done) break
      }
      if (buffer.trim()) {
        const data = buffer.split('\n').filter((line) => line.startsWith('data:')).map((line) => line.slice(5).trim()).join('\n')
        if (data) acceptEvent(JSON.parse(data) as RunEvent)
      }
    } catch (err) {
      const message = err instanceof Error ? err.message : 'Browser recipe run failed.'
      setError(message); setRunStatus('failed')
      if (streamRunId) onRunEvent(conversationId, streamRunId, { type: 'error', message })
    } finally {
      setRunBusy(false)
      setRunInputs({})
    }
  }

  const resolveApproval = async (approval: RunEvent, decision: 'approved' | 'rejected') => {
    const runId = String(approval.run_id || '')
    const approvalId = String(approval.approval_id || '')
    if (!runId || !approvalId) return
    setApprovalBusy(approvalId); setError('')
    try {
      const response = await fetch(`/api/runs/${encodeURIComponent(runId)}/approvals/${encodeURIComponent(approvalId)}`, {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ action_hash: approval.action_hash, decision }),
      })
      const result = await response.json() as { detail?: string; accepted?: boolean }
      if (!response.ok || !result.accepted) throw new Error(result.detail || 'This approval is no longer available.')
    } catch (err) { setError(err instanceof Error ? err.message : 'Could not submit this approval.') }
    finally { setApprovalBusy('') }
  }

  const save = async (event: FormEvent) => {
    event.preventDefault()
    setBusy(true); setError(''); setNotice('')
    try {
      const payload = { ...draft, name: draft.name.trim(), allowed_domains: draft.allowed_domains.map((host) => host.trim()).filter(Boolean) }
      const saved = await request(editingId ? `/${editingId}` : '', {
        method: editingId ? 'PUT' : 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(editingId ? { ...payload, expected_version: expectedVersion } : payload),
      }) as Recipe
      await refresh(); setSelectedId(saved.recipe_id); setEditingId(saved.recipe_id); setExpectedVersion(saved.version)
      const history = await request(`/${saved.recipe_id}/versions`) as { versions: RecipeVersion[] }
      setVersions(history.versions); setNotice(`Saved version ${saved.version}.`)
    } catch (err) { setError(err instanceof Error ? err.message : 'Could not save recipe.') }
    finally { setBusy(false) }
  }

  const toggleEnabled = async (recipe: Recipe) => {
    setBusy(true); setError(''); setNotice('')
    try {
      await request(`/${recipe.recipe_id}/enabled`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ enabled: !recipe.enabled }) })
      await refresh(); setNotice(recipe.enabled ? 'Recipe disabled.' : 'Recipe enabled.')
    } catch (err) { setError(err instanceof Error ? err.message : 'Could not update recipe.') }
    finally { setBusy(false) }
  }

  const remove = async (recipe: Recipe) => {
    if (!window.confirm(`Delete “${recipe.name}” and all its saved versions?`)) return
    setBusy(true); setError(''); setNotice('')
    try { await request(`/${recipe.recipe_id}`, { method: 'DELETE' }); await refresh(); reset(); setNotice('Recipe and version history deleted.') }
    catch (err) { setError(err instanceof Error ? err.message : 'Could not delete recipe.') }
    finally { setBusy(false) }
  }

  const changeStep = (index: number, changes: Partial<RecipeStep>) => setDraft((value) => ({ ...value, steps: value.steps.map((step, current) => current === index ? { ...step, ...changes } : step) }))
  const addStep = () => setDraft((value) => ({ ...value, steps: [...value.steps, { action: 'click', role: 'link', target_name: '' }] }))
  const addInput = () => setDraft((value) => ({ ...value, inputs: [...value.inputs, { name: `input_${value.inputs.length + 1}`, label: '', type: 'text', required: true }] }))
  const resolvedApprovals = new Set(runEvents.filter((item) => ['approval_approved', 'approval_rejected', 'approval_expired'].includes(String(item.type))).map((item) => String(item.approval_id)))
  const pendingApprovals = runEvents.filter((item) => item.type === 'approval_requested' && !resolvedApprovals.has(String(item.approval_id)))

  return <section className="browser-recipes page-enter">
    <div className="browser-recipes__header"><div><span className="eyebrow">Agent tools / Browser</span><h1>Browser workflows</h1><p>Save reviewed steps for reuse. Recipes stay on this PC and never run on a schedule.</p></div><button className="action-button" onClick={reset}><Plus size={14} /> New recipe</button></div>
    {(error || notice) && <div className={`browser-recipes__notice${error ? ' browser-recipes__notice--error' : ''}`} role={error ? 'alert' : 'status'}>{error || notice}{error && <button onClick={() => setError('')} aria-label="Dismiss error"><X size={13} /></button>}</div>}
    <div className="browser-recipes__layout">
      <aside className="panel browser-recipes__list"><div className="browser-recipes__list-head"><b>Saved recipes</b><button className="icon-button" onClick={() => void refresh()} aria-label="Refresh recipes" disabled={busy}><RefreshCw size={14} /></button></div>
        {recipes.length === 0 ? <p className="browser-recipes__empty">No recipes saved yet. Create a reviewed workflow to begin.</p> : recipes.map((recipe) => <button key={recipe.recipe_id} className={`browser-recipes__item${selectedId === recipe.recipe_id ? ' browser-recipes__item--selected' : ''}`} onClick={() => void edit(recipe)}><span><b>{recipe.name}</b><small>v{recipe.version} · {recipe.steps.length} steps · {recipe.enabled ? 'Enabled' : 'Disabled'}</small></span><ChevronRight size={14} /></button>)}
      </aside>
      <form className="panel browser-recipes__editor" onSubmit={(event) => void save(event)}>
        <div className="browser-recipes__editor-head"><div><span className="eyebrow">{editingId ? `Editing version ${expectedVersion}` : 'New local recipe'}</span><h2>{editingId ? draft.name || 'Edit recipe' : 'Build a workflow'}</h2></div>{editingId && <div className="browser-recipes__record-actions"><button type="button" className="quiet-button" disabled={busy || runBusy} onClick={() => { const recipe = recipes.find((item) => item.recipe_id === editingId); if (recipe) { setRunRecipe(recipe); setRunInputs({}); setRunEvents([]); setRunStatus('Ready') } }}>Run saved version</button><button type="button" className="quiet-button" disabled={busy || runBusy} onClick={() => { const recipe = recipes.find((item) => item.recipe_id === editingId); if (recipe) void toggleEnabled(recipe) }}>{recipes.find((item) => item.recipe_id === editingId)?.enabled ? 'Disable' : 'Enable'}</button><button type="button" className="icon-button icon-button--danger" disabled={busy || runBusy} onClick={() => { const recipe = recipes.find((item) => item.recipe_id === editingId); if (recipe) void remove(recipe) }} aria-label="Delete recipe and history"><Trash2 size={14} /></button></div>}</div>
        <label className="browser-recipes__field">Recipe name<input required maxLength={120} value={draft.name} onChange={(event) => setDraft((value) => ({ ...value, name: event.target.value }))} placeholder="e.g. Check order status" /></label>
        <label className="browser-recipes__field">Allowed hosts <small>Exact public hostnames, comma separated. No wildcards.</small><input required value={draft.allowed_domains.join(', ')} onChange={(event) => setDraft((value) => ({ ...value, allowed_domains: event.target.value.split(',') }))} placeholder="example.com" /></label>
        <div className="browser-recipes__section-head"><div><h3>Inputs</h3><small>Values are requested during execution and are not saved.</small></div><button type="button" className="quiet-button" onClick={addInput}><Plus size={13} /> Add input</button></div>
        {draft.inputs.map((input, index) => <div className="browser-recipes__input-row" key={`${input.name}-${index}`}><input aria-label="Input name" pattern="[a-z][a-z0-9_]{0,39}" required value={input.name} onChange={(event) => setDraft((value) => ({ ...value, inputs: value.inputs.map((item, i) => i === index ? { ...item, name: event.target.value } : item) }))} /><input aria-label="Input label" required placeholder="What should the user enter?" value={input.label} onChange={(event) => setDraft((value) => ({ ...value, inputs: value.inputs.map((item, i) => i === index ? { ...item, label: event.target.value } : item) }))} /><select aria-label="Input type" value={input.type} onChange={(event) => setDraft((value) => ({ ...value, inputs: value.inputs.map((item, i) => i === index ? { ...item, type: event.target.value as RecipeInput['type'] } : item) }))}><option value="text">Text</option><option value="url">URL</option></select><label className="browser-recipes__required"><input type="checkbox" checked={input.required} onChange={(event) => setDraft((value) => ({ ...value, inputs: value.inputs.map((item, i) => i === index ? { ...item, required: event.target.checked } : item) }))} /><span>Required</span></label><button type="button" className="icon-button" aria-label="Remove input" onClick={() => setDraft((value) => ({ ...value, inputs: value.inputs.filter((_, i) => i !== index) }))}><X size={13} /></button></div>)}
        <div className="browser-recipes__section-head"><div><h3>Steps</h3><small>Each step uses accessible names and must match its stop condition.</small></div><button type="button" className="quiet-button" onClick={addStep}><Plus size={13} /> Add step</button></div>
        {draft.steps.map((step, index) => <fieldset className="browser-recipes__step" key={index}><legend>Step {index + 1}</legend><div className="browser-recipes__step-top"><select aria-label={`Step ${index + 1} action`} value={step.action} onChange={(event) => { const action = event.target.value as RecipeStep['action']; changeStep(index, { action, role: roleFor(action), target_name: '', input_ref: '', url: action === 'navigate' ? 'https://' : '', direction: action === 'scroll' ? 'down' : undefined }) }}><option value="navigate">Open allowed URL</option><option value="click">Click a named link</option><option value="type">Type a named field</option><option value="select">Select an option</option><option value="scroll">Scroll</option></select><button type="button" className="icon-button" aria-label={`Remove step ${index + 1}`} disabled={draft.steps.length <= 1} onClick={() => setDraft((value) => ({ ...value, steps: value.steps.filter((_, i) => i !== index) }))}><X size={13} /></button></div>
          {step.action === 'navigate' && <label className="browser-recipes__field">Page URL<input required type="url" value={step.url || ''} onChange={(event) => changeStep(index, { url: event.target.value })} placeholder="https://example.com/orders" /></label>}
          {['click', 'type', 'select'].includes(step.action) && <><label className="browser-recipes__field">Accessible name<input required maxLength={160} value={step.target_name || ''} onChange={(event) => changeStep(index, { target_name: event.target.value })} placeholder={step.action === 'click' ? 'Order details' : 'Order number'} /></label>{step.input_ref !== undefined && <label className="browser-recipes__field">Input value<select required value={step.input_ref || ''} onChange={(event) => changeStep(index, { input_ref: event.target.value })}><option value="">Choose an input</option>{draft.inputs.map((item) => <option key={item.name} value={item.name}>{item.label || item.name}</option>)}</select></label>}</>}
          {step.action === 'scroll' && <label className="browser-recipes__field">Direction<select value={step.direction || 'down'} onChange={(event) => changeStep(index, { direction: event.target.value as 'up' | 'down' })}><option value="down">Down</option><option value="up">Up</option></select></label>}
          <div className="browser-recipes__checkpoint"><span>Stop condition<br />Set title or text</span><input maxLength={160} aria-label={`Step ${index + 1} expected page title`} value={step.checkpoint?.title_contains || ''} onChange={(event) => changeStep(index, { checkpoint: { ...step.checkpoint, title_contains: event.target.value } })} placeholder="Expected page title contains…" /><input maxLength={300} aria-label={`Step ${index + 1} expected page text`} value={step.checkpoint?.text_contains || ''} onChange={(event) => changeStep(index, { checkpoint: { ...step.checkpoint, text_contains: event.target.value } })} placeholder="Expected visible text contains…" /></div>
        </fieldset>)}
        <div className="browser-recipes__approval"><Check size={14} /><span><b>Approval required on every run</b><small>Each saved workflow version is reviewed before execution. Buttons and form submission are unavailable.</small></span></div>
        {editingId && versions.length > 0 && <details className="browser-recipes__history"><summary>Version history ({versions.length})</summary>{versions.map((version) => <details className="browser-recipes__version" key={version.version}><summary><b>Version {version.version}</b><small>{new Date(version.created_at).toLocaleString()}</small></summary><pre>{JSON.stringify(version.definition, null, 2)}</pre></details>)}</details>}
        <div className="browser-recipes__footer"><span>{editingId ? `Saving creates version ${expectedVersion + 1}.` : 'This recipe will not run until explicitly started.'}</span><button className="action-button" type="submit" disabled={busy}><Save size={14} /> {busy ? 'Saving…' : editingId ? 'Save new version' : 'Save recipe'}</button></div>
      </form>
    </div>
    {runRecipe && <section className="panel browser-recipes__run" aria-label="Run browser recipe">
      <div className="browser-recipes__run-head"><div><span className="eyebrow">Explicit recipe run</span><h2>{runRecipe.name}</h2><p>Version {runRecipe.version} · {runRecipe.allowed_domains.join(', ')} · approval before every step</p></div><button type="button" className="icon-button" disabled={runBusy} onClick={() => { setRunRecipe(null); setRunEvents([]); setRunStatus('') }} aria-label="Close run panel"><X size={14} /></button></div>
      {runStatus === 'Ready' && <form className="browser-recipes__run-form" onSubmit={(event) => void startRun(event)}>
        {runRecipe.inputs.map((input) => <label className="browser-recipes__field" key={input.name}>{input.label || input.name}{input.required && <small>Required</small>}<input type={input.type === 'url' ? 'url' : 'text'} required={input.required} maxLength={1000} value={runInputs[input.name] || ''} onChange={(event) => setRunInputs((current) => ({ ...current, [input.name]: event.target.value }))} placeholder={input.type === 'url' ? 'https://example.com/…' : 'Enter this value for this run'} /></label>)}
        {runRecipe.inputs.length === 0 && <p className="browser-recipes__empty">This recipe has no run-time inputs.</p>}
        <p className="browser-recipes__privacy">Inputs stay in memory for this run and are not saved to recipe history or run events.</p>
        <button className="action-button" type="submit" disabled={runBusy || !runRecipe.enabled}>{runBusy ? 'Starting…' : `Run version ${runRecipe.version}`}</button>
      </form>}
      {runStatus && runStatus !== 'Ready' && <div className="browser-recipes__run-status" role="status">Run status: <b>{runStatus}</b>{runBusy && <span className="live-label"><span /> Live</span>}</div>}
      {pendingApprovals.map((approval) => <div className="browser-recipes__run-approval" key={String(approval.approval_id)}><div><b>Approval required · step {String((approval.action as Record<string, unknown> | undefined)?.step || '')}</b><small>{String(approval.message || 'Review this recipe step before it runs.')}</small><small>{String((approval.action as Record<string, unknown> | undefined)?.action || '')} · {String((approval.action as Record<string, unknown> | undefined)?.target || '')}</small></div><div><button type="button" className="action-button" disabled={!runBusy || approvalBusy === approval.approval_id} onClick={() => void resolveApproval(approval, 'approved')}>Approve</button><button type="button" className="quiet-button" disabled={!runBusy || approvalBusy === approval.approval_id} onClick={() => void resolveApproval(approval, 'rejected')}>Reject</button></div></div>)}
      {runEvents.length > 0 && <div className="browser-recipes__run-events" aria-live="polite">{runEvents.map((item, index) => {
        const type = String(item.type || 'activity')
        const action = item.action && typeof item.action === 'object' ? String((item.action as Record<string, unknown>).action || '') : String(item.action || '')
        if (type === 'approval_requested') return <div className="browser-recipes__run-event" key={String(item.sequence ?? index)}><span>Approval requested</span><small>{String(item.message || '')}</small></div>
        if (type === 'recipe_step_started') return <div className="browser-recipes__run-event" key={String(item.sequence ?? index)}><span>Step {String(item.step)} · {action}</span><small>Waiting for approval and page action</small></div>
        if (type === 'recipe_step_result') return <div className="browser-recipes__run-event" key={String(item.sequence ?? index)}><span>Step {String(item.step)} · {String(item.status)}</span><small>{String(item.title || '')} · {String(item.url || '')}</small></div>
        if (type === 'browser_screenshot') return <div className="browser-recipes__run-event" key={String(item.sequence ?? index)}><span>{String(item.name || 'Page screenshot')}</span>{typeof item.url === 'string' && <a href={item.url} target="_blank" rel="noreferrer"><img src={item.url} alt={`Screenshot for ${String(item.name || 'recipe step')}`} loading="lazy" /></a>}</div>
        if (type === 'recipe_run_started' || type === 'recipe_run_finished' || type === 'done' || type === 'error' || type === 'cancelled' || type === 'timed_out' || type === 'approval_approved' || type === 'approval_rejected' || type === 'approval_expired') return <div className="browser-recipes__run-event" key={String(item.sequence ?? index)}><span>{type.replaceAll('_', ' ')}</span><small>{String(item.message || item.status || '')}</small></div>
        return null
      })}</div>}
    </section>}
  </section>
}
