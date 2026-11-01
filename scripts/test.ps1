$ErrorActionPreference = 'Stop'
$projectRoot = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
Set-Location -LiteralPath $projectRoot
$pythonPath = Join-Path $projectRoot '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $pythonPath)) { throw 'Install Python dependencies in .venv first.' }
$testPath = [System.IO.Path]::GetFullPath((Join-Path $projectRoot 'data\private\test-runs'))
if ($testPath -ne "$projectRoot\data\private\test-runs") { throw 'Refusing to clean an unexpected test path.' }
New-Item -ItemType Directory -Path $testPath -Force | Out-Null
$runPath = [System.IO.Path]::GetFullPath((Join-Path $testPath ([Guid]::NewGuid().ToString('N'))))
if (-not $runPath.StartsWith("$testPath\") -or (Test-Path -LiteralPath $runPath)) { throw 'Unexpected test run directory.' }
& $pythonPath -m ruff check services tests scripts
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
& $pythonPath -m pytest -q --tb=short --basetemp=$runPath
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
& npm.cmd test
exit $LASTEXITCODE
