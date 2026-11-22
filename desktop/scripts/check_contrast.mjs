// Checks WCAG 2.2 AA contrast for every theme in src/styles.css. Usage: npm run check:contrast
// Reads the :root block (PockPock Dark) and each :root[data-theme="…"] block, resolves var()
// references, blends translucent colours over the surface they sit on, and checks the pairs below.
// Exits with 1 if any pair fails. Add pairs here when a component combines tokens in a new way.
import fs from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

const file = process.argv.slice(2).find((arg) => arg.endsWith('.css')) || path.join(path.dirname(fileURLToPath(import.meta.url)), '..', 'src', 'styles.css')
const css = fs.readFileSync(file, 'utf8')

/** Token blocks by theme id: 'pockpock-dark' is :root; others override it. */
function themes() {
  const blocks = {}
  for (const match of css.matchAll(/:root(?:\[data-theme="([\w-]+)"\])?\s*\{([^}]*)\}/g)) {
    const id = match[1] || 'pockpock-dark'
    const vars = {}
    for (const decl of match[2].replace(/\/\*[\s\S]*?\*\//g, '').matchAll(/--([\w-]+)\s*:\s*([^;]+);/g)) vars[decl[1]] = decl[2].trim()
    blocks[id] = vars
  }
  const base = blocks['pockpock-dark']
  return Object.fromEntries(Object.entries(blocks).map(([id, vars]) => [id, id === 'pockpock-dark' ? vars : { ...base, ...vars }]))
}

function parse(value, vars, depth = 0) {
  if (depth > 10) throw new Error(`var() loop at ${value}`)
  const ref = /^var\(--([\w-]+)\)$/.exec(value)
  if (ref) return parse(vars[ref[1]], vars, depth + 1)
  const hex = /^#([0-9a-f]{3}|[0-9a-f]{6})$/i.exec(value)
  if (hex) {
    const h = hex[1].length === 3 ? [...hex[1]].map((c) => c + c).join('') : hex[1]
    return { r: parseInt(h.slice(0, 2), 16), g: parseInt(h.slice(2, 4), 16), b: parseInt(h.slice(4, 6), 16), a: 1 }
  }
  const rgba = /^rgba?\(\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)\s*(?:,\s*([\d.]+))?\s*\)$/.exec(value)
  if (rgba) return { r: +rgba[1], g: +rgba[2], b: +rgba[3], a: rgba[4] === undefined ? 1 : +rgba[4] }
  throw new Error(`Cannot read colour "${value}"`)
}

/** "token" or "token@surface" (a translucent token blended over a surface). */
function colour(spec, vars) {
  const [top, under] = spec.split('@')
  const c = parse(`var(--${top})`, vars)
  if (c.a >= 1 || !under) return c
  const b = colour(under, vars)
  return { r: c.r * c.a + b.r * (1 - c.a), g: c.g * c.a + b.g * (1 - c.a), b: c.b * c.a + b.b * (1 - c.a), a: 1 }
}

const channel = (v) => { const s = v / 255; return s <= 0.04045 ? s / 12.92 : ((s + 0.055) / 1.055) ** 2.4 }
const luminance = ({ r, g, b }) => 0.2126 * channel(r) + 0.7152 * channel(g) + 0.0722 * channel(b)
export function ratio(a, b) { const [x, y] = [luminance(a), luminance(b)].sort((p, q) => q - p); return (x + 0.05) / (y + 0.05) }

