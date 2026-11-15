'use client'

import { useState } from 'react'
import { ArrowUpRight, Menu, Orbit, X } from 'lucide-react'
import { CosmicMotionToggle } from './CosmicMotionToggle'

const links = [
  ['Services', '#services'], ['Work', '#work'], ['Pricing', '#pricing'], ['About', '#about'], ['Blog', '#blog'],
]

export function Nav() {
  const [open, setOpen] = useState(false)
  return <header className="nav-wrap">
    <a href="#top" className="brand" aria-label="YourBrand home"><span className="brand-mark"><Orbit size={17} /></span><span>YourBrand</span></a>
    <nav id="primary-navigation" className={`nav-links glass${open ? ' nav-links-open' : ''}`} aria-label="Main navigation">
      {links.map(([label, href]) => <a key={label} href={href} onClick={() => setOpen(false)}>{label}</a>)}
    </nav>
    <div className="nav-actions"><CosmicMotionToggle compact /><a className="nav-contact" href="mailto:hello@yourbrand.ai">Contact</a><a href="#contact" className="nav-book">Book a call <ArrowUpRight size={13} /></a></div>
    <button className="nav-menu" aria-label={open ? 'Close menu' : 'Open menu'} aria-controls="primary-navigation" aria-expanded={open} onClick={() => setOpen(!open)}>{open ? <X size={19} /> : <Menu size={19} />}</button>
  </header>
}
