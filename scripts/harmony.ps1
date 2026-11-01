param(
    [ValidateSet('doctor', 'build', 'check')]
    [string]$Command = 'doctor',
    [string]$ToolchainRoot = ''
)

$ErrorActionPreference = 'Stop'
$projectRoot = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
$privateRoot = Join-Path $projectRoot 'data\private\toolchains'
$nodeInfoPath = Join-Path $privateRoot 'node-install.json'
$javaInfoPath = Join-Path $privateRoot 'jdk-install.json'
$sdkInfoPath = Join-Path $privateRoot 'sdk-install.json'
$cliPath = Join-Path $privateRoot 'deveco-cli\node_modules\@deveco\deveco-cli\cli.js'

if (-not (Test-Path -LiteralPath $nodeInfoPath) -or -not (Test-Path -LiteralPath $javaInfoPath)) {
    throw 'Project-local Node.js and JDK have not been prepared.'
}
$nodeInfo = Get-Content -LiteralPath $nodeInfoPath -Raw -Encoding utf8 | ConvertFrom-Json
$javaInfo = Get-Content -LiteralPath $javaInfoPath -Raw -Encoding utf8 | ConvertFrom-Json
$nodeExe = Join-Path $nodeInfo.path 'node.exe'
$javaExe = Join-Path $javaInfo.path 'bin\java.exe'

if ($ToolchainRoot) {
    $resolvedRoot = (Resolve-Path -LiteralPath $ToolchainRoot).Path
    $sdkMetadata = Join-Path $resolvedRoot 'sdk\default\openharmony\ets\oh-uni-package.json'
    if (-not (Test-Path -LiteralPath $sdkMetadata)) {
        throw 'Select the DevEco Studio or Command Line Tools root containing sdk/default.'
    }
    $metadata = Get-Content -LiteralPath $sdkMetadata -Raw -Encoding utf8 | ConvertFrom-Json
    if ([string]$metadata.apiVersion -ne '26') { throw 'This project requires the API 26 toolchain.' }
    if (Test-Path -LiteralPath (Join-Path $resolvedRoot 'tools\hvigor')) {
        $kind = 'studio'
    } elseif (Test-Path -LiteralPath (Join-Path $resolvedRoot 'hvigor')) {
        $kind = 'command-line-tools'
    } else {
        throw 'The SDK directory is present, but its matching Hvigor build tools are missing.'
    }
    @{ path = $resolvedRoot; kind = $kind; apiVersion = 26; platformVersion = $metadata.platformVersion } |
        ConvertTo-Json | Set-Content -LiteralPath $sdkInfoPath -Encoding utf8
}

$sdk = $null
if (Test-Path -LiteralPath $sdkInfoPath) {
    $sdk = Get-Content -LiteralPath $sdkInfoPath -Raw -Encoding utf8 | ConvertFrom-Json
}

if ($Command -eq 'doctor') {
    & $nodeExe --version
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
    & $javaExe -version
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
    & $nodeExe $cliPath --version
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
    if ($null -eq $sdk) {
        Write-Output 'SDK status: not installed. Supply the official API 26 archive to finish setup.'
        exit 2
    }
    Write-Output ('SDK status: API ' + $sdk.apiVersion + ' at ' + $sdk.path)
    exit 0
}

if ($null -eq $sdk) { throw 'Register the installed API 26 toolchain with -ToolchainRoot first.' }
$env:JAVA_HOME = $javaInfo.path
$env:Path = $nodeInfo.path + ';' + (Join-Path $javaInfo.path 'bin') + ';' + $env:Path
if ($sdk.kind -eq 'studio') {
    $env:DEVECO_CLI_STUDIO_PATH = $sdk.path
} else {
    $env:DEVECO_CLI_CLT_PATH = $sdk.path
}
Push-Location -LiteralPath (Join-Path $projectRoot 'apps\harmony')
try {
    if ($Command -eq 'build') { & $nodeExe $cliPath build }
    else { & $nodeExe $cliPath check arkts }
    $commandExit = $LASTEXITCODE
} finally {
    Pop-Location
}
exit $commandExit
