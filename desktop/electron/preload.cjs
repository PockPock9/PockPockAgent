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
  openExternal: (url) => ipcRenderer.invoke('shell:openExternal', url),
  openPath: (target) => ipcRenderer.invoke('shell:openPath', target),
})
