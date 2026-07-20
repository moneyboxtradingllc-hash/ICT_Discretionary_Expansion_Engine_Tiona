# ======================================================================
# launch_ninjatrader_mnq_readonly.ps1
# NINJATRADER-MNQ-INTEGRATION-FOUNDATION — READ-ONLY launcher
#
# Purpose: preflight, connect/read, archive, build snapshots — EXECUTION
# DISABLED, ORDER SUBMISSION DISABLED. This launcher NEVER arms trading and
# NEVER calls OpenAI. It is separate from the proven QQQ launcher by design.
# ======================================================================
$ErrorActionPreference = "Stop"
Set-Location -Path $PSScriptRoot

# --- Integration-era fingerprint ---
$env:INTEGRATION_ERA = "MNQ_NINJATRADER_FOUNDATION"
$env:NINJATRADER_ACCOUNT_ALLOWLIST = "Sim101"
$env:NINJATRADER_MAX_CONTRACTS = "1"
$env:NINJATRADER_AUTOMATED_SUBMISSION = "DISABLED"
$env:OPENAI_DISABLED_FOR_INTEGRATION = "1"
$env:NINJATRADER_MODE = "readonly"

Write-Host "======================================================================"
Write-Host "ERA: $env:INTEGRATION_ERA   MODE: READ-ONLY"
Write-Host "ACCOUNT ALLOWLIST: $env:NINJATRADER_ACCOUNT_ALLOWLIST"
Write-Host "AUTOMATED ORDER SUBMISSION: $env:NINJATRADER_AUTOMATED_SUBMISSION"
Write-Host "MAX CONTRACTS: $env:NINJATRADER_MAX_CONTRACTS"
Write-Host "LIVE ACCOUNTS: FORBIDDEN"
Write-Host "OPENAI CALLS: DISABLED FOR INTEGRATION TEST"
Write-Host "======================================================================"

python "src/integrations/ninjatrader/run_foundation.py" --mode readonly
