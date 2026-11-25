const test = require('node:test')
const assert = require('node:assert/strict')
const fs = require('node:fs')
const os = require('node:os')
const path = require('node:path')

// maintenance.cjs requires paths.cjs, which reads electron's `app`; outside Electron it is undefined.
const { Maintenance, parseDeviceCode, suggestLocalModel, ACCOUNT_CONFIRM_ERROR } = require('./maintenance.cjs')

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
  assert.throws(() => manager.setAgent({ id: 'claude' }), /Connect your Anthropic account first/, 'a signed-in tool is not used until connected here')
  manager.save({ connected: { claude: '2026-11-22T00:00:00.000Z' } })
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

const { installPlan, parseAccount, parseUrl, plain } = require('./maintenance-connect.cjs')

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
  const codex = installPlan('codex', { platform: 'win32', tools: { winget: 'C:\\w\\winget.exe', npm: 'npm.cmd' } })
  assert.deepEqual(codex.map((step) => step.label), ['npm'], 'Codex has no winget package: npm only on Windows')
  assert.deepEqual(codex[0].args, ['install', '-g', '@openai/codex'])
  assert.deepEqual(installPlan('codex', { platform: 'darwin', tools: { brew: '/opt/homebrew/bin/brew' } })[0].args, ['install', '--cask', 'codex'])
})

test('sign-in links and plain text are read from CLI output', () => {
  assert.equal(parseUrl('Open https://claude.ai/oauth/authorize?code=1&x=2). to continue'), 'https://claude.ai/oauth/authorize?code=1&x=2')
  assert.equal(parseUrl('no link, http://insecure.example'), '')
  assert.equal(plain('\u001b[32mDone\u001b[0m\r'), 'Done\n')
})

test('connect refuses unknown AIs and a second run at the same time', async () => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'maint-'))
  const manager = new Maintenance({ userData: dir, emit: () => {} })
  await assert.rejects(() => manager.connectAgent('local'), /cannot be connected/)
  await assert.rejects(() => manager.connectAgent('gpt-everything'), /cannot be connected/)
  manager.connecting = { id: 'claude', child: null }
  await assert.rejects(() => manager.connectAgent('copilot'), /still running/)
  assert.equal(manager.cancelConnect(), true)
  fs.rmSync(dir, { recursive: true, force: true })
})

test('an account already signed in on this PC is connected only after the user confirms it', async () => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'maint-'))
  const logs = []
  const manager = new Maintenance({ userData: dir, emit: (event) => logs.push(event) })
  manager.agentPath = () => 'C:\claude.exe'
  manager.cliStatus = async () => ({ signedIn: true, account: { email: 'someone@example.com', plan: 'Claude Pro' } })
  manager.agents = async () => []
  await assert.rejects(() => manager.connectAgent('claude'), (error) => error.message === ACCOUNT_CONFIRM_ERROR)
  assert.equal(manager.config().connected, undefined, 'nothing is saved without confirmation')
  assert.equal(manager.connecting, null)
  assert.ok(logs.some((event) => /Confirm the account/.test(event.line ?? '')))
  await manager.connectAgent('claude', { useSignedIn: true })
  assert.ok(manager.config().connected.claude, 'confirmed: connected')
  fs.rmSync(dir, { recursive: true, force: true })
})

test('the account a signed-in tool uses is read from its status output', () => {
  const claude = parseAccount('claude', '{\n  "loggedIn": true,\n  "authMethod": "claude.ai",\n  "email": "someone@example.com",\n  "subscriptionType": "pro"\n}')
  assert.deepEqual(claude, { email: 'someone@example.com', plan: 'Claude Pro' })
  assert.deepEqual(parseAccount('claude', 'not json'), { email: '', plan: '' })
  assert.deepEqual(parseAccount('codex', 'Logged in using ChatGPT\n'), { email: '', plan: 'Logged in using ChatGPT' })
})

test('PockPock itself fixes reports unless a chosen account is connected here and still signed in', async () => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'maint-'))
  const manager = new Maintenance({ userData: dir, emit: () => {} })
  const local = { id: 'local', model: 'qwen3.5:9b', openclaw: false, chosenAt: '' }
  manager.localAgent = async () => local
  let signedIn = true
  manager.cliStatus = async () => ({ signedIn, account: null })
  manager.agentPath = () => 'C:\\claude.exe'
  // Nothing chosen: PockPock itself, with no note.
  assert.deepEqual(await manager.effectiveAgent(), { agent: local, fallback: '' })
  // Chosen but never connected here (the tool is only signed in on this PC): PockPock itself, and why.
  manager.save({ agent: { id: 'claude', model: '', openclaw: false, chosenAt: 'x' } })
  let result = await manager.effectiveAgent()
  assert.equal(result.agent, local)
  assert.match(result.fallback, /never connected here, so PockPock itself fixes reports with qwen3.5:9b/)
  // Connected: the account is used.
  manager.save({ connected: { claude: '2026-11-22T00:00:00.000Z' } })
  assert.equal((await manager.effectiveAgent()).agent.id, 'claude')
  // Signed out since: back to PockPock itself.
  signedIn = false
  result = await manager.effectiveAgent()
  assert.equal(result.agent, local)
  assert.match(result.fallback, /no longer signed in/)
  // No local model either: nothing can fix reports, and the note says what to do.
  manager.localAgent = async () => null
  result = await manager.effectiveAgent()
  assert.equal(result.agent, null)
  assert.match(result.fallback, /start Ollama/)
  fs.rmSync(dir, { recursive: true, force: true })
})

test('disconnecting forgets the account here and goes back to PockPock itself', async () => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'maint-'))
  const manager = new Maintenance({ userData: dir, emit: () => {} })
  manager.agents = async () => []
  manager.save({ agent: { id: 'codex', model: '', openclaw: false, chosenAt: 'x' }, connected: { codex: 'a', claude: 'b' } })
  await manager.disconnectAgent('codex')
  assert.deepEqual(manager.config().connected, { claude: 'b' })
  assert.equal(manager.config().agent, null, 'the chosen account is cleared, so PockPock itself is used')
  manager.save({ agent: { id: 'local', model: 'qwen3.5:9b', openclaw: false, chosenAt: 'x' } })
  await manager.disconnectAgent('claude')
  assert.equal(manager.config().agent.id, 'local', 'another choice is kept')
  assert.throws(() => manager.disconnectAgent('local'), /Unknown AI/)
  fs.rmSync(dir, { recursive: true, force: true })
})
