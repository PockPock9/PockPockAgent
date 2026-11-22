// Cloud model providers (NVIDIA NIM, OpenRouter, Alibaba Cloud Model Studio).
//
// The user connects a provider with an API key and chooses which of its models to show in the model
// pickers. Keys are encrypted with the operating system's credential protection (Electron
// safeStorage) in <userData>/cloud.json and are never sent to the renderer. The gateway receives the
// connected providers over an internal, token-protected call and keeps them in memory; OpenClaw and
// NemoClaw reach cloud models only through the gateway's local endpoint, so keys are not written
// into their configuration.
const fs = require('node:fs')
const path = require('node:path')
const crypto = require('node:crypto')

// The gateway the app talks to (POCKPOCK_BACKEND_URL, as in main.cjs); :8766 by default.
const GATEWAY = (process.env.POCKPOCK_BACKEND_URL || 'http://127.0.0.1:8766').replace(/\/$/, '')
const MAX_CHOSEN = 40

/** Every address is fixed here; nothing a user or a page types becomes a URL. */
const PROVIDERS = {
  nim: {
    name: 'NVIDIA NIM',
    about: 'Models hosted by NVIDIA at build.nvidia.com, including open models such as Llama, Qwen and DeepSeek.',
    keyUrl: 'https://build.nvidia.com/settings/api-keys',
    keyHint: 'Starts with nvapi-',
    regions: { default: { name: 'Global', baseUrl: 'https://integrate.api.nvidia.com/v1' } },
    modelsNeedKey: false,
    // Checked against the live list on 2026-11-16. Ids that are no longer offered are skipped on connect.
    suggested: ['deepseek-ai/deepseek-v4.1-flash', 'openai/gpt-oss-20b', 'mistralai/mistral-large-4-1t-a52b', 'nvidia/nemotron-3-ultra-550b-a55b', 'z-ai/glm-5.3-flash'],
  },
  openrouter: {
    name: 'OpenRouter',
    about: 'One account for models from many companies (Anthropic, OpenAI, Google, Qwen, DeepSeek and others), including some free ones.',
    keyUrl: 'https://openrouter.ai/settings/keys',
    keyHint: 'Starts with sk-or-',
    regions: { default: { name: 'Global', baseUrl: 'https://openrouter.ai/api/v1' } },
    modelsNeedKey: false,
    suggested: ['anthropic/claude-sonnet-4.5', 'openai/gpt-5', 'google/gemini-2.5-pro', 'qwen/qwen3-coder', 'deepseek/deepseek-chat-v3.1'],
  },
  alibaba: {
    name: 'Alibaba Cloud Model Studio',
    about: 'Qwen and other models from Alibaba Cloud (DashScope). The key belongs to one region.',
    keyUrl: 'https://modelstudio.console.alibabacloud.com/?tab=model#/api-key',
    keyHint: 'Starts with sk-',
    regions: {
      intl: { name: 'International (Singapore)', baseUrl: 'https://dashscope-intl.aliyuncs.com/compatible-mode/v1' },
      us: { name: 'United States (Virginia)', baseUrl: 'https://dashscope-us.aliyuncs.com/compatible-mode/v1' },
      cn: { name: 'China (Beijing)', baseUrl: 'https://dashscope.aliyuncs.com/compatible-mode/v1' },
    },
    modelsNeedKey: true,
    suggested: ['qwen3-max', 'qwen-plus', 'qwen3-coder-plus', 'qwen-flash'],
  },
}
const PROVIDER_IDS = Object.keys(PROVIDERS)
const MODEL_ID = /^[A-Za-z0-9][A-Za-z0-9._:/-]{0,87}$/
// Models that cannot hold a chat (embeddings, images, speech and so on) are left out of the list.
const NOT_CHAT = /embed|rerank|whisper|tts|speech|audio|asr|ocr|image|video|diffusion|flux|sdxl|wan2|wanx|paraformer|cosyvoice|sambert|guard|safety|retriev|parse|translate-|nv-clip|nvclip|starcoder|calibration|cosmos|detector|vila|bge-|e5-|arctic-embed/i

function cleanKey(value) {
  const key = String(value ?? '').trim()
  if (!key || key.length > 400 || /\s/.test(key)) throw new Error('Paste the API key exactly as the provider shows it, without spaces.')
  return key
}

