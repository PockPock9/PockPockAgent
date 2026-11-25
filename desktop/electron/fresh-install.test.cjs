const test = require('node:test')
const assert = require('node:assert/strict')
const fs = require('node:fs')
const os = require('node:os')
const path = require('node:path')
const { CACHE_DIRS, MARKER, cleanAfterManualInstall } = require('./fresh-install.cjs')

function fixture() {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), 'fresh-install-'))
  const userData = path.join(root, 'PockPock Agent')
  const home = path.join(root, 'home')
  for (const name of CACHE_DIRS) fs.mkdirSync(path.join(userData, name), { recursive: true })
  fs.writeFileSync(path.join(userData, 'Cache', 'data_0'), 'x')
  for (const file of ['sessions.json', 'settings.json', 'cloud.json', 'connectors.json']) fs.writeFileSync(path.join(userData, file), '{}')
  fs.mkdirSync(path.join(userData, 'Local Storage'))
  fs.mkdirSync(path.join(userData, 'reports'))
  const updater = path.join(home, 'Library', 'Caches', 'pockpock-desktop-updater')
  fs.mkdirSync(updater, { recursive: true })
  return { root, userData, home, updater, options: { userData, home, local: path.join(root, 'local'), platform: 'darwin', isPackaged: true } }
}

test('a new version installed by hand on macOS clears the caches and keeps the data', () => {
  const { userData, updater, options } = fixture()
  const removed = cleanAfterManualInstall({ ...options, version: '0.2.10' })
  for (const name of CACHE_DIRS) assert.equal(fs.existsSync(path.join(userData, name)), false, name)
  assert.equal(fs.existsSync(updater), false)
  assert.ok(removed.includes(updater))
  for (const kept of ['sessions.json', 'settings.json', 'cloud.json', 'connectors.json', 'Local Storage', 'reports']) assert.ok(fs.existsSync(path.join(userData, kept)), kept)
  assert.deepEqual(JSON.parse(fs.readFileSync(path.join(userData, MARKER), 'utf8')), { version: '0.2.10' })
})

test('later starts of the same version keep the caches', () => {
  const { userData, options } = fixture()
  cleanAfterManualInstall({ ...options, version: '0.2.10' })
  fs.mkdirSync(path.join(userData, 'Cache'))
  assert.deepEqual(cleanAfterManualInstall({ ...options, version: '0.2.10' }), [])
  assert.ok(fs.existsSync(path.join(userData, 'Cache')))
})

test('Windows is left to the installer, and running from source never cleans', () => {
  const { userData, options } = fixture()
  assert.deepEqual(cleanAfterManualInstall({ ...options, platform: 'win32', version: '0.2.10' }), [])
  assert.deepEqual(cleanAfterManualInstall({ ...options, isPackaged: false, version: '0.2.10' }), [])
  assert.ok(fs.existsSync(path.join(userData, 'Cache', 'data_0')))
  assert.equal(fs.existsSync(path.join(userData, MARKER)), false)
})
