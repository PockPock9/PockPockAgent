// Cloud model providers (NVIDIA NIM, OpenAI, Claude by Anthropic, Alibaba Cloud Model Studio).
//
// The user connects a provider with an API key and chooses which of its models to show in the model
// pickers. Keys are encrypted with the operating system's credential protection (Electron
// safeStorage) in <userData>/cloud.json and are never sent to the renderer. The gateway receives the
// connected providers over an internal, token-protected call and keeps them in memory; OpenClaw
// reaches cloud models only through the gateway's local endpoint, so keys are not written into its
// configuration.
const fs = require('node:fs')
const path = require('node:path')
const crypto = require('node:crypto')

// The gateway the app talks to (POCKPOCK_BACKEND_URL, as in main.cjs); :8766 by default.
const GATEWAY = (process.env.POCKPOCK_BACKEND_URL || 'http://127.0.0.1:8766').replace(/\/$/, '')
const MAX_CHOSEN = 40
// Anthropic's own API (model list) wants these headers; chat goes through its OpenAI-compatible
// endpoint, which takes the same key as a Bearer token.
const ANTHROPIC_VERSION = '2023-06-01'

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
    // Models that answered a test call on 2026-11-22 (several listed models did not, or are not served).
    suggested: ['nvidia/nemotron-3-ultra-550b-a55b', 'nvidia/nemotron-3.5-lightning-30b-a3b', 'moonshotai/kimi-k3.1-pro', 'mistralai/mistral-large-4-1t-a52b'],
  },
  openai: {
    name: 'OpenAI',
    about: 'GPT models from OpenAI, with a key from your OpenAI API account (platform.openai.com). A ChatGPT subscription is a separate account and does not include API use.',
    keyUrl: 'https://platform.openai.com/api-keys',
    keyHint: 'Starts with sk-',
    regions: { default: { name: 'Global', baseUrl: 'https://api.openai.com/v1' } },
    modelsNeedKey: true,
    // Ids that this account is not offered are skipped; when none is offered, the newest GPT models are used.
    suggested: ['gpt-5.1', 'gpt-5', 'gpt-5-mini'],
    newestFallback: /^gpt-\d/,
  },
  anthropic: {
    name: 'Claude (Anthropic)',
    about: 'Claude models from Anthropic, with a key from the Claude Console (platform.claude.com). A Claude.ai subscription is a separate account and does not include API use.',
    keyUrl: 'https://platform.claude.com/settings/keys',
    keyHint: 'Starts with sk-ant-',
    regions: { default: { name: 'Global', baseUrl: 'https://api.anthropic.com/v1' } },
    modelsNeedKey: true,
    auth: 'anthropic',
    // The model list returns 20 models unless asked for more.
    modelsQuery: '?limit=1000',
    // Current models as of 2026-11-22 (Opus 5.5 is Anthropic's default; Sonnet 5.5 and Haiku 5.5 are faster and cheaper).
    suggested: ['claude-opus-5-5', 'claude-sonnet-5-5', 'claude-haiku-5-5'],
    newestFallback: /^claude-/,
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
// OpenAI lists every model of the account; these cannot be used through chat completions.
const NOT_OPENAI_CHAT = /moderation|realtime|transcribe|dall-e|sora|davinci|babbage|computer-use|deep-research|codex|search|-instruct|^gpt-image|^o\d+-pro|-pro(-\d|$)/i

function cleanKey(value) {
  const key = String(value ?? '').trim()
  if (!key || key.length > 400 || /\s/.test(key)) throw new Error('Paste the API key exactly as the provider shows it, without spaces.')
  return key
}

/** One provider's /models answer as { id, name, contextWindow, tools }, chat models only, sorted. */
function normalizeModels(payload, providerId = '') {
  const list = Array.isArray(payload?.data) ? payload.data : Array.isArray(payload) ? payload : []
  const seen = new Set()
  const models = []
  for (const item of list) {
    const id = typeof item === 'string' ? item : item?.id
    if (typeof id !== 'string' || !MODEL_ID.test(id) || NOT_CHAT.test(id) || seen.has(id)) continue
    if (providerId === 'openai' && NOT_OPENAI_CHAT.test(id)) continue
    const output = item?.architecture?.output_modalities
    if (Array.isArray(output) && !output.includes('text')) continue
    seen.add(id)
    // Anthropic: display_name and max_input_tokens (the context window).
    const context = Number(item?.context_length ?? item?.context_window ?? item?.max_input_tokens ?? item?.top_provider?.context_length)
    const parameters = item?.supported_parameters
    const label = [item?.name, item?.display_name].find((value) => typeof value === 'string' && value)
    const created = typeof item?.created === 'number' ? item.created : Date.parse(item?.created_at ?? '') / 1000
    models.push({
      id,
      name: label ? label.slice(0, 120) : id,
      contextWindow: Number.isInteger(context) && context > 0 ? context : null,
      tools: Array.isArray(parameters) ? parameters.includes('tools') : null,
      free: /:free$/.test(id) || (item?.pricing && Number(item.pricing.prompt) === 0 && Number(item.pricing.completion) === 0) || false,
      ...(Number.isFinite(created) ? { created } : {}),
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
    this.forgetRetired()
  }

  /** A provider PockPock no longer offers (OpenRouter, up to 0.2.8): its saved key and models are deleted. */
  forgetRetired() {
    const config = this.read()
    const saved = config.providers ?? {}
    const retired = Object.keys(saved).filter((id) => !PROVIDERS[id])
    if (!retired.length) return []
    const providers = Object.fromEntries(Object.entries(saved).filter(([id]) => PROVIDERS[id]))
    try { this.write({ ...config, providers }) } catch { /* tried again at the next start */ }
    return retired
  }

  read() {
    try { const parsed = JSON.parse(fs.readFileSync(this.file, 'utf8')); return parsed && typeof parsed === 'object' ? parsed : {} } catch { return {} }
  }

  write(config) {
    const temp = `${this.file}.tmp`
    fs.writeFileSync(temp, JSON.stringify(config, null, 2), { encoding: 'utf8', mode: 0o600 })
    fs.renameSync(temp, this.file)
  }

  /** The token OpenClaw uses for the gateway's local cloud endpoint. Not a cloud key. */
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

  /** How long each NVIDIA key-check request may take (the requests run together). */
  get nimCheckTimeoutMs() { return this._nimCheckTimeoutMs ?? 12000 }
  set nimCheckTimeoutMs(value) { this._nimCheckTimeoutMs = value }

  async request(url, { key, method = 'GET', body, timeoutMs = 20000, auth } = {}) {
    const controller = new AbortController()
    const timer = setTimeout(() => controller.abort(), timeoutMs)
    const keyHeaders = !key ? {} : auth === 'anthropic' ? { 'x-api-key': key, 'anthropic-version': ANTHROPIC_VERSION } : { Authorization: `Bearer ${key}` }
    try {
      const response = await this.fetch(url, {
        method, signal: controller.signal, redirect: 'error',
        headers: { Accept: 'application/json', ...keyHeaders, ...(body ? { 'Content-Type': 'application/json' } : {}) },
        body: body ? JSON.stringify(body) : undefined,
      })
      let json = null
      try { json = await response.json() } catch { /* not JSON */ }
      return { status: response.status, json }
    } catch (error) {
      return { status: 0, json: null, error: error?.name === 'AbortError' ? 'timeout' : 'network' }
    } finally { clearTimeout(timer) }
  }

  /** The provider's model list; OpenAI, Anthropic and Alibaba need the key for it. */
  listModels(id, baseUrl, key) {
    const provider = PROVIDERS[id]
    return this.request(`${baseUrl}/models${provider.modelsQuery ?? ''}`, { key: provider.modelsNeedKey ? key : undefined, auth: provider.auth })
  }

  /** Is the key accepted? Each provider has one cheap call that needs a valid key. */
  async verify(id, key, baseUrl) {
    const provider = PROVIDERS[id]
    // OpenAI, Anthropic and Alibaba answer the model list only for a valid key (401 otherwise).
    const reply = id === 'nim' ? await this.verifyNim(key, baseUrl) : await this.listModels(id, baseUrl, key)
    if (reply.status === 0) throw new Error(`${provider.name} could not be reached (${reply.error === 'timeout' ? 'it did not answer in time' : 'check the internet connection'}).`)
    if ([401, 402, 403].includes(reply.status)) throw new Error(explainStatus(reply.status, provider))
    // NVIDIA: any other answer (200, 400, 429) means the key was read and accepted.
    if (id !== 'nim' && reply.status >= 400) throw new Error(explainStatus(reply.status, provider))
    return reply
  }

  /**
   * NVIDIA lists models without a key, so the key is checked with one-token requests to a few models
   * in its current list, sent together; the first answer that says something about the key decides.
   * Measured 2026-11-22: a wrong or missing key is refused at once (401/403) by any listed model; an
   * accepted key gets a real answer, an error from the model (for example 500), or 404 "Not found for
   * account" for a model this account cannot use, which still means NVIDIA read the key. A 410, a
   * plain 404 and a timeout say nothing about the key: one listed model never answered within 30 s,
   * and waiting on it one model at a time made a good key fail with "did not answer in time".
   */
  async verifyNim(key, baseUrl) {
    const listing = await this.request(`${baseUrl}/models`)
    if (listing.status === 0) return listing
    const offered = normalizeModels(listing.json).map((model) => model.id)
    const small = offered.filter((modelId) => /flash|nano|bolt|mini|lite|-[1-9]b|20b/i.test(modelId))
    const candidates = [...new Set([...small, ...offered])].slice(0, 6)
    const decisive = (reply) => {
      if ([401, 402, 403].includes(reply.status)) return reply
      if (reply.status === 404 && /for account/i.test(JSON.stringify(reply.json ?? ''))) return { status: 200, json: null }
      if (reply.status === 0 || reply.status === 404 || reply.status === 410) return null
      return reply
    }
    const replies = []
    const decided = await new Promise((resolve) => {
      let waiting = candidates.length
      if (!waiting) resolve(null)
      for (const model of candidates) {
        void this.request(`${baseUrl}/chat/completions`, { key, method: 'POST', timeoutMs: this.nimCheckTimeoutMs, body: { model, messages: [{ role: 'user', content: 'Hi' }], max_tokens: 1 } }).then((reply) => {
          replies.push(reply)
          const answer = decisive(reply)
          if (answer) resolve(answer)
          else if (--waiting === 0) resolve(null)
        })
      }
    })
    if (decided) return decided
    if (replies.length && replies.every((reply) => reply.status === 0)) return { status: 0, json: null, error: replies.some((reply) => reply.error === 'timeout') ? 'timeout' : 'network' }
    throw new Error('NVIDIA NIM could not check the key right now (none of its test models answered). Try again in a few minutes.')
  }

  /** All chat models the provider offers this account. */
  async available(id) {
    if (!PROVIDERS[id]) throw new Error('Unknown cloud provider.')
    const entry = this.read().providers?.[id]
    const key = this.key(id)
    if (!key) throw new Error('Connect this provider first.')
    const reply = await this.listModels(id, this.baseUrl(id, entry.region), key)
    if (reply.status === 0) throw new Error(`${PROVIDERS[id].name} could not be reached.`)
    if (reply.status >= 400) throw new Error(explainStatus(reply.status, PROVIDERS[id]))
    return normalizeModels(reply.json, id).map(({ created, ...model }) => model)
  }

  /** Checks the key, saves it encrypted, and switches on the suggested models that exist. */
  async connect(id, { key, region } = {}) {
    const provider = PROVIDERS[id]
    if (!provider) throw new Error('Unknown cloud provider.')
    if (!this.crypt.available()) throw new Error('This computer cannot protect saved keys right now, so the key was not saved.')
    const cleaned = cleanKey(key)
    const chosenRegion = provider.regions[region] ? region : Object.keys(provider.regions)[0]
    const baseUrl = provider.regions[chosenRegion].baseUrl
    const checked = await this.verify(id, cleaned, baseUrl)
    const listing = id === 'nim' ? await this.listModels(id, baseUrl, cleaned) : checked
    const offered = listing.status === 200 ? normalizeModels(listing.json, id) : []
    const config = this.read()
    const earlier = Array.isArray(config.providers?.[id]?.models) ? config.providers[id].models : []
    // Reconnecting keeps the earlier choice; a first connection starts with the suggested models.
    const wanted = earlier.length ? earlier.map((model) => model.id) : provider.suggested
    let picked = wanted.map((modelId) => offered.find((model) => model.id === modelId)).filter(Boolean)
    // New model names appear often: when none of the suggested ones is offered, start with the newest three.
    if (!picked.length && !earlier.length && provider.newestFallback) {
      picked = offered.filter((model) => provider.newestFallback.test(model.id) && model.created).sort((a, b) => b.created - a.created).slice(0, 3)
    }
    const models = picked.map(({ id: modelId, name, contextWindow }) => ({ id: modelId, name, contextWindow }))
    const offeredForPage = offered.map(({ created, ...model }) => model)
    this.write({
      ...config,
      providers: { ...config.providers, [id]: { key: this.crypt.encrypt(cleaned).toString('base64'), keyEnding: cleaned.slice(-4), region: chosenRegion, models, connectedAt: new Date().toISOString() } },
    })
    await this.changed()
    return { providers: this.list(), offered: offeredForPage }
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

  /**
   * Removes the saved key and everything that used the provider's models: the gateway's copy (pushed),
   * and OpenClaw's pockpock-cloud provider (onChange rewrites it from the remaining models). The app's
   * own model choices are cleared by the page when it hears of the change (src/lib/cloudCleanup.ts).
   */
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
