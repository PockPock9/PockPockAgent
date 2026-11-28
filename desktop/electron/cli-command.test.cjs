const test = require('node:test')
const assert = require('node:assert/strict')
const fs = require('node:fs')
const os = require('node:os')
const path = require('node:path')
const { installCommand, launcherText, binDir } = require('./cli-command.cjs')

test('the launcher runs the app Python with the bundled script and passes all arguments', () => {
  const win = launcherText({ python: 'C:\\P\\python.exe', backend: 'C:\\App\\backend', platform: 'win32' })
  assert.match(win, /"C:\\P\\python.exe" ".*pockpock_code\.py" %\*/)
  const mac = launcherText({ python: '/r/bin/python', backend: '/App/backend', platform: 'darwin' })
  assert.match(mac, /^#!\/bin\/sh\nexec "\/r\/bin\/python" ".*pockpock_code\.py" "\$@"\n$/)
})

test('the command folder is the data folder on Windows and ~/.local/bin elsewhere', () => {
  assert.equal(binDir({ dataRoot: 'D', platform: 'win32' }), path.join('D', 'bin'))
  assert.equal(binDir({ dataRoot: 'D', platform: 'darwin', home: '/h' }), path.join('/h', '.local', 'bin'))
})

test('nothing is installed before setup has made the Python environment', async () => {
  const top = fs.mkdtempSync(path.join(os.tmpdir(), 'pockpock-cli-'))
  try {
    assert.equal(await installCommand({ python: path.join(top, 'missing.exe'), backend: top, dataRoot: top }), null)
  } finally { fs.rmSync(top, { recursive: true, force: true }) }
})
