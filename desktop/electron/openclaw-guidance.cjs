// Keeps PockPock's guidance in OpenClaw's workspace AGENTS.md current. OpenClaw reads that file at
// the start of every session; PockPock's part sits between two markers and is replaced whenever the
// bundled guidance changes, so improvements reach existing installs (not only first setup). The rest
// of the file belongs to OpenClaw and the user and is never touched.
const fs = require('node:fs')
const os = require('node:os')
const path = require('node:path')

const START = '<!-- pockpock-guidance:start (managed by PockPock Agent; edits here are replaced) -->'
const END = '<!-- pockpock-guidance:end -->'
// The first version was appended without markers; it began and ended with these lines.
const LEGACY_FIRST = '## Using the browser on this PC'
const LEGACY_LAST = 'say what you are about to do.'

/** Returns the AGENTS.md text with PockPock's block set to `guidance`. Pure, for tests. */
function mergeGuidance(existing, guidance) {
  const block = `${START}\n${guidance.trim()}\n${END}`
  let text = existing.replace(/\r\n/g, '\n')
  const start = text.indexOf(START)
  const end = text.indexOf(END)
  if (start !== -1 && end > start) return `${text.slice(0, start)}${block}${text.slice(end + END.length)}`
  const legacy = text.indexOf(LEGACY_FIRST)
  if (legacy !== -1) {
    const tail = text.indexOf(LEGACY_LAST, legacy)
    const cut = tail === -1 ? text.length : text.indexOf('\n', tail) === -1 ? text.length : text.indexOf('\n', tail) + 1
    text = (text.slice(0, legacy) + text.slice(cut)).replace(/\n{3,}$/, '\n')
  }
  return `${text.replace(/\s*$/, '')}${text.trim() ? '\n\n' : ''}${block}\n`
}

/** Writes the bundled guidance into OpenClaw's AGENTS.md. Returns 'updated', 'current' or 'skipped'. */
function syncGuidance(backendRoot, openclawHome = path.join(os.homedir(), '.openclaw')) {
  const source = path.join(backendRoot, 'projects', 'openclaw_bridge', 'workspace-guidance.md')
  const agentsFile = path.join(openclawHome, 'workspace', 'AGENTS.md')
  if (!fs.existsSync(source) || !fs.existsSync(openclawHome)) return 'skipped'
  fs.mkdirSync(path.dirname(agentsFile), { recursive: true })
  const existing = fs.existsSync(agentsFile) ? fs.readFileSync(agentsFile, 'utf8') : ''
  const next = mergeGuidance(existing, fs.readFileSync(source, 'utf8'))
  if (next === existing.replace(/\r\n/g, '\n')) return 'current'
  fs.writeFileSync(agentsFile, next, 'utf8')
  return 'updated'
}

module.exports = { mergeGuidance, syncGuidance, START, END }
