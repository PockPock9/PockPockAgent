// File access for the Files panel. Every path is resolved and must stay inside the workspace
// folder the user chose, so the renderer cannot read or open arbitrary files.
const fs = require('node:fs/promises')
const path = require('node:path')

const MAX_ENTRIES = 600
const MAX_READ_BYTES = 256 * 1024
const HIDDEN = new Set(['.git', 'node_modules', '__pycache__', '.venv', 'venv', '.pytest_cache', '.mypy_cache', 'dist', '.DS_Store', 'Thumbs.db'])

function inside(root, target) {
  const base = path.resolve(root)
  const resolved = path.resolve(base, target)
  if (resolved !== base && !resolved.startsWith(base + path.sep)) throw new Error('That path is outside the workspace.')
  return resolved
}

async function list(root, relative = '') {
  const folder = inside(root, relative)
  const entries = await fs.readdir(folder, { withFileTypes: true })
  const items = entries
    .filter((entry) => !entry.isSymbolicLink())
    .map((entry) => ({
      name: entry.name,
      path: path.relative(path.resolve(root), path.join(folder, entry.name)),
      directory: entry.isDirectory(),
      muted: HIDDEN.has(entry.name) || entry.name.startsWith('.'),
    }))
    .sort((a, b) => (a.directory === b.directory ? a.name.localeCompare(b.name, undefined, { sensitivity: 'base' }) : a.directory ? -1 : 1))
  return { items: items.slice(0, MAX_ENTRIES), truncated: items.length > MAX_ENTRIES }
}

async function read(root, relative) {
  const file = inside(root, relative)
  const stat = await fs.stat(file)
  if (!stat.isFile()) throw new Error('That is not a file.')
  if (stat.size > MAX_READ_BYTES) throw new Error(`The file is larger than ${MAX_READ_BYTES / 1024} KB, too big to attach.`)
  const data = await fs.readFile(file)
  if (data.includes(0)) throw new Error('That looks like a binary file, which cannot be attached as text.')
  return { name: path.basename(file), text: data.toString('utf8'), size: stat.size }
}

module.exports = { inside, list, read }
