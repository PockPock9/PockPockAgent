import { Nav } from './Nav'
import { Hero } from './Hero'
import { WorkflowDiagram } from './WorkflowDiagram'
import { RoiCalculator } from './RoiCalculator'
import { Pricing } from './Pricing'
import { BlogAndCta, Footer, Reveal, Services, Testimonials, Work } from './MarketingSections'
import { CosmicBackground } from './CosmicBackground'

export function MarketingSite() {
  return <div className="site-shell"><CosmicBackground /><a className="skip-link" href="#main-content">Skip to content</a><div className="site-content"><Nav /><main id="main-content" tabIndex={-1}><Hero /><Reveal><WorkflowDiagram /></Reveal><Reveal><RoiCalculator /></Reveal><Reveal><Services /></Reveal><Reveal><Work /></Reveal><Reveal><Pricing /></Reveal><Reveal><Testimonials /></Reveal><Reveal><BlogAndCta /></Reveal></main><Footer /></div></div>
}
