# Stage 5 four-gap offline completion: return package

Claims are labelled as follows:

- VERIFIED-RUN: executed, with the log in this package.
- VERIFIED-CODE: read from source.
- INFERRED or UNKNOWN.

Nothing here is an owner decision. Current Brain recognition and historical
archive certification stay UNPROVEN. Stage 4 owner acceptance is pending.
Production is disarmed and untouched.

## 1. Identity

- **Repository:** moneyboxtradingllc-hash/ICT_Discretionary_Expansion_Engine_Tiona.
- **Branch:** engineering/stage5-gap-closure-20261019. It is new, and every
  push to it was a fast-forward.
- **Final code commit:** c962a3db256eb76b7b66f9fc158f6f6f1bf01bbb, tree
  dd7cb762d772e2a2bffa38242f93982bf7ae105b. The package itself is committed
  in the next, docs-only commit on the same branch.
- **Parent:** audit/stage5-owner-corrections-20261018 =
  51eb3e1c209d205891a75a1181ad2f42dd65333d, tree 883d8c5e.
- **Frozen refs, unchanged** (VERIFIED-RUN, `identity/remote_refs.txt`):

  | Ref | Commit |
  |---|---|
  | review | a41c552 |
  | feature/latency-1-preauthorized-plans | cbfaddb |
  | main | a1614ae |
  | audit | 51eb3e1 |

- **Production source changed: none** (VERIFIED-RUN,
  `identity/production_src_changed.txt` is empty against 51eb3e1). Every
  changed path is under `src/recognition_validation/`, `tests/` or
  `docs/recognition_validation/`.
- **Ledger:** `tools/verify_engineering_ledger.py` reports LEDGER_VERIFIED.
  It checks the receipt chain, the 32 protected sources (equal to the pins),
  the 48-entry Brain closure, and the fingerprints brain:3d9878ad3ff57f1f and
  retr:0c241bdb8234d1ba, all unchanged.
- **Never done:** merge, deploy, arming, orders, credentials, or any model,
  provider, venue or account call. External requests made: 0.

| Mission | Parent (tree) | Exit commit(s) | Receipt |
|---|---|---|---|
| GAP_M1 required rule coverage | 51eb3e1 (883d8c5e) | 82937f0 | 7c33aa389048a188... |
| GAP_M2 fresh child per trajectory | 82937f0 (64734e29) | 7938e0a, 2c063d0 | 7e8a0357880ac22c... |
| GAP_M3 quote wake / trigger / final quote | 2c063d0 (c68250ed) | a68c89a | 8f2416056f8a2050... |
| GAP_M4 six-layer projection and scoring | a68c89a (2dd4838e) | c962a3d | 720e059ceb7ef1ba... |

The full receipts are in `missions/` and in
docs/recognition_validation/ENGINEERING_LEDGER.md. Each ledger section holds:

- the parent reproducer;
- the repair;
- the acceptance;
- the declared limits.

## 2. Per-mission evidence

Each frozen-worktree focused run passed in full (VERIFIED-RUN, `focused/`):

| Mission exit | Focused result |
|---|---|
| M1 | 181 passed |
| M2 | 191 passed |
| M3 | 214 passed |
| M4 | 248 passed |

Parent reproducers (VERIFIED-RUN, `reproducers/`):

- **M1:** a zero-denominator ratified rule disappears. The parent reports
  ELIGIBLE_FOR_OWNER_REVIEW. The fix keeps the rule as an UNPROVEN
  obligation, so coverage is INCOMPLETE.
- **M2:** an open provider circuit set before `driver.isolation` survives into
  the "new" trajectory. The fix runs every CLI trajectory in a `python -I`
  allowlisted child. The child is cold, its receipt is sealed, and the report
  binds CHILD_STATUS.
- **M3:** on the parent:
  - QUOTE_WAKE is TICK_ADAPTER_UNAVAILABLE;
  - there is no wake registry;
  - every scan refuses the authored plan with
    `conditional_plan_watch_unavailable`, at one Brain call per minute.

  Fixed: the real WakeRegistry is fed like the launcher feeds it, and
  `handle_pending_conditional_wake` runs first. In the refusing-venue lane
  the trigger reaches `validate_final_quote` (EXECUTE_AS_AUTHORIZED at
  29514.0) and one refused place_order. Twelve attacks, each with a healthy
  control, are covered.
- **M4:** two labels that differ only in campaign, delivery and tool truth
  score identically, and no layer cells exist. Fixed: a `layer_projection/v1`
  artifact per tick, read from the actual producers, with six cells per label.
  Each layer is mutated independently and detected. Mission 1 coverage is
  rerun on the layer outputs.

Activated mutants (VERIFIED-RUN, `mutants/MUTANT_RESULTS.txt`): 21 of 21
killed, each by its decisive assertion:

| Mission | Killed |
|---|---|
| M1 | 4 |
| M2 | 3 |
| M3 | 6 |
| M4 | 8 |

Both-lane integrated raw traces (VERIFIED-RUN, `traces/`): the HEALTHY world
was run through the CLI child for each of the four combinations below.
Each has its evidence directory, `result.json` and `report.md`, including the
per-layer table and cells:

