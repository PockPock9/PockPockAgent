'use client'

import { Pause, Play } from 'lucide-react'
import { useState } from 'react'

export function CosmicMotionToggle({ compact = false }: { compact?: boolean }) {
  const [paused, setPaused] = useState(false)

  function toggleMotion() {
    const nextPaused = !paused
    document.documentElement.dataset.cosmicPaused = String(nextPaused)
    setPaused(nextPaused)
  }

  return (
    <button className={`cosmic-motion-toggle${compact ? ' cosmic-motion-toggle--icon' : ''}`} type="button" aria-label={paused ? 'Resume space background animation' : 'Pause space background animation'} aria-pressed={paused} onClick={toggleMotion}>
      {paused ? <Play size={13} aria-hidden="true" /> : <Pause size={13} aria-hidden="true" />}
      <span>{paused ? 'Resume motion' : 'Pause motion'}</span>
    </button>
  )
}
