# PHASE MAP-0 — Full System Wiring Diagram

As-built audit of the Expansion Bot at commit `6f99455` (post FC-0A/0B/1/2,
NA-1). Every claim is verified against source. Line numbers reference the
current tree.

---

## PART 1 — SYSTEM MAP (actual module hierarchy, in execution order)

```
src/main.py  (entrypoint → startup authority → scan loop)
│
├── OPERATIONAL PLANE (session boundary)
│   ├── operational_readiness/startup_authority    13 mandatory + optional checks; refuses launch
│   ├── operational_readiness/readiness_checklist  per-scan 100-pt readiness
│   ├── operational_readiness/activation_controller
│   ├── operational_readiness/eod_authority        15:50 no-entry / 15:55 flatten
│   └── paper_activation/*                         arms paper trading (max_trades, risk $)
│
├── DATA PLANE (per scan, inside build_snapshot)
│   ├── data_feed/alpaca_provider                  600×1m candles (Alpaca)
│   ├── data_feed/timeframe_builder                1m → 3m/5m/15m
│   ├── data_feed/market_clock                     scan window, session labels
│   └── market_data/candle_normalizer
│
├── EVIDENCE PLANE (build_snapshot, snapshot_builder.py:55-100)
│   ├── structure/structure_engine                 swings, bias, BOS, MSS (per TF)
│   ├── structure/liquidity_engine                 sweeps, reclaims, resting pools (per TF)
│   ├── volatility/volatility_classifier + expansion_detector
│   ├── structure/po3_engine                       PO3 phase + manipulation/distribution direction
│   ├── state/market_memory  (in-RAM, 20 snapshots) PO3 stability, confidence trend
│   ├── ai_layer/narrative_builder                 mechanical narrative + directional_bias
│   └── ai_layer/confidence_engine                 mechanical confidence score/tier
│        └→ all of the above fuse into snapshot["ai_context"]
│
├── JUDGMENT PLANE (build_snapshot, snapshot_builder.py:120-141)
│   ├── regime_classification/regime_classifier    regime label (observe-side)
│   ├── qualification/trade_qualification_engine   opportunity + DIRECTION (structure-rooted; FC-0A veto)
│   ├── playbooks/playbook_classifier              tactical playbook + direction (inherits qualification)
│   ├── regime_authority/regime_permission_matrix  CONSTRAINT authority (caps, trigger, age, mgmt profile)
│   ├── risk/risk_governor                         trade_allowed, risk tier/multiplier
│   └── toolbox/toolbox_engine (+price_levels, tool_library)  entry tools + zones + trigger prep
│
├── SCAN LOOP PLANE (scan_loop.py, per-scan order)
│   ├── ai_refresh_controller → ai_layer/discretionary_ai (external gpt-4o-mini)   ~line 833
│   ├── confidence fusion rebuild                                                  834
│   ├── state_transitions/transition_engine                                        857
│   ├── setup_lifecycle/setup_tracker                                              864
│   ├── shared_context/shared_market_context → council                             869-870
│   ├── ai_layer/shadow_ai_evaluator (Fable 5, observe)                            875
│   ├── narrative_authority: protected_swings → narrative_engine (NA-1)            ~876+
│   ├── decision_authority/decision_engine                                         878+
│   ├── execution_gate/execution_gate  (12 checks — THE permission point)          886+
│   ├── trade_intent/intent_builder → intent_scoring → intent_archive              894-910
│   ├── observe plane: experience, correlation, memory_search, dashboard,
│   │                  recommendations (all confidence_modifier=0)                 918-1010
│   ├── paper_execution/execution_engine (11 layers → order_builder → paper_broker) 1065+
│   ├── position plane: position_supremacy(995) / position_monitor(1006) /
│   │                  stop_enforcer(1094) / protective_stop (broker stop)
│   ├── trade_reconciliation (fill truth, closure)                                 1138
│   ├── trade_manager (BE/TP/trail, profile-driven)                                1151
│   ├── thesis_monitor (FC-2: live exits)                                          1162
│   ├── pending_order_lifecycle (legacy limit-order hygiene)                       1172
│   ├── rule_governance/shadow_evaluator → divergence_ledger                       1179-1222
│   └── snapshot_store (archive to data/live_snapshots/)
│
└── GOVERNANCE / LEARNING (cross-scan)
    ├── rule_governance/{rule_registry, predicates, promoted_rules, rule_scoring,
    │                    member_calibration, divergence_ledger, governance_report}
    ├── ai_feedback/{ai_feedback_builder, ai_outcome_scorer, ai_feedback_summary}
    ├── experience_intelligence/*, performance_intelligence/*, recommendation_engine/*
    └── memory_search/{feature_vector, memory_record_builder, similarity_search}
```

