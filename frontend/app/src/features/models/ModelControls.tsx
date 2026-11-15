import { Play, RefreshCw, X } from 'lucide-react'
import type { OllamaFeedbackState } from './modelTypes'

export function StatusMark({ online }: { online: boolean }) {
  return <span className={`status-mark${online ? ' status-mark--on' : ''}`} aria-hidden="true" />
}

export function OllamaActionButton({
  connected,
  pending,
  disabled,
  onClick,
}: {
  connected: boolean
  pending: boolean
  disabled: boolean
  onClick: () => void
}) {
  return (
    <button className="ollama-action" onClick={onClick} disabled={disabled || pending}>
      {pending ? <RefreshCw size={13} className="spin" /> : connected ? <RefreshCw size={13} /> : <Play size={13} />}
      {pending ? 'Connecting…' : connected ? 'Refresh inventory' : 'Connect / Start Ollama'}
    </button>
  )
}

export function OllamaFeedback({ feedback, onDismiss }: { feedback: OllamaFeedbackState; onDismiss: () => void }) {
  if (!feedback) return null
  return (
    <div className={`notice-banner notice-banner--${feedback.error ? 'error' : 'success'}`} role="status">
      <StatusMark online={!feedback.error} />
      <span>{feedback.message}</span>
      <button onClick={onDismiss} aria-label="Dismiss Ollama status"><X size={13} /></button>
    </div>
  )
}
