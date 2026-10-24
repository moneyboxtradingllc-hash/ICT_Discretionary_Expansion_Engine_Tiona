# Phase 1 completion: the Brain's authored market read is preserved and transported

**Scope.** This implements NARRATIVE_FIRST_CONTRACT_20261024 (sha256 43a55c8c…), as locked by the PHASE 1 SCOPE LOCK
email.

**What was not done.** There is:

- no Q-BEARING work, no CISD authority and no campaign-authority change;
- nothing inherited from f6e4013;
- no repinning of f6e4013 and no change to the C2 expectations.

f6e4013, 0df06ea and all of their evidence are untouched; the four C2 authority regressions remain a separate open
item.

**Run conditions.** Everything ran offline:

- no model, provider or venue call, and no credentials;
- no merge, deploy, arm or order;
- production stays disarmed.

## 1. Identity

| Item | Value |
|---|---|
| Parent | `ffe00aef3db7fb2339780ed0fa9016149923c96e` (stable RC). The branch was created from it before any edit |
| Final | `9045675fca32e731c62c60154abb1d54dd062a49`, tree `0e398e269b7bc11af6376318fd8d79f47a537423`, branch **`review/narrative-first-20261024`** (pushed, not merged) |
| Commits | `5390bf2` preserve read beside permission; `d9599fb` keep the pre-hold digest out of the transported item (replay determinism); `9045675` bind market_narrative.py into the Brain contract closure. The earlier pushed `a0a5c40` was amended into `9045675` on this review-only branch |
| Changed files | 17 files, +752/−14: `src/ai_brain/{market_narrative.py (new), narrative_brain.py, stance_memory.py, brain_input.py, brain_prompt.py, production_model.py}`, three `recognition_validation/examples/*.json` fingerprint fields, `tools/narrative_read_report.py` (new), `tests/test_market_narrative_first.py` (new), five tests with fingerprint/closure expectations, and the ledger |
| Fingerprints | Parent: `brain:3d9878ad3ff57f1f`, closure 48. Final: **`brain:0720fde4c842045d`**, closure **49** (adds `ai_brain/market_narrative.py`, which defines Brain-visible text). Retrieval is unchanged at `retr:0c241bdb8234d1ba` |
| Protected pins | All 32 byte-identical; protected digest unchanged |
| Ledger | Entries `NARRATIVE_FIRST_20261024` (parent ffe00ae) and `NARRATIVE_FIRST_BIND_20261024` (parent d9599fb). `tools/verify_engineering_ledger.py` returns LEDGER_VERIFIED: protected_verified 32, fingerprints_checked, network_requests 0 |
| Repins | Seven literal expectations of the measured Brain fingerprint (four tests, three example fixtures), the closure count (48→49) and the governance membership list are updated to the measured values. Each is declared in the ledger; no historical receipt is rewritten. A previous session authorization cannot be reused |

## 2. What changed (additive; participation untouched)

1. **Capture** (`narrative_brain.run_narrative_brain` → `market_narrative.capture`).
   - When it happens: after validation and any accepted repair, before `output_direction_hold`.
   - What it captures: a deep copy of the validated primary judgment, as `brain_block.authored_market_read`
     (`authored_market_read/v1`, `authority: OBSERVATIONAL_ONLY`).
   - Fields: story, direction, phase, reasoning, delivery, liquidity, protected high/low interpretation, thesis
     health and `authored_action`.
   - Provenance:
     - source `validated_primary_pre_authority_hold`;
     - contract, symbol, session, settled cutoff, history revision, process session and lineage (custody, revision);
     - served model, Brain and retrieval fingerprints;
     - repair flags and the pre-hold output digest.
   - Degraded, fallback or circuit-open cognition is `UNKNOWN` with a reason; a read is never built from the held
     template. Text over 1,200 characters is truncated with a declared length and digest.
2. **Permission view unchanged.**
   - `brain_block.output` is still the guarded output.
   - Unchanged: campaign direction and establishment, transfer proof, Draw, Lifecycle, candidate, conditional
     trigger, final quote, and the ECU direction/opportunity projection.
   - No authority module reads the new view; a test asserts the only readers are the five Brain-assembly files plus
     `production_model.py`, which only names the source.
3. **Existing custody** (`StanceMemory.record`).
   - The read is stored on the same proved row, through a new optional parameter. Recorders with the old signature
     keep their exact call.
   - All existing derivations and fields are unchanged. `stance_history` rows are stripped of the new field, so that
     view is byte-for-byte the old one.
4. **Next input** (`brain_input.market_narrative_history`).
   - Contents: schema, authority, scope note, `last`, up to 4 `prior` items, an unknown count and withheld-row counts.
   - Built only from rows that the existing contract/session/cutoff/lineage hygiene already accepts.
   - An item whose read provenance does not match its row (contract, session, cutoff, process, revision), or whose
     authority label is not OBSERVATIONAL_ONLY, becomes `UNKNOWN`. Legacy rows are `UNKNOWN`.
   - The prompt adds one bullet: this is your own prior descriptive read, not an incumbent, transfer, falsifier or
     approval, and never a sign that participation was allowed.
5. **Report** (`tools/narrative_read_report.py`). For every persisted call it shows three separate columns:
   - AUTHORED: from `authored_market_read`, or for legacy records the original `llm_raw_response`, labelled
     LEGACY_RAW_RESPONSE;
   - PERMITTED: from `parsed_output`;
   - REFUSAL: from `narrative_authority_guard`.

   It reports `llm_model` and `provider_latency_seconds`.

## 3. Proof on the actual path

### 3a. Codex's acceptance test (unchanged file)

| Source | Result |
|---|---|
| Parent | **2 failed**, both lanes, at "Actual next Brain receives the held template but lacks the separate authored market read" |
| Final | **2 passed** |

