// Chromium-based browsers OpenClaw can drive (it controls the browser over the DevTools protocol),
// found in their standard install locations. Used for Settings → OpenClaw browser.
const fs = require('node:fs')
const os = require('node:os')
const path = require('node:path')
const paths = require('./paths.cjs')

function candidates() {
  if (paths.IS_WIN) {
    const programFiles = [process.env.ProgramFiles, process.env['ProgramFiles(x86)'], process.env.LOCALAPPDATA].filter(Boolean)
    const under = (...parts) => programFiles.map((root) => path.join(root, ...parts))
    return [
      { id: 'edge', name: 'Microsoft Edge', files: under('Microsoft', 'Edge', 'Application', 'msedge.exe') },
      { id: 'chrome', name: 'Google Chrome', files: under('Google', 'Chrome', 'Application', 'chrome.exe') },
      { id: 'brave', name: 'Brave', files: under('BraveSoftware', 'Brave-Browser', 'Application', 'brave.exe') },
    ]
  }
  const apps = ['/Applications', path.join(os.homedir(), 'Applications')]
  const app = (bundle, binary) => apps.map((root) => path.join(root, bundle, 'Contents', 'MacOS', binary))
  return [
    { id: 'chrome', name: 'Google Chrome', files: app('Google Chrome.app', 'Google Chrome') },
    { id: 'brave', name: 'Brave', files: app('Brave Browser.app', 'Brave Browser') },
    { id: 'edge', name: 'Microsoft Edge', files: app('Microsoft Edge.app', 'Microsoft Edge') },
  ]
}

/** Installed browsers: [{ id, name, path }]. */
function installedBrowsers() {
  return candidates().map(({ id, name, files }) => ({ id, name, path: files.find((file) => fs.existsSync(file)) })).filter((browser) => browser.path)
}

module.exports = { installedBrowsers }
