# SUPPRESS-1 — Suppression Cost Engine

Date: 2026-07-03 (pre-session — ADAPTIVE-8 measures suppression cost from scan #1)

Blocked trades are not dead. They are unrealized evidence.

## Blind spot BEFORE

Ten block owners (risk_governor, regime_authority, decision_authority,
execution_gate incl. narrative/council/promoted-rules, adaptive_live_authority,
position_supremacy, intent_score gating, execution-engine ops/EOD/guard/sizing
denials) — and every refused opportunity died with zero forward evidence.
The intent archive tracked MFE/MAE only when an intent existed, and nothing
anywhere attributed outcomes to block owners. Tuning was one-eyed: the cost of
trades taken was measurable; the cost of trades refused was invisible.

## Model

`src/adaptive_learning/suppression_cost_engine.py` — SHADOW ONLY:

- **Register** (`register_blocked_candidate`): when a scan carries a real
  opportunity (active qualification / prepare / ready / intent), a non-empty
  DECON-3 block_trace, no submission, and a COMPLETE price plan (entry +
  invalidation stop from the preferred candidate — no synthetic values;
  target = entry ± risk × TAKE_PROFIT_R). One open record per
  (tool, direction); repeat blocks increment `times_blocked` and merge owners.
- **Resolve** (`resolve_shadow_outcome`): each scan advances open records on
  the 1m candle. Limit-style trigger at entry; after trigger, stop vs target;
  a candle spanning both resolves STOP-FIRST (conservative — never over-claims
  false suppression). Session change settles honestly (the live organism is
  EOD-flat): triggered → neutral at last unrealized R; untriggered → expired.
- **Score** (`score_suppression`): `false_suppression` cost +TP_R (missed),
  `correct_suppression` −1R (avoided), `neutral` = unrealized R, `expired` 0.

## Forensics

Per record: suppression_id, block_owners, block_reasons, plan, confidence,
5 dimensions, times_blocked, mfe/mae R, shadow_outcome, suppression_cost,
suppression_duration_scans. Open records in `suppression_open.json`; resolved
records append-only in `suppression_resolved.jsonl`; per-scan telemetry on
`snapshot["suppression"]`, persisted by the DECON-3 writer.

## Adaptive memory feed (observation only)

`suppression_metrics.json` (beside the performance tables): per-dimension
buckets of suppressed_total / correct / false / neutral / expired /
suppression_accuracy. The policy report surfaces it read-only per dimension
(`dimensions.<dim>.suppression`) — NO policy flag reads it. Repeated false
suppressions are now measurable tuning evidence for the threshold-tuning phase.

## Doctrine compliance

Persist contract: the scan loop is the only writer (`track_suppression`);
policy reads are pure. State under the performance root → inherits
PERFORMANCE_TABLES_DIR test isolation. Untouched per hard rules: AI authority,
adaptive policy decisions, mutation engine, execution gate, risk math, MC.

## Regression lock

`tests/test_suppress1_engine.py` (14 tests): A registration + dedup +
refusal paths · B target → false (+2R) · C stop → correct (−1R) + ambiguous
candle conservatism · D neutral at session end · E expired costless ·
F/G bucket increments across all five dimensions · H policy report carries
the evidence with zero flag movement · full track cycle + pure scorer.

Suite: 1416 tests OK. Live substrate hash-verified untouched; no leaks.
