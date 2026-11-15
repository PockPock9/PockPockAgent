// Self-update from the project's GitHub releases (electron-updater, configured by "publish" in
// package.json). Windows: new versions download in the background (unless automatic downloads are
// switched off) and install on "Restart to update" or when the app quits. macOS: the app is only
// signed ad hoc, and macOS refuses to replace such an app automatically, so a new version is
// reported with a link to its download page instead.
const fs = require('node:fs')
const path = require('node:path')
const { app, shell } = require('electron')
const paths = require('./paths.cjs')

const RELEASES = 'https://github.com/PockPock9/PockPockAgent/releases'
const FIRST_CHECK_MS = 15 * 1000
const CHECK_EVERY_MS = 4 * 60 * 60 * 1000

class Updater {
  /**
   * @param {object} options
   * @param {(state: object) => void} options.emit sends the state to the window
   * @param {() => boolean} options.autoDownload whether downloads start without asking (a setting)
   * @param {() => Promise<void>} options.beforeInstall stops what holds files inside the app folder
   */
  constructor({ emit, autoDownload, beforeInstall }) {
    this.emit = emit
    this.autoDownload = autoDownload
    this.beforeInstall = beforeInstall
    this.updater = null
    this.timer = null
    this.state = {
      status: 'idle', // idle | checking | none | available | downloading | ready | error | unsupported
      current: app.getVersion(),
      version: '',
      progress: 0,
      error: '',
      checkedAt: '',
      canInstall: paths.IS_WIN,
      releaseUrl: RELEASES,
    }
  }

  set(change) {
    this.state = { ...this.state, ...change }
    this.emit(this.state)
  }

  log(level, message) {
    try {
      fs.appendFileSync(path.join(paths.logsRoot(), 'updater.log'), `${new Date().toISOString()} ${level} ${String(message).slice(0, 2000)}\n`)
    } catch { /* logging must never break updates */ }
  }

  start() {
    if (!app.isPackaged) {
      this.set({ status: 'unsupported', error: 'Updates work in the installed app, not when running from source.' })
      return
    }
    // Loaded here so running from source never touches the updater.
    const { autoUpdater } = require('electron-updater')
    this.updater = autoUpdater
    autoUpdater.logger = { info: (m) => this.log('info', m), warn: (m) => this.log('warn', m), error: (m) => this.log('error', m), debug: () => {} }
    autoUpdater.autoDownload = false // decided per check, below
    autoUpdater.autoInstallOnAppQuit = false // installed by quitAndInstall after the backend is stopped
    autoUpdater.allowPrerelease = false
    autoUpdater.on('checking-for-update', () => this.set({ status: 'checking', error: '' }))
    autoUpdater.on('update-not-available', () => this.set({ status: 'none', checkedAt: new Date().toISOString() }))
    autoUpdater.on('update-available', (info) => {
      const version = String(info?.version || '')
      this.set({ status: 'available', version, checkedAt: new Date().toISOString(), releaseUrl: `${RELEASES}/tag/v${version}` })
      if (paths.IS_WIN && this.autoDownload()) void this.download()
    })
    autoUpdater.on('download-progress', (progress) => this.set({ status: 'downloading', progress: Math.max(0, Math.min(1, (progress?.percent ?? 0) / 100)) }))
    autoUpdater.on('update-downloaded', (info) => this.set({ status: 'ready', version: String(info?.version || this.state.version), progress: 1 }))
    autoUpdater.on('error', (error) => {
      this.log('error', error?.stack || error)
      // A failed check is not worth interrupting anyone for; it is shown on the Settings page only.
      this.set({ status: 'error', error: plainError(error) })
    })
    setTimeout(() => void this.check(), FIRST_CHECK_MS)
    this.timer = setInterval(() => { if (this.state.status !== 'downloading' && this.state.status !== 'ready') void this.check() }, CHECK_EVERY_MS)
  }

  async check() {
    if (!this.updater || this.state.status === 'downloading' || this.state.status === 'ready') return this.state
    try { await this.updater.checkForUpdates() } catch (error) { this.set({ status: 'error', error: plainError(error) }) }
    return this.state
  }

  async download() {
    if (!this.updater) return this.state
    if (!paths.IS_WIN) { void shell.openExternal(this.state.releaseUrl); return this.state }
    if (this.state.status !== 'available' && this.state.status !== 'error') return this.state
    this.set({ status: 'downloading', progress: 0, error: '' })
    try { await this.updater.downloadUpdate() } catch (error) { this.set({ status: 'error', error: plainError(error) }) }
    return this.state
  }

  /** Whether quitting should install the downloaded update. */
  get ready() {
    return Boolean(this.updater) && paths.IS_WIN && this.state.status === 'ready'
  }

  /** Stops the backend, then lets the installer replace the app. `restart` opens the new version. */
  async install(restart) {
    if (!this.ready) return false
    this.log('info', `installing ${this.state.version}${restart ? ' and restarting' : ' on quit'}`)
    try { await this.beforeInstall() } catch (error) { this.log('warn', `before install: ${error?.message || error}`) }
    // Silent install; the one-click installer keeps the user's data and settings.
    this.updater.quitAndInstall(true, restart)
    return true
  }
}

function plainError(error) {
  const text = String(error?.message || error || '')
  if (/ENOTFOUND|ECONNREFUSED|ETIMEDOUT|EAI_AGAIN|net::ERR_/i.test(text)) return 'Could not reach GitHub to check for updates. Check the internet connection.'
  if (/sha512 checksum mismatch/i.test(text)) return 'The downloaded update was damaged. It will be downloaded again at the next check.'
  if (/404/.test(text)) return 'No update information was found for this version.'
  return text.split('\n')[0].slice(0, 200) || 'The update check failed.'
}

module.exports = { Updater }
