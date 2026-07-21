# ======================================================================
# launch_ninjatrader_mnq_shadow.ps1
# NINJATRADER-MNQ-INTEGRATION-FOUNDATION — SHADOW launcher
#
# Purpose: run the full organism's decisions on MNQ and record would-authorize
# outcomes. ORDER SUBMISSION REMAINS DISABLED. This is NOT an armed execution
# launcher. An armed launcher only exists after a separate DEMO8458533 smoke-order
# authorization mission. This launcher NEVER calls OpenAI during the integration
# test and NEVER routes to a live account.
# ======================================================================
$ErrorActionPreference = "Stop"
Set-Location -Path $PSScriptRoot

# --- Integration-era fingerprint ---
$env:INTEGRATION_ERA = "MNQ_NINJATRADER_FOUNDATION"
$env:NINJATRADER_ACCOUNT_ALLOWLIST = "DEMO8458533"
$env:NINJATRADER_MAX_CONTRACTS = "1"
$env:NINJATRADER_AUTOMATED_SUBMISSION = "DISABLED"
$env:OPENAI_DISABLED_FOR_INTEGRATION = "1"
$env:NINJATRADER_MODE = "shadow"

Write-Host "======================================================================"
Write-Host "ERA: $env:INTEGRATION_ERA   MODE: SHADOW (execution disabled)"
Write-Host "ACCOUNT ALLOWLIST: $env:NINJATRADER_ACCOUNT_ALLOWLIST"
Write-Host "AUTOMATED ORDER SUBMISSION: $env:NINJATRADER_AUTOMATED_SUBMISSION"
Write-Host "MAX CONTRACTS: $env:NINJATRADER_MAX_CONTRACTS"
Write-Host "LIVE ACCOUNTS: FORBIDDEN"
Write-Host "OPENAI CALLS: DISABLED FOR INTEGRATION TEST"
Write-Host "======================================================================"

python "src/integrations/ninjatrader/run_foundation.py" --mode shadow
