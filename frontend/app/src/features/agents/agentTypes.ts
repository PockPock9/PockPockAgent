export type AgentFile = { name: string; text: string; size: number }
export type AgentArtifact = { name: string; path: string; kind: string; url: string }

export type AgentStatus = {
  available: boolean
  execution_scope: string
  image_engine: { available: boolean; engine: string | null }
  output_directory: string
}

export type RoutedTask = {
  id: string
  task: string
  sourceTask?: string
  files: AgentFile[]
  conversationId?: string
  permissionMode?: 'default' | 'auto-review' | 'full-access'
  preferredModel?: string
  workspacePath?: string
}

export type PlanDecision = {
  decision: 'approved' | 'rejected'
  plan: string[]
  successChecks: string[]
  planId?: string
  planHash?: string
  versionHash?: string
}
