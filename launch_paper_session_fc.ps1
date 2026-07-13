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

# ── FC-1 — promoted authority: council veto (measured PROTECTIVE, kept) ──────
$env:COUNCIL_AUTHORITY             = "enforce"
$env:COUNCIL_VETO_MIN_NO_VOTES     = "2"
$env:COUNCIL_VETO_MIN_CONFIDENCE   = "70"
# ── R-001-AUDIT (2026-07-11): R-001 DEMOTED enforce→shadow on evidence.
# 22 sessions / 87 suppressed trades: 28W/48L/11BE net +3.06R — the rule
# blocked a net-POSITIVE population with ZERO discrimination while firing on
# 58.8% of all scans (vs council −2.0R and narrative −1.0R, both protective).
# Its regime input is the demoted classifier's label. Shadow keeps the
# divergence ledger recording every fire (would-have-blocked evidence
# continues). Re-promotion = its own governance mission (no auto path back).
# Rollback: "enforce".
$env:RULE_GOVERNANCE_MODE          = "shadow"
$env:PROMOTED_RULES                = "R-001"

# ── FC-2 — live thesis exits (TFX-001 promotion) ─────────────────────────────
$env:THESIS_EXIT_MODE              = "live"
$env:THESIS_EXIT_CONFIRM_SCANS     = "1"

# ── AB-1/AB-3/AI-BRAIN-L — AI Brain + LLM + vector retrieval (OBSERVE-ONLY) ──
$env:AI_BRAIN_ENABLED              = "true"
$env:AI_BRAIN_LLM                  = "true"      # real GPT narrative

# ── AI-BRAIN-REQUIRED (2026-07-10): the Brain-availability operating policy.
# Silent deterministic fallback changes the ORGANISM being tested — a session
# without the Brain is safe but behaviorally meaningless as AI evidence.
# Preflight must succeed (no quota/auth/model-access error) or the session
# REFUSES TO START; in-session, 5 consecutive Brain failures revoke NEW-ENTRY
# authority (restored on the next healthy scan). Existing-position safety
# (stops, management, reconciliation, EOD) NEVER depends on the Brain.
# Diagnostics-only sessions: set "false" (results are not AI-organism evidence).
$env:AI_BRAIN_REQUIRED             = "true"

# ── INTENT-SCORE-AUDIT (2026-07-10): the last un-audited mechanical judge in
# the execution path, demoted on replay evidence. It would have blocked 2/7 of
# the Brain's authorized trades — and the blocked pair outcome-scored BETTER
# (0.0R) than the five it passed (−4.0R); its penalties punish defensive risk
# tiers and young (fresh sovereign) setups. observe_only = verdict computed +
# recorded as would_have_blocked telemetry, never a veto. Rollback: "enforce".
$env:INTENT_SCORE_MODE             = "observe_only"

# ── VOLUME-WITNESS (2026-07-10): relative-volume sense organ. Volume flowed
# through the whole data plane and was read by NOTHING. Per-TF participation
# (last/recent volume vs own trailing baseline → dead/quiet/normal/elevated/
# climactic) attached to the Brain payload as NON-DIRECTIONAL conviction
# evidence + prompt clause. Witness only — no gate/risk/decision path reads it
# (test-locked). Rollback: "off" (organ not computed, payload unchanged).
$env:VOLUME_WITNESS                = "on"
# AB-5B/5C — ECU mode: Brain OWNS direction/opportunity/playbook/tool;
# mechanical layer becomes sensors/validators/executors. Enabled for the ECU test.
$env:BRAIN_ECU_MODE                = "true"
$env:AI_BRAIN_MODEL                = "gpt-4o-mini"
$env:AI_BRAIN_TIMEOUT_SECONDS      = "25"
$env:AI_RETRIEVAL_ENABLED          = "true"

# ── BRAIN-FAMILY-REPAIR (2026-07-09): soft family-repair turn.
# 2026-07-09 audit: the LLM emitted a directional narrative with
# recommended_playbook_family='none' on 60/80 directional scans — violating the
# AB-5C mandate and blocking Brain sovereignty on 75% of directional reads. In
# "on" mode a directional read whose family is 'none' gets ONE repair round-trip
# asking the LLM to name the family its own story implies. Guards: the repair
# may never flip direction; a failed repair keeps the ORIGINAL output (never
# falls back, never fabricates). Prompt mandate also strengthened inline.
# Rollback: set "off".
$env:BRAIN_FAMILY_REPAIR           = "on"

