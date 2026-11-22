// Workshop → MCP servers: programs that give the OpenClaw agent extra tools. Add one from a GitHub link,
// a server address or a local command (inspected and approved first), switch it on or off, disconnect.
import { Plug, Trash2 } from 'lucide-react'
import { ExtensionCard } from '../components/ExtensionCard'
import { Empty } from '../components/ui'
import { ErrorNote, Loading, PageFrame, Toggle } from '../components/page'
import type { Status } from '../lib/status'
import { AddLink, useExtensions, useProposal } from './extensions'
import { DirectorySearch } from './DirectorySearch'

export function McpPage({ status }: { status: Status }) {
  const { list, error, setError, pending, load, act } = useExtensions(() => void status.refreshCounts())
  const { proposal, setProposal, busy, preview } = useProposal('mcp', setError)
  const on = list?.mcp.filter((server) => server.enabled).length ?? 0
  return (
    <PageFrame eyebrow="Workshop · Capabilities" title="MCP servers" intro="Programs that give the OpenClaw agent extra tools. Every call still follows the permission you pick in the task.">
      <AddLink kind="mcp" busy={busy} onPreview={(url) => void preview(url)} />
      {proposal && <ExtensionCard key={proposal.id} proposal={proposal} onClose={() => { setProposal(null); void load(); void status.refreshCounts() }} onSwitch={(next) => void preview(proposal.source, next)} onOpen={(url) => void preview(url, 'mcp')} />}
      <DirectorySearch kind="mcp" busy={busy} onPreview={(url) => preview(url, 'mcp', true)} />
      <ErrorNote message={error} onRetry={() => void load()} />
      {!list && !error && <Loading>Loading servers…</Loading>}
      {list && !list.openclaw_ready && <ErrorNote message={`${list.detail || 'OpenClaw is not reachable.'} Servers cannot be listed until it is running.`} />}
      {list?.openclaw_ready && (
        <>
          <h2 className="list-title">Servers <small>{list.mcp.length ? `${on} of ${list.mcp.length} on` : 0}</small></h2>
          {!list.mcp.length ? <Empty icon={<Plug size={20} />} title="No MCP servers yet"><p>Paste a GitHub link to an MCP server, a server address, or a command that starts one on this PC, above.</p></Empty> : (
            <ul className="rows">
              {list.mcp.map((server) => (
                <li key={server.name} className="row">
                  <Plug size={16} className="row__icon" aria-hidden="true" />
                  <div className="row__text">
                    <strong>{server.name} <small className={`badge ${server.enabled ? 'badge--ok' : 'badge--off'}`}>{server.enabled ? 'On' : 'Off'}</small></strong>
                    <span>{server.transport === 'stdio' ? 'Runs on this PC' : 'Remote server'} · {server.managed ? server.source || 'Added from a link' : 'Added outside PockPock'}</span>
                    <code>{server.target}</code>
                  </div>
                  <Toggle checked={server.enabled} busy={pending === `mcp:${server.name}`} label={`Use MCP server ${server.name}`} onChange={(next) => void act(`mcp:${server.name}`, '/api/extensions/toggle', { kind: 'mcp', name: server.name, enabled: next })} />
                  {server.managed && <button type="button" className="icon-button" aria-label={`Disconnect ${server.name}`} title="Disconnect" disabled={pending === `remove:${server.name}`}
                    onClick={() => { if (window.confirm(`Disconnect the MCP server “${server.name}”?`)) void act(`remove:${server.name}`, '/api/extensions/remove', { kind: 'mcp', name: server.name }) }}><Trash2 size={14} /></button>}
                </li>
              ))}
            </ul>
          )}
        </>
      )}
    </PageFrame>
  )
}
