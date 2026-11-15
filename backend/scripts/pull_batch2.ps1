$env:Path = [System.Environment]::GetEnvironmentVariable("Path","Machine") + ";" + [System.Environment]::GetEnvironmentVariable("Path","User")

# Ensure server is running
Get-Process -Name "ollama*" -ErrorAction SilentlyContinue | Stop-Process -Force -ErrorAction SilentlyContinue
Start-Sleep -Seconds 2
$job = Start-Job -ScriptBlock { 
    $env:Path = [System.Environment]::GetEnvironmentVariable("Path","Machine") + ";" + [System.Environment]::GetEnvironmentVariable("Path","User")
    & ollama serve 2>&1 
}
for ($i = 0; $i -lt 20; $i++) {
    Start-Sleep -Seconds 2
    try { Invoke-WebRequest -Uri "http://localhost:11434/" -UseBasicParsing -TimeoutSec 3 | Out-Null; Write-Host "API UP"; break } catch { Write-Host "Waiting... ($($i+1))" }
}

$models = @(
    @{ name = "nomic-embed-text"; desc = "Embedding Model for RAG (~275MB)" },
    @{ name = "llava:7b"; desc = "Vision Model (~4.7GB)" },
    @{ name = "qwen2.5-coder:1.5b"; desc = "Autocomplete Model (~1GB)" },
    @{ name = "dolphin-mistral:7b"; desc = "Uncensored Model (~4.1GB)" },
    @{ name = "reader-lm:1.5b"; desc = "HTML-to-Markdown Model (~1GB)" },
    @{ name = "mistral-nemo:12b"; desc = "Agentic Tool-Calling Model (~7.1GB)" },
    @{ name = "llama3.2:3b"; desc = "Lightweight Agent Model (~2GB)" }
)

$total = $models.Count
$done = 0

foreach ($m in $models) {
    $done++
    Write-Host "`n=== [$done/$total] Pulling $($m.name) ($($m.desc)) ==="
    try {
        $body = "{`"name`":`"$($m.name)`",`"stream`":false}"
        $r = Invoke-WebRequest -Uri "http://localhost:11434/api/pull" -Method POST -Body $body -ContentType "application/json" -UseBasicParsing -TimeoutSec 1800
        Write-Host "$($m.name) DONE: $($r.Content)"
    } catch {
        Write-Host "ERROR pulling $($m.name): $_"
    }
}

Write-Host "`n=== ALL MODELS COMPLETE ==="

# List all models
Write-Host "`n=== FULL MODEL INVENTORY ==="
$tags = Invoke-WebRequest -Uri "http://localhost:11434/api/tags" -UseBasicParsing -TimeoutSec 10
$tagData = $tags.Content | ConvertFrom-Json
foreach ($model in $tagData.models) {
    $sizeGB = [math]::Round($model.size / 1GB, 2)
    Write-Host "$($model.name) - ${sizeGB}GB"
}
