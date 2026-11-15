import { useEffect } from 'react'
import Lenis from 'lenis'
import gsap from 'gsap'
import 'lenis/dist/lenis.css'

export function useLenis() {
  useEffect(() => {
    const reducedMotion = window.matchMedia('(prefers-reduced-motion: reduce)')
    if (reducedMotion.matches) return

    const lenis = new Lenis({
      autoRaf: false,
      smoothWheel: true,
      syncTouch: false,
      wheelMultiplier: 0.8,
      lerp: 0.12,
    })
    let timeout = 0
    const tick = (time: number) => lenis.raf(time * 1000)
    const onScroll = ({ velocity }: { velocity: number }) => {
      if (Math.abs(velocity) > 1.1) {
        document.documentElement.classList.add('is-scrolling-fast')
        window.clearTimeout(timeout)
        timeout = window.setTimeout(() => {
          document.documentElement.classList.remove('is-scrolling-fast')
        }, 140)
      }
    }
    const onMotionChange = (event: MediaQueryListEvent) => {
      if (event.matches) {
        gsap.ticker.remove(tick)
        lenis.stop()
        window.clearTimeout(timeout)
        document.documentElement.classList.remove('is-scrolling-fast')
      } else {
        lenis.start()
        gsap.ticker.add(tick)
      }
    }

    lenis.on('scroll', onScroll)
    gsap.ticker.add(tick)
    reducedMotion.addEventListener('change', onMotionChange)

    return () => {
      window.clearTimeout(timeout)
      document.documentElement.classList.remove('is-scrolling-fast')
      reducedMotion.removeEventListener('change', onMotionChange)
      gsap.ticker.remove(tick)
      lenis.destroy()
    }
  }, [])
}