# ── BRAIN-INVALIDATION-REPAIR (2026-07-10): completeness — the Brain must name
# where it is WRONG. invalidation_level was null on 73% of directional reads
# (blocking thesis path-grading + forcing zone-edge fallback stops). Replay
# verdict on 40 historical gap scans: 70% fixed (27 prompt + 1 repair), 10
# migrated to honest conflicted, 0 unfixed nulls among still-directional reads.
# Repair adoption refuses wrong-side levels (bearish stop must sit ABOVE price);
# never falls back, never flips direction. Rollback: "off".
$env:BRAIN_INVALIDATION_REPAIR     = "on"

# ── BRAIN-INVALIDATION-SIDE-CHECK (2026-07-12): the #9 watch item closed.
# Repair ADOPTIONS were side-checked; INITIAL reads were not — a directional
# read with a numeric invalidation on the WRONG side of price (bearish thesis
# "dying" below price) passed unguarded as a poisoned stop reference. When on,
# the level is STRIPPED (recorded in telemetry as invalidation_side_check_
# flagged/stripped) and becomes an ordinary invalidation gap for the existing
# guarded repair turn. Direction never touched; unknown price never fires.
# Rollback: "off".
$env:BRAIN_INVALIDATION_SIDE_CHECK = "on"

# ── ENTRY-INVARIANT (2026-07-13): a directional Brain thesis is ineligible
# for FRESH exposure until it carries a valid correct-side invalidation (its
# own read, or the active thesis's inherited one — as_brain_thesis/
# produce_thesis now project the field the audit found dropped everywhere).
# Audit: 37/80 (46%) of directional authorized scans across 22 sessions rode
# an invalidation-less thesis. Thesis untouched (stays directional/persistent/
# repairable); neutral+degraded theses exempt (mechanical era unchanged);
# POSITION SAFETY UNCONDITIONAL (gate-only; stops/management never consult
# the gate). Rollback: "off".
$env:BRAIN_INVALIDATION_ENTRY_INVARIANT = "on"

# ── BRAIN-AUTHORSHIP-CLOSURE (2026-07-13): THE BRAIN IS THE SOLE AUTHOR OF
# FRESH EXPOSURE. Audit: qualification's authoring seam fell through to
# mechanical direction when the Brain was neutral, and never consulted Brain
# HEALTH (deterministic-fallback theses and served AB-7 theses on degraded
# cycles could author direction) — 175/255 authorized scans on the current
# stack rode non-Brain-authored direction. The gate guard requires direct
# healthy-LLM authorship or valid AB-7 inheritance (healthy current cycle per
# the existing laundering doctrine) AND full direction-chain agreement
# (qualification/decision/playbook may DECLINE, never substitute).
# Neutral/conflicted/degraded/unavailable/fallback author NOTHING new.
# Gate-only: position safety, stops, reconciliation, EOD unconditional.
# Fail-closed while on. Rollback: "off" (legacy mechanical-era authorship).
$env:BRAIN_AUTHORSHIP_REQUIRED     = "on"

# ── BRAIN-RELIABILITY (2026-07-09, Mission 3 organism examination):
# 1) A schema-valid directional LLM read whose ONLY residual repair error is
#    shallow PROSE is KEPT with a warning instead of being replaced by the
#    deterministic fallback (12 records + live-replay scans showed healthy reads
#    nuked over style — an authority inversion). Content gaps still fall back.
# 2) BRAIN_JSON_MODE=on makes OpenAI enforce JSON output, eliminating the
#    JSONDecodeError fallback class. Rollback: "false" / "off".
$env:BRAIN_KEEP_SHALLOW_REASONING  = "true"
$env:BRAIN_JSON_MODE               = "on"
# 3) validate-before-normalize seam: the core validator rejected phases the
#    normalizer maps deterministically one step later (live-replay proof:
#    'manipulation_to_distribution', 'mixed'). Tolerance accepts KNOWN synonyms
#    only; unknown phases still fail. Rollback: "off".
$env:BRAIN_PHASE_SYNONYM_TOLERANCE = "on"

# ── ADAPT-LOOP-2 (2026-07-09): Adaptive Effect Ledger (TELEMETRY ONLY).
# Every adaptive actuation (soft-block / confidence-lower / size-reduce) with a
# measurable trade-intent context is recorded; the replay engine resolves each
# into helped/hurt via SimBroker counterfactuals — the adaptive layer graded on
# its own decisions (the missing second-order loop). Zero authority; the ledger
# influences nothing until earn-back governance (ADAPT-LOOP-4) consumes it
# under replay gates. Rollback: "off".
$env:ADAPTIVE_EFFECT_LEDGER        = "on"

