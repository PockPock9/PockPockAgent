import { useCallback, useEffect, useLayoutEffect, useRef, useState } from 'react'
import type { Dispatch, SetStateAction } from 'react'
import { AgentWorkbench } from '../agents/AgentWorkbench'
import type { PlanDecision, RoutedTask } from '../agents/agentTypes'
import type { AppState } from '../models/modelTypes'
import { CodeBlock } from './ChatTimeline'
import { ChatView } from './ChatView'
import type { Conversation, PendingToolAction } from './chatTypes'
import { conversationTitle, createId } from './chatUtils'

const markdownComponents = { pre: CodeBlock }

export function ChatWorkspace({
  state,
  conversations,
  setConversations,
  activeId,
  setActiveId,
  newChat,
  onOpenExtensions,
}: {
  state: AppState
  conversations: Conversation[]
  setConversations: Dispatch<SetStateAction<Conversation[]>>
  activeId: string
  setActiveId: (id: string) => void
  newChat: () => void
  onOpenExtensions: (kind: 'skills' | 'mcp') => void
}) {
  const [agentTask, setAgentTask] = useState<RoutedTask | null>(null)
  const [toolBusy, setToolBusy] = useState(false)
  const [stopTool, setStopTool] = useState<(() => void) | null>(null)
  const registerStop = useCallback((stop: (() => void) | null) => setStopTool(() => stop), [])
  const conversationsRef = useRef(conversations)
  useLayoutEffect(() => {
    conversationsRef.current = conversations
  }, [conversations])
  const planDecisionResolvers = useRef(new Map<string, (decision: PlanDecision) => void>())
  const registerPlanDecision = useCallback((runId: string, resolver: (decision: PlanDecision) => void) => {
    planDecisionResolvers.current.set(runId, resolver)
  }, [])
  const resolvePlanDecision = useCallback((runId: string, decision: PlanDecision) => {
    const resolver = planDecisionResolvers.current.get(runId)
    if (!resolver) return
    planDecisionResolvers.current.delete(runId)
    resolver(decision)
  }, [])
  const clearAllChats = useCallback(() => {
    stopTool?.()
    planDecisionResolvers.current.clear()
    conversationsRef.current = []
    setAgentTask(null)
    setToolBusy(false)
    setStopTool(null)
    setConversations([])
    setActiveId('')
  }, [setActiveId, setConversations, stopTool])

  const reportToolUpdate = useCallback((runId: string, text: string, sequence?: number, final = false) => {
    if (final) setToolBusy(false)
    const conversationId = conversationsRef.current.find((conversation) => conversation.messages.some((message) => message.toolRunId === runId))?.id
    if (!conversationId) return
    setConversations((previous) => previous.map((conversation) => conversation.id !== conversationId ? conversation : {
      ...conversation,
      updatedAt: Date.now(),
      messages: conversation.messages.map((message) => message.toolRunId === runId
        ? typeof sequence === 'number' && Number.isFinite(sequence) && sequence <= (message.toolSequence ?? 0)
          ? message
          : { ...message, content: `${message.content}${text.startsWith('**') && message.content ? '\n\n' : ''}${text}`, toolSequence: typeof sequence === 'number' && Number.isFinite(sequence) ? sequence : message.toolSequence, error: final && text.startsWith('**Task failed:') }
        : message),
    }))
  }, [setConversations])

  const reportToolEvent = useCallback((runId: string, event: Record<string, unknown>) => {
    if (event.type === 'token') return
    if (['done', 'error', 'cancelled', 'timed_out', 'interrupted'].includes(String(event.type))) setToolBusy(false)
    const conversationId = conversationsRef.current.find((conversation) => conversation.messages.some((message) => message.toolRunId === runId))?.id
    if (!conversationId) return
    setConversations((previous) => previous.map((conversation) => conversation.id !== conversationId ? conversation : {
      ...conversation, updatedAt: Date.now(), messages: conversation.messages.map((message) => {
        if (message.toolRunId !== runId) return message
        const sequence = Number(event.sequence)
        const events = message.runEvents ?? []
        if (Number.isFinite(sequence) && events.some((item) => item.sequence === sequence)) return message
        return { ...message, runEvents: [...events, { ...event, ...(Number.isFinite(sequence) ? { sequence } : {}) }].sort((left, right) => (left.sequence ?? 0) - (right.sequence ?? 0)) }
      }),
    }))
  }, [setConversations])

  const activeRunIds = conversations.find((item) => item.id === activeId)?.messages.map((item) => item.toolRunId).join(',')

  useEffect(() => {
    if (!activeId) return
    let cancelled = false
    void (async () => {
      try {
        let runs: Array<{ run_id: string }> = []
        for (let attempt = 0; attempt < 12 && !cancelled; attempt += 1) {
          const response = await fetch(`/api/conversations/${encodeURIComponent(activeId)}/runs`)
          if (!response.ok) return
          runs = (await response.json() as { runs: Array<{ run_id: string }> }).runs
          const expectedIds = conversationsRef.current.find((item) => item.id === activeId)?.messages.map((item) => item.toolRunId).filter((id): id is string => Boolean(id)) ?? []
          if (expectedIds.every((id) => runs.some((run) => run.run_id === id))) break
          await new Promise((resolve) => window.setTimeout(resolve, 500))
        }
        for (const run of runs) {
          if (cancelled) return
          let after = conversationsRef.current.find((item) => item.id === activeId)?.messages.find((item) => item.toolRunId === run.run_id)?.toolSequence ?? 0
          let status = 'running'
          while (!cancelled && ['running', 'cancelling'].includes(status)) {
            const replay = await fetch(`/api/runs/${run.run_id}/events?after=${after}`)
            if (!replay.ok) break
            const result = await replay.json() as { run: { status: string }; events: Array<{ sequence: number; event: Record<string, unknown> }> }
            status = result.run.status
            for (const item of result.events) {
              if (cancelled) return
              after = item.sequence
              const event = item.event
              reportToolEvent(run.run_id, { ...event, sequence: item.sequence })
              let text = ''
              if (event.type === 'token') text = String(event.content || '')
              else if (event.type === 'error') text = `**Task failed:** ${String(event.message || 'Run failed')}`
              if (text) reportToolUpdate(run.run_id, text, item.sequence, event.type === 'error')
            }
            if (status === 'running' && result.events.length === 0) await new Promise((resolve) => window.setTimeout(resolve, 800))
          }
          if (!cancelled && status === 'interrupted') reportToolUpdate(run.run_id, '**Run interrupted. Review the activity above and rerun the task if needed.**', after + 1, true)
          if (!cancelled && status === 'cancelled') reportToolUpdate(run.run_id, '**Agent stopped.**', after + 1, true)
          if (!cancelled && status === 'timed_out') reportToolUpdate(run.run_id, '**Agent timed out. Review the activity above and rerun the task if needed.**', after + 1, true)
        }
      } catch { /* Run history remains available from the locally stored transcript. */ }
    })()
    return () => { cancelled = true }
  }, [activeId, activeRunIds, reportToolUpdate, reportToolEvent])

  const approveToolAction = (action: PendingToolAction) => {
    let request = action.request
    let conversationId = request.conversationId || activeId
    if (!conversationId) {
      conversationId = createId()
      setConversations((previous) => [{ id: conversationId, title: conversationTitle(request.sourceTask ?? request.task), updatedAt: Date.now(), messages: [] }, ...previous])
      setActiveId(conversationId)
    }
    request = { ...request, conversationId }
    setToolBusy(true)
    setConversations((previous) => previous.map((conversation) => conversation.id !== conversationId ? conversation : {
      ...conversation, updatedAt: Date.now(),
      title: conversation.messages.length ? conversation.title : conversationTitle(request.sourceTask ?? request.task),
      messages: [...conversation.messages,
        { role: 'user' as const, content: request.sourceTask ?? request.task },
        { role: 'assistant' as const, content: '', toolRunId: request.id },
      ],
    }))
    setAgentTask(request)
  }

  return (
    <div className="chat-workspace">
      <div>
        <ChatView
          state={state}
          conversations={conversations}
          setConversations={setConversations}
          activeId={activeId}
          setActiveId={setActiveId}
          newChat={newChat}
          toolBusy={toolBusy}
          onStopTool={() => stopTool?.()}
          onApproveToolAction={approveToolAction}
          onPlanDecision={resolvePlanDecision}
          onClearAllChats={clearAllChats}
          onOpenExtensions={onOpenExtensions}
        />
      </div>
      <div hidden><AgentWorkbench state={state} autoStartTask={agentTask} onTranscriptUpdate={reportToolUpdate} onTranscriptEvent={reportToolEvent} onStopChange={registerStop} onPlanDecisionRequest={registerPlanDecision} markdownComponents={markdownComponents} /></div>
    </div>
  )
}

