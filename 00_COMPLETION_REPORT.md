# Participation-refusal telemetry: bounded reader correction (completion report)

Request: Codex's independent audit of `14c996c`, Gmail `1a1761ba4f60d14b` ("BOUNDED TELEMETRY CORRECTION — eight
independent reader controls; no policy changes"). Package `OWNER_TELEMETRY_AUDIT_14c996c.zip`, SHA256
`e8700d5f…` (896,109 bytes); its manifest verified with 0 mismatches. The audit text and the bounded request
are copied under `identity/CODEX_*`.

Everything was offline. No paid, current-model, provider or venue call was made. No pricing or budget work
was done, and no credentials or private Mac state were used. Nothing was merged, deployed, armed or ordered;
production stays disarmed.

There is no Brain, strategy, transfer, D3, Draw, Lifecycle, risk, economics, capture or loop change. The
correction is reader validation only, in one file outside the bound closure.

**Codex keeps the three doctrine questions** (successor chronology, protected-high ownership, transfer-proof
vocabulary). **Natural-model recognition and trading readiness remain unproven.**

## Identity

| | Audited submission | Corrected final |
|---|---|---|
| SHA | `14c996cea5b636beaba9d0e0a3d4d73dee8b4fdc` (preserved, unchanged) | `ec8197ec5411fcbcae5b25ba5a4c395f82c122cc` |
| Tree | `5cb9414e5958e27a2b588e88b4301b57be1112de` | `f28923b6b758cff123cb661600fca14dff9fd503` |
| Brain (measured) | `brain:43569c8bd11004d7` | `brain:43569c8bd11004d7` (unchanged, no repin) |
| Retrieval | `retr:0c241bdb8234d1ba` | `retr:0c241bdb8234d1ba` (unchanged) |
| Closure digest | `e15f8493…f5fffc0f` | `e15f8493…f5fffc0f` (identical; 49 paths, none changed) |
| Protected pins | 32 | 32, byte-identical; none in the diff |

- Branch: `review/participation-refusal-telemetry-20261025`, `7b5218a → 14c996c → ec8197e`. The correction is
  one commit on top of the audited submission. Nothing was rewritten or force-pushed.
- Correction diff `14c996c..ec8197e`: 4 files, +229/−4 (`source/CORRECTION_DIFF_14c996c_ec8197e.diff`).
  - `src/broker/candidate_decision_record.py`: not bound, not protected.
  - `tests/test_participation_refusal_telemetry.py`.
  - `docs/recognition_validation/PARTICIPATION_REFUSAL_TELEMETRY.md`.
  - `docs/recognition_validation/ENGINEERING_LEDGER.md`.
- Whole change from the parent `7b5218a`: 13 files, +1238/−12 (`source/FULL_DIFF_7b5218a_ec8197e.diff`). The
  bundle `source/participation_refusal_telemetry_correction.bundle` needs prerequisite 7b5218a; `git bundle
  verify` returns okay.
- Ledger entry `PARTICIPATION_REFUSAL_TELEMETRY_CORRECTION_20261026`: parent `14c996c`, receipt
  `7a900a64c417add61caac0106923ae91238576bb3facab0401f126ce1366c1c0`. `tools/verify_engineering_ledger.py` returns
  LEDGER_VERIFIED, with 32 protected sources verified, fingerprints checked, and the closure unchanged since the
  latest parent (`identity/LEDGER_VERIFY.json`).
- `identity/PINS_AND_CLOSURE_14c996c_ec8197e.json` and `identity/PINS_AND_CLOSURE_7b5218a_ec8197e.json` record
  per-file pin, parent and final hashes, the closure comparison and the changed files.

## The defect, reproduced at the audited submission

I ran Codex's `test_independent_reader_integrity.py` unchanged against the actual loop-emitted records from the
original package (`codex_reader_test/`):

| Source | Result |
|---|---|
| `14c996c` (my rerun) | **8 failed, 2 passed**. This matches Codex's run: every attack returned `RECONCILED`, and only the untouched controls passed |
| `ec8197e` | **10 passed**. All four attacks × two lanes are `CANDIDATE_DECISION_ACCOUNTING_FAILURE`; untouched records still reconcile |

Per-attack reports from both runs are kept (`READER_ATTACK_*.json`).

## Root cause

