'use client'

import { useState } from 'react'
import { motion, useReducedMotion } from 'framer-motion'
import { ArrowRight, ArrowUpRight, AtSign, Bot, ChartNoAxesCombined, Clock3, FileSearch, MessageCircle, Quote, Send, ShieldCheck, Sparkles, Workflow } from 'lucide-react'

const services = [
  { title: 'Lead operations', copy: 'Give every new conversation a thoughtful, timely next step.', icon: MessageCircle },
  { title: 'Knowledge work', copy: 'Turn scattered docs and updates into clear, useful answers.', icon: FileSearch },
  { title: 'Team coordination', copy: 'Keep handoffs moving across the tools your team already uses.', icon: Workflow },
  { title: 'Reporting & insight', copy: 'See what changed and what needs attention, without asking.', icon: ChartNoAxesCombined },
]
const work = [
  { metric: '12 hrs back / week', title: 'A warmer first response', copy: 'A growing services team automated intake and made space for better client conversations.' },
  { metric: '3× faster', title: 'From signal to follow-up', copy: 'A sales crew connected their inbox, CRM and calendar into one steady routine.' },
  { metric: '40% less admin', title: 'Clearer daily operations', copy: 'A distributed team gathered updates into a useful morning brief, automatically.' },
]
const quotes = [
  { quote: 'The little handoffs that used to break our day just happen now. We have more time for actual client work.', name: 'Maya Chen', role: 'Operations lead, Northstar', initials: 'MC' },
  { quote: 'It feels less like adding software and more like getting a teammate who never forgets the follow-up.', name: 'Jordan Ellis', role: 'Founder, Common Ground', initials: 'JE' },
  { quote: 'We can see exactly what each workflow did, and step in whenever we want. That trust mattered.', name: 'Ari Morgan', role: 'Head of growth, Fieldwork', initials: 'AM' },
]
const posts = [
  { tag: 'A better rhythm', title: 'The quiet power of a five-minute follow-up', copy: 'Small, timely actions change how a customer experiences your whole team.', icon: Clock3 },
  { tag: 'Inside operations', title: 'Give your team a morning back', copy: 'A simple guide to making the first hour of work feel a little lighter.', icon: Sparkles },
  { tag: 'Trust by design', title: 'Automation that keeps people in control', copy: 'How clear steps and thoughtful review build confidence in AI work.', icon: ShieldCheck },
]

export function Reveal({ children, className = '' }: { children: React.ReactNode; className?: string }) {
  const reduce = useReducedMotion()
  return <motion.div className={className} initial={reduce ? false : { opacity: 0, y: 24 }} whileInView={{ opacity: 1, y: 0 }} viewport={{ once: true, amount: .14 }} transition={{ duration: .6, ease: 'easeOut' }}>{children}</motion.div>
}

export function Services() {
  const [point, setPoint] = useState<Record<number, { x: number; y: number }>>({})
  return <section className="section container" id="services"><div className="section-heading"><span className="eyebrow"><i className="eyebrow-dot" /> More room for meaningful work</span><h2>Your day, with fewer<br />things in the way.</h2><p>Thoughtful agents take care of the repeatable work between the big moments.</p></div><div className="services-grid">{services.map(({ title, copy, icon: Icon }, i) => <article className="service-card glass card-hover" key={title} onMouseMove={(e) => { const rect = e.currentTarget.getBoundingClientRect(); setPoint((p) => ({ ...p, [i]: { x: e.clientX - rect.left, y: e.clientY - rect.top } })) }} style={{ ['--x' as string]: `${point[i]?.x ?? 50}%`, ['--y' as string]: `${point[i]?.y ?? 50}%` }}><div className="service-glow" /><span className="service-icon"><Icon size={18} /></span><h3>{title}</h3><p>{copy}</p></article>)}</div></section>
}

export function Work() {
  return <section className="section container" id="work"><div className="section-heading"><span className="eyebrow"><i className="eyebrow-dot" /> Small shifts, real impact</span><h2>Less operational drag.<br />More forward motion.</h2><p>Good automation gives people more time to do the work only people can do.</p></div><div className="work-grid">{work.map((item) => <article className="work-card glass card-hover" key={item.title}><div className="work-visual"><Sparkles size={22} /></div><strong>{item.metric}</strong><h3>{item.title}</h3><p>{item.copy}</p></article>)}</div></section>
}

export function Testimonials() {
  return <section className="section container" id="about"><div className="section-heading"><span className="eyebrow"><i className="eyebrow-dot" /> Good company, doing good work</span><h2>Made for the people<br />behind the work.</h2><p>Helping small, thoughtful teams make the everyday feel easier.</p></div><div className="logo-row" aria-label="Teams we work with"><span>northstar</span><span>Common Ground</span><span>FIELDWORK</span><span>daylight</span><span>monument</span></div><div className="testimonial-grid">{quotes.map((item) => <article className="quote-card glass card-hover" key={item.name}><Quote size={19} color="#73bcff" /><blockquote>“{item.quote}”</blockquote><div className="quote-author"><span className="avatar">{item.initials}</span><span><b style={{ display: 'block', color: '#e5dff5', fontWeight: 500 }}>{item.name}</b>{item.role}</span></div></article>)}</div></section>
}

export function BlogAndCta() {
  return <><section className="section container" id="blog"><div className="section-heading"><span className="eyebrow"><i className="eyebrow-dot" /> Notes for a more human workflow</span><h2>Ideas for work<br />that flows better.</h2></div><div className="blog-grid">{posts.map(({ tag, title, copy, icon: Icon }) => <a className="blog-card glass card-hover" key={title} href="#contact"><div className="blog-art"><Icon size={35} strokeWidth={1.2} /></div><div className="blog-copy"><small>{tag} · 5 min read</small><h3>{title}</h3><p>{copy}</p></div></a>)}</div></section><section className="container" id="contact"><div className="final-cta glass"><div className="horizon" aria-hidden="true" /><span className="eyebrow"><i className="eyebrow-dot" /> Your next good idea starts here</span><h2>Let's give your team<br />a little more room.</h2><p>Bring us one repetitive task. We’ll help you see what could change.</p><a href="mailto:hello@yourbrand.ai" className="button button-primary">Talk to our team <ArrowRight size={15} /></a></div></section></>
}

export function Footer() {
  return <footer className="container"><div className="footer"><div className="footer-brand"><a href="#top" className="brand"><span className="brand-mark"><Bot size={17} /></span><span>YourBrand</span></a><p>Thoughtful AI agents for the work that keeps your business moving.</p><div style={{ display: 'flex', gap: 13, color: '#a39abf' }}><a href="#contact" aria-label="Professional network"><Send size={15} /></a><a href="#contact" aria-label="Social updates"><AtSign size={15} /></a><a href="mailto:hello@yourbrand.ai" aria-label="Email"><ArrowUpRight size={15} /></a></div></div><div><h4>Explore</h4><div className="footer-links"><a href="#services">Services</a><a href="#work">Our work</a><a href="#pricing">Pricing</a></div></div><div><h4>Company</h4><div className="footer-links"><a href="#about">About us</a><a href="#blog">Journal</a><a href="mailto:hello@yourbrand.ai">Contact</a></div></div><div><h4>Take a look</h4><div className="footer-links"><a href="/app">Your workspace</a><a href="#contact">Get in touch</a><a href="#top">Back to top ↑</a></div></div></div><div className="footer-bottom"><span>© 2026 YOURBRAND STUDIO</span><span>Privacy · Terms · Made with intention</span></div></footer>
}
