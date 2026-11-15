$ErrorActionPreference = "Stop"

$projectRoot = Split-Path -Parent $PSScriptRoot
$startScript = Join-Path $PSScriptRoot "start_frog_ai_dashboard.ps1"
$tailscaleExe = Join-Path $env:ProgramFiles "Tailscale\tailscale.exe"
$apiHealthUrl = "http://127.0.0.1:8766/api/health"
$dashboardUrl = "http://127.0.0.1:8766/"

if (-not (Test-Path -LiteralPath $tailscaleExe)) {
    throw "Tailscale is not installed. Install Tailscale and sign in before configuring remote access."
}

$tailnetStatus = & $tailscaleExe status 2>&1
if ($LASTEXITCODE -ne 0 -or ($tailnetStatus -join "`n") -match "Logged out") {
    throw "This PC is not connected to Tailscale. Sign in with .\tailscale.exe up, then rerun this script."
}

$ready = $false
try {
    $health = Invoke-RestMethod -Uri $apiHealthUrl -TimeoutSec 2
    $ready = $health.ok -eq $true -and $health.service -eq "PockPock AI"
} catch {
    $ready = $false
}

if (-not $ready) {
    & "$PSHOME\powershell.exe" -NoProfile -ExecutionPolicy Bypass -File $startScript -NoBrowser
    if ($LASTEXITCODE -ne 0) {
        throw "Could not start PockPock AI. Check %LOCALAPPDATA%\FrogAI\logs."
    }
}

try {
    $page = Invoke-WebRequest -Uri $dashboardUrl -TimeoutSec 5 -UseBasicParsing
} catch {
    throw "The production dashboard is not being served by PockPock AI. Build it with npm run build in the frontend\app folder, then restart PockPock AI."
}
if ($page.StatusCode -ne 200 -or -not $page.Content.Contains('id="root"')) {
    throw "The production dashboard is not available. Build it with npm run build in the frontend\app folder, then restart PockPock AI."
}

$existingConfig = & $tailscaleExe serve status 2>&1
if ($LASTEXITCODE -ne 0) {
    throw "Could not inspect existing Tailscale Serve configuration: $($existingConfig -join "`n")"
}
$existingText = $existingConfig -join "`n"
if ($existingText -match "No serve config") {
    & $tailscaleExe serve --bg --yes "127.0.0.1:8766"
    if ($LASTEXITCODE -ne 0) {
        throw "Tailscale Serve could not be configured: $($existingText -join "`n")"
    }
} elseif ($existingText -notmatch "127\.0\.0\.1:8766") {
    throw "This PC already has a different Tailscale Serve configuration. Nothing was changed. Review it with 'tailscale serve status' before choosing how to combine routes."
}

$serveStatus = & $tailscaleExe serve status 2>&1
if ($LASTEXITCODE -ne 0) {
    throw "Could not verify the Tailscale Serve configuration."
}

Write-Host "PockPock AI is served over your private Tailscale network only." -ForegroundColor Green
Write-Host "No Tailscale Funnel or Windows firewall rule was enabled." -ForegroundColor Green
Write-Host "Install Tailscale and sign in to the same tailnet on each device that needs access." -ForegroundColor Green
Write-Host ($serveStatus -join "`n")
