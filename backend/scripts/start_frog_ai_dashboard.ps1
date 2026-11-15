param(
    [switch]$NoBrowser
)

$ErrorActionPreference = "Stop"

$projectRoot = Split-Path -Parent $PSScriptRoot  # backend
$repoRoot = Split-Path -Parent $projectRoot
$webRoot = Join-Path $repoRoot "frontend\app"
$pythonExe = Join-Path $repoRoot ".venv\Scripts\python.exe"
$apiScript = Join-Path $PSScriptRoot "frog_ai_server.py"
$viteCli = Join-Path $webRoot "node_modules\vite\bin\vite.js"
$dashboardUrl = "http://127.0.0.1:5173"
$apiHealthUrl = "http://127.0.0.1:8766/api/health"
$logRoot = Join-Path $env:LOCALAPPDATA "FrogAI\logs"
New-Item -ItemType Directory -Path $logRoot -Force | Out-Null
$startupLog = Join-Path $logRoot "startup.log"

. (Join-Path $PSScriptRoot "frog_ai_service_helpers.ps1")

if (-not (Test-Path -LiteralPath $pythonExe)) {
    Add-Content -LiteralPath $startupLog -Value "[$(Get-Date -Format s)] API dependencies are missing."
    throw "PockPock AI dependencies are not installed. Run .\backend\scripts\setup_frog_ai.ps1 first."
}
if (-not (Test-Path -LiteralPath $viteCli)) {
    Add-Content -LiteralPath $startupLog -Value "[$(Get-Date -Format s)] Frontend dependencies are missing."
    throw "PockPock AI frontend dependencies are missing. Run npm install in the frontend\app folder."
}

Start-FrogAiMicroservices -ProjectRoot $projectRoot -PythonExe $pythonExe -LogRoot $logRoot

$nodeCommand = Get-Command node.exe -ErrorAction SilentlyContinue
$nodeExe = if ($nodeCommand) { $nodeCommand.Source } else { $null }
if (-not $nodeExe) {
    $wingetRoot = Join-Path $env:LOCALAPPDATA "Microsoft\WinGet\Packages"
    if (Test-Path -LiteralPath $wingetRoot) {
        $nodePackages = Get-ChildItem -LiteralPath $wingetRoot -Directory -Filter "OpenJS.NodeJS*" -ErrorAction SilentlyContinue
        foreach ($package in $nodePackages) {
            $versions = Get-ChildItem -LiteralPath $package.FullName -Directory -ErrorAction SilentlyContinue
            foreach ($version in $versions) {
                $candidate = Join-Path $version.FullName "node.exe"
                if (Test-Path -LiteralPath $candidate) {
                    $nodeExe = $candidate
                    break
                }
            }
            if ($nodeExe) { break }
        }
    }
}
if (-not $nodeExe) {
    Add-Content -LiteralPath $startupLog -Value "[$(Get-Date -Format s)] Node.js was not found."
    throw "Node.js was not found. Install Node.js to start the PockPock AI dashboard."
}

function Test-PockPockApi {
    try {
        $health = Invoke-RestMethod -Uri $apiHealthUrl -TimeoutSec 2
        return $health.ok -eq $true -and $health.service -eq "PockPock AI"
    } catch {
        return $false
    }
}

function Test-PockPockDashboard {
    try {
        $response = Invoke-WebRequest -Uri $dashboardUrl -TimeoutSec 2 -UseBasicParsing
        return $response.StatusCode -eq 200 -and $response.Content.Contains("PockPock AI")
    } catch {
        return $false
    }
}

if (-not (Test-PockPockApi)) {
    $apiProcess = Start-Process -FilePath $pythonExe `
        -ArgumentList ('-u "{0}"' -f $apiScript) `
        -WorkingDirectory $projectRoot `
        -WindowStyle Hidden `
        -RedirectStandardOutput (Join-Path $logRoot "api.log") `
        -RedirectStandardError (Join-Path $logRoot "api-error.log") `
        -PassThru

    $apiReady = $false
    for ($attempt = 0; $attempt -lt 30; $attempt++) {
        Start-Sleep -Seconds 1
        if (Test-PockPockApi) {
            $apiReady = $true
            break
        }
        if ($apiProcess.HasExited) { break }
    }
    if (-not $apiReady) {
        $detail = if (Test-Path -LiteralPath (Join-Path $logRoot "api-error.log")) {
            Get-Content -LiteralPath (Join-Path $logRoot "api-error.log") -Tail 20
        } else {
            "The API process did not become ready."
        }
        Add-Content -LiteralPath $startupLog -Value "[$(Get-Date -Format s)] PockPock AI API failed to start. $detail"
        throw "PockPock AI API failed to start. Logs: $logRoot`n$detail"
    }
}

if (-not (Test-PockPockDashboard)) {
    $viteProcess = Start-Process -FilePath $nodeExe `
        -ArgumentList ('"{0}" --host 127.0.0.1 --port 5173 --strictPort' -f $viteCli) `
        -WorkingDirectory $webRoot `
        -WindowStyle Hidden `
        -RedirectStandardOutput (Join-Path $logRoot "web.log") `
        -RedirectStandardError (Join-Path $logRoot "web-error.log") `
        -PassThru

    $dashboardReady = $false
    for ($attempt = 0; $attempt -lt 30; $attempt++) {
        Start-Sleep -Seconds 1
        if (Test-PockPockDashboard) {
            $dashboardReady = $true
            break
        }
        if ($viteProcess.HasExited) { break }
    }
    if (-not $dashboardReady) {
        $detail = if (Test-Path -LiteralPath (Join-Path $logRoot "web-error.log")) {
            Get-Content -LiteralPath (Join-Path $logRoot "web-error.log") -Tail 20
        } else {
            "The dashboard process did not become ready."
        }
        Add-Content -LiteralPath $startupLog -Value "[$(Get-Date -Format s)] PockPock AI dashboard failed to start. $detail"
        throw "PockPock AI dashboard failed to start. Logs: $logRoot`n$detail"
    }
}

Add-Content -LiteralPath $startupLog -Value "[$(Get-Date -Format s)] PockPock AI API and dashboard are ready."
if (-not $NoBrowser) {
    Start-Process $dashboardUrl
}
