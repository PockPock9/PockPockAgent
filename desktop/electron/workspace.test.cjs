const test = require('node:test')
const assert = require('node:assert/strict')
const fs = require('node:fs')
const os = require('node:os')
const path = require('node:path')
const workspace = require('./workspace.cjs')

// Issue #74: a symlink or junction inside the workspace must not let the Files panel read
// or list what it points to outside the workspace.
function setup() {
  const top = fs.mkdtempSync(path.join(os.tmpdir(), 'pockpock-ws-'))
  const root = path.join(top, 'workspace'); const outside = path.join(top, 'outside')
  fs.mkdirSync(path.join(root, 'sub'), { recursive: true }); fs.mkdirSync(outside)
  fs.writeFileSync(path.join(root, 'sub', 'ok.txt'), 'inside')
  fs.writeFileSync(path.join(outside, 'secret.txt'), 'secret')
  return { top, root, outside }
}

test('files inside the workspace can be listed and read', async () => {
  const { top, root } = setup()
  try {
    const listing = await workspace.list(root, 'sub')
    assert.deepEqual(listing.items.map((item) => item.path), [path.join('sub', 'ok.txt')])
    assert.equal((await workspace.read(root, path.join('sub', 'ok.txt'))).text, 'inside')
    await assert.rejects(workspace.read(root, '../outside/secret.txt'), /outside the workspace/)
  } finally { fs.rmSync(top, { recursive: true, force: true }) }
})

test('a directory link pointing outside the workspace is refused', async () => {
  const { top, root, outside } = setup()
  try {
    // A junction needs no special privilege on Windows; elsewhere this is a normal symlink.
    fs.symlinkSync(outside, path.join(root, 'linkdir'), process.platform === 'win32' ? 'junction' : 'dir')
    await assert.rejects(workspace.list(root, 'linkdir'), /outside the workspace/)
    await assert.rejects(workspace.read(root, path.join('linkdir', 'secret.txt')), /outside the workspace/)
    await assert.rejects(workspace.insideReal(root, 'linkdir'), /outside the workspace/)
  } finally { fs.rmSync(top, { recursive: true, force: true }) }
})

test('a file symlink pointing outside the workspace is refused', async (t) => {
  const { top, root, outside } = setup()
  try {
    try { fs.symlinkSync(path.join(outside, 'secret.txt'), path.join(root, 'link.txt'), 'file') } catch (error) {
      if (error.code === 'EPERM') { t.skip('creating file symlinks needs Developer Mode on Windows'); return }
      throw error
    }
    await assert.rejects(workspace.read(root, 'link.txt'), /outside the workspace/)
  } finally { fs.rmSync(top, { recursive: true, force: true }) }
})
