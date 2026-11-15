// PockPock Agent desktop app: window, local server, backend supervision, and the narrow IPC
// surface the renderer may use (session storage, workspace files, terminal, shell helpers).
const { app, BrowserWindow, dialog, ipcMain, shell, Menu } = require('electron')
const fs = require('node:fs')
const path = require('node:path')
const { Backend } = require('./backend.cjs')
const { startServer } = require('./server.cjs')
const workspace = require('./workspace.cjs')
const { Terminals } = require('./terminal.cjs')

const DEV = process.env.POCKPOCK_DESKTOP_DEV === '1'
const DEV_URL = 'http://127.0.0.1:5180'
const BACKEND_URL = process.env.POCKPOCK_BACKEND_URL || 'http://127.0.0.1:8766'
const REPO_ROOT = process.env.POCKPOCK_ROOT || path.resolve(__dirname, '..', '..')
const PREFERRED_PORT = 8790
const MAX_STORE_BYTES = 20 * 1024 * 1024
const STORE_KEYS = new Set(['sessions', 'settings'])

// Tests point the app at a throwaway data folder so they never touch real chats.
if (process.env.POCKPOCK_DESKTOP_USER_DATA) app.setPath('userData', process.env.POCKPOCK_DESKTOP_USER_DATA)

let mainWindow = null
let appOrigin = ''
let server = null
const backend = new Backend({ backendUrl: BACKEND_URL, repoRoot: REPO_ROOT, onStatus: (state) => send('backend:status', state) })
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
    repoRoot: REPO_ROOT,
    backendUrl: BACKEND_URL,
    terminal: terminals.available(),
    backend: backend.state,
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

  handle('backend:retry', () => backend.ensure())
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
    titleBarStyle: 'hidden',
    titleBarOverlay: process.platform === 'win32' ? { color: '#0d1014', symbolColor: '#aab4c2', height: 38 } : undefined,
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
  void backend.ensure()
}

if (!app.requestSingleInstanceLock()) {
  app.quit()
} else {
  app.on('second-instance', () => {
    if (mainWindow) { if (mainWindow.isMinimized()) mainWindow.restore(); mainWindow.focus() }
  })
  app.whenReady().then(() => {
    if (process.platform === 'win32') app.setAppUserModelId('ai.pockpock.agent')
    Menu.setApplicationMenu(null)
    registerIpc()
    return createWindow()
  })
  app.on('window-all-closed', () => app.quit())
  app.on('before-quit', () => {
    terminals.killAll()
    backend.stop()
    server?.close()
  })
}
