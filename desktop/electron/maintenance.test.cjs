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
  assert.equal(manager.setAgent({ id: 'claude', openclaw: true }).agent.openclaw, false, 'only PockPock itself can use OpenClaw')
  assert.equal(manager.config().agent.id, 'claude')
  assert.equal(manager.setAgent({ id: 'local', model: 'qwen3.5:9b' }).agent.openclaw, false, 'off unless chosen')
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

const { installPlan, parseUrl, plain } = require('./maintenance-connect.cjs')

test('install plan: winget or Homebrew first, npm as the fallback, constants only', () => {
  const win = installPlan('claude', { platform: 'win32', tools: { winget: 'C:\\w\\winget.exe', npm: 'C:\\Program Files\\nodejs\\npm.cmd' } })
  assert.deepEqual(win.map((step) => step.label), ['winget', 'npm'])
  assert.ok(win[0].args.includes('Anthropic.ClaudeCode'))
  assert.equal(win[1].file, '"C:\\Program Files\\nodejs\\npm.cmd"', 'a .cmd path is quoted for cmd.exe')
  assert.deepEqual(win[1].args, ['install', '-g', '@anthropic-ai/claude-code'])
  const mac = installPlan('copilot', { platform: 'darwin', tools: { brew: '/opt/homebrew/bin/brew', npm: '/usr/local/bin/npm', winget: 'ignored' } })
  assert.deepEqual(mac.map((step) => step.label), ['Homebrew', 'npm'])
  assert.equal(mac[1].shell, false)
  assert.deepEqual(installPlan('copilot', { platform: 'win32', tools: {} }), [])
  assert.deepEqual(installPlan('codex', { platform: 'win32', tools: { npm: 'npm.cmd' } }), [], 'only Claude Code and Copilot connect from the app')
})

test('sign-in links and plain text are read from CLI output', () => {
  assert.equal(parseUrl('Open https://claude.ai/oauth/authorize?code=1&x=2). to continue'), 'https://claude.ai/oauth/authorize?code=1&x=2')
  assert.equal(parseUrl('no link, http://insecure.example'), '')
  assert.equal(plain('\u001b[32mDone\u001b[0m\r'), 'Done\n')
})

test('connect refuses unknown AIs and a second run at the same time', async () => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'maint-'))
  const manager = new Maintenance({ userData: dir, emit: () => {} })
  await assert.rejects(() => manager.connectAgent('codex'), /cannot be connected/)
  await assert.rejects(() => manager.connectAgent('local'), /cannot be connected/)
  manager.connecting = { id: 'claude', child: null }
  await assert.rejects(() => manager.connectAgent('copilot'), /still running/)
  assert.equal(manager.cancelConnect(), true)
  fs.rmSync(dir, { recursive: true, force: true })
})