---

## PART 2 — INPUT / OUTPUT MAP (per subsystem)

**Data feed / timeframes** — IN: Alpaca API (600×1m). OUT: `timeframes{1m,3m,5m,15m}`. CONSUMERS: every evidence engine.

**Structure engine** — IN: candles per TF. OUT: per-TF `{bias, state, BOS, MSS, last_swing_high/low}` + alignment. Bias = two ascending/descending swing pairs (`structure_engine.py:28`). CONSUMERS: narrative_builder (**directional_bias — the direction root**), po3, qualification, AI input, trade_manager trail.

**Liquidity engine** — IN: candles per TF. OUT: per-TF `{sweep_detected, sweep_direction, reclaim_detected, failed_breakout, nearest_buy/sell_side_liquidity}`. **One-scan memory.** CONSUMERS: po3, playbook scoring, qualification FC-0A veto, AI input (events only), NA-1 protected swings + draw, toolbox price_levels (nearest levels — sole consumer of the pools).

**Volatility / Expansion** — IN: candles+ATR. OUT: states, scores, displacement, exhaustion. CONSUMERS: regime, narrative, qualification, playbook, risk, shared context.

**PO3 engine** — IN: structure+liquidity+volatility+expansion. OUT: per-TF phase + **manipulation/distribution direction** (`above_high → bearish`, po3_engine.py:116) + alignment. CONSUMERS: narrative, qualification (conflict check), shared context `_delivery` (**delivery state root**), AI input.

**Market memory (state/)** — IN: completed snapshots. OUT: PO3 stability, confidence trend/delta, flicker flags. CONSUMERS: narrative_builder, confidence_engine, AI input (2 numbers). **In-RAM only — wiped by restart** (June 11 11:36 restart cleared it).

**Narrative builder (mechanical)** — IN: structure/vol/expansion/liquidity/po3/session/memory-mods. OUT: `ai_context{market_narrative, market_state, directional_bias, trade_personality, coherence, warnings}`. CONSUMERS: qualification (**direction**), confidence engine, AI input, playbook fallback.

**Confidence engine** — IN: same evidence + narrative. OUT: mechanical `confidence_score/tier`. CONSUMERS: fusion, intent score, NA-1 witness confidence.

**Regime classifier** — IN: snapshot + candles. OUT: `market_regime{label, family, confidence, vol_state, expansion_state}`. CONSUMERS: **regime_permission_matrix (constraint authority)**, council REGIME, R-001 predicate, journal enrichment, AI input.

**Qualification** — IN: full snapshot. OUT: `{status, grade, direction, opportunity_score, ...}`. Direction = `ai_context.directional_bias` first (structure), FC-0A sweep veto second, PO3 conflict third. CONSUMERS: playbook (**direction inheritance**), risk, intent score, council QUALIFICATION, pending-order hygiene, thesis monitor (via lifecycle).

**Playbook classifier** — IN: qualification + evidence. OUT: `{selected_playbook, direction, confidence, status, eligible/preferred_tools}`. CONSUMERS: **toolbox (sole activation source)**, regime matrix (forbidden families), gate NA-1 proposed-direction, council OPPORTUNITY, shared context.

