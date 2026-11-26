// Composer pickers: the plus menu (attach, folder, Skills, MCP servers, report), the engine,
// permission (PockPock Agent and OpenClaw) and model menus. Each opens above its button with a title
// and one line per option; arrow keys move, Escape closes and returns focus (ui.tsx Popover).
import { useEffect, useState, type ReactNode } from 'react'
import { Bot, ChevronDown, Cloud, Download, Flag, Folder, Image as ImageIcon, LoaderCircle, Paperclip, Plug, Plus, Puzzle, Shield, ShieldOff, Sparkles } from 'lucide-react'
import type { Status } from '../lib/status'
import { ENGINE_LABEL } from '../lib/types'
import type { AgentPermission, ClawPermission, Engine, NemoRoute, Settings } from '../lib/types'
import { AGENT_PERMISSION, CLAW_PERMISSION } from '../lib/permissions'
import { MenuItem, Popover } from './ui'

/** The optional uncensored OpenClaw model (electron/model-pull.cjs): a community Qwen 3.5 9B with its refusals removed. */
export const UNCENSORED_MODEL = 'huihui_ai/qwen3.5-abliterated:9b'

export type Menu = 'attach' | 'engine' | 'permission' | 'model' | null

function Toggle({ menu, id, label, className = 'pill', children, onToggle, disabled }: { menu: Menu; id: Exclude<Menu, null>; label: string; className?: string; children: ReactNode; onToggle: (id: Menu) => void; disabled?: boolean }) {
  return (
    <button type="button" className={className} aria-haspopup="menu" aria-expanded={menu === id} data-popover-toggle={menu === id ? 'open' : undefined} aria-label={label} disabled={disabled} onClick={() => onToggle(menu === id ? null : id)}>
      {children}
    </button>
  )
}

export function PlusMenu({ menu, onToggle, busy, counts, workspace, onAttach, onImage, onChooseFolder, onOpenPage }: {
  menu: Menu
  onToggle: (id: Menu) => void
  busy: boolean
  counts?: { skills?: number; mcp?: number }
  workspace?: string
  onAttach: () => void
  onImage: () => void
  onChooseFolder: () => void
  onOpenPage: (page: 'skills' | 'mcp' | 'maintenance') => void
}) {
  const close = (then: () => void) => () => { onToggle(null); then() }
  return (
    <div className="anchor">
      <Toggle menu={menu} id="attach" label="Attach and navigate" className="icon-button" onToggle={onToggle} disabled={busy}>
        {busy ? <LoaderCircle size={15} className="spin" /> : <Plus size={16} />}
      </Toggle>
      <Popover open={menu === 'attach'} onClose={() => onToggle(null)} label="Attach and navigate">
        <div className="popover__label">Attach</div>
        <MenuItem icon={<Paperclip size={14} />} title="Attach a file" detail="Text, PDF, Office files and spreadsheets" onSelect={close(onAttach)} />
        <MenuItem icon={<ImageIcon size={14} />} title="Add an image" detail="PNG and JPG; Chat and PockPock Agent" onSelect={close(onImage)} />
        <MenuItem icon={<Folder size={14} />} title={workspace ? 'Change folder' : 'Choose a folder'} detail="Let the agent work in it" onSelect={close(onChooseFolder)} />
        <div className="popover__label">Go to</div>
        <MenuItem icon={<Puzzle size={14} />} title="Skills" detail={counts?.skills !== undefined ? `${counts.skills} available` : 'Add or switch skills'} onSelect={close(() => onOpenPage('skills'))} />
        <MenuItem icon={<Plug size={14} />} title="MCP servers" detail={counts?.mcp !== undefined ? `${counts.mcp} connected` : 'Connect tool servers'} onSelect={close(() => onOpenPage('mcp'))} />
        <MenuItem icon={<Flag size={14} />} title="Report a problem" detail="Opens Maintenance" onSelect={close(() => onOpenPage('maintenance'))} />
      </Popover>
    </div>
  )
}

