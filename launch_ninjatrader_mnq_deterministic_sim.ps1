# ======================================================================
# launch_ninjatrader_mnq_deterministic_sim.ps1
# DETERMINISTIC_MNQ_SIM_ONLY — automated SIMULATION execution (NOT shadow).
# ======================================================================
$ErrorActionPreference = "Stop"
Set-Location -Path $PSScriptRoot

$env:INTEGRATION_ERA = "MNQ_DETERMINISTIC_SIM_WEEK"
$env:NINJATRADER_ACCOUNT_ALLOWLIST = "DEMO8458533"
$env:NINJATRADER_INSTRUMENT = "MNQ SEP26"
$env:DETERMINISTIC_CONTRACTS = "15"
$env:OPENAI_DISABLED_FOR_INTEGRATION = "1"
$env:PYTHONPATH = "src"

Write-Host "======================================================================"
Write-Host "MODE: DETERMINISTIC_MNQ_SIM_ONLY"
Write-Host "AUTHOR: deterministic_sim_author"
Write-Host "ACCOUNT: DEMO8458533"
Write-Host "INSTRUMENT: MNQ SEP26"
Write-Host "CONTRACTS PER TRADE: 15"
Write-Host "PROFIT TARGET: 35 POINTS"
Write-Host "STOP: STRUCTURAL INVALIDATION"
Write-Host "MAXIMUM STOP DISTANCE: 16.5 POINTS"
Write-Host "MAXIMUM GROSS TRADE RISK: `$495"
Write-Host "MAXIMUM TRADES: 2"
Write-Host "DAILY LOSS CEILING: `$1000"
Write-Host "OPENAI CALLS: DISABLED"
Write-Host "ATM TEMPLATE: NOT USED"
Write-Host "AUTOMATED SIMULATION TRADING: ENABLED"
Write-Host "LIVE-MONEY ACCOUNTS: FORBIDDEN"
Write-Host "======================================================================"

# Clear any stale STOP flag, then run the live loop.
$stop = "data/integration/ninjatrader/deterministic/STOP"
if (Test-Path $stop) { Remove-Item $stop -Force }

python -m integrations.ninjatrader.deterministic.loop