**Regime permission matrix** — IN: market_regime + playbook. OUT: `{allowed, risk_multiplier_cap, required_trigger_status, min_setup_age_scans, management_profile, forbidden_playbooks}`. CONSUMERS: **order_builder (cap), execution gate (3 checks), management_policies (profile)**. ENFORCEMENT authority since 5F.2.

**Risk governor** — IN: snapshot incl. qualification/playbook. OUT: `{trade_allowed, risk_tier, risk_multiplier, blocks, restrictions}`. CONSUMERS: gate (`risk_allows_trade`), order_builder (multiplier), toolbox, council RISK. ENFORCEMENT.

**Toolbox** — IN: playbook name+direction, risk, evidence. OUT: tool candidates with `price_level` (zones, midpoint, invalidation) + `trigger_prep` (entry models). CONSUMERS: gate (trigger checks), order_builder (entry/stop), trade intent, AI input (top 3), trade_manager (trail levels).

**External AI (discretionary_ai + api_adapter + input_builder)** — IN: `build_compact_ai_input` (see AI-0 autopsy: no price on no-setup scans, no candles, no position, no own history). OUT: 11 fields. CONSUMED: `ai_direction`+`ai_confidence` → fusion, debate, NA-1 lens; agreement booleans → journal scoring; **7 prose fields → main.py print + archive only.**

**Confidence fusion** — IN: mechanical confidence + ai_confidence. OUT: `fusion_status`. CONSUMER: gate (blocks only `strong_disagreement`).

**AI debate (deterministic)** — IN: snapshot + ai_disc (direction/conf only). OUT: bull/bear/neutral cases + verdict stance. CONSUMERS: gate (`ai_verdict_supports_trade`), decision authority.

**State transitions / setup lifecycle** — IN: consecutive snapshots. OUT: upgrade/downgrade/invalidated; phase, age_scans. CONSUMERS: gate (invalidation + age), thesis monitor (**death trigger**), pending-order hygiene, intent archive.

**Shared context (5G.1)** — IN: snapshot. OUT: normalized ctx incl. `delivery_state/confidence`, exhaustion, reversal. CONSUMERS: **council, rule predicates (R-001 promoted path), thesis monitor (trend profile), NA-1 delivery lens**.

**Council** — IN: shared ctx. OUT: 6 votes + consensus + **veto** (FC-1). CONSUMER: execution gate (`council_permits_trade` when `COUNCIL_AUTHORITY=enforce`). ENFORCEMENT (was observe until FC-1).

**Shadow AI — Fable 5** — IN: same compact input. OUT: `snapshot["ai_shadow"]` + data/ai_shadow/. CONSUMERS: none (observation stage; FC-3 ladder defined).

**NA-1 Narrative Authority** — IN: ai_disc (dir/conf), shared-ctx delivery, po3, liquidity, ai_context bias, protected swings tracker. OUT: full narrative block (direction/phase/confidence, protected levels, draw, forbidden direction). CONSUMERS: **execution gate (`narrative_permits_trade`)**, journal `*_at_entry`, snapshot store. ENFORCEMENT when `NARRATIVE_AUTHORITY=enforce`. **Computed after the AI, before decision/gate — it judges trades; it does not author them.**

**Decision authority** — IN: snapshot. OUT: `decision` (`ready_for_execution` required), never `trade_authorized=true` pre-gate. CONSUMER: gate, execution engine layer 4.

**Execution gate** — IN: everything above. OUT: `allow_execution` + 12 `authorization_checks` (9 original + council + promoted rules + narrative). CONSUMER: execution engine layer 3. **THE permission point.**

**Trade intent / intent score / intent archive** — IN: gate+toolbox+playbook. OUT: intent (zone, type), score (gating vs MIN_INTENT_GATED_SCORE=70), archived intent records w/ MFE/MAE (outcome_tracker). CONSUMERS: execution engine layers 5/7, order_builder, memory records.

