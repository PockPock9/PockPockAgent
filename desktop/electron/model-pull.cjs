// Downloads the optional uncensored model for OpenClaw through Ollama (POST /api/pull), reporting
// progress. Only the names in PULLABLE can be downloaded from here, so the page cannot make the main
// process fetch arbitrary models. The model is a community "abliterated" build of Qwen 3.5 9B
// (its refusal behaviour removed); see docs/features/openclaw-agent.md, "Uncensored model".
const http = require('node:http')

const UNCENSORED_MODEL = 'huihui_ai/qwen3.5-abliterated:9b'
const PULLABLE = new Set([UNCENSORED_MODEL])

/**
 * @param {string} model
 * @param {(progress: { fraction?: number, detail: string }) => void} onProgress
 * @param {{ host?: string, port?: number }} [where] Ollama's address (tests use a stand-in)
 */
function pullModel(model, onProgress, { host = '127.0.0.1', port = 11434 } = {}) {
  if (!PULLABLE.has(model)) return Promise.reject(new Error('This model cannot be downloaded from here.'))
  return new Promise((resolve, reject) => {
    const request = http.request({ host, port, path: '/api/pull', method: 'POST', headers: { 'Content-Type': 'application/json' } }, (response) => {
      let buffer = ''
      let failed = response.statusCode && response.statusCode >= 400 ? `Ollama answered ${response.statusCode}` : ''
      response.on('data', (chunk) => {
        buffer += chunk.toString('utf8')
        const lines = buffer.split('\n')
        buffer = lines.pop() ?? ''
        for (const line of lines) {
          let event
          try { event = JSON.parse(line) } catch { continue }
          if (event.error) failed = String(event.error)
          else if (event.total && event.completed !== undefined) onProgress({ fraction: event.completed / event.total, detail: `${(event.completed / 1e9).toFixed(1)} of ${(event.total / 1e9).toFixed(1)} GB` })
          else if (event.status) onProgress({ detail: String(event.status) })
        }
      })
      response.on('end', () => (failed ? reject(new Error(`Downloading ${model} failed: ${failed}`)) : resolve()))
    })
    request.on('error', () => reject(new Error('Ollama is not running. Start it on the Services page, then try again.')))
    request.end(JSON.stringify({ model, stream: true }))
  })
}

module.exports = { UNCENSORED_MODEL, PULLABLE, pullModel }