const SURFACES = ['bg', 'bg-side', 'bg-panel', 'bg-raise', 'bg-hover', 'bg-active', 'bg-popover']
const TEXT = 4.5
const UI = 3
export const PAIRS = [
  // Body text on every surface
  ...['text', 'text-2', 'text-3'].flatMap((fg) => SURFACES.map((bg) => [fg, bg, TEXT, 'text'])),
  ['text', 'accent-bg@bg-popover', TEXT, 'selected option'],
  ['text', 'accent-bg@bg-side', TEXT, 'selected chat'],
  ['text-2', 'off-bg@bg-panel', TEXT, 'neutral badge'],
  // Accent as text (links, selected labels, chips)
  ...['bg', 'bg-panel', 'bg-raise', 'bg-popover'].map((bg) => ['accent-strong', bg, TEXT, 'accent text']),
  ['accent-strong', 'accent-bg@bg-popover', TEXT, 'accent text on selected option'],
  // Text on filled accent controls (primary buttons, send, update button)
  ['on-accent', 'accent-fill', TEXT, 'primary button'],
  ['on-accent', 'accent-fill-hover', TEXT, 'primary button hover'],
  // Code blocks, logs, diffs, terminal
  ['code-text', 'bg-code', TEXT, 'code and diffs'],
  ['log-text', 'bg-code', TEXT, 'logs'],
  ['term-fg', 'term-bg', TEXT, 'terminal'],
  ['term-fg', 'term-selection', TEXT, 'terminal selection'],
  // Status text on tinted backgrounds
  ['ok-text', 'ok-bg@bg-panel', TEXT, 'ok badge'],
  ['warn-text', 'warn-bg@bg', TEXT, 'warning notice'],
  ['warn-text', 'warn-bg-strong@bg-panel', TEXT, 'warning badge'],
  ['err-text', 'err-bg@bg', TEXT, 'error banner'],
  ['err-text', 'bg-panel', TEXT, 'error text in cards'],
  ['bg', 'text', TEXT, 'stop button'],
  ['bg', 'stop-hover', TEXT, 'stop button hover'],
  // Status bar text
  ['text-3', 'bg-side', TEXT, 'status bar'],
  // Focus ring on every surface (non-text, 3:1)
  ...SURFACES.map((bg) => ['focus', bg, UI, 'focus ring']),
  // Control boundaries and indicators
  ...['bg', 'bg-panel', 'bg-raise'].map((bg) => ['control-border', bg, UI, 'input and switch border']),
  ['switch-knob', 'switch-bg', UI, 'switch knob (off)'],
  ['on-accent', 'accent', UI, 'switch knob (on)'],
  ['accent', 'bg-panel', UI, 'switch track (on)'],
  ...['ok', 'warn', 'err', 'info', 'dot-off'].flatMap((dot) => [[dot, 'bg-side', UI, 'status dot'], [dot, 'bg', UI, 'status dot']]),
  ['tree-folder', 'bg-side', UI, 'folder icon'],
  ['accent-border@bg', 'bg', UI, 'waiting card border'],
  // Agent Studio shell: run bar, rail, segmented engine switch, command palette, inspector.
  ['ok-text', 'bg-panel', TEXT, 'run bar: finished phase'],
  ['ok-text', 'ok-bg@bg-panel', TEXT, 'run bar: finished phase marker'],
  ['warn-text', 'warn-bg@bg-panel', TEXT, 'run bar: slow note'],
  ['err-text', 'err-bg@bg-panel', TEXT, 'run bar: failed note'],
  ['control-border', 'bg-panel', UI, 'run bar: phase marker ring'],
  ['accent-strong', 'bg-active', UI, 'rail: active icon'],
  ['accent-strong', 'bg-side', UI, 'rail: needs-you badge'],
  ['warn', 'bg-side', UI, 'rail: services badge'],
  ['err', 'bg-panel', UI, 'run bar: failed track'],
  ['accent-strong', 'border@bg-panel', UI, 'run bar: working track on its rail'],
  ['text', 'accent-bg@bg-popover', TEXT, 'palette: selected result'],
  ['accent-strong', 'bg-active', TEXT, 'Workshop: active page icon and inspector meter'],
  // Agent Studio thread: plan card, approvals, failed card, menus.
  ['accent-strong', 'accent-bg@bg-panel', TEXT, 'badge: waiting for you'],
  ['ok-text', 'ok-bg@bg-panel', TEXT, 'badge: pre-check passed'],
  ['warn-text', 'warn-bg-strong@bg-panel', TEXT, 'badge: pre-check warning'],
  ['text', 'warn-bg@bg-panel', TEXT, 'plan: question text'],
  ['warn-text', 'warn-bg@bg-panel', TEXT, 'plan: question heading and warnings'],
  ['text-2', 'warn-bg@bg-panel', TEXT, 'plan: question hint'],
  ['err-text', 'err-bg@bg-panel', TEXT, 'failed card heading'],
  ['text-2', 'err-bg@bg-panel', TEXT, 'failed card hint'],
  ['text-2', 'off-bg@bg-popover', TEXT, 'menu: status badge'],
  ['warn-text', 'warn-bg-strong@bg-popover', TEXT, 'menu: risky badge'],
  ['err', 'err-bg@bg-panel', UI, 'failed card icon'],
  // Agent Studio settings, setup and toasts.
  ['text', 'accent-bg@bg-panel', TEXT, 'settings: update ready row'],
  ['text-2', 'accent-bg@bg-panel', TEXT, 'settings: update ready row detail'],
  ['err', 'bg-popover', UI, 'toast: error icon'],
  ['accent-strong', 'bg-popover', UI, 'toast: update icon'],
  ['accent-border@bg', 'bg-panel', UI, 'theme picker: selected card border'],
  // Plan-step progress: the run bar's "Step 3 of 5" and the plan card's current step.
  ['accent-strong', 'accent-bg@bg-panel', TEXT, 'run bar: plan step chip'],
  ['accent-strong', 'accent-bg@bg-panel', UI, 'plan: current step marker'],
  // Watched pages (Research): paused banner.
  ['warn-text', 'warn-bg@bg', TEXT, 'research: checks paused banner'],
  ['warn', 'bg', UI, 'research: checks paused banner border'],
]

const all = themes()
let failures = 0
const report = {}
for (const [id, vars] of Object.entries(all)) {
  report[id] = []
  for (const [fg, bg, min, what] of PAIRS) {
    const value = ratio(colour(fg, vars), colour(bg, vars))
    const ok = value >= min
    if (!ok) failures += 1
    report[id].push({ fg, bg, min, what, value: Math.round(value * 100) / 100, ok })
  }
}

if (process.argv.includes('--json')) {
  console.log(JSON.stringify(report, null, 2))
} else {
  for (const [id, rows] of Object.entries(report)) {
    const failed = rows.filter((row) => !row.ok)
    const lowest = (kind) => rows.filter((row) => row.min === kind).reduce((low, row) => (row.value < low.value ? row : low))
    const t = lowest(TEXT)
    const u = lowest(UI)
    console.log(`${id}: ${rows.length - failed.length}/${rows.length} pass · lowest text ${t.value}:1 (${t.fg} on ${t.bg}) · lowest non-text ${u.value}:1 (${u.fg} on ${u.bg})`)
    for (const row of failed) console.log(`  FAIL ${row.value}:1 < ${row.min}:1  ${row.fg} on ${row.bg} (${row.what})`)
  }
}
process.exitCode = failures ? 1 : 0
