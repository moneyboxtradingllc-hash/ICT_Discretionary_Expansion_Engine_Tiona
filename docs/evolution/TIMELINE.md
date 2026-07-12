# Organism Evolution Timeline

_A living changelog keyed to evidence. Every badge links to a replay/
lab/ablation artifact; a claim without an artifact renders as PENDING._
_`REJECTED` and `NO CHANGE` entries are displayed with the same
prominence as wins — they are the credibility of this document._

_Rendered 2026-07-12T19:07:44.979944+00:00 — 26 milestones on a 167-commit spine._

## 2026-07-10

### [VALIDATED] TIER-2A

- **Change:** Deleted legacy AI wrapper cluster: discretionary_ai, ai_debate_engine, ai_input_builder, shadow_ai_evaluator, ai_refresh_controller, ai_brain/divergence + all wiring (-3630 lines). ECU Brain is the single AI organ; gate/store/formatter carry no wrapper fields; ADAPTIVE-6 confidence overlay target retired (recorded no-op). Kept: narrative_builder, ai_api_adapter, ai_snapshot_formatter, confidence_engine (mechanical witness).
- **Measured:** wrapper ran every scan (deterministic mode) + Fable5 shadow API calls; fusion fed Commander council testimony + decision.confidence → replay parity 372/372 scans zero divergence, funnels identical (0708: 6 auth, 0709: 7 auth); suite 1769 passed
- **Evidence:** `data/replay/reports/tier2a_parity_20260710.json`
- **Commit:** `fa15e4b`

### [VALIDATED] TIER-2B

- **Change:** Deleted dead journal/ package (Phase-3 stub: empty __init__ + pass-only trade_journal). The real journal is paper_execution/trade_journal.py, untouched.
- **Measured:** 6-line stub package shipped in every backup/deploy; zero importers (static, dynamic, CLI, scheduled, artifact, migration — all verified zero) → package gone; suite 1769 passed; lock test forbids revival
- **Evidence:** `tests/test_tier2a_retirement.py (journal.trade_journal in RETIRED_MODULES)`
- **Commit:** `1e2f689`

### [VALIDATED] VOLUME-WITNESS

