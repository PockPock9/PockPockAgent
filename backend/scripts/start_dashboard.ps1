$ErrorActionPreference = "Stop"

$pythonExe = "C:\Users\kchan\AppData\Local\Programs\Python\Python312\python.exe"
if (-not (Test-Path $pythonExe)) {
    $scriptPath = Join-Path $PSScriptRoot "observability_dashboard.py"
    $pyCommand = Get-Command py -ErrorAction SilentlyContinue
    if ($pyCommand) {
        & $pyCommand.Source -3.12 $scriptPath
        if ($LASTEXITCODE -eq 0) {
            exit 0
        }
    }

    $pythonCommand = Get-Command python -ErrorAction SilentlyContinue
    if ($pythonCommand) {
        & $pythonCommand.Source $scriptPath
        exit $LASTEXITCODE
    }

    throw "Python 3.12 was not found. Install Python or update pythonExe in this script."
}

& $pythonExe (Join-Path $PSScriptRoot "observability_dashboard.py")
exit $LASTEXITCODE
