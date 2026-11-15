/**
 * Real-time Schwarzschild black hole renderer (raw WebGL, no dependencies).
 *
 * Every pixel traces a light ray backwards from the camera and bends it with the
 * null-geodesic acceleration a = -1.5 * h^2 * r / |r|^5 (units of Schwarzschild
 * radius). The thin accretion disk is hit wherever the bent ray crosses the disk
 * plane, which produces the lensed "halo" over and under the shadow, the photon
 * ring, and the gravitationally distorted star field without any faked layers.
 * The disk turns with Keplerian speed (inner gas faster) and is Doppler beamed.
 *
 * Framework agnostic: shared by the Vite app and the Next.js marketing site.
 */

const vertexSource = `
attribute vec2 aPosition;
varying vec2 vUv;
void main() {
  vUv = aPosition * 0.5 + 0.5;
  gl_Position = vec4(aPosition, 0.0, 1.0);
}
`

const fragmentSource = `
precision highp float;

varying vec2 vUv;
uniform vec2 uResolution;
uniform float uTime;
uniform vec2 uLook;
uniform float uSteps;
uniform vec3 uRimColor;
uniform vec3 uRecedeTint;
uniform vec3 uNebulaColor;

#define MAX_STEPS 260
const float DISK_IN = 2.9;
const float DISK_OUT = 15.0;
const float PI = 3.14159265;

float hash13(vec3 p) {
  p = fract(p * 0.1031);
  p += dot(p, p.zyx + 31.32);
  return fract((p.x + p.y) * p.z);
}

float noise3(vec3 p) {
  vec3 i = floor(p);
  vec3 f = fract(p);
  f = f * f * (3.0 - 2.0 * f);
  float n000 = hash13(i);
  float n100 = hash13(i + vec3(1.0, 0.0, 0.0));
  float n010 = hash13(i + vec3(0.0, 1.0, 0.0));
  float n110 = hash13(i + vec3(1.0, 1.0, 0.0));
  float n001 = hash13(i + vec3(0.0, 0.0, 1.0));
  float n101 = hash13(i + vec3(1.0, 0.0, 1.0));
  float n011 = hash13(i + vec3(0.0, 1.0, 1.0));
  float n111 = hash13(i + vec3(1.0, 1.0, 1.0));
  return mix(
    mix(mix(n000, n100, f.x), mix(n010, n110, f.x), f.y),
    mix(mix(n001, n101, f.x), mix(n011, n111, f.x), f.y),
    f.z
  );
}

float fbm(vec3 p) {
  float sum = 0.0;
  float amp = 0.5;
  for (int i = 0; i < 5; i++) {
    sum += amp * noise3(p);
    p = p * 2.03 + vec3(1.7, 9.2, 3.1);
    amp *= 0.5;
  }
  return sum;
}

// Streaky gas pattern: high frequency across radius, long along the orbit.
float diskPattern(float r, float a, float seed) {
  vec3 q = vec3(r * 3.0, cos(a) * 2.2, sin(a) * 2.2) + seed;
  // Domain warp breaks the perfectly concentric rings into turbulent filaments.
  q.x += (fbm(q * vec3(0.6, 1.4, 1.4) + 5.0) - 0.5) * 2.4;
  float coarse = fbm(q);
  vec3 q2 = vec3(r * 10.0 + coarse * 4.0, cos(a) * 5.0, sin(a) * 5.0) + seed * 1.7;
  float fine = noise3(q2) * 0.6 + noise3(q2 * 2.1) * 0.4;
  return coarse * 0.7 + fine * 0.45;
}

vec4 sampleDisk(vec3 p, vec3 dir) {
  float r = length(p.xz);
  if (r < DISK_IN || r > DISK_OUT) return vec4(0.0);

  float phi = atan(p.z, p.x);
  float omega = 2.2 * pow(r, -1.5);

  // Two phase-shifted layers cross-faded so differential rotation never winds up forever.
  float period = 36.0;
  float t1 = mod(uTime, period);
  float t2 = mod(uTime + period * 0.5, period);
  float w1 = 1.0 - abs(2.0 * t1 / period - 1.0);
  float pattern = diskPattern(r, phi - omega * t1, 0.0) * w1
                + diskPattern(r, phi - omega * t2, 17.0) * (1.0 - w1);

  float x = (r - DISK_IN) / (DISK_OUT - DISK_IN);
  float inner = smoothstep(0.0, 0.05, x);
  float outer = 1.0 - smoothstep(0.55, 1.0, x);
  float density = inner * outer * smoothstep(0.32, 0.95, pattern);
  density *= 0.55 + 0.9 * pow(1.0 - x, 2.0);

  // Temperature palette: white-blue core, cobalt middle, violet/magenta rim.
  vec3 hot = vec3(0.9, 0.95, 1.0);
  vec3 mid = vec3(0.32, 0.5, 1.0);
  vec3 cool = uRimColor;
  vec3 col = mix(hot, mid, smoothstep(0.0, 0.28, x));
  col = mix(col, cool, smoothstep(0.3, 0.85, x));

  // Relativistic Doppler beaming: one side brighter and bluer, the other dimmer and redder.
  vec3 orbit = normalize(vec3(-p.z, 0.0, p.x));
  float beta = clamp(sqrt(0.5 / max(r - 1.0, 0.2)), 0.0, 0.7);
  float gamma = 1.0 / sqrt(1.0 - beta * beta);
  float g = 1.0 / (gamma * (1.0 + beta * dot(orbit, dir)));
  float beaming = pow(g, 3.6);
  col = mix(col * uRecedeTint, col * vec3(0.85, 1.0, 1.25), smoothstep(0.75, 1.35, g));

  // Gravitational redshift dims the innermost gas.
  float redshift = sqrt(max(1.0 - 1.0 / r, 0.0));

  float emission = 2.6 * pow(DISK_IN / r, 1.35) * beaming * redshift;
  float alpha = clamp(density * 0.95, 0.0, 0.9);
  return vec4(col * emission * density, alpha);
}

vec3 sky(vec3 d) {
  vec3 col = vec3(0.0);

  // Faint violet and blue nebula wisps.
  float n = fbm(d * 2.6 + vec3(0.0, 0.0, uTime * 0.004));
  float wisps = fbm(d * vec3(5.0, 11.0, 5.0) + 4.0);
  col += uNebulaColor * pow(n, 3.2) * 0.5;
  col += vec3(0.05, 0.09, 0.22) * pow(wisps, 4.0) * 0.6;

  // Two layers of hashed stars on the (lensed) ray direction.
  for (int layer = 0; layer < 2; layer++) {
    float scale = layer == 0 ? 70.0 : 150.0;
    vec3 p = d * scale;
    vec3 id = floor(p);
    vec3 f = fract(p) - 0.5;
    float h = hash13(id + float(layer) * 13.1);
    float threshold = layer == 0 ? 0.965 : 0.94;
    if (h > threshold) {
      vec3 offset = vec3(hash13(id + 1.3), hash13(id + 2.7), hash13(id + 5.1)) - 0.5;
      float dist = length(f - offset * 0.6);
      float brightness = pow((h - threshold) / (1.0 - threshold), 2.2);
      float twinkle = 0.75 + 0.25 * sin(uTime * (1.0 + h * 3.0) + h * 40.0);
      vec3 tint = mix(vec3(0.7, 0.8, 1.0), vec3(1.0, 0.86, 0.78), hash13(id + 9.4));
      col += tint * brightness * twinkle * exp(-dist * dist * (layer == 0 ? 90.0 : 160.0)) * 2.2;
    }
  }
  return col;
}

mat3 lookAt(vec3 eye, vec3 target, float roll) {
  vec3 fwd = normalize(target - eye);
  vec3 rollUp = vec3(sin(roll), cos(roll), 0.0);
  vec3 right = normalize(cross(fwd, rollUp));
  vec3 up = cross(right, fwd);
  return mat3(right, up, fwd);
}

void main() {
  vec2 frag = vUv * uResolution;
  vec2 uv = (frag - 0.5 * uResolution) / uResolution.y;
  float aspect = uResolution.x / uResolution.y;

  // Frame the hole slightly below centre so hero copy sits over darker sky.
  uv.y -= 0.05;

  float azimuth = -0.35 + uTime * 0.006 + uLook.x * 0.05;
  float elevation = -0.05 + uLook.y * 0.02 + sin(uTime * 0.05) * 0.008;
  float distance = 26.0;
  vec3 eye = distance * vec3(cos(elevation) * sin(azimuth), sin(elevation), -cos(elevation) * cos(azimuth));
  mat3 cam = lookAt(eye, vec3(0.0), -0.12);

  // Pull back on tall/narrow screens so the whole silhouette stays in frame.
  float focal = mix(0.95, 2.05, smoothstep(0.45, 1.3, aspect));
  vec3 dir = normalize(cam * vec3(uv, focal));

  vec3 pos = eye;
  vec3 vel = dir;
  vec3 h = cross(pos, vel);
  float h2 = dot(h, h);

  vec3 color = vec3(0.0);
  float alpha = 0.0;
  float glow = 0.0;
  bool captured = false;

  for (int i = 0; i < MAX_STEPS; i++) {
    if (float(i) >= uSteps) break;
    float r2 = dot(pos, pos);
    float r = sqrt(r2);
    if (r < 1.0) { captured = true; break; }
    if (r > 60.0 && dot(pos, vel) > 0.0) break;

    float dt = clamp(0.065 * r, 0.025, 4.0);
    // Smaller steps when skimming the disk plane keep crossings crisp.
    dt = min(dt, max(abs(pos.y) * 0.6, 0.05) + 0.04 * r);
    vec3 prev = pos;
    vel += -1.5 * h2 * pos / (r2 * r2 * r) * dt;
    pos += vel * dt;

    // Soft haze hugging the disk and a faint photon-sphere glow (cheap stand-in for bloom).
    float rr = length(pos.xz);
    float haze = smoothstep(DISK_IN - 0.6, DISK_IN + 0.8, rr) * exp(-(rr - DISK_IN) * 0.22);
    glow += (1.0 - alpha) * haze * exp(-abs(pos.y) * 2.2) * dt * 0.018;
    glow += (1.0 - alpha) * exp(-abs(r - 1.5) * 9.0) * dt * 0.01;

    if (prev.y * pos.y < 0.0) {
      float f = prev.y / (prev.y - pos.y);
      vec3 hit = mix(prev, pos, f);
      vec4 disk = sampleDisk(hit, normalize(vel));
      color += (1.0 - alpha) * disk.rgb;
      alpha += (1.0 - alpha) * disk.a;
      if (alpha > 0.985) break;
    }
  }

  if (!captured) {
    color += (1.0 - alpha) * sky(normalize(vel));
  }
  color += glow * vec3(0.45, 0.55, 1.0);

  // Filmic exposure, gentle vignette, and dithering to avoid banding.
  color = 1.0 - exp(-color * 1.2);
  color = pow(color, vec3(0.92));
  float vignette = smoothstep(1.35, 0.35, length(uv * vec2(0.85, 1.0)));
  color *= mix(0.55, 1.0, vignette);
  color += (hash13(vec3(frag, fract(uTime))) - 0.5) / 255.0;

  gl_FragColor = vec4(color, 1.0);
}
`

