# Run the Jobcast dev server. From the repo root:  .\tools\run_server.ps1
# Options:  -Port 8090  -Python <path>  -DevPlanHeader
param(
  [int]$Port = 8090,
  [string]$Python = "",
  [switch]$DevPlanHeader
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot

if (-not $Python) {
  if ($env:JOBCAST_PYTHON) { $Python = $env:JOBCAST_PYTHON }
  else { $Python = "python" }
}

$env:JOBCAST_PORT = "$Port"
$env:PYTHONUTF8 = "1"
if ($DevPlanHeader) { $env:JOBCAST_DEV_PLAN_HEADER = "1" }

Write-Host "Jobcast dev server on http://127.0.0.1:$Port  (Ctrl+C to stop)"
Push-Location $root
try { & $Python -m server } finally { Pop-Location }
