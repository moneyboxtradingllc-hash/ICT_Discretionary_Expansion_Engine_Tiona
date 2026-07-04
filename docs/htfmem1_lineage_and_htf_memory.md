# HTF-MEM-1 + TRADE LINEAGE PURIFICATION

Date: 2026-07-04. Truth first. Then memory.

## PHASE 0 — lineage verdict (evidence, not assumption)

| Trade | R | Classification | Proof |
|---|---|---|---|
| PT_QQQ_20260609T114426 | −4.81 | STALE_PRE_AI + MANUAL_CLOSE_STOP_FAILURE | `close_reason: externally_closed`, held OVERNIGHT 17h55m, loss 4.8× the 1R design (stop never fired), playbook `infrastructure_test`, batch-closed 06-10 09:26 |
| PT_QQQ_20260609T120049 | −0.03 | STALE_PRE_AI + MANUAL_CLOSE_STOP_FAILURE | externally_closed, overnight, batch 09:25 |
| PT_QQQ_20260609T120356 | −0.12 | STALE_PRE_AI + MANUAL_CLOSE_STOP_FAILURE | externally_closed, overnight, batch 09:24 |
| PT_QQQ_20260610T115837 | −0.72 | STALE_PRE_AI | broker stop worked, but wrapper-era authority — pre-Brain, pre-FC, pre-OPS-1 |
| PT_QQQ_20260611T102953 | −1.34 | STALE_PRE_AI | THE documented June-11 incident that triggered FC-0A/0B that same day |
| 5E8VAL_E053ABD4 | — | SYNTHETIC | `SYNTHETIC_*` oid (already gate-excluded) |

Git timeline: FC-0A/0B landed June 11 AFTER the last close; AI Brain (AB-1)
and ECU sovereignty June 12–15. All five predate the Brain entirely.
**FOREIGN_OR_CONTAMINATED: none found** — real Alpaca UUIDs in Maurice's QQQ
journal; Topstep code never wrote Alpaca journals (DECON-1 verified).

## PHASE 1/2 — quarantine + rebuilt baseline

- `data/performance/QQQ/` (tables + ledger) moved to
  `data/performance_quarantine_PREAI_20260704/` with a classification
  MANIFEST. Journals left in place as historical evidence; nothing deleted.
- **ORGANISM_EPOCH** (default `20260706`, env `ORGANISM_EPOCH_DATE`): the
  DECON-2 write gate now rejects pre-epoch entries
  (`write_gate:pre_epoch_lineage`) and capital's journal reads are
  epoch-filtered — quarantine is enforced by code, not just by a file move
  (a rebuild-tool run can never re-import the disputed history).
- Read paths no longer create directories (reader-hygiene fix across
  decay/suppression/capital) — the live performance root stays EMPTY through
  a full test-suite run.

BEFORE → AFTER: table trades 5→0 · ledger 5→0 · loss_streaks →0 · every
grade → insufficient_data · penalties/blocks → none · capital → probation
(closed 0, weekly 0, risk_efficiency None) · scar memory empty · suppression
memory empty (born post-epoch). **Monday starts from zero honest evidence.**

## PHASE 3–6 — Higher Timeframe Memory

`src/market_data/htf_memory_engine.py` — daily OHLC accumulated ONLY from
real observed 1m candles (no synthetic backfill; the 300-bar lookback
naturally seeds the prior session), persisted at `data/htf_memory/<SYM>.json`
(env `HTF_MEMORY_DIR`; scan loop is the only writer). Outputs: daily_context,
weekly_context (direction/strength/HH-LL over ≤5 sessions),
previous_session_context (+swept flags), gap_context (points/pct/side/filled),
liquidity_context (untapped prior-day highs/lows = draw candidates),
htf_bias + htf_confidence (bounded by memory_age — thin memory can never be
confident), memory_age, htf_conflict_flags (HTF bias vs narrative direction +
unfilled gaps, computed pre-Brain so the Brain sees the warning).

Wiring: scan_loop `htf_engine.update(candles_1m)` → `build_snapshot(...,
htf_context=)` → `snapshot["htf_memory"]` attached BEFORE the ECU pre-pass →
`brain_input` includes it (NEWS-1 pattern) → persisted by the DECON-3 writer.
**Context only:** authority_level hard-locked `context_only`; source-guard
test proves the gate, decision engine, risk governor, mutation engine, and
execution engine never read it.

## Tests

`tests/test_htfmem1_lineage_and_memory.py` (13): A pre-epoch rejection +
post-epoch acceptance + epoch default · B zero baseline everywhere ·
C capital blind to disputed losses · D four pre-epoch losses fold nothing ·
E daily memory + restart persistence + untapped-draw liquidity · F weekly
direction over 5 sessions + thin-memory confidence cap · G Brain-input feed ·
H authority hard-lock + source guard. Epoch-affected fixtures updated
(DECON-2 gate tests, adaptive3 tables).

Suite: 1464 tests OK. Live adaptive state EMPTY and clean through full suite.
