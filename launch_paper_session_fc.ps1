Set-Location "C:\Users\jesus\ICT_Discretionary_Expansion_Engine"

# ══════════════════════════════════════════════════════════════════════════════
# FULL-CAPABILITY PAPER SESSION (Post-June-11 implementation order)
#   FC-0A direction-conflict veto | FC-0B market-order doctrine
#   FC-1  council veto + R-001 enforcement | FC-2 live thesis exits
# Rollback: any single flag back to its default restores that subsystem's
# pre-FC behavior; launching launch_paper_session_20260611.ps1 restores all.
# ══════════════════════════════════════════════════════════════════════════════

# ── Core execution config (protected values — never lower) ───────────────────
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

# ── FC-0A — direction-conflict veto (June 11 root cause) ─────────────────────
$env:DIRECTION_CONFLICT_VETO       = "true"

# ── FC-0B — market-order execution doctrine ──────────────────────────────────
$env:ENTRY_ORDER_TYPE              = "market"
$env:MAX_CHASE_RISK_MULT           = "2.0"

# ── FC-1 — promoted authority: council veto + R-001 enforcement ──────────────
$env:COUNCIL_AUTHORITY             = "enforce"
$env:COUNCIL_VETO_MIN_NO_VOTES     = "2"
$env:COUNCIL_VETO_MIN_CONFIDENCE   = "70"
$env:RULE_GOVERNANCE_MODE          = "enforce"
$env:PROMOTED_RULES                = "R-001"

# ── FC-2 — live thesis exits (TFX-001 promotion) ─────────────────────────────
$env:THESIS_EXIT_MODE              = "live"
$env:THESIS_EXIT_CONFIRM_SCANS     = "1"

# ── AB-1/AB-3/AI-BRAIN-L — AI Brain + LLM + vector retrieval (OBSERVE-ONLY) ──
$env:AI_BRAIN_ENABLED              = "true"
$env:AI_BRAIN_LLM                  = "true"      # real GPT narrative
# AB-5B — ECU mode: Brain OWNS direction/playbook/toolbox (mechanical validates).
# Default off; uncomment to run the Brain-as-ECU architecture.
# $env:BRAIN_ECU_MODE              = "true"
$env:AI_BRAIN_MODEL                = "gpt-4o-mini"
$env:AI_BRAIN_TIMEOUT_SECONDS      = "25"
$env:AI_RETRIEVAL_ENABLED          = "true"

# ── NA-1 — Narrative Authority (the widest lens owns the story) ──────────────
$env:NARRATIVE_AUTHORITY           = "enforce"
$env:NARRATIVE_AI_MIN_CONF         = "55"
$env:NARRATIVE_DELIVERY_MIN_CONF   = "25"
$env:NARRATIVE_PROTECTED_ZONE_PCT  = "0.3"
$env:NARRATIVE_PROTECTED_BUFFER_PCT = "0.05"

# ── AI layer (live + Fable 5 shadow — FC-3 stays observation-stage) ──────────
$env:AI_MODEL                      = "gpt-4o-mini"
$env:AI_TIMEOUT_SECONDS            = "25"
$env:AI_PROVIDER_LIVE              = "openai"
$env:AI_MODEL_LIVE                 = "gpt-4o-mini"
$env:AI_PROVIDER_SHADOW            = "anthropic"
$env:AI_MODEL_SHADOW               = "claude-fable-5"
$env:AI_SHADOW_ENABLED             = "true"
$env:AI_SHADOW_MODE                = "setups_only"
$env:AI_SHADOW_TIMEOUT_SECONDS     = "10"

# ── Phase 5T — adaptive management + thesis monitor ──────────────────────────
$env:TRADE_MANAGEMENT_ENABLED      = "true"
$env:BREAKEVEN_ENABLED             = "true"
$env:BREAKEVEN_TRIGGER_R           = "1.0"
$env:TAKE_PROFIT_ENABLED           = "true"
$env:TAKE_PROFIT_R                 = "2.0"
$env:STRUCTURE_TRAIL_ENABLED       = "true"
$env:STRUCTURE_TRAIL_AFTER_BREAKEVEN = "true"
$env:ADAPTIVE_MANAGEMENT_ENABLED   = "true"
$env:THESIS_MONITOR_ENABLED        = "true"

# ── Phase 5F/5H — authority + governance ─────────────────────────────────────
$env:REGIME_AUTHORITY_ENABLED      = "true"
$env:RULE_GOVERNANCE_ENABLED       = "true"

# ── OPS-1 — end-of-day authority ─────────────────────────────────────────────
$env:EOD_NO_ENTRY_AFTER            = "15:50"
$env:EOD_FLATTEN_AT                = "15:55"
$env:EOD_POLICY                    = "flatten"

$env:RUN_SCAN_LOOP                 = "true"
$env:LIVE_MODE                     = "true"
$env:MAX_SCAN_ITERATIONS           = "0"
$env:SCAN_INTERVAL_SECONDS         = "60"
$env:PYTHONUNBUFFERED              = "1"

# ── Log paths ─────────────────────────────────────────────────────────────────
$dateTag = Get-Date -Format yyyyMMdd
$logDir  = "C:\Users\jesus\ICT_Discretionary_Expansion_Engine\logs"
$logPath = "$logDir\paper_session_fc_$dateTag.log"
$errPath = "$logDir\paper_session_fc_${dateTag}_err.log"

New-Item -ItemType Directory -Force $logDir | Out-Null

# ── Guard: refuse to launch if python is already running ──────────────────────
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

Write-Host "FULL-CAPABILITY SESSION"
Write-Host "Launched PID : $($proc.Id)"
Write-Host "Log          : $logPath"
Write-Host "Err log      : $errPath"
Write-Host ""
Write-Host "Authority    : direction-conflict VETO | market-order DOCTRINE"
Write-Host "             : council ENFORCE | R-001 ENFORCE | thesis exits LIVE"
Write-Host "             : NARRATIVE AUTHORITY ENFORCE (AI+Delivery own the story)"

Start-Sleep -Seconds 4

$pyProcs = Get-Process python -ErrorAction SilentlyContinue
Write-Host "Python processes running: $($pyProcs.Count)"
foreach ($p in $pyProcs) {
    Write-Host "  PID $($p.Id)"
}
