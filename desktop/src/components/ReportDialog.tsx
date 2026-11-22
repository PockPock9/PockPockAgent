// "Report a problem" for one assistant reply: what went wrong, the user's description, and a preview
// of exactly what will be saved (redacted by the main process). Reports stay on this PC.
import { useEffect, useRef, useState } from 'react'
import { Check, Flag, LoaderCircle, X } from 'lucide-react'
import { bridge } from '../lib/types'
import type { Message, Redactions, ReportCapture, ReportCategory, Session } from '../lib/types'
import { buildCapture, captureText, CATEGORY_LABEL, describeRedactions } from '../lib/reports'

const CATEGORIES = Object.keys(CATEGORY_LABEL) as ReportCategory[]

export function ReportDialog({ session, message, onClose, onOpenMaintenance }: {
  session: Session
  message: Message
  onClose: () => void
  onOpenMaintenance: () => void
}) {
  const desktop = bridge()
  const dialogRef = useRef<HTMLDivElement>(null)
  const [category, setCategory] = useState<ReportCategory | ''>(message.status === 'error' ? 'failed' : message.status === 'stopped' ? 'hang' : '')
  const [description, setDescription] = useState('')
  const [capture, setCapture] = useState<ReportCapture | null>(null)
  const [preview, setPreview] = useState<{ capture: ReportCapture; redactions: Redactions } | null>(null)
  const [phase, setPhase] = useState<'editing' | 'saving' | 'saved'>('editing')
  const [error, setError] = useState('')

  useEffect(() => {
    if (!desktop) return
    void desktop.info().then((info) => {
      const built = buildCapture(session, message, { version: info.version, platform: `${info.platform} ${info.arch}` })
      setCapture(built)
      return desktop.reports.preview(built).then(setPreview)
    }).catch((reason: unknown) => setError(reason instanceof Error ? reason.message : 'The reply could not be captured.'))
  }, [desktop, session, message])

  // Modal behaviour: focus inside on open, Escape closes, Tab stays inside the dialog, and focus goes
  // back to what opened it (the Report button) when it closes.
  const closeRef = useRef(onClose)
  closeRef.current = onClose
  useEffect(() => {
    const opener = document.activeElement as HTMLElement | null
    return () => { opener?.focus?.() }
  }, [])
  useEffect(() => {
    const dialog = dialogRef.current
    dialog?.querySelector<HTMLElement>('input, textarea, button')?.focus()
    const onKey = (event: KeyboardEvent) => {
      if (event.key === 'Escape') { event.preventDefault(); closeRef.current(); return }
      if (event.key !== 'Tab' || !dialog) return
      const focusable = [...dialog.querySelectorAll<HTMLElement>('input, textarea, button, summary, [tabindex]:not([tabindex="-1"])')].filter((el) => !el.hasAttribute('disabled'))
      if (!focusable.length) return
      const first = focusable[0]; const last = focusable[focusable.length - 1]
      if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last.focus() }
      else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first.focus() }
    }
    document.addEventListener('keydown', onKey)
    return () => document.removeEventListener('keydown', onKey)
  }, [phase])

  const save = async () => {
    if (!desktop || !capture || !category) return
    setPhase('saving'); setError('')
    try {
      await desktop.reports.create({ category, description: description.trim(), capture })
      setPhase('saved')
    } catch (reason) {
      setError(reason instanceof Error ? reason.message.replace(/^Error invoking remote method '[^']+': (Error: )?/, '') : 'The report could not be saved.')
      setPhase('editing')
    }
  }

  return (
    <div className="modal-backdrop" onMouseDown={(event) => { if (event.target === event.currentTarget) onClose() }}>
      <div ref={dialogRef} className="modal" role="dialog" aria-modal="true" aria-labelledby="report-title">
        <header className="modal__head">
          <h2 id="report-title"><Flag size={16} /> Report a problem with this reply</h2>
          <button type="button" className="icon-button" onClick={onClose} aria-label="Close"><X size={15} /></button>
        </header>
        {phase === 'saved' ? (
          <div className="modal__body">
            <p className="modal__done" role="status"><Check size={15} /> Report saved on this PC. You can review, change or delete it on the <strong>Maintenance</strong> page.</p>
            <div className="card__actions">
              <button type="button" className="button button--primary" onClick={onOpenMaintenance}>Open Maintenance</button>
              <button type="button" className="button" onClick={onClose}>Close</button>
            </div>
          </div>
        ) : (
          <form className="modal__form" onSubmit={(event) => { event.preventDefault(); void save() }}>
            <div className="modal__body">
            <fieldset className="report-categories">
              <legend>What went wrong?</legend>
              {CATEGORIES.map((id) => (
                <label key={id} className={category === id ? 'is-chosen' : undefined}>
                  <input type="radio" name="report-category" value={id} checked={category === id} onChange={() => setCategory(id)} />
                  <span><strong>{CATEGORY_LABEL[id].title}</strong><em>{CATEGORY_LABEL[id].detail}</em></span>
                </label>
              ))}
            </fieldset>
            <label className="report-description">
              <span>What happened, and what did you expect?</span>
              <textarea className="input" rows={4} maxLength={4000} value={description} onChange={(event) => setDescription(event.target.value)}
                placeholder="For example: it opened the page but never clicked Download, then stopped." />
            </label>
            <details className="report-preview">
              <summary>What will be saved</summary>
              {preview ? (
                <>
                  <p className="note">{describeRedactions(preview.redactions)} Your description is checked the same way when you save. Attachment contents are never included. The report stays on this PC.</p>
                  <pre>{captureText(preview.capture)}</pre>
                </>
              ) : <p className="note"><LoaderCircle size={13} className="spin" /> Preparing…</p>}
            </details>
            {error && <p className="card__error" role="alert">{error}</p>}
            </div>
            <div className="card__actions modal__foot">
              <button type="submit" className="button button--primary" disabled={!category || !description.trim() || !capture || phase === 'saving'}>
                {phase === 'saving' ? <LoaderCircle size={13} className="spin" /> : <Flag size={13} />} Save report
              </button>
              <button type="button" className="button" onClick={onClose}>Cancel</button>
              {(!category || !description.trim()) && <span className="note">{!category ? 'Choose what went wrong' : 'Describe what happened'} to save.</span>}
            </div>
          </form>
        )}
      </div>
    </div>
  )
}
