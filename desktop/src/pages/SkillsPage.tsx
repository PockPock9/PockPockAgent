// Workshop → Skills: OpenClaw skills (added from links and built in) as cards with tabs (All, On,
// Needs setup), search and a details drawer; and skills PockPock Agent learned from finished tasks,
// waiting in the skill inbox for you to check, add or reject.
import { useCallback, useEffect, useMemo, useState } from 'react'
import { Check, FlaskConical, LoaderCircle, Puzzle, Search, Sparkles, Trash2, X } from 'lucide-react'
import { ExtensionCard } from '../components/ExtensionCard'
import { Empty } from '../components/ui'
import { Drawer, ErrorNote, Loading, PageFrame, Tabs, Toggle } from '../components/page'
import { getJson, relativeTime, sendJson } from '../lib/api'
import type { Status } from '../lib/status'
import { AddLink, useExtensions, useProposal } from './extensions'
import { DirectorySearch } from './DirectorySearch'

type Skill = { id: string; name: string; description: string; kind: 'added' | 'builtin'; enabled: boolean; needsSetup: boolean; needs: string[]; source: string; toggleKey?: string; removeKey?: string; note?: string }
type Candidate = { id: string; kind: string; name: string; source_run_id: string; status: string; verification_result: { passed?: boolean; detail?: string } | null; created_at: string }

function LearnedSkills() {
  const [candidates, setCandidates] = useState<Candidate[] | null>(null)
  const [error, setError] = useState('')
  const [busy, setBusy] = useState('')
  const load = useCallback(async () => {
    try { setCandidates((await getJson<{ candidates: Candidate[] }>('/api/skills/inbox')).candidates); setError('') } catch (loadError) { setCandidates([]); setError(loadError instanceof Error ? loadError.message : 'The skill inbox is unavailable.') }
  }, [])
  useEffect(() => { void load() }, [load])
  const act = async (candidate: Candidate, action: 'verify' | 'approve' | 'reject') => {
    setBusy(`${action}:${candidate.id}`); setError('')
    try { await sendJson(`/api/skills/inbox/${encodeURIComponent(candidate.id)}/${action}`, action === 'verify' ? undefined : { reason: action === 'approve' ? 'Added on the Skills page' : 'Rejected on the Skills page', by: 'human' }); await load() }
    catch (actError) { setError(actError instanceof Error ? actError.message : 'That did not work.') } finally { setBusy('') }
  }
  if (!candidates?.length && !error) return null
  return (
    <section className="learned" aria-labelledby="learned-title">
      <h2 className="list-title" id="learned-title"><Sparkles size={14} aria-hidden="true" /> Learned from your tasks <small>{candidates?.length ?? 0}</small></h2>
      <ErrorNote message={error} />
      <ul className="learned__list">
        {candidates?.map((candidate) => {
          const result = candidate.verification_result
          return (
            <li key={candidate.id} className="card learned__card">
              <header><Sparkles size={14} aria-hidden="true" /><strong>{candidate.name}</strong>
                <span className={`badge${result?.passed ? ' badge--ok' : result ? ' badge--warn' : ''}`}>{result?.passed ? 'Check passed' : result ? 'Check failed' : 'Not checked yet'}</span></header>
              <p className="card__sub">{candidate.kind === 'tip' ? 'A tip' : 'A skill'} PockPock Agent wrote after a task{candidate.created_at ? ` · ${relativeTime(Date.parse(candidate.created_at))}` : ''}. Review what it learned before you keep it.</p>
              {result?.detail && <p>{result.detail}</p>}
              <div className="card__actions">
                <button type="button" className="button" disabled={busy !== ''} onClick={() => void act(candidate, 'verify')}>{busy === `verify:${candidate.id}` ? <LoaderCircle size={13} className="spin" /> : <FlaskConical size={13} />} Check it</button>
                <button type="button" className="button button--primary" disabled={busy !== '' || !result?.passed} title={result?.passed ? undefined : 'Check it first'} onClick={() => void act(candidate, 'approve')}><Check size={13} /> Review and add</button>
                <button type="button" className="button button--quiet-end" disabled={busy !== ''} onClick={() => void act(candidate, 'reject')}><X size={13} /> Reject</button>
              </div>
            </li>
          )
        })}
      </ul>
    </section>
  )
}

