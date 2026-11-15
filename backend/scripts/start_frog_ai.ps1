$ErrorActionPreference = "Stop"

$projectRoot = Split-Path -Parent $PSScriptRoot  # backend
$repoRoot = Split-Path -Parent $projectRoot
$venvPython = Join-Path $repoRoot ".venv\Scripts\python.exe"
$serverScript = Join-Path $PSScriptRoot "frog_ai_server.py"
$logRoot = Join-Path $env:LOCALAPPDATA "FrogAI\logs"
New-Item -ItemType Directory -Path $logRoot -Force | Out-Null

if (-not (Test-Path -LiteralPath $venvPython)) {
    throw "Frog AI dependencies are not installed. Run .\backend\scripts\setup_frog_ai.ps1 first."
}

. (Join-Path $PSScriptRoot "frog_ai_service_helpers.ps1")
Start-FrogAiMicroservices -ProjectRoot $projectRoot -PythonExe $venvPython -LogRoot $logRoot

& $venvPython $serverScript
exit $LASTEXITCODE
