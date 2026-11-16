// node --test electron/   (npm test)
const test = require('node:test')
const assert = require('node:assert/strict')
const fs = require('node:fs')
const os = require('node:os')
const path = require('node:path')
const { mergeGuidance, syncGuidance, START, END } = require('./openclaw-guidance.cjs')

const OPENCLAW = '# AGENTS.md - Your Workspace\n\n## Red Lines\n\nBe careful.\n'
const LEGACY = '## Using the browser on this PC\n\nOld text.\n\n## Operating this Windows PC\n\nMore old text. Before deleting files, say what you are about to do.\n'

test('appends a marked block to a file without one', () => {
  const out = mergeGuidance(OPENCLAW, 'New guidance')
  assert.ok(out.startsWith(OPENCLAW.trim()))
  assert.ok(out.includes(`${START}\nNew guidance\n${END}`))
})

test('replaces only the marked block, keeping text before and after it', () => {
  const first = mergeGuidance(`${OPENCLAW}\n## User notes\n\nKeep me.\n`, 'v1')
  const withAfter = `${first}\n## Added later\n\nAlso keep me.\n`
  const second = mergeGuidance(withAfter, 'v2')
  assert.ok(second.includes('Keep me.') && second.includes('Also keep me.') && second.includes('## Red Lines'))
  assert.ok(second.includes(`${START}\nv2\n${END}`))
  assert.ok(!second.includes('v1'))
  assert.equal(second.split(START).length, 2)
})

test('removes the unmarked first version before adding the block', () => {
  const out = mergeGuidance(`${OPENCLAW}\n${LEGACY}`, 'v2')
  assert.ok(!out.includes('Old text') && !out.includes('More old text'))
  assert.ok(out.includes('## Red Lines') && out.includes(`${START}\nv2\n${END}`))
})

test('is stable: merging the same guidance twice changes nothing', () => {
  const once = mergeGuidance(OPENCLAW, 'Same')
  assert.equal(mergeGuidance(once, 'Same'), once)
})

test('handles Windows line endings', () => {
  const once = mergeGuidance(OPENCLAW.replace(/\n/g, '\r\n'), 'X')
  assert.ok(!once.includes('\r'))
  assert.equal(mergeGuidance(once, 'X'), once)
})

test('syncGuidance writes the bundled file and reports current afterwards', () => {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), 'guidance-'))
  const backend = path.join(root, 'backend')
  const home = path.join(root, '.openclaw')
  fs.mkdirSync(path.join(backend, 'projects', 'openclaw_bridge'), { recursive: true })
  fs.mkdirSync(path.join(home, 'workspace'), { recursive: true })
  fs.writeFileSync(path.join(backend, 'projects', 'openclaw_bridge', 'workspace-guidance.md'), 'Bundled')
  fs.writeFileSync(path.join(home, 'workspace', 'AGENTS.md'), OPENCLAW + '\n' + LEGACY)
  assert.equal(syncGuidance(backend, home), 'updated')
  assert.equal(syncGuidance(backend, home), 'current')
  const text = fs.readFileSync(path.join(home, 'workspace', 'AGENTS.md'), 'utf8')
  assert.ok(text.includes('Bundled') && !text.includes('Old text'))
  assert.equal(syncGuidance(backend, path.join(root, 'missing')), 'skipped')
  fs.rmSync(root, { recursive: true, force: true })
})
