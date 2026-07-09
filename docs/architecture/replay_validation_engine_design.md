# Replay Validation Engine — Architecture (REPLAY-0, 2026-07-09)

> Stop asking whether the code looks better. Start proving whether the bot trades better.

## 1. Executive Verdict

A faithful replay engine is **feasible today** with one missing dataset. Three codebase
facts make it so:

1. **The entire perception layer derives from 1m candles.** `timeframe_builder._aggregate`
   builds 3m/5m/15m from the 1m stream; structure, liquidity, expansion, PO3, volatility,
   and every downstream authority are pure functions of that stream plus threaded state.
   Archive the 1m candles and the whole mechanical organism is reproducible.
2. **The Brain is record-replayable.** `persist_brain_call` has stored every LLM call
   since 2026-06-13 (2,241 records: prompt, input_payload, parsed_output, usage). A
   RecordedBrain can serve the historical output by timestamp — deterministic, free,
   reproducible.
3. **Every repair is config-gated.** REGIME_AUTHORITY_MODE, MARKET_COMMANDER_AUTHORITY_MODE,
   MECHANICAL_JUDGES_MODE, EXPANSION_CONTINUATION_TRIGGER, SETUP_NO_PLAYBOOK_GRACE,
   EXPANSION_STABILITY_CONFIRM, QUALIFICATION_THESIS_FLOOR, VOLATILITY_AUTHORITY_MODE,
   BRAIN_FAMILY_REPAIR. Attribution therefore does not require code archaeology:
   **replay the same day twice with one flag flipped** and the diff IS that repair's
   behavioral effect.

The one hard gap: **no historical 1m candle archive and no range-fetch** —
`fetch_1m_candles(lookback_bars)` only reaches back a rolling window. The first
implementation phase is therefore a candle archiver, and it is urgent: each day we
wait, a session ages toward the fetch horizon.

The critical honesty constraint baked into this design: stored live snapshots record
**decisions, not inputs** (no timeframes/structure/liquidity persisted). They are the
*ground-truth baseline* for comparison — never the replay input. Replay always
reconstructs from candles.

## 2. Replay Engine Architecture

New isolated package `src/replay_validation/` — it imports the trading pipeline;
**nothing in the trading pipeline ever imports it**. Zero changes to trading logic.

```
src/replay_validation/
  candle_archive.py    # per-session 1m candle store + EOD archiver + backfill
  replay_session.py    # chronological scan-walker (scan_loop minus network/broker)
  recorded_brain.py    # Brain modes: RECORDED | DETERMINISTIC | LIVE
  sim_broker.py        # fill/stop/target/BE/trail simulation on 1m candles
  stage_trace.py       # canonical per-scan pipeline stage vector
  compare.py           # run-vs-run first-divergence + subsystem attribution
  metrics.py           # session scoreboard (sovereignty → expectancy → drawdown)
  report.py            # REPLAY VERDICT (markdown + JSON)
  run.py               # CLI: python -m replay_validation.run --date 20260708
                       #        --brain recorded --flags baseline.env --out ...
```