export type BlackHolePalette = 'cosmic' | 'blue'

const palettes: Record<BlackHolePalette, { rim: [number, number, number]; recede: [number, number, number]; nebula: [number, number, number] }> = {
  // Blue-white core fading to violet/magenta edges, as in the reference image.
  cosmic: { rim: [0.58, 0.26, 0.62], recede: [1.15, 0.7, 0.92], nebula: [0.26, 0.07, 0.24] },
  // All-blue variant: icy core, cobalt body, deep navy rim.
  blue: { rim: [0.12, 0.3, 0.72], recede: [0.72, 0.85, 1.05], nebula: [0.05, 0.12, 0.3] },
}

export type BlackHoleOptions = {
  /** Disk and nebula colour scheme. Defaults to 'cosmic'. */
  palette?: BlackHolePalette
  /** Start paused (renders one still frame). */
  paused?: boolean
  /** Render one still frame and never animate. */
  reducedMotion?: boolean
  /** Fraction of CSS pixels to render at; adapted automatically at runtime. */
  initialScale?: number
}

export type BlackHoleHandle = {
  setPaused: (paused: boolean) => void
  setLook: (x: number, y: number) => void
  destroy: () => void
}

function compile(gl: WebGLRenderingContext, type: number, source: string) {
  const shader = gl.createShader(type)
  if (!shader) throw new Error('Unable to create shader')
  gl.shaderSource(shader, source)
  gl.compileShader(shader)
  if (!gl.getShaderParameter(shader, gl.COMPILE_STATUS)) {
    const log = gl.getShaderInfoLog(shader)
    gl.deleteShader(shader)
    throw new Error(`Black hole shader failed to compile: ${log ?? 'unknown error'}`)
  }
  return shader
}

