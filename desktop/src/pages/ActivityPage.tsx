// Recent Smart Router activity: which model handled each request, how long it took, and how
// each model performs. Prompts and replies are never stored, only routing metadata.
import { Activity, CircleAlert, Gauge, Server } from 'lucide-react'
import { Empty } from '../components/ui'
import { ErrorNote, PageFrame, Stat } from '../components/page'
import type { Status } from '../lib/status'
import type { Trace } from '../lib/types'

function label(trace: Trace) {
  if (trace.event === 'request_received') return 'Request received'
  if (trace.event === 'route_decision') return `Routed to ${trace.model || 'a model'}`
  if (trace.event === 'model_call_finished') return `${trace.model || 'Model'} answered`
  if (trace.event === 'model_call_failed') return `${trace.model || 'Model'} failed`
  if (trace.event === 'router_state') return trace.status === 'enabled' ? 'Router started' : 'Router paused'
  return trace.event.replaceAll('_', ' ')
}

export function ActivityPage({ status }: { status: Status }) {
  const state = status.state
  const events = state?.events ?? []
  const totals = state?.totals ?? {}
  const models = (state?.models ?? []).filter((model) => (model.calls ?? 0) > 0).sort((a, b) => (b.calls ?? 0) - (a.calls ?? 0))
  return (
    <PageFrame eyebrow="Workshop · System" title="Activity" intro="What the Smart Router did recently. Only routing details are kept: never your prompts or the replies.">
        {!state ? <ErrorNote message="The PockPock gateway is not answering. Start it from Services." /> : (
          <>
            <div className="stats">
              <Stat icon={<Activity size={16} />} label="Requests" value={totals.requests ?? 0} />
              <Stat icon={<Server size={16} />} label="Model calls" value={totals.calls ?? 0} />
              <Stat icon={<Gauge size={16} />} label="Average time" value={totals.avg_ms ? `${(totals.avg_ms / 1000).toFixed(1)} s` : '—'} />
              <Stat icon={<Server size={16} />} label="Loaded now" value={state.models.filter((model) => model.running && !model.embedding).length} />
            </div>
            <h2 className="list-title">By model</h2>
            {!models.length ? <p className="note">No model has been used yet.</p> : (
              <table className="table"><caption className="visually-hidden">Calls, success rate and average time by model</caption>
                <thead><tr><th>Model</th><th>Calls</th><th>Succeeded</th><th>Average time</th></tr></thead>
                <tbody>{models.map((model) => (
                  <tr key={model.name}><td>{model.name}</td><td>{model.calls}</td><td>{model.calls ? `${Math.round(((model.successes ?? 0) / model.calls) * 100)}%` : '—'}</td><td>{model.avg_ms ? `${(model.avg_ms / 1000).toFixed(1)} s` : '—'}</td></tr>
                ))}</tbody>
              </table>
            )}
            <h2 className="list-title">Recent events <small>{events.length}</small></h2>
            {!events.length ? <Empty icon={<Activity size={20} />} title="Nothing yet"><p>Send a message in Chat or PockPock Agent and it will show up here.</p></Empty> : (
              <ul className="rows rows--compact">
                {events.slice(0, 120).map((trace) => (
                  <li key={trace.id} className={`row${trace.status === 'error' || trace.error ? ' row--error' : ''}`}>
                    {trace.error ? <CircleAlert size={15} className="row__icon row__icon--error" /> : <Activity size={15} className="row__icon" />}
                    <div className="row__text">
                      <strong>{label(trace)}</strong>
                      <span>{[new Date(trace.created_at).toLocaleString(), trace.category, trace.role, trace.source, trace.duration_ms ? `${(trace.duration_ms / 1000).toFixed(1)} s` : ''].filter(Boolean).join(' · ')}</span>
                      {(trace.reason || trace.error) && <p>{trace.error || trace.reason}</p>}
                    </div>
                  </li>
                ))}
              </ul>
            )}
          </>
        )}
    </PageFrame>
  )
}
