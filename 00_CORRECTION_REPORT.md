# Phase 1 custody correction (after the owner-side audit of 9045675)

**Source of the request.** This answers Codex's PHASE1_OWNER_AUDIT_9045675 (zip sha256 72f56ba0…; 21 manifest files
verified).

**Scope.** The change is bounded to the reported provenance defect plus one test-only path fix. It touches:

- no Q-BEARING, protected-high authority or CISD;
- no campaign/trading policy, economics, risk or execution permission;
- no storage, signature or authority layer.

**Run conditions.** Everything ran offline: no merge, deploy, arm, order, live provider or model call. Production stays
disarmed.

## 1. Identity

| Item | Value |
|---|---|
| Parent | `9045675fca32e731c62c60154abb1d54dd062a49` (the audited Phase 1 head) |
| Final | `357668ea8742cb4a7916580908be6fff5a0b82d7` on `review/narrative-first-20261024` (pushed, not merged; fast-forward from 9045675) |
| Changed | `src/ai_brain/market_narrative.py` (+12 lines in `_item`); `tests/test_market_narrative_first.py` (+8 cases, path fix); the seven measured fingerprint literals (four tests, three example fixtures); the ledger |
| Fingerprints | `brain:0720fde4c842045d` → **`brain:62fe5ecf46d75dc4`** (the bound closure source changed; still 49 sources). Retrieval is unchanged at `retr:0c241bdb8234d1ba` |
| Protected pins | All 32 unchanged |
| Ledger | Entry `NARRATIVE_FIRST_CUSTODY_20261025` (parent 9045675). `verify_engineering_ledger.py` returns LEDGER_VERIFIED: protected_verified 32, network_requests 0 |
| Authorization | A previous session authorization cannot be reused |

## 2. The fix

**Where.** In `market_narrative._item()`, when a current scope is supplied, after the existing contract, session,
cutoff, process and revision matches.

**Rule.** The read's `provenance.history_lineage.custody` must be a nonempty string equal to the eligible row's
`history_lineage.custody`. The row's custody is itself already proved by the existing stance hygiene.

| Read custody | Typed UNKNOWN reason |
|---|---|
| Missing or empty | `provenance_missing:history_lineage.custody` |
| Different from the row | `provenance_mismatch:history_lineage.custody` |

What does not change: the legitimate row, the guarded stance, `stance_history` and participation. There is no fallback
to the held narrative; an UNKNOWN item carries no story.

## 3. Proof

### 3a. Codex's reproducer (`test_owner_provenance.py`, unchanged)

| Source | Result |
|---|---|
| 9045675 | **2 failed** (foreign_custody, both lanes) / 4 passed |
| 357668e | **6 passed** |

Candidate refusal holds in every case.

### 3b. New permanent cases (`test_read_row_identity_at_next_consumer`, both lanes)

| Case | Expected result |
|---|---|
| healthy | AVAILABLE, story intact |
| foreign_contract | UNKNOWN `provenance_mismatch:contract_id` |
| foreign_custody | UNKNOWN `provenance_mismatch:history_lineage.custody` |
| missing_custody | UNKNOWN `provenance_missing:history_lineage.custody` |

Each case asserts `campaign_lifecycle_refused`. The file now has 23 cases, all passing.

### 3c. Activated control

| Source | Result |
|---|---|
| New check removed | foreign_custody and missing_custody fail in both lanes (4 failed); healthy and foreign_contract pass |
| Healthy twin | 23/23 |

### 3d. Windows path fix

The reader-scope test now compares `relative_to(src).as_posix()`. The six permitted readers are unchanged.

## 4. Complete isolated offline suite on 357668e

Runtime: Linux, Python 3.12.3 with 47/47 pins. The run is isolated, disarmed and network-denied, and each shard ran in
its own worktree.

| Item | Result |
|---|---|
| Result | Collected **9,724** unique `tests/` cases in 357 files; shard union = collection, file-disjoint. **9,141 passed, 583 skipped, 0 failed, 0 errors** (+34 subtests). Run 03:21:11–04:03:57Z |
| Reruns on 357668e | Codex's acceptance test 2 passed; Codex's reproducer 6 passed; Friday recorded replay (281 cutoffs) identical in both lanes, with 265/265 authored reads in the next input, 15/15 degraded calls honestly dated and 0 mismatches |
| Skips | 583, the same archive/credential classes as before; see `full_suite/skip_reasons.txt` |

## 5. Precision (as Codex noted)

- **The Friday replay** covers 281 deduplicated cutoffs, not all 397 original calls (the last call per cutoff). It
  uses partially capped fields and controlled quotes, so it proves only the stated transport comparisons. It does not
  prove full historical execution or current-Brain narrative/recognition quality.
- **Price-print presence** in the narrative review is diagnostic, not semantic certification.
- **Still open, unchanged:** Q-BEARING, the four C2 regressions on f6e4013, and CISD O1.
