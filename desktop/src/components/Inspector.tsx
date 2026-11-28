// The right inspector: Context (engine, model, where it runs, context used, permission, folders and
// files the run touched), Files (the open folder), and Terminal (the panel under the composer).
import { useRef } from 'react'
import type { KeyboardEvent, ReactNode } from 'react'
import { FileText, FolderOpen, SquareTerminal, X } from 'lucide-react'
import { bridge, ENGINE_LABEL } from '../lib/types'
import type { Message, Settings } from '../lib/types'
import type { Status } from '../lib/status'
import { AGENT_PERMISSION, CLAW_PERMISSION } from '../lib/permissions'
import { FilesPanel } from './FilesPanel'
import { IconButton } from './ui'
import { mod } from '../lib/platform'

export type InspectorTab = 'context' | 'files' | 'terminal'
const TABS: Array<{ id: InspectorTab; label: string }> = [{ id: 'context', label: 'Context' }, { id: 'files', label: 'Files' }, { id: 'terminal', label: 'Terminal' }]

function tokens(count: number) {
  // Context sizes are powers of two (32768 = "32k"); token counts are shown in thousands.
  if (count >= 1024 && count % 1024 === 0) return `${count / 1024}k`
  return count >= 1000 ? `${(count / 1000).toFixed(1)}k` : String(count)
}

function Row({ label, children }: { label: string; children: ReactNode }) {
  return <div className="kv"><span>{label}</span><span>{children}</span></div>
}

