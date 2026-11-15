import { useEffect, useRef } from 'react'
import {
  BufferAttribute,
  BufferGeometry,
  OrthographicCamera,
  Points,
  Scene,
  ShaderMaterial,
  Vector2,
  WebGLRenderer,
} from 'three'

const vertexShader = `
  uniform float uTime;
  uniform vec2 uPointer;
  uniform float uMotion;
  varying float vHeight;

  void main() {
    vec3 displaced = position;
    float wave = sin(position.x * 1.05 + uTime * 0.24) * 0.11;
    wave += cos(position.y * 1.32 - uTime * 0.19) * 0.09;
    float distanceToPointer = distance(position.xy, uPointer);
    float influence = exp(-distanceToPointer * 0.52) * uMotion;
    displaced.z += wave + influence * 0.34;
    vHeight = wave + influence;
    vec4 viewPosition = modelViewMatrix * vec4(displaced, 1.0);
    gl_Position = projectionMatrix * viewPosition;
    gl_PointSize = clamp(1.45 + influence * 2.2, 1.0, 4.0);
  }
`

const fragmentShader = `
  varying float vHeight;

  void main() {
    float pointDistance = length(gl_PointCoord - vec2(0.5));
    float pointMask = 1.0 - smoothstep(0.34, 0.5, pointDistance);
    float field = smoothstep(-0.15, 0.25, vHeight);
    vec3 base = vec3(0.55, 0.61, 0.55);
    vec3 accent = vec3(0.74, 0.94, 0.48);
    vec3 color = mix(base, accent, field * 0.68);
    float opacity = (0.32 + field * 0.62) * pointMask;
    gl_FragColor = vec4(color, opacity);
  }
`

function createGeometry() {
  const columns = 112
  const rows = 54
  const positions = new Float32Array(columns * rows * 3)
  let index = 0

  for (let row = 0; row < rows; row += 1) {
    for (let column = 0; column < columns; column += 1) {
      positions[index++] = (column / (columns - 1) - 0.5) * 18
      positions[index++] = (row / (rows - 1) - 0.5) * 6.2
      positions[index++] = 0
    }
  }

  const geometry = new BufferGeometry()
  geometry.setAttribute('position', new BufferAttribute(positions, 3))
  geometry.computeBoundingSphere()
  return geometry
}

export default function HeroField() {
  const host = useRef<HTMLDivElement>(null)

  useEffect(() => {
    const element = host.current
    if (!element) return

    let renderer: WebGLRenderer
    try {
      renderer = new WebGLRenderer({
        alpha: true,
        antialias: false,
        powerPreference: 'high-performance',
      })
    } catch (error) {
      console.error('Unable to initialize the interactive WebGL field:', error)
      return
    }

    const geometry = createGeometry()
    const material = new ShaderMaterial({
      transparent: true,
      depthWrite: false,
      uniforms: {
        uTime: { value: 0 },
        uPointer: { value: new Vector2(30, 30) },
        uMotion: { value: 0 },
      },
      vertexShader,
      fragmentShader,
    })
    const scene = new Scene()
    const camera = new OrthographicCamera(-1, 1, 1, -1, 0.1, 30)
    camera.position.z = 10
    const points = new Points(geometry, material)
    points.frustumCulled = false
    scene.add(points)

    const pointer = material.uniforms.uPointer.value as Vector2
    const pointerTarget = new Vector2(30, 30)
    const reducedMotion = window.matchMedia('(prefers-reduced-motion: reduce)')
    let inView = false
    let raf = 0
    let disposed = false
    let startedAt = 0

    const resize = () => {
      if (!element.clientWidth || !element.clientHeight) return
      const width = element.clientWidth
      const height = element.clientHeight
      const halfHeight = height / 140
      const halfWidth = width / 140
      camera.left = -halfWidth
      camera.right = halfWidth
      camera.top = halfHeight
      camera.bottom = -halfHeight
      camera.updateProjectionMatrix()
      renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2))
      renderer.setSize(width, height, false)
      renderer.render(scene, camera)
    }

    const renderFrame = () => {
      raf = 0
      if (disposed || document.hidden || !inView || reducedMotion.matches) return
      material.uniforms.uTime.value = (performance.now() - startedAt) / 1000
      pointer.lerp(pointerTarget, 0.09)
      renderer.render(scene, camera)
      raf = requestAnimationFrame(renderFrame)
    }

    const syncLoop = () => {
      const shouldAnimate = inView && !document.hidden && !reducedMotion.matches
      element.dataset.rendering = String(shouldAnimate)
      if (shouldAnimate && !raf) {
        startedAt = performance.now()
        raf = requestAnimationFrame(renderFrame)
      } else if (!shouldAnimate && raf) {
        cancelAnimationFrame(raf)
        raf = 0
        renderer.render(scene, camera)
      }
    }

    const movePointer = (event: globalThis.PointerEvent) => {
      const x = (event.offsetX / element.clientWidth - 0.5) * (element.clientWidth / 70)
      const y = (0.5 - event.offsetY / element.clientHeight) * (element.clientHeight / 70)
      pointerTarget.set(x, y)
    }

    const observer = new IntersectionObserver(([entry]) => {
      inView = entry.isIntersecting
      syncLoop()
    })
    const onVisibilityChange = () => syncLoop()
    const onMotionChange = () => {
      material.uniforms.uMotion.value = reducedMotion.matches ? 0 : 1
      syncLoop()
    }

    element.appendChild(renderer.domElement)
    resize()
    observer.observe(element)
    element.addEventListener('pointermove', movePointer, { passive: true })
    document.addEventListener('visibilitychange', onVisibilityChange)
    reducedMotion.addEventListener('change', onMotionChange)

    const resizeObserver = new ResizeObserver(resize)
    resizeObserver.observe(element)
    window.addEventListener('resize', resize, { passive: true })
    onMotionChange()

    return () => {
      disposed = true
      if (raf) cancelAnimationFrame(raf)
      resizeObserver.disconnect()
      observer.disconnect()
      window.removeEventListener('resize', resize)
      document.removeEventListener('visibilitychange', onVisibilityChange)
      reducedMotion.removeEventListener('change', onMotionChange)
      element.removeEventListener('pointermove', movePointer)
      geometry.dispose()
      material.dispose()
      renderer.dispose()
      renderer.domElement.remove()
    }
  }, [])

  return <div className="field-host" ref={host} />
}
