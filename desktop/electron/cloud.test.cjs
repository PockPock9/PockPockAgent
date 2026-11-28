const test = require('node:test')
const assert = require('node:assert/strict')
const fs = require('node:fs')
const os = require('node:os')
const path = require('node:path')

const { Cloud, normalizeModels, cleanKey } = require('./cloud.cjs')
const { openclawProvider, syncOpenClaw } = require('./cloud-openclaw.cjs')

// A reversible stand-in for the operating system's encryption.
const crypt = { available: () => true, encrypt: (text) => Buffer.from(`enc:${text}`).reverse(), decrypt: (data) => Buffer.from(data).reverse().toString().replace(/^enc:/, '') }

// OpenAI lists every model of the account, with no names or context sizes.
const OPENAI_MODELS = { object: 'list', data: [
  { id: 'gpt-5.1', object: 'model', created: 1762000000, owned_by: 'system' },
  { id: 'gpt-5-mini', object: 'model', created: 1754000000, owned_by: 'system' },
  { id: 'gpt-4.1', object: 'model', created: 1744000000, owned_by: 'system' },
  { id: 'text-embedding-3-small', object: 'model', created: 1705000000, owned_by: 'system' },
  { id: 'gpt-realtime', object: 'model', created: 1756000000, owned_by: 'system' },
  { id: 'omni-moderation-latest', object: 'model', created: 1731000000, owned_by: 'system' },
  { id: 'dall-e-3', object: 'model', created: 1698000000, owned_by: 'system' },
  { id: 'gpt-5-pro', object: 'model', created: 1759000000, owned_by: 'system' },
  { id: 'whisper-1', object: 'model', created: 1677000000, owned_by: 'openai-internal' },
] }
// Anthropic's GET /v1/models: display_name and max_input_tokens (the context window).
const ANTHROPIC_MODELS = { data: [
  { type: 'model', id: 'claude-opus-5-5', display_name: 'Claude Opus 5.5', created_at: '2026-10-01T00:00:00Z', max_input_tokens: 1000000, max_tokens: 128000 },
  { type: 'model', id: 'claude-sonnet-5-5', display_name: 'Claude Sonnet 5.5', created_at: '2026-10-01T00:00:00Z', max_input_tokens: 1000000, max_tokens: 128000 },
  { type: 'model', id: 'claude-haiku-4-5', display_name: 'Claude Haiku 4.5', created_at: '2025-10-01T00:00:00Z', max_input_tokens: 200000, max_tokens: 64000 },
], has_more: false }

