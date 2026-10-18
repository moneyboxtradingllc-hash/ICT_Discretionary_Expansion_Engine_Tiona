# Stage 5: final engineering completion return (contract 12)

Claims are labelled VERIFIED-RUN (executed, with the log in this package),
VERIFIED-CODE (read from source), INFERRED or UNKNOWN. Nothing below is an
owner decision.

## 1. Identity and decision

- **Status: ENGINEERING_COMPLETE / READY_FOR_OWNER_REVIEW.** Current Brain recognition is UNPROVEN.
- Repository: moneyboxtradingllc-hash/ICT_Discretionary_Expansion_Engine_Tiona,
  branch review/reversal-foundation-wip-20261006.
- Final SHA fb20d96a5b4675eb2998e1e269f2b977e23cfa7b, tree
  b81d0fe680e426a040abbf4cb2e92bb46ac16ed4.
  - The fresh clone from the remote is clean.
  - The remote head equals the final SHA, reached by fast-forwards only
    (`identity/remote_refs.txt`).
- Lineage from baseline f5934c0 (tree 96316d4b). Each child is bound by a
  ledger entry:

  | Mission | Commit |
  |---|---|
  | M00 | 6e6286c |
  | M01 | 6db3b47, 3b0f8da, 63d503f |
  | M02 | f3d8a97 |
  | M03 | e046cbf |
  | M04 | cecdfe7 |
  | M05 | 5032345 |
  | M06 | 90d8b56 |
  | M07 | 63e194f |
  | M07R | fb20d96 |

- `tools/verify_engineering_ledger.py` reports LEDGER_VERIFIED
  (VERIFIED-RUN, `identity/ledger_verify_final.json`). It checks:
  - the receipt chain;
  - parent trees;
  - the 32 protected sources, which equal the baseline pins;
  - the 48-entry Brain closure, unchanged;
  - canonical fingerprints brain:3d9878ad3ff57f1f and retr:0c241bdb8234d1ba,
    unchanged;
  - the scope of every commit.
- Ledger file sha256: 57fa07c44aefe7ab0cf8917c77d13ab0c1376ebce6a14392aa8a41183b13a30d.
- The contract's `verify_source_baseline.py` on f5934c0 reports
  VERIFIED_EXACT_BASELINE (`identity/baseline_verify_f5934c0.json`).
- Production source changed: **none** (VERIFIED-RUN, `git diff f5934c0`).
  What was added:
  - the new offline package `src/recognition_validation/`;
  - new tests;
  - three new Stage 4 test modules;
  - one scoped literal update to an existing test (M07R, §4);
  - `tools/verify_engineering_ledger.py`;
  - docs under `docs/recognition_validation/`.
- The production branch feature/latency-1-preauthorized-plans (cbfaddb) and
  main (a1614ae) are untouched.
- None of the following happened: merge, deploy, arming, orders, or any
  model, provider, venue or account call. **External requests made: 0.**
- The only armed-looking paths are pure offline synthetic proofs, using the
  refusing fake venue and fake provider transports.
