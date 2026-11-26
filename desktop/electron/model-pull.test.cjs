const test = require('node:test')
const assert = require('node:assert/strict')
const http = require('node:http')
const { UNCENSORED_MODEL, pullModel } = require('./model-pull.cjs')

function standIn(lines) {
  const seen = []
  const server = http.createServer(async (req, res) => {
    let body = ''
    for await (const chunk of req) body += chunk
    seen.push({ path: req.url, body: JSON.parse(body) })
    res.writeHead(200, { 'content-type': 'application/x-ndjson' })
    for (const line of lines) res.write(`${JSON.stringify(line)}\n`)
    res.end()
  })
  return new Promise((resolve) => server.listen(0, '127.0.0.1', () => resolve({ server, seen, port: server.address().port })))
}

test('only the uncensored model can be pulled from here', async () => {
  await assert.rejects(() => pullModel('anything:latest', () => {}), /cannot be downloaded/)
})

test('progress is reported and the pull resolves', async () => {
  const { server, seen, port } = await standIn([{ status: 'pulling manifest' }, { status: 'pulling', total: 6.6e9, completed: 3.3e9 }, { status: 'success' }])
  const progress = []
  await pullModel(UNCENSORED_MODEL, (event) => progress.push(event), { port })
  server.close()
  assert.deepEqual(seen, [{ path: '/api/pull', body: { model: UNCENSORED_MODEL, stream: true } }])
  assert.deepEqual(progress[1], { fraction: 0.5, detail: '3.3 of 6.6 GB' })
})

test('an error line from Ollama fails the pull with its message', async () => {
  const { server, port } = await standIn([{ status: 'pulling manifest' }, { error: 'pull model manifest: file does not exist' }])
  await assert.rejects(() => pullModel(UNCENSORED_MODEL, () => {}, { port }), /file does not exist/)
  server.close()
})
