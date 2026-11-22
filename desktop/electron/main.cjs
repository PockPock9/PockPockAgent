// PockPock Agent desktop app: window, local server, service supervision, first-run setup, and the
// narrow IPC surface the renderer may use (storage, services, setup, workspace files, terminal).
const { app, BrowserWindow, dialog, ipcMain, nativeTheme, safeStorage, shell, Menu } = require('electron')
const fs = require('node:fs')
const path = require('node:path')
const { ServiceManager, httpJson, internalToken } = require('./services.cjs')
const { Setup } = require('./setup.cjs')
const { Updater } = require('./updater.cjs')
const themes = require('./themes.cjs')
const { syncGuidance } = require('./openclaw-guidance.cjs')
const { installedBrowsers } = require('./browsers.cjs')
const { ReportStore, prepareCapture } = require('./reports.cjs')
const { Maintenance } = require('./maintenance.cjs')
const { Cloud } = require('./cloud.cjs')
const { Connectors } = require('./connectors.cjs')
const { syncOpenClaw } = require('./cloud-openclaw.cjs')
const { FixRunner } = require('./maintenance-fix.cjs')
const { run } = require('./platform.cjs')
const paths = require('./paths.cjs')

// An app opened from Finder or the Dock gets a minimal PATH; add the folders PockPock's tools live in.
paths.fixPath()
// The data folder was named FrogAI before 2026-11-15; move it before any service writes to the new one.
paths.migrateLegacyData()
const { startServer } = require('./server.cjs')
const workspace = require('./workspace.cjs')
const { Terminals } = require('./terminal.cjs')

const DEV = process.env.POCKPOCK_DESKTOP_DEV === '1'
const DEV_URL = 'http://127.0.0.1:5180'
const BACKEND_URL = process.env.POCKPOCK_BACKEND_URL || 'http://127.0.0.1:8766'
const PREFERRED_PORT = 8790
const MAX_STORE_BYTES = 20 * 1024 * 1024
const STORE_KEYS = new Set(['sessions', 'settings'])

// Tests point the app at a throwaway data folder so they never touch real chats.
if (process.env.POCKPOCK_DESKTOP_USER_DATA) app.setPath('userData', process.env.POCKPOCK_DESKTOP_USER_DATA)

let mainWindow = null
let appOrigin = ''
let server = null
let quitting = false
const services = new ServiceManager({
  onChange: (list) => { send('services:changed', list); send('backend:status', backendPhase(list)); cloudFollowServices(list) },
})
let cloud = null // cloud model providers and their encrypted keys (cloud.cjs)
let connectors = null // connected apps and their encrypted credentials (connectors.cjs)
let gatewayWasUp = false
let openclawWasUp = false
/** The gateway keeps cloud keys only in memory, so they are sent again each time it comes up;
 * OpenClaw's copy of the model list is refreshed when it comes up. */
function cloudFollowServices(list) {
  const up = (id) => list.find((item) => item.id === id)?.status === 'running'
  const gatewayUp = up('gateway')
  const openclawUp = up('openclaw')
  if (cloud && gatewayUp && (!gatewayWasUp || !cloud.pushed)) void cloud.push()
  if (connectors && gatewayUp && (!gatewayWasUp || !connectors.pushed)) void connectors.push()
  if (cloud && openclawUp && !openclawWasUp) void syncCloudToOpenClaw()
  gatewayWasUp = gatewayUp
  openclawWasUp = openclawUp
}
let openclawSync = Promise.resolve()
/** Writes the chosen cloud models into OpenClaw's configuration (one run at a time). */
function syncCloudToOpenClaw() {
  openclawSync = openclawSync.then(async () => {
    const entry = paths.openclawEntry()
    if (!cloud || !entry) return
    const models = cloud.chosenModels()
    const cli = (args) => run(entry.node, [entry.script, ...args], { timeout: 60000 })
    try { await syncOpenClaw(cli, models, models.length ? cloud.proxyToken() : '') } catch (error) { console.error('Cloud models could not be written to OpenClaw:', error.message) }
  })
  return openclawSync
}
let autoStarting = false
let startingDetail = '' // shown while services start, e.g. while packages are updated after an app update
let updater = null
let themeSetting = themes.DEFAULT // the saved choice, which may be "system"
let setup = null // created once the app data folder is known
let reports = null // problem reports, in <userData>/reports
let maintenance = null // Maintenance Manager setup
let fixes = null // Maintenance Manager fix runs

