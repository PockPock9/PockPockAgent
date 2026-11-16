const test = require('node:test')
const assert = require('node:assert/strict')
const fs = require('node:fs')
const os = require('node:os')
const path = require('node:path')

const { Cloud, normalizeModels, cleanKey } = require('./cloud.cjs')
const { openclawProvider, syncOpenClaw } = require('./cloud-openclaw.cjs')

// A reversible stand-in for the operating system's encryption.
const crypt = { available: () => true, encrypt: (text) => Buffer.from(`enc:${text}`).reverse(), decrypt: (data) => Buffer.from(data).reverse().toString().replace(/^enc:/, '') }

const OPENROUTER_MODELS = { data: [
  { id: 'qwen/qwen3-coder', name: 'Qwen3 Coder', context_length: 262144, supported_parameters: ['tools', 'temperature'], pricing: { prompt: '0.0000002', completion: '0.0000008' } },
  { id: 'anthropic/claude-sonnet-4.5', name: 'Claude Sonnet 4.5', context_length: 1000000, supported_parameters: ['tools'] },
  { id: 'deepseek/deepseek-r1:free', name: 'DeepSeek R1 (free)', context_length: 163840, supported_parameters: [] },
  { id: 'openai/text-embedding-3-small', name: 'Embedding' },
  { id: 'black-forest-labs/flux-1', architecture: { output_modalities: ['image'] } },
  { id: 'bad id with spaces' },
] }

/** A fake fetch: records calls and answers by URL. */
function fakeFetch(routes) {
  const calls = []
  const fetch = async (url, options = {}) => {
    calls.push({ url, method: options.method ?? 'GET', auth: options.headers?.Authorization ?? '', token: options.headers?.['X-PockPock-Internal-Token'] ?? '', body: options.body ? JSON.parse(options.body) : null })
    const route = routes(url, options)
    if (route === 'network') throw new TypeError('fetch failed')
    return { status: route.status, ok: route.status < 400, json: async () => route.json }
  }
  return { fetch, calls }
}

function setup(routes) {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'cloud-'))
  const net = fakeFetch(routes)
  let changes = 0
  const cloud = new Cloud({ userData: dir, crypt, fetch: net.fetch, internalToken: () => 'internal', onChange: () => { changes += 1 } })
  return { dir, cloud, calls: net.calls, changes: () => changes, done: () => fs.rmSync(dir, { recursive: true, force: true }) }
}

const openrouterRoutes = (url, options) => {
  if (url.includes('127.0.0.1:8766')) return { status: 200, json: { ok: true } }
  if (url.endsWith('/key')) return options.headers.Authorization === 'Bearer sk-or-good' ? { status: 200, json: { data: {} } } : { status: 401, json: { error: 'bad' } }
  if (url.endsWith('/models')) return { status: 200, json: OPENROUTER_MODELS }
  return { status: 404, json: null }
}

test('model lists keep chat models only and read their details', () => {
  const models = normalizeModels(OPENROUTER_MODELS)
  assert.deepEqual(models.map((model) => model.id), ['anthropic/claude-sonnet-4.5', 'deepseek/deepseek-r1:free', 'qwen/qwen3-coder'])
  assert.deepEqual(models[2], { id: 'qwen/qwen3-coder', name: 'Qwen3 Coder', contextWindow: 262144, tools: true, free: false })
  assert.equal(models[1].free, true)
  assert.deepEqual(normalizeModels({ data: [{ id: 'qwen-plus' }, { id: 'text-embedding-v4' }, { id: 'wan2.5-t2v' }] }).map((model) => model.id), ['qwen-plus'])
  assert.deepEqual(normalizeModels(null), [])
})

test('keys are trimmed and refused when empty or with spaces', () => {
  assert.equal(cleanKey('  nvapi-abc\n'), 'nvapi-abc')
  for (const bad of ['', '   ', 'two words', 'x'.repeat(401), null]) assert.throws(() => cleanKey(bad), /API key/)
})

