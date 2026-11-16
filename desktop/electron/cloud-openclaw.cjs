// Makes the chosen cloud models available to OpenClaw as one provider, "pockpock-cloud", whose
// address is the PockPock gateway's local cloud endpoint. Its "API key" is PockPock's local token:
// the real cloud keys never enter OpenClaw's configuration file.
const PROVIDER = 'pockpock-cloud'
const BASE_URL = 'http://127.0.0.1:8766/cloud/v1'
const KEY = `models.providers.${PROVIDER}`

/** The provider entry for openclaw.json, or null when there are no cloud models. */
function openclawProvider(models, proxyToken) {
  if (!Array.isArray(models) || !models.length || !proxyToken) return null
  return {
    baseUrl: BASE_URL,
    api: 'openai-completions',
    apiKey: proxyToken,
    models: models.map((model) => ({
      id: model.name, // "<provider>/<model id>", as the gateway's endpoint expects it
      name: model.label && model.label !== model.name ? `${model.label} (${model.provider})` : model.name,
      reasoning: false,
      input: ['text'],
      // The provider bills the user's own account; OpenClaw's cost display has no price to show.
      cost: { input: 0, output: 0, cacheRead: 0, cacheWrite: 0 },
      contextWindow: model.contextWindow || 128000,
      maxTokens: 8192,
      compat: { supportsTools: true },
    })),
  }
}

/**
 * Writes or removes the provider with `openclaw config`. `cli(args)` runs the OpenClaw command line
 * and resolves { ok, stdout, stderr }. Returns what happened: 'set', 'removed' or 'unchanged'.
 */
async function syncOpenClaw(cli, models, proxyToken) {
  const provider = openclawProvider(models, proxyToken)
  const current = await cli(['config', 'get', KEY, '--json'])
  let existing = null
  try { const parsed = JSON.parse(String(current.stdout).trim().split('\n').pop()); existing = parsed && parsed.baseUrl ? parsed : null } catch { existing = null }
  if (!provider) {
    if (!existing) return 'unchanged'
    const removed = await cli(['config', 'unset', KEY])
    if (!removed.ok) throw new Error(lastLine(removed) || 'OpenClaw did not remove the cloud models.')
    return 'removed'
  }
  // OpenClaw may show the saved key masked, so the key itself is not compared.
  const same = existing && existing.baseUrl === provider.baseUrl && JSON.stringify((existing.models ?? []).map((model) => [model.id, model.contextWindow])) === JSON.stringify(provider.models.map((model) => [model.id, model.contextWindow]))
  if (same) return 'unchanged'
  const result = await cli(['config', 'set', KEY, JSON.stringify(provider), '--strict-json'])
  if (!result.ok) throw new Error(lastLine(result) || 'OpenClaw did not accept the cloud models.')
  return 'set'
}

function lastLine(result) {
  return String(result.stderr || result.stdout || '').trim().split('\n').slice(-2).join(' ').slice(0, 300)
}

module.exports = { PROVIDER, BASE_URL, openclawProvider, syncOpenClaw }
