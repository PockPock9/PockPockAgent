// Problem reports: a user marks one assistant reply as hung, failed or wrong and describes it. The
// report keeps that exchange (prompt, reply, steps, approvals, timing) so the Maintenance Manager can
// reproduce and fix it later. Reports stay on this PC, one JSON file each in <userData>/reports.
// Personal details are redacted before anything is stored, and the user sees the redacted capture
// before saving. Attachment contents are never captured, only their names.
const crypto = require('node:crypto')
const fs = require('node:fs')
const os = require('node:os')
const path = require('node:path')

const CATEGORIES = ['hang', 'failed', 'wrong', 'other']
const STATUSES = ['open', 'in-progress', 'fixed', 'wont-fix']
const MAX_REPORTS = 200
const MAX_DESCRIPTION = 4000
const MAX_TEXT = 20000 // per captured string
const MAX_STEPS = 120
const ID = /^r-[a-z0-9]+-[a-f0-9]{8}$/

function escapeRegExp(text) { return text.replace(/[.*+?^${}()|[\]\\]/g, '\\$&') }

/** Who to hide: the user's home folder (in any slash style) and user name. */
function redactionContext() {
  return { home: os.homedir(), user: os.userInfo().username }
}

const SECRET_PATTERNS = [
  ['token', /\b(?:gh[pousr]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,}|sk-[A-Za-z0-9_-]{20,}|xox[abprs]-[A-Za-z0-9-]{10,}|AKIA[0-9A-Z]{16})\b/g],
  ['token', /\b(Bearer|token|apikey|api_key|password|secret)(\s*[:=]\s*|\s+)["']?[^\s"',;]{8,}/gi],
  ['email', /\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b/g],
  // Long opaque strings (keys, session tokens). Hashes in a report are rarely useful to a fixer.
  ['token', /\b(?=[A-Za-z0-9_-]*\d)(?=[A-Za-z0-9_-]*[A-Za-z])[A-Za-z0-9_-]{40,}\b/g],
]

/** Redacts one string. Returns { text, found: { path, user, email, token } } with counts. */
function redactText(text, context = redactionContext()) {
  const found = { path: 0, user: 0, email: 0, token: 0 }
  if (typeof text !== 'string' || !text) return { text: typeof text === 'string' ? text : '', found }
  let out = text
  const count = (kind, pattern, replacement) => {
    out = out.replace(pattern, (...match) => { found[kind] += 1; return typeof replacement === 'function' ? replacement(...match) : replacement })
  }
  if (context.home && context.home.length > 3) {
    const variants = new Set([context.home, context.home.replace(/\\/g, '/'), context.home.replace(/\//g, '\\')])
    for (const home of variants) count('path', new RegExp(escapeRegExp(home), 'gi'), '~')
  }
  for (const [kind, pattern] of SECRET_PATTERNS) {
    count(kind, pattern, kind === 'email' ? '<email>' : (whole, label, separator) => (label && separator !== undefined && /^[A-Za-z_]+$/.test(label) ? `${label}${separator}<secret>` : '<secret>'))
  }
  if (context.user && context.user.length >= 3) count('user', new RegExp(`\\b${escapeRegExp(context.user)}\\b`, 'gi'), '<user>')
  return { text: out, found }
}

const cut = (value, limit = MAX_TEXT) => (typeof value === 'string' ? (value.length > limit ? `${value.slice(0, limit)}…` : value) : '')
const num = (value) => (typeof value === 'number' && Number.isFinite(value) ? Math.round(value) : undefined)

/** Keeps only the known capture fields, bounded in size. Unknown fields are dropped. */
function sanitizeCapture(raw) {
  const c = raw && typeof raw === 'object' ? raw : {}
  const list = (value, max) => (Array.isArray(value) ? value.slice(0, max) : [])
  return {
    appVersion: cut(c.appVersion, 40),
    platform: cut(c.platform, 40),
    engine: cut(c.engine, 40),
    model: cut(c.model, 200),
    chatTitle: cut(c.chatTitle, 200),
    createdAt: num(c.createdAt),
    userMessage: cut(c.userMessage),
    attachments: list(c.attachments, 20).map((name) => cut(name, 200)),
    reply: cut(c.reply),
    status: cut(c.status, 40),
    notice: cut(c.notice, 2000),
    plan: c.plan && typeof c.plan === 'object' ? { goal: cut(c.plan.goal, 2000), steps: list(c.plan.steps, 40).map((step) => cut(step, 1000)), status: cut(c.plan.status, 40) } : undefined,
    steps: list(c.steps, MAX_STEPS).map((step) => ({ label: cut(step?.label, 500), status: cut(step?.status, 40), detail: cut(step?.detail, 2000), ms: num(step?.ms) })),
    approvals: list(c.approvals, 60).map((item) => ({ title: cut(item?.title, 500), description: cut(item?.description, 2000), status: cut(item?.status, 40) })),
    timing: list(c.timing, 10).map((phase) => ({ label: cut(phase?.label, 40), ms: num(phase?.ms) })),
  }
}

/** Sanitizes and redacts a capture. Returns { capture, redactions } where redactions counts what was hidden. */
function prepareCapture(raw, context = redactionContext()) {
  const totals = { path: 0, user: 0, email: 0, token: 0 }
  const walk = (value) => {
    if (typeof value === 'string') {
      const { text, found } = redactText(value, context)
      for (const key of Object.keys(totals)) totals[key] += found[key]
      return text
    }
    if (Array.isArray(value)) return value.map(walk)
    if (value && typeof value === 'object') return Object.fromEntries(Object.entries(value).map(([key, inner]) => [key, walk(inner)]))
    return value
  }
  return { capture: walk(sanitizeCapture(raw)), redactions: totals }
}

class ReportStore {
  constructor(dir) { this.dir = dir }

  file(id) {
    if (typeof id !== 'string' || !ID.test(id)) throw new Error('Unknown report.')
    return path.join(this.dir, `${id}.json`)
  }

  read(id) {
    try { return JSON.parse(fs.readFileSync(this.file(id), 'utf8')) } catch (error) { if (error.message === 'Unknown report.') throw error; return null }
  }

  write(report) {
    fs.mkdirSync(this.dir, { recursive: true })
    const target = this.file(report.id)
    fs.writeFileSync(`${target}.tmp`, JSON.stringify(report, null, 2), 'utf8')
    fs.renameSync(`${target}.tmp`, target)
    return report
  }

  /** Newest first, without the bulky capture. */
  list() {
    let names = []
    try { names = fs.readdirSync(this.dir).filter((name) => name.endsWith('.json')) } catch { return [] }
    return names
      .map((name) => this.read(name.slice(0, -5)))
      .filter(Boolean)
      .sort((a, b) => b.createdAt - a.createdAt)
      .map(({ capture, ...summary }) => ({ ...summary, engine: capture?.engine || '', chatTitle: capture?.chatTitle || '' }))
  }

  get(id) {
    const report = this.read(id)
    if (!report) throw new Error('Unknown report.')
    return report
  }

  create({ category, description, capture }, context = redactionContext()) {
    if (!CATEGORIES.includes(category)) throw new Error('Choose what went wrong.')
    // A report without a description gives the Maintenance Manager nothing to work from (issue #77).
    if (typeof description !== 'string' || !description.trim()) throw new Error('Describe what happened.')
    const prepared = prepareCapture(capture, context)
    const now = Date.now()
    const report = {
      id: `r-${now.toString(36)}-${crypto.randomBytes(4).toString('hex')}`,
      createdAt: now,
      updatedAt: now,
      category,
      description: redactText(cut(description, MAX_DESCRIPTION), context).text,
      status: 'open',
      capture: prepared.capture,
      redactions: prepared.redactions,
    }
    this.write(report)
    this.prune()
    return report
  }

  update(id, change) {
    const report = this.get(id)
    const patch = change && typeof change === 'object' ? change : {}
    if (patch.category !== undefined && !CATEGORIES.includes(patch.category)) throw new Error('Unknown category.')
    if (patch.status !== undefined && !STATUSES.includes(patch.status)) throw new Error('Unknown status.')
    const next = {
      ...report,
      ...(patch.category !== undefined ? { category: patch.category } : {}),
      ...(patch.status !== undefined ? { status: patch.status } : {}),
      ...(patch.description !== undefined ? { description: redactText(cut(String(patch.description), MAX_DESCRIPTION)).text || report.description } : {}),
      updatedAt: Date.now(),
    }
    return this.write(next)
  }

  remove(id) {
    fs.rmSync(this.file(id), { force: true })
    return true
  }

  /** Keeps the newest MAX_REPORTS reports. */
  prune() {
    const all = this.list()
    for (const old of all.slice(MAX_REPORTS)) this.remove(old.id)
  }
}

module.exports = { ReportStore, prepareCapture, redactText, CATEGORIES, STATUSES, MAX_REPORTS }
