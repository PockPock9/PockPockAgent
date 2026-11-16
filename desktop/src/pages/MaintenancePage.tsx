// Maintenance: problem reports made with the Report button on a reply. They stay on this PC; each can
// be reviewed, corrected or deleted here. (The Maintenance Manager that works through open reports
// and proposes fixes is LRN-04 in docs/TASKS.md.)
import { useCallback, useEffect, useState } from 'react'
import { ArrowLeft, Flag, LoaderCircle, Trash2, Wrench } from 'lucide-react'
import { Empty } from '../components/ui'
import { MaintenanceSetup } from '../components/MaintenanceSetup'
import { FixPanel } from '../components/FixPanel'
import { PageFrame } from './Pages'
import { bridge } from '../lib/types'
import type { MaintenanceStatus, Report, ReportCategory, ReportStatus, ReportSummary } from '../lib/types'
import { captureText, CATEGORY_LABEL, describeRedactions, STATUS_LABEL } from '../lib/reports'
import { relativeTime } from '../lib/api'

const clean = (reason: unknown, fallback: string) => (reason instanceof Error ? reason.message.replace(/^Error invoking remote method '[^']+': (Error: )?/, '') : fallback)

export function MaintenancePage() {
  const desktop = bridge()
  const [reports, setReports] = useState<ReportSummary[] | null>(null)
  const [error, setError] = useState('')
  const [open, setOpen] = useState<string | null>(null)
  const [setup, setSetup] = useState<MaintenanceStatus | null>(null)

  const load = useCallback(() => {
    if (!desktop) return
    desktop.maintenance.status().then(setSetup, () => setSetup(null))
    desktop.reports.list().then((list) => { setReports(list); setError('') }, (reason: unknown) => setError(clean(reason, 'Reports could not be loaded.')))
  }, [desktop])
  useEffect(() => { load() }, [load])
  // A fix starting or finishing (also in automatic mode) changes report statuses: refresh the list.
  useEffect(() => desktop?.maintenance.onEvent((event) => { if (event.type === 'fix') load() }), [desktop, load])

  if (open) return <ReportDetail id={open} setup={setup} onBack={() => { setOpen(null); load() }} />
  const openCount = reports?.filter((report) => report.status === 'open').length ?? 0
  return (
    <PageFrame eyebrow="System" title="Maintenance" intro="Problems you reported with the Report button under a reply. Each report keeps that exchange so it can be reproduced and fixed. Reports stay on this PC.">
      {error && <div className="banner banner--error" role="alert"><span>{error}</span></div>}
      {setup && <MaintenanceSetup status={setup} onChange={load} />}
      <h2 className="section-title">Reports</h2>
      {!reports && !error && <p className="note"><LoaderCircle size={13} className="spin" /> Loading reports…</p>}
      {reports && reports.length === 0 && (
        <Empty icon={<Flag size={20} />} title="No reports yet"><p>When a reply hangs, fails or gets something wrong, press <strong>Report</strong> under it to describe what happened.</p></Empty>
      )}
      {reports && reports.length > 0 && (
        <>
          <p className="note">{reports.length} {reports.length === 1 ? 'report' : 'reports'}, {openCount} open.</p>
          <ul className="rows">
            {reports.map((report) => (
              <li key={report.id} className="row report-row">
                <Wrench size={16} className="row__icon" />
                <button type="button" className="report-row__open" onClick={() => setOpen(report.id)} aria-label={`Open report: ${CATEGORY_LABEL[report.category].title}${report.chatTitle ? `, ${report.chatTitle}` : ''}`}>
                  <span className="row__text">
                    <strong>{CATEGORY_LABEL[report.category].title}<small className={`badge ${report.status === 'open' ? 'badge--warn' : report.status === 'fixed' ? 'badge--ok' : 'badge--off'}`}>{STATUS_LABEL[report.status]}</small></strong>
                    <span>{report.description || 'No description'}</span>
                    <small>{[report.chatTitle, report.engine, relativeTime(report.createdAt)].filter(Boolean).join(' · ')}</small>
                  </span>
                </button>
              </li>
            ))}
          </ul>
        </>
      )}
    </PageFrame>
  )
}

function ReportDetail({ id, setup, onBack }: { id: string; setup: MaintenanceStatus | null; onBack: () => void }) {
  const desktop = bridge()
  const [report, setReport] = useState<Report | null>(null)
  const [draft, setDraft] = useState<{ category: ReportCategory; status: ReportStatus; description: string } | null>(null)
  const [message, setMessage] = useState('')
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)

  useEffect(() => {
    if (!desktop) return
    desktop.reports.get(id).then((loaded) => { setReport(loaded); setDraft({ category: loaded.category, status: loaded.status, description: loaded.description }) }, (reason: unknown) => setError(clean(reason, 'The report could not be opened.')))
  }, [desktop, id])

  const save = async () => {
    if (!desktop || !draft) return
    setBusy(true); setError(''); setMessage('')
    try { setReport(await desktop.reports.update(id, draft)); setMessage('Saved.') } catch (reason) { setError(clean(reason, 'The report could not be saved.')) } finally { setBusy(false) }
  }
  const remove = async () => {
    if (!desktop || !window.confirm('Delete this report? This cannot be undone.')) return
    try { await desktop.reports.delete(id); onBack() } catch (reason) { setError(clean(reason, 'The report could not be deleted.')) }
  }

  return (
    <PageFrame eyebrow="Maintenance" title="Report" intro={report ? `Reported ${relativeTime(report.createdAt)}${report.capture.chatTitle ? ` from “${report.capture.chatTitle}”` : ''}.` : 'Loading…'}
      actions={<button type="button" className="button" onClick={onBack}><ArrowLeft size={13} /> All reports</button>}>
      {error && <div className="banner banner--error" role="alert"><span>{error}</span></div>}
      {message && <div className="banner" role="status"><span>{message}</span></div>}
      {!report && !error && <p className="note"><LoaderCircle size={13} className="spin" /> Loading…</p>}
      {report && draft && (
        <>
          <section className="card report-edit">
            <div className="report-edit__grid">
              <label><span>What went wrong</span>
                <select className="input" value={draft.category} onChange={(event) => setDraft({ ...draft, category: event.target.value as ReportCategory })}>
                  {(Object.keys(CATEGORY_LABEL) as ReportCategory[]).map((key) => <option key={key} value={key}>{CATEGORY_LABEL[key].title}</option>)}
                </select>
              </label>
              <label><span>Status</span>
                <select className="input" value={draft.status} onChange={(event) => setDraft({ ...draft, status: event.target.value as ReportStatus })}>
                  {(Object.keys(STATUS_LABEL) as ReportStatus[]).map((key) => <option key={key} value={key}>{STATUS_LABEL[key]}</option>)}
                </select>
              </label>
            </div>
            <label className="report-description"><span>Description</span>
              <textarea className="input" rows={4} maxLength={4000} value={draft.description} onChange={(event) => setDraft({ ...draft, description: event.target.value })} />
            </label>
            <div className="card__actions">
              <button type="button" className="button button--primary" disabled={busy} onClick={() => void save()}>{busy && <LoaderCircle size={13} className="spin" />} Save changes</button>
              <button type="button" className="button" onClick={() => void remove()}><Trash2 size={13} /> Delete report</button>
            </div>
          </section>
          <FixPanel reportId={id} setup={setup} onOpenSetup={onBack} />
          <h2 className="section-title">Captured exchange</h2>
          <p className="note">{describeRedactions(report.redactions)}</p>
          <pre className="report-capture">{captureText(report.capture)}</pre>
        </>
      )}
    </PageFrame>
  )
}