**Scan walker.** For each simulated scan tick (60s cadence, or the recorded scan
timestamps from that day's snapshots), slice the trailing candle window, run
`timeframe_builder`, call `build_snapshot(...)` with the SAME persistent state threaded
as `scan_loop` does: Po3StabilityManager, ExpansionStabilityManager, thesis lifecycle
engine, market memory, setup tracker. Statefulness is not optional — half the repairs
(PERCEPTION-1/2, SETUP-PERSIST, AB-7) live in that threaded state.

**Brain modes.**
- `RECORDED` (default): serve the persisted `parsed_output` matched by scan timestamp
  (nearest within tolerance). Deterministic, zero cost. Required for A/B trust.
- `DETERMINISTIC`: force the deterministic fallback path (tests mechanical organism only).
- `LIVE`: re-call the real LLM. Non-reproducible, costs money — reserved for validating
  *Brain-side* repairs (e.g. BRAIN-FAMILY-REPAIR prompt changes), run N times and
  reported as a distribution, never a single pass.

**SimBroker.** Replaces the Alpaca adapter at the execution seam. Entry fill = next 1m
candle open after authorization (conservative). Stops/targets/breakeven/trailing walked
forward candle-by-candle (low-before-high pessimism on ambiguous candles). Produces
per-trade entry/exit/R/MFE/MAE. **The replay environment never loads broker
credentials; a run asserts at startup that no Alpaca env keys are present.**

**Isolation.** All state stores are already env-overridable (the DECON-2 test-isolation
pattern): LIVE_SNAPSHOTS_DIR, AI_BRAIN_DIR, AI_RETRIEVAL_DIR, performance dirs. A replay
run gets a fresh sandbox directory tree per run-id; it can be seeded from an archived
copy of the live data dirs for memory-faithful replay, or left empty (declared in the
manifest as a caveat).

## 3. Historical Data Requirements

| Input | Status | Source / gap |
|---|---|---|
| 1m candles per session | **MISSING — build first** | `candle_archive.py`: EOD archiver + `fetch_1m_candles_range(start,end)` (additive provider method; the single trading-adjacent addition) + immediate backfill of recent days before they age out |
| Brain LLM records | HAVE (2,241 since 2026-06-13) | `data/ai_brain/*.json` — prompt, input_payload, parsed_output |
| Ground-truth baseline (what the old bot DID) | HAVE | `data/live_snapshots/` — decisions/outputs incl. THESIS-PERSIST sovereignty from 723151b onward |
| Config per revision | HAVE | git history of `launch_paper_session_fc.ps1` → env manifest extractor |
| News context | PARTIAL | inside Brain `input_payload`; mechanical replay runs `NEWS_LAYER_ENABLED=false` with a manifest caveat |
| Account state | SIMULATED | constant equity; risk dollars from manifest ($500) |
| Memory / vector stores | SANDBOXED | empty or seeded-from-archive; declared in manifest (ORGANISM_EPOCH gate respected) |

**Replay-hardening item:** any pipeline read of wall-clock (session labels, EOD rules)
must derive from the snapshot/candle timestamp during replay. The walker injects the
simulated clock; an audit for stray `datetime.now()` in decision paths is part of
REPLAY-2 acceptance.

## 4. Replay Pipeline

```
1. LOAD      candle archive for date D + brain records for D + env manifest M
2. SANDBOX   fresh data dirs; assert no broker credentials; write run manifest
             (git rev, dirty-tree hash, flags, brain mode, seeds)
3. WALK      for each scan tick t: slice candles ≤ t → timeframes → build_snapshot
             (threaded state, RecordedBrain(t), simulated clock)
4. TRACE     emit stage_trace(t): the canonical stage vector (below)
5. EXECUTE   gate-authorized intents → SimBroker; walk outcomes on forward candles
6. SCORE     metrics.py over all scans + trades
7. COMPARE   (optional) against baseline run or against live-session ground truth
8. REPORT    REPLAY VERDICT (md + json artifacts keyed by run-id)
```

Stage vector per scan (the unit of divergence):

```
perception(expansion/vol states) → narrative → brain(direction/family/sovereign)
→ qualification(status/score/disqualifier) → playbook(selected/dir) → toolbox(tool/status)
→ trigger(status/exec_ready) → decision → gate(would_authorize/blockers)
→ intent(created/dir) → broker(sim order) → execution(fill/R/MFE/MAE)
```

## 5. Comparison Methodology

- **Determinism gate first.** Same revision + same flags + RECORDED brain, run twice →
  stage traces must be byte-identical. No A/B is trusted until this passes.
- **Flag ablation (primary).** Same working tree, one flag flipped per run. Cleanest
  attribution; available for every mission since VOL-AUTH-1.
- **Revision A/B (secondary).** `git worktree` checkout of revision B beside working
  tree A; identical dataset + manifest; used when a repair was not flag-gated or for
  cumulative before/after across many commits.
- **Ground-truth calibration.** Replaying revision R over day D that revision R actually
  traded live must reproduce the stored live snapshots' decisions (within declared
  caveats: news off, memory seed). Divergence here is an ENGINE bug, not a bot finding —
  this is how the engine itself earns trust.
- Paired per-scan diff → funnel deltas → trade-level counterfactuals. All runs archived
  under `data/replay/runs/<run_id>/` with manifest, traces, metrics, report.

## 6. Counterfactual Analysis Design

For every trade (taken by either side) and every gate-authorized near-miss:

```
{ scan, direction, zone,
  current_result:  {taken?, R, MFE, MAE, exit_reason},
  previous_result: {taken?, R, MFE, MAE, exit_reason},
  first_divergent_stage: "trigger",          # first stage-vector field that differs
  responsible_subsystem: "toolbox/entry_trigger_prep.py",   # stage→owner map
  responsible_flag: "EXPANSION_CONTINUATION_TRIGGER",       # from ablation run
  classification: new_opportunity | prevented_bad_trade | new_loss | no_change }
```

