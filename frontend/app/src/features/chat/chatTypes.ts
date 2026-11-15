import type { RoutedTask } from '../agents/agentTypes'

export type Attachment = {
  name: string
  kind: 'image' | 'document'
  mime?: string
  data?: string
  text?: string
  size: number
}

/** One tool call made by an OpenClaw turn, shown as an activity line above the reply. */
export type ClawStep = {
  id: string
  title: string
  status: 'running' | 'completed' | 'failed' | 'blocked' | 'stopped'
  error?: string
}

export type ChatMessage = {
  role: 'user' | 'assistant'
  content: string
  attachments?: Attachment[]
  model?: string
  category?: string
  error?: boolean
  toolRunId?: string
  toolSequence?: number
  runEvents?: Array<Record<string, unknown> & { sequence?: number }>
  clawSteps?: ClawStep[]
}

export type Conversation = {
  id: string
  title: string
  updatedAt: number
  messages: ChatMessage[]
}

export type PendingToolAction = {
  target: 'agent'
  summary: string
  request: RoutedTask
}

export type ResearchSnapshot = {
  snapshot_id: number
  captured_at: string
  content_hash: string
  byte_count: number
  truncated: boolean
  text?: string
}

export type SavedResearchSource = {
  source: Record<string, unknown>
  notes: string
  created_at: string
  updated_at: string
  last_checked_at: string
  version_count: number
  versions: ResearchSnapshot[]
  latest: ResearchSnapshot | null
}

export type SavedResearchCollection = {
  task_id: string
  created_at: string
  updated_at: string
  sources: SavedResearchSource[]
}
