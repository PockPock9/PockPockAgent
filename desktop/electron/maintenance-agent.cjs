// "PockPock itself": the Maintenance Manager's own fixing agent. A small tool loop against a local
// Ollama model that can only look at and edit files inside the fix worktree. It cannot run commands
// (the Maintenance Manager runs the checks afterwards), so a tool can never hang the run, and its
// prompt stays small enough for local models (OpenClaw's own prompt is about 21K tokens).
const fs = require('node:fs')
const path = require('node:path')
const http = require('node:http')

const OLLAMA = 'http://127.0.0.1:11434'
const MAX_STEPS = 40
const CALL_TIMEOUT_MS = 6 * 60 * 1000
const SKIP = new Set(['.git', 'node_modules', 'dist', 'release', '.venv', '__pycache__', '.pytest_cache'])

const TOOLS = [
  ['list_files', 'List files and folders under a folder of the repository (relative path, "" for the root). Skips node_modules, .git and build output.', { path: { type: 'string', description: 'Folder, relative to the repository root' } }, []],
  ['search', 'Find lines that contain some text (case-insensitive) in the repository. Returns up to 60 matches as "path:line: text".', { text: { type: 'string' }, path: { type: 'string', description: 'Optional folder to search in' } }, ['text']],
  ['read_file', 'Read a text file with line numbers (at most 400 lines per call).', { path: { type: 'string' }, start_line: { type: 'integer' }, end_line: { type: 'integer' } }, ['path']],
  ['replace_in_file', 'Replace one exact piece of text in a file. old_text must appear exactly once; include a few surrounding lines to make it unique.', { path: { type: 'string' }, old_text: { type: 'string' }, new_text: { type: 'string' } }, ['path', 'old_text', 'new_text']],
  ['write_file', 'Create a new file, or replace a small file completely.', { path: { type: 'string' }, content: { type: 'string' } }, ['path', 'content']],
  ['finish', 'Call when the fix and its documentation update are done, or when you cannot fix it. title: a Conventional Commit title. description: what was wrong, the cause, the fix, the documentation updated, and anything left for a person to check.', { title: { type: 'string' }, description: { type: 'string' } }, ['title', 'description']],
].map(([name, description, properties, required]) => ({ type: 'function', function: { name, description, parameters: { type: 'object', properties, required } } }))

/** Resolves a repository-relative path inside the worktree; refuses anything outside it or in .git. */
function resolveInside(root, relative) {
  const target = path.resolve(root, String(relative ?? '').replace(/^[/\\]+/, ''))
  const rel = path.relative(root, target)
  if (rel.startsWith('..') || path.isAbsolute(rel) || rel.split(/[\\/]/)[0] === '.git') throw new Error(`"${relative}" is outside the repository.`)
  return target
}

function walk(root, start, limit = 4000) {
  const out = []
  const visit = (dir) => {
    if (out.length >= limit) return
    let entries = []
    try { entries = fs.readdirSync(dir, { withFileTypes: true }) } catch { return }
    for (const entry of entries) {
      if (SKIP.has(entry.name)) continue
      const full = path.join(dir, entry.name)
      if (entry.isDirectory()) visit(full)
      else out.push(path.relative(root, full).replace(/\\/g, '/'))
      if (out.length >= limit) return
    }
  }
  visit(start)
  return out
}

/** Executes one tool call. Returns the text given back to the model. */
function runTool(root, name, args, onFinish) {
  const a = args && typeof args === 'object' ? args : {}
  switch (name) {
    case 'list_files': {
      const dir = resolveInside(root, a.path || '')
      const entries = fs.readdirSync(dir, { withFileTypes: true }).filter((entry) => !SKIP.has(entry.name)).slice(0, 200)
      return entries.map((entry) => `${entry.name}${entry.isDirectory() ? '/' : ''}`).join('\n') || '(empty)'
    }
    case 'search': {
      const needle = String(a.text || '').toLowerCase()
      if (!needle) return 'Give the text to search for.'
      const matches = []
      for (const file of walk(root, resolveInside(root, a.path || ''))) {
        if (!/\.(md|ts|tsx|js|cjs|mjs|py|json|css|html|yml|yaml|txt)$/i.test(file)) continue
        let text = ''
        try { text = fs.readFileSync(path.join(root, file), 'utf8') } catch { continue }
        text.split(/\r?\n/).forEach((line, index) => { if (matches.length < 60 && line.toLowerCase().includes(needle)) matches.push(`${file}:${index + 1}: ${line.trim().slice(0, 200)}`) })
        if (matches.length >= 60) break
      }
      return matches.join('\n') || 'No matches.'
    }
    case 'read_file': {
      const lines = fs.readFileSync(resolveInside(root, a.path), 'utf8').split(/\r?\n/)
      const start = Math.max(1, Number(a.start_line) || 1)
      const end = Math.min(lines.length, Number(a.end_line) || start + 399, start + 399)
      return `${a.path} (lines ${start}-${end} of ${lines.length})\n${lines.slice(start - 1, end).map((line, index) => `${start + index}: ${line}`).join('\n')}`
    }
    case 'replace_in_file': {
      const file = resolveInside(root, a.path)
      const text = fs.readFileSync(file, 'utf8')
      const crlf = text.includes('\r\n')
      const normal = text.replace(/\r\n/g, '\n')
      const oldText = String(a.old_text ?? '').replace(/\r\n/g, '\n')
      if (!oldText) return 'old_text is empty.'
      const count = normal.split(oldText).length - 1
      if (count !== 1) return `old_text was found ${count} times in ${a.path}; it must appear exactly once. Read the file again and include more surrounding lines.`
      const next = normal.replace(oldText, String(a.new_text ?? '').replace(/\r\n/g, '\n'))
      fs.writeFileSync(file, crlf ? next.replace(/\n/g, '\r\n') : next, 'utf8')
      return `Replaced in ${a.path}.`
    }
    case 'write_file': {
      const file = resolveInside(root, a.path)
      fs.mkdirSync(path.dirname(file), { recursive: true })
      fs.writeFileSync(file, String(a.content ?? ''), 'utf8')
      return `Wrote ${a.path}.`
    }
    case 'finish':
      onFinish(String(a.title || '').trim(), String(a.description || '').trim())
      return 'Finished.'
    default:
      return `There is no tool named "${name}". Use one of: ${TOOLS.map((tool) => tool.function.name).join(', ')}.`
  }
}