test('connect checks the key, saves it encrypted and never lists it', async () => {
  const { dir, cloud, calls, changes, done } = setup(openrouterRoutes)
  await assert.rejects(() => cloud.connect('openrouter', { key: 'sk-or-wrong' }), /did not accept that API key/)
  assert.equal(cloud.list().find((item) => item.id === 'openrouter').connected, false)
  assert.equal(fs.existsSync(path.join(dir, 'cloud.json')), false, 'nothing is saved for a refused key')

  const result = await cloud.connect('openrouter', { key: ' sk-or-good ' })
  const listed = result.providers.find((item) => item.id === 'openrouter')
  assert.equal(listed.connected, true)
  assert.equal(listed.keyEnding, 'good')
  // Suggested models that the provider really offers are switched on.
  assert.deepEqual(listed.models.map((model) => model.id), ['anthropic/claude-sonnet-4.5', 'qwen/qwen3-coder'])
  assert.equal(result.offered.length, 3)
  const onDisk = fs.readFileSync(path.join(dir, 'cloud.json'), 'utf8')
  assert.ok(!onDisk.includes('sk-or-good'), 'the key is not stored in plain text')
  assert.ok(!JSON.stringify(result).includes('sk-or-good'), 'the key is not returned to the page')
  assert.equal(changes(), 1)

  // The gateway gets the key over the internal call only.
  const push = calls.find((call) => call.url.endsWith('/api/cloud/config'))
  assert.equal(push.token, 'internal')
  assert.equal(push.body.providers[0].api_key, 'sk-or-good')
  assert.equal(push.body.providers[0].base_url, 'https://openrouter.ai/api/v1')
  assert.deepEqual(push.body.providers[0].models[1], { id: 'qwen/qwen3-coder', context_window: 262144 })
  assert.ok(push.body.proxy_token.length >= 32)
  assert.equal(cloud.pushed, true)
  // No request other than the provider's own address and the local gateway.
  assert.ok(calls.every((call) => call.url.startsWith('https://openrouter.ai/api/v1/') || call.url.startsWith('http://127.0.0.1:8766/')))
  done()
})

test('choosing models, reconnecting and disconnecting', async () => {
  const { cloud, done } = setup(openrouterRoutes)
  await assert.rejects(() => cloud.setModels('openrouter', []), /Connect this provider first/)
  await cloud.connect('openrouter', { key: 'sk-or-good' })
  const offered = await cloud.available('openrouter')
  await cloud.setModels('openrouter', [offered[1], offered[1], { id: 'bad id' }])
  assert.deepEqual(cloud.chosenModels(), [{ name: 'openrouter/deepseek/deepseek-r1:free', label: 'DeepSeek R1 (free)', provider: 'openrouter', contextWindow: 163840 }])
  await assert.rejects(() => cloud.setModels('openrouter', Array.from({ length: 41 }, (_, index) => ({ id: `m/${index}` }))), /at most 40/)
  // A new key keeps the earlier choice.
  const again = await cloud.connect('openrouter', { key: 'sk-or-good' })
  assert.deepEqual(again.providers.find((item) => item.id === 'openrouter').models.map((model) => model.id), ['deepseek/deepseek-r1:free'])
  const after = await cloud.disconnect('openrouter')
  assert.equal(after.find((item) => item.id === 'openrouter').connected, false)
  assert.deepEqual(cloud.chosenModels(), [])
  assert.deepEqual(cloud.gatewayConfig().providers, [])
  await assert.rejects(() => cloud.connect('other', { key: 'x' }), /Unknown cloud provider/)
  done()
})

test('Alibaba uses the chosen region; NVIDIA checks the key with a one-token reply', async () => {
  const alibaba = setup((url, options) => {
    if (url.includes('127.0.0.1')) return { status: 200, json: {} }
    if (!url.startsWith('https://dashscope-us.aliyuncs.com/compatible-mode/v1/')) return 'network'
    return options.headers.Authorization === 'Bearer sk-ali' ? { status: 200, json: { data: [{ id: 'qwen-plus' }, { id: 'qwen3-max' }] } } : { status: 401, json: null }
  })
  const connected = await alibaba.cloud.connect('alibaba', { key: 'sk-ali', region: 'us' })
  assert.equal(connected.providers.find((item) => item.id === 'alibaba').region, 'us')
  assert.equal(alibaba.cloud.gatewayConfig().providers[0].base_url, 'https://dashscope-us.aliyuncs.com/compatible-mode/v1')
  await assert.rejects(() => alibaba.cloud.connect('alibaba', { key: 'sk-other', region: 'us' }), /region matches the key/)
  alibaba.done()

  const nim = setup((url, options) => {
    if (url.includes('127.0.0.1')) return { status: 200, json: {} }
    // A listed model that is not served answers 404 whatever the key is; a served one checks the key.
    if (url.endsWith('/chat/completions')) return JSON.parse(options.body).model === 'aaa/retired-mini' ? { status: 404, json: null } : options.headers.Authorization === 'Bearer nvapi-good' ? { status: 200, json: {} } : { status: 403, json: null }
    return { status: 200, json: { data: [{ id: 'aaa/retired-mini' }, { id: 'openai/gpt-oss-20b' }, { id: 'nvidia/nv-embedqa-e5-v5' }, { id: 'nvidia/nvclip' }] } }
  })
  await assert.rejects(() => nim.cloud.connect('nim', { key: 'nvapi-bad' }), /did not accept/)
  const result = await nim.cloud.connect('nim', { key: 'nvapi-good' })
  assert.deepEqual(result.providers.find((item) => item.id === 'nim').models.map((model) => model.id), ['openai/gpt-oss-20b'])
  assert.deepEqual(result.offered.map((model) => model.id), ['aaa/retired-mini', 'openai/gpt-oss-20b'])
  const checks = nim.calls.filter((call) => call.url.endsWith('/chat/completions') && call.auth === 'Bearer nvapi-good')
  assert.deepEqual(checks.map((call) => [call.body.model, call.body.max_tokens]), [['aaa/retired-mini', 1], ['openai/gpt-oss-20b', 1]])
  nim.done()
  const gone = setup((url) => (url.includes('127.0.0.1') ? { status: 200, json: {} } : url.endsWith('/models') ? { status: 200, json: { data: [{ id: 'aaa/retired-mini' }] } } : { status: 410, json: null }))
  await assert.rejects(() => gone.cloud.connect('nim', { key: 'nvapi-good' }), /could not check the key right now/)
  gone.done()
})

