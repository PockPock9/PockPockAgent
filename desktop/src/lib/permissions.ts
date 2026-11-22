// What each permission mode allows, as shown in the pickers and the inspector.
import type { AgentPermission, ClawPermission } from './types'

export const CLAW_PERMISSION: Record<ClawPermission, { title: string; detail: string }> = {
  ask: { title: 'Ask first', detail: 'Every action waits for you to allow or deny it.' },
  auto: { title: 'Auto-approve safe', detail: 'Reading files and read-only commands run on their own. Everything else asks.' },
  full: { title: 'Full access', detail: 'Nothing asks. The agent can run any command and change any file on this PC.' },
}
export const AGENT_PERMISSION: Record<AgentPermission, { title: string; detail: string }> = {
  default: { title: 'Default', detail: 'Read-only tools. File changes are not allowed.' },
  'auto-review': { title: 'Auto-review', detail: 'Changes inside the task folder; risky actions ask first.' },
  'full-access': { title: 'Full access', detail: 'Reads and edits inside the task folder without asking; no arbitrary shell.' },
}