- Separate statuses:

  | Item | Status |
  |---|---|
  | Stage 4 internal | S4-01..S4-10 PASS-BOUNDED (limits stated per row); S4-11 source VERIFIED, archive certification OWNER-RESERVED (D04); S4-12 CLOSED (see §2) |
  | Stage 4 independent owner acceptance | PENDING |
  | Stage 5 engineering | ENGINEERING_COMPLETE (one disclosed pre-existing environmental test failure, not this program's) |
  | Current cognition | UNPROVEN |
  | Historical archive certification | UNPROVEN |
  | Controlled observation | NOT AUTHORIZED |
  | Production | NOT AUTHORIZED |

## 2. Stage 4 dependency disposition

See `repo docs/recognition_validation/STAGE4_DEPENDENCY_MATRIX.md` at the
final SHA. It covers S4-01 to S4-12 and T01 to T22, mapped to verified
nodes.

- New in this program, each with healthy and activated negative controls:
  - S4-05: the distinct-anchor witness
    (`tests/test_po3_distinct_anchor_premise.py`), with identity-collapse
    and retirement-collapse mutants.
  - S4-09: bound-scope duplicate cutoff and restatement in both lanes, JSON
    copy and new-process replay
    (`tests/test_bound_scope_history_custody.py`), with revision-skip and
    serialized-view-trust mutants.
  - S4-10: the ten new-order routes indexed and pinned
    (`tests/test_order_route_inventory.py`).
- S4-11 (archive certification) is owner-reserved (D04).
- The closed original N1, HO1 and composition evidence is reused unchanged.

## 3. Stage 5 deliverables

See `repo docs/recognition_validation/STAGE5_DELIVERABLES.md` for paths,
API, CLI, schemas and tests, and ENGINEERING_LEDGER.md for each mission's
receipts. The schemas are the contract's v1 set.

Samples (`samples/`) ran on 63e194f, whose `src/` is byte-identical to
fb20d96 (`identity/delta_63e194f_to_fb20d96.txt`). They use CONSTRUCTED
inputs only. `samples/run_samples.sh` and `samples/inputs/make_inputs.py`
regenerate them. Results:

- `validate` 0 and `plan` 0.
- Mode B: B1, B2 and B_ecu all exit 0. `compare B1 B2` is identical:
  225 events and 75 calls, with equal semantic hashes and different raw
  hashes.
- Mode A: A1 replays records harvested from B1. Its semantic event hash is
  identical to B1's. `compare B1 A1` exits 4 by design, because call
  provenance differs (HISTORICAL vs MOCK, plus the disclosed rebinding
  notes).
- `report` exits 3 when there are no annotations. The results are
  engineering COMPLETE, READY_FOR_OWNER_REVIEW and recognition UNPROVEN,
  with 0 external requests.
- Mode C dry run exits 0. It plans 0 requests, has blockers
  CURRENT_MODEL_CALLS_DISABLED and PRICING_OR_OUTPUT_CAP_MISSING, and
  reports its formulas. A live Mode C run exits 2
  (CURRENT_MODEL_CALLS_DISABLED). The build contains no external
  transport.
- Session inventory: one CONSTRUCTED session (DAW-CONSTRUCTED-20260819,
  MNQ Z26).
  - Warm-up runs to 15:30Z; scoring runs from 15:30Z to the end of the
    tape.
  - It has no quotes (a constructed quote is placed at the close), no
    news, an EMPTY memory policy and no historical Brain records.
  - Repository fixtures are inventoried by
    `corpus.repository_fixture_inventory`.
  - No operator or real session was used (D01/D02).
- Mode C authority and budget proofs:
  - `test_recognition_model_authority.py`, 28 passed.
  - Refusal before the fake transport, in 17 cases.
  - Reservation, settle and orphan ledger accounting.
  - Retry, repair, request and cost caps.
  - Whole-trajectory fake provider in both lanes.
- Observations, with production unchanged:
  - Production's model request sets no output-token cap, so external mode
    also needs a separately digested evaluation profile.
  - narrative_brain stamps provider calls with the wall clock, and that
    stamp re-enters the next Brain input. Inside the seam the replay reads
    the decision clock instead.
  - 162 wall-clock sites are inventoried (T32).

## 4. Tests and hostile evidence

Final suite on fb20d96 (VERIFIED-RUN, fresh clone):

- Result: 8977 passed, 583 skipped, 1 failed, 34 subtests passed in 6684s (1:51:24); 9561 unique node ids. The single failure is test_replay2_session_walker::test_end_to_end_synthetic_walk_and_forced_safety, pre-existing and environmental (identical on baseline f5934c0, see failure_analysis). Versus 63e194f: the regression is fixed and there are no new failures.
- Started 2026-10-18T03:36:58Z, finished 2026-10-18T05:28:26Z.
- Files: `final_suite/full_suite.log`, `final_suite/full.junit.xml`
  (per-node summary in `final_suite/junit_summary.json`) and
  `final_suite/full_suite_command.txt`.
- Environment: `final_suite/environment.txt` (Python 3.12, pytest 9.1.1,
  pip freeze).
- The runner is `run.sh.txt`:
  - `env -i` allowlist, no `.env`, TZ=UTC;
  - EXECUTION_ENABLED=false, ALLOW_PAPER_ORDERS=false, AI_BRAIN_LLM=false,
    TWO_BRAIN_MODE=off;
  - isolated runtime roots;
  - proxy set to 127.0.0.1:9.

Preserved earlier attempts:

- `attempts/63e194f/`: the full suite on the previous candidate.
  - Result: 8976 passed, 583 skipped, 2 failed, 34 subtests passed
    (1h50m).
  - The node-level JUnit has 9561 unique ids.
  - Failure analysis is in `failure_analysis/`:
    - **Regression (repaired in M07R).** The occurrence-field
      source-content theorem names only three production files. The M03
      driver names the field once, to record it. The scoped literal update
      admits that one file, pins the read to that recording line, and pins
      that no production module imports the harness. Activated control: a
      planted production import fails on that assertion.
    - **Environmental, not this program (left unchanged).**
      `test_replay2_session_walker::test_end_to_end_synthetic_walk_and_forced_safety`
      fails identically on baseline f5934c0 under the mandated
      EXECUTION_ENABLED=false. It passes on both baseline and final with
      that variable unset. Its assertion assumes the variable is absent.
      `PROPOSED_walker_env_restore.patch` is offered and NOT applied; it
      passes in both environments.
- `attempts/interrupted/`: the first 63e194f attempt, stopped at 6% because
  of CPU contention. It is preserved as is.

Skips and collection gaps:

- 583 skipped. Reasons are grouped in `junit_summary.json`: archived
  snapshots, tapes and canonical stores absent; git-ignored proposals;
  operator forensic artifacts; live credentials not shipped.
- Explicit collection inventory (`collection/ignored_module_collection.json`,
  VERIFIED-RUN):
  - 28 operator-state modules (731 nodes) are not collected by
    `tests/conftest.py`, because no archived operator corpus is present.
    They were collected explicitly and not run.
  - 4 module names in the conftest lists do not exist in the repository.
  - The NT lane is configured, and its 6 modules run in the suite.
- No skip is counted as PASS.

Other evidence:

- Activated mutants (`mutants/`):
  - Round 1: 12 mutants over T23-T32. 11 were killed on their targeted
    assertion; 1 survived as an EQUIVALENT mutant (unknown-usage charge,
    which is dead code).
  - Round 2: that mutant was replaced by MUT-T26-UNKNOWN-USAGE-UNDERCHARGED,
    which was killed.
  - Plus the M07R importer mutant.
  - Each log names the decisive E-line.
- Static checks: `compileall` OK; `git diff --check` from f5934c0 OK (56
  files, +12876, -0).
- Stage 4/5 focused runs: before freeze, the twelve new modules gave
  154 passed. The one ledger-scope failure, from the uncommitted M06
  driver, was correct, and the check was re-run green after commit.
- Both lanes: actual-loop paths (current path, replay, model authority) run
  ECU true and false. Mission, token, attempt and venue counts are all
  zero; the venue refuses every write.

## 5. Owner-reserved decisions

See `repo docs/recognition_validation/OWNER_DECISIONS_APPENDIX.md`. It
covers D01-D10, the safe defaults, what stays UNPROVEN, the executable
future commands and the ratification receipt mapping. No annotation is
fabricated and nothing is attributed to Maurice. Still required for
current recognition:

- Stage 4 owner acceptance;
- a ratified corpus;
- sealed owner or delegate annotations;
- a ratified scoring plan with N and thresholds;
- a sealed model, pricing and cost authorization plus a real transport;
- an operator export.

**No trade-readiness statement is made.**

## 5b. What this package omits, and how to regenerate it

Only regenerable bulk is left out, listed by SHA-256:

- the per-call artifact trees of the four sample runs
  (`samples/out/*/artifacts_SHA256_not_included.txt`, about 28 MB of
  Brain input/prompt bytes);
- the harvested Mode A records
  (`samples/out/historical_records_SHA256_not_included.txt`).

`samples/run_samples.sh` regenerates both. Raw traces carry process-random
ids by design, so a regenerated run matches the included traces under
semantic-v1, not byte for byte. Everything else is included in full: both
full-suite JUnit files and logs, the sample traces and the CONSTRUCTED
corpus.

## 6. Reproduction

1. Extract into a clean directory and run `sha256sum -c MANIFEST_SHA256`.
2. `git clone` the repository and `git checkout fb20d96a5b4675eb2998e1e269f2b977e23cfa7b`.
3. Run `python3 tools/verify_engineering_ledger.py --repo .`.
4. Run the suite command in `final_suite/full_suite_command.txt` with
   no operator environment.
5. Run `samples/run_samples.sh` (edit the two paths at its top).

The package contains no credentials, account identifiers, operator
archives or runtime state.
