// Keeps OpenClaw's own list of Ollama models (models.providers.ollama.models in openclaw.json) in step
// with the models installed in Ollama. OpenClaw writes that list once, when it is set up, so a model
// pulled later (for example qwen3.6:35b-a3b) never appeared in the OpenClaw model menu, and removed
// models stayed in it. Existing entries keep their settings (context size, thinking levels); new ones
// get theirs from Ollama's /api/show; the default model's entry is never removed.
const KEY = 'models.providers.ollama.models'
// OpenClaw's own prompt is about 21K tokens, so a model needs a 64K window to work well (setup.cjs).
const CONTEXT_TOKENS = 65536
const THINKING_LEVELS = { off: 'false', minimal: null, low: 'true', medium: 'true', high: 'true', xhigh: null, max: 'true' }

/** The context length Ollama reports for a model ("<arch>.context_length"), or 0. */
function contextLength(show) {
  const info = show?.model_info && typeof show.model_info === 'object' ? show.model_info : {}
  const key = Object.keys(info).find((name) => name.endsWith('.context_length'))
  const value = key ? Number(info[key]) : 0
  return Number.isFinite(value) && value > 0 ? value : 0
}

/** A new OpenClaw entry for an installed model, from its /api/show reply; null for non-chat models. */
function ollamaEntry(name, show) {
  const caps = Array.isArray(show?.capabilities) ? show.capabilities : []
  if (!caps.includes('completion')) return null // embedding models cannot chat
  const window = contextLength(show) || 32768
  const reasoning = caps.includes('thinking')
  return {
    id: name,
    name,
    reasoning,
    input: caps.includes('vision') ? ['text', 'image'] : ['text'],
    cost: { input: 0, output: 0, cacheRead: 0, cacheWrite: 0 },
    contextWindow: window,
    maxTokens: 16384,
    ...(reasoning ? { thinkingLevelMap: { ...THINKING_LEVELS } } : {}),
    compat: { supportsTools: caps.includes('tools'), supportsUsageInStreaming: true, supportsJsonSchemaResponseFormat: true },
    contextTokens: Math.min(CONTEXT_TOKENS, window),
  }
}

/**
 * The new list: entries for installed models (existing ones unchanged, new ones from `shows`), in
 * Ollama's order, plus the entries named in `keep` (the default model) even when not installed.
 * `shows` maps a model name to its /api/show reply. Returns { models, added, removed }.
 */
function mergeOllamaModels(existing, installed, shows, { keep = [] } = {}) {
  const current = Array.isArray(existing) ? existing.filter((entry) => entry && typeof entry.id === 'string') : []
  const byId = new Map(current.map((entry) => [entry.id, entry]))
  const models = []
  const added = []
  for (const name of installed) {
    if (byId.has(name)) { models.push(byId.get(name)); continue }
    const entry = ollamaEntry(name, shows[name])
    if (entry) { models.push(entry); added.push(name) }
  }
  for (const entry of current) if (!installed.includes(entry.id) && keep.includes(entry.id)) models.push(entry)
  const removed = current.filter((entry) => !models.includes(entry)).map((entry) => entry.id)
  return { models, added, removed }
}

/**
 * Reads Ollama's models and OpenClaw's list, and writes the list when it changed. `cli(args)` runs the
 * OpenClaw command line ({ ok, stdout, stderr }); `ollama(path, body)` calls Ollama's API and resolves
 * the parsed JSON or null. Returns { changed, added, removed }; nothing is written when Ollama is down.
 */
async function syncOllamaModels(cli, ollama) {
  const tags = await ollama('/api/tags')
  if (!Array.isArray(tags?.models)) return { changed: false, added: [], removed: [] }
  const installed = tags.models.map((model) => model.name).filter((name) => typeof name === 'string')
  const listed = await cli(['config', 'get', KEY, '--json'])
  let existing = []
  try { existing = JSON.parse(String(listed.stdout).slice(String(listed.stdout).indexOf('['))) } catch { existing = [] }
  const primary = await cli(['config', 'get', 'agents.defaults.model.primary', '--json'])
  let keep = []
  try { keep = [String(JSON.parse(String(primary.stdout).trim().split('\n').pop())).replace(/^ollama\//, '')] } catch { keep = [] }
  const known = new Set((Array.isArray(existing) ? existing : []).map((entry) => entry?.id))
  const shows = {}
  for (const name of installed) if (!known.has(name)) shows[name] = await ollama('/api/show', { model: name })
  const { models, added, removed } = mergeOllamaModels(existing, installed, shows, { keep })
  if (!added.length && !removed.length) return { changed: false, added, removed }
  // OpenClaw refuses to drop entries without --replace; dropping uninstalled models is the point here.
  const result = await cli(['config', 'set', KEY, JSON.stringify(models), '--strict-json', ...(removed.length ? ['--replace'] : [])])
  if (!result.ok) throw new Error(String(result.stderr || result.stdout || '').trim().split('\n').pop() || 'OpenClaw did not accept the model list.')
  return { changed: true, added, removed }
}

module.exports = { KEY, CONTEXT_TOKENS, contextLength, ollamaEntry, mergeOllamaModels, syncOllamaModels }
