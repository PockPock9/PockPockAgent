// Connectors: external apps (GitHub, email, Telegram, ...) the agent can use as tools.
//
// The catalog and every call to an app live in the gateway (backend/projects/connectors). This
// module owns the credentials: a credential is checked by the gateway with the app itself, then
// encrypted with the operating system's credential protection (Electron safeStorage) and kept in
// <userData>/connectors.json. It never goes back to the renderer. The gateway gets the connected
// apps over an internal, token-protected call and holds them in memory only.
const fs = require('node:fs')
const path = require('node:path')
const crypto = require('node:crypto')

// The gateway the app talks to (POCKPOCK_BACKEND_URL, as in main.cjs); :8766 by default.
const GATEWAY = (process.env.POCKPOCK_BACKEND_URL || 'http://127.0.0.1:8766').replace(/\/$/, '')
const ID = /^[a-z][a-z0-9_-]{0,39}$/

class Connectors {
  /**
   * @param {{ userData: string, crypt: { available: () => boolean, encrypt: (text: string) => Buffer, decrypt: (data: Buffer) => string },
   *   fetch?: typeof fetch, internalToken: () => string, onChange?: () => void }} options
   */
  constructor({ userData, crypt, fetch: fetchImpl, internalToken, onChange }) {
    this.file = path.join(userData, 'connectors.json')
    this.crypt = crypt
    this.fetchImpl = fetchImpl
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

  /** The token an agent uses for the gateway's connector tools. Not an app credential. */
  toolToken() {
    const config = this.read()
    if (typeof config.toolToken === 'string' && config.toolToken.length >= 32) return config.toolToken
    const toolToken = crypto.randomBytes(32).toString('base64url')
    this.write({ ...config, toolToken })
    return toolToken
  }

  /** The saved credentials of one app, or null when there are none or they cannot be decrypted. */
  credentials(id) {
    const stored = this.read().connected?.[id]?.secret
    if (!stored) return null
    try { const parsed = JSON.parse(this.crypt.decrypt(Buffer.from(stored, 'base64'))); return parsed && typeof parsed === 'object' ? parsed : null } catch { return null }
  }

  async gateway(pathname, { method = 'GET', body, timeoutMs = 45000 } = {}) {
    let response
    try {
      response = await (this.fetchImpl ?? globalThis.fetch)(`${GATEWAY}${pathname}`, {
        method, signal: AbortSignal.timeout(timeoutMs),
        headers: { Accept: 'application/json', 'X-PockPock-Internal-Token': this.internalToken(), ...(body ? { 'Content-Type': 'application/json' } : {}) },
        body: body ? JSON.stringify(body) : undefined,
      })
    } catch { throw new Error('The PockPock backend is not running. Start it on the Services page, then try again.') }
    let json = null
    try { json = await response.json() } catch { /* not JSON */ }
    if (!response.ok) throw new Error(typeof json?.detail === 'string' ? json.detail : response.status === 404 ? 'The running PockPock backend is older than this app and has no connectors yet. Restart PockPock.' : `The PockPock backend answered with an error (HTTP ${response.status}).`)
    return json
  }

  /** The catalog with this computer's connections. Never includes a credential. */
  async list() {
    const catalog = (await this.gateway('/api/connectors', { timeoutMs: 8000 }))?.connectors
    if (!Array.isArray(catalog)) throw new Error('The PockPock backend did not list the connectors.')
    const saved = this.read().connected ?? {}
    return catalog.map((connector) => {
      const entry = saved[connector.id]
      const readable = Boolean(entry) && this.credentials(connector.id) !== null
      return {
        ...connector,
        connected: readable,
        // Saved, but no longer decryptable (for example after the files moved to another computer).
        needsReconnect: Boolean(entry) && !readable,
        account: readable ? String(entry.account ?? '') : '',
        connectedAt: readable ? entry.connectedAt ?? null : null,
      }
    })
  }

  /** Checks the credential with the app, saves it encrypted, and gives the tools to the agent. */
  async connect(id, values) {
    if (typeof id !== 'string' || !ID.test(id)) throw new Error('Unknown connector.')
    if (!this.crypt.available()) throw new Error('This computer cannot protect saved credentials right now, so nothing was saved.')
    const input = {}
    for (const [key, value] of Object.entries(values && typeof values === 'object' ? values : {})) {
      if (/^[a-z_]{1,30}$/.test(key) && typeof value === 'string') input[key] = value.slice(0, 500)
    }
    const verified = await this.gateway('/api/connectors/verify', { method: 'POST', body: { id, credentials: input } })
    if (!verified || typeof verified.account !== 'string' || !verified.credentials) throw new Error('The PockPock backend did not confirm the connection.')
    const config = this.read()
    this.write({
      ...config,
      connected: { ...config.connected, [id]: { secret: this.crypt.encrypt(JSON.stringify(verified.credentials)).toString('base64'), account: verified.account.slice(0, 120), connectedAt: new Date().toISOString() } },
    })
    await this.changed()
    return this.list()
  }

  /** Deletes the saved credential and takes the app's tools away from the agent. */
  async disconnect(id) {
    if (typeof id !== 'string' || !ID.test(id)) throw new Error('Unknown connector.')
    const config = this.read()
    const connected = { ...config.connected }
    delete connected[id]
    this.write({ ...config, connected })
    await this.changed()
    return this.list()
  }

  count() {
    return Object.keys(this.read().connected ?? {}).filter((id) => this.credentials(id) !== null).length
  }

  /** The gateway's copy: every readable connection with its credentials, and the tool token. */
  gatewayConfig() {
    const saved = this.read().connected ?? {}
    const connected = []
    for (const [id, entry] of Object.entries(saved)) {
      const credentials = this.credentials(id)
      if (credentials) connected.push({ id, account: String(entry.account ?? ''), credentials })
    }
    return { connected, tool_token: this.toolToken() }
  }

  /** Sends the connections to the gateway. Returns false when it is not up; they are sent again when it starts. */
  async push() {
    try { await this.gateway('/api/connectors/config', { method: 'PUT', body: this.gatewayConfig(), timeoutMs: 8000 }); this.pushed = true } catch { this.pushed = false }
    return this.pushed
  }

  async changed() {
    await this.push()
    this.onChange()
  }
}

module.exports = { Connectors }
