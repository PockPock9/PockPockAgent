/**
 * Installs the `pockpock-code` terminal command (PockPock Code, backend/projects/coding_cli).
 *
 * The command is a small launcher that runs the app's own Python with the bundled backend, so it
 * always matches the installed version. Windows: %LOCALAPPDATA%\PockPock\bin\pockpock-code.cmd, with
 * that folder added to the user's PATH once. macOS and Linux: ~/.local/bin/pockpock-code, with the
 * folder added to ~/.zprofile (macOS) when it is not on PATH. Written at every start (a no-op when
 * unchanged), so an app update or a moved install is picked up.
 */
const fs = require('node:fs')
const os = require('node:os')
const path = require('node:path')
const { execFile } = require('node:child_process')

function launcherText({ python, backend, platform = process.platform }) {
  const script = path.join(backend, 'scripts', 'pockpock_code.py')
  if (platform === 'win32') return `@echo off\r\n"${python}" "${script}" %*\r\n`
  return `#!/bin/sh\nexec "${python}" "${script}" "$@"\n`
}

function binDir({ dataRoot, platform = process.platform, home = os.homedir() }) {
  return platform === 'win32' ? path.join(dataRoot, 'bin') : path.join(home, '.local', 'bin')
}

function writeIfChanged(file, text, mode) {
  try { if (fs.readFileSync(file, 'utf8') === text) return false } catch { /* new file */ }
  fs.mkdirSync(path.dirname(file), { recursive: true })
  fs.writeFileSync(file, text, mode ? { mode } : undefined)
  if (mode) fs.chmodSync(file, mode)
  return true
}

/** Adds dir to the user's PATH (Windows registry, via PowerShell; never setx, which truncates). */
function addToWindowsPath(dir) {
  const script = `$d='${dir.replace(/'/g, "''")}'; $p=[Environment]::GetEnvironmentVariable('Path','User'); if (-not $p) { $p='' }; ` +
    `if (-not (($p -split ';') -contains $d)) { [Environment]::SetEnvironmentVariable('Path', (($p.TrimEnd(';') + ';' + $d).TrimStart(';')), 'User') }`
  return new Promise((resolve) => execFile('powershell.exe', ['-NoProfile', '-NonInteractive', '-Command', script], { windowsHide: true, timeout: 20000 }, (error) => resolve(!error)))
}

function addToShellProfile(dir, home = os.homedir()) {
  if ((process.env.PATH || '').split(path.delimiter).includes(dir)) return false
  const profile = path.join(home, '.zprofile')
  const line = 'export PATH="$HOME/.local/bin:$PATH"  # added by PockPock for pockpock-code'
  let text = ''
  try { text = fs.readFileSync(profile, 'utf8') } catch { /* none yet */ }
  if (text.includes('.local/bin')) return false
  fs.appendFileSync(profile, `${text && !text.endsWith('\n') ? '\n' : ''}${line}\n`)
  return true
}

/** Writes the launcher and makes sure its folder is on PATH. Returns where it is. */
async function installCommand({ python, backend, dataRoot, platform = process.platform }) {
  if (!fs.existsSync(python) || !fs.existsSync(path.join(backend, 'scripts', 'pockpock_code.py'))) return null
  const dir = binDir({ dataRoot, platform })
  const file = path.join(dir, platform === 'win32' ? 'pockpock-code.cmd' : 'pockpock-code')
  const changed = writeIfChanged(file, launcherText({ python, backend, platform }), platform === 'win32' ? undefined : 0o755)
  const marker = path.join(dataRoot, 'bin', '.path-added')
  if (!fs.existsSync(marker)) {
    const added = platform === 'win32' ? await addToWindowsPath(dir) : (addToShellProfile(dir), true)
    if (added) writeIfChanged(marker, new Date().toISOString())
  }
  return { file, changed }
}

module.exports = { installCommand, launcherText, binDir }
