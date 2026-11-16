const test = require('node:test')
const assert = require('node:assert/strict')
const fs = require('node:fs')
const os = require('node:os')
const path = require('node:path')

const { Connectors } = require('./connectors.cjs')

// A reversible stand-in for the operating system's encryption.
const crypt = { available: () => true, encrypt: (text) => Buffer.from(`enc:${text}`).reverse(), decrypt: (data) => Buffer.from(data).reverse().toString().replace(/^enc:/, '') }
const CATALOG = [{ id: 'github', name: 'GitHub', connected: false, account: '' }, { id: 'telegram', name: 'Telegram', connected: false, account: '' }]

/** A fake gateway: verifies "good" tokens, records every call. */
function fakeGateway({ up = true } = {}) {
  const calls = []
  const fetch = async (url, options = {}) => {
    const body = options.body ? JSON.parse(options.body) : null
    calls.push({ url, method: options.method ?? 'GET', token: options.headers?.['X-PockPock-Internal-Token'], body })
    if (!up) throw new TypeError('fetch failed')
    const reply = (status, json) => ({ status, ok: status < 400, json: async () => json })
    if (url.endsWith('/api/connectors')) return reply(200, { connectors: CATALOG })
    if (url.endsWith('/api/connectors/verify')) {
      if (body.credentials.token !== 'good-token') return reply(409, { detail: 'GitHub did not accept that personal access token.' })
      return reply(200, { id: body.id, account: 'octo', credentials: { token: body.credentials.token } })
    }
    if (url.endsWith('/api/connectors/config')) return reply(200, { ok: true })
    return reply(404, { detail: 'Not Found' })
  }
  return { fetch, calls }
}

function setup(options) {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'connectors-'))
  const gateway = fakeGateway(options)
  let changes = 0
  const connectors = new Connectors({ userData: dir, crypt, fetch: gateway.fetch, internalToken: () => 'internal', onChange: () => { changes += 1 } })
  return { dir, connectors, calls: gateway.calls, changes: () => changes, done: () => fs.rmSync(dir, { recursive: true, force: true }) }
}

test('a refused credential is not saved; an accepted one is saved encrypted and never listed', async () => {
  const { dir, connectors, calls, changes, done } = setup()
  await assert.rejects(() => connectors.connect('github', { token: 'bad-token' }), /did not accept/)
  assert.equal(fs.existsSync(path.join(dir, 'connectors.json')), false)
  assert.equal(changes(), 0)

  const list = await connectors.connect('github', { token: 'good-token', '__proto__': 'x', 'Bad Key': 'y', nested: { a: 1 } })
  const github = list.find((item) => item.id === 'github')
  assert.equal(github.connected, true)
  assert.equal(github.account, 'octo')
  assert.ok(github.connectedAt)
  assert.equal(list.find((item) => item.id === 'telegram').connected, false)
  assert.ok(!JSON.stringify(list).includes('good-token'), 'the credential is not returned to the page')
  assert.ok(!fs.readFileSync(path.join(dir, 'connectors.json'), 'utf8').includes('good-token'), 'the credential is not stored in plain text')
  assert.equal(changes(), 1)

  // Only plain string fields reach the gateway, with the internal token.
  const verify = calls.filter((call) => call.url.endsWith('/verify')).at(-1)
  assert.deepEqual(verify.body, { id: 'github', credentials: { token: 'good-token' } })
  assert.equal(verify.token, 'internal')
  const push = calls.find((call) => call.url.endsWith('/config'))
  assert.deepEqual(push.body.connected, [{ id: 'github', account: 'octo', credentials: { token: 'good-token' } }])
  assert.ok(push.body.tool_token.length >= 32)
  assert.equal(connectors.pushed, true)
  assert.ok(calls.every((call) => call.url.startsWith('http://127.0.0.1:8766/')), 'the page talks only to the local gateway')
  done()
})

test('disconnect deletes the credential and tells the gateway', async () => {
  const { dir, connectors, calls, done } = setup()
  await connectors.connect('github', { token: 'good-token' })
  assert.equal(connectors.count(), 1)
  const list = await connectors.disconnect('github')
  assert.equal(list.find((item) => item.id === 'github').connected, false)
  assert.equal(connectors.count(), 0)
  assert.deepEqual(calls.filter((call) => call.url.endsWith('/config')).at(-1).body.connected, [])
  assert.ok(!fs.readFileSync(path.join(dir, 'connectors.json'), 'utf8').includes('secret'))
  for (const bad of ['../x', 'GitHub', '', 42]) await assert.rejects(() => connectors.disconnect(bad), /Unknown connector/)
  await assert.rejects(() => connectors.connect('bad id', {}), /Unknown connector/)
  done()
})

test('a credential that can no longer be decrypted asks to reconnect and is not sent', async () => {
  const { dir, connectors, done } = setup()
  await connectors.connect('github', { token: 'good-token' })
  const moved = new Connectors({ userData: dir, crypt: { ...crypt, decrypt: () => { throw new Error('wrong machine') } }, fetch: fakeGateway().fetch, internalToken: () => 'i' })
  const github = (await moved.list()).find((item) => item.id === 'github')
  assert.deepEqual([github.connected, github.needsReconnect, github.account], [false, true, ''])
  assert.deepEqual(moved.gatewayConfig().connected, [])
  assert.equal(moved.count(), 0)
  done()
})

test('clear messages when the backend is down, too old, or keys cannot be protected', async () => {
  const down = setup({ up: false })
  await assert.rejects(() => down.connectors.list(), /backend is not running/)
  assert.equal(await down.connectors.push(), false)
  down.done()
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'connectors-'))
  const old = new Connectors({ userData: dir, crypt, fetch: async () => ({ status: 404, ok: false, json: async () => ({ detail: { not: 'a string' } }) }), internalToken: () => 'i' })
  await assert.rejects(() => old.list(), /older than this app/)
  const unsafe = new Connectors({ userData: dir, crypt: { ...crypt, available: () => false }, fetch: fakeGateway().fetch, internalToken: () => 'i' })
  await assert.rejects(() => unsafe.connect('github', { token: 'good-token' }), /cannot protect saved credentials/)
  fs.rmSync(dir, { recursive: true, force: true })
})
