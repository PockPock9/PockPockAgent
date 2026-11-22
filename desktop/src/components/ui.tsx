// Small shared UI pieces: popover menus, markdown, icon buttons, status dots.
import { memo, useEffect, useRef, useState } from 'react'
import type { ReactNode } from 'react'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import { Check, Copy } from 'lucide-react'

export function Popover({ open, onClose, children, align = 'left', className = '' }: {
  open: boolean
  onClose: () => void
  children: ReactNode
  align?: 'left' | 'right'
  className?: string
}) {
  const ref = useRef<HTMLDivElement>(null)
  useEffect(() => {
    if (!open) return
    const onPointer = (event: PointerEvent) => {
      const target = event.target as Node
      if (ref.current?.contains(target)) return
      if ((target as Element).closest?.('[data-popover-toggle="open"]')) return
      onClose()
    }
    const onKey = (event: KeyboardEvent) => { if (event.key === 'Escape') onClose() }
    document.addEventListener('pointerdown', onPointer, true)
    document.addEventListener('keydown', onKey)
    return () => { document.removeEventListener('pointerdown', onPointer, true); document.removeEventListener('keydown', onKey) }
  }, [open, onClose])
  if (!open) return null
  return <div ref={ref} className={`popover popover--${align} ${className}`} role="menu">{children}</div>
}

export function MenuItem({ icon, title, detail, selected, disabled, danger, onSelect }: {
  icon?: ReactNode
  title: string
  detail?: string
  selected?: boolean
  disabled?: boolean
  danger?: boolean
  onSelect: () => void
}) {
  return (
    <button type="button" role="menuitemradio" aria-checked={Boolean(selected)} className={`menu-item${selected ? ' is-selected' : ''}${danger ? ' is-danger' : ''}`} disabled={disabled} onClick={onSelect}>
      {icon && <span className="menu-item__icon">{icon}</span>}
      <span className="menu-item__text"><span>{title}</span>{detail && <small>{detail}</small>}</span>
      {selected && <Check size={14} className="menu-item__check" />}
    </button>
  )
}

export function IconButton({ label, onClick, children, active, disabled, className = '' }: {
  label: string
  onClick: () => void
  children: ReactNode
  active?: boolean
  disabled?: boolean
  className?: string
}) {
  return (
    <button type="button" className={`icon-button${active ? ' is-active' : ''} ${className}`} aria-label={label} title={label} aria-pressed={active} disabled={disabled} onClick={onClick}>
      {children}
    </button>
  )
}

export function Dot({ tone }: { tone: 'ok' | 'warn' | 'off' | 'busy' | 'err' }) {
  return <span className={`dot dot--${tone}`} aria-hidden="true" />
}

function CodeBlock({ children }: { children?: ReactNode }) {
  const ref = useRef<HTMLPreElement>(null)
  const [copied, setCopied] = useState(false)
  const copy = () => {
    void navigator.clipboard.writeText(ref.current?.innerText ?? '').then(() => { setCopied(true); window.setTimeout(() => setCopied(false), 1400) })
  }
  return (
    <div className="code-block">
      <button type="button" className="code-block__copy" onClick={copy} aria-label="Copy code">{copied ? <Check size={13} /> : <Copy size={13} />}</button>
      <pre ref={ref}>{children}</pre>
    </div>
  )
}

const plugins = [remarkGfm]
const components = { pre: CodeBlock }
export const Markdown = memo(function Markdown({ content }: { content: string }) {
  return <div className="markdown"><ReactMarkdown remarkPlugins={plugins} components={components}>{content}</ReactMarkdown></div>
})

export function Empty({ icon, title, children }: { icon: ReactNode; title: string; children?: ReactNode }) {
  return <div className="empty"><span className="empty__icon">{icon}</span><strong>{title}</strong>{children}</div>
}
