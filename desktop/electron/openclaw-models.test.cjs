const test = require('node:test')
const assert = require('node:assert/strict')
const { ollamaEntry, mergeOllamaModels, syncOllamaModels } = require('./openclaw-models.cjs')

const SHOW_QWEN36 = { capabilities: ['completion', 'vision', 'tools', 'thinking'], model_info: { 'qwen35moe.context_length': 262144 } }
const SHOW_EMBED = { capabilities: ['embedding'], model_info: { 'nomic-bert.context_length': 2048 } }
const SHOW_PLAIN = { capabilities: ['completion'], model_info: { 'llama.context_length': 8192 } }

test('a new model gets its settings from Ollama', () => {
  const entry = ollamaEntry('qwen3.6:35b-a3b', SHOW_QWEN36)
  assert.equal(entry.id, 'qwen3.6:35b-a3b')
  assert.equal(entry.reasoning, true)
  assert.deepEqual(entry.input, ['text', 'image'])
  assert.equal(entry.compat.supportsTools, true)
  assert.equal(entry.contextWindow, 262144)
  assert.equal(entry.contextTokens, 65536, 'OpenClaw gets a 64K window, not the model maximum')
  assert.ok(entry.thinkingLevelMap)
  const plain = ollamaEntry('old:7b', SHOW_PLAIN)
  assert.equal(plain.compat.supportsTools, false, 'listed, but the menu hides models without tools')
  assert.equal(plain.contextTokens, 8192)
  assert.equal(ollamaEntry('nomic-embed-text', SHOW_EMBED), null, 'embedding models are not chat models')
})

test('the list follows Ollama: new models added, removed ones dropped, existing and default kept', () => {
  const tuned = { id: 'qwen3.5:9b', name: 'qwen3.5:9b', contextTokens: 65536, custom: true }
  const gone = { id: 'llama3.2:3b', name: 'llama3.2:3b' }
  const defaultGone = { id: 'qwen2.5:14b', name: 'qwen2.5:14b' }
  const result = mergeOllamaModels([tuned, gone, defaultGone], ['qwen3.6:35b-a3b', 'qwen3.5:9b', 'nomic-embed-text'], { 'qwen3.6:35b-a3b': SHOW_QWEN36, 'nomic-embed-text': SHOW_EMBED }, { keep: ['qwen2.5:14b'] })
  assert.deepEqual(result.models.map((entry) => entry.id), ['qwen3.6:35b-a3b', 'qwen3.5:9b', 'qwen2.5:14b'])
  assert.equal(result.models[1], tuned, 'an existing entry is kept as it is')
  assert.deepEqual(result.added, ['qwen3.6:35b-a3b'])
  assert.deepEqual(result.removed, ['llama3.2:3b'])
})

test('sync writes only when something changed, and nothing when Ollama is down', async () => {
  const calls = []
  let list = [{ id: 'qwen3.5:9b', name: 'qwen3.5:9b' }]
  const cli = async (args) => {
    calls.push(args)
    if (args[1] === 'get' && args[2] === 'models.providers.ollama.models') return { ok: true, stdout: `Config\n${JSON.stringify(list)}` }
    if (args[1] === 'get') return { ok: true, stdout: '"ollama/qwen3.5:9b"' }
    if (args[1] === 'set') { list = JSON.parse(args[3]); return { ok: true, stdout: '' } }
    return { ok: false, stdout: '' }
  }
  const tags = { models: [{ name: 'qwen3.6:35b-a3b' }, { name: 'qwen3.5:9b' }] }
  const ollama = async (path) => (path === '/api/tags' ? tags : SHOW_QWEN36)
  assert.deepEqual(await syncOllamaModels(cli, ollama), { changed: true, added: ['qwen3.6:35b-a3b'], removed: [] })
  assert.deepEqual(list.map((entry) => entry.id), ['qwen3.6:35b-a3b', 'qwen3.5:9b'])
  calls.length = 0
  assert.equal((await syncOllamaModels(cli, ollama)).changed, false)
  assert.ok(!calls.some((args) => args[1] === 'set'), 'an unchanged list is not written again')
  assert.deepEqual(await syncOllamaModels(cli, async () => null), { changed: false, added: [], removed: [] })
  // Removing an uninstalled model needs OpenClaw's --replace.
  list = [...list, { id: 'gone:7b', name: 'gone:7b' }]
  calls.length = 0
  assert.deepEqual((await syncOllamaModels(cli, ollama)).removed, ['gone:7b'])
  assert.ok(calls.find((args) => args[1] === 'set').includes('--replace'))
})
