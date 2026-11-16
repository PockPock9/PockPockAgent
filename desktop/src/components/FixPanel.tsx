// The Maintenance Manager on one report: start a fix, follow it, review the result, and approve a draft
// pull request or discard the fix. Nothing is pushed before "Approve and open draft PR".
import { useEffect, useRef, useState } from 'react'
import { Check, ExternalLink, FileText, GitPullRequest, LoaderCircle, RotateCcw, Square, Trash2, Wand2, X } from 'lucide-react'
import { Mark } from './Mark'
import { bridge } from '../lib/types'
import type { FixRun, MaintenanceStatus } from '../lib/types'

const clean = (reason: unknown, fallback: string) => (reason instanceof Error ? reason.message.replace(/^Error invoking remote method '[^']+': (Error: )?/, '') : fallback)
const AGENT_NAME: Record<string, string> = { local: 'PockPock', claude: 'Claude Code', codex: 'OpenAI Codex', copilot: 'GitHub Copilot' }

export function FixPanel({ reportId, setup, onOpenSetup }: { reportId: string; setup: MaintenanceStatus | null; onOpenSetup: () => void }) {
  const desktop = bridge()
  const [run, setRun] = useState<FixRun | null>(null)
  const [loaded, setLoaded] = useState(false)
  const [title, setTitle] = useState('')
  const [body, setBody] = useState('')
  const [busy, setBusy] = useState('')
  const [error, setError] = useState('')
  const logRef = useRef<HTMLPreElement>(null)

  useEffect(() => {
    if (!desktop) return
    void desktop.maintenance.fixGet(reportId).then((current) => { setRun(current); setLoaded(true); if (current) { setTitle(current.title ?? ''); setBody(current.body ?? '') } })
    return desktop.maintenance.onEvent((event) => {
      if (event.type === 'fix' && event.run.reportId === reportId) {
        setRun(event.run.state === 'none' ? null : event.run)
        if (event.run.state === 'ready' || event.run.state === 'failed') { setTitle(event.run.title ?? ''); setBody(event.run.body ?? '') }
      }
      if (event.type === 'fix-log' && event.reportId === reportId) setRun((current) => (current ? { ...current, log: [...current.log.slice(-400), event.line] } : current))
    })
  }, [desktop, reportId])
  useEffect(() => { if (logRef.current) logRef.current.scrollTop = logRef.current.scrollHeight }, [run?.log.length])

  const act = async (name: string, task: () => Promise<unknown>) => {
    setBusy(name); setError('')
    try { await task() } catch (reason) { setError(clean(reason, 'That did not work.')) } finally { setBusy('') }
  }
  const agentName = setup?.agent ? (setup.agent.id === 'local' ? `PockPock (with ${setup.agent.model}${setup.agent.openclaw ? ' through OpenClaw' : ''})` : AGENT_NAME[setup.agent.id]) : ''

  return (
    <section className="card fix-panel" aria-labelledby="fix-title">
      <header><Wand2 size={15} /><strong id="fix-title">Maintenance Manager</strong></header>
      {error && <div className="banner banner--error" role="alert"><span>{error}</span></div>}
      {!loaded && <p className="note"><LoaderCircle size={13} className="spin" /> Loading…</p>}

      {loaded && !setup?.ready && (
        <p className="note">Set up the Maintenance Manager (AI, GitHub and a copy of PockPock) to have it fix this report. <button type="button" className="link-button" onClick={onOpenSetup}>Set it up</button></p>
      )}

      {loaded && setup?.ready && (!run || run.state === 'cancelled') && (
        <>
          <p className="note">{run?.state === 'cancelled' ? 'The last fix was stopped. ' : ''}{agentName.charAt(0).toUpperCase() + agentName.slice(1)} will look for the cause in a separate working copy of PockPock, fix it with a documentation update, and run the checks. Nothing is pushed until you approve.</p>
          <div className="card__actions"><button type="button" className="button button--primary" disabled={Boolean(busy)} onClick={() => void act('start', () => desktop!.maintenance.fixStart(reportId))}><Wand2 size={13} /> Fix with {AGENT_NAME[setup.agent?.id ?? 'local']}</button></div>
        </>
      )}

      {run?.state === 'running' && (
        <>
          <p className="working" role="status"><Mark size={16} working /> <span>{AGENT_NAME[run.agent.id] ?? run.agent.id} is working on branch <code>{run.branch}</code>…</span></p>
          <pre ref={logRef} className="setup-log fix-log" aria-live="polite">{run.log.slice(-60).join('\n')}</pre>
          <div className="card__actions"><button type="button" className="button" onClick={() => void act('cancel', () => desktop!.maintenance.fixCancel(reportId))}><Square size={13} /> Stop</button></div>
        </>
      )}

      {run?.state === 'failed' && (
        <>
          <div className="banner banner--error" role="status"><X size={14} /><span>The fix was not proposed: {run.reason}</span></div>
          {run.body && <><h3 className="fix-h">What the AI found</h3><pre className="report-capture">{run.body}</pre></>}
          {run.checks.filter((check) => !check.ok).map((check) => <details key={check.name} className="report-preview" open><summary>{check.name} output</summary><pre>{check.output}</pre></details>)}
          {run.diff && <details className="report-preview"><summary>Changes it made ({run.changed?.length ?? 0} files)</summary><pre>{run.diff}</pre></details>}
          <div className="card__actions">
            <button type="button" className="button button--primary" disabled={Boolean(busy)} onClick={() => void act('start', () => desktop!.maintenance.fixStart(reportId))}><RotateCcw size={13} /> Try again</button>
            <button type="button" className="button" disabled={Boolean(busy)} onClick={() => void act('discard', () => desktop!.maintenance.fixDiscard(reportId))}><Trash2 size={13} /> Discard</button>
          </div>
        </>
      )}

      {run?.state === 'ready' && (
        <>
          <div className="banner" role="status"><Check size={14} /><span>A fix is ready for your review on branch <code>{run.branch}</code>. {run.checks.length ? `Checks passed: ${run.checks.map((check) => check.name).join(', ')}.` : 'Only documentation changed.'}</span></div>
          <h3 className="fix-h">Changed files</h3>
          <ul className="fix-files">{run.changed?.map((file) => <li key={file}><FileText size={13} /><code>{file}</code></li>)}</ul>
          <details className="report-preview"><summary>Show the changes</summary><pre>{run.diff}</pre></details>
          <h3 className="fix-h">Pull request</h3>
          <label className="report-description"><span>Title</span><input className="input" value={title} maxLength={120} onChange={(event) => setTitle(event.target.value)} /></label>
          <label className="report-description"><span>Description</span><textarea className="input" rows={7} value={body} onChange={(event) => setBody(event.target.value)} /></label>
          <p className="note">Approving commits this change, pushes the branch to {setup?.repo?.fork ? 'your fork' : setup?.repo?.upstream}, and opens a <strong>draft</strong> pull request on {setup?.repo?.upstream}. Personal details are removed from the text first. The project owner decides whether to merge it.</p>
          <div className="card__actions">
            <button type="button" className="button button--primary" disabled={Boolean(busy) || !title.trim()} onClick={() => void act('approve', () => desktop!.maintenance.fixApprove(reportId, { title, body }).then(setRun))}>{busy === 'approve' ? <LoaderCircle size={13} className="spin" /> : <GitPullRequest size={13} />} Approve and open draft PR</button>
            <button type="button" className="button" disabled={Boolean(busy)} onClick={() => void act('discard', () => desktop!.maintenance.fixDiscard(reportId))}><Trash2 size={13} /> Discard fix</button>
          </div>
        </>
      )}

      {run?.state === 'proposed' && (
        <div className="banner" role="status"><GitPullRequest size={14} /><span>Draft pull request opened: <strong>{run.title}</strong>.</span>
          {run.prUrl && <button type="button" className="button" onClick={() => void desktop?.openExternal(run.prUrl!)}><ExternalLink size={13} /> Open on GitHub</button>}</div>
      )}
    </section>
  )
}
