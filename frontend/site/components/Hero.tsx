'use client'

import { motion, useReducedMotion } from 'framer-motion'
import { ArrowRight, Check, Play } from 'lucide-react'

export function Hero() {
  const reduce = useReducedMotion()
  return <section id="top" className="hero container">
    <div className="hero-glow" aria-hidden="true" />
    <motion.div initial={reduce ? false : { opacity: 0, y: 18 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: .65, ease: 'easeOut' }}>
      <span className="eyebrow"><i className="eyebrow-dot" /> AI agents for operations</span>
      <h1>Your operations,<br /><span>on autopilot.</span></h1>
      <p className="hero-copy">Give your team its time back. YourBrand agents take care of the busywork, so good work moves faster.</p>
      <div className="hero-actions"><a href="#contact" className="button button-primary">Build your first workflow <ArrowRight size={15} /></a><a href="#workflow" className="button button-glass"><Play size={14} /> See how it works</a></div>
    </motion.div>
    <div className="horizon hero-horizon" aria-hidden="true" />
    <motion.div className="agent-card glass" initial={reduce ? false : { opacity: 0, y: 24 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: .7, delay: .18, ease: 'easeOut' }}>
      <div className="agent-card-header"><div className="agent-title"><i className="agent-orb" /> Operations agent <span style={{ color: '#85809c' }}>· inbound follow-up</span></div><span className="status-chip">RUNNING</span></div>
      <p className="agent-prompt">✦ Qualify new inbound leads and book calls with the right people</p>
      {['Read 128 new leads from your CRM', 'Enriched company and role details', 'Found 23 high-intent conversations', 'Drafted personal replies', 'Booked 7 calls on your calendar'].map((step, i) => <div className="feed-row" key={step}><span className="feed-check"><Check size={10} /></span><span>{step}</span><small>{['0.8s', '1.4s', '0.6s', '2.1s', 'synced'][i]}</small></div>)}
    </motion.div>
  </section>
}