/** One provider's /models answer as { id, name, contextWindow, tools }, chat models only, sorted. */
function normalizeModels(payload) {
  const list = Array.isArray(payload?.data) ? payload.data : Array.isArray(payload) ? payload : []
  const seen = new Set()
  const models = []
  for (const item of list) {
    const id = typeof item === 'string' ? item : item?.id
    if (typeof id !== 'string' || !MODEL_ID.test(id) || NOT_CHAT.test(id) || seen.has(id)) continue
    const output = item?.architecture?.output_modalities
    if (Array.isArray(output) && !output.includes('text')) continue
    seen.add(id)
    const context = Number(item?.context_length ?? item?.context_window ?? item?.top_provider?.context_length)
    const parameters = item?.supported_parameters
    models.push({
      id,
      name: typeof item?.name === 'string' && item.name ? item.name.slice(0, 120) : id,
      contextWindow: Number.isInteger(context) && context > 0 ? context : null,
      tools: Array.isArray(parameters) ? parameters.includes('tools') : null,
      free: /:free$/.test(id) || (item?.pricing && Number(item.pricing.prompt) === 0 && Number(item.pricing.completion) === 0) || false,
    })
  }
  return models.sort((a, b) => a.id.localeCompare(b.id))
}

/** A short reason for a failed provider call, without any part of the key. */
function explainStatus(status, provider) {
  if (status === 401 || status === 403) return `${provider.name} did not accept that API key. Check that it was copied completely${Object.keys(provider.regions).length > 1 ? ' and that the region matches the key' : ''}.`
  if (status === 402) return `${provider.name} says the account has no credit.`
  if (status === 429) return `${provider.name} is limiting requests right now. Try again in a minute.`
  return `${provider.name} answered with an error (HTTP ${status}).`
}

class Cloud {
  /**
   * @param {{ userData: string, crypt: { available: () => boolean, encrypt: (text: string) => Buffer, decrypt: (data: Buffer) => string },
   *   fetch?: typeof fetch, internalToken: () => string, onChange?: () => void }} options
   */
  constructor({ userData, crypt, fetch: fetchImpl, internalToken, onChange }) {
    this.file = path.join(userData, 'cloud.json')
    this.crypt = crypt
    this.fetch = fetchImpl ?? globalThis.fetch
    this.internalToken = internalToken
    this.onChange = onChange ?? (() => {})
    this.pushed = false
  }

  read() {
    try { const parsed = JSON.parse(fs.readFileSync(this.file, 'utf8')); return parsed && typeof parsed === 'object' ? parsed : {} } catch { return {} }
  }

  write(config) {
    const temp = `${this.file}.tmp`
    fs.writeFileSync(temp, JSON.stringify(config, null, 2), { encoding: 'utf8', mode: 0o600 })
    fs.renameSync(temp, this.file)
  }

  /** The token OpenClaw and NemoClaw use for the gateway's local cloud endpoint. Not a cloud key. */
  proxyToken() {
    const config = this.read()
    if (typeof config.proxyToken === 'string' && config.proxyToken.length >= 32) return config.proxyToken
    const proxyToken = crypto.randomBytes(32).toString('base64url')
    this.write({ ...config, proxyToken })
    return proxyToken
  }

  key(id) {
    const stored = this.read().providers?.[id]?.key
    if (!stored) return ''
    try { return this.crypt.decrypt(Buffer.from(stored, 'base64')) } catch { return '' }
  }

  baseUrl(id, region) {
    const regions = PROVIDERS[id].regions
    return (regions[region] ?? regions[Object.keys(regions)[0]]).baseUrl
  }

  /** What the Cloud page shows. Never includes a key. */
  list() {
    const saved = this.read().providers ?? {}
    return PROVIDER_IDS.map((id) => {
      const provider = PROVIDERS[id]
      const entry = saved[id]
      const connected = Boolean(entry?.key) && Boolean(this.key(id))
      return {
        id, name: provider.name, about: provider.about, keyUrl: provider.keyUrl, keyHint: provider.keyHint,
        regions: Object.entries(provider.regions).map(([key, value]) => ({ id: key, name: value.name })),
        connected,
        // A saved key that can no longer be decrypted (for example after moving the files to another PC).
        needsKey: Boolean(entry?.key) && !connected,
        region: entry?.region ?? Object.keys(provider.regions)[0],
        keyEnding: connected ? String(entry.keyEnding ?? '') : '',
        connectedAt: connected ? entry.connectedAt : null,
        models: connected && Array.isArray(entry.models) ? entry.models : [],
      }
    })
  }

