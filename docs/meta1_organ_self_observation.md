# META-1 — Meta-Awareness Engine (organ self-observation)

Date: 2026-07-03 (pre-session — the organism watches itself from scan #1)

The organism watches the market. Now it watches itself.

## Blind spot BEFORE

Every organ recorded its own output (DECON-3), but nothing WATCHED the
recordings: brain fallbacks, thesis flapping, authority contradictions,
adaptive re-lock loops, false-suppression clusters, denial storms, and store
corruption were all discoverable only after damage — reactive, not proactive.

## Drift model (PHASE 2 — exact signals)

| Organ | Signal | Level | Trigger |
|---|---|---|---|
| brain | fallback_frequency | degraded | >30% of window scans on fallback/degraded input |
| brain | thesis_flip_frequency | watch | >40% direction flips across directional scans |
| brain | confidence_instability | watch | phase-confidence swing >35 in window |
| authority | contradiction_spike | degraded | >50% of scans carry AB-4 divergence / MC contradictions / narrative conflicts |
| adaptive | excessive_mutation_frequency | watch | mutation active on >80% of scans |
| adaptive | repeated_relocks | degraded | any scar record lock_count >= 3 (probation keeps failing) |
| suppression | false_suppression_cluster | degraded | bucket with >=3 false suppressions and accuracy <0.40 |
| suppression | overblocking_owner | watch | one owner on >=90% of blocked opportunities (>=6) |
| execution | denial_cluster | watch | >=95% of >=6 real opportunities die pre-broker |
| execution | broker_error_observed | degraded | any broker error in window |
| memory | table_ledger_mismatch | CRITICAL | table trades != idempotency ledger |
| memory | suppression_metrics_mismatch | CRITICAL | outcome parts != suppressed_total |

Scoring: watch +8 / degraded +20 / critical +40, capped 100. State: any
critical signal → critical; else 0 healthy, <25 watchlist, <50 degraded,
else critical. Rolling window 30 scans (min 6 before rolling signals fire).

## Engine

`src/adaptive_learning/meta_awareness_engine.py` — `MetaAwarenessEngine`
(`inspect_organs` / `detect_drift` / `score_instability` /
`generate_health_report`). One instance owned by the scan loop; store reads
(tables, ledger, scar_state, suppression_metrics) are READ-ONLY under the
performance root. Never raises — on internal failure it reports organ "meta"
as degraded instead of guessing organism health.

## Integration + forensics

`snapshot["meta_awareness"]` every scan (after all organs settle, before
persistence) with organ_health, per-organ aliases (brain_health,
authority_health, adaptive_health, suppression_health, execution_health,
memory_health), drift_signals, instability_score, watch_flags,
critical_flags. Persisted verbatim by the DECON-3 writer; console prints one
line whenever state != healthy.

## Observe-only governance (PHASE 6)

authority_level hard-locked observe_only. No consumer reads META-1 for
authority; the test lock proves no store writes and no authority fields.
Future governance may consume it — not now. (The AI-AUTH-1 MC-consumer guard
allowlists the meta engine explicitly as an observability witness.)

## Regression lock

`tests/test_meta1_awareness.py` (15 tests): A brain drift (fallback storm,
flip/confidence instability, and stable-brain-stays-healthy) · B contradiction
spike · C false-suppression cluster + overblocking owner · D repeated
re-locks · E denial cluster + broker error · F table/ledger and metrics
mismatches are CRITICAL · G healthy scores exactly healthy (0) ·
H stacked failure scores critical · observe-only lock (no writes, no
authority, never raises).

Suite: 1431 tests OK. Substrate hash-verified untouched; no leaks.
