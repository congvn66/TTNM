$ErrorActionPreference = "Stop"

$repoRoot = Split-Path -Parent $PSScriptRoot
$webRoot = Join-Path $repoRoot "apps\web"
$port = 4173

if (-not (Test-Path (Join-Path $webRoot "package.json"))) {
  throw "Frontend directory not found: $webRoot"
}

$listenerLine = netstat -ano | Select-String -Pattern "\s127\.0\.0\.1:$port\s+.*LISTENING\s+\d+" | Select-Object -First 1
if ($listenerLine) {
  $listenerParts = ($listenerLine.ToString() -split "\s+") | Where-Object { $_ }
  $listenerPid = [int]$listenerParts[-1]
  $owner = Get-Process -Id $listenerPid -ErrorAction SilentlyContinue
  $ownerName = if ($owner) { $owner.ProcessName } else { "process #$listenerPid" }
  Write-Host "Frontend already running at http://127.0.0.1:$port ($ownerName, PID $listenerPid)." -ForegroundColor Green
  Write-Host "If this is not the TTNM frontend, free port $port and run this script again." -ForegroundColor Yellow
  exit 0
}

Push-Location $webRoot
try {
  # Use npm.cmd because restricted PowerShell execution policies block npm.ps1
  # in the integrated terminal on Windows.
  & npm.cmd run dev -- --host 127.0.0.1 --port $port
  if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
}
finally {
  Pop-Location
}