# ── ADAPT-LOOP-3 (2026-07-10): Brain self-accuracy context (DESCRIPTIVE_ONLY).
# The Brain's payload carries its own graded directional track record (replay-
# built brain_accuracy.json: 896 calls graded 2026-06→07: overall 49.4% hits,
# confidence anti-calibrated — <50-conf calls hit 59.7%, 50-69 band 37.6%).
# Context the Brain reasons WITH, never a directional input; no module may veto
# on it. Refresh: python -m replay_validation.brain_accuracy. Rollback: "off".
$env:BRAIN_ACCURACY_CONTEXT        = "on"

# ── ADAPT-LOOP-4 (2026-07-10): Earn-Back Governance — SHADOW first.
# The symmetric actuation path: an APPROVED (evidence → replay gate → explicit
# approval) promotion may LIFT one of the adaptive layer's OWN per-bucket
# restrictions (trade_block / risk_reduction / confidence_penalty). Ceiling is
# NEUTRAL (no boosts, never above 1.0x size); capital locks and hard safety
# caps are NEVER targets; no self-approval path exists. SHADOW records what
# WOULD lift without lifting — promote to "enforce" only after shadow evidence.
# CLI: python -m adaptive_learning.earnback --generate / --approve <id>
#      python -m replay_validation.earnback_gate --proposal <id>
$env:EARNBACK_MODE                 = "shadow"

# ── BRAIN-LIFECYCLE-ENFORCE (2026-07-10): AB-7 persistent thesis PROMOTED.
# Replay ablation (recorded, 0708+0709): brain-direction flicker HALVED
# (70→41, 48→24), sovereignty 27→49 / 18→38, intents +7/+10, confirmed
# triggers 14→23, would_authorize UNCHANGED (no discipline erosion), 0 errors.
# In enforce, snapshot.brain_thesis is the STABILIZED persistent thesis
# (source=ab7_active_thesis); sovereignty still fails closed on degraded scans
# (the stabilized thesis cannot launder a dead Brain). Rollback: "shadow".
$env:THESIS_LIFECYCLE_MODE         = "enforce"

# ── AI-AUTH-2 — qualification stability floor (AB-7.3c, implemented + tested).
# A mature persistent thesis prevents a one-scan mechanical dip from collapsing
# qualified->no_trade. Complements the Brain-sovereignty repair; never overrides
# a hard disqualification.
$env:QUALIFICATION_THESIS_FLOOR    = "true"

# ── PERCEPTION-1 — expansion-state hysteresis (VECTOR-3 analogue).
# The 5m expansion classifier oscillated (state 29 transitions/11 one-scan
# reversals; exhaustion level 51/21) with no hysteresis, driving 38/48
# exhaustion_risk narratives off a noisy fast-TF signal while the 15m stayed
# stable. This debounces the per-TF expansion state (a change must persist N
# scans to be accepted) without touching the detector. Rollback: set "off".
$env:EXPANSION_STABILITY_MODE      = "on"
# BOT-VS-MAURICE (2026-07-08): behavioral replay proved the confirmed 13:12
# short (+1.69R) was killed at 13:13:43 by a TRANSIENT 2-scan 5m exhaustion
# blip ~1 min before its confirmation candle. Session exhaustion episodes split
# cleanly: 9 noise episodes (<=2 scans) vs 4 sustained (>=4 scans) — ZERO 3-scan
# episodes, so a 3-scan confirm window absorbs every blip while accepting every
# genuine exhaustion. confirm=3 clears 131237's exhaustion block (confirm=2 held
# it) and leaves the one confirmed LOSER (142641) gating byte-identical, so it
# adds no losing entry. Code default stays 2 (legacy). Rollback: remove/set "2".
$env:EXPANSION_STABILITY_CONFIRM   = "3"

# ── SETUP-PERSIST — setup lifecycle transient-flicker grace window.
# A single-scan qualification dip (no_trade -> no_playbook) previously killed
# the active setup at age 1 (71% of setups died at age 1). This lets a setup
# stay DORMANT (age/lifecycle preserved, NOT traded that scan) across up to 2
# consecutive no_playbook scans so it can survive a confirmation window.
# Genuine invalidations still kill immediately. Rollback: set to "0".
$env:SETUP_NO_PLAYBOOK_GRACE        = "2"

# ── VOL-AUTH-1 — volatility authority demoted to OBSERVE-ONLY for validation.
# Volatility still calculates, logs, and records would_have_vetoed, but during
# the campaign it may NOT zero qualification, block risk, or prevent execution.
# Rollback to full veto authority: set this to "enforce". FC-0B, stops, sizing,
# max-trades/risk/daily-loss and broker safety are UNAFFECTED by this flag.
$env:VOLATILITY_AUTHORITY_MODE     = "observe_only"

# ── NEWS-1 — Market Intelligence Layer (non-directional context into the Brain) ─
$env:NEWS_LAYER_ENABLED            = "true"

