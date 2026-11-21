const test = require('node:test')
const assert = require('node:assert/strict')
const os = require('node:os')
const path = require('node:path')

// Regression test for the macOS Intel CI failure on PR #96: loading paths.cjs under plain
// Node used to `require('electron')` at module scope. The `electron` npm package has no
// postinstall, so that require lazily downloaded and extracted the whole Electron.app
// into node_modules — an extraction that failed with EPERM inside the app bundle on the
// macOS Intel runner. Nothing in the unit-test path may require the real `electron`
// package; outside Electron, paths.cjs uses a stub instead.
const paths = require('./paths.cjs')

test('loading paths.cjs under plain Node does not load the electron package', () => {
  assert.equal(process.versions.electron, undefined, 'this test runs under plain Node')
  const loadedElectron = Object.keys(require.cache).filter((file) => file.includes(`node_modules${path.sep}electron${path.sep}`))
  assert.deepEqual(loadedElectron, [], 'no file from node_modules/electron may be loaded')
})

test('paths work outside Electron through the isPackaged stub', () => {
  assert.equal(paths.getElectronApp(), null)
  assert.equal(paths.backendRoot(), path.join(paths.repoRoot(), 'backend'))
  assert.equal(paths.venvRoot(), path.join(paths.repoRoot(), '.venv'))
  assert.equal(paths.dataRoot(), path.join(paths.LOCAL, 'PockPock'))
})

test('defaultFolder falls back to Documents without the Electron app object', () => {
  const { Maintenance } = require('./maintenance.cjs')
  const manager = new Maintenance({ userData: path.join(os.tmpdir(), 'paths-test'), emit: () => {} })
  assert.equal(manager.defaultFolder(), path.join(os.homedir(), 'Documents', 'PockPock', 'PockPockAgent'))
  const loadedElectron = Object.keys(require.cache).filter((file) => file.includes(`node_modules${path.sep}electron${path.sep}`))
  assert.deepEqual(loadedElectron, [], 'defaultFolder must not require the electron package either')
})
