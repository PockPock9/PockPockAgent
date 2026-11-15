export type Model = {
  name: string
  size: number
  details?: Record<string, unknown>
  enabled: boolean
  running: boolean
  calls?: number
  decisions?: number
  successes?: number
  avg_ms?: number | null
}

export type Trace = {
  id: number
  created_at: string
  request_id: string
  call_id: string
  event: string
  model: string
  automatic_model: string
  role: string
  status: string
  category: string
  source: string
  reason: string
  error: string
  confidence: number | null
  complexity: number | null
  duration_ms: number | null
}

export type AppState = {
  api_connected: boolean
  connected: boolean
  error: string
  router_enabled: boolean
  classifier: string
  models: Model[]
  events: Trace[]
  active: Array<{ model: string; role: string; call_id: string }>
  totals: { requests?: number; calls?: number; avg_ms?: number | null }
}

export type OllamaFeedbackState = { message: string; error: boolean } | null