/** Starts the renderer on a canvas. Throws if WebGL is unavailable so callers can fall back. */
export function createBlackHole(canvas: HTMLCanvasElement, options: BlackHoleOptions = {}): BlackHoleHandle {
  const gl = canvas.getContext('webgl', { antialias: false, alpha: false, depth: false, stencil: false, powerPreference: 'high-performance', preserveDrawingBuffer: false })
  if (!gl) throw new Error('WebGL is not available')

  const program = gl.createProgram()
  if (!program) throw new Error('Unable to create WebGL program')
  const vertex = compile(gl, gl.VERTEX_SHADER, vertexSource)
  const fragment = compile(gl, gl.FRAGMENT_SHADER, fragmentSource)
  gl.attachShader(program, vertex)
  gl.attachShader(program, fragment)
  gl.linkProgram(program)
  if (!gl.getProgramParameter(program, gl.LINK_STATUS)) throw new Error(`Black hole program failed to link: ${gl.getProgramInfoLog(program) ?? ''}`)
  gl.useProgram(program)

  const buffer = gl.createBuffer()
  gl.bindBuffer(gl.ARRAY_BUFFER, buffer)
  gl.bufferData(gl.ARRAY_BUFFER, new Float32Array([-1, -1, 3, -1, -1, 3]), gl.STATIC_DRAW)
  const position = gl.getAttribLocation(program, 'aPosition')
  gl.enableVertexAttribArray(position)
  gl.vertexAttribPointer(position, 2, gl.FLOAT, false, 0, 0)

  const uResolution = gl.getUniformLocation(program, 'uResolution')
  const uTime = gl.getUniformLocation(program, 'uTime')
  const uLook = gl.getUniformLocation(program, 'uLook')
  const uSteps = gl.getUniformLocation(program, 'uSteps')
  const colors = palettes[options.palette ?? 'cosmic']
  gl.uniform3fv(gl.getUniformLocation(program, 'uRimColor'), colors.rim)
  gl.uniform3fv(gl.getUniformLocation(program, 'uRecedeTint'), colors.recede)
  gl.uniform3fv(gl.getUniformLocation(program, 'uNebulaColor'), colors.nebula)

  let scale = options.initialScale ?? 0.6
  let steps = 220
  let paused = Boolean(options.paused)
  const still = Boolean(options.reducedMotion)
  let raf = 0
  let destroyed = false
  let simTime = 18 // start mid-cycle so the first frame already looks settled
  let lastNow = 0
  let frameAverage = 16
  let framesSinceAdjust = 0
  const look = { x: 0, y: 0, tx: 0, ty: 0 }

  const resize = () => {
    const dpr = Math.min(window.devicePixelRatio || 1, 2)
    const width = Math.max(1, Math.round(canvas.clientWidth * dpr * scale))
    const height = Math.max(1, Math.round(canvas.clientHeight * dpr * scale))
    if (canvas.width !== width || canvas.height !== height) {
      canvas.width = width
      canvas.height = height
    }
    gl.viewport(0, 0, width, height)
  }

  const draw = () => {
    gl.uniform2f(uResolution, canvas.width, canvas.height)
    gl.uniform1f(uTime, simTime)
    gl.uniform2f(uLook, look.x, look.y)
    gl.uniform1f(uSteps, steps)
    gl.drawArrays(gl.TRIANGLES, 0, 3)
  }

  // Keep frame time near 60fps budget by trading resolution first, then ray steps.
  const adapt = (frameMs: number) => {
    frameAverage = frameAverage * 0.9 + frameMs * 0.1
    framesSinceAdjust += 1
    if (framesSinceAdjust < 45) return
    framesSinceAdjust = 0
    if (frameAverage > 24) {
      if (scale > 0.34) scale = Math.max(0.34, scale - 0.08)
      else steps = Math.max(140, steps - 30)
      resize()
    } else if (frameAverage < 14.5) {
      if (steps < 220) steps = Math.min(220, steps + 30)
      else if (scale < 0.85) scale = Math.min(0.85, scale + 0.05)
      resize()
    }
  }

  const frame = (now: number) => {
    raf = 0
    if (destroyed) return
    const delta = lastNow ? Math.min(now - lastNow, 100) : 16
    lastNow = now
    simTime += delta / 1000
    look.x += (look.tx - look.x) * 0.03
    look.y += (look.ty - look.y) * 0.03
    draw()
    adapt(delta)
    schedule()
  }

  const shouldRun = () => !destroyed && !paused && !still && !document.hidden

  function schedule() {
    if (shouldRun() && !raf) raf = requestAnimationFrame(frame)
  }

  const sync = () => {
    if (shouldRun()) {
      lastNow = 0
      schedule()
    } else if (raf) {
      cancelAnimationFrame(raf)
      raf = 0
    }
  }

  const resizeObserver = new ResizeObserver(() => {
    resize()
    if (!shouldRun()) draw()
  })
  resizeObserver.observe(canvas)
  document.addEventListener('visibilitychange', sync)

  const onContextLost = (event: Event) => {
    event.preventDefault()
    if (raf) cancelAnimationFrame(raf)
    raf = 0
  }
  canvas.addEventListener('webglcontextlost', onContextLost)

  resize()
  draw()
  sync()

  return {
    setPaused(next) {
      paused = next
      sync()
    },
    setLook(x, y) {
      look.tx = Math.max(-1, Math.min(1, x))
      look.ty = Math.max(-1, Math.min(1, y))
    },
    destroy() {
      destroyed = true
      if (raf) cancelAnimationFrame(raf)
      resizeObserver.disconnect()
      document.removeEventListener('visibilitychange', sync)
      canvas.removeEventListener('webglcontextlost', onContextLost)
      gl.deleteBuffer(buffer)
      gl.deleteProgram(program)
      gl.deleteShader(vertex)
      gl.deleteShader(fragment)
    },
  }
}
