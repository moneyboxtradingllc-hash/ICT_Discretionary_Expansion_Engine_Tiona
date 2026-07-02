# DECON-2 — Performance Table Purification

Date: 2026-07-02

Truth before memory. Memory before adaptation. Adaptation before capital.

## Contamination (proven, not guessed)

`data/performance/QQQ/*` held **132 trades, 132 wins, 0 losses, every trade
exactly +2.3R** — while the real journal history contains **5 real closed
trades: 0 wins, 4 losses, 1 breakeven (sum −7.02R)**. The tables were a total
inversion of reality.

Vector, proven empirically: `tests/test_phase_adaptive1a5_runtime_wiring.py`
isolated `AI_RETRIEVAL_DIR` and `PAPER_TRADES_DIR` but **not**
`PERFORMANCE_TABLES_DIR`. Its fixture (+2.3R QQQ win) flows through
`record_closed_trade_scar()` → `update_performance_tables()` → live tables.
One run of that file writes exactly **12 synthetic wins** (measured against a
sandbox). 132 = 11 accumulated runs. The scar store deduped (hiding the leak);
the tables had no dedup, so every rerun re-counted.

## Writer map (post-DECON-1)

| Writer | Call site | Gated? |
|---|---|---|
| `performance_tables.record_result` | low-level primitive; production reaches it only through `update_performance_tables` | via caller |
| `performance_tables.update_performance_tables` | ONE production call site: `outcome_assembler.record_closed_trade_scar` (scan-loop reconciliation close event) | **STRICT GATE + LEDGER** |
| `tools/rebuild_performance_tables.py --apply` | operator-run rebuild; uses the same gated pipeline | same gate + ledger |

## Hardening

**Strict write gate** (`validate_performance_write`): a table write requires a
reconciled `status=closed` trade with a real non-synthetic execution id
(`alpaca_order_id`), entry + exit timestamps, numeric realized pnl, and a valid
symbol, playbook, and session. Test fixtures, replays, studies, manual inserts,
and null-execution records are rejected with `write_gate:<reason>` telemetry.
The 5E8 harness record (`SYNTHETIC_*` order id) and the 1A.5 fixture shape are
both rejected by construction.

**Idempotency** (`applied_writes.json` per symbol):
`sha256(symbol|entry_ts|exit_ts|execution_id)`. A trade folds exactly once;
restarts, re-reconciliations, and reruns are ignored safely (`duplicate_write`).

**Dimensional capture**: `execution_engine._snapshot_summary` now records the
executed `tool`, closing the write/read key mismatch that sent every trade to
tool="unknown". (Registered as a deliberate scoped revision in the ADAPTIVE
guard tests, like ADAPTIVE-7's order_builder entry.)

**Test isolation**: `PERFORMANCE_TABLES_DIR` added to the 1A.5 isolation set;
adaptive3 fixtures upgraded to gate-valid unique trades. Full-suite proof:
sha256 of live tables identical before/after `unittest discover`.

## Purge + rebuild

- Contaminated tables quarantined at `data/performance_quarantine_DECON2_20260702/` (local, git-ignored).
- Live `data/performance/QQQ/` purged, then rebuilt via
  `python tools/rebuild_performance_tables.py --apply`:
  **5 accepted (all real), 1 rejected (`synthetic_execution_id`)**; second
  apply run: **0 accepted, 5 duplicate_write** (idempotency live-proven).

## Rebuilt substrate (verified TRUSTED)

Every dimension totals 5 trades / 0W / 4L / 1BE / sum −7.0239R (exp −1.40R),
matching the journal exactly; per-bucket counts, expectancies, and streaks all
recomputed and consistent; ledger holds 5 unique trade ids.

Honest live consequence to be aware of: with real losses on the books, the
DEFENSIVE_ONLY adaptive policy will now recommend confidence penalties /
risk reduction for the weak buckets (e.g. session `morning_continuation`,
expectancy −1.58 over 4 trades). That is the system doing its job on truth.
