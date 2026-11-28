# Create or update the database tables in DATABASE_URL (safe to run again).
$projectRoot = Split-Path -Parent $PSScriptRoot
$envFile = Join-Path $projectRoot '.env'
$python = Join-Path $projectRoot '.venv\Scripts\python.exe'

if (-not (Test-Path -LiteralPath $envFile)) { throw "Missing $envFile. Copy .env.example and fill it in (see docs/SETUP.md)." }
if (-not (Test-Path -LiteralPath $python)) { throw "Missing project virtual environment: $python" }

foreach ($line in Get-Content -LiteralPath $envFile) {
    if ($line -match '^\s*#' -or $line -notmatch '^([A-Z0-9_]+)=(.*)$') { continue }
    [Environment]::SetEnvironmentVariable($matches[1], $matches[2], 'Process')
}

Push-Location (Join-Path $projectRoot 'services\backend')
try { & $python -m alembic upgrade head; if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE } }
finally { Pop-Location }
