// PockPock Agent desktop app: window, local server, service supervision, first-run setup, and the
// narrow IPC surface the renderer may use (storage, services, setup, workspace files, terminal).
const { app, BrowserWindow, dialog, ipcMain, shell, Menu } = require('electron')
const fs = require('node:fs')
const path = require('node:path')
const { ServiceManager } = require('./services.cjs')
const { Setup } = require('./setup.cjs')
const { Updater } = require('./updater.cjs')
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
  onChange: (list) => { send('services:changed', list); send('backend:status', backendPhase(list)) },
})
let autoStarting = false
let startingDetail = '' // shown while services start, e.g. while packages are updated after an app update
let updater = null
let setup = null // created once the app data folder is known

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
    const error = await shell.openPath(workspace.inside(workspaceRoot(), String(relative || '')))
    if (error) throw new Error(error)
    return true
  })
  handle('workspace:reveal', (relative) => {
    shell.showItemInFolder(workspace.inside(workspaceRoot(), String(relative || '')))
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

async function createWindow() {
  if (DEV) {
    appOrigin = DEV_URL
  } else {
    const started = await startServer({ root: path.join(__dirname, '..', 'dist'), backendUrl: BACKEND_URL, preferredPort: PREFERRED_PORT })
    server = started.server
    appOrigin = `http://127.0.0.1:${started.port}`
  }

  mainWindow = new BrowserWindow({
    width: 1440,
    height: 900,
    minWidth: 760,
    minHeight: 520,
    backgroundColor: '#0d1014',
    title: 'PockPock Agent',
    icon: path.join(__dirname, '..', 'public', process.platform === 'win32' ? 'icon.ico' : 'icon.png'),
    titleBarStyle: paths.IS_MAC ? 'hiddenInset' : 'hidden',
    titleBarOverlay: paths.IS_WIN ? { color: '#0d1014', symbolColor: '#aab4c2', height: 38 } : undefined,
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

  await mainWindow.loadURL(`${appOrigin}/`)
  services.watch()
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
