// Shared pieces of the Workshop and System pages: the page frame, switches, error and loading rows,
// tabs with counts, stat tiles, and a side drawer for details.
import { useEffect, useRef } from 'react'
import type { KeyboardEvent, ReactNode } from 'react'
import { LoaderCircle, X } from 'lucide-react'

export function PageFrame({ title, eyebrow, intro, children, actions, wide }: { title: string; eyebrow: string; intro: string; children: ReactNode; actions?: ReactNode; wide?: boolean }) {
  return (
    <div className="page">
      <div className={`page__inner${wide ? ' page__inner--wide' : ''}`}>
        <header className="page__head">
          <div><span className="eyebrow">{eyebrow}</span><h1>{title}</h1><p>{intro}</p></div>
          {actions && <div className="page__actions">{actions}</div>}
        </header>
        {children}
      </div>
    </div>
  )
}

export function Toggle({ checked, busy, label, onChange }: { checked: boolean; busy?: boolean; label: string; onChange: (next: boolean) => void }) {
  return <button type="button" role="switch" aria-checked={checked} aria-label={label} className="switch" disabled={busy} onClick={() => onChange(!checked)}><span /></button>
}

export function ErrorNote({ message, onRetry }: { message: string; onRetry?: () => void }) {
  if (!message) return null
  return <div className="banner banner--error" role="alert"><span>{message}</span>{onRetry && <button type="button" className="button button--small" onClick={onRetry}>Try again</button>}</div>
}

export function Loading({ children }: { children: ReactNode }) {
  return <p className="note" role="status"><LoaderCircle size={13} className="spin" aria-hidden="true" /> {children}</p>
}

/** A row of tabs with counts. Arrow keys move between tabs. */
export function Tabs<T extends string>({ label, tabs, value, onChange, controls }: { label: string; tabs: Array<{ id: T; label: string; count?: number }>; value: T; onChange: (id: T) => void; controls: string }) {
  const refs = useRef<Array<HTMLButtonElement | null>>([])
  const onKey = (event: KeyboardEvent) => {
    const step = event.key === 'ArrowRight' ? 1 : event.key === 'ArrowLeft' ? -1 : 0
    if (!step) return
    event.preventDefault()
    const next = (tabs.findIndex((tab) => tab.id === value) + step + tabs.length) % tabs.length
    onChange(tabs[next].id)
    refs.current[next]?.focus()
  }
  return (
    <div className="tabs" role="tablist" aria-label={label} onKeyDown={onKey}>
      {tabs.map((tab, index) => (
        <button key={tab.id} ref={(node) => { refs.current[index] = node }} type="button" role="tab" id={`${controls}-tab-${tab.id}`} aria-selected={value === tab.id} aria-controls={controls}
          tabIndex={value === tab.id ? 0 : -1} className={value === tab.id ? 'is-active' : ''} onClick={() => onChange(tab.id)}>
          {tab.label}{tab.count !== undefined && <small>{tab.count}</small>}
        </button>
      ))}
    </div>
  )
}

export function Stat({ icon, label, value }: { icon: ReactNode; label: string; value: ReactNode }) {
  return <div className="stat">{icon}<span>{label}</span><strong>{value}</strong></div>
}

/** Details beside a list: a panel over the right side of the page. Escape or the close button closes it
 * and focus returns to what opened it. */
export function Drawer({ title, onClose, children, footer }: { title: string; onClose: () => void; children: ReactNode; footer?: ReactNode }) {
  const ref = useRef<HTMLElement>(null)
  useEffect(() => {
    const opener = document.activeElement as HTMLElement | null
    ref.current?.querySelector<HTMLElement>('button, a, input, select, textarea')?.focus()
    const onKey = (event: globalThis.KeyboardEvent) => { if (event.key === 'Escape') { event.preventDefault(); onClose() } }
    document.addEventListener('keydown', onKey)
    return () => { document.removeEventListener('keydown', onKey); opener?.focus?.() }
  }, [onClose])
  return (
    <>
      <button type="button" className="drawer-backdrop" aria-label="Close details" onClick={onClose} />
      <aside ref={ref} className="drawer" role="dialog" aria-modal="true" aria-label={title}>
        <header className="drawer__head"><h2>{title}</h2><button type="button" className="icon-button" aria-label="Close" onClick={onClose}><X size={15} /></button></header>
        <div className="drawer__body">{children}</div>
        {footer && <footer className="drawer__foot">{footer}</footer>}
      </aside>
    </>
  )
}
