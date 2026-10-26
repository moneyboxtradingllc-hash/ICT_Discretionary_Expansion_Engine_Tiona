# Participation-refusal telemetry repair: completion report

Contract: `TIONA_TELEMETRY_REPAIR_CONTRACT_20261025.zip`, SHA256
`78a0635306fbdbc5955fa734bbf3f2dae3ef6d12da322f4fa55b24672dd46d04` (Gmail `1a17533dba44f946`). The nested
`OFFLINE_AUTHORITY_RECONCILIATION_20261025.zip` (`921d9773…`, 31 artifacts) was verified: 31/31 manifest OK.

Everything was offline. No paid, current-model, provider or venue call was made, and no credentials or
private Mac state were used. Nothing was merged, deployed, armed or ordered; production stays disarmed.
No economics, risk, execution, participation, Lifecycle, Draw, D3, transfer-family or prompt change was made.

**Doctrine reconciliation and natural-model recognition remain unproven by this telemetry patch.**
That covers successor chronology, protected-high ownership and transfer-proof vocabulary, which Codex owns.
Production remains disarmed.

The superseded eval-preparation work is preserved, unmerged, at `preserve/current-brain-eval-prep-wip-20261025`
(`cf0950f`). It is not part of this branch.

## Identity

| | Parent | Final |
|---|---|---|
| SHA | `7b5218ac2fe9bdc1f348c1c433fa4060ae8ba3a2` | `14c996cea5b636beaba9d0e0a3d4d73dee8b4fdc` |
| Tree | `d1ef036f1b2dbb5d91f53243673580f85767ad5e` | `5cb9414e5958e27a2b588e88b4301b57be1112de` |
| Brain (measured) | `brain:d17223b71ac698ff` | `brain:43569c8bd11004d7` |
| Retrieval | `retr:0c241bdb8234d1ba` | `retr:0c241bdb8234d1ba` (unchanged) |
| Closure | 49 | 49, same paths; only `src/broker/topstepx_production_loop.py` changed |
| Protected pins | 32 | 32, all byte-identical (parent = final = pin) |

- Branch: `review/participation-refusal-telemetry-20261025`, one commit on top of the parent.
- Ledger entry: `PARTICIPATION_REFUSAL_TELEMETRY_20261025`. `tools/verify_engineering_ledger.py` returns
  LEDGER_VERIFIED with 32 protected sources verified and fingerprints checked (`identity/LEDGER_VERIFY.json`).
- Fingerprint repin: the closure member `topstepx_production_loop.py` changed, so the Brain fingerprint
  rotated. Only the same 7 literal expectations Phase 3 repinned were updated to the measured value: 3
  disabled example JSONs and 4 test literals. No strategy behaviour was repinned.
- Source: `source/FULL_DIFF_7b5218a_14c996c.diff` (13 files, +1013/−12) and
  `source/participation_refusal_telemetry.bundle` (prerequisite 7b5218a; `git bundle verify` okay).

## The defect, reproduced on the parent

The owner reproducer `test_offline_boundaries.py` was run unchanged except for its scratch-root path
assumptions; no assertion was edited. On the parent it gave **7 passed** in both lanes
(`parent_reproduction/`). Example from the actual recorder at scan `scan-20260819T143700`:

- **Available on the scan:** `AUTHORITY_UNKNOWN / campaign_draw_authority_unknown`.
- **Stored in the journal:** `campaign_lifecycle_refused: campaign_lifecycle_refused:AUTHORITY_UNKNOWN`, as
  `UNCLASSIFIED`; `reconcile()` returns CANDIDATE_DECISION_ACCOUNTING_FAILURE.

On the final source, the same unchanged file shows **2 failed, 5 passed** (`final_reproduction/`). Both
failures are the defect-asserting lane cases, which now fail with
`assert 'PARTICIPATION_REFUSED' == 'UNCLASSIFIED'`.

- The three other whole-path tests (scope/plan/fresh-quote and C2, both lanes) still pass.
- The owner's last test also still passes, and that is correct: a bare `build_record` row without the
  live loop's v2 evidence stays unaccounted.

These defect-asserting tests are parent evidence only. The corrected expectations live in
`tests/test_participation_refusal_telemetry.py`.

## What changed (smallest backward-compatible schema)

1. **`src/broker/candidate_decision_record.py` (not bound, not protected).**
   - Adds the `PARTICIPATION_REFUSED` terminal category. It is neutral: never `STOOD_DOWN`, never a
     candidate. The single mapping `campaign_lifecycle_refused → PARTICIPATION_REFUSED` is added.
   - Adds `participation_evidence` / `attach_participation_evidence`, which upgrade a live record to
     `candidate_decision.v2`.
   - Adds `refusal_problems` and a stricter `reconcile`.
   - v1 rows keep their exact old semantics; `build_record` and `blank_trace` are unchanged.
