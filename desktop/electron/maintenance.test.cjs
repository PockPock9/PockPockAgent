const test = require('node:test')
const assert = require('node:assert/strict')
const fs = require('node:fs')
const os = require('node:os')
const path = require('node:path')

// maintenance.cjs requires paths.cjs, which reads electron's `app`; outside Electron it is undefined.
const { Maintenance, parseDeviceCode, suggestLocalModel } = require('./maintenance.cjs')

test('reads the one-time code from gh auth login output', () => {
  const output = '! First copy your one-time code: 1A2B-C3D4\nPress Enter to open https://github.com/login/device in your browser...'
  assert.equal(parseDeviceCode(output), '1A2B-C3D4')
  assert.equal(parseDeviceCode('no code here'), '')
})

test('suggests the largest local model that is not an embedding or vision model', () => {
  assert.equal(suggestLocalModel(['qwen3.5:9b', 'qwen3.5:27b', 'nomic-embed-text:latest', 'llava:7b', 'qwen2.5:1.5b']), 'qwen3.5:27b')
  assert.equal(suggestLocalModel([]), '')
})

test('agent choice is validated and saved; forget removes the setup', () => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'maint-'))
  const manager = new Maintenance({ userData: dir, emit: () => {} })
  assert.throws(() => manager.setAgent({ id: 'gpt-everything' }), /Unknown AI/)
  assert.throws(() => manager.setAgent({ id: 'local' }), /Choose a local model/)
  assert.equal(manager.setAgent({ id: 'local', model: 'qwen3.5:27b' }).agent.model, 'qwen3.5:27b')
  assert.equal(manager.setAgent({ id: 'claude', model: 'ignored' }).agent.model, '')
  assert.equal(manager.config().agent.id, 'claude')
  assert.equal(manager.forget(), true)
  assert.deepEqual(manager.config(), {})
  fs.rmSync(dir, { recursive: true, force: true })
})

test('clone refuses relative folders and non-empty folders that are not a PockPock copy', async () => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'maint-'))
  const manager = new Maintenance({ userData: dir, emit: () => {} })
  await assert.rejects(() => manager.clone('relative/path'), /Choose a folder/)
  await assert.rejects(() => manager.clone(42), /Choose a folder/)
  fs.rmSync(dir, { recursive: true, force: true })
})
