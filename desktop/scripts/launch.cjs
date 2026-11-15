// Starts the app with a clean environment. Editors such as VS Code set ELECTRON_RUN_AS_NODE in
// their terminals, which would make Electron run as plain Node instead of opening a window.
const { spawn } = require('node:child_process')
const path = require('node:path')

const electron = require('electron')
const env = { ...process.env }
delete env.ELECTRON_RUN_AS_NODE
const child = spawn(electron, [path.join(__dirname, '..'), ...process.argv.slice(2)], { env, stdio: 'inherit', windowsHide: false })
child.on('exit', (code) => process.exit(code ?? 0))
