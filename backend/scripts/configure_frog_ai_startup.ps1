param(
    [switch]$Remove
)

$ErrorActionPreference = "Stop"

$startupFolder = [Environment]::GetFolderPath("Startup")
$shortcutPath = Join-Path $startupFolder "PockPock AI Dashboard.lnk"
$legacyShortcutPath = Join-Path $startupFolder "Frog AI Dashboard.lnk"
$projectRoot = Split-Path -Parent $PSScriptRoot
$launcher = Join-Path $PSScriptRoot "start_frog_ai_dashboard.ps1"
$powershellExe = Join-Path $PSHOME "powershell.exe"

if ($Remove) {
    $shell = New-Object -ComObject WScript.Shell
    foreach ($path in @($shortcutPath, $legacyShortcutPath)) {
        if (-not (Test-Path -LiteralPath $path)) { continue }
        $existingShortcut = $shell.CreateShortcut($path)
        if ($existingShortcut.TargetPath -ne $powershellExe -or $existingShortcut.Arguments -notlike "*$launcher*") {
            throw "The Startup shortcut exists but does not point to this PockPock AI launcher. It was not removed."
        }
        Remove-Item -LiteralPath $path -Force
    }
    Write-Host "PockPock AI will no longer start automatically when you sign in." -ForegroundColor Yellow
    exit 0
}

if (-not (Test-Path -LiteralPath $launcher)) {
    throw "PockPock AI dashboard launcher was not found: $launcher"
}

$shell = New-Object -ComObject WScript.Shell
$shortcut = $shell.CreateShortcut($shortcutPath)
$shortcut.TargetPath = $powershellExe
$shortcut.Arguments = '-NoProfile -WindowStyle Hidden -ExecutionPolicy Bypass -File "{0}"' -f $launcher
$shortcut.WorkingDirectory = $projectRoot
$shortcut.Description = "Start the PockPock AI local dashboard at Windows sign-in."
$shortcut.Save()

if (Test-Path -LiteralPath $legacyShortcutPath) {
    $legacyShortcut = $shell.CreateShortcut($legacyShortcutPath)
    if ($legacyShortcut.TargetPath -ne $powershellExe -or $legacyShortcut.Arguments -notlike "*$launcher*") {
        throw "The legacy Startup shortcut exists but does not point to this app. It was not removed."
    }
    Remove-Item -LiteralPath $legacyShortcutPath -Force
}

Write-Host "PockPock AI will start at Windows sign-in and open the dashboard in your browser." -ForegroundColor Green
Write-Host "To disable startup, run .\backend\scripts\configure_frog_ai_startup.ps1 -Remove" -ForegroundColor Green
