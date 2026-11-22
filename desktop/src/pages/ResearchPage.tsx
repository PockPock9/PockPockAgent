// Workshop → Research: whether PockPock Agent tasks may read public websites (backed by
// /api/research/provider: named_host_fetcher = on, disabled = off), and the watched pages: saved
// sources the gateway re-reads in the background (/api/research/watch, lib/watch.ts).
import { useEffect, useState } from 'react'
import { Bookmark, Check, Eye, EyeOff, Globe2, RefreshCw, ShieldOff } from 'lucide-react'
import { ErrorNote, Loading, PageFrame, Toggle } from '../components/page'
import { getJson, sendJson } from '../lib/api'
import { ago, checkNow, intervalText, markSeen, setWatched, until, useWatchedSources, type WatchedSource } from '../lib/watch'

type Provider = { provider: 'disabled' | 'named_host_fetcher'; enabled: boolean; destination: string; supports_search: boolean }

function WatchedRow({ item, onNote }: { item: WatchedSource; onNote: (text: string) => void }) {
  const [busy, setBusy] = useState('')
  const act = async (label: string, run: () => Promise<string>) => {
    setBusy(label)
    try { onNote(await run()) } catch (error) { onNote(`${label} failed: ${error instanceof Error ? error.message : 'try again later.'}`) } finally { setBusy('') }
  }
  const { watch } = item
  return (
    <li className={`watch-row${watch.unseen ? ' is-changed' : ''}`}>
      <div className="watch-row__text">
        <a href={item.url} target="_blank" rel="noreferrer">{item.title || item.url}</a>
        <small>{item.url}</small>
        <span className="watch-row__status">
          {watch.unseen && <span className="badge badge--accent">Changed {ago(watch.changed_at)}</span>}
          {watch.error
            ? <span className="watch-row__error">Last check failed {ago(watch.error_at)}: {watch.error}</span>
            : <span>Checked {ago(item.last_checked_at)}</span>}
          <span>Next check {until(item.next_check_at)}</span>
        </span>
      </div>
      <span className="watch-row__actions">
        <button type="button" className="button button--small" disabled={Boolean(busy)} onClick={() => void act('Check now', async () => {
          const result = await checkNow(item.task_id, item.source_id)
          return result.changed && result.previous ? `${item.title} has changed. The new version is saved with its task.` : `${item.title} has not changed.`
        })}><RefreshCw size={12} className={busy === 'Check now' ? 'spin' : undefined} /> Check now</button>
        {watch.unseen && <button type="button" className="button button--small" disabled={Boolean(busy)} onClick={() => void act('Mark as seen', async () => { await markSeen(item.task_id, item.source_id); return `Marked ${item.title} as seen.` })}><Check size={12} /> Mark as seen</button>}
        <button type="button" className="button button--small" disabled={Boolean(busy)} onClick={() => void act('Stop watching', async () => { await setWatched(item.task_id, item.source_id, false); return `Stopped watching ${item.title}.` })}><EyeOff size={12} /> Stop watching</button>
      </span>
    </li>
  )
}

export function ResearchPage() {
  const [state, setState] = useState<Provider | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [note, setNote] = useState('')
  const watched = useWatchedSources(60_000)
  const load = () => { getJson<Provider>('/api/research/provider').then((next) => { setState(next); setError('') }, (loadError: unknown) => setError(loadError instanceof Error ? loadError.message : 'Research settings are unavailable.')) }
  useEffect(load, [])
  const choose = async (provider: Provider['provider']) => {
    setBusy(true); setError('')
    try { setState(await sendJson<Provider>('/api/research/provider', { provider }, 'PUT')); watched.reload() } catch (saveError) { setError(saveError instanceof Error ? saveError.message : 'Could not save.') } finally { setBusy(false) }
  }
  const on = state?.provider === 'named_host_fetcher'
  const list = watched.data
  const changed = list?.sources.filter((item) => item.watch.unseen).length ?? 0
  return (
    <PageFrame eyebrow="Workshop · Capabilities" title="Research" intro="Whether PockPock Agent tasks may read public websites. Sources it reads appear under its reply, where you can save them, check them for changes and watch them.">
      <ErrorNote message={error} onRetry={load} />
      {!state && !error && <Loading>Loading…</Loading>}
      {state && (
        <>
          <div className="card setting-card">
            {on ? <Globe2 size={16} aria-hidden="true" /> : <ShieldOff size={16} aria-hidden="true" />}
            <div className="row__text"><strong>Allow reading public websites</strong>
              <span>{on ? 'On: tasks may read text from public sites they name by hostname. No general web search; private and local addresses are blocked, with time and size limits.' : 'Off: research tools make no network requests.'}</span></div>
            <Toggle checked={on} busy={busy} label="Allow reading public websites" onChange={(next) => void choose(next ? 'named_host_fetcher' : 'disabled')} />
          </div>
          <p className="note">Requests go to: {state.destination.replace(/\.\s*$/, '')}. No API keys are used or stored. The OpenClaw engine has its own web access, controlled by its permission setting.</p>
        </>
      )}
      <section className="settings-section" aria-labelledby="watched-title">
        <h2 className="list-title" id="watched-title"><Eye size={15} aria-hidden="true" /> Watched pages{list && list.sources.length > 0 && <small>{list.sources.length}</small>}{changed > 0 && <span className="badge badge--accent">{changed} changed</span>}</h2>
        <p className="note">
          {list ? `Each watched page is read again ${intervalText(list.interval_minutes)} while PockPock runs, and you are told when its text changes. This reads the page from the internet; nothing else is sent.` : 'Saved sources you choose to watch are read again in the background while PockPock runs.'}
        </p>
        <ErrorNote message={watched.error} onRetry={watched.reload} />
        {!list && !watched.error && <Loading>Loading watched pages…</Loading>}
        {list && !list.research_enabled && list.sources.length > 0 && <p className="banner banner--warn" role="status">Checks are paused while <strong>Allow reading public websites</strong> is off.</p>}
        {list && !list.background && list.sources.length > 0 && <p className="banner banner--warn" role="status">Background checks are turned off on this PC (<code>POCKPOCK_SOURCE_WATCH=0</code>). <strong>Check now</strong> still works.</p>}
        {list && !list.sources.length && (
          <p className="note note--text"><Bookmark size={13} aria-hidden="true" />No watched pages. In a task, <strong>Save</strong> a source on its sources card, then turn on <strong>Watch for changes</strong>.</p>
        )}
        {list && list.sources.length > 0 && <ul className="watch-list">{list.sources.map((item) => <WatchedRow key={`${item.task_id}:${item.source_id}`} item={item} onNote={setNote} />)}</ul>}
        {note && <p className="note" role="status">{note}</p>}
      </section>
    </PageFrame>
  )
}
