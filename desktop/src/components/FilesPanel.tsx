// Explorer for the open folder. Files can be attached to the next message or opened.
import { useCallback, useEffect, useState } from 'react'
import { ChevronDown, ChevronRight, File, Folder, FolderOpen, LoaderCircle, Paperclip, RefreshCw, SquareArrowOutUpRight } from 'lucide-react'
import { bridge } from '../lib/types'
import type { FileEntry } from '../lib/types'
import { Empty, IconButton } from './ui'

type Tree = Record<string, { items: FileEntry[]; truncated: boolean } | 'loading' | { error: string }>

export function FilesPanel({ overlay, embedded, workspace, onChooseFolder, onAttach }: {
  overlay?: boolean
  /** Inside the inspector's Files tab: no panel of its own, the tab is the label. */
  embedded?: boolean
  workspace?: string
  onChooseFolder: () => void
  onAttach: (file: { name: string; text: string; size: number }) => void
}) {
  const [tree, setTree] = useState<Tree>({})
  const [open, setOpen] = useState<Set<string>>(new Set(['']))
  const [selected, setSelected] = useState('')
  const [message, setMessage] = useState('')
  const desktop = bridge()

  const load = useCallback(async (relative: string) => {
    if (!desktop) return
    setTree((previous) => ({ ...previous, [relative]: 'loading' }))
    try {
      const listing = await desktop.workspace.list(relative)
      setTree((previous) => ({ ...previous, [relative]: listing }))
    } catch (error) {
      setTree((previous) => ({ ...previous, [relative]: { error: error instanceof Error ? error.message : 'Could not read this folder.' } }))
    }
  }, [desktop])

  useEffect(() => {
    setTree({})
    setOpen(new Set(['']))
    if (workspace) void load('')
  }, [workspace, load])

  const toggle = (entry: FileEntry) => {
    setOpen((previous) => {
      const next = new Set(previous)
      if (next.has(entry.path)) next.delete(entry.path)
      else { next.add(entry.path); if (!tree[entry.path]) void load(entry.path) }
      return next
    })
  }

  const attach = async (entry: FileEntry) => {
    try {
      onAttach(await desktop!.workspace.read(entry.path))
      setMessage(`Attached ${entry.name} to the next message.`)
    } catch (error) {
      setMessage(error instanceof Error ? error.message.replace(/^Error invoking remote method '[^']+': (Error: )?/, '') : 'Could not attach that file.')
    }
    window.setTimeout(() => setMessage(''), 3500)
  }

  const refresh = () => { const folders = [...open]; setTree({}); folders.forEach((folder) => void load(folder)) }

  const render = (relative: string, depth: number): React.ReactNode => {
    const node = tree[relative]
    if (!node || node === 'loading') return <div className="tree__note" style={{ paddingLeft: 12 + depth * 12 }}><LoaderCircle size={12} className="spin" /> Loading…</div>
    if ('error' in node) return <div className="tree__note tree__note--error" style={{ paddingLeft: 12 + depth * 12 }}>{node.error}</div>
    if (!node.items.length) return <div className="tree__note" style={{ paddingLeft: 12 + depth * 12 }}>Empty folder</div>
    return (
      <>
        {node.items.map((entry) => (
          <div key={entry.path} role="treeitem" aria-expanded={entry.directory ? open.has(entry.path) : undefined} aria-selected={selected === entry.path}>
            <div className={`tree__row${selected === entry.path ? ' is-selected' : ''}${entry.muted ? ' is-muted' : ''}`} style={{ paddingLeft: 8 + depth * 12 }}>
              <button type="button" className="tree__name" title={entry.path}
                onClick={() => { setSelected(entry.path); if (entry.directory) toggle(entry) }}
                onDoubleClick={() => { if (!entry.directory) void desktop?.workspace.open(entry.path) }}>
                {entry.directory ? (open.has(entry.path) ? <ChevronDown size={13} /> : <ChevronRight size={13} />) : <span className="tree__spacer" />}
                {entry.directory ? (open.has(entry.path) ? <FolderOpen size={14} className="tree__folder" /> : <Folder size={14} className="tree__folder" />) : <File size={14} />}
                <span>{entry.name}</span>
              </button>
              {!entry.directory && <button type="button" className="tree__action" onClick={() => void attach(entry)} aria-label={`Attach ${entry.name} to the chat`} title="Attach to chat"><Paperclip size={12} /></button>}
              <button type="button" className="tree__action" onClick={() => void (entry.directory ? desktop?.workspace.reveal(entry.path) : desktop?.workspace.open(entry.path))} aria-label={`Open ${entry.name}`} title={entry.directory ? 'Show in Explorer' : 'Open'}><SquareArrowOutUpRight size={12} /></button>
            </div>
            {entry.directory && open.has(entry.path) && render(entry.path, depth + 1)}
          </div>
        ))}
        {node.truncated && <div className="tree__note" style={{ paddingLeft: 12 + depth * 12 }}>Only the first 600 items are shown.</div>}
      </>
    )
  }

  const name = workspace?.split(/[\\/]/).filter(Boolean).at(-1)
  return (
    <div className={`files${embedded ? ' files--embedded' : ''}${overlay ? ' is-overlay' : ''}`}>
      <div className="panel-head">
        <span className="panel-head__title" title={workspace}>{embedded ? (name || 'No folder open') : 'Files'}</span>
        <span className="panel-head__actions">
          <IconButton label="Open folder" onClick={onChooseFolder}><FolderOpen size={14} /></IconButton>
          {workspace && <IconButton label="Refresh" onClick={refresh}><RefreshCw size={13} /></IconButton>}
        </span>
      </div>
      {!desktop ? <Empty icon={<Folder size={20} />} title="Files need the desktop app">Run PockPock Agent from Electron to browse folders.</Empty>
        : !workspace ? (
          <Empty icon={<Folder size={20} />} title="No folder open">
            <p>Open a folder to browse it here, attach files to a message, and let the agent work in it.</p>
            <button type="button" className="button button--primary" onClick={onChooseFolder}><FolderOpen size={13} /> Open folder</button>
          </Empty>
        ) : (
          <div className="tree" role="tree" aria-label={name}>
            <div className="tree__root" title={workspace}>{name}</div>
            {render('', 0)}
          </div>
        )}
      {message && <div className="files__toast" role="status">{message}</div>}
    </div>
  )
}
