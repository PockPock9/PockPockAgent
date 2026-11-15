# Creates "PockPock Agent" shortcuts on the Desktop and in the Start menu.
# Run from the desktop folder after `npm install` and `npm run build`:
#   powershell -ExecutionPolicy Bypass -File scripts\create_shortcut.ps1
$ErrorActionPreference = 'Stop'
$appDir = Split-Path -Parent $PSScriptRoot
$electron = Join-Path $appDir 'node_modules\electron\dist\electron.exe'
if (-not (Test-Path $electron)) { throw "Electron is not installed. Run npm install in $appDir first." }
if (-not (Test-Path (Join-Path $appDir 'dist\index.html'))) { throw "The app is not built. Run npm run build in $appDir first." }
$shell = New-Object -ComObject WScript.Shell
$targets = @(
  (Join-Path ([Environment]::GetFolderPath('Desktop')) 'PockPock Agent.lnk'),
  (Join-Path ([Environment]::GetFolderPath('Programs')) 'PockPock Agent.lnk')
)
foreach ($path in $targets) {
  $link = $shell.CreateShortcut($path)
  $link.TargetPath = $electron
  $link.Arguments = '"' + $appDir + '"'
  $link.WorkingDirectory = $appDir
  $link.IconLocation = (Join-Path $appDir 'public\icon.ico')
  $link.Description = 'PockPock Agent desktop app'
  $link.Save()
  Write-Output "Created $path"
}