Repair attribution per mission = aggregate of its flag-ablation classifications:
- **created additional opportunities**: new_opportunity count with R > 0 evidence
- **prevented bad trades**: prevented_bad_trade (previous took it, R < 0; current refused)
- **introduced new losses**: new_loss (current took it, R < 0; previous refused) — the
  metric that keeps us honest
- **no measurable change**: identical funnel + identical trades

The stage→owner map is maintained in `stage_trace.py` alongside the vector definition so
divergence always names a file, not a vibe.

## 7. Validation Metrics

Per run (definitions fixed here so every report is comparable):

| Metric | Definition |
|---|---|
| Brain sovereignty rate | sovereign scans / scans (THESIS-PERSIST semantics) |
| Qualified setups | scans with qualification ≥ candidate |
| Trade intents / Broker intents / Executed | funnel counts |
| Win rate | wins / closed trades (win = R > 0 at exit) |
| Average R | mean realized R |
| Profit factor | gross positive R / |gross negative R| |
| Expectancy | mean R per trade (with count — no expectancy claims under N=5) |
| MFE / MAE | per-trade max favorable/adverse excursion in R (from SimBroker walk) |
| Max drawdown | max peak-to-trough on cumulative R curve |
| Safety invariants | trades > MAX_TRADES_PER_DAY: must be 0; risk > $500: must be 0; daily loss beyond limit: must be 0 — **any violation fails the run outright** |

## 8. Reporting Format

Every run emits `report.md` + `report.json` ending exactly with:

```
REPLAY VERDICT
Dataset:                     2026-07-08 QQQ (148 scans)
Revision / Flags:            <rev> / <manifest-hash>   vs   <rev> / <manifest-hash>
Determinism Gate:            PASS
Ground-Truth Calibration:    PASS (0 undeclared divergences)
Funnel (A → B):              sovereign 20→64 | qualified 25→41 | intents 8→11 |
                             broker 0→2 | executed 0→2
Trades:                      2 (1W / 1L), avg R +0.34, PF 1.9, expectancy +0.34R
New Opportunities:           3   Prevented Bad Trades: 1
New Losses:                  1   No-Change Scans: 121
Safety Invariants:           0 violations
ACCEPTED / REJECTED:         <verdict against acceptance gates>
```

**Acceptance gates for future repairs** (a repair must pass replay before merge):
1. Determinism gate PASS.
2. Safety invariants: zero violations.
3. No unexplained funnel collapse (a stage losing >X% throughput must be named + justified).
4. Expectancy not reduced on the reference dataset without explicit user acceptance.
5. Every behavioral diff attributed to the repair's own flag (no side-effect leakage).

## 9. Implementation Plan

| Phase | Scope | Risk |
|---|---|---|
| **REPLAY-1** | `fetch_1m_candles_range` (additive provider method) + `candle_archive.py` + EOD archiver hook + **immediate backfill of recent sessions** | Data-only; the single trading-adjacent file touch; do FIRST — data is aging |
| **REPLAY-2** | `replay_session.py` walker + `recorded_brain.py` + `stage_trace.py`; wall-clock audit; ground-truth calibration on one day | Isolated package; no trading-logic change |
| **REPLAY-3** | `sim_broker.py` + `metrics.py`; reproduce the hand-scored 2026-07-08 outcomes | Isolated |
| **REPLAY-4** | `compare.py` ablation + `report.py` + acceptance gates; wire into the post-phase workflow (test → **replay** → backup → commit → push) | Isolated |

Each phase: own tests, own commit, full suite green, no safety-file references.

## 10. Recommended First Replay Dataset

**2026-07-08 (calibration day).** BOT-VS-MAURICE hand-scored this day candle-by-candle:
10 intents, 8 deduped setups, confirmed 4W/1L vs unconfirmed 0W/3L, the 13:12 short
+1.69R. The engine must reproduce those known outcomes — this validates the ENGINE
before the engine validates the bot.

**2026-07-09 (attribution day).** The repair-stack day: rich brain records, known
sovereignty baseline (~20/148), and every new flag exercisable by ablation
(REGIME-DEMOTE, MC-ENFORCE, RETEST-DOCTRINE, JUDGE-FREEZE, AI_CONTEXT-AUTHORITY,
BRAIN-FAMILY-REPAIR). Expected first product: the full attribution table for this
week's missions, measured instead of argued.