2. **`src/broker/topstepx_production_loop.py` (bound).** The recorder's signature is unchanged.
   - The two `NoCandidate` handlers hand the refusal over as `self._decision_refusal = (scan_count,
     snapshot_id, exc)` immediately before recording.
   - `_record_decision` consumes it only when it matches this scan and reason, clears it, then calls
     `attach_participation_evidence` inside the existing best-effort `try`. It passes the scan, the parsed
     output, the Phase 3 current-scan marker and the loop's own producer trace (only when current).
   - Nothing else in the loop changed.
3. Tests and docs: the new module, the 7 repins, and a one-entry extension of the Phase 3 reader-scope
   guard (explained under Limitations).

The schema, the cause → code → reader map and the reconciliation rules are in
`docs/recognition_validation/PARTICIPATION_REFUSAL_TELEMETRY.md` (copied as `01_SCHEMA_AND_READER_MAP.md`).

**Gate attribution comes from the actual raiser, never from a label.** The only two raisers of
`campaign_lifecycle_refused` are:

- **`PRODUCER_LIFECYCLE_GATE`**: identified by the producer's own `NoCandidate.decision_trace` under the
  loop's current-scan marker.
- **`LOOP_PARTICIPATION_BINDING`**: the loop's own binding, which raises before `produce()`, so the
  producer is not reached.

Detailed reasons come only from the assessment's own `reason` field or the exception's `detail`. A
diagnostic pointer to the gate function is stored separately and labelled `DIAGNOSTIC_POINTER_NOT_OBSERVATION`.

## Acceptance (both ECU and non-ECU)

| # | Proof | Result |
|---|---|---|
| 1 | Real loop (W5 natural tape, CONTROLLED Brain): every refusal persists the exact same-scan state and reason, gate, identity, Draw/acceptance/scope, authored vs consumed intent; reconciles | PASS. Real reasons include `campaign_draw_authority_unknown`, `campaign_draw_participation_withheld:pre_cognition_campaign_draw_retired_by_current_acceptance` and `settled_campaign_objective_touch_proven` (`final_records/LOOP_RECORDS_*.json`) |
| 2 | Healthy control | `QUALIFIED_CANDIDATE_OBSERVED` / `EXECUTION_DISARMED`; zero tokens, attempts and venue calls. `STOOD_DOWN` (`action_declines_entry`) stays distinct |
| 2b | Stable parent vs final (healthy and retired, both lanes) | Identical outcomes for every minute, candidate geometry, plan, tokens, attempts, venue calls and payloads, and every v1 record field. The only change: 6 rows per case `UNCLASSIFIED → PARTICIPATION_REFUSED` (`stable_comparison/STABLE_COMPARISON.json`). Per-run ids were alpha-renamed only for the comparison |
| 3 | Mechanical states through the actual recorder | ESTABLISHING (Friday tape 13:16–13:18, `active_path_causal_hypothesis_only`); TRANSFER_UNRESOLVED (C2 03:07–03:14, `narrative_control_transfer_not_yet_confirmed`); newborn Draw (W5 T3); real loop-binding mismatch (`participation_authority_bound`, foreign session). All exact and all reconciled. The retired formation's `tool_not_detected` is unchanged (`UNCLASSIFIED`, no refusal block) |
| 4 | Custody: stale previous-scan trace, decoy cycle producer, foreign contract, skipped producer, superseded scan-level copy, missing acceptance/scope/Draw/intent | No leakage. Typed `UNKNOWN`/`ABSENT`; foreign or unattributed refusals never reconcile |
| 5 | Readers: mixed v1/v2, legacy refusal, derived reclassified copy, unknown reason, 8 malformed shapes, 3 contradictory dispositions, session report on a mixed journal | Legacy stays `UNCLASSIFIED`. The derived copy is `PARTICIPATION_REFUSED` but incomplete (`legacy_record_lacks_participation_refusal_evidence`). Malformed and contradictory rows never go green. Journal bytes are unchanged |
| 6 | Failure isolation: evidence capture raises; journal write fails; oversized or nested input | Outcomes identical; the record is still written as v1 or nothing is written; capture errors are typed; output stays bounded and holds no account fields. No participation module reads the telemetry |
| 7 | Activated mutants on final code (`mutants/`, at 14c996c) | M1 drop Lifecycle fields: 27 caught. M2 generic `UNCLASSIFIED`: 11 caught. M3 stale ownership: 4 caught. M4 blanket reconcile pass: 14 caught. M5 blanket unknown-reason mapping: 19 caught (including the existing decision-accounting tests). M6 stale refusal hand-off (scan key ignored): 1 caught. Healthy final passes. Mutants were never committed |
| 8 | Existing controls rerun (focused): conditional plan, bound plan across a fresh cutoff, lost custody, brainless trigger, final quote, narrative-history separation, decision-trace ownership, fingerprint/safety readiness | PASS; see Focused below |