In both lanes:

- the healthy bullish candidate is produced;
- C2 is `developing_transfer` / `stand_down` / `campaign_lifecycle_refused`, unchanged.

The next transported input, after (ECU lane, `acceptance/after/NARRATIVE_CONTEXT_CURRENT_ecu.json`):

- **Guarded:** `narrative_continuity.prior_thesis.market_story` = "Directional control is developing but no new
  dominant campaign is confirmed; stand down."
- **Authored:** `market_narrative_history.last` = bearish / OBSERVATIONAL_ONLY / "AUDIT CONTROL: price rejected
  buy-side liquidity at 29500 and broke the protected local low at 29457 …".
- Its provenance: served model gpt-6-luna, contract CON.F.US.MNQ.Z26, settled cutoff 03:06Z, revision 0, custody
  lineage, and Brain and retrieval fingerprints.

Before, `market_narrative_history` was `null`.

### 3b. Permanent tests (`tests/test_market_narrative_first.py`): 15 passing

The cases are:

1. Envelope, transport and report consumption, in both lanes. The report reads the exact persisted records.
2. A blocked `propose_entry` shown beside the exact hold, with the candidate refused.
3. Observational invariance: a forged in-place read (bearish, "EXECUTION" authority, propose_entry) leaves the
   healthy candidate's geometry identical, and the refusal is unchanged.
4. A poisoned label or a copied foreign-contract read becomes `UNKNOWN`, while continuity, Lifecycle and candidate
   results stay identical.
5. Withheld rows (future-dated, wrong contract, superseded revision, legacy) never supply the narrative.
6. Degraded, deterministic, fallback and circuit-open cognition all come out as `UNKNOWN`.
7. Capture is by value, and truncation is declared.
8. Only Brain-assembly modules reference the view.

### 3c. Activated controls

Each mutant fails, and the healthy twin passes 15/15.

| Mutant | Failing tests |
|---|---|
| Overwrite the read with the held template (capture after hold) | 8 |
| Drop it before the next input | 10 |
| Relabel it as `EXECUTION_AUTHORITY` | 8 |
| Mix withheld/foreign rows into the history | 6 |
| Remove the provenance-match check | 2 |

### 3d. Friday recorded replay (`replay/`)

**Setup.**

- A real ProductionScanCycle runs minute by minute over the archived PROD-20261023-C1 1m tape (13:18–17:58Z), in
  both lanes.
- Each of the 281 recorded cutoffs is served its recorded original response. The fields are recovered from
  `llm_raw_response`; truncated fields stay at stand-down defaults, matching every recorded primary action.
- The 15 `llm_failed_fallback` calls are served as provider failures.
- No new judgment is authored and no model is called.

**Result, identical in both lanes.**

| Measure | Count |
|---|---|
| Reads captured | 266 |
| Degraded calls, UNKNOWN | 15 |
| Holds rewrote the guarded story in the replay | 181 |
| Next inputs where the previous authored read arrived as `last` (OBSERVATIONAL_ONLY) | **265/265** |
| Inputs after a degraded call | 15/15 |
| Mismatches | 0 |

A degraded call records no cognition. The input after it shows the last real read, honestly dated at its own earlier
cutoff.

Example at 12:30 ET (16:30Z input):

- authored `last` = bearish, recorded 16:29: "Price rallied into buy-side liquidity around 29325.75, then rejected the
  highs and delivered lower; the higher-timeframe delivery read is manipulation-to-distribution …";
- guarded prior_thesis = the generic stand-down sentence.

## 4. Complete offline suite on the final frozen SHA

Runtime: Linux, Python 3.12.3 with 47/47 pins. The run is isolated, disarmed and network-denied, and each shard ran in
its own worktree of `9045675`.

| Item | Result |
|---|---|
| Result | Collected **9,716** unique `tests/` cases in 357 files; shard union = collection, file-disjoint. **9,133 passed, 583 skipped, 0 failed, 0 errors** (+34 subtests). Run 21:55:37–22:27:09Z. Codex's acceptance test and all five controls rerun on the frozen source with identical results |
| Skips | Same archive/credential classes as the baseline; see `full_suite/skip_reasons.txt` |

Fixed during verification (all ordinary failures, repaired and documented):

- the old-signature stance recorder that degraded the Brain call;
- replay non-determinism from the digest in the transported item;
- the closure governance list and count;
- a cross-shard race on on-disk sealing probes (harness only).

## 5. Friday narrative-quality review

See `FRIDAY_NARRATIVE_REVIEW.md`. In summary:

- **Facts.** 2,724 of 2,783 cited levels were settled prints at the cutoff, and no contradiction was established.
- **The bearish read existed.** The Brain authored bearish delivery reads from 12:22 ET onward, but every one was held
  and transported as the generic sentence.
- **Interpretive limits.**
  - Every lower-timeframe sweep-and-reclaim is treated as a fresh opposing origin.
  - System vocabulary partly replaces market description.
  - Session extremes and time of day get little context.
- **No entry was suppressed** (382/382 stood down).

## 6. Remaining limits

- **Recognition is not proven.** Preserving the read proves transport, not reasoning quality or what a newly prompted
  model would decide. Current-Brain recognition, setups and fills are UNPROVEN.
- **Truncation in the extract.** The Friday extract truncated some original protected and thesis-health fields;
  replay and review use the recovered fields only.
- **Pre-existing persistence issue, not fixed (out of scope).** Persisted Brain-call files are named by wall-clock
  second, so two calls in the same second overwrite each other.
- **Fingerprint.** It changed, so previous session authorization cannot be reused.
- **Open from earlier, unchanged:** Q-BEARING and the four C2 regressions on f6e4013, and CISD O1.