`refusal_problems` checked only `scan_id` and `contract` of the nested identity against the record. It never
compared the duplicated Lifecycle fields with the same record's `campaign_lifecycle_assessment`. The session,
the settled cutoff, and the state, reason, permission and other duplicated fields could each be foreign,
missing or contradictory while the report still marked the row complete.

## What changed (`src/broker/candidate_decision_record.py` only)

1. **Identity is required and belongs to the enclosing record.**
   - `session_id` and `settled_cutoff` are now required, like `scan_id` and `contract`.
   - `session_id` must equal the record's own.
   - `settled_cutoff` must be a strict canonical instant under the existing
     `market_data.object_identity.canonical_instant(strict=True)` semantics. It must also equal the record's
     `timestamp_et`.
   - The loop writes `timestamp_et` from the same scan's settled `market_data_timestamp` (`str(snapshot.timestamp)`),
     which is the same instant. The scan-id clock (`scan-…T143700`, one minute after the settled 14:36 bar) is
     never used. A permanent test asserts the two differ in real records.
   - Naive, unparseable, missing or other-instant cutoffs are incomplete. The same instant spelled with `Z`
     still reconciles.
2. **Duplicated refusal fields are checked against the record's own assessment.**
   - A missing or malformed assessment is incomplete.
   - `lifecycle_status` must equal the assessment's `status`.
   - When the assessment is AVAILABLE, these fields must each equal the assessment's: state, reason, permission,
     authorized direction, narrative control state, phase, episode and objective.
   - The producer gate's `campaign_lifecycle_refused:<STATE>` label must name that state.
   - `campaign_lifecycle_direction_mismatch`, and a loop-binding refusal, require a permissive assessment.
3. **Preserved, and proven through the real report:**
   - a loop-binding refusal on a permissive `ACTIVE_DELIVERY` assessment;
   - a producer direction mismatch on a permissive assessment;
   - the internally consistent `current_campaign_lifecycle_assessment_unavailable` refusal.

   All three reconcile. A direction mismatch on a non-permissive assessment is now caught.

Optional supporting evidence (Draw, acceptance, scope, authored intent) stays typed UNKNOWN/ABSENT and is not
required. No historical fact is fabricated, and no journal is rewritten. This detects inconsistency inside a
record; it does not authenticate an archive that was rewritten coherently. These rules are documented in
`01_SCHEMA_AND_READER_MAP.md` (also committed).

## Permanent actual-reader tests (`tests/test_participation_refusal_telemetry.py`, section 6)

- A module-scoped fixture runs the real `ProductionLoop` (`G._loop`, both ECU and non-ECU) and takes the
  actual refused v2 records. Every case goes through `tools/topstepx_session_outcome_report.py::decisions` on a
  JSONL journal.
- **13 attacks × 2 lanes must never report complete:**
  - Codex's four, verbatim: foreign session, missing settled cutoff, conflicting Lifecycle reason, conflicting
    Lifecycle state.
  - Missing session; naive cutoff; unparseable cutoff; scan clock used as the cutoff.
  - Conflicting permission; conflicting control state; conflicting status.
  - Assessment removed; assessment state rewritten alone.
- Further tests:
  - untouched records reconcile;
  - the scan clock differs from the settled cutoff;
  - equal instants in other spellings reconcile;
  - the valid binding, direction-mismatch and unavailable refusals reconcile, and a non-permissive direction
    mismatch is caught.
- Synthetic fixtures now follow the real loop chronology (`market_data_timestamp` and `timestamp_et`).
- The module has 73 tests (it had 40 at `14c996c`).

**Permanent tests at the audited submission** (`submission_reproduction/`): the corrected module was placed
inside a clean `14c996c` checkout, run, then removed. Result: **25 failed, 9 passed**.

- 24 of the failures are 12 attacks × 2 lanes that the submission marked complete.
- The 25th is the valid-case test, failing only on its new negative assertion (a non-permissive direction
  mismatch was accepted).
- `conflicting_status` was already caught at `14c996c`.

## Other evidence at `ec8197e`

- **Owner reproducer** `test_offline_boundaries.py`, unchanged: 2 failed, 5 passed (`owner_reproduction/`). This
  is the same as at `14c996c`; the two failures are the parent-defect assertions, as intended.
