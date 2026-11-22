// "Find on mcpservers.org" on the MCP servers and Skills pages. The gateway searches mcpservers.org's
// published lists (backend/projects/agent_extensions/directory.py): its curated list (name, description,
// GitHub link) always, and its full index of every server or skill page once the user asks for it.
// A curated result opens the normal preview, so nothing is installed without the user's approval.
import { useEffect, useRef, useState } from 'react'
import { BadgeCheck, Compass, ExternalLink, LoaderCircle, Search } from 'lucide-react'
import { getJson } from '../lib/api'
import { bridge } from '../lib/types'

type Result = { name: string; description: string; owner: string; curated: boolean; install_url: string | null; source_url: string | null; page_url: string }
type Reply = { results: Result[]; total: number; counts: { curated: number; index: number }; index_cached: boolean; note: string; site: string }

const COPY = {
  mcp: {
    title: 'Find an MCP server on mcpservers.org',
    intro: 'Searches the servers listed on mcpservers.org. Curated servers have a description and can be previewed here; open any result to read more on the site.',
    full: 'Search all servers on mcpservers.org',
    fullNote: 'About 13,000 servers. The first search downloads the site’s server index (about 57 MB), then once a week.',
    placeholder: 'postgres, github, browser, calendar…',
  },
  skills: {
    title: 'Find a skill on mcpservers.org',
    intro: 'Searches the agent skills listed on mcpservers.org. Open a result to see it on the site, then paste its GitHub link above to preview and add it.',
    full: 'Search skills on mcpservers.org',
    fullNote: 'About 8,000 skills. The first search downloads the site’s skill index (about 9 MB), then once a week.',
    placeholder: 'pdf, spreadsheet, slides, review…',
  },
} as const

export function DirectorySearch({ kind, onPreview, busy }: { kind: 'mcp' | 'skills'; onPreview: (url: string) => Promise<string>; busy: boolean }) {
  const copy = COPY[kind]
  const [query, setQuery] = useState('')
  const [reply, setReply] = useState<Reply | null>(null)
  const [loading, setLoading] = useState<'' | 'search' | 'full'>('')
  const [error, setError] = useState('')
  const [asked, setAsked] = useState(false)
  // A preview that failed, shown under its result: PockPock could not tell how to start that server.
  const [failed, setFailed] = useState<{ url: string; message: string } | null>(null)
  const tryPreview = async (url: string) => {
    setFailed(null)
    const message = await onPreview(url)
    if (message) setFailed({ url, message })
  }
  const sequence = useRef(0)

  const search = async (text: string, full = false) => {
    const id = ++sequence.current
    setLoading(full ? 'full' : 'search'); setError(''); setAsked(true)
    try {
      const next = await getJson<Reply>(`/api/extensions/directory?kind=${kind}&q=${encodeURIComponent(text.trim())}&limit=30${full ? '&full=true' : ''}`)
      if (id === sequence.current) setReply(next)
    } catch (reason) {
      if (id === sequence.current) setError(reason instanceof Error ? reason.message : 'mcpservers.org could not be searched.')
    } finally {
      if (id === sequence.current) setLoading('')
    }
  }
  // Search while typing, after a short pause; nothing is downloaded until the user types or presses a button.
  useEffect(() => {
    if (!query.trim()) return
    const timer = window.setTimeout(() => void search(query), 350)
    return () => window.clearTimeout(timer)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [query])

  const canFull = kind === 'skills' ? !reply?.index_cached : reply !== null && !reply.index_cached
  return (
    <section className="card directory" aria-labelledby={`directory-${kind}`}>
      <header><Compass size={15} aria-hidden="true" /><strong id={`directory-${kind}`}>{copy.title}</strong></header>
      <p className="card__sub">{copy.intro}</p>
      <form className="directory__search" role="search" onSubmit={(event) => { event.preventDefault(); void search(query) }}>
        <label className="search">
          <Search size={13} aria-hidden="true" />
          <input type="search" className="input" aria-label={copy.title} placeholder={copy.placeholder} value={query} onChange={(event) => setQuery(event.target.value)} maxLength={100} spellCheck={false} />
        </label>
        {loading === 'search' && <LoaderCircle size={14} className="spin" aria-label="Searching" />}
      </form>
      {error && <p className="card__error" role="alert">{error}</p>}
      {reply?.note && <p className="note" role="status">{reply.note}</p>}
      {asked && canFull && (
        <div className="directory__full">
          <button type="button" className="button" disabled={loading !== ''} onClick={() => void search(query, true)}>
            {loading === 'full' ? <LoaderCircle size={13} className="spin" /> : <Search size={13} />} {loading === 'full' ? 'Downloading the index…' : copy.full}
          </button>
          <small>{copy.fullNote}</small>
        </div>
      )}
      {reply && asked && (
        reply.results.length ? (
          <ul className="directory__results" aria-label="Results from mcpservers.org">
            {reply.results.map((result) => (
              <li key={result.page_url + result.name} className="directory__result">
                <div>
                  <strong>{result.name}{result.curated && <small className="badge badge--accent"><BadgeCheck size={11} aria-hidden="true" /> Curated</small>}</strong>
                  <span>{result.description || (result.curated ? '' : `by ${result.owner}`)}</span>
                  {result.source_url && <small>{result.source_url}</small>}
                </div>
                <span className="directory__actions">
                  {result.install_url && <button type="button" className="button button--small button--primary" disabled={busy} onClick={() => void tryPreview(result.install_url!)}>Preview and install</button>}
                  <button type="button" className="button button--small" onClick={() => void bridge()?.openExternal(result.page_url)}><ExternalLink size={12} /> Open on mcpservers.org</button>
                </span>
                {failed && failed.url === result.install_url && (
                  <p className="directory__failed" role="alert">
                    {failed.message} Open it on mcpservers.org or GitHub for its setup steps; if they give a command that starts it (such as <code>npx …</code> or <code>uvx …</code>) or a server address, paste that in the box above.
                  </p>
                )}
              </li>
            ))}
          </ul>
        ) : loading === '' && <p className="note">Nothing on mcpservers.org matches “{query.trim()}”{reply.index_cached || kind === 'skills' ? '' : ' in its curated list'}.</p>
      )}
      <small className="directory__foot">
        Results come from mcpservers.org (its curated list on GitHub and its public index), downloaded by PockPock; your search stays on this PC. Servers and skills are third-party code: PockPock shows what it would install and asks first.
      </small>
    </section>
  )
}
