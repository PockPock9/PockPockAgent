# Quick Service Launcher for Local AI Control Center
# Hardware: RTX 4070 SUPER, Ryzen 7 7800X3D, 32GB RAM

$env:Path = [System.Environment]::GetEnvironmentVariable("Path","Machine") + ";" + [System.Environment]::GetEnvironmentVariable("Path","User")
$pythonExe = "C:\Users\kchan\AppData\Local\Programs\Python\Python312\python.exe"

Write-Host "========================================" -ForegroundColor Cyan
Write-Host "   🚀 Local AI Control Center Startup   " -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan

# 1. Check/Start Ollama
$ollamaProc = Get-Process -Name "ollama*" -ErrorAction SilentlyContinue
if (-not $ollamaProc) {
    Write-Host "[1/2] Starting Ollama server in background..." -ForegroundColor Yellow
    Start-Process -FilePath "ollama" -ArgumentList "serve" -WindowStyle Hidden
    Start-Sleep -Seconds 3
} else {
    Write-Host "[1/2] Ollama server is already running." -ForegroundColor Green
}

# Test Ollama API
try {
    $apiTest = Invoke-WebRequest -Uri "http://localhost:11434/" -UseBasicParsing -TimeoutSec 3
    Write-Host "  -> Ollama API responding at http://localhost:11434" -ForegroundColor Green
} catch {
    Write-Host "  -> Ollama is still initializing..." -ForegroundColor Yellow
}

# 2. Check/Start Open WebUI
Write-Host "[2/2] Checking Open WebUI dashboard..." -ForegroundColor Yellow
$owuiInstalled = & $pythonExe -m pip list | Select-String "open-webui"
if (-not $owuiInstalled) {
    Write-Host "  -> Installing Open WebUI via pip (first run)..." -ForegroundColor Yellow
    & $pythonExe -m pip install open-webui
}

Write-Host "  -> Starting Open WebUI on http://localhost:3000 ..." -ForegroundColor Green
& $pythonExe -m open_webui serve --port 3000
