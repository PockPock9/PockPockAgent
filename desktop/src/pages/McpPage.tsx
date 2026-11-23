// Workshop → MCP servers: programs that give the agents extra tools. Add one from a GitHub link, a server
// address or a local command (inspected and approved first), switch it on or off, disconnect. Servers added
// in PockPock run in Local MCP (backend/projects/mcp_hub, on the Services page): started once, shared by
// every agent, with their keys kept there. This page shows each one's state, restarts it and shows its log.
import { useState } from 'react'
import { FileText, LoaderCircle, Plug, RotateCw, Trash2, X } from 'lucide-react'
import { ExtensionCard } from '../components/ExtensionCard'
import { Empty } from '../components/ui'
import { ErrorNote, Loading, PageFrame, Toggle } from '../components/page'
import { getJson, sendJson } from '../lib/api'
import type { Status } from '../lib/status'
import { AddLink, useExtensions, useProposal } from './extensions'
import type { ExtensionList } from './extensions'
import { DirectorySearch } from './DirectorySearch'

type Server = ExtensionList['mcp'][number]

/** The state badge of a server in Local MCP. */
function stateBadge(server: Server): { text: string; tone: string } | null {
  if (!server.local || !server.enabled) return null
  switch (server.state) {
    case 'running': return { text: server.tools != null ? `Running · ${server.tools} ${server.tools === 1 ? 'tool' : 'tools'}` : 'Running', tone: 'ok' }
    case 'starting': return { text: 'Starting…', tone: 'busy' }
    case 'stopped': return { text: 'Starts when used', tone: 'off' }
    case 'error': return { text: 'Error', tone: 'warn' }
    case 'unavailable': return { text: 'Local MCP stopped', tone: 'warn' }
    default: return null
  }
}

function where(server: Server): string {
  if (server.local) return server.transport === 'stdio' ? 'Runs on this PC in Local MCP' : 'Remote server, reached through Local MCP'
  return server.transport === 'stdio' ? 'Runs on this PC (started by OpenClaw)' : 'Remote server'
}