  async request(url, { key, method = 'GET', body, timeoutMs = 20000 } = {}) {
    const controller = new AbortController()
    const timer = setTimeout(() => controller.abort(), timeoutMs)
    try {
      const response = await this.fetch(url, {
        method, signal: controller.signal, redirect: 'error',
        headers: { Accept: 'application/json', ...(key ? { Authorization: `Bearer ${key}` } : {}), ...(body ? { 'Content-Type': 'application/json' } : {}) },
        body: body ? JSON.stringify(body) : undefined,
      })
      let json = null
      try { json = await response.json() } catch { /* not JSON */ }
      return { status: response.status, json }
    } catch (error) {
      return { status: 0, json: null, error: error?.name === 'AbortError' ? 'timeout' : 'network' }
    } finally { clearTimeout(timer) }
  }

  /** Is the key accepted? Each provider has one cheap call that needs a valid key. */
  async verify(id, key, baseUrl) {
    const provider = PROVIDERS[id]
    let reply
    if (id === 'openrouter') reply = await this.request(`${baseUrl}/key`, { key })
    else if (id === 'alibaba') reply = await this.request(`${baseUrl}/models`, { key })
    else reply = await this.verifyNim(key, baseUrl)
    if (reply.status === 0) throw new Error(`${provider.name} could not be reached (${reply.error === 'timeout' ? 'it did not answer in time' : 'check the internet connection'}).`)
    if ([401, 402, 403].includes(reply.status)) throw new Error(explainStatus(reply.status, provider))
    // NVIDIA: any other answer (200, 400, 429) means the key was read and accepted.
    if (id !== 'nim' && reply.status >= 400) throw new Error(explainStatus(reply.status, provider))
    return reply
  }

  /**
   * NVIDIA lists models without a key, so the key is checked with a one-token reply from a model in
   * its current list. A model that is listed but not served answers 404 or 410 whatever the key is,
   * so a few small models are tried until one gives a real answer (403 for a bad key).
   */
  async verifyNim(key, baseUrl) {
    const listing = await this.request(`${baseUrl}/models`)
    if (listing.status === 0) return listing
    const offered = normalizeModels(listing.json).map((model) => model.id)
    const small = offered.filter((modelId) => /flash|nano|bolt|mini|lite|-[1-9]b|20b/i.test(modelId))
    const candidates = [...new Set([...small, ...offered])].slice(0, 4)
    let reply = { status: 404, json: null }
    for (const model of candidates) {
      reply = await this.request(`${baseUrl}/chat/completions`, { key, method: 'POST', timeoutMs: 30000, body: { model, messages: [{ role: 'user', content: 'Hi' }], max_tokens: 1 } })
      if (reply.status !== 404 && reply.status !== 410) return reply
    }
    throw new Error('NVIDIA NIM could not check the key right now (none of its test models answered). Try again in a few minutes.')
  }

  /** All chat models the provider offers this account. */
  async available(id) {
    if (!PROVIDERS[id]) throw new Error('Unknown cloud provider.')
    const entry = this.read().providers?.[id]
    const key = this.key(id)
    if (!key) throw new Error('Connect this provider first.')
    const reply = await this.request(`${this.baseUrl(id, entry.region)}/models`, { key: PROVIDERS[id].modelsNeedKey || id === 'openrouter' ? key : undefined })
    if (reply.status === 0) throw new Error(`${PROVIDERS[id].name} could not be reached.`)
    if (reply.status >= 400) throw new Error(explainStatus(reply.status, PROVIDERS[id]))
    return normalizeModels(reply.json)
  }