export function SkillsPage({ status }: { status: Status }) {
  const { list, error, setError, pending, load, act } = useExtensions(() => void status.refreshCounts())
  const { proposal, setProposal, busy, preview } = useProposal('skills', setError)
  const [tab, setTab] = useState<'all' | 'on' | 'setup'>('all')
  const [query, setQuery] = useState('')
  const [open, setOpen] = useState<string | null>(null)
  // OpenClaw notices a new skill after a short delay; recheck until it has a switch.
  const settling = Boolean(list?.openclaw_ready && list.skills.some((skill) => !skill.key && !skill.missing))
  useEffect(() => {
    if (!settling) return
    const timer = window.setInterval(() => void load(), 5000)
    return () => window.clearInterval(timer)
  }, [settling, load])

  const skills = useMemo<Skill[]>(() => [
    ...(list?.skills ?? []).map((skill) => ({ id: `added:${skill.slug}`, name: skill.name, description: skill.description, kind: 'added' as const, enabled: skill.enabled, needsSetup: skill.missing, needs: skill.missing ? ['its files, which are missing: remove it and add it again'] : [],
      source: skill.source.replace('https://github.com/', 'github.com/'), toggleKey: skill.key, removeKey: skill.slug, note: !skill.key && !skill.missing ? 'Getting ready…' : undefined })),
    ...(list?.builtin_skills ?? []).map((skill) => ({ id: `builtin:${skill.key}`, name: skill.name, description: skill.description, kind: 'builtin' as const, enabled: skill.enabled && skill.ready, needsSetup: !skill.ready, needs: skill.ready ? [] : (skill.needs.length ? skill.needs : ['setup in OpenClaw']), source: 'Built into OpenClaw', toggleKey: skill.ready ? skill.key : undefined })),
  ], [list])
  const words = query.toLowerCase().split(/\s+/).filter(Boolean)
  const shown = skills.filter((skill) => (tab === 'on' ? skill.enabled : tab === 'setup' ? skill.needsSetup : true) && words.every((word) => `${skill.name} ${skill.description}`.toLowerCase().includes(word)))
  const selected = skills.find((skill) => skill.id === open) ?? null
  const toggle = (skill: Skill, next: boolean) => skill.toggleKey && void act(`skill:${skill.toggleKey}`, '/api/extensions/toggle', { kind: 'skill', name: skill.toggleKey, enabled: next })
  const remove = (skill: Skill) => { if (skill.removeKey && window.confirm(`Remove the skill “${skill.name}”? Its files will be deleted.`)) { setOpen(null); void act(`remove:${skill.removeKey}`, '/api/extensions/remove', { kind: 'skill', name: skill.removeKey }) } }

  return (
    <PageFrame eyebrow="Workshop · Capabilities" title="Skills" intro="Instructions and helpers the OpenClaw agent can use. Turn off what you don't want it to reach for." wide>
      <AddLink kind="skills" busy={busy} onPreview={(url) => void preview(url)} />
      {proposal && <ExtensionCard key={proposal.id} proposal={proposal} onClose={() => { setProposal(null); void load(); void status.refreshCounts() }} onSwitch={(next) => void preview(proposal.source, next)} onOpen={(url) => void preview(url, 'mcp')} />}
      <DirectorySearch kind="skills" busy={busy} onPreview={(url) => preview(url, 'skills', true)} />
      <ErrorNote message={error} onRetry={() => void load()} />
      <LearnedSkills />
      {!list && !error && <Loading>Loading skills…</Loading>}
      {list && !list.openclaw_ready && <ErrorNote message={`${list.detail || 'OpenClaw is not reachable.'} Skills cannot be switched until it is running.`} />}
      {list && (
        <>
          <div className="page-toolbar">
            <Tabs label="Skills" controls="skills-panel" value={tab} onChange={setTab} tabs={[
              { id: 'all', label: 'All', count: skills.length },
              { id: 'on', label: 'On', count: skills.filter((skill) => skill.enabled).length },
              { id: 'setup', label: 'Needs setup', count: skills.filter((skill) => skill.needsSetup).length },
            ]} />
            <label className="search page-toolbar__search"><Search size={13} aria-hidden="true" /><input type="search" placeholder="Search skills" value={query} onChange={(event) => setQuery(event.target.value)} aria-label="Search skills" /></label>
          </div>
          <div id="skills-panel" role="tabpanel" aria-labelledby={`skills-panel-tab-${tab}`}>
            {!shown.length && (words.length ? <Empty icon={<Search size={20} />} title="No skill matches"><p>Try another word, or clear the search.</p></Empty>
              : tab === 'setup' ? <Empty icon={<Check size={20} />} title="Nothing needs setup"><p>Every skill has what it needs.</p></Empty>
                : <Empty icon={<Puzzle size={20} />} title="No skills yet"><p>Paste a GitHub link above, or into a task, to add one.</p></Empty>)}
            <ul className="card-grid">
              {shown.map((skill) => (
                <li key={skill.id} className={`card skill-card${skill.needsSetup ? ' is-muted' : ''}`}>
                  <div className="skill-card__head">
                    <Puzzle size={16} aria-hidden="true" />
                    <button type="button" className="skill-card__open" onClick={() => setOpen(skill.id)}>{skill.name}</button>
                    {skill.toggleKey ? <Toggle checked={skill.enabled} busy={pending === `skill:${skill.toggleKey}`} label={`Use skill ${skill.name}`} onChange={(next) => toggle(skill, next)} />
                      : skill.note ? <em className="row__hint">{skill.note}</em> : null}
                  </div>
                  <p>{skill.description || 'No description.'}</p>
                  <small>{skill.needsSetup ? <span className="badge badge--warn">Needs setup</span> : skill.source}</small>
                </li>
              ))}
            </ul>
          </div>
        </>
      )}
      {selected && (
        <Drawer title={selected.name} onClose={() => setOpen(null)}
          footer={selected.kind === 'added' ? <button type="button" className="button" onClick={() => remove(selected)} disabled={pending === `remove:${selected.removeKey}`}><Trash2 size={13} /> Remove</button> : undefined}>
          <p className="card__sub">{selected.source}</p>
          <p>{selected.description || 'No description.'}</p>
          {selected.toggleKey && <div className="kv"><span>Use it</span><span><Toggle checked={selected.enabled} busy={pending === `skill:${selected.toggleKey}`} label={`Use skill ${selected.name}`} onChange={(next) => toggle(selected, next)} /></span></div>}
          {selected.needs.length > 0 && <><h3 className="drawer__label">Needs</h3><ul className="drawer__list">{selected.needs.map((need) => <li key={need}>{need}</li>)}</ul></>}
          <h3 className="drawer__label">Where it applies</h3>
          <p>OpenClaw tasks. Each tool call still follows the permission you choose in the task.</p>
        </Drawer>
      )}
    </PageFrame>
  )
}