- **Change:** Participation sense organ: per-TF relative volume + z-score + same-minute-of-day percentile (22-session replay-built baseline) + sweep/displacement association (existing sensors' events only) + IEX venue provenance, attached to the Brain payload as NON-DIRECTIONAL conviction evidence with prompt clause. Witness only: no authority path reads it (test-locked); gated VOLUME_WITNESS (launcher on, default off).
- **Measured:** volume flowed alpaca(IEX)->timeframe_builder->normalizer and was read by NOTHING; Brain traded blind to participation → replay: 372/372 scans ZERO pre-witness divergence, funnels identical; descriptive gradients (n=888 joined rows): fulfilled 24->34pct and invalidated 34->20pct dead->climactic; rising-trend +0.248R vs falling -0.00R; interactions INSUFFICIENT DATA (n<30); ~581 payload tokens/scan; suite 1797
- **Evidence:** `data/replay/reports/volume_witness_parity_20260710.json + volume_witness_report_*.json`
- **Commit:** `63721ad`

<sub>spine: `1fcba8c` ADAPT-LOOP-2 - Adaptive effect ledger and resolver · `12ceed0` ADAPT-LOOP-3 - Brain accuracy table and self-track-record feed · `9d409b5` ADAPT-LOOP-3B - Brain thesis quality grading · `d34dc21` ADAPT-LOOP-4 - Earn-back governance with replay gate · `85e204e` ADAPT-LOOP-5 - Retire recommendation engine · `48b1a79` REPLAY-4 - Counterfactual decision laboratory · `e295fc8` ADAPT-LOOP-6 - Organism health monitor and evolution timeline · `134a708` BRAIN-LIFECYCLE-ENFORCE - Persistent thesis promoted to enforce · `14a400b` MILESTONE - Brain lifecycle enforce · `734da90` BRAIN-INVALIDATION-REPAIR - Elicit invalidation level · `477f531` MILESTONE - Brain invalidation repair · `1aa2278` BRAIN-MODEL-TRIAL - Model arm support in live brain study · `e15dc90` MILESTONE - Adaptive unblocked lab result · `93b2ee3` AI-BRAIN-REQUIRED - Brain availability operating policy · `1e22d3e` MILESTONE - AI Brain required policy · `09bfc3f` HEALTH-ERA-LABEL - Calibration era quality from commit timestamps · `0b72e1c` MILESTONE - Calibration era labeling · `f605670` INTENT-SCORE-AUDIT - Execution-path quality gate demoted to witness · `df7289c` MILESTONE - Intent score demotion</sub>

## 2026-07-11

### [NO CHANGE] NA-1-AUDIT

- **Change:** Narrative gate (narrative_permits_trade, NARRATIVE_AUTHORITY=enforce) put on trial via new counterfactual lab override narrative_permits (pre_decision seam; evidence channel untouched, only gate-read veto fields flip; prong provenance recorded). NO code change to authority — the gate KEEPS enforce.
- **Measured:** last mechanical judge with live gate authority, never measured; anatomy looked suspect (AI lens structurally empty live; mechanical-quarrel global kill possible) → 22 sessions / 12,043 scans: veto touches 31.8pct of scans; 50 binding vetoes -> 38 scored suppressed trades = 10W/21L/7BE, net -1.0R AVOIDED (protective); suspect wide_lens_vs_structure prong fired ZERO times — live vetoes are 100pct protected-swing zone doctrine. VERDICT: NO CHANGE, gate vindicated (2nd judge to survive trial after council)
- **Evidence:** `data/replay/reports/na1_audit_20260711.json`
- **Commit:** `47b78c4`

### [VALIDATED] R-001-AUDIT

- **Change:** Promoted rule R-001 (compound hostility) DEMOTED enforce->shadow (launcher + CURRENT_STACK). Rule stays registered — the divergence ledger keeps recording every fire (would-have-blocked evidence continues). Rollback: RULE_GOVERNANCE_MODE=enforce. Re-promotion = its own governance mission.
- **Measured:** promoted on ONE June-11 trade (-1.34R); fired on 58.8pct of ALL scans; regime input = the DEMOTED classifier's label re-entering as veto basis → flag ablation, 22 sessions: 110 binding vetoes -> 87 scored suppressed trades = 28W/48L/11BE net +3.06R — blocked a net-POSITIVE population with ZERO discrimination (vs council -2.0R and narrative -1.0R, both protective, both kept). Suite 1803
- **Evidence:** `data/replay/reports/r001_audit_20260711.json`
- **Commit:** `6f82ee8`

<sub>spine: `fa15e4b` TIER-2A - Legacy AI wrapper retirement · `271ae2d` MILESTONE - TIER-2A wrapper retirement · `1e2f689` TIER-2B - Dead journal package retirement · `c980bdf` MILESTONE - TIER-2B journal retirement · `63721ad` VOLUME-WITNESS - Participation sense organ · `6fad982` MILESTONE - Volume witness organ · `47b78c4` NA-1-AUDIT - Narrative gate vindicated · `2b76f17` MILESTONE - Narrative gate trial</sub>

## 2026-07-12

### [VALIDATED] SIDE-CHECK

- **Change:** Initial-read invalidation side guard (BRAIN_INVALIDATION_SIDE_CHECK, launcher on, default off): a directional read whose numeric invalidation sits on the WRONG side of a known price has the poisoned level STRIPPED (telemetry: invalidation_side_check_flagged/stripped) and becomes an ordinary invalidation gap for the existing guarded repair turn (which is told WHY). Direction never touched; unknown price never fires; repair adoption side-guard unchanged.
- **Measured:** watch item estimated ~5pct wrong-side INITIAL reads passing unguarded (repair adoptions were side-checked, initial reads were not) → MEASURED 4x worse: 83/394 (21.1pct) of checkable directional LLM reads carried a wrong-side invalidation (bullish theses 'dying' ABOVE price — target named as stop; incl. degenerate inv==px). All 83 would now be stripped->repaired-or-honest-null. Suite 1814 (11 new tests). Live repair-fix rate measurable when credits/live sessions resume
- **Evidence:** `data/replay/reports/invalidation_side_check_20260712.json`
- **Commit:** `67d76d2`

### [VALIDATED] RETRO-REMEASURE

- **Change:** First periodic retro-remeasure: earlier milestone claims re-tested over the grown 22-session archive (no code changed — pure evidence). Confirmation doctrine and council claims re-tried at the same scale as NA-1/R-001; brain report-card tables rebuilt; organism health refreshed.
- **Measured:** confirmation doctrine n=2 (0W/2L one day); council vindication n=6 one day (-2.0R, 0709-era config); brain tables n=896; 80-89 bucket -0.27R (n=59) → CONFIRMATION STRENGTHENED 170x: waiving it = 342 trades 101W/184L/57BE net -8.26R (29.5pct win rate, below 2:1 breakeven) — the most valuable constraint ever measured. COUNCIL: era claim HOLDS but on the CURRENT stack its veto is 100pct REDUNDANT (fires ~every scan, 0 binding vetoes in 22 sessions — everything it blocks is already blocked upstream; harmless, kept). TABLES: reproduced exactly (n=896, integrity confirmed, no new data until live resumes). 80-89 pocket moderated to +0.044R (n=51, still parked <100)
- **Evidence:** `data/replay/reports/retro_remeasure_20260712.json + organism_health_20260712_050437.json`
- **Commit:** `7427a1c`

<sub>spine: `6f82ee8` R-001-AUDIT - Promoted rule demoted to shadow · `642c42e` MILESTONE - R-001 demotion · `67d76d2` SIDE-CHECK - Initial-read invalidation guard · `7427a1c` MILESTONE - Invalidation side check · `2e6aa43` MILESTONE - Retro-remeasure of timeline claims</sub>

## 2026-07-08

### [VALIDATED] PERCEPTION-1 expansion hysteresis

- **Change:** 5m expansion state debounced (2-scan confirm)
- **Measured:** 11 one-scan reversals/session → 0 one-scan reversals (77/224 scans stabilized)
- **Evidence:** `data/replay/reports/validation_suite_20260709_161212.json`
- **Commit:** `270383b-era`

### [VALIDATED] VOL-AUTH-1 volatility observe_only

- **Change:** volatility demoted from qualification veto
- **Measured:** qualified 37, intents 11 → qualified 56, intents 15
- **Evidence:** `data/replay/reports/validation_suite_20260709_161212.json`
- **Commit:** `pre-campaign`

### [NO CHANGE] PERCEPTION-2 confirm window 3

- **Change:** expansion confirm window 2→3
- **Measured:** funnel: qual 56, intents 15, auth 0 → funnel identical (49 scans perception-stabilized only)
- **Evidence:** `data/replay/reports/validation_suite_20260709_161212.json`
- **Commit:** `18bad64`

### [NO CHANGE] SETUP-PERSIST no_playbook grace

- **Change:** setups survive transient no_playbook scans as dormant
- **Measured:** funnel: qual 56, intents 15, auth 0 → funnel identical (44 scans kept alive in gate state)
- **Evidence:** `data/replay/reports/validation_suite_20260709_161212.json`
- **Commit:** `pre-campaign`

<sub>spine: `96b68b7` DASHBOARD-BASELINE - Epoch-gate stale pre-baseline trade memory · `68556bb` HOSTILE-AUDIT - Truthful hard-disqualifier reporting · `c36b5dc` VOL-AUTH-1 - Volatility authority demotion (observe_only) · `4937ec7` TRIGGER-AUDIT - Confirmation transparency (observe-only telemetry) · `0da7ffa` SETUP-PERSIST - Transient-flicker grace window for setup lifecycle · `94282a6` QUAL-FLICKER-AUDIT - Opportunity-masking transparency (qualification exonerated) · `45ef969` NARRATIVE-AUDIT - Narrative decision-reason transparency (engine exonerated) · `05626b7` PERCEPTION-1 - Expansion state hysteresis (5m expansion flicker fixed) · `18bad64` PERCEPTION-2 - Expansion confirm window 3</sub>

## 2026-07-09

### [VALIDATED] REGIME-DEMOTE

- **Change:** mechanical regime demoted to observe_only at the gate
- **Measured:** would-authorize 0 → would-authorize 7
- **Evidence:** `data/replay/reports/validation_suite_20260709_161212.json`
- **Commit:** `fcfc60c`

### [VALIDATED] MC-ENFORCE

- **Change:** Market Commander owns environment; advisory council veto demoted
- **Measured:** would-authorize 1 → would-authorize 7
- **Evidence:** `data/replay/reports/validation_suite_20260709_161212.json`
- **Commit:** `3ff6f72`

### [VALIDATED] JUDGE-FREEZE + AI_CONTEXT-AUTHORITY

- **Change:** mechanical confidence tier + narrative frozen to witness
- **Measured:** qualified 77, intents 11 → qualified 90, intents 15
- **Evidence:** `data/replay/reports/validation_suite_20260709_161212.json`
- **Commit:** `6e74ca2/ad98581`

### [VALIDATED] RETEST-DOCTRINE

- **Change:** expansion-continuation trigger path (reversals keep retest)
- **Measured:** 12 continuation scans stuck waiting_for_retest → 12 scans trigger=confirmed via displacement
- **Evidence:** `data/replay/reports/validation_suite_20260709_161212.json`
- **Commit:** `1255aaa`

### [VALIDATED] BRAIN-FAMILY-REPAIR (targeted live replay)

- **Change:** prompt salience + soft repair turn vs 153 historical gap scans
- **Measured:** 153 directional reads with family='none' (sovereignty blocked) → 93/153 fixed (61%; prompt 47 + repair 46; 0 direction flips)
- **Evidence:** `data/replay/reports/family_repair_live_20260709_214329.json`
- **Commit:** `23bfbec`

<sub>spine: `fcfc60c` REGIME-DEMOTE - Mechanical regime authority observe_only · `3ff6f72` MC-ENFORCE - Market Commander final environment authority · `1255aaa` RETEST-DOCTRINE - Expansion continuation trigger path · `6e74ca2` JUDGE-FREEZE - Mechanical confidence tier telemetry_only · `ad98581` AI_CONTEXT-AUTHORITY - Mechanical narrative witness-only under sovereign Brain · `723151b` THESIS-PERSIST - Persist brain thesis and sovereignty in snapshots · `23bfbec` BRAIN-FAMILY-REPAIR - Fix directional playbook_family none rate · `a057436` REPLAY-0 - Replay validation engine architecture · `832ae63` REPLAY-1 - Candle archive and historical range fetch · `270383b` REPLAY-2 - Session walker with recorded brain and stage trace · `8bb5b65` REPLAY-SUITE - Flag ablation validation suite · `e47e7f1` REPLAY-LIVE - Live brain mode and family repair replay · `7467d6b` BRAIN-RELIABILITY - Keep shallow reads and JSON mode · `cfa4e0b` REPLAY-STUDY - Live brain study with rate-limit backoff · `b90e217` BRAIN-RELIABILITY-3 - Phase synonym tolerance in core validator · `ac3e993` REPLAY-3 - SimBroker outcome simulation and metrics</sub>

## 2026-07-10

### [VALIDATED] LIVE BRAIN STUDY (5-run matrix, 0709)

- **Change:** full-organism live-LLM replay, repair off/on
- **Measured:** sovereignty 12% (recorded era) → 50% repair-off / 55% repair-on; pb_none 60→1.8; would-authorize 7→3.2 (discipline intact)
- **Evidence:** `data/replay/reports/live_brain_study_20260710_095943.json`
- **Commit:** `e47e7f1/cfa4e0b`

### [VALIDATED] LAB: council_yes counterfactual

- **Change:** what if the council had voted yes? (0709)
- **Measured:** council vetoes unproven → alternate history 1W/5L, -2.0R, violates daily limits — vetoes RIGHT
- **Evidence:** `data/replay/reports/lab_council_yes_20260709_20260710_022256.json`
- **Commit:** `48b1a79`

### [REJECTED] LAB: trigger_confirmed counterfactual

- **Change:** what if confirmation were waived? (0709, negative control)
- **Measured:** confirmation doctrine (BOT-VS-MAURICE: unconfirmed 0W/3L) → 2 new trades, both stopped, -1.0R each — confirmation removal REJECTED
- **Evidence:** `data/replay/reports/lab_trigger_confirmed_20260709_20260710_022401.json`
- **Commit:** `48b1a79`

### [PENDING] EARNBACK shadow arm

- **Change:** earn-back governance armed in shadow
- **Measured:** adaptive layer punish-only → None
- **Evidence:** _none — pending until an artifact exists_
- **Commit:** `d34dc21`

### [VALIDATED] BRAIN-LIFECYCLE-ENFORCE

- **Change:** AB-7 persistent thesis promoted shadow->enforce (dormant since AB-7)
- **Measured:** brain-direction flicker 70/48 per session; sovereignty 27/18 recorded → flicker 41/24 (halved); sovereignty 49/38; would_authorize unchanged
- **Evidence:** `replay ablation 20260708+20260709 (recorded, deterministic)`
- **Commit:** `134a708`

### [VALIDATED] BRAIN-INVALIDATION-REPAIR

- **Change:** prompt mandate + gap detector + soft repair for invalidation_level (family-repair recipe)
- **Measured:** invalidation_level null on 73% of directional reads → 70% fixed (27 prompt + 1 repair / 40 sampled); 0 unfixed nulls among still-directional; wrong-side levels refused
- **Evidence:** `live replay on 40 historical gap-scan payloads (2026-07-10)`
- **Commit:** `734da90`

### [NO CHANGE] LAB: adaptive_unblocked counterfactual

- **Change:** what if the adaptive soft-veto hadn't blocked? (0709, current stack)
- **Measured:** adaptive block authority unproven → 0 scans mutated — the soft-veto never fired (substrate empty; authority currently inert)
- **Evidence:** `data/replay/reports/lab_adaptive_unblocked_20260709_20260710_121247.json`
- **Commit:** `1aa2278`

### [VALIDATED] AI-BRAIN-REQUIRED

- **Change:** operating policy: new judgment requires the Brain; position safety never does (preflight refusal + 5-failure entry revocation)
- **Measured:** credit/auth failure silently substituted the deterministic fallback organism → session refuses to start without a healthy Brain; degraded scans marked; entries revoked at threshold; positions managed regardless
- **Evidence:** `tests/test_ai_brain_required.py (12 locks incl. quota/auth classification)`
- **Commit:** `93b2ee3`

### [VALIDATED] HEALTH-ERA-LABEL

- **Change:** calibration results labeled by config-era quality, auto-derived from in-session commit timestamps
- **Measured:** 0709's 69/148 calibration read as ordinary drift despite two mid-session authority repairs → 0709 auto-flagged mixed_config_era / trend_eligible=false; clean-era days remain longitudinal benchmarks
- **Evidence:** `organism_health.config_era_quality + live check naming the in-session commits`
- **Commit:** `09bfc3f`

### [VALIDATED] INTENT-SCORE-AUDIT

- **Change:** last un-audited mechanical judge (order_builder quality gate) demoted to witness
- **Measured:** would have blocked 2/7 of the Brain's authorized trades → blocked pair outcome-scored BETTER (0.0R) than the 5 passed (-4.0R) — inverse discrimination; observe_only records would_have_blocked, never vetoes
- **Evidence:** `replay 0709 lifecycle-enforce + SimBroker outcome comparison`
- **Commit:** `f605670`

<sub>spine: `1fcba8c` ADAPT-LOOP-2 - Adaptive effect ledger and resolver · `12ceed0` ADAPT-LOOP-3 - Brain accuracy table and self-track-record feed · `9d409b5` ADAPT-LOOP-3B - Brain thesis quality grading · `d34dc21` ADAPT-LOOP-4 - Earn-back governance with replay gate · `85e204e` ADAPT-LOOP-5 - Retire recommendation engine · `48b1a79` REPLAY-4 - Counterfactual decision laboratory · `e295fc8` ADAPT-LOOP-6 - Organism health monitor and evolution timeline · `134a708` BRAIN-LIFECYCLE-ENFORCE - Persistent thesis promoted to enforce · `14a400b` MILESTONE - Brain lifecycle enforce · `734da90` BRAIN-INVALIDATION-REPAIR - Elicit invalidation level · `477f531` MILESTONE - Brain invalidation repair · `1aa2278` BRAIN-MODEL-TRIAL - Model arm support in live brain study · `e15dc90` MILESTONE - Adaptive unblocked lab result · `93b2ee3` AI-BRAIN-REQUIRED - Brain availability operating policy · `1e22d3e` MILESTONE - AI Brain required policy · `09bfc3f` HEALTH-ERA-LABEL - Calibration era quality from commit timestamps · `0b72e1c` MILESTONE - Calibration era labeling · `f605670` INTENT-SCORE-AUDIT - Execution-path quality gate demoted to witness · `df7289c` MILESTONE - Intent score demotion</sub>