export function McpPage({ status }: { status: Status }) {
  const { list, error, setError, pending, load, act } = useExtensions(() => void status.refreshCounts())
  const { proposal, setProposal, busy, preview } = useProposal('mcp', setError)
  const [restarting, setRestarting] = useState('')
  const [log, setLog] = useState<{ name: string; lines: string[] } | null>(null)
  const on = list?.mcp.filter((server) => server.enabled).length ?? 0

  const restart = async (name: string) => {
    setRestarting(name); setError('')
    try { await sendJson('/api/extensions/mcp/restart', { name }); await load() } catch (reason) { setError(reason instanceof Error ? reason.message : 'The server could not be restarted.') } finally { setRestarting('') }
  }
  const showLog = async (name: string) => {
    setError('')
    try { setLog({ name, lines: (await getJson<{ lines: string[] }>(`/api/extensions/mcp/log?name=${encodeURIComponent(name)}`)).lines }) } catch (reason) { setError(reason instanceof Error ? reason.message : 'The log could not be read.') }
  }

  return (
    <PageFrame eyebrow="Workshop · Capabilities" title="MCP servers" intro="Programs that give the agents extra tools. Servers you add here run in Local MCP: started once on this PC and shared by the agents (OpenClaw uses them today), with their keys kept by PockPock. Every call still follows the permission you pick in the task.">
      <AddLink kind="mcp" busy={busy} onPreview={(url) => void preview(url)} />
      {proposal && <ExtensionCard key={proposal.id} proposal={proposal} onClose={() => { setProposal(null); void load(); void status.refreshCounts() }} onSwitch={(next) => void preview(proposal.source, next)} onOpen={(url) => void preview(url, 'mcp')} />}
      <DirectorySearch kind="mcp" busy={busy} onPreview={(url) => preview(url, 'mcp', true)} />
      <ErrorNote message={error} onRetry={() => void load()} />
      {!list && !error && <Loading>Loading servers…</Loading>}
      {list && list.local_mcp && !list.local_mcp.running && (
        <p className="note note--error" role="status">Local MCP is not running, so servers added in PockPock cannot be used or added. Start it on the Services page.</p>
      )}
      {list && !list.openclaw_ready && <ErrorNote message={`${list.detail || 'OpenClaw is not reachable.'} Servers cannot be listed until it is running.`} />}
      {list?.openclaw_ready && (
        <>
          <h2 className="list-title">Servers <small>{list.mcp.length ? `${on} of ${list.mcp.length} on` : 0}</small></h2>
          {!list.mcp.length ? <Empty icon={<Plug size={20} />} title="No MCP servers yet"><p>Paste a GitHub link to an MCP server, a server address, or a command that starts one on this PC, above.</p></Empty> : (
            <ul className="rows">
              {list.mcp.map((server) => {
                const badge = stateBadge(server)
                const failed = server.local && server.enabled && (server.state === 'error' || server.state === 'unavailable')
                return (
                  <li key={server.name} className={`row${failed ? ' row--error' : ''}`}>
                    <Plug size={16} className={`row__icon${failed ? ' row__icon--error' : ''}`} aria-hidden="true" />
                    <div className="row__text">
                      <strong>
                        {server.name} <small className={`badge ${server.enabled ? 'badge--ok' : 'badge--off'}`}>{server.enabled ? 'On' : 'Off'}</small>
                        {badge && <small className={`badge badge--${badge.tone}`}>{badge.text}</small>}
                      </strong>
                      <span>{where(server)} · {server.managed ? server.source || 'Added from a link' : 'Added outside PockPock'}</span>
                      <code>{server.target}</code>
                      {failed && server.state_detail && <span className="row__error">{server.state_detail}</span>}
                    </div>
                    {server.local && (
                      <>
                        <button type="button" className="icon-button" aria-label={`Show the log of ${server.name}`} title="Log" onClick={() => void showLog(server.name)}><FileText size={14} /></button>
                        <button type="button" className="icon-button" aria-label={`Restart ${server.name}`} title="Restart" disabled={!server.enabled || restarting !== '' || list.local_mcp?.running === false} onClick={() => void restart(server.name)}>
                          {restarting === server.name ? <LoaderCircle size={14} className="spin" /> : <RotateCw size={14} />}
                        </button>
                      </>
                    )}
                    <Toggle checked={server.enabled} busy={pending === `mcp:${server.name}`} label={`Use MCP server ${server.name}`} onChange={(next) => void act(`mcp:${server.name}`, '/api/extensions/toggle', { kind: 'mcp', name: server.name, enabled: next })} />
                    {server.managed && <button type="button" className="icon-button" aria-label={`Disconnect ${server.name}`} title="Disconnect" disabled={pending === `remove:${server.name}`}
                      onClick={() => { if (window.confirm(`Disconnect the MCP server “${server.name}”?`)) void act(`remove:${server.name}`, '/api/extensions/remove', { kind: 'mcp', name: server.name }) }}><Trash2 size={14} /></button>}
                  </li>
                )
              })}
            </ul>
          )}
          {log && (
            <section className="log-view" aria-label={`Log of ${log.name}`}>
              <header>
                <strong>{log.name}</strong>
                <code>What the server printed since Local MCP started it (last 200 lines, kept in memory only)</code>
                <button type="button" className="icon-button" aria-label="Refresh the log" title="Refresh" onClick={() => void showLog(log.name)}><RotateCw size={13} /></button>
                <button type="button" className="icon-button" aria-label="Close the log" title="Close" onClick={() => setLog(null)}><X size={13} /></button>
              </header>
              <pre tabIndex={0}>{log.lines.length ? log.lines.join('\n') : 'No output yet. The server starts when an agent first uses it.'}</pre>
            </section>
          )}
        </>
      )}
    </PageFrame>
  )
}