## Superseded checkpoint (disclosed)

An earlier candidate, `02361b7`, passed `refusal=exc` to `_record_decision` as a new keyword argument.

- Its full suite was stopped at about 20% when shard 3 failed 18 cases in
  `test_campaign_draw_exact_binding.py` and `test_campaign_draw_temporal_authority.py`.
- Those tests (and five other test files) replace `loop._record_decision` with fixed-signature lambdas, so the new
  keyword raised `TypeError` (`focused/superseded_02361b7_recorder_signature_finding.log`).
- The fix is the scan-keyed hand-off above. It keeps the recorder's signature identical to the parent's and adds a
  regression for a refusal left by another scan.
- The 176 tests of every recorder-replacing file plus the new module pass
  (`focused/rerun_after_handoff_fix_176.log`).
- All final evidence (reproducers, stable comparison, records, mutants, full suite) was regenerated at `14c996c`.

## Focused and full suite

- **Focused** (`focused/`): 20 files, 542 tests, run on the tree before the first commit. Result: 531 passed, 9 skipped, 2 failed.
  1. **`test_session_evidence_contract::test_24…`** I invoked this operator-state file explicitly, which
     bypasses the `tests/conftest.py` `collect_ignore` that excludes it from the supported suite. It needs
     an untracked live corpus. It fails identically on the parent and is not a regression.
  2. **`test_market_narrative_first::test_no_authority_module_reads_the_observational_view`** This was a
     real finding: the journal writer reads the `authored_market_read` envelope. It was resolved by the
     justified guard extension under Limitations.
- **Full isolated suite at the final frozen source `14c996c`** (`full_suite/`). Setup: four fresh clones; one
  `--collect-only` of the supported `tests/` scope; four file-disjoint shards, each in a separate process under
  the credential-free, network-denied runner (`run.sh.txt`).
  - **9826 collected = 9826 unique JUnit testcases**, across 361 files; disjoint and equal to the collection.
  - **9243 passed, 583 skipped, 0 failures, 0 errors** (plus 34 subtests).
  - The skipped set is identical to the parent's accepted Phase 3 run: the same 583 test IDs and the same 40
    reasons (`skip_accounting.json`).
  - The parent had 9786 tests; the new module adds 40.

## Known limitations

- **Historical journals.** The original Friday journal (PROD-20261023-C1) is not in this environment, so
  it was neither read nor rewritten. Historical rows stay v1, keep their `UNCLASSIFIED` status, and gain
  no claimed reason. Any reclassification is a separate derived copy that stays incomplete.
- **Reader-scope guard extended.** Phase 3's guard
  (`tests/test_market_narrative_first.py::test_no_authority_module_reads_the_observational_view`) now
  allows exactly one new reader, `broker/candidate_decision_record.py`.
  - Contract item 3 requires the existing authentic envelope for pre-hold intent.
  - The writer copies only `authored_action`, `narrative_direction` and `pre_hold_output_digest`.
  - The test now also asserts that the writer never reads `descriptive_market_read` or
    `market_narrative_history`.
  - The new module proves no participation module reads the journal.
- **ESTABLISHING evidence comes from the cycle, not the loop.** No existing loop-level fixture reaches
  ESTABLISHING or TRANSFER_UNRESOLVED. Those states, and the newborn Draw, were exercised through the
  actual `ProductionLoop._record_decision` on real `ProductionScanCycle` scans with real
  `CandidateProducer` refusals. The host object supplies only the cycle, producer and marker; this is
  the cycle-plus-recorder path rather than the full loop tick. Unknown Draw, retired-by-acceptance and
  delivered destination were exercised through the full loop.
- **Lifecycle refusals only.** `PARTICIPATION_REFUSED` covers `campaign_lifecycle_refused` alone. The
  other deliberately unmapped producer reasons (`tool_not_detected` and others) are unchanged and still
  fail reconciliation, as before.
- **Supplemental runtime.** Linux Python 3.12 in a credential-free runner with network denied
  (`g5/run.sh`). This is not Mac or live certification.

## Index

See `INDEX.md` and `MANIFEST_SHA256.txt`.