/** The renderer's view of the backend: the gateway's state, or why it is not up. */
function backendPhase(list = services.list()) {
  const gateway = list.find((item) => item.id === 'gateway')
  if (!gateway || gateway.status === 'checking') return { phase: 'checking', detail: 'Checking services…', startedByApp: false }
  if (gateway.status === 'running') return { phase: 'ready', detail: gateway.detail, startedByApp: gateway.startedByApp }
  if (gateway.status === 'unavailable') return { phase: 'missing', detail: gateway.detail, startedByApp: false }
  if (gateway.status === 'starting' || autoStarting) return { phase: 'starting', detail: startingDetail || 'Starting PockPock services…', startedByApp: false }
  if (gateway.status === 'error') return { phase: 'failed', detail: gateway.detail, startedByApp: false }
  return { phase: 'stopped', detail: 'The PockPock gateway is stopped. Start it from Services.', startedByApp: false }
}

function appSettings() {
  const services = readSettings().services
  return { autoStart: services?.autoStart !== false, stopOnQuit: services?.stopOnQuit !== false, nemoclaw: services?.nemoclaw !== false }
}
const terminals = new Terminals((...args) => send(...args))

function send(channel, ...args) {
  if (mainWindow && !mainWindow.isDestroyed()) mainWindow.webContents.send(channel, ...args)
}

function storePath(key) {
  return path.join(app.getPath('userData'), `${key}.json`)
}

function readSettings() {
  try { return JSON.parse(fs.readFileSync(storePath('settings'), 'utf8')) } catch { return {} }
}

function workspaceRoot() {
  const root = readSettings().workspace
  if (typeof root !== 'string' || !root || !fs.existsSync(root)) throw new Error('Open a folder first.')
  return root
}

/** Only the app's own page may call these handlers. */
function handle(channel, handler) {
  ipcMain.handle(channel, async (event, ...args) => {
    const url = event.senderFrame?.url || ''
    if (!appOrigin || !url.startsWith(appOrigin)) throw new Error('Request refused.')
    return handler(...args)
  })
}

