Set-Location "C:\Users\jesus\ICT_Discretionary_Expansion_Engine"

# ── Paper session config — 2026-06-11 (first full-stack session: 5F+5G+5H+5T+OPS-1)
$env:EXECUTION_ENABLED             = "true"
$env:ALLOW_PAPER_ORDERS            = "true"
$env:PAPER_TRADING_ONLY            = "true"
$env:PAPER_ACTIVATION_MODE         = "true"
$env:PAPER_EXIT_ON_STOP            = "true"
$env:BROKER_STOP_ENABLED           = "true"

$env:MAX_TRADES_PER_DAY            = "2"
$env:ONE_POSITION_AT_A_TIME        = "true"

$env:RISK_PER_TRADE_DOLLARS        = "500"
$env:DAILY_LOSS_LIMIT_DOLLARS      = "500"

$env:PAPER_ACTIVATION_MAX_TRADES   = "2"
$env:PAPER_ACTIVATION_RISK_DOLLARS = "500"

$env:AI_MODEL                      = "gpt-4o-mini"
$env:AI_TIMEOUT_SECONDS            = "25"

# Phase AI-SHADOW — Fable 5 shadow evaluator (OBSERVE_ONLY; live AI unchanged)
$env:AI_PROVIDER_LIVE              = "openai"
$env:AI_MODEL_LIVE                 = "gpt-4o-mini"
$env:AI_PROVIDER_SHADOW            = "anthropic"
$env:AI_MODEL_SHADOW               = "claude-fable-5"
$env:AI_SHADOW_ENABLED             = "true"
$env:AI_SHADOW_MODE                = "setups_only"
$env:AI_SHADOW_TIMEOUT_SECONDS     = "10"

# Phase 5T — adaptive management + thesis monitor (shadow)
$env:TRADE_MANAGEMENT_ENABLED      = "true"
$env:BREAKEVEN_ENABLED             = "true"
$env:BREAKEVEN_TRIGGER_R           = "1.0"
$env:TAKE_PROFIT_ENABLED           = "true"
$env:TAKE_PROFIT_R                 = "2.0"
$env:STRUCTURE_TRAIL_ENABLED       = "true"
$env:STRUCTURE_TRAIL_AFTER_BREAKEVEN = "true"
$env:ADAPTIVE_MANAGEMENT_ENABLED   = "true"
$env:THESIS_MONITOR_ENABLED        = "true"

# Phase 5F/5H — authority + governance (defaults true; explicit for attestation)
$env:REGIME_AUTHORITY_ENABLED      = "true"
$env:RULE_GOVERNANCE_ENABLED       = "true"

# OPS-1 — end-of-day authority (defaults; explicit for attestation)
$env:EOD_NO_ENTRY_AFTER            = "15:50"
$env:EOD_FLATTEN_AT                = "15:55"
$env:EOD_POLICY                    = "flatten"

$env:RUN_SCAN_LOOP                 = "true"
$env:LIVE_MODE                     = "true"
$env:MAX_SCAN_ITERATIONS           = "0"
$env:SCAN_INTERVAL_SECONDS         = "60"
$env:PYTHONUNBUFFERED              = "1"

# ── Log paths ─────────────────────────────────────────────────────────────────
$logDir  = "C:\Users\jesus\ICT_Discretionary_Expansion_Engine\logs"
$logPath = "$logDir\paper_session_20260611.log"
$errPath = "$logDir\paper_session_20260611_err.log"

New-Item -ItemType Directory -Force $logDir | Out-Null

# ── Guard: refuse to launch if python is already running ──────────────────────
# (OPS-1 single-instance lock also enforces this natively inside the bot.)
$existing = Get-Process python -ErrorAction SilentlyContinue
if ($existing.Count -gt 0) {
    Write-Host "ABORT: $($existing.Count) Python process(es) already running. Stop them first."
    exit 1
}

# ── Launch exactly one scan loop ─────────────────────────────────────────────
$proc = Start-Process `
    -FilePath "python" `
    -ArgumentList "src/main.py" `
    -WorkingDirectory "C:\Users\jesus\ICT_Discretionary_Expansion_Engine" `
    -RedirectStandardOutput $logPath `
    -RedirectStandardError  $errPath `
    -NoNewWindow `
    -PassThru

Write-Host "Launched PID : $($proc.Id)"
Write-Host "Log          : $logPath"
Write-Host "Err log      : $errPath"

Start-Sleep -Seconds 4

$pyProcs = Get-Process python -ErrorAction SilentlyContinue
Write-Host "Python processes running: $($pyProcs.Count)"
foreach ($p in $pyProcs) {
    Write-Host "  PID $($p.Id)"
}
