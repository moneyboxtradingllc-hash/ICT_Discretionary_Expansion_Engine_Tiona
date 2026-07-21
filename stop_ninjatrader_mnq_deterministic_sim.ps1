# ======================================================================
# stop_ninjatrader_mnq_deterministic_sim.ps1
# Stops the DETERMINISTIC_MNQ_SIM_ONLY lane: no new entries, manage/flatten any
# open protected position per doctrine, cancel residual orders, end session.
# ======================================================================
$ErrorActionPreference = "Stop"
Set-Location -Path $PSScriptRoot
$env:PYTHONPATH = "src"

$stopDir = "data/integration/ninjatrader/deterministic"
New-Item -ItemType Directory -Force -Path $stopDir | Out-Null
# 1. Prevent new entries (the running loop checks this flag each scan).
Set-Content -Path "$stopDir/STOP" -Value "stop requested"
Write-Host "STOP flag set — new entries prevented."

# 2. Reconcile, flatten any open position (manual-stop doctrine), cancel residual.
python -m integrations.ninjatrader.deterministic.stop_lane
