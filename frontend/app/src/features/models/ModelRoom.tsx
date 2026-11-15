import { useMemo, useState } from 'react'
import { Check, CircleHelp, RefreshCw, Server, Shield, X } from 'lucide-react'
import { OllamaActionButton, OllamaFeedback, StatusMark } from './ModelControls'
import type { AppState, Model, OllamaFeedbackState } from './modelTypes'
import { formatBytes, modelFamily } from './modelUtils'

export function ModelRoom({
  state,
  refresh,
  onOllamaAction,
  ollamaPending,
  ollamaFeedback,
  onDismissOllamaFeedback,
}: {
  state: AppState
  refresh: () => Promise<unknown>
  onOllamaAction: () => void
  ollamaPending: boolean
  ollamaFeedback: OllamaFeedbackState
  onDismissOllamaFeedback: () => void
}) {
  const [pending, setPending] = useState('')
  const [error, setError] = useState('')

  const toggleModel = async (model: Model) => {
    setPending(model.name)
    setError('')
    try {
      const response = await fetch(`/api/models/${encodeURIComponent(model.name)}`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ enabled: !model.enabled }),
      })
      const result = await response.json()
      if (!response.ok) throw new Error(result.detail || 'Could not change model state')
      await refresh()
    } catch (requestError) {
      setError(requestError instanceof Error ? requestError.message : 'Could not change model state')
    } finally {
      setPending('')
    }
  }

  const totalSize = useMemo(() => state.models.reduce((total, model) => total + (model.size || 0), 0), [state.models])

  return (
    <div className="page models-page">
      <div className="page-title">
        <div><div className="eyebrow"><span className="eyebrow__rule" />Local / Model inventory</div><h1>Model room<span>.</span></h1><p>Installed weights, live runtime state, and routing eligibility.</p></div>
        <div className="model-management-actions">
          <div className="model-summary"><span>{state.models.length} installed</span><span>{formatBytes(totalSize)} on disk</span></div>
          <OllamaActionButton connected={state.connected} pending={ollamaPending} disabled={!state.api_connected} onClick={onOllamaAction} />
        </div>
      </div>
      {!state.connected && <div className="notice-banner"><CircleHelp size={15} /><span>{state.error || 'Ollama is offline.'} Model controls require Ollama to be running.</span></div>}
      <OllamaFeedback feedback={ollamaFeedback} onDismiss={onDismissOllamaFeedback} />
      {error && <div className="notice-banner notice-banner--error"><CircleHelp size={15} /><span>{error}</span><button onClick={() => setError('')}><X size={13} /></button></div>}

      <div className="model-grid">
        {!state.models.length && <div className="panel models-empty"><Server size={21} /><strong>{state.connected ? 'No Ollama models installed' : 'No Ollama models found'}</strong><span>{state.connected ? 'Ollama is connected. Install a model before chatting.' : 'Connect or start Ollama to load the installed-model inventory.'}</span></div>}
        {state.models.map((model) => {
          const isClassifier = model.name === state.classifier
          return (
            <article className={`panel model-card${model.enabled ? '' : ' model-card--disabled'}`} key={model.name}>
              <div className="model-card__head">
                <span className="model-card__type">{modelFamily(model.name)}{isClassifier && <b>Router</b>}</span>
                <StatusMark online={model.running} />
              </div>
              <h2>{model.name}</h2>
              <div className="model-card__meta"><span>{formatBytes(model.size || 0)}</span><span>{model.running ? 'In GPU memory' : 'On disk'}</span></div>
              <div className="model-card__usage"><span>{model.calls ?? 0} calls</span><span>{model.decisions ?? 0} decisions</span></div>
              <div className="model-card__bottom">
                <span className={`model-enabled${model.enabled ? ' model-enabled--yes' : ''}`}>{model.enabled ? 'Routable' : 'Excluded'}</span>
                <button className={`model-switch${model.enabled ? ' model-switch--on' : ''}`} onClick={() => void toggleModel(model)} disabled={pending !== '' || isClassifier} aria-label={`${model.enabled ? 'Disable' : 'Enable'} ${model.name}`} aria-pressed={model.enabled}>
                  {pending === model.name ? <RefreshCw size={13} className="spin" /> : model.enabled ? <Check size={13} /> : <X size={13} />}
                </button>
              </div>
              {isClassifier && <div className="model-lock"><Shield size={11} /> Classifier stays enabled for automatic routing.</div>}
            </article>
          )
        })}
      </div>
      <div className="overview-footnote"><Shield size={13} /> Enablement applies only to PockPock AI; Ollama weights and Open WebUI access are unchanged. The classifier stays enabled.</div>
    </div>
  )
}
