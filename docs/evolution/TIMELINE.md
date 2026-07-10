# Organism Evolution Timeline

_A living changelog keyed to evidence. Every badge links to a replay/
lab/ablation artifact; a claim without an artifact renders as PENDING._
_`REJECTED` and `NO CHANGE` entries are displayed with the same
prominence as wins — they are the credibility of this document._

_Rendered 2026-07-10T16:50:55.516929+00:00 — 17 milestones on a 149-commit spine._

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

<sub>spine: `1fcba8c` ADAPT-LOOP-2 - Adaptive effect ledger and resolver · `12ceed0` ADAPT-LOOP-3 - Brain accuracy table and self-track-record feed · `9d409b5` ADAPT-LOOP-3B - Brain thesis quality grading · `d34dc21` ADAPT-LOOP-4 - Earn-back governance with replay gate · `85e204e` ADAPT-LOOP-5 - Retire recommendation engine · `48b1a79` REPLAY-4 - Counterfactual decision laboratory · `e295fc8` ADAPT-LOOP-6 - Organism health monitor and evolution timeline · `134a708` BRAIN-LIFECYCLE-ENFORCE - Persistent thesis promoted to enforce · `14a400b` MILESTONE - Brain lifecycle enforce · `734da90` BRAIN-INVALIDATION-REPAIR - Elicit invalidation level · `477f531` MILESTONE - Brain invalidation repair · `1aa2278` BRAIN-MODEL-TRIAL - Model arm support in live brain study · `e15dc90` MILESTONE - Adaptive unblocked lab result · `93b2ee3` AI-BRAIN-REQUIRED - Brain availability operating policy</sub>
