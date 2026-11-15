'use client'

import { useEffect, useRef, useState } from 'react'
import { createBlackHole, type BlackHoleHandle, type BlackHolePalette } from './blackHoleRenderer'

type Props = {
  className?: string
  /** Static image shown if WebGL is unavailable. */
  fallbackSrc?: string
  palette?: BlackHolePalette
}

/**
 * Full-screen, fixed, real-time black hole. Pauses when the tab is hidden, when
 * `<html data-cosmic-paused="true">` is set, and renders a single still frame for
 * users who prefer reduced motion.
 */
export function BlackHoleBackground({ className = 'blackhole-backdrop', fallbackSrc = '/images/black-hole-reference.jpg', palette = 'cosmic' }: Props) {
  const canvasRef = useRef<HTMLCanvasElement>(null)
  const [failed, setFailed] = useState(false)
  const [ready, setReady] = useState(false)

  useEffect(() => {
    const canvas = canvasRef.current
    if (!canvas) return

    const reducedMotion = window.matchMedia('(prefers-reduced-motion: reduce)')
    const isPaused = () => document.documentElement.dataset.cosmicPaused === 'true'
    let handle: BlackHoleHandle | null = null

    const start = () => {
      handle?.destroy()
      try {
        handle = createBlackHole(canvas, { palette, paused: isPaused(), reducedMotion: reducedMotion.matches })
        setReady(true)
      } catch (error) {
        console.warn('Black hole background unavailable, using still image.', error)
        setFailed(true)
      }
    }
    start()

    const pauseObserver = new MutationObserver(() => handle?.setPaused(isPaused()))
    pauseObserver.observe(document.documentElement, { attributes: true, attributeFilter: ['data-cosmic-paused'] })

    const onPointer = (event: PointerEvent) => {
      handle?.setLook((event.clientX / window.innerWidth) * 2 - 1, (event.clientY / window.innerHeight) * 2 - 1)
    }
    window.addEventListener('pointermove', onPointer, { passive: true })
    reducedMotion.addEventListener('change', start)

    return () => {
      pauseObserver.disconnect()
      window.removeEventListener('pointermove', onPointer)
      reducedMotion.removeEventListener('change', start)
      handle?.destroy()
    }
  }, [palette])

  return (
    <div className={className} aria-hidden="true" data-ready={ready} data-failed={failed}>
      {failed
        ? <div className="blackhole-backdrop__fallback" style={{ backgroundImage: `url('${fallbackSrc}')` }} />
        : <canvas ref={canvasRef} className="blackhole-backdrop__canvas" />}
      <div className="blackhole-backdrop__scrim" />
    </div>
  )
}