| Venue lane | ECU | non-ECU |
|---|---|---|
| DISARMED | yes | yes |
| REFUSING_VENUE_DOUBLE | yes | yes |

`traces/EXPORT_SUMMARY.json` lists exits, statuses and layer tables.

## 3. Final full suite

VERIFIED-RUN (`final_suite/`). The suite ran on a fresh clone of the
remote branch at c962a3d (clean status), with the restricted runner
(`tools/run.sh.txt`):

- disarmed flags;
- network refused;
- no `.env`;
- isolated runtime roots.

**Result: 9659 test cases, 9076 passed, 583 skipped, 0 failed, 0 errors.**

- **Collection:** `pytest --collect-only` collected 9659 tests in 353 files.
- **Execution:** the suite ran from 07:45 to 09:09 UTC, as 12 file-disjoint
  shards. Each shard was its own process, three at a time
  (`final_suite/COMMANDS.txt`).
- **Union check** (`final_suite/shard_union.json`):
  - the shard files equal the collected files;
  - the shards are disjoint;
  - the merged JUnit has 9659 unique test cases, equal to the collection.
- **Merged JUnit:** `final_suite/full.junit.xml`, with its sha256. Each
  shard's log, JUnit, start and done files are in `final_suite/shards/`.
- **Why shards:** three single-process attempts were cut off by the
  environment, not by a test. Two were container restarts, at about 2% and
  5%. The third hit the 2-hour background limit at 68%, with 0 failures up to
  that point. All three are kept in `attempts/`. The first starts of shards
  00 to 02 were also cut off by a restart. Those shards were rerun whole, and
  their partial logs are kept as `shard_0N.interrupted.0`.

Collection comparison with the previous full run (fb20d96, single process)
(VERIFIED-RUN, `collection/collection_comparison.json`):

| | Previous | Final |
|---|---|---|
| Test cases | 9561 | 9659 |
| Failed | 1 | 0 |
| Skipped | 583 | 583 |

- **Added:** 98 cases, the new GAP_M1 to M4 tests plus the tests from
  Codex's audit commit 51eb3e1.
- **Removed:** 0.
- **Skip set:** identical.
- **One status change:**
  `test_replay2_session_walker::test_end_to_end_synthetic_walk_and_forced_safety`
  went from failure to passed. The test itself was changed in 51eb3e1
  (`git diff fb20d96 51eb3e1 -- tests/test_replay2_session_walker.py`),
  not by these missions.

## 4. Preserved failed and interrupted attempts

These are in `attempts/`:

- **M4 first freeze 9c5bf03** (local only, never pushed): its focused run had
  4 failures, 243 passed. Three were determinism failures (process-random
  identities in evidence artifacts) and one was the occurrence-reader theorem.
  It was superseded by c962a3d after a soft reset of the unpushed commit.
  `attempts/M4_9c5bf03_superseded/` has the patch, the logs, and the mutant
  results on that tree.
- **Interrupted:**
  - a focused run cut off by a container restart;
  - three full-suite attempts cut off by the environment (see section 3);
  - the first starts of shards 00 to 02.
- **Development iterations:** the failing M3 and M4 development runs that set
  the final expectations.

## 5. Findings for independent review

Protected sources are unchanged for all three findings.

1. **Import-time `.env` loading.** `load_dotenv()` runs at import in
   `src/data_feed/__init__.py`, `src/live_scan/scan_loop.py` and
   `src/main.py`. In a trajectory child it is a recorded no-op. Proposed fix:
   move the call to the launcher entrypoint.
2. **Wall-clock wake stamps.** `WakeRegistry._observed_at` (an inventoried
   T32 site) stamps an interaction raised without `observed_at` with the wall
   clock. It is telemetry only. Offline, the registry reads the decision
   clock. Proposed fix: callers pass `observed_at`.
3. **WATCHING in the REFUSAL cell.** The contract 07 REFUSAL cell does not
   know `expected_action` WATCHING: a published plan scores FALSE_POSITIVE.
   The COMPOSITION layer scores WATCHING correctly. The change is reserved to
   the owner (D11).

## 6. Limitations

- **M3:** one offered tick holds one historical quote, so a quote moving
  between trigger and capture is modelled at capture time. A route-raised
  interaction is spent by the next tick. The Brain fingerprint and Draw
  attacks are in-process instrumentation, not natural tapes.
- **M4:** restart, duplicate-cutoff, stale-Draw, prefix-eviction and
  false-reversal cases are mutations of copies of the real projections.
  MARKET_FACTS is verified only when the scorer is given the sealed corpus.
- **Data:** all corpora, labels and responders are CONSTRUCTED, FICTIONAL or
  MOCK engineering data. They are never owner truth.
- **Out of scope:** Mode C transport.

## 7. Owner-reserved decisions

D11 to D14 were added to docs/recognition_validation/OWNER_DECISIONS_APPENDIX.md:

- D11: WATCHING in the REFUSAL cell;
- D12: the `.env` fix;
- D13: the wall-clock fix;
- D14: the delivery vocabulary mapping.

D01 to D10 are unchanged.

## 8. Manifest

`MANIFEST_SHA256` (inside the archive) lists every file. The archive and its
sha256 sit next to this report in docs/recognition_validation/gap_closure_package/.