  /** Checks the key, saves it encrypted, and switches on the suggested models that exist. */
  async connect(id, { key, region } = {}) {
    const provider = PROVIDERS[id]
    if (!provider) throw new Error('Unknown cloud provider.')
    if (!this.crypt.available()) throw new Error('This computer cannot protect saved keys right now, so the key was not saved.')
    const cleaned = cleanKey(key)
    const chosenRegion = provider.regions[region] ? region : Object.keys(provider.regions)[0]
    const baseUrl = provider.regions[chosenRegion].baseUrl
    await this.verify(id, cleaned, baseUrl)
    const listing = await this.request(`${baseUrl}/models`, { key: cleaned })
    const offered = listing.status === 200 ? normalizeModels(listing.json) : []
    const config = this.read()
    const earlier = Array.isArray(config.providers?.[id]?.models) ? config.providers[id].models : []
    // Reconnecting keeps the earlier choice; a first connection starts with the suggested models.
    const wanted = earlier.length ? earlier.map((model) => model.id) : provider.suggested
    const models = wanted.map((modelId) => offered.find((model) => model.id === modelId)).filter(Boolean).map(({ id: modelId, name, contextWindow }) => ({ id: modelId, name, contextWindow }))
    this.write({
      ...config,
      providers: { ...config.providers, [id]: { key: this.crypt.encrypt(cleaned).toString('base64'), keyEnding: cleaned.slice(-4), region: chosenRegion, models, connectedAt: new Date().toISOString() } },
    })
    await this.changed()
    return { providers: this.list(), offered }
  }

  /** Which models of a connected provider appear in the pickers. */
  async setModels(id, models) {
    const config = this.read()
    if (!PROVIDERS[id] || !config.providers?.[id]?.key) throw new Error('Connect this provider first.')
    if (!Array.isArray(models)) throw new Error('Choose models from the list.')
    const seen = new Set()
    const chosen = []
    for (const item of models) {
      const modelId = String(item?.id ?? '')
      if (!MODEL_ID.test(modelId) || seen.has(modelId)) continue
      seen.add(modelId)
      const context = Number(item?.contextWindow)
      chosen.push({ id: modelId, name: String(item?.name || modelId).slice(0, 120), contextWindow: Number.isInteger(context) && context > 0 ? context : null })
    }
    if (chosen.length > MAX_CHOSEN) throw new Error(`Choose at most ${MAX_CHOSEN} models per provider.`)
    this.write({ ...config, providers: { ...config.providers, [id]: { ...config.providers[id], models: chosen } } })
    await this.changed()
    return this.list()
  }

  /** Removes the saved key and the provider's models. */
  async disconnect(id) {
    if (!PROVIDERS[id]) throw new Error('Unknown cloud provider.')
    const config = this.read()
    const providers = { ...config.providers }
    delete providers[id]
    this.write({ ...config, providers })
    await this.changed()
    return this.list()
  }

  /** Every chosen model as the engines name it: "<provider>/<model id>". */
  chosenModels() {
    return this.list().filter((provider) => provider.connected).flatMap((provider) => provider.models.map((model) => ({ name: `${provider.id}/${model.id}`, label: model.name, provider: provider.id, contextWindow: model.contextWindow })))
  }

  /** The gateway's copy: providers, keys and chosen models. Sent over loopback with the internal token. */
  gatewayConfig() {
    const saved = this.read().providers ?? {}
    const providers = []
    for (const id of PROVIDER_IDS) {
      const key = this.key(id)
      if (!key) continue
      providers.push({ id, base_url: this.baseUrl(id, saved[id].region), api_key: key, models: (saved[id].models ?? []).map((model) => ({ id: model.id, context_window: model.contextWindow ?? null })) })
    }
    return { providers, proxy_token: this.proxyToken() }
  }

  /** Sends the configuration to the gateway. Returns false when the gateway is not up; it is sent again when it starts. */
  async push() {
    try {
      const response = await this.fetch(`${GATEWAY}/api/cloud/config`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json', 'X-PockPock-Internal-Token': this.internalToken() },
        body: JSON.stringify(this.gatewayConfig()),
        signal: AbortSignal.timeout(8000),
      })
      this.pushed = response.ok
    } catch { this.pushed = false }
    return this.pushed
  }

  async changed() {
    await this.push()
    this.onChange()
  }
}

module.exports = { Cloud, PROVIDERS, PROVIDER_IDS, normalizeModels, cleanKey, explainStatus }