**Execution engine (11 layers)** — IN: snapshot. OUT: paper order via order_builder (FC-0B market doctrine; zone guard; chase cap) → paper_broker (Alpaca paper) → journal record (`paper_execution/trade_journal.py` — the REAL journal). CONSUMERS: broker; journal consumed by everything post-trade.

**Position plane** — position_supremacy (broker is truth), position_monitor, stop_enforcer, protective_stop (after-fill broker stop), trade_reconciliation (fill truth: FC-0B recomputes risk from fill; closure + realized_r), trade_manager (BE 0.75R/TP 1.25R/trail per locked profile), thesis_monitor (FC-2 live exits, broker-stop-cancel-first), pending_order_lifecycle (limit-era hygiene, self-neutralizing under market doctrine).

**Rule governance** — registry (14 rules, data/rule_governance/registry.json) + predicates (3 in library) + shadow_evaluator (observe, after execution at 1179) + **promoted_rules (FC-1 enforcement_ref, called BY the gate pre-execution)** + divergence_ledger (resolves R on fired events, incl. blocked ones) + rule_scoring/member_calibration (promotion evidence).

**Observe plane** — experience_intelligence, performance dashboard, memory_search, recommendations, ai_feedback: all emit `confidence_modifier: 0` hardcoded; consumed only as AI input context + console + archive.

---

## PART 3 — AI MAP