function chat(body, signal) {
  return new Promise((resolve, reject) => {
    const request = http.request(`${OLLAMA}/api/chat`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, timeout: CALL_TIMEOUT_MS }, (response) => {
      let data = ''
      response.on('data', (chunk) => { data += chunk })
      response.on('end', () => { try { const parsed = JSON.parse(data); parsed.error ? reject(new Error(parsed.error)) : resolve(parsed) } catch { reject(new Error(`Ollama answered HTTP ${response.statusCode}.`)) } })
    })
    request.on('timeout', () => request.destroy(new Error('The model did not answer within 6 minutes.')))
    request.on('error', reject)
    signal?.addEventListener('abort', () => request.destroy(new Error('Stopped.')), { once: true })
    request.end(JSON.stringify(body))
  })
}

/**
 * Runs the loop. Returns { ok, output } like the command-line agents; writes the PR text to prFile
 * when the model calls finish.
 */
async function runPockPockAgent({ model, worktree, prompt, prFile, onLine, signal }) {
  const system = [
    'You are PockPock, fixing a problem in your own source code. You can only use the tools provided: list_files, search, read_file, replace_in_file, write_file and finish.',
    'You cannot run commands; the Maintenance Manager runs the project checks after you finish.',
    'Work step by step: find the relevant files with search or list_files, read them, then change them with replace_in_file. Keep changes small and focused.',
    'Every fix must also update the documentation that describes the changed behaviour (docs/features/*.md, README.md or docs/ARCHITECTURE.md).',
    'When done, call finish. Do not reply with plain text instead of a tool call.',
  ].join('\n')
  const messages = [{ role: 'system', content: system }, { role: 'user', content: prompt }]
  let finished = null
  let idle = 0
  for (let step = 1; step <= MAX_STEPS && !finished; step += 1) {
    if (signal?.aborted) return { ok: false, code: -1, output: 'Stopped.' }
    let reply
    try {
      reply = await chat({ model, messages, tools: TOOLS, stream: false, think: false, options: { temperature: 0.2 } }, signal)
    } catch (error) {
      onLine(`The model failed: ${error.message}`)
      return { ok: false, code: -1, output: error.message }
    }
    const message = reply.message || {}
    messages.push({ role: 'assistant', content: message.content || '', ...(message.tool_calls ? { tool_calls: message.tool_calls } : {}) })
    const calls = message.tool_calls || []
    if (!calls.length) {
      idle += 1
      if (message.content) onLine(`PockPock: ${message.content.trim().slice(0, 300)}`)
      if (idle > 2) return { ok: false, code: 1, output: 'The model stopped using its tools before finishing.' }
      messages.push({ role: 'user', content: 'Continue by calling a tool. When the fix and the documentation update are done, call finish.' })
      continue
    }
    idle = 0
    for (const call of calls) {
      const name = call.function?.name
      const args = call.function?.arguments
      const shown = name === 'finish' ? '' : ` ${String(args?.path ?? args?.text ?? '').slice(0, 120)}`
      onLine(`· ${name}${shown}`)
      let result
      try { result = runTool(worktree, name, args, (title, description) => { finished = { title, description } }) } catch (error) { result = `Error: ${error.message}` }
      messages.push({ role: 'tool', content: String(result).slice(0, 16000), tool_name: name })
    }
  }
  if (!finished) return { ok: false, code: 1, output: `The model did not finish within ${MAX_STEPS} steps.` }
  fs.writeFileSync(prFile, `# ${finished.title}\n\n${finished.description}\n`, 'utf8')
  return { ok: true, code: 0, output: finished.description }
}

module.exports = { runPockPockAgent, runTool, resolveInside, TOOLS }
