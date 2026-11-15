param(
    [Parameter(Mandatory = $true)]
    [ValidatePattern('^[a-p]{32}$')]
    [string]$ExtensionId
)

$ErrorActionPreference = 'Stop'
$moduleRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$installDirectory = Join-Path $env:LOCALAPPDATA 'FrogAI\chrome-companion'
$hostPath = Join-Path $installDirectory 'pockpock_chrome_companion.exe'
$temporaryHostPath = Join-Path $installDirectory ('pockpock_chrome_companion.' + [guid]::NewGuid().ToString('N') + '.exe')
$hostManifestPath = Join-Path $installDirectory 'native-host-manifest.json'
$extensionIdPath = Join-Path $installDirectory 'extension-id.txt'
$registryPath = 'HKCU:\Software\Google\Chrome\NativeMessagingHosts\com.pockpock.chrome_companion'

New-Item -ItemType Directory -Path $installDirectory -Force | Out-Null
try {
    Add-Type -Path (Join-Path $moduleRoot 'native_host.cs') `
        -ReferencedAssemblies 'System.Web.Extensions.dll' `
        -OutputType ConsoleApplication `
        -OutputAssembly $temporaryHostPath

    if (Test-Path -LiteralPath $hostPath) {
        Remove-Item -LiteralPath $hostPath -Force
    }
    Move-Item -LiteralPath $temporaryHostPath -Destination $hostPath

    [System.IO.File]::WriteAllText(
        $extensionIdPath,
        $ExtensionId,
        (New-Object System.Text.UTF8Encoding($false))
    )

    $manifest = [ordered]@{
        name = 'com.pockpock.chrome_companion'
        description = 'PockPock AI explicitly paired Chrome tab companion'
        path = $hostPath
        type = 'stdio'
        allowed_origins = @("chrome-extension://$ExtensionId/")
    }
    $manifestJson = $manifest | ConvertTo-Json -Depth 4
    [System.IO.File]::WriteAllText(
        $hostManifestPath,
        $manifestJson,
        (New-Object System.Text.UTF8Encoding($false))
    )

    New-Item -Path $registryPath -Force | Out-Null
    Set-Item -Path $registryPath -Value $hostManifestPath

    Write-Output "Registered PockPock Chrome companion for extension $ExtensionId."
}
finally {
    if (Test-Path -LiteralPath $temporaryHostPath) {
        Remove-Item -LiteralPath $temporaryHostPath -Force
    }
}
