# Pre-Brain Wake Shadow Audit — 2026-09-10

## Decision

This is an offline, observe-only experiment. It does not change the production
scan loop, Brain timing, model, strategy, qualification, risk, authorization,
execution, or position protection. The experiment is **not historically
validated** because no raw PROD-20260908, PROD-20260909, or PROD-20260910
replay bundle was available in this checkout.

The reconciled local checkout is `claude/optimistic-turing-bxpw5k` at
`1bbb8dcc8f73643d848ee94b8c6a59e727260b4e`, tracking the same remote tip. The
audit was initially developed at `0cb155ce8ee0f83197c54ec499a12a3db03d2eac`;
the uncommitted files were preserved while the branch was fast-forwarded. The
two incoming commits modify only `tests/test_retrieval_telemetry.py` and
`tools/topstepx_candle_coverage_audit.py`.

## Production call graph inspected

The relevant path is:

```text
TopstepXProductionLoop._scan_once                    [broker/...production_loop.py:597]
  -> reconcile_missions()
  -> manage_open_position()                          [same file:348]
       deterministic protection/reconciliation; before the entry-authority gate
  -> entry-authority-exhausted gate
  -> coherent candle window and deep context fetch
  -> ProductionScanCycle.scan()                      [live_scan/production_scan_cycle.py:394]
       -> build_snapshot()
            -> when ECU is enabled, produce_thesis()  [market_data/snapshot_builder.py:891]
               before qualification, playbook, risk, toolbox, and execution price
       -> continuity and derived-state revision checks
       -> active-path and setup-lifecycle state
       -> one retrieval call and retrieval telemetry
       -> structure-flip update
       -> ECU canonical thesis, or run_narrative_brain() [ai_brain/narrative_brain.py:551]
            -> build_brain_input()
            -> authorized objective/invalidation catalogs
            -> cognition.escalation_router.observe()  [shadow sink only]
            -> provider call and any repair/fallback handling
       -> optional _two_brain_shadow()               [production_scan_cycle.py:669]
       -> CandidateProducer.produce()                 [production_loop.py:~711]
  -> candidate recording, risk and deterministic submission lifecycle
```

The ordinary non-ECU provider path has a useful pre-provider observation seam:
the snapshot and Brain input exist, the authorized catalogs exist, and the
escalation observer runs before the provider call. That does **not** make it a
safe production wake gate. The ECU path can call inside `build_snapshot`
earlier, before later qualification and execution fields exist. The prototype
therefore refuses ECU records rather than pretending the two pipelines have the
same evidence boundary.

The current `wake_registry` is an accelerator for actionable FVG episode and
quote events. It sets events and never suppresses the normal scan or calls the
Brain. It is not a general ICT interest detector. The cognition escalation
router is also a shadow telemetry sink, not a gate. Existing two-Brain shadow
mode is not enabled for this experiment because its accounted adjudicator can
make paid model calls.

## Offline prototype

`tools/pre_brain_wake_shadow.py` reads an explicit JSON bundle and writes only a
JSON report to stdout. It has standard-library imports only and does not import
the broker, provider, production loop, or model code. There is no production
integration point.

The detector compares whole canonical evidence blocks in sequence. It retains
embedded timestamps, event order, and numeric values. It intentionally wakes on
any change in one of these families:

- session, session PO3, and session context;
- liquidity;
- structure, protected swings, structure flips, and MTF state;
- active-path ownership;
- expansion, volatility, and PO3 delivery;
- market regime and market context;
- setup lifecycle;
- executable quote;
- candle continuity and derived-state currency;
- authorized tools, objectives, and invalidations.

This is deliberately conservative and may wake every bar. No volatile field was
discarded, no dwell or quantization threshold was tuned, and no binary PO3 veto
was introduced. A forming setup or authorized catalog change can wake the
shadow; a fully bound mechanical candidate is not required.

The observer emits `WAKE_SHADOW`, `HOLD_SHADOW`, or
`PRESERVE_BASELINE`. Invalid, missing, stale, duplicated, out-of-order,
non-contiguous, non-current, post-call, or unsupported-ECU evidence cannot
support a hold. A session or contract change, restart, or uncertainty reset
bootstraps a wake. Every output carries `production_action: NONE` and
`production_authorized: false`.

Historical labels are joined after detector decisions by the exact
`session_id + contract_id + scan_id` identity. A wake on an earlier scan gets no
credit for a candidate appearing on a later held scan. Same-scan capture is only
an observed-label recall proxy, not a counterfactual proof: suppressing a prior
Brain call could change stance, retrieval, future state, and later actions.
`model_calls_saved` and `cost_saved` therefore remain unknown in every report.

## Evidence status

The email summary reports for PROD-20260910: 597 scans, 598 requests (597
primary plus one JSON repair), zero trades, 565 stand-downs, and 32
`action_declines_entry` rows. Those are useful operational claims but are not a
replay bundle. The checkout contains no raw PROD-20260908, PROD-20260909, or
PROD-20260910 pre-call snapshots, candidate-decision/lineage exports, or model
call ledger that can independently establish the counterfactual.

Accordingly, this audit reports:

- historical wake recall: **UNKNOWN**;
- historical holds: **UNKNOWN**;
- calls saved: **UNKNOWN**;
- cost saved: **UNKNOWN**;
- whether zero-trade calls were avoidable: **UNPROVEN**.

The Sept. 10 one-minute candle-store absence is retained as an operational
incident from the email, but it did not create a consumed-window hole according
to that report. This audit does not classify its cause without the raw store
and capture evidence.

## Required replay bundle

For each of PROD-20260908, PROD-20260909, and PROD-20260910, provide an
exported bundle covering every scan in chronological order, including scans
with no candidate. The bundle must contain:

1. the exact pre-provider snapshot and Brain input as-of each call boundary,
   with `session_id`, `contract_id`, `scan_id`, sequence, timezone-aware
   observation time, capture stage, and pipeline mode;
2. the complete evidence blocks used by the prototype, including continuity,
   derived-state revisions, executable quote freshness and bid/ask, active-path
   state, setup lifecycle, and all authorized catalogs;
3. an independently auditable candidate label manifest joined by exact scan
   identity, including trade and order/position lineage where a candidate
   produced a mission or trade;
4. the model-call ledger separated by primary, JSON repair, other repair,
   fallback, cache, and failed request roles, with session and source-version
   binding;
5. exporter provenance proving that the packet is pre-call, not a post-call
   snapshot relabeled as pre-call, plus coverage counts that can be checked
   against the session recorder.

A final healed OHLCV tape alone is insufficient: it cannot prove what the
organism knew at the original call boundary, which revision was current, or
whether a later candidate depended on the earlier Brain output.

## Verification performed

On the reconciled branch, the focused regression set, including this prototype,
wake tests, cognition router tests, two-Brain protections, break-even
binding/wiring, session-cap behavior, readiness, fingerprint portability, and
the remote retrieval-telemetry repair, passed **355 tests**, with 56
archive/history-dependent skips and one pre-existing pytest deprecation
warning. The full repository discovery run passed **7,296 tests**, skipped 583,
reported 34 subtests and 9 warnings. Compilation passed and no tracked or
untracked trailing whitespace was found. The three missing-session CLI probes
returned exit code 2 with `MISSING_EVIDENCE`.

The prototype remains uncommitted by design. No production file was modified,
and no wake-gate or model-cost optimization should begin until independently
auditable replay bundles are available. `action_declines_entry`, shutdown
durability, and process-local arm state remain separate follow-up audits.