# ── NA-1 — Narrative Authority (the widest lens owns the story) ──────────────
$env:NARRATIVE_AUTHORITY           = "enforce"
$env:NARRATIVE_AI_MIN_CONF         = "55"
$env:NARRATIVE_DELIVERY_MIN_CONF   = "25"
$env:NARRATIVE_PROTECTED_ZONE_PCT  = "0.3"
$env:NARRATIVE_PROTECTED_BUFFER_PCT = "0.05"

# ── AI layer (single sovereign Brain — TIER-2A retired the legacy wrapper,
# the Fable 5 shadow evaluator, and the refresh controller on 2026-07-10) ────
$env:AI_MODEL                      = "gpt-4o-mini"
$env:AI_TIMEOUT_SECONDS            = "25"
$env:AI_PROVIDER_LIVE              = "openai"
$env:AI_MODEL_LIVE                 = "gpt-4o-mini"

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

# ── REGIME-DEMOTE (2026-07-09): mechanical Regime Authority = OBSERVE_ONLY.
# Live scan 20260709_094951 showed the mechanical regime still owning FINAL
# execution authority — a range_rotation label imposed required_trigger=confirmed
# + min_setup_age=2 and hard-blocked an ELITE LIQUIDITY_SWEEP_REVERSAL SHORT while
# Market Commander was DIRECTIONAL/MATURE_EXPANSION and itself only OBSERVE.
# In observe_only the regime still CALCULATES, WARNS, records
# regime_would_have_blocked/veto_reason, and feeds Market Commander — but it may
# NOT hard-block execution; the gate falls through to the next non-regime
# authority (decision, real trigger execution_ready, risk, council, narrative).
# FC-0B, risk, sizing, stops, broker, max-trades, daily-loss are UNAFFECTED.
# Market Commander owns final environment authority. Rollback: set "enforce".
$env:REGIME_AUTHORITY_MODE         = "observe_only"

# ── MC-ENFORCE (2026-07-09): Market Commander = FINAL ENVIRONMENT AUTHORITY.
# The mechanical council voices (REGIME/OPPORTUNITY/TOOLBOX/DELIVERY/QUALIFICATION)
# were still vetoing the gate while Market Commander read DIRECTIONAL/MATURE_EXPANSION
# (scans 094304/094349/095057) — an indirect channel restoring the demoted regime
# veto. In enforce mode the council is split: safety-class (RISK) may still veto;
# advisory-class NO votes become would_have_vetoed telemetry. Commander itself
# hard-blocks ONLY a STAND_DOWN (HOSTILE/INERT guardian) environment. FC-0B, risk,
# sizing, stops, broker, max-trades, daily-loss, and the real trigger
# execution_ready check are ALL untouched. Rollback: set "observe_only".
$env:MARKET_COMMANDER_AUTHORITY_MODE = "enforce"

# ── RETEST-DOCTRINE (2026-07-09): expansion-continuation trigger path.
# The retest trial proved the trigger applied ONE retest-only rule to every
# family: any relation other than inside/touching → waiting_for_retest forever.
# Scan 095457 (trend_continuation, price 2.2pt above the FVG in mature_expansion)
# waited all day while the market expanded. In "on" mode a CONTINUATION family in
# a directional expansion may confirm on a genuine displacement candle instead of
# a pullback retest. REVERSAL setups (liquidity_sweep_reversal, etc.) keep their
# retest requirement — 094951's tape reversed up, so waiting was correct there.
# Confirmation is NOT removed; FC-0B's chase cap remains the backstop against
# extended displacement entries. Rollback: set "off".
$env:EXPANSION_CONTINUATION_TRIGGER = "on"

# ── JUDGE-FREEZE (2026-07-09): mechanical judges = TELEMETRY_ONLY.
# The mechanical confidence_tier still influenced decisions off the gate — it
# disqualified in qualification, hard-blocked in risk, and boosted playbook
# scores, a second opinion competing with the sovereign AI Brain. In
# telemetry_only it MAY measure/warn/log/record would_have_* and feed post-trade
# analysis, but MAY NOT block execution or alter qualification/decision/playbook/
# trigger/intent, nor override Brain / Market Commander. Regime and council are
# already gate-demoted (REGIME_AUTHORITY_MODE / MARKET_COMMANDER_AUTHORITY_MODE);
# the regime risk-multiplier CAP (reduce-only) and ALL safety systems (risk,
# sizing, stops, daily-loss, max-trades, broker, FC-0B) are UNTOUCHED.
# Rollback: set "active".
$env:MECHANICAL_JUDGES_MODE        = "telemetry_only"

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
