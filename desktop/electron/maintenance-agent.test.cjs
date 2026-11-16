const test = require('node:test')
const assert = require('node:assert/strict')
const fs = require('node:fs')
const os = require('node:os')
const path = require('node:path')
const { runTool, resolveInside } = require('./maintenance-agent.cjs')

function repo() {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), 'agent-'))
  fs.mkdirSync(path.join(root, 'docs'))
  fs.mkdirSync(path.join(root, '.git'))
  fs.mkdirSync(path.join(root, 'node_modules'))
  fs.writeFileSync(path.join(root, 'docs', 'guide.md'), '# Guide\r\n\r\nRun npm test.\r\n')
  fs.writeFileSync(path.join(root, 'node_modules', 'x.js'), 'needle')
  return root
}

test('paths cannot leave the worktree or touch .git', () => {
  const root = repo()
  assert.throws(() => resolveInside(root, '../outside.txt'), /outside the repository/)
  assert.throws(() => resolveInside(root, '.git/config'), /outside the repository/)
  assert.equal(resolveInside(root, '/docs/guide.md'), path.join(root, 'docs', 'guide.md'))
})

test('list, search and read skip build folders and number lines', () => {
  const root = repo()
  assert.equal(runTool(root, 'list_files', { path: '' }), 'docs/')
  assert.equal(runTool(root, 'search', { text: 'NPM TEST' }), 'docs/guide.md:3: Run npm test.')
  assert.equal(runTool(root, 'search', { text: 'needle' }), 'No matches.')
  assert.match(runTool(root, 'read_file', { path: 'docs/guide.md' }), /^docs\/guide\.md \(lines 1-4 of 4\)\n1: # Guide\n2: \n3: Run npm test\./)
})

test('replace_in_file needs exactly one match and keeps Windows line endings', () => {
  const root = repo()
  assert.match(runTool(root, 'replace_in_file', { path: 'docs/guide.md', old_text: 'missing', new_text: 'x' }), /found 0 times/)
  assert.equal(runTool(root, 'replace_in_file', { path: 'docs/guide.md', old_text: 'Run npm test.', new_text: 'Run npm test and npm run build.' }), 'Replaced in docs/guide.md.')
  assert.equal(fs.readFileSync(path.join(root, 'docs', 'guide.md'), 'utf8'), '# Guide\r\n\r\nRun npm test and npm run build.\r\n')
})

test('finish reports the title and description; unknown tools are explained', () => {
  const root = repo()
  let done = null
  runTool(root, 'finish', { title: 'docs: x', description: 'y' }, (title, description) => { done = { title, description } })
  assert.deepEqual(done, { title: 'docs: x', description: 'y' })
  assert.match(runTool(root, 'run_shell', {}), /There is no tool named "run_shell"/)
})