function registerIpc() {
  handle('app:info', () => ({
    version: app.getVersion(),
    electron: process.versions.electron,
    platform: process.platform,
    arch: process.arch,
    repoRoot: paths.repoRoot(),
    backendRoot: paths.backendRoot(),
    python: paths.venvPython(),
    packaged: app.isPackaged,
    backendUrl: BACKEND_URL,
    terminal: terminals.available(),
    backend: backendPhase(),
    loginItem: app.getLoginItemSettings().openAtLogin,
  }))

  handle('store:get', (key) => {
    if (!STORE_KEYS.has(key)) throw new Error('Unknown store.')
    try { return JSON.parse(fs.readFileSync(storePath(key), 'utf8')) } catch { return null }
  })
  handle('store:set', (key, value) => {
    if (!STORE_KEYS.has(key)) throw new Error('Unknown store.')
    const text = JSON.stringify(value)
    if (text.length > MAX_STORE_BYTES) throw new Error('Saved data is too large.')
    const file = storePath(key)
    fs.writeFileSync(`${file}.tmp`, text, 'utf8')
    fs.renameSync(`${file}.tmp`, file)
    return true
  })

  handle('workspace:choose', async () => {
    const result = await dialog.showOpenDialog(mainWindow, { title: 'Open folder', properties: ['openDirectory'] })
    if (result.canceled || !result.filePaths[0]) return null
    const settings = { ...readSettings(), workspace: result.filePaths[0] }
    fs.writeFileSync(storePath('settings'), JSON.stringify(settings), 'utf8')
    return result.filePaths[0]
  })
  handle('workspace:list', (relative) => workspace.list(workspaceRoot(), typeof relative === 'string' ? relative : ''))
  handle('workspace:read', (relative) => workspace.read(workspaceRoot(), String(relative)))
  handle('workspace:open', async (relative) => {
    const error = await shell.openPath(await workspace.insideReal(workspaceRoot(), String(relative || '')))
    if (error) throw new Error(error)
    return true
  })
  handle('workspace:reveal', async (relative) => {
    shell.showItemInFolder(await workspace.insideReal(workspaceRoot(), String(relative || '')))
    return true
  })

  handle('terminal:create', (options) => {
    let cwd = ''
    try { cwd = workspaceRoot() } catch { cwd = '' }
    return terminals.create({ cwd, cols: options?.cols, rows: options?.rows })
  })
  handle('terminal:write', (id, data) => terminals.write(id, data))
  handle('terminal:resize', (id, cols, rows) => terminals.resize(id, cols, rows))
  handle('terminal:kill', (id) => terminals.kill(id))

  handle('setup:status', () => setup.status())
  handle('setup:start', (plan) => {
    const components = Array.isArray(plan?.components) ? plan.components.filter((name) => ['core', 'ollama', 'openclaw', 'nemoclaw'].includes(name)) : ['core']
    // The model is checked against the offered choices in setup.start; anything else means "recommended".
    const model = typeof plan?.model === 'string' ? plan.model.slice(0, 64) : undefined
    void setup.start({ components, disabledSkills: Array.isArray(plan?.disabledSkills) ? plan.disabledSkills.map(String) : [], model })
    return true
  })
  handle('setup:cancel', () => { setup.cancel(); return true })
  // Theme: the renderer applies the colours; the main process keeps the window background, the
  // Windows caption buttons and Chromium's colour scheme in step. Only known theme ids are accepted.
  // OpenClaw's browser: its default (Chrome/Edge as OpenClaw finds it) or an installed Chromium browser.
  const openclawCli = async (args, timeout = 60000) => {
    const entry = paths.openclawEntry()
    if (!entry) throw new Error('OpenClaw is not installed. Run Setup.')
    return run(entry.node, [entry.script, ...args], { timeout })
  }
  handle('openclaw:browsers', async () => {
    const available = installedBrowsers()
    const result = await openclawCli(['config', 'get', 'browser.executablePath', '--json'], 30000)
    // A set value prints as its JSON (a quoted path); an unset one prints {"ok": false, ...}.
    let currentPath = ''
    try { const parsed = JSON.parse(result.stdout.trim().split('\n').pop()); currentPath = typeof parsed === 'string' ? parsed : '' } catch { currentPath = '' }
    const current = available.find((browser) => browser.path.toLowerCase() === currentPath.toLowerCase())?.id || (currentPath ? 'custom' : 'default')
    return { available: available.map(({ id, name }) => ({ id, name })), current, currentPath }
  })
  // How long OpenClaw waits for a slow local model (issue #83). Without this provider setting it
  // gives up after 300 seconds, before a small model on a CPU has read OpenClaw's prompt.
  const SLOW_MODEL_KEY = 'models.providers.ollama.timeoutSeconds'
  const SLOW_MODEL_SECONDS = 1800
  handle('openclaw:slowModels', async () => {
    const result = await openclawCli(['config', 'get', SLOW_MODEL_KEY, '--json'], 30000)
    let seconds = null
    try { const parsed = JSON.parse(result.stdout.trim().split('\n').pop()); seconds = typeof parsed === 'number' ? parsed : null } catch { seconds = null }
    return { seconds, recommended: SLOW_MODEL_SECONDS }
  })
  handle('openclaw:allowSlowModels', async () => {
    const result = await openclawCli(['config', 'set', SLOW_MODEL_KEY, String(SLOW_MODEL_SECONDS), '--strict-json'])
    if (!result.ok) throw new Error((result.stderr || result.stdout).trim().split('\n').slice(-2).join(' ') || 'OpenClaw did not accept the setting.')
    // OpenClaw reads provider settings when its gateway starts.
    await services.stop('openclaw').catch(() => undefined)
    await services.start('openclaw')
    return { seconds: SLOW_MODEL_SECONDS, recommended: SLOW_MODEL_SECONDS }
  })
  handle('openclaw:setBrowser', async (id) => {
    const available = installedBrowsers()
    const chosen = available.find((browser) => browser.id === id)
    if (id !== 'default' && !chosen) throw new Error('That browser is not installed.')
    const result = id === 'default'
      ? await openclawCli(['config', 'unset', 'browser.executablePath'])
      : await openclawCli(['config', 'set', 'browser.executablePath', JSON.stringify(chosen.path), '--strict-json'])
    if (!result.ok && !/unset|not set/i.test(result.stderr + result.stdout)) throw new Error((result.stderr || result.stdout).trim().split('\n').slice(-2).join(' ') || 'OpenClaw did not accept the browser.')
    // Close OpenClaw's running browser so the next browser action starts the chosen one.
    await openclawCli(['browser', 'stop'], 30000).catch(() => undefined)
    return id
  })
  // Problem reports (see reports.cjs). The store validates ids, categories and sizes and redacts
  // personal details; preview shows the user exactly what would be saved.
  handle('reports:preview', (capture) => prepareCapture(capture))
  handle('reports:create', (input) => { const report = reports.create(input && typeof input === 'object' ? input : {}); void fixes.autoNext(); return report })
  handle('reports:list', () => reports.list())
  handle('reports:get', (id) => reports.get(id))
  handle('reports:update', (id, change) => reports.update(id, change))
  handle('reports:delete', (id) => reports.remove(id))
  // Maintenance Manager setup (maintenance.cjs): each step is an explicit user action.
  // Connectors (connectors.cjs). Credentials go in, encrypted, and never come back out.
  handle('connectors:list', () => connectors.list())
  handle('connectors:connect', (id, values) => connectors.connect(id, values))
  handle('connectors:disconnect', (id) => connectors.disconnect(id))
  // Cloud model providers (cloud.cjs). API keys go in, encrypted, and never come back out.
  handle('cloud:list', () => cloud.list())
  handle('cloud:connect', (id, input) => cloud.connect(String(id), { key: input?.key, region: typeof input?.region === 'string' ? input.region : undefined }))
  handle('cloud:available', (id) => cloud.available(String(id)))
  handle('cloud:setModels', (id, models) => cloud.setModels(String(id), models))
  handle('cloud:disconnect', (id) => cloud.disconnect(String(id)))
  handle('maintenance:status', () => maintenance.status())
  handle('maintenance:agents', () => maintenance.agents())
  handle('maintenance:setAgent', (choice) => maintenance.setAgent(choice))
  handle('maintenance:connectAgent', (id) => maintenance.connectAgent(String(id)))
  handle('maintenance:cancelConnect', () => maintenance.cancelConnect())
  handle('maintenance:disconnectAgent', (id) => maintenance.disconnectAgent(String(id)))
  handle('maintenance:github', () => maintenance.github())
  handle('maintenance:githubLogin', () => maintenance.githubLogin())
  handle('maintenance:cancelLogin', () => { maintenance.cancelLogin(); return true })
  handle('maintenance:chooseFolder', async (current) => {
    const result = await dialog.showOpenDialog(mainWindow, { title: 'Where should the copy of PockPock go?', properties: ['openDirectory', 'createDirectory'], defaultPath: typeof current === 'string' ? current : undefined })
    return result.canceled ? '' : result.filePaths[0]
  })
  handle('maintenance:clone', (dir) => maintenance.clone(dir))
  handle('maintenance:forget', () => maintenance.forget())
  handle('maintenance:setAuto', (enabled) => { const result = maintenance.setAuto(enabled === true); void fixes.autoNext(); return result })
  // Fix runs: start, stop, read; approve (commit, push, draft PR) and discard need an explicit click.
  handle('maintenance:fixGet', (reportId) => fixes.get(reportId))
  handle('maintenance:fixStart', (reportId) => fixes.start(reportId))
  handle('maintenance:fixCancel', (reportId) => fixes.cancel(reportId))
  handle('maintenance:fixApprove', (reportId, text) => fixes.approve(reportId, text && typeof text === 'object' ? { title: String(text.title ?? ''), body: String(text.body ?? '') } : {}))
  handle('maintenance:fixDiscard', (reportId) => fixes.discard(reportId))
  handle('theme:set', (id) => {
    if (!themes.IDS.includes(id)) throw new Error('Unknown theme.')
    themeSetting = id
    themes.applyNative(id)
    return applyWindowTheme()
  })
  handle('updates:state', () => updater.state)
  handle('updates:check', () => updater.check())
  handle('updates:download', () => updater.download())
  handle('updates:install', () => updater.install(true))
  handle('backend:retry', () => services.startAll({ includeNemo: false }))
  handle('services:list', () => { void services.refresh(); return services.list() })
  handle('services:start', (id) => id === 'all' ? services.startAll({ includeNemo: true }) : services.start(String(id)))
  handle('services:stop', (id) => id === 'all' ? services.stopAll(false) : services.stop(String(id)))
  handle('services:restart', async (id) => { await services.stop(String(id)); return services.start(String(id)) })
  handle('services:logs', (id) => services.logs(String(id)))
  handle('services:openLogs', () => shell.openPath(paths.logsRoot()))
  handle('app:setLoginItem', (enabled) => {
    app.setLoginItemSettings({ openAtLogin: Boolean(enabled), path: process.execPath, args: app.isPackaged ? [] : [path.join(__dirname, '..')] })
    return app.getLoginItemSettings().openAtLogin
  })
  handle('shell:openExternal', (url) => {
    const parsed = new URL(String(url))
    if (parsed.protocol !== 'https:' && parsed.protocol !== 'http:') throw new Error('Only web links can be opened.')
    return shell.openExternal(parsed.href)
  })
  handle('shell:openPath', async (target) => {
    // Agent task folders and artifacts live outside the workspace; open folders and files only.
    const resolved = path.resolve(String(target))
    if (!fs.existsSync(resolved)) throw new Error('That path does not exist.')
    const error = await shell.openPath(resolved)
    if (error) throw new Error(error)
    return true
  })
}