- **Stable comparison against `7b5218a`** (`stable_comparison/`): all four cases (healthy and retired, both lanes)
  are stable-equal in outcomes, candidate geometry, plan, permissions, tokens, attempts, venue calls and every v1
  record field. The only change is still `UNCLASSIFIED → PARTICIPATION_REFUSED` × 6 per case.
- **Focused** (`focused/`), pre-commit tree: **324 passed**. Files run:
  - the telemetry module;
  - `test_decision_accounting_stood_down` and `test_decision_accounting_held`;
  - `test_decision_trace_ownership`, `test_rr_floor_1_0`, `test_market_narrative_first`;
  - `test_campaign_draw_exact_binding` and `test_campaign_draw_temporal_authority`;
  - `test_brain_fingerprint_portability`, `test_pre_authorized_conditional_plan` and
    `test_latency1_final_quote_zone`.

## Activated restore-break controls (`mutants/`, at `ec8197e`, never committed)

Each mutant was applied in its own detached worktree at `ec8197e`, by exact-match replacement
(`apply_reader_mutant.py` for M7–M9; `apply_M1_M6.py` for M1–M6). The run covered the telemetry module plus
`test_decision_accounting_stood_down` and `test_decision_accounting_held`: 111 tests, all of which pass
unmutated. Every mutant is caught. The worktrees were then removed.

| Mutant | What it breaks | Caught |
|---|---|---|
| **M7_NO_SESSION_RELATION** | session no longer required or compared with the record | **4** (foreign/missing session × 2 lanes) |
| **M8_NO_CUTOFF_RELATION** | settled cutoff no longer required, validated or compared | **8** (missing/naive/unparseable/scan-clock cutoff × 2 lanes) |
| **M9_NO_ASSESSMENT_CONSISTENCY** | duplicated fields no longer checked against the assessment | **13** (reason, state, permission, control state, assessment removed, assessment rewritten alone × 2 lanes; non-permissive direction mismatch) |
| M1_DROP_LIFECYCLE_FIELDS | capture drops the Lifecycle fields | 28 failed + 32 errors (the section-6 attacks raise on the missing assessment) |
| M2_GENERIC_UNCLASSIFIED | refusal mapped back to `UNCLASSIFIED` | 42 |
| M3_STALE_OWNERSHIP | stale producer trace attributed | 4 |
| M4_BLANKET_RECONCILE_PASS | `refusal_problems` always `[]` | 41 |
| M5_BLANKET_UNKNOWN_REASON | every unknown reason mapped | 19 (including 11 existing decision-accounting tests) |
| M6_STALE_REFUSAL_HANDOFF | hand-off scan key ignored | 1 |

`conflicting_status` is not in M9's list because the earlier lifecycle-status check already caught it at
`14c996c`. M9 shows that the remaining 12 relations depend on the new consistency check.

## Full isolated suite at the final frozen source `ec8197e`

Results are in `full_suite/`. Run 2026-10-26T04:05:26Z → 04:54:44Z.

- **Setup.** Four fresh clones were checked out detached at `ec8197e`, each with a clean tree. One
  `--collect-only` of the supported `tests/` scope was split into four file-disjoint shards. Each shard ran in its
  own process under the credential-free, network-denied runner (`run.sh.txt`).
- **Collection.** 9859 collected, equal to 9859 unique JUnit testcases, across 361 files. The shards are disjoint
  and together equal the collection (`union.json`). That is 9826 at `14c996c` plus 33 new tests in the telemetry
  module.
- **Result.** **9276 passed, 583 skipped, 0 failures, 0 errors** (plus 34 subtests). Every shard exited with
  rc 0.
- **Skips.** The skipped set is identical to the accepted Phase 3 parent run: the same 583 test IDs, each with
  the same reason, 40 reasons in all (`skip_accounting.json`).

## Known limitations

- **No authentication.** The reader detects internal inconsistency. A coherently forged record (identity,
  assessment and refusal all rewritten together) is out of scope, as before.
- **Historical journals stay v1.** They are neither read nor rewritten here. A reclassified derived copy stays
  incomplete (`legacy_record_lacks_participation_refusal_evidence`).
- **Supplemental runtime.** Linux Python 3.12 in a credential-free, network-denied runner (`g5/run.sh`). This is
  not Mac or live certification.

## Index

See `INDEX.md` and `MANIFEST_SHA256.txt`.
