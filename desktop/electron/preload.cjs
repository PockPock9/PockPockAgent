// The only bridge between the page and the main process. Exposes named calls, never ipcRenderer.
const { contextBridge, ipcRenderer } = require('electron')

function subscribe(channel, callback) {
  const listener = (_event, ...args) => callback(...args)
  ipcRenderer.on(channel, listener)
  return () => ipcRenderer.removeListener(channel, listener)
}

contextBridge.exposeInMainWorld('pockpock', {
  info: () => ipcRenderer.invoke('app:info'),
  store: {
    get: (key) => ipcRenderer.invoke('store:get', key),
    set: (key, value) => ipcRenderer.invoke('store:set', key, value),
  },
  workspace: {
    choose: () => ipcRenderer.invoke('workspace:choose'),
    list: (relative) => ipcRenderer.invoke('workspace:list', relative),
    read: (relative) => ipcRenderer.invoke('workspace:read', relative),
    open: (relative) => ipcRenderer.invoke('workspace:open', relative),
    reveal: (relative) => ipcRenderer.invoke('workspace:reveal', relative),
  },
  terminal: {
    create: (options) => ipcRenderer.invoke('terminal:create', options),
    write: (id, data) => ipcRenderer.invoke('terminal:write', id, data),
    resize: (id, cols, rows) => ipcRenderer.invoke('terminal:resize', id, cols, rows),
    kill: (id) => ipcRenderer.invoke('terminal:kill', id),
    onData: (callback) => subscribe('terminal:data', callback),
    onExit: (callback) => subscribe('terminal:exit', callback),
  },
  backend: {
    retry: () => ipcRenderer.invoke('backend:retry'),
    onStatus: (callback) => subscribe('backend:status', callback),
  },
  services: {
    list: () => ipcRenderer.invoke('services:list'),
    start: (id) => ipcRenderer.invoke('services:start', id),
    stop: (id) => ipcRenderer.invoke('services:stop', id),
    restart: (id) => ipcRenderer.invoke('services:restart', id),
    logs: (id) => ipcRenderer.invoke('services:logs', id),
    openLogs: () => ipcRenderer.invoke('services:openLogs'),
    onChange: (callback) => subscribe('services:changed', callback),
  },
  setup: {
    status: () => ipcRenderer.invoke('setup:status'),
    start: (plan) => ipcRenderer.invoke('setup:start', plan),
    cancel: () => ipcRenderer.invoke('setup:cancel'),
    onEvent: (callback) => subscribe('setup:event', callback),
  },
  updates: {
    state: () => ipcRenderer.invoke('updates:state'),
    check: () => ipcRenderer.invoke('updates:check'),
    download: () => ipcRenderer.invoke('updates:download'),
    install: () => ipcRenderer.invoke('updates:install'),
    onChange: (callback) => subscribe('updates:state', callback),
  },
  openclaw: {
    browsers: () => ipcRenderer.invoke('openclaw:browsers'),
    setBrowser: (id) => ipcRenderer.invoke('openclaw:setBrowser', id),
    slowModels: () => ipcRenderer.invoke('openclaw:slowModels'),
    allowSlowModels: () => ipcRenderer.invoke('openclaw:allowSlowModels'),
  },
  connectors: {
    list: () => ipcRenderer.invoke('connectors:list'),
    connect: (id, values) => ipcRenderer.invoke('connectors:connect', id, values),
    disconnect: (id) => ipcRenderer.invoke('connectors:disconnect', id),
    onChange: (callback) => subscribe('connectors:changed', callback),
  },
  cloud: {
    list: () => ipcRenderer.invoke('cloud:list'),
    connect: (id, input) => ipcRenderer.invoke('cloud:connect', id, input),
    available: (id) => ipcRenderer.invoke('cloud:available', id),
    setModels: (id, models) => ipcRenderer.invoke('cloud:setModels', id, models),
    disconnect: (id) => ipcRenderer.invoke('cloud:disconnect', id),
    onChange: (callback) => subscribe('cloud:changed', callback),
  },
  maintenance: {
    status: () => ipcRenderer.invoke('maintenance:status'),
    agents: () => ipcRenderer.invoke('maintenance:agents'),
    setAgent: (choice) => ipcRenderer.invoke('maintenance:setAgent', choice),
    connectAgent: (id) => ipcRenderer.invoke('maintenance:connectAgent', id),
    cancelConnect: () => ipcRenderer.invoke('maintenance:cancelConnect'),
    github: () => ipcRenderer.invoke('maintenance:github'),
    githubLogin: () => ipcRenderer.invoke('maintenance:githubLogin'),
    cancelLogin: () => ipcRenderer.invoke('maintenance:cancelLogin'),
    chooseFolder: (current) => ipcRenderer.invoke('maintenance:chooseFolder', current),
    clone: (dir) => ipcRenderer.invoke('maintenance:clone', dir),
    forget: () => ipcRenderer.invoke('maintenance:forget'),
    setAuto: (enabled) => ipcRenderer.invoke('maintenance:setAuto', enabled),
    fixGet: (reportId) => ipcRenderer.invoke('maintenance:fixGet', reportId),
    fixStart: (reportId) => ipcRenderer.invoke('maintenance:fixStart', reportId),
    fixCancel: (reportId) => ipcRenderer.invoke('maintenance:fixCancel', reportId),
    fixApprove: (reportId, text) => ipcRenderer.invoke('maintenance:fixApprove', reportId, text),
    fixDiscard: (reportId) => ipcRenderer.invoke('maintenance:fixDiscard', reportId),
    onEvent: (callback) => subscribe('maintenance:event', callback),
  },
  reports: {
    preview: (capture) => ipcRenderer.invoke('reports:preview', capture),
    create: (input) => ipcRenderer.invoke('reports:create', input),
    list: () => ipcRenderer.invoke('reports:list'),
    get: (id) => ipcRenderer.invoke('reports:get', id),
    update: (id, change) => ipcRenderer.invoke('reports:update', id, change),
    delete: (id) => ipcRenderer.invoke('reports:delete', id),
  },
  theme: {
    set: (id) => ipcRenderer.invoke('theme:set', id),
  },
  setLoginItem: (enabled) => ipcRenderer.invoke('app:setLoginItem', enabled),
  openExternal: (url) => ipcRenderer.invoke('shell:openExternal', url),
  openPath: (target) => ipcRenderer.invoke('shell:openPath', target),
})