/** A fake fetch: records calls and answers by URL. */
function fakeFetch(routes) {
  const calls = []
  const fetch = async (url, options = {}) => {
    calls.push({ url, method: options.method ?? 'GET', auth: options.headers?.Authorization ?? '', apiKey: options.headers?.['x-api-key'] ?? '', version: options.headers?.['anthropic-version'] ?? '', token: options.headers?.['X-PockPock-Internal-Token'] ?? '', body: options.body ? JSON.parse(options.body) : null })
    const route = routes(url, options)
    if (route === 'network') throw new TypeError('fetch failed')
    // A server that never answers: the request ends only when the caller gives up.
    if (route === 'hang') return new Promise((resolve, reject) => options.signal.addEventListener('abort', () => reject(Object.assign(new Error('aborted'), { name: 'AbortError' }))))
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

const openaiRoutes = (url, options) => {
  if (url.includes('127.0.0.1:8766')) return { status: 200, json: { ok: true } }
  if (url === 'https://api.openai.com/v1/models') return options.headers.Authorization === 'Bearer sk-good' ? { status: 200, json: OPENAI_MODELS } : { status: 401, json: { error: { message: 'Incorrect API key provided' } } }
  return { status: 404, json: null }
}

const anthropicRoutes = (url, options) => {
  if (url.includes('127.0.0.1:8766')) return { status: 200, json: { ok: true } }
  if (url === 'https://api.anthropic.com/v1/models?limit=1000') {
    if (options.headers['anthropic-version'] !== '2023-06-01') return { status: 400, json: null }
    return options.headers['x-api-key'] === 'sk-ant-good' ? { status: 200, json: ANTHROPIC_MODELS } : { status: 401, json: { type: 'error', error: { type: 'authentication_error' } } }
  }
  return { status: 404, json: null }
}

test('model lists keep chat models only and read their details', () => {
  const openai = normalizeModels(OPENAI_MODELS, 'openai')
  assert.deepEqual(openai.map((model) => model.id), ['gpt-4.1', 'gpt-5-mini', 'gpt-5.1'])
  assert.deepEqual(openai[2], { id: 'gpt-5.1', name: 'gpt-5.1', contextWindow: null, tools: null, free: false, created: 1762000000 })
  const claude = normalizeModels(ANTHROPIC_MODELS, 'anthropic')
  assert.deepEqual(claude[1], { id: 'claude-opus-5-5', name: 'Claude Opus 5.5', contextWindow: 1000000, tools: null, free: false, created: Date.parse('2026-10-01T00:00:00Z') / 1000 })
  assert.deepEqual(normalizeModels({ data: [{ id: 'qwen-plus' }, { id: 'text-embedding-v4' }, { id: 'wan2.5-t2v' }] }).map((model) => model.id), ['qwen-plus'])
  assert.deepEqual(normalizeModels({ data: [{ id: 'meta/llama-3.3-70b-instruct', name: 'Llama' }, { id: 'black-forest-labs/flux-1', architecture: { output_modalities: ['image'] } }, { id: 'bad id' }] }).map((model) => model.id), ['meta/llama-3.3-70b-instruct'])
  assert.deepEqual(normalizeModels(null), [])
})

test('keys are trimmed and refused when empty or with spaces', () => {
  assert.equal(cleanKey('  nvapi-abc\n'), 'nvapi-abc')
  for (const bad of ['', '   ', 'two words', 'x'.repeat(401), null]) assert.throws(() => cleanKey(bad), /API key/)
})

test('OpenAI: connect checks the key, saves it encrypted and never lists it', async () => {
  const { dir, cloud, calls, changes, done } = setup(openaiRoutes)
  await assert.rejects(() => cloud.connect('openai', { key: 'sk-wrong' }), /OpenAI did not accept that API key/)
  assert.equal(cloud.list().find((item) => item.id === 'openai').connected, false)
  assert.equal(fs.existsSync(path.join(dir, 'cloud.json')), false, 'nothing is saved for a refused key')

  const result = await cloud.connect('openai', { key: ' sk-good ' })
  const listed = result.providers.find((item) => item.id === 'openai')
  assert.equal(listed.connected, true)
  assert.equal(listed.keyEnding, 'good')
  // Suggested models that the account really offers are switched on.
  assert.deepEqual(listed.models.map((model) => model.id), ['gpt-5.1', 'gpt-5-mini'])
  assert.deepEqual(result.offered.map((model) => model.id), ['gpt-4.1', 'gpt-5-mini', 'gpt-5.1'])
  assert.ok(result.offered.every((model) => !('created' in model)))
  const onDisk = fs.readFileSync(path.join(dir, 'cloud.json'), 'utf8')
  assert.ok(!onDisk.includes('sk-good'), 'the key is not stored in plain text')
  assert.ok(!JSON.stringify(result).includes('sk-good'), 'the key is not returned to the page')
  assert.equal(changes(), 1)
  // One model-list call checks the key and lists the models.
  assert.equal(calls.filter((call) => call.url.startsWith('https://api.openai.com/')).length, 2)

  // The gateway gets the key over the internal call only.
  const push = calls.find((call) => call.url.endsWith('/api/cloud/config'))
  assert.equal(push.token, 'internal')
  assert.equal(push.body.providers[0].api_key, 'sk-good')
  assert.equal(push.body.providers[0].base_url, 'https://api.openai.com/v1')
  assert.deepEqual(push.body.providers[0].models[0], { id: 'gpt-5.1', context_window: null })
  assert.ok(push.body.proxy_token.length >= 32)
  assert.equal(cloud.pushed, true)
  // No request other than the provider's own address and the local gateway.
  assert.ok(calls.every((call) => call.url.startsWith('https://api.openai.com/v1/') || call.url.startsWith('http://127.0.0.1:8766/')))
  done()
})

test('Claude: the key goes in x-api-key with anthropic-version, and the current models are suggested', async () => {
  const { cloud, calls, done } = setup(anthropicRoutes)
  await assert.rejects(() => cloud.connect('anthropic', { key: 'sk-ant-wrong' }), /Claude \(Anthropic\) did not accept that API key/)
  const result = await cloud.connect('anthropic', { key: 'sk-ant-good' })
  const listed = result.providers.find((item) => item.id === 'anthropic')
  assert.deepEqual(listed.models, [
    { id: 'claude-opus-5-5', name: 'Claude Opus 5.5', contextWindow: 1000000 },
    { id: 'claude-sonnet-5-5', name: 'Claude Sonnet 5.5', contextWindow: 1000000 },
  ])
  const providerCalls = calls.filter((call) => call.url.startsWith('https://api.anthropic.com/'))
  assert.ok(providerCalls.every((call) => call.apiKey && call.version === '2023-06-01' && !call.auth), 'the Bearer header is not used for the model list')
  assert.deepEqual((await cloud.available('anthropic')).map((model) => model.id), ['claude-haiku-4-5', 'claude-opus-5-5', 'claude-sonnet-5-5'])
  // The gateway reaches Claude through Anthropic's OpenAI-compatible endpoint.
  assert.equal(cloud.gatewayConfig().providers[0].base_url, 'https://api.anthropic.com/v1')
  done()
})

test('when none of the suggested models is offered, the newest ones are switched on', async () => {
  const renamed = { data: [{ id: 'gpt-7', created: 1800000000 }, { id: 'gpt-6.5', created: 1790000000 }, { id: 'gpt-6', created: 1780000000 }, { id: 'gpt-4.1', created: 1744000000 }, { id: 'tts-2', created: 1800000001 }] }
  const { cloud, done } = setup((url, options) => (url.includes('127.0.0.1') ? { status: 200, json: {} } : options.headers.Authorization === 'Bearer sk-good' ? { status: 200, json: renamed } : { status: 401, json: null }))
  const result = await cloud.connect('openai', { key: 'sk-good' })
  assert.deepEqual(result.providers.find((item) => item.id === 'openai').models.map((model) => model.id), ['gpt-7', 'gpt-6.5', 'gpt-6'])
  done()
})

test('choosing models, reconnecting and disconnecting', async () => {
  const { cloud, done } = setup(openaiRoutes)
  await assert.rejects(() => cloud.setModels('openai', []), /Connect this provider first/)
  await cloud.connect('openai', { key: 'sk-good' })
  const offered = await cloud.available('openai')
  await cloud.setModels('openai', [offered[0], offered[0], { id: 'bad id' }])
  assert.deepEqual(cloud.chosenModels(), [{ name: 'openai/gpt-4.1', label: 'gpt-4.1', provider: 'openai', contextWindow: null }])
  await assert.rejects(() => cloud.setModels('openai', Array.from({ length: 41 }, (_, index) => ({ id: `m/${index}` }))), /at most 40/)
  // A new key keeps the earlier choice.
  const again = await cloud.connect('openai', { key: 'sk-good' })
  assert.deepEqual(again.providers.find((item) => item.id === 'openai').models.map((model) => model.id), ['gpt-4.1'])
  const after = await cloud.disconnect('openai')
  assert.equal(after.find((item) => item.id === 'openai').connected, false)
  assert.deepEqual(cloud.chosenModels(), [])
  assert.deepEqual(cloud.gatewayConfig().providers, [])
  await assert.rejects(() => cloud.connect('other', { key: 'x' }), /Unknown cloud provider/)
  await assert.rejects(() => cloud.connect('openrouter', { key: 'sk-or-x' }), /Unknown cloud provider/)
  done()
})

test('a saved OpenRouter key from 0.2.8 or earlier is deleted at start', async () => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'cloud-'))
  const old = { proxyToken: 'p'.repeat(40), providers: { openrouter: { key: crypt.encrypt('sk-or-old').toString('base64'), keyEnding: '-old', region: 'default', models: [{ id: 'qwen/qwen3-coder' }] }, nim: { key: crypt.encrypt('nvapi-x').toString('base64'), region: 'default', models: [] } } }
  fs.writeFileSync(path.join(dir, 'cloud.json'), JSON.stringify(old))
  const cloud = new Cloud({ userData: dir, crypt, fetch: fakeFetch(openaiRoutes).fetch, internalToken: () => 'i' })
  const onDisk = JSON.parse(fs.readFileSync(path.join(dir, 'cloud.json'), 'utf8'))
  assert.deepEqual(Object.keys(onDisk.providers), ['nim'])
  assert.equal(onDisk.proxyToken, old.proxyToken)
  assert.deepEqual(cloud.list().map((item) => item.id), ['nim', 'openai', 'anthropic', 'alibaba'])
  fs.rmSync(dir, { recursive: true, force: true })
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
    return { status: 200, json: { data: [{ id: 'aaa/retired-mini' }, { id: 'nvidia/nemotron-3-ultra-550b-a55b' }, { id: 'nvidia/nv-embedqa-e5-v5' }, { id: 'nvidia/nvclip' }] } }
  })
  await assert.rejects(() => nim.cloud.connect('nim', { key: 'nvapi-bad' }), /did not accept/)
  const result = await nim.cloud.connect('nim', { key: 'nvapi-good' })
  assert.deepEqual(result.providers.find((item) => item.id === 'nim').models.map((model) => model.id), ['nvidia/nemotron-3-ultra-550b-a55b'])
  assert.deepEqual(result.offered.map((model) => model.id), ['aaa/retired-mini', 'nvidia/nemotron-3-ultra-550b-a55b'])
  const checks = nim.calls.filter((call) => call.url.endsWith('/chat/completions') && call.auth === 'Bearer nvapi-good')
  assert.deepEqual(checks.map((call) => [call.body.model, call.body.max_tokens]), [['aaa/retired-mini', 1], ['nvidia/nemotron-3-ultra-550b-a55b', 1]])
  nim.done()
  const gone = setup((url) => (url.includes('127.0.0.1') ? { status: 200, json: {} } : url.endsWith('/models') ? { status: 200, json: { data: [{ id: 'aaa/retired-mini' }] } } : { status: 410, json: null }))
  await assert.rejects(() => gone.cloud.connect('nim', { key: 'nvapi-good' }), /could not check the key right now/)
  gone.done()
})

