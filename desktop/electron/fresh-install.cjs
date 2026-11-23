// A new version installed by hand (a downloaded installer or .dmg) starts without the old app's
// caches; an update installed from inside the app keeps them. Only caches are removed: chats,
// settings, keys, connectors, reports, models and the Python environment are always kept.
//
// Windows: the installer does this itself (desktop/installer/installer.nsh), because it can tell
// an in-app update (electron-updater runs it with --updated) from a manual install.
// macOS: there are no in-app installs (updater.cjs only links to the download page), so every
// version change is a manual install; the app clears the caches on the first start of a new version.
// Keep CACHE_DIRS in step with installer.nsh.
const fs = require('node:fs')
const path = require('node:path')

/** Chromium and Electron caches inside the app's data folder (userData). */
const CACHE_DIRS = [
  'Cache', 'Code Cache', 'GPUCache', 'DawnCache', 'DawnGraphiteCache', 'DawnWebGPUCache', 'GPUPersistentCache',
  'GrShaderCache', 'ShaderCache', 'Shared Dictionary', 'Service Worker', 'blob_storage', 'Session Storage',
]
const MARKER = 'installed-version.json'

/** Folders where electron-updater kept downloaded installers (old and current app names). */
function updaterCacheDirs({ platform, home, local }) {
  const base = platform === 'darwin' ? path.join(home, 'Library', 'Caches') : local
  return ['pockpock-desktop-updater', 'pockpock-ai-desktop-updater'].map((name) => path.join(base, name))
}

/**
 * Clears the old app's caches on the first start of a version installed by hand. Returns the
 * folders it removed. Runs before the app is ready, so Chromium has not opened its caches yet.
 * @param {{ userData: string, version: string, platform: string, isPackaged: boolean, home: string, local: string }} options
 */
function cleanAfterManualInstall({ userData, version, platform, isPackaged, home, local }) {
  if (!isPackaged || platform === 'win32') return []
  const marker = path.join(userData, MARKER)
  let previous = ''
  try { previous = String(JSON.parse(fs.readFileSync(marker, 'utf8')).version || '') } catch { /* first start */ }
  if (previous === version) return []
  const removed = []
  for (const dir of [...CACHE_DIRS.map((name) => path.join(userData, name)), ...updaterCacheDirs({ platform, home, local })]) {
    if (!fs.existsSync(dir)) continue
    try { fs.rmSync(dir, { recursive: true, force: true }); removed.push(dir) } catch { /* a cache in use is left for next time */ }
  }
  try {
    fs.mkdirSync(userData, { recursive: true })
    fs.writeFileSync(marker, JSON.stringify({ version }))
  } catch { /* cleaning again next start is harmless */ }
  return removed
}

module.exports = { CACHE_DIRS, MARKER, updaterCacheDirs, cleanAfterManualInstall }
