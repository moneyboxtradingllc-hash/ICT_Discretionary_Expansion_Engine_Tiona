# ======================================================================
# launch_ninjatrader_mnq_deterministic_sim.ps1
# DETERMINISTIC_MNQ_SIM_ONLY — automated SIMULATION execution (NOT shadow).
# ======================================================================
$ErrorActionPreference = "Stop"
Set-Location -Path $PSScriptRoot

$env:INTEGRATION_ERA = "MNQ_DETERMINISTIC_SIM_WEEK"
$env:NINJATRADER_ACCOUNT_ALLOWLIST = "DEMO8458533"
$env:NINJATRADER_INSTRUMENT = "MNQ SEP26"
$env:DETERMINISTIC_MAX_RISK = "500"   # risk-based sizing target (informational)
$env:OPENAI_DISABLED_FOR_INTEGRATION = "1"
$env:PYTHONPATH = "src"

# ── REGIME CLASSIFIER IS OBSERVE-ONLY (operator decision, 2026-07-26) ──
# regime_classifier.py has always been observe_only with confidence_modifier 0.
# Phase 5F.2 then added regime_permission_matrix.py — a SEPARATE execution
# authority defaulting to "true" — which re-armed the veto under a different
# name. It vetoes on the regime LABEL, and that label falls to `range_rotation`
# whenever trend_score misses 55, which it does during distribution.
#
# Replayed 2026-07-24: PO3 distribution + bearish narrative + valid block + valid
# OTE, rejected because regime read `range_rotation` and _REVERSAL_ONLY_REGIMES
# permits only reversal families. Distribution and range rotation cannot both
# describe the trading timeframe.
#
# The regime classifier consumes a far narrower evidence set than the narrative
# pipeline and must not outrank it. It stays a source of EVIDENCE: disagreement
# should adjust confidence, never veto execution. Do not remove this line without
# an explicit architecture decision.
$env:REGIME_AUTHORITY_ENABLED = "false"

Write-Host "======================================================================"
Write-Host "MODE: DETERMINISTIC_MNQ_SIM_ONLY"
Write-Host "AUTHOR: deterministic_sim_author"
Write-Host "ACCOUNT: DEMO8458533"
Write-Host "INSTRUMENT: MNQ SEP26"
Write-Host "SIZING: RISK-BASED (contracts = floor(`$500 / (stop_pts x `$2)), max 30)"
Write-Host "PROFIT TARGET: 35 POINTS"
Write-Host "STOP: STRUCTURAL INVALIDATION"
Write-Host "MAXIMUM STOP DISTANCE: 25 POINTS"
Write-Host "MAXIMUM RISK PER TRADE: `$500"
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
