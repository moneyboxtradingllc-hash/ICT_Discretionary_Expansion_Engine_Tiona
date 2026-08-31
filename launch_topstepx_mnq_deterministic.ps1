# ======================================================================
# launch_topstepx_mnq_deterministic.ps1
# DETERMINISTIC_MNQ_SIM_ONLY on TOPSTEPX. NinjaTrader is not involved at all.
#
# The lane's logic is identical to the NinjaTrader launcher; only the transport
# differs. Everything account-specific lives in .env, which is gitignored, so a
# `git pull` can never overwrite your account with someone else's.
# ======================================================================
$ErrorActionPreference = "Stop"
Set-Location -Path $PSScriptRoot

$env:PYTHONPATH = "src"
$env:DETERMINISTIC_VENUE = "topstepx"
$env:OPENAI_DISABLED_FOR_INTEGRATION = "1"

# ── operator decisions carried from the NinjaTrader lane ──────────────
# These govern the shared pipeline, not a venue, so they must be repeated.
$env:REGIME_AUTHORITY_ENABLED = "false"   # regime is observe-only
$env:PO3_LEG_SCOPED_METRICS   = "off"     # correct metric, thresholds not recalibrated

# ── ORDERS ARE DISARMED ───────────────────────────────────────────────
# NinjaTrader's bridge owns an ArmOrders switch that physically refuses orders.
# TopstepX has no equivalent, so the safety lives in the transport. Leave this
# false until a full session has run and the funnel output looks right; the lane
# scans, decides and records everything with it off, and simply never sends.
$env:TOPSTEPX_ARM_ORDERS = "false"

# ── required in .env (see .env.template) ──────────────────────────────
#   TOPSTEPX_USERNAME       TOPSTEPX_API_KEY
#   TOPSTEPX_ACCOUNT_NAME   TOPSTEPX_CONTRACT
#   TOPSTEP_ACCOUNT_SIZE    50K | 100K | 150K   <- drives the trailing drawdown cap
foreach ($k in @("TOPSTEPX_USERNAME","TOPSTEPX_API_KEY","TOPSTEPX_ACCOUNT_NAME",
                 "TOPSTEPX_CONTRACT","TOPSTEP_ACCOUNT_SIZE")) {
    if (-not (Select-String -Path ".env" -Pattern "^$k=.+" -Quiet -ErrorAction SilentlyContinue)) {
        Write-Host "$k is not set in .env" -ForegroundColor Yellow
        Write-Host "Copy .env.template to .env and fill it in, then re-run."
        exit 1
    }
}

# ── preflight: prove the connection before the loop can decide anything ──
Write-Host "Running TopstepX preflight..." -ForegroundColor Cyan
python -m broker.topstepx_preflight
if ($LASTEXITCODE -ne 0) {
    Write-Host ""
    Write-Host "Preflight failed - not starting the loop." -ForegroundColor Red
    exit 1
}

Write-Host "======================================================================"
Write-Host "MODE: DETERMINISTIC_MNQ_SIM_ONLY"
Write-Host "VENUE: TOPSTEPX  (NinjaTrader NOT used)"
Write-Host "AUTHOR: deterministic_sim_author"
Write-Host "SIZING: RISK-BASED, capped by the Topstep trailing drawdown"
Write-Host "STOP: STRUCTURAL INVALIDATION, max 25 points"
Write-Host "TARGET: 35 POINTS"
Write-Host "ORDERS ARMED: $($env:TOPSTEPX_ARM_ORDERS)"
Write-Host "OPENAI CALLS: DISABLED"
Write-Host "======================================================================"

$stop = "data/integration/topstepx/deterministic/STOP"
if (Test-Path $stop) { Remove-Item $stop -Force }

python -m integrations.topstepx.deterministic.loop