test('NVIDIA: a model that never answers does not fail a good key; a wrong key is refused', async () => {
  // Measured 2026-11-22: models this account cannot use answer 404 "Not found for account", one model
  // hung, and a wrong key gets 403 from any listed model.
  const list = { status: 200, json: { data: [{ id: 'aaa/hangs-flash' }, { id: 'bbb/not-for-you-mini' }, { id: 'ccc/broken-8b' }] } }
  const routes = (good) => (url, options) => {
    if (url.includes('127.0.0.1')) return { status: 200, json: {} }
    if (!url.endsWith('/chat/completions')) return list
    if (options.headers.Authorization !== `Bearer ${good}`) return { status: 403, json: { detail: 'Authorization failed' } }
    const model = JSON.parse(options.body).model
    if (model === 'aaa/hangs-flash') return 'hang'
    if (model === 'bbb/not-for-you-mini') return { status: 404, json: { detail: "Function 'x': Not found for account 'y'" } }
    return { status: 500, json: { error: 'inference failed' } }
  }
  const nim = setup(routes('nvapi-good'))
  nim.cloud.nimCheckTimeoutMs = 300
  const started = Date.now()
  const result = await nim.cloud.connect('nim', { key: 'nvapi-good' })
  assert.equal(result.providers.find((item) => item.id === 'nim').connected, true)
  assert.ok(Date.now() - started < 300, 'decided without waiting for the model that hangs')
  await assert.rejects(() => nim.cloud.connect('nim', { key: 'nvapi-bad' }), /did not accept/)
  nim.done()
  const silent = setup((url) => (url.includes('127.0.0.1') ? { status: 200, json: {} } : url.endsWith('/models') ? list : 'hang'))
  silent.cloud.nimCheckTimeoutMs = 100
  await assert.rejects(() => silent.cloud.connect('nim', { key: 'nvapi-good' }), /did not answer in time/)
  silent.done()
})

test('a provider that cannot be reached, and a key that cannot be protected', async () => {
  const offline = setup(() => 'network')
  await assert.rejects(() => offline.cloud.connect('openai', { key: 'sk-good' }), /could not be reached/)
  offline.done()
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'cloud-'))
  const unsafe = new Cloud({ userData: dir, crypt: { ...crypt, available: () => false }, fetch: fakeFetch(openaiRoutes).fetch, internalToken: () => 'i' })
  await assert.rejects(() => unsafe.connect('openai', { key: 'sk-good' }), /cannot protect saved keys/)
  fs.rmSync(dir, { recursive: true, force: true })
})

test('a key that can no longer be decrypted asks for the key again', async () => {
  const { dir, cloud, done } = setup(openaiRoutes)
  await cloud.connect('openai', { key: 'sk-good' })
  const moved = new Cloud({ userData: dir, crypt: { ...crypt, decrypt: () => { throw new Error('wrong machine') } }, fetch: fakeFetch(openaiRoutes).fetch, internalToken: () => 'i' })
  const listed = moved.list().find((item) => item.id === 'openai')
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
