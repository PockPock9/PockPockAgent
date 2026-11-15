'use client'

import { useState } from 'react'
import { motion, useReducedMotion } from 'framer-motion'
import { CalendarDays, FileText, Mail, MessageSquare, PanelsTopLeft, Phone, Radio, Sparkles, Users, Zap } from 'lucide-react'

const inputs = [
  { label: 'Email inbox', note: 'Read and route requests', icon: Mail },
  { label: 'Team chat', note: 'Catch every handoff', icon: MessageSquare },
  { label: 'CRM records', note: 'Keep customer data current', icon: PanelsTopLeft },
  { label: 'Docs & PDFs', note: 'Find answers in seconds', icon: FileText },
]
const outputs = [
  { label: 'Booked calls', note: 'Good meetings, on the calendar', icon: CalendarDays },
  { label: 'Live reports', note: 'A clear view of what changed', icon: Radio },
  { label: 'Instant actions', note: 'Follow-ups without the wait', icon: Zap },
  { label: 'Happy clients', note: 'Faster, thoughtful responses', icon: Users },
]

export function WorkflowDiagram() {
  const [active, setActive] = useState<string | null>(null)
  const reduce = useReducedMotion()
  return <section className="section container" id="workflow">
    <div className="section-heading"><span className="eyebrow"><i className="eyebrow-dot" /> From signal to done</span><h2>Watch a workflow<br />run itself.</h2><p>Connect the tools your team already uses. YourBrand handles the handoffs, decisions, and follow-through.</p></div>
    <motion.div className="workflow-panel glass" initial={reduce ? false : { opacity: 0, y: 24 }} whileInView={{ opacity: 1, y: 0 }} viewport={{ once: true, amount: .2 }} transition={{ duration: .6, ease: 'easeOut' }}>
      <div className="workflow-grid">
        <div className="node-column">{inputs.map(({ label, note, icon: Icon }, i) => <button key={label} className={`flow-node${active === `i${i}` ? ' is-active' : ''}`} onMouseEnter={() => setActive(`i${i}`)} onMouseLeave={() => setActive(null)} onFocus={() => setActive(`i${i}`)} onBlur={() => setActive(null)}><span className="flow-icon"><Icon size={16} /></span><span>{label}<small>{note}</small></span></button>)}</div>
        <div className="hub"><span className="hub-orb"><Sparkles size={22} color="#fff" /></span><span className="hub-label">YOURBRAND AI</span></div>
        <div className="node-column">{outputs.map(({ label, note, icon: Icon }, i) => <button key={label} className={`flow-node${active === `o${i}` ? ' is-active' : ''}`} onMouseEnter={() => setActive(`o${i}`)} onMouseLeave={() => setActive(null)} onFocus={() => setActive(`o${i}`)} onBlur={() => setActive(null)}><span className="flow-icon"><Icon size={16} /></span><span>{label}<small>{note}</small></span></button>)}</div>
        <svg className="flow-lines" viewBox="0 0 1000 340" preserveAspectRatio="none" aria-hidden="true">
          <defs><linearGradient id="flow-gradient"><stop stopColor="#7c5cff" stopOpacity="0" /><stop offset=".5" stopColor="#e2d7ff" /><stop offset="1" stopColor="#7c5cff" stopOpacity="0" /></linearGradient></defs>
          {[58, 132, 208, 282].map((y, i) => <g key={`l${i}`} opacity={active && active !== `i${i}` ? .16 : 1}><path d={`M 280 ${y} C 390 ${y}, 390 170, 500 170`} className="flow-base" /><path d={`M 280 ${y} C 390 ${y}, 390 170, 500 170`} className="flow-pulse" style={{ animationDelay: `${i * -.7}s` }} /></g>)}
          {[58, 132, 208, 282].map((y, i) => <g key={`r${i}`} opacity={active && active !== `o${i}` ? .16 : 1}><path d={`M 500 170 C 610 170, 610 ${y}, 720 ${y}`} className="flow-base" /><path d={`M 500 170 C 610 170, 610 ${y}, 720 ${y}`} className="flow-pulse" style={{ animationDelay: `${i * -.8 - .4}s` }} /></g>)}
        </svg>
      </div>
      <div className="stats-row"><div className="stat"><strong>&lt; 5 min</strong><span>to launch a workflow</span></div><div className="stat"><strong>24/7</strong><span>always-on follow-through</span></div><div className="stat"><strong>100%</strong><span>visibility and control</span></div></div>
    </motion.div>
  </section>
}
