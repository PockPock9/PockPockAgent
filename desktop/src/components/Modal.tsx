// A modal dialog: dims the window, keeps focus inside until it closes (Tab wraps), closes with Escape
// or a click on the backdrop, and gives focus back to what opened it.
import { useEffect, useRef } from 'react'
import type { ReactNode } from 'react'
import { X } from 'lucide-react'

export function Modal({ title, icon, onClose, children, footer, wide }: { title: string; icon?: ReactNode; onClose: () => void; children: ReactNode; footer?: ReactNode; wide?: boolean }) {
  const ref = useRef<HTMLDivElement>(null)
  const closeRef = useRef(onClose)
  closeRef.current = onClose
  useEffect(() => {
    const opener = document.activeElement as HTMLElement | null
    const dialog = ref.current
    const focusable = () => [...(dialog?.querySelectorAll<HTMLElement>('a[href], button, input, select, textarea, summary, [tabindex]:not([tabindex="-1"])') ?? [])].filter((item) => !item.hasAttribute('disabled'))
    ;(dialog?.querySelector<HTMLElement>('.modal__body input, .modal__body select, .modal__body textarea, .modal__body button') ?? focusable()[0])?.focus()
    const onKey = (event: KeyboardEvent) => {
      if (event.key === 'Escape') { event.preventDefault(); closeRef.current(); return }
      if (event.key !== 'Tab') return
      const items = focusable()
      if (!items.length) return
      const first = items[0]; const last = items[items.length - 1]
      if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last.focus() }
      else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first.focus() }
    }
    document.addEventListener('keydown', onKey)
    return () => { document.removeEventListener('keydown', onKey); opener?.focus?.() }
  }, [])
  return (
    <div className="modal-backdrop" onMouseDown={(event) => { if (event.target === event.currentTarget) onClose() }}>
      <div ref={ref} className={`modal${wide ? ' modal--wide' : ''}`} role="dialog" aria-modal="true" aria-label={title}>
        <header className="modal__head"><h2>{icon}{title}</h2><button type="button" className="icon-button" aria-label="Close" onClick={onClose}><X size={15} /></button></header>
        <div className="modal__body">{children}</div>
        {footer && <footer className="card__actions modal__foot">{footer}</footer>}
      </div>
    </div>
  )
}
