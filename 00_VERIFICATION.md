# Source-isolated verification of frozen 6e30453 (verification only)

Frozen source: `6e30453b70022ee66240716b72683b798ad4f523`, tree
`09429e544f9514754462a1950db19e854c706228` (parent `ec8197ec5411fcbcae5b25ba5a4c395f82c122cc`).
No source, test, fingerprint, authorization, risk or policy change was made. No
model/provider/venue request, merge, deployment, rebind, arming or order. New
local routes remain disabled by default; activation and session authorization
remain reserved.

## 1. Owner correction received and verified

`OWNER_SHARED_CHECKOUT_VERIFICATION_CORRECTION_20261027.zip` sha256
`5acb9283fc13857a0ac6cfb03973e1477863d293b9276313a9ecf2a9077f0093`; all 10 members match
`MANIFEST_SHA256.txt`.

Agreed mechanism: my original launcher (`shard_suite.py run`) handed the SAME
clone to four concurrent workers. File-disjoint test lists and per-process
runtime roots did not isolate the closure-sensitivity tests (shard 1,
`test_authorization_source_closure.py`) temporarily rewriting fingerprinted
source while shard 0 authenticated it.

## 2. Race reproduced (`race/`)

The owner reproducer, unmodified, in a disposable `--no-hardlinks` clone at
`6e30453` via the owner `run_checks.py`: **2 passed**
(`race/race_probe.log`, `.junit.xml`, `.exit.json`). While a separate process
holds an appended `# closure probe` in `market_data/local_authority.py`, the real
capture refuses `session_authorization_invalid:AuthorizationRefused`
(`AUTHORIZATION_BRAIN_CONTRACT_CHANGED`) and the real trigger refuses
`conditional_plan_environment_lineage_changed`; healthy controls pass before and
after byte-exact restoration; the clone was clean afterwards. This reproduces
the mechanism; it does not prove the exact instruction-level scheduling of the
original run. The original two red cases stay red in the preserved record
(`original_run/`).

## 3. Corrected orchestration (`orchestration/isolated_suite.py`)

* `collect`: one clean clone, one `--collect-only` (receipt with pre/post state).
* `plan`: file-disjoint shards from that single collection.
* `run`: a thread pool of 4 workers; **every shard gets its own `git clone
  --no-hardlinks` checkout of the frozen SHA** (17 distinct physical checkouts, no
  shared or hardlinked source inode), its own HOME, TMPDIR, pytest `--basetemp`
  and runtime roots; sockets/DNS denied in-process plus a sinkhole proxy;
  execution switches false. Before and after each shard it records HEAD, tree,
  `git status --porcelain --untracked-files=all`, the link count of every tracked
  file and a digest over every tracked file's on-disk bytes; the receipt fails if
  anything differs. No test is skipped or deselected by the orchestrator; source-
  probe tests stay active.
* Disclosed launcher defect found during this run: the launched planner only
  took `tests/` paths, but the collection also contains one test outside `tests/`
  (`docs/recognition_validation/release_candidate/mac_evidence/test_mac_env_parent_repro.py::test_mac_condition`).
  It was therefore NOT run in my original suite either (my original report of
  "9,976 collected" counted node lines under `tests/`; the collection summary is
  9,977). It was run here as isolated shard 16 (`run-one`, same machinery), and
  the planner is fixed to take every collected path
  (`orchestration/as_launched_to_final.diff`; `isolated_suite.as_launched.py` is
  the exact launched version).

## 4. Result at the unchanged source

| | |
|---|---|
| Collection | 9,977 node ids in 365 files (`suite/collect.txt`; `collect_receipt.json` clean, frozen HEAD/tree) |
| Shards | 16 planned + 1 (`docs/` file) = 17, file-disjoint, files = collection |
| JUnit | 9,977 cases, 9,977 unique, **equal to the collected node ids** (`suite/union_source_isolated.json`) |
| Outcomes | **9,394 passed, 583 skipped, 0 failed, 0 errors** |
| Receipts (17) | all exit 0; HEAD = frozen SHA before and after; tree `09429e54…`; one tracked-bytes digest `e2b43717d5cdb1a229513aef53075719d9c518033e78004d85137528786932eb` for every checkout before AND after; clean status before and after; zero hardlinked tracked files; 17 distinct checkouts |

The two previously red cases
(`test_latency1_final_quote_zone.py::test_verified_conditional_final_quote_inside_inclusive_zone_reaches_mint[inside]`
and `[upper_edge]`) pass in shard 00 under source isolation, alongside
`test_authorization_source_closure.py` running concurrently in its own checkout.
Reconciliation with the original run: 9,391 passed + 2 failed + 583 skipped +
the 1 never-run `docs/` test = 9,977; now 9,394 passed + 583 skipped.

Skip accounting (`union_source_isolated.json → skip_reasons`, 40 reason kinds,
583 total): all are the repository's own environment skips — absent archived
snapshots/tapes/stores, git-ignored proposals, operator-local forensic
artifacts, and live-credential tests (`LIVE_ENV_REQUIRED`, credentials are not
present by design). None was added by this work.

## 5. Package

`suite/` — collect list + receipt, shard plan, 17 logs, 17 JUnit files, 17
per-worker receipts (HEAD, tree, status, tracked-bytes digest, link check, pre
and post), merged JUnit, union/skip accounting, console. `race/` — owner
reproducer run. `orchestration/` — corrected launcher (portable: needs only git,
Python and the repository's test dependencies), the as-launched version, the
diff, and the union script. `original_run/` — the original shared-checkout
shard 00 log/JUnit and its union, preserved red. `MANIFEST_SHA256.txt` indexes
every member (size + sha256).

Correction acknowledged: the previous evidence package was 68 non-directory ZIP
members plus four evidence-branch top-level files (the "72 files" figure I gave);
that ZIP had no internal manifest — its outer digest authenticated the bytes.
This package carries an internal indexed manifest.