test('a provider that cannot be reached, and a key that cannot be protected', async () => {
  const offline = setup(() => 'network')
  await assert.rejects(() => offline.cloud.connect('openrouter', { key: 'sk-or-good' }), /could not be reached/)
  offline.done()
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'cloud-'))
  const unsafe = new Cloud({ userData: dir, crypt: { ...crypt, available: () => false }, fetch: fakeFetch(openrouterRoutes).fetch, internalToken: () => 'i' })
  await assert.rejects(() => unsafe.connect('openrouter', { key: 'sk-or-good' }), /cannot protect saved keys/)
  fs.rmSync(dir, { recursive: true, force: true })
})

test('a key that can no longer be decrypted asks for the key again', async () => {
  const { dir, cloud, done } = setup(openrouterRoutes)
  await cloud.connect('openrouter', { key: 'sk-or-good' })
  const moved = new Cloud({ userData: dir, crypt: { ...crypt, decrypt: () => { throw new Error('wrong machine') } }, fetch: fakeFetch(openrouterRoutes).fetch, internalToken: () => 'i' })
  const listed = moved.list().find((item) => item.id === 'openrouter')
  assert.equal(listed.connected, false)
  assert.equal(listed.needsKey, true)
  assert.deepEqual(moved.gatewayConfig().providers, [])
  done()
})

test('OpenClaw gets one provider that points at the local endpoint, never a cloud key', async () => {
  const models = [{ name: 'nim/meta/llama-3.3-70b-instruct', label: 'Llama 3.3 70B', provider: 'nim', contextWindow: 131072 }, { name: 'alibaba/qwen-plus', label: 'alibaba/qwen-plus', provider: 'alibaba', contextWindow: null }]
  const provider = openclawProvider(models, 'local-token')
  assert.equal(provider.baseUrl, 'http://127.0.0.1:8766/cloud/v1')
  assert.equal(provider.apiKey, 'local-token')
  assert.deepEqual(provider.models.map((model) => [model.id, model.contextWindow]), [['nim/meta/llama-3.3-70b-instruct', 131072], ['alibaba/qwen-plus', 128000]])
  assert.equal(openclawProvider([], 'local-token'), null)

  const ran = []
  let stored = null
  const cli = async (args) => {
    ran.push(args)
    if (args[1] === 'get') return { ok: true, stdout: stored ? JSON.stringify({ ...stored, apiKey: '***' }) : '{"ok":false}', stderr: '' }
    if (args[1] === 'set') { stored = JSON.parse(args[3]); return { ok: true, stdout: '', stderr: '' } }
    stored = null
    return { ok: true, stdout: '', stderr: '' }
  }
  assert.equal(await syncOpenClaw(cli, [], ''), 'unchanged')
  assert.equal(await syncOpenClaw(cli, models, 'local-token'), 'set')
  assert.deepEqual(ran.at(-1).slice(0, 3), ['config', 'set', 'models.providers.pockpock-cloud'])
  assert.equal(await syncOpenClaw(cli, models, 'local-token'), 'unchanged')
  assert.equal(await syncOpenClaw(cli, models.slice(0, 1), 'local-token'), 'set')
  assert.equal(await syncOpenClaw(cli, [], ''), 'removed')
  assert.equal(stored, null)
  await assert.rejects(() => syncOpenClaw(async (args) => (args[1] === 'get' ? { ok: true, stdout: '{"ok":false}', stderr: '' } : { ok: false, stdout: '', stderr: 'config is locked' }), models, 't'), /config is locked/)
})