/** Colours the window chrome for the current theme; returns the concrete theme id. */
function applyWindowTheme() {
  const resolved = themes.resolve(themeSetting)
  const colours = themes.THEMES[resolved]
  if (mainWindow && !mainWindow.isDestroyed()) {
    mainWindow.setBackgroundColor(colours.bg)
    if (paths.IS_WIN) mainWindow.setTitleBarOverlay({ color: colours.bg, symbolColor: colours.symbol, height: 38 })
  }
  return resolved
}

async function createWindow() {
  if (DEV) {
    appOrigin = DEV_URL
  } else {
    const started = await startServer({ root: path.join(__dirname, '..', 'dist'), backendUrl: BACKEND_URL, preferredPort: PREFERRED_PORT })
    server = started.server
    appOrigin = `http://127.0.0.1:${started.port}`
  }

  // The saved theme colours the window before the page paints, so there is no flash.
  themeSetting = themes.valid(readSettings().theme)
  themes.applyNative(themeSetting)
  const initialTheme = themes.resolve(themeSetting)
  const chrome = themes.THEMES[initialTheme]
  mainWindow = new BrowserWindow({
    width: 1440,
    height: 900,
    minWidth: 760,
    minHeight: 520,
    backgroundColor: chrome.bg,
    title: 'PockPock Agent',
    icon: path.join(__dirname, '..', 'public', process.platform === 'win32' ? 'icon.ico' : 'icon.png'),
    titleBarStyle: paths.IS_MAC ? 'hiddenInset' : 'hidden',
    titleBarOverlay: paths.IS_WIN ? { color: chrome.bg, symbolColor: chrome.symbol, height: 38 } : undefined,
    trafficLightPosition: paths.IS_MAC ? { x: 14, y: 12 } : undefined,
    show: false,
    webPreferences: {
      preload: path.join(__dirname, 'preload.cjs'),
      contextIsolation: true,
      sandbox: true,
      nodeIntegration: false,
      spellcheck: true,
    },
  })
  mainWindow.once('ready-to-show', () => mainWindow.show())

  // Links open in the default browser; the window never navigates away from the app.
  mainWindow.webContents.setWindowOpenHandler(({ url }) => {
    if (/^https?:/i.test(url)) void shell.openExternal(url)
    return { action: 'deny' }
  })
  mainWindow.webContents.on('will-navigate', (event, url) => {
    if (!url.startsWith(appOrigin)) {
      event.preventDefault()
      if (/^https?:/i.test(url)) void shell.openExternal(url)
    }
  })
  mainWindow.webContents.session.setPermissionRequestHandler((_contents, permission, callback) => {
    callback(permission === 'clipboard-sanitized-write' || permission === 'media')
  })

  // public/theme-boot.js reads ?theme= and sets data-theme before the app renders.
  await mainWindow.loadURL(`${appOrigin}/?theme=${encodeURIComponent(initialTheme)}`)
  // With "system", follow the OS switching between light and dark while the app is open.
  nativeTheme.on('updated', () => { if (themeSetting === 'system') applyWindowTheme() })
  services.watch()
  // Maintenance Manager automatic mode resumes shortly after start.
  setTimeout(() => { void fixes?.autoNext() }, 60_000)
  // Bring PockPock's guidance in OpenClaw's AGENTS.md up to this version (a no-op when current).
  try { syncGuidance(paths.backendRoot()) } catch (error) { console.warn('OpenClaw guidance not updated:', error?.message || error) }
  // Before setup has installed the backend there is nothing to start.
  const needsSetup = !fs.existsSync(paths.venvPython())
  if (!needsSetup && appSettings().autoStart) {
    autoStarting = true
    send('backend:status', backendPhase())
    void (async () => {
      // After the app updated itself, the new version may need other Python packages.
      if (app.isPackaged && setup.backendOutdated()) {
        startingDetail = 'Updating PockPock’s services for the new version…'
        send('backend:status', backendPhase())
        await setup.refreshBackend()
        startingDetail = ''
      }
      await services.startAll({ includeNemo: appSettings().nemoclaw })
    })().finally(() => { autoStarting = false; startingDetail = ''; send('backend:status', backendPhase()) })
  }
  updater.start()
}

