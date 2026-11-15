function Start-FrogAiMicroservices {
    param(
        [Parameter(Mandatory = $true)][string]$ProjectRoot,
        [Parameter(Mandatory = $true)][string]$PythonExe,
        [Parameter(Mandatory = $true)][string]$LogRoot
    )

    $tokenPath = Join-Path $env:LOCALAPPDATA "FrogAI\services.token"
    $tokenDirectory = Split-Path -Parent $tokenPath
    New-Item -ItemType Directory -Path $tokenDirectory -Force | Out-Null
    if (-not (Test-Path -LiteralPath $tokenPath)) {
        [System.IO.File]::WriteAllText($tokenPath, [guid]::NewGuid().ToString("N"))
    }
    $env:POCKPOCK_INTERNAL_TOKEN = (Get-Content -LiteralPath $tokenPath -Raw).Trim()
    if (-not $env:POCKPOCK_INTERNAL_TOKEN) {
        throw "The local service authentication token is empty: $tokenPath"
    }
    $env:POCKPOCK_PLANNER_URL = "http://127.0.0.1:8771"
    $env:POCKPOCK_VALIDATOR_URL = "http://127.0.0.1:8772"
    $env:POCKPOCK_RUN_STORE_URL = "http://127.0.0.1:8773"
    $env:POCKPOCK_BROWSER_AUTOMATION_URL = "http://127.0.0.1:8774"

    $services = @(
        @{ Name = "planner"; Port = 8771; Directory = "planner" },
        @{ Name = "validator"; Port = 8772; Directory = "validator" },
        @{ Name = "run-store"; Port = 8773; Directory = "run_store" },
        @{ Name = "browser-automation"; Port = 8774; Directory = "browser_automation" }
    )
    foreach ($service in $services) {
        $healthUrl = "http://127.0.0.1:$($service.Port)/health"
        $healthy = $false
        try {
            $health = Invoke-RestMethod -Uri $healthUrl -TimeoutSec 2
            $healthy = $health.ok -eq $true
        } catch {
            $healthy = $false
        }
        if (-not $healthy) {
            $serviceDirectory = Join-Path $ProjectRoot "projects\$($service.Directory)"
            $serviceLog = Join-Path $LogRoot "$($service.Name).log"
            $serviceErrorLog = Join-Path $LogRoot "$($service.Name)-error.log"
            $null = Start-Process -FilePath $PythonExe `
                -ArgumentList @("-m", "uvicorn", "app:app", "--host", "127.0.0.1", "--port", "$($service.Port)") `
                -WorkingDirectory $serviceDirectory `
                -WindowStyle Hidden `
                -RedirectStandardOutput $serviceLog `
                -RedirectStandardError $serviceErrorLog `
                -PassThru
            for ($attempt = 0; $attempt -lt 30; $attempt++) {
                Start-Sleep -Seconds 1
                try {
                    $health = Invoke-RestMethod -Uri $healthUrl -TimeoutSec 2
                    $healthy = $health.ok -eq $true
                } catch {
                    $healthy = $false
                }
                if ($healthy) { break }
            }
        }
        if (-not $healthy) {
            $detail = if (Test-Path -LiteralPath $serviceErrorLog) { Get-Content -LiteralPath $serviceErrorLog -Tail 20 } else { "Service did not become ready." }
            throw "PockPock $($service.Name) service failed to start. Logs: $serviceErrorLog`n$detail"
        }
    }
}
