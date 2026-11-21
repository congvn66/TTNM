param(
    [int]$Port = 8000,
    [switch]$Reload
)

$projectRoot = Split-Path -Parent $PSScriptRoot
$envFile = Join-Path $projectRoot '.env'
$python = Join-Path $projectRoot '.venv\Scripts\python.exe'

if (-not (Test-Path -LiteralPath $envFile)) {
    throw "Missing $envFile. Copy .env.example and set Supabase/R2 credentials."
}
if (-not (Test-Path -LiteralPath $python)) {
    throw "Missing project virtual environment: $python"
}

foreach ($line in Get-Content -LiteralPath $envFile) {
    if ($line -match '^\s*#' -or $line -notmatch '^([A-Z0-9_]+)=(.*)$') {
        continue
    }
    [Environment]::SetEnvironmentVariable($matches[1], $matches[2], 'Process')
}

$env:PYTHONPATH = Join-Path $projectRoot 'services\backend\src'
$arguments = @(
    '-m', 'uvicorn', 'report_qa.api.main:app',
    '--app-dir', (Join-Path $projectRoot 'services\backend\src'),
    '--host', '127.0.0.1', '--port', $Port
)
if ($Reload) {
    $arguments += '--reload'
}

& $python @arguments
