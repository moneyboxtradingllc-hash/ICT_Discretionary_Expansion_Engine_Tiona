# ======================================================================
# launch_ninjatrader_mnq_brain_on.ps1
# MNQ live scan lane WITH the external AI Brain enabled.
#
# This is NOT the deterministic lane. That lane
# (launch_ninjatrader_mnq_deterministic_sim.ps1) aborts the scan outright if
# `openai` is ever imported, by design — it is authored by explicit predicates
# and must never depend on a model being reachable. The Brain runs in the
# scan_loop lane via src/main.py.
#
# Run the deterministic lane first for a session or two after any wiring change.
# Turning the Brain on the same day changes WHO AUTHORS DIRECTION
# (qualification.direction_source becomes ai_brain), so a surprise cannot be
# attributed to either the wiring or the model. One variable at a time.
# ======================================================================
$ErrorActionPreference = "Stop"
Set-Location -Path $PSScriptRoot

# ── instrument ────────────────────────────────────────────────────────
# SCAN_SYMBOL is NOT optional. It defaults to "QQQ" in src/main.py, and the
# thesis lifecycle uses the same default for its cross-instrument reload guard —
# so an unset symbol on an MNQ session both scans and persists as QQQ.
$env:SCAN_SYMBOL = "MNQ SEP26"
$env:NINJATRADER_ACCOUNT_ALLOWLIST = "DEMO8458533"
$env:NINJATRADER_INSTRUMENT = "MNQ SEP26"
$env:PYTHONPATH = "src"

# ── the Brain ─────────────────────────────────────────────────────────
# AI_BRAIN_ENABLED alone does almost nothing: the brain runs but never calls a
# model. Every layer below is independently gated and off by default.
$env:AI_BRAIN_ENABLED = "true"     # run the brain at all
$env:AI_BRAIN_LLM     = "true"     # actually call the model
$env:BRAIN_ECU_MODE   = "true"     # publish candidate_thesis / brain_thesis
$env:AI_BRAIN_MODEL   = "gpt-4o-mini"
$env:AI_BRAIN_TIMEOUT_SECONDS = "25"

# API-enforced JSON output. The prompt already demands JSON-only; this makes the
# API guarantee it and removes the malformed-JSON fallback class entirely.
$env:BRAIN_JSON_MODE = "on"

# Thesis lifecycle starts in SHADOW: it observes and reports without replacing
# brain_thesis. Move to "enforce" only after a session confirms the theses it
# forms are sane — enforce lets it stabilize the thesis the consumers read.
$env:THESIS_LIFECYCLE_MODE = "shadow"

# Do NOT set AI_BRAIN_REQUIRED=true on a first session. It hard-fails the scan
# when the brain is unhealthy; while credits/quota are still settling, that turns
# a degraded brain into a dead session instead of a mechanical fallback.

# ── operator decisions carried over from the deterministic lane ────────
# Both apply to the shared pipeline, not to a lane, so they must be repeated
# here. See launch_ninjatrader_mnq_deterministic_sim.ps1 for the full rationale.
$env:REGIME_AUTHORITY_ENABLED = "false"   # regime is observe-only
$env:PO3_LEG_SCOPED_METRICS   = "off"     # correct metric, thresholds not yet recalibrated

# ── key ───────────────────────────────────────────────────────────────
if (-not $env:OPENAI_API_KEY) {
    Write-Host "OPENAI_API_KEY is not set in this shell." -ForegroundColor Yellow
    Write-Host "Set it for this session only (it is never written to disk):"
    Write-Host '    $env:OPENAI_API_KEY = "sk-..."'
    Write-Host ""
    Write-Host "Get credits at platform.openai.com (OpenAI - not OpenSea)."
    exit 1
}

# ── preflight: one minimal live call before any trading decision ──────
# This is the difference between "the brain is off" and "the brain is on but
# every call is silently failing to a mechanical fallback". It classifies the
# failure, so an empty balance reads as `quota` rather than a mystery.
Write-Host "Brain preflight ..." -NoNewline
$pf = python -c @"
import json, sys
sys.path.insert(0, 'src')
from ai_brain.brain_preflight import preflight
print(json.dumps(preflight()))
"@
$result = $pf | ConvertFrom-Json
if (-not $result.ok) {
    Write-Host " FAILED" -ForegroundColor Red
    Write-Host "  classification : $($result.classification)"
    Write-Host "  model          : $($result.model)"
    Write-Host "  detail         : $($result.detail)"
    Write-Host ""
    switch ($result.classification) {
        "quota"        { Write-Host "No credit on the account. Add funds at platform.openai.com." -ForegroundColor Yellow }
        "auth"         { Write-Host "The key was rejected. Check OPENAI_API_KEY." -ForegroundColor Yellow }
        "model_access" { Write-Host "This key cannot reach $($result.model). Try AI_BRAIN_MODEL=gpt-4o-mini." -ForegroundColor Yellow }
        default        { Write-Host "Network or config problem - the brain would fall back mechanically all session." -ForegroundColor Yellow }
    }
    Write-Host ""
    Write-Host "Not launching. The deterministic lane is unaffected and still runs:"
    Write-Host "    .\launch_ninjatrader_mnq_deterministic_sim.ps1"
    exit 1
}
Write-Host " ok (model $($result.model))" -ForegroundColor Green

Write-Host "======================================================================"
Write-Host "MODE: LIVE SCAN + EXTERNAL AI BRAIN"
Write-Host "INSTRUMENT: MNQ SEP26"
Write-Host "BRAIN: ENABLED   LLM CALLS: ENABLED   MODEL: $($env:AI_BRAIN_MODEL)"
Write-Host "ECU: ON (brain authors direction)   THESIS LIFECYCLE: $($env:THESIS_LIFECYCLE_MODE)"
Write-Host "REGIME AUTHORITY: DISABLED (observe-only)"
Write-Host "LEG-SCOPED METRICS: OFF"
Write-Host "LIVE-MONEY ACCOUNTS: FORBIDDEN"
Write-Host "======================================================================"

python src/main.py
