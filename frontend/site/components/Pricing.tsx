'use client'

import { useState } from 'react'
import { Check } from 'lucide-react'

const plans = [
  { name: 'Starter', description: 'A calmer way to handle the everyday.', monthly: 49, annual: 39, features: ['3 active workflows', '1,000 runs per month', 'Core integrations', 'Email support'] },
  { name: 'Studio', description: 'A capable operations partner for your team.', monthly: 149, annual: 119, features: ['Unlimited workflows', '10,000 runs per month', 'All integrations', 'Priority support', 'Team workspaces'] },
  { name: 'Company', description: 'More control for complex operations.', monthly: 399, annual: 319, features: ['Everything in Studio', 'Custom run capacity', 'Advanced permissions', 'Dedicated onboarding', 'Human review controls'] },
]

export function Pricing() {
  const [annual, setAnnual] = useState(true)
  return <section className="section container" id="pricing">
    <div className="section-heading"><span className="eyebrow"><i className="eyebrow-dot" /> Clear plans, room to grow</span><h2>A little less busywork<br />starts here.</h2><p>Start small. Add capacity as the workflows your team trusts grow.</p></div>
    <div className="pricing-toggle" role="group" aria-label="Billing period"><button aria-pressed={!annual} onClick={() => setAnnual(false)}>Monthly</button><button aria-pressed={annual} onClick={() => setAnnual(true)}>Yearly <small> save 20%</small></button></div>
    <div className="pricing-grid">{plans.map((plan, i) => <article className={`price-card glass card-hover${i === 1 ? ' popular' : ''}`} key={plan.name}>{i === 1 && <span className="popular-pill">Most popular</span>}<h3>{plan.name}</h3><p>{plan.description}</p><div className="price">${annual ? plan.annual : plan.monthly}<small> / month</small></div><ul className="price-list">{plan.features.map((feature) => <li key={feature}><Check size={14} /> {feature}</li>)}</ul><a href="#contact" className={`button ${i === 1 ? 'button-primary' : 'button-glass'}`}>{i === 2 ? 'Talk with our team' : 'Get started'}</a></article>)}</div>
  </section>
}
