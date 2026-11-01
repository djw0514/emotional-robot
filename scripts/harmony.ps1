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
    New-Item -ItemType Directory -Path $privateRoot -Force | Out-Null
    @{ path = $resolvedRoot; kind = $kind; apiVersion = 26; platformVersion = $metadata.platformVersion } |
        ConvertTo-Json | Set-Content -LiteralPath $sdkInfoPath -Encoding utf8
}

$sdk = $null
if (Test-Path -LiteralPath $sdkInfoPath) {
    $sdk = Get-Content -LiteralPath $sdkInfoPath -Raw -Encoding utf8 | ConvertFrom-Json
}

$nodeHome = ''
$javaHome = ''
if ($null -ne $sdk -and $sdk.kind -eq 'studio') {
    $nodeHome = Join-Path $sdk.path 'tools\node'
    $javaHome = Join-Path $sdk.path 'jbr'
}
if (-not $nodeHome -or -not (Test-Path -LiteralPath (Join-Path $nodeHome 'node.exe'))) {
    if (-not (Test-Path -LiteralPath $nodeInfoPath)) { throw 'Node.js is missing from the toolchain.' }
    $nodeHome = (Get-Content -LiteralPath $nodeInfoPath -Raw -Encoding utf8 | ConvertFrom-Json).path
}
if (-not $javaHome -or -not (Test-Path -LiteralPath (Join-Path $javaHome 'bin\java.exe'))) {
    if (-not (Test-Path -LiteralPath $javaInfoPath)) { throw 'The JDK is missing from the toolchain.' }
    $javaHome = (Get-Content -LiteralPath $javaInfoPath -Raw -Encoding utf8 | ConvertFrom-Json).path
}
$nodeExe = Join-Path $nodeHome 'node.exe'
$javaExe = Join-Path $javaHome 'bin\java.exe'
if (-not (Test-Path -LiteralPath $cliPath)) {
    throw 'DevEco CLI is missing. Install @deveco/deveco-cli into data/private/toolchains/deveco-cli.'
}

if ($Command -eq 'doctor') {
    Write-Output ('Node: ' + $nodeExe)
    & $nodeExe --version
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
    Write-Output ('Java: ' + $javaExe)
    & $javaExe -version
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
    & $nodeExe $cliPath --version
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
    if ($null -eq $sdk) {
        Write-Output 'SDK status: not registered. Select an API 26 toolchain with -ToolchainRoot.'
        exit 2
    }
    Write-Output ('SDK status: API ' + $sdk.apiVersion + ' at ' + $sdk.path)
    exit 0
}

if ($null -eq $sdk) { throw 'Register the installed API 26 toolchain with -ToolchainRoot first.' }
$env:JAVA_HOME = $javaHome
$env:Path = $nodeHome + ';' + (Join-Path $javaHome 'bin') + ';' + $env:Path
if ($sdk.kind -eq 'studio') {
    $env:DEVECO_CLI_STUDIO_PATH = $sdk.path
    Remove-Item Env:DEVECO_CLI_CLT_PATH -ErrorAction SilentlyContinue
} else {
    $env:DEVECO_CLI_CLT_PATH = $sdk.path
    Remove-Item Env:DEVECO_CLI_STUDIO_PATH -ErrorAction SilentlyContinue
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
