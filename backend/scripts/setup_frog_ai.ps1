$ErrorActionPreference = "Stop"

$projectRoot = Split-Path -Parent $PSScriptRoot  # backend
$repoRoot = Split-Path -Parent $projectRoot
$pythonExe = "C:\Users\kchan\AppData\Local\Programs\Python\Python312\python.exe"
if (-not (Test-Path -LiteralPath $pythonExe)) {
    $pythonCommand = Get-Command python -ErrorAction SilentlyContinue
    if (-not $pythonCommand) {
        throw "Python 3.12 was not found. Update pythonExe in this setup script."
    }
    $pythonExe = $pythonCommand.Source
}

$venvPython = Join-Path $repoRoot ".venv\Scripts\python.exe"
if (-not (Test-Path -LiteralPath $venvPython)) {
    & $pythonExe -m venv (Join-Path $repoRoot ".venv")
    if ($LASTEXITCODE -ne 0) { throw "Could not create the Frog AI Python environment." }
}

& $venvPython -m pip install --upgrade pip
if ($LASTEXITCODE -ne 0) { throw "Could not update pip in the Frog AI environment." }
& $venvPython -m pip install -r (Join-Path $PSScriptRoot "requirements-frog-ai.txt")
if ($LASTEXITCODE -ne 0) { throw "Could not install Frog AI API dependencies." }

& $venvPython -m pip install -r (Join-Path $projectRoot "projects\browser_automation\requirements.txt")
if ($LASTEXITCODE -ne 0) { throw "Could not install browser automation dependencies." }
& $venvPython -m playwright install chromium
if ($LASTEXITCODE -ne 0) { throw "Could not install the isolated Chromium runtime. Check network access and rerun setup." }

Write-Host "Frog AI API dependencies installed in $($repoRoot)\.venv" -ForegroundColor Green
Write-Host "Start the application with .\backend\scripts\start_frog_ai.ps1" -ForegroundColor Green