export function PermissionPicker({ menu, onToggle, engine, settings, status, patchSettings }: { menu: Menu; onToggle: (id: Menu) => void; engine: Engine; settings: Settings; status: Status; patchSettings: (change: Partial<Settings>) => void }) {
  if (engine !== 'openclaw' && engine !== 'agent') return null
  const clawPermission = settings.clawPermission ?? 'ask'
  const agentPermission = settings.agentPermission ?? 'auto-review'
  const risky = engine === 'openclaw' ? clawPermission === 'full' || clawPermission === 'full-auto' : agentPermission === 'full-access'
  const title = engine === 'openclaw' ? CLAW_PERMISSION[clawPermission].title : AGENT_PERMISSION[agentPermission].title
  const folderName = settings.workspace?.split(/[\\/]/).filter(Boolean).at(-1)
  const choose = (change: Partial<Settings>) => { patchSettings(change); onToggle(null) }
  return (
    <div className="anchor">
      <Toggle menu={menu} id="permission" label={`Permission: ${title}`} className={`pill${risky ? ' pill--danger' : ''}`} onToggle={onToggle}>
        <Shield size={13} /> {title} <ChevronDown size={12} aria-hidden="true" />
      </Toggle>
      <Popover open={menu === 'permission'} onClose={() => onToggle(null)} className="popover--wide" label={`Permission for ${ENGINE_LABEL[engine]}`}>
        <div className="popover__label">Permission · {ENGINE_LABEL[engine]}</div>
        {engine === 'openclaw'
          ? (Object.keys(CLAW_PERMISSION) as ClawPermission[]).map((key) => (
            <MenuItem key={key} icon={<Shield size={14} />} title={CLAW_PERMISSION[key].title} badge={key === 'full' || key === 'full-auto' ? 'Risky' : undefined} detail={CLAW_PERMISSION[key].detail} danger={key === 'full' || key === 'full-auto'} selected={clawPermission === key}
              disabled={key !== 'full' && key !== 'full-auto' && status.claw?.plugin === false} onSelect={() => choose({ clawPermission: key })} />
          ))
          : (Object.keys(AGENT_PERMISSION) as AgentPermission[]).map((key) => (
            <MenuItem key={key} icon={<Shield size={14} />} title={AGENT_PERMISSION[key].title} badge={key === 'full-access' ? 'Use with care' : undefined} detail={AGENT_PERMISSION[key].detail} danger={key === 'full-access'} selected={agentPermission === key} onSelect={() => choose({ agentPermission: key })} />
          ))}
        <div className="popover__label">Task folder</div>
        <MenuItem icon={<Folder size={14} />} title={settings.workspace ? `Work in ${folderName}` : 'Work in the open folder'} detail={settings.workspace ? (engine === 'openclaw' ? 'Commands run here, and files without a full path are read and saved here.' : 'The agent reads and edits files in this folder.') : 'Open a folder first.'} disabled={!settings.workspace}
          selected={Boolean(settings.workspace && settings.useWorkspaceForAgent !== false)} onSelect={() => choose({ useWorkspaceForAgent: true })} />
        {engine === 'openclaw'
          ? <MenuItem icon={<Folder size={14} />} title="Use OpenClaw's workspace" detail="OpenClaw's own folder in your user profile (.openclaw\workspace)." selected={!settings.workspace || settings.useWorkspaceForAgent === false} onSelect={() => choose({ useWorkspaceForAgent: false })} />
          : <MenuItem icon={<Folder size={14} />} title="Use a new temporary folder" detail="Each task gets an empty folder." selected={!settings.workspace || settings.useWorkspaceForAgent === false} onSelect={() => choose({ useWorkspaceForAgent: false })} />}
      </Popover>
    </div>
  )
}

