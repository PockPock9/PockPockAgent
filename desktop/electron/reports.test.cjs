const test = require('node:test')
const assert = require('node:assert/strict')
const fs = require('node:fs')
const os = require('node:os')
const path = require('node:path')
const { ReportStore, prepareCapture, redactText } = require('./reports.cjs')

const ctx = { home: 'C:\\Users\\alice', user: 'alice' }

test('redacts the home folder in any slash style, the user name, emails and secrets', () => {
  const { text, found } = redactText('Wrote C:\\Users\\alice\\notes.txt and c:/users/alice/a.md for alice (alice@example.com) with token=abcd1234efgh and ghp_aaaaaaaaaaaaaaaaaaaaaaaaaaaaaa', ctx)
  assert.equal(text, 'Wrote ~\\notes.txt and ~/a.md for <user> (<email>) with token=<secret> and <secret>')
  assert.deepEqual(found, { path: 2, user: 1, email: 1, token: 2 })
})

test('leaves ordinary text, short ids and plain words alone', () => {
  const sample = 'npm.cmd ls -g puppeteer exited with code 1 after 32 s; step e179; model qwen3.5:9b'
  assert.equal(redactText(sample, ctx).text, sample)
})

test('long opaque keys are hidden but long plain words are not', () => {
  assert.equal(redactText('key Zm9vYmFyYmF6cXV4MTIzNDU2Nzg5MGFiY2RlZmdoaWprbG1u end', ctx).text, 'key <secret> end')
  assert.equal(redactText('Supercalifragilisticexpialidocious_and_more_words_here', ctx).text, 'Supercalifragilisticexpialidocious_and_more_words_here')
})

test('capture keeps only known fields, bounded, and redacts nested strings', () => {
  const { capture, redactions } = prepareCapture({
    engine: 'openclaw', userMessage: 'open C:\\Users\\alice\\x.pdf', secretField: 'dropped',
    steps: [{ label: 'Read C:\\Users\\alice\\x.pdf', status: 'failed', detail: 'boom', ms: 12.6, extra: 1 }],
    attachments: ['x.pdf'], reply: 'a'.repeat(30000),
  }, ctx)
  assert.equal(capture.secretField, undefined)
  assert.equal(capture.userMessage, 'open ~\\x.pdf')
  assert.deepEqual(capture.steps[0], { label: 'Read ~\\x.pdf', status: 'failed', detail: 'boom', ms: 13 })
  assert.equal(capture.reply.length, 20001)
  assert.equal(redactions.path, 2)
})

test('store: create, list, update, delete; rejects bad input and path tricks', () => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'reports-'))
  const store = new ReportStore(dir)
  assert.throws(() => store.create({ category: 'nope', description: '', capture: {} }), /Choose what went wrong/)
  const report = store.create({ category: 'hang', description: 'It froze for alice', capture: { engine: 'openclaw', chatTitle: 'Scrape' } }, ctx)
  assert.match(report.id, /^r-[a-z0-9]+-[a-f0-9]{8}$/)
  assert.equal(report.description, 'It froze for <user>')
  assert.equal(report.status, 'open')
  const listed = store.list()
  assert.equal(listed.length, 1)
  assert.equal(listed[0].capture, undefined)
  assert.equal(listed[0].engine, 'openclaw')
  assert.equal(store.update(report.id, { status: 'fixed' }).status, 'fixed')
  assert.throws(() => store.update(report.id, { status: 'merged' }), /Unknown status/)
  for (const bad of ['../evil', 'r-x', '', 7, 'r-abc-12345678/../../x']) assert.throws(() => store.get(bad), /Unknown report/)
  store.remove(report.id)
  assert.equal(store.list().length, 0)
  fs.rmSync(dir, { recursive: true, force: true })
})
