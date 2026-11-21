param(
    [string]$WorkerId = ""
)

$projectRoot = Split-Path -Parent $PSScriptRoot
$envFile = Join-Path $projectRoot '.env'
$python = Join-Path $projectRoot '.venv\Scripts\python.exe'

if (-not (Test-Path -LiteralPath $envFile)) { throw "Missing $envFile" }
if (-not (Test-Path -LiteralPath $python)) { throw "Missing project virtual environment: $python" }

foreach ($line in Get-Content -LiteralPath $envFile) {
    if ($line -match '^\s*#' -or $line -notmatch '^([A-Z0-9_]+)=(.*)$') { continue }
    [Environment]::SetEnvironmentVariable($matches[1], $matches[2], 'Process')
}

$env:PYTHONPATH = Join-Path $projectRoot 'services\backend\src'
if ($WorkerId) { $env:SOURCELENS_WORKER_ID = $WorkerId }
& $python -m report_qa.worker.runner