export function ModelPicker({ menu, onToggle, engine, settings, status, patchSettings, label, nemo }: {
  menu: Menu
  onToggle: (id: Menu) => void
  engine: Engine
  settings: Settings
  status: Status
  patchSettings: (change: Partial<Settings>) => void
  label: string
  nemo: { route: NemoRoute | null; busy: string | null; error: string; choose: (name: string) => void }
}) {
  // Embedding models (nomic-embed-text, used for tool retrieval) cannot chat, so they are not offered.
  const local = (status.state?.models ?? []).filter((model) => model.enabled && !model.embedding)
  const cloudModels = status.state?.cloud_models ?? []
  const cloudNames = new Set(cloudModels.map((model) => model.name))
  const cloudTitle = (name: string) => name.slice(name.indexOf('/') + 1)
  const cloudDetail = (name: string) => cloudModels.find((model) => model.name === name)?.provider_label ?? 'Cloud'
  const clawAll = status.claw?.models ?? []
  const chatModelKnown = settings.chatModel && settings.chatModel !== 'auto' && (local.some((model) => model.name === settings.chatModel) || cloudNames.has(settings.chatModel))
  const size = (bytes: number) => (bytes ? `${(bytes / 1e9).toFixed(1)} GB` : '')
  const pick = (change: Partial<Settings>) => { patchSettings(change); onToggle(null) }
  // Downloading the uncensored model: progress text while it runs, or the error.
  const [pull, setPull] = useState<{ busy: boolean; detail: string; error: string }>({ busy: false, detail: '', error: '' })
  useEffect(() => window.pockpock?.models.onPullProgress((progress) => {
    setPull((current) => ({ ...current, detail: progress.fraction !== undefined ? `${Math.round(progress.fraction * 100)}% · ${progress.detail}` : progress.detail }))
  }), [])
  const pullUncensored = async () => {
    const desktop = window.pockpock
    if (!desktop || pull.busy) return
    setPull({ busy: true, detail: 'Starting the download…', error: '' })
    try {
      const name = await desktop.models.pullUncensored()
      await status.refreshClaw(true)
      setPull({ busy: false, detail: '', error: '' })
      pick({ clawModel: name })
    } catch (error) {
      setPull({ busy: false, detail: '', error: (error instanceof Error ? error.message : String(error)).replace(/^Error invoking remote method '[^']+': (Error: )?/, '') })
    }
  }
  const uncensoredReady = clawAll.includes(UNCENSORED_MODEL)
  if (engine === 'nemoclaw' && !cloudModels.length && !nemo.route?.cloud) return null
  return (
    <div className="anchor">
      <Toggle menu={menu} id="model" label={`Model: ${label}`} className="pill pill--quiet" onToggle={onToggle}>
        <Sparkles size={13} /> <span className="pill__text">{label}</span> <ChevronDown size={12} aria-hidden="true" />
      </Toggle>
      <Popover open={menu === 'model'} onClose={() => onToggle(null)} align="right" className="popover--wide popover--scroll" label="Model">
        {engine === 'nemoclaw' ? <>
          <div className="popover__label">Sandbox model · applies to every NemoClaw task</div>
          {nemo.error && <div className="popover__note" role="alert">{nemo.error}</div>}
          <MenuItem icon={nemo.busy === '' ? <LoaderCircle size={14} className="spin" /> : <Bot size={14} />} title={nemo.route?.local?.model || status.nemo?.model || 'Local model'} detail="On this PC" disabled={nemo.busy !== null} selected={nemo.route ? !nemo.route.cloud : true} onSelect={() => nemo.choose('')} />
          {cloudModels.length > 0 && <div className="popover__label">Cloud · sends data to the provider</div>}
          {cloudModels.map((model) => (
            <MenuItem key={model.name} icon={nemo.busy === model.name ? <LoaderCircle size={14} className="spin" /> : <Cloud size={14} />} title={cloudTitle(model.name)} detail={model.provider_label} disabled={nemo.busy !== null} selected={nemo.route?.cloud === true && nemo.route.model === model.name} onSelect={() => nemo.choose(model.name)} />
          ))}
        </> : engine === 'openclaw' ? <>
          <div className="popover__label">OpenClaw model · loads when used</div>
          <MenuItem icon={<Sparkles size={14} />} title="Default" detail={status.claw?.model?.replace('ollama/', '') || 'OpenClaw default'} selected={!settings.clawModel || !clawAll.includes(settings.clawModel)} onSelect={() => pick({ clawModel: '' })} />
          <div className="popover__label">Uncensored · refusals removed</div>
          {uncensoredReady
            ? <MenuItem icon={<ShieldOff size={14} />} title="Qwen 3.5 9B uncensored" detail={`${local.find((model) => model.name === UNCENSORED_MODEL)?.running ? 'Loaded' : 'Not loaded'} · does what you ask, including what the normal model declines`} selected={settings.clawModel === UNCENSORED_MODEL} onSelect={() => pick({ clawModel: UNCENSORED_MODEL })} />
            : <MenuItem icon={pull.busy ? <LoaderCircle size={14} className="spin" /> : <Download size={14} />} title={pull.busy ? 'Downloading Qwen 3.5 9B uncensored…' : 'Download Qwen 3.5 9B uncensored (6.6 GB)'}
                detail={pull.busy ? pull.detail : `A community build (${UNCENSORED_MODEL}) with its refusals removed: it does what you ask, including what the normal model declines. You are responsible for how you use it.`}
                disabled={pull.busy} onSelect={() => void pullUncensored()} />}
          {pull.error && <div className="popover__note" role="alert">{pull.error}</div>}
          <div className="popover__label">Local</div>
          {clawAll.filter((name) => !cloudNames.has(name) && name !== UNCENSORED_MODEL && `ollama/${name}` !== status.claw?.model && name !== status.claw?.model).map((name) => (
            <MenuItem key={name} icon={<Bot size={14} />} title={name} detail={local.find((model) => model.name === name)?.running ? 'Loaded' : 'Not loaded'} selected={settings.clawModel === name} onSelect={() => pick({ clawModel: name })} />
          ))}
          {clawAll.some((name) => cloudNames.has(name)) && <div className="popover__label">Cloud · sends data to the provider</div>}
          {clawAll.filter((name) => cloudNames.has(name)).map((name) => (
            <MenuItem key={name} icon={<Cloud size={14} />} title={cloudTitle(name)} detail={cloudDetail(name)} selected={settings.clawModel === name} onSelect={() => pick({ clawModel: name })} />
          ))}
        </> : <>
          <div className="popover__label">Automatic</div>
          <MenuItem icon={<Sparkles size={14} />} title="Smart route" detail="Picks a local model for each request" selected={!chatModelKnown} onSelect={() => pick({ chatModel: 'auto' })} />
          {local.length > 0 && <div className="popover__label">Local · loads when used</div>}
          {local.map((model) => (
            <MenuItem key={model.name} icon={<Bot size={14} />} title={model.name} detail={[model.running ? 'Loaded' : 'Not loaded', size(model.size)].filter(Boolean).join(' · ')} selected={settings.chatModel === model.name} onSelect={() => pick({ chatModel: model.name })} />
          ))}
          {!local.length && <div className="popover__note">No local model is switched on. Switch one on in Workshop → Local models.</div>}
          {cloudModels.length > 0 && <div className="popover__label">Cloud · sends data to the provider</div>}
          {cloudModels.map((model) => (
            <MenuItem key={model.name} icon={<Cloud size={14} />} title={cloudTitle(model.name)} detail={model.provider_label} selected={settings.chatModel === model.name} onSelect={() => pick({ chatModel: model.name })} />
          ))}
          {engine === 'agent' && <>
            <div className="popover__label">Planning · the model above does the steps</div>
            <MenuItem icon={<Sparkles size={14} />} title="One model plans and works" detail="The plan you can edit, then one model does the whole task" selected={!settings.agentPlanner} onSelect={() => pick({ agentPlanner: '' })} />
            {cloudModels.map((model) => (
              <MenuItem key={`plan:${model.name}`} icon={<Cloud size={14} />} title={`Plan in steps with ${cloudTitle(model.name)}`} detail={`${model.provider_label} writes the plan; sends your request to it`} selected={settings.agentPlanner === model.name} onSelect={() => pick({ agentPlanner: model.name })} />
            ))}
            {local.filter((model) => !/embed/i.test(model.name)).map((model) => (
              <MenuItem key={`plan:${model.name}`} icon={<Bot size={14} />} title={`Plan in steps with ${model.name}`} detail="Writes a checked step plan on this PC" selected={settings.agentPlanner === model.name} onSelect={() => pick({ agentPlanner: model.name })} />
            ))}
          </>}
        </>}
      </Popover>
    </div>
  )
}