| Component | File | Live? | Called by | Output consumed by | Authority |
|---|---|---|---|---|---|
| AI input builder | ai_layer/ai_input_builder.py | LIVE | discretionary_ai, shadow_ai | the two models | n/a |
| External AI (gpt-4o-mini) | ai_layer/discretionary_ai.py + ai_api_adapter.py | LIVE (external mode; ~every other scan via 60s refresh) | scan_loop:833 | dir+conf → fusion/debate/NA-1; booleans → journal; 7 prose fields → **print+archive only** | ADVISORY (2 fields), one binary veto via fusion |
| Deterministic AI fallback | discretionary_ai.py `_build_deterministic_content` | LIVE (fallback/internal) | same | same | same — **"AI" = structure in costume when fallback fires** |
| AI refresh controller | live_scan/ai_refresh_controller.py | LIVE | scan_loop | cache reuse tagging | n/a |
| AI debate engine | ai_layer/ai_debate_engine.py | LIVE (deterministic, no API) | scan_loop via discretionary | gate `ai_verdict_supports_trade` | ENFORCEMENT input |
| Confidence engine (mechanical "AI") | ai_layer/confidence_engine.py | LIVE | snapshot_builder | fusion, intent score | input |
| Narrative builder (mechanical "AI") | ai_layer/narrative_builder.py | LIVE | snapshot_builder | **direction root of the whole system** | de-facto authority |
| Snapshot formatter | ai_layer/ai_snapshot_formatter.py | LIVE | scan_loop | console + summary text | log only |
| Fable 5 shadow | ai_layer/shadow_ai_evaluator.py | LIVE (setups_only) | scan_loop:875 | **nobody** (data/ai_shadow + snapshot) | OBSERVE (FC-3 ladder designed) |
| AI feedback / outcome scorer | ai_feedback/* | LIVE post-close | reconciliation path | journal labels, AI input context | OBSERVE (modifier=0) |
| AI connectivity test | ai_layer/ai_connectivity_test.py | utility only | manual | n/a | dead in scan path |
| "AI vector search" | — | **does not exist** | — | — | memory_search is categorical overlap, not embeddings |

## PART 4 — MEMORY MAP

| Memory | Exists | Populated | Queried live | Consumed by decisions | Notes |
|---|---|---|---|---|---|
| Market memory (state/) | YES | YES (RAM, 20 snaps) | YES every scan | YES — feeds narrative/confidence (PO3 stability, trend) | **lost on restart** |
| Snapshot store (data/live_snapshots) | YES | YES (1/min) | NO (offline audits only) | NO | archive |
| Trade journal (paper_execution/) | YES | YES | YES | YES — management, reconciliation, supremacy, experience | the real journal |
| Intent archive + outcome tracker | YES | YES | YES | observe plane + memory records only | MFE/MAE per intent |
| Memory search (similarity) | YES | YES (journal+archive records) | YES every scan | **NO** — observe_only, modifier=0; summary into AI input | categorical weights (110-pt), **no embeddings/vector store** |
| Divergence ledger | YES | YES | resolution pass each scan | NO (evidence for promotions) | governance memory |
| Protected swings (NA-1) | YES | YES (RAM tracker) | YES | YES — NA-1 → gate | first persistent liquidity memory; lost on restart |
| AI's own memory | **NO** | — | — | — | model is amnesiac; only confidence trend (2 numbers) passes |
| Narrative memory / replay memory | NO | — | — | — | do not exist |
| Prior-session levels / overnight refs | NO | — | — | — | do not exist anywhere |

## PART 5 — PLAYBOOK MAP

- **Created by:** static library (`playbooks/playbook_library.py` ↔ `toolbox/tool_library.py`) — humans author playbooks.
- **Selected by:** `playbook_classifier` scoring over evidence (narrative label, liquidity, PO3, vol, alignment).
- **Direction determined by:** qualification.direction (= structure bias via `ai_context.directional_bias`, FC-0A veto) — `playbook_classifier._direction()` step 1; sweep semantics step 2 (reached only when qualification is non-directional).
- **Vetoed by:** regime permission matrix (forbidden families per regime, exhaustion overlay) — pre-gate; council/R-001/NA-1 — at gate.
- **Consumed by:** toolbox (activation), gate, regime matrix, council, AI input, NA-1 proposed-direction.
- **Activation:** score ≥ thresholds → status forming/active/strong/elite; `no_playbook` ⇒ toolbox cannot activate.

## PART 6 — TOOLBOX MAP

- **Opportunities created by:** `toolbox_engine.run_toolbox` — scores ONLY `eligible_tools(playbook, playbook_direction)` (`toolbox_engine.py:424-442`). **Monocular: one direction per scan.**
- **Filtered by:** tool scoring, readiness prerequisites, risk block, price_levels zone construction, trigger_prep.
- **Direction determined by:** playbook direction, exclusively.
- **Availability determined by:** playbook existence + directionality; `no_playbook` → "toolbox cannot activate"; non-directional → "tool selection deferred".
- **Consumed by:** gate (trigger checks), order_builder (entry zone, invalidation → stop), trade intent, AI input, trade_manager (structure trail), NA-1 (current price fallback).

## PART 7 — AUTHORITY MAP (actual, as enforced today)

```
GENERATION AUTHORITY (who authors trades)            PERMISSION AUTHORITY (who approves trades)
Structure bias (narrative_builder._directional_bias)  Execution gate — 12 checks:
  ↓ (FC-0A sweep-conflict veto can nullify)             decision=ready • risk allows • trigger ready
Qualification direction                                 • not invalidated • debate supports • lifecycle ok
  ↓                                                     • fusion not strong-disagreement • regime allowed
Playbook direction                                      • trigger=confirmed • age≥2
  ↓                                                     • council permits (FC-1) • no promoted rule (FC-1)
Toolbox tools + entry models                            • narrative permits (NA-1)
  ↓                                                          ↓
Trade intent + intent score (≥70 strong_watch)         Execution engine 11 layers (env flags, endpoint,
  ↓                                                     gate, decision, intent, trigger, score, build,
  └────────────────────────────────────────────────→   position guard, submit, journal)
                                                             ↓
EXPOSURE/RISK AUTHORITY (independent):                  Alpaca paper broker
  Risk Governor (multiplier, allowed)                        ↓
  Regime Matrix (cap, trigger, age, profile)            Position plane: Broker Supremacy is exposure
  Position Guard (one position, max 2 trades, daily $)  truth • protective stop • trade_manager (profile)
  EOD authority (15:50/15:55)                           • thesis monitor LIVE exits (FC-2)
  Broker Supremacy (positions reconcile FROM broker)
```

Authority handoffs: structure → qualification (silent inheritance) → playbook (silent) → toolbox (silent). First real challenge points: FC-0A veto (inside qualification), regime matrix (constraint), then the gate (12 checks), then position guard. Post-fill: broker stop + trade manager + thesis monitor + EOD.

## PART 8 — DEAD PATH AUDIT

| Item | Status | Why it exists | Affects live behavior? |
|---|---|---|---|
| `src/journal/trade_journal.py` | **DEAD STUB** (6 lines, `pass`, imported by nothing) | Phase-3 placeholder superseded by paper_execution/trade_journal | NO |
| 7 AI prose fields | **decision-dead** (print+archive only) | schema built rich, consumers never wired | NO (AI-0 finding) |
| `ai_context.summary` text | log artifact only — appended all scan, consumed by no decision path | human/audit readability | NO |
| `confidence_modifier` (5 observe modules) | hardcoded 0 by constitution | designed promotion hooks, never promoted | NO |
| Recommendation engine | live but emitted 0 recommendations June 8–11 | needs sample size | NO currently |
| Fable 5 shadow output | produced, consumed by nobody | FC-3 observation stage | NO |
| `hybrid` AI mode `deterministic_output` | dormant (AI_MODE=external) | audit trail for hybrid mode | NO |
| `would_authorize_if_enabled` plumbing | vestigial naming from pre-execution era, **still load-bearing** (engine layer 3 checks it) | 1U firewall heritage | YES |
| pending_order_lifecycle | self-neutralizing under market doctrine; live for legacy recovery | FC-0B transition | rarely |
| ai_connectivity_test | manual utility | ops | NO |
| Council `_AUTHORITY` constant | superseded by env fn; constant retained as default | FC-1 | default only |
| Prior-session/overnight refs, AI vector store, narrative memory | **absent entirely** (consumers exist in spirit, no producers) | never built | the June-10→11 gap was invisible for this reason |
| Market memory across restarts | not persisted | in-RAM design | June 11 11:36 restart wiped PO3 stability history |

## PART 9 — JUNE 11 TRACE (condensed; full forensics in session reports)

**The long (PT_QQQ_20260611T102953):**
Candles → structure read raid-made higher highs ⇒ bias bullish (10:13) → narrative_builder broadcast bullish → qualification inherited (no FC-0A then) → playbook LSR-bullish@88 → toolbox bullish-only tools, IFVG zone 700.79–701.49 → AI (echo: qualified ⇒ bullish@65) → debate bull 72/bear 0 → gate 9/9 green at 10:29:53 → limit 701.14 → filled 10:31 by the rejection.
Ignored en route: PO3 manipulation_direction=bearish (shared ctx → council DELIVERY NO@75 — observe), REGIME NO@95 (observe), R-001 fired (shadow), AI's own 10:15 bearish prose (decision-dead fields), liquidity sweep semantics (dormant step 2). Authority transferred: structure → qualification → playbook → toolbox → gate. **Final decision originated in the gate; the direction originated in `structure_engine._bias`.**
Post-fill: thesis monitor signaled death at −0.06R (shadow then) → ignored → broker stop −1.34R.

**The short (PT_QQQ_20260611T131740):**
Structure bias finally bearish 12:59 → qualification bearish/qualified 13:16 (one scan) → playbook LSR-bearish → bearish toolbox first time all day → gate authorized 13:17:41 (R-001 fired again — shadow then) → order rejected: buying power consumed by the morning long's cost basis. The only thing that stopped the short was the long.
**Under today's wiring both trades are gate-blocked multiple independent ways** (FC-0A conflicted direction, council veto, R-001 enforcement, NA-1 conflict/protected levels) — verified by the replay test suites (`tests/test_phase_fc1_*`, `test_phase_na1_*`).
