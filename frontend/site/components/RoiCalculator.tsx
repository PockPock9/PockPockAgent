'use client'

import { useMemo, useState } from 'react'
import { ArrowUpRight } from 'lucide-react'

const fmt = new Intl.NumberFormat('en-US')

export function RoiCalculator() {
  const [team, setTeam] = useState(12)
  const [hours, setHours] = useState(8)
  const [rate, setRate] = useState(65)
  const savings = useMemo(() => Math.round(team * hours * rate * 52 * .75), [team, hours, rate])
  const values = [22, 32, 29, 40, 38, 51, 49, 61, 57, 73, 80, 96]
  const sliders = [
    { id: 'team-size', label: 'People on your team', value: team, min: 2, max: 60, unit: ' people', change: setTeam },
    { id: 'hours-saved', label: 'Hours saved per week', value: hours, min: 1, max: 25, unit: ' hrs', change: setHours },
    { id: 'hourly-cost', label: 'Average hourly cost', value: rate, min: 20, max: 200, unit: '/ hr', change: setRate },
  ]
  return <section className="section container" id="roi">
    <div className="section-heading"><span className="eyebrow"><i className="eyebrow-dot" /> Time back, made visible</span><h2>What could your team<br />do with the time back?</h2><p>Adjust the sliders to see what everyday automation can give back to your team.</p></div>
    <div className="roi-card glass">
      <div className="roi-controls">{sliders.map((slider) => <div className="range-row" key={slider.label}><label htmlFor={slider.id}><span>{slider.label}</span><output>{slider.value}{slider.unit}</output></label><input id={slider.id} aria-label={slider.label} type="range" min={slider.min} max={slider.max} value={slider.value} onChange={(e) => slider.change(Number(e.target.value))} /></div>)}</div>
      <div className="roi-result"><span className="eyebrow">Estimated annual value returned</span><strong>${fmt.format(savings)}</strong><p>Based on time your team could spend moving the work that matters.</p><div className="spark-bars" aria-label="Projected value returned over twelve months">{values.map((value, i) => <i key={i} style={{ height: `${value}%` }} />)}</div><a className="button button-primary" href="#contact">Find your team's number <ArrowUpRight size={14} /></a></div>
    </div>
  </section>
}