if (!app.requestSingleInstanceLock()) {
  app.quit()
} else {
  app.on('second-instance', () => {
    if (mainWindow) { if (mainWindow.isMinimized()) mainWindow.restore(); mainWindow.focus() }
  })
  app.whenReady().then(() => {
    if (process.platform === 'win32') app.setAppUserModelId('ai.pockpock.agent')
    // Windows uses the app's own title bar. macOS needs a menu bar for Cmd+C/V/X/A/Z, Cmd+Q and Cmd+W.
    Menu.setApplicationMenu(paths.IS_MAC ? Menu.buildFromTemplate([{ role: 'appMenu' }, { role: 'editMenu' }, { label: 'View', submenu: [{ role: 'reload' }, { role: 'toggleDevTools' }, { type: 'separator' }, { role: 'resetZoom' }, { role: 'zoomIn' }, { role: 'zoomOut' }, { type: 'separator' }, { role: 'togglefullscreen' }] }, { role: 'windowMenu' }]) : null)
    setup = new Setup({ services, userData: app.getPath('userData'), emit: (event) => send('setup:event', event) })
    reports = new ReportStore(path.join(app.getPath('userData'), 'reports'))
    maintenance = new Maintenance({ userData: app.getPath('userData'), emit: (event) => send('maintenance:event', event) })
    cloud = new Cloud({
      userData: app.getPath('userData'),
      crypt: { available: () => safeStorage.isEncryptionAvailable(), encrypt: (text) => safeStorage.encryptString(text), decrypt: (data) => safeStorage.decryptString(data) },
      internalToken,
      onChange: () => { void syncCloudToOpenClaw(); send('cloud:changed', cloud.list()) },
    })
    const crypt = { available: () => safeStorage.isEncryptionAvailable(), encrypt: (text) => safeStorage.encryptString(text), decrypt: (data) => safeStorage.decryptString(data) }
    connectors = new Connectors({ userData: app.getPath('userData'), crypt, internalToken, onChange: () => send('connectors:changed') })
    // The same for connected apps: the gateway holds their credentials in memory only.
    setInterval(async () => {
      const wanted = connectors.count()
      if (!wanted || !gatewayWasUp) return
      const reply = await httpJson(`${BACKEND_URL}/api/connectors`, 3000)
      const live = Array.isArray(reply?.json?.connectors) ? reply.json.connectors.filter((item) => item.connected).length : wanted
      if (reply?.status === 200 && live !== wanted) void connectors.push()
    }, 60_000).unref()
    // A gateway that restarted by itself has lost the keys it held in memory: send them again.
    setInterval(async () => {
      const wanted = cloud.chosenModels().length
      if (!wanted || !gatewayWasUp) return
      const reply = await httpJson(`${BACKEND_URL}/api/cloud/models`, 3000)
      if (reply?.status === 200 && Array.isArray(reply.json?.models) && reply.json.models.length !== wanted) void cloud.push()
    }, 60_000).unref()
    fixes = new FixRunner({ maintenance, reports, userData: app.getPath('userData'), emit: (event) => send('maintenance:event', event) })
    updater = new Updater({
      emit: (state) => send('updates:state', state),
      autoDownload: () => readSettings().updates?.autoDownload !== false,
      // The Python services and terminals run from inside the app folder; Windows cannot replace
      // files a running program holds, so they stop before the installer runs.
      beforeInstall: async () => {
        terminals.killAll()
        for (const id of ['gateway', 'planner', 'validator', 'run-store', 'browser-automation']) await services.stop(id).catch(() => undefined)
        services.killOwnedSync()
      },
    })
    registerIpc()
    return createWindow()
  })
  // PockPock supervises services, so closing the window quits the app on macOS too.
  app.on('window-all-closed', () => app.quit())
  app.on('activate', () => { if (mainWindow) mainWindow.show() })
  app.on('before-quit', (event) => {
    if (quitting) return
    terminals.killAll()
    if (updater?.ready) {
      // A downloaded update installs on quit, after the backend has stopped.
      event.preventDefault()
      quitting = true
      const others = appSettings().stopOnQuit ? Promise.race([services.stopAll(true), new Promise((resolve) => setTimeout(resolve, 20000))]) : Promise.resolve()
      void others.catch(() => undefined).then(() => updater.install(false))
      return
    }
    if (!appSettings().stopOnQuit) { server?.close(); return }
    // Stop what this app started (OpenClaw and NemoClaw need a command, not just a kill).
    event.preventDefault()
    quitting = true
    const done = () => { services.killOwnedSync(); server?.close(); app.exit(0) }
    Promise.race([services.stopAll(true), new Promise((resolve) => setTimeout(resolve, 20000))]).then(done, done)
  })
}