export function Inspector({ tab, onTab, overlay, message, settings, status, terminalOpen, onToggleTerminal, onChooseFolder, onAttach, onClose }: {
  tab: InspectorTab
  onTab: (tab: InspectorTab) => void
  overlay?: boolean
  /** The newest assistant turn of the open task, if any. */
  message?: Message
  settings: Settings
  status: Status
  terminalOpen: boolean
  onToggleTerminal: () => void
  onChooseFolder: () => void
  onAttach: (file: { name: string; text: string; size: number }) => void
  onClose: () => void
}) {
  const tabRefs = useRef<Array<HTMLButtonElement | null>>([])
  const onKey = (event: KeyboardEvent) => {
    const index = TABS.findIndex((item) => item.id === tab)
    const step = event.key === 'ArrowRight' ? 1 : event.key === 'ArrowLeft' ? -1 : 0
    if (!step) return
    event.preventDefault()
    const next = (index + step + TABS.length) % TABS.length
    onTab(TABS[next].id)
    tabRefs.current[next]?.focus()
  }
  const engine = message?.engine ?? settings.engine ?? 'agent'
  const modelName = message?.model?.split(' · ')[0] || (settings.chatModel && settings.chatModel !== 'auto' ? settings.chatModel : '')
  const cloud = status.state?.cloud_models?.find((model) => model.name === modelName)
  const local = status.state?.models.find((model) => model.name === modelName || model.name === `${modelName}:latest`)
  const where = cloud ? `Cloud · ${cloud.provider_label}` : local ? `This PC · ${local.running ? 'loaded' : 'not loaded'}` : engine === 'openclaw' ? 'OpenClaw on this PC' : '—'
  const usage = message?.usage
  const permission = engine === 'openclaw' ? CLAW_PERMISSION[settings.clawPermission ?? 'ask'] : engine === 'agent' ? AGENT_PERMISSION[settings.agentPermission ?? 'auto-review'] : null
  const taskFolder = message?.taskFolder || (message?.runId && status.state?.output_directory ? `${status.state.output_directory}${status.state.output_directory.includes('\\') ? '\\' : '/'}${message.runId}` : '')
  const touched = message?.touched ?? []
  return (
    <aside className={`inspector${overlay ? ' is-overlay' : ''}`} aria-label="Inspector">
      <div className="inspector__tabs">
        <div role="tablist" aria-label="Inspector" onKeyDown={onKey}>
          {TABS.map((item, index) => (
            <button key={item.id} ref={(node) => { tabRefs.current[index] = node }} type="button" role="tab" id={`inspector-tab-${item.id}`} aria-controls={`inspector-panel-${item.id}`}
              aria-selected={tab === item.id} tabIndex={tab === item.id ? 0 : -1} className={tab === item.id ? 'is-active' : ''} onClick={() => onTab(item.id)}>{item.label}</button>
          ))}
        </div>
        <IconButton label={`Close inspector (${mod}Shift+E)`} onClick={onClose}><X size={14} /></IconButton>
      </div>
      <div role="tabpanel" id={`inspector-panel-${tab}`} aria-labelledby={`inspector-tab-${tab}`} className="inspector__panel">
        {tab === 'context' && (
          <>
            <section className="inspector__section">
              <h3>Model</h3>
              <Row label="Engine">{ENGINE_LABEL[engine]}</Row>
              <Row label="Model">{modelName || (engine === 'chat' || engine === 'agent' ? 'Smart route' : 'Engine default')}</Row>
              <Row label="Where">{where}</Row>
              {usage ? (
                <div className="inspector__meter">
                  <div className="kv"><span>Context used</span><span>{tokens(usage.promptTokens)}{usage.contextWindow ? ` / ${tokens(usage.contextWindow)}` : ' tokens'}</span></div>
                  {usage.contextWindow ? <div className="meter" role="meter" aria-label="Context used" aria-valuemin={0} aria-valuemax={usage.contextWindow} aria-valuenow={Math.min(usage.promptTokens, usage.contextWindow)}><i style={{ width: `${Math.min(100, (usage.promptTokens / usage.contextWindow) * 100)}%` }} /></div> : null}
                </div>
              ) : <Row label="Context used">{engine === 'agent' ? 'Shown once the agent calls the model' : 'Not reported by this engine'}</Row>}
            </section>
            {permission && (
              <section className="inspector__section">
                <h3>Permission</h3>
                <Row label="Mode">{permission.title}</Row>
                <p className="inspector__hint">{permission.detail}</p>
              </section>
            )}
            <section className="inspector__section">
              <h3>Folders</h3>
              <Row label="Workspace">{settings.workspace && settings.useWorkspaceForAgent !== false ? <span className="mono" title={settings.workspace}>{settings.workspace.split(/[\\/]/).filter(Boolean).at(-1)}</span> : engine === 'openclaw' ? "OpenClaw's workspace" : 'A new task folder'}</Row>
              <Row label="Task folder">{taskFolder ? <button type="button" className="link-button" title={taskFolder} onClick={() => void bridge()?.openPath(taskFolder)}><FolderOpen size={12} /> Open</button> : engine === 'agent' ? 'Created when a run starts' : '—'}</Row>
            </section>
            <section className="inspector__section">
              <h3>Files touched</h3>
              {touched.length ? (
                <ul className="touched">
                  {touched.slice(-40).map((file) => <li key={file.path}><FileText size={13} aria-hidden="true" /><span className="mono" title={file.path}>{file.path.split(/[\\/]/).at(-1)}</span><em>{file.kind}</em></li>)}
                </ul>
              ) : <p className="inspector__hint">{message ? 'This run has not read or changed any files.' : 'Files the agent reads, changes or saves are listed here.'}</p>}
            </section>
          </>
        )}
        {tab === 'files' && <FilesPanel embedded workspace={settings.workspace} onChooseFolder={onChooseFolder} onAttach={onAttach} />}
        {tab === 'terminal' && (
          <section className="inspector__section">
            <h3>Terminal</h3>
            <p className="inspector__hint">The terminal opens in the panel under the composer, in {settings.workspace ? 'the open folder' : 'your home folder'}.</p>
            <button type="button" className="button" onClick={onToggleTerminal}><SquareTerminal size={13} /> {terminalOpen ? 'Close the terminal' : 'Open the terminal'} <kbd>{mod}J</kbd></button>
          </section>
        )}
      </div>
    </aside>
  )
}
