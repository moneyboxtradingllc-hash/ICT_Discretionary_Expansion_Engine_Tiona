# PROD-20260806 -- Memory, Retrieval and Learning Audit

Read-only evidence audit of what the August 6 production session actually stored,
learned, indexed and made retrievable. No memory was written, no vector store
created, no order endpoint touched.

```
OPENAI VECTOR STORE : OPENAI_VECTOR_STORE_UNUSED - BOT_MEMORY_IS_LOCAL
LOCAL BOT MEMORY    : LOCAL JSONL + IN-PROCESS COSINE, RETRIEVAL CORPUS EMPTY
PROD-20260806       : ARCHIVED IN FULL, ALMOST NOTHING LEARNED
```

## The short answer

The bot **archived** 172 scans and **learned** four small facts. Its analog
retrieval corpus is still empty, so tomorrow cannot retrieve a single thing from
today.

## 1. Is the vector search OpenAI-hosted or local? Why does the dashboard show 0 bytes?

**Both questions have the same answer: the bot never used OpenAI vector stores.**

A read-only listing against the configured project returned **0 stores, 0 bytes**.
That is not a symptom -- it is the expected state. The repository contains **zero
references** to `vector_stores`, `file_search`, `vector_store_ids`,
`file_batches` or `embeddings.create`. The dashboard reads 0 bytes because
nothing has ever been uploaded, and nothing ever will be by this code.

The bot's retrieval is entirely local and does **not** use the OpenAI Embeddings
API:

| | |
|---|---|
| Embedding | hand-rolled, **47 dimensions** |
| Composition | one-hot over 10 regimes + 6 volatility states + 7 sessions + 8 phases |
| Metric | cosine (`ai_retrieval/embedding.py`) |
| Backend | append-only JSONL, `data/ai_retrieval/memory_store.jsonl` |
| Index | none -- linear scan |
| OpenAI calls | Chat Completions only |

## 2. Memory system inventory

| System | Taxonomy | Written 8/6 | Records after | Read tomorrow |
|---|---|---|---|---|
| vector retrieval | VECTOR_RETRIEVAL_MEMORY | **no** | **0** | no (disabled + empty) |
| HTF memory | HTF_MEMORY | **yes** | 3 days | **yes** |
| thesis lifecycle | THESIS_LIFECYCLE_MEMORY | **no** | 0 for 8/6 | yes (stale) |
| stance memory | THESIS_LIFECYCLE_MEMORY | **yes** | 30 (1 from 8/6) | **yes** |
| brain artifacts | BRAIN_ARTIFACT_STORE / RAW_SESSION_LOG | yes | 172 | **no** |
| capital history | ADAPTIVE_CONTEXT_STATE | **yes** | 7 anchors | **yes** |
| performance tables (MNQ) | ADAPTIVE_CONTEXT_STATE | no | **0 (empty)** | yes |
| slippage state | SLIPPAGE_STATE | no | 0 | yes |
| candle cache | TEMPORARY_CACHE | yes | 835 | yes |
| global lessons | DEAD_OR_UNREACHABLE_STORE / TEST_ARTIFACT | no (tests) | 266 | **no** |
| OpenAI vector stores | DEAD_OR_UNREACHABLE_STORE | no | 0 | no |

Full machine-readable detail, with per-system proof, lives in the ignored archive
at `analysis/memory_inventory.json` and `analysis/memory_records_20260806.csv`.

## 3. What the bot actually learned

### WHAT THE BOT OBSERVED
172 production scans across three code phases; 66 under the final semantics.
211 session 1-minute candles. Two malformed Brain responses and three schema
degradations, all before the mid-session repairs.

### WHAT THE BOT ARCHIVED
738 files, SHA-256 verified: every scan input, every Brain artifact, raw
responses, launcher and monitor logs, git provenance, explicit execution
zero-state. Audit material only.

### WHAT THE BOT STORED AS DURABLE MEMORY
Exactly four things:

1. **One HTF daily bar** -- `data/htf_memory/MNQ.json` gained
   `2026-08-06: O 29357.75 / H 29686.25 / L 29241.0 / C 29533.0`, beside 08-04
   and 08-05.
2. **One stance entry** -- `stance_memory.json`, timestamped 18:00Z:
   `conflicted / accumulation / confidence 58 / stand_down`. One entry in a
   30-slot ring buffer, from 172 scans.
3. **One equity anchor** -- `capital_history.json` gained
   `20260806: 50042.96`.
4. **835 rolling candles** -- a market-data cache, trimmed over time.

### WHAT TOMORROW'S SESSION CAN RETRIEVE
The August 6 daily OHLC bar, the single closing stance, the equity anchor, and
whatever candles survive the rolling trim. **Nothing else.**

### WHAT ADAPTIVE STATE CHANGED
Only `capital_history`. `data/performance/MNQ/` is **empty** -- no brain-accuracy,
thesis-quality or suppression table exists for MNQ at all.

### WHAT DID NOT CHANGE
The retrieval corpus (0 records, last modified 2026-06-16, before the session).
Slippage state (**0/20 observations, 0/10 round trips** -- unchanged, as it must
be after a day with no fills). Performance tables. No thesis journal for 8/6.

### WHAT WAS REJECTED FROM MEMORY
Nothing was rejected, because **nothing was offered**. There is no code path from
a scan to `vector_store.add_record` in the production loop -- the analog corpus
is written by a separate memory-writer that this session never invoked. The
identity filters (MNQ-only, instrument required) were therefore never exercised
on live data.

### WHAT THE BOT STILL DOES NOT KNOW
That it stood down 172 times. Which conditions it declined. That two Brain
responses were malformed. That the semantic contract changed mid-session. That
Terra is now the Brain. None of it is retrievable.

## 4. Archive versus learning

| Artifact | Archived | Auto-retrieved | Vector-indexed | Adaptive input | Tomorrow sees it |
|---|---|---|---|---|---|
| 172 scan inputs | yes | no | **no** | no | **no** |
| 172 Brain artifacts | yes | no | **no** | no | **no** |
| 211 session candles | yes | yes (cache) | no | via HTF | **yes, as OHLC** |
| malformed / degraded artifacts | yes | no | no | no | **no** |
| phase + commit evidence | yes | no | no | no | no |
| execution zero-state | yes | no | no | no | no |

**The archive is not memory.** It is read only when an operator runs a replay.

## 5. Findings that need a decision

**The retrieval corpus has never been written.** `AI_RETRIEVAL_ENABLED` is unset
*and* the store is 0 bytes. Both would have to change for analog retrieval to do
anything. Simulated Aug-7 queries across six representative contexts (bullish
expansion, bearish delivery, conflicted rotation, neutral lunch, exhaustion,
volatility expansion) all returned `corpus_size=0, returned=0`.

**Test pollution of runtime stores.** `global_lessons.jsonl` grew 240 -> 266
during the audit's own test runs, from
`tests/test_phase_deploy1_multi_instance.py:198` writing the literal
`"news raises whipsaw risk"` into the real `data/global_memory/` path with no
tmp isolation. Its module has zero production importers, so nothing reads it --
but a test writing to a live memory path is a latent hazard.

**`active_thesis.json` holds a June 15 QQQ thesis**, re-saved at 15:54 ET by the
same test runs. The August 6 session produced **no** thesis record
(`20260806_theses.jsonl` does not exist) and no scan input carried a
`thesis_lifecycle` block. So the live thesis store is both stale and
retired-instrument labelled.

**Peak equity is cross-venue.** `capital_history.peak_equity = 99990.53` predates
the TopstepX account (`last_equity = 50042.96`). Drawdown pressure is therefore
computed against a peak from a different account. Not touched during this audit.

## 6. QQQ / test contamination status

The 16 QQQ-labelled brain artifacts written today are test-suite output
(`model=None`, `source=deterministic`/`contaminated_input`, empty input). They
are excluded from the session census and cannot enter retrieval: the corpus is
empty, and `doctrine/instrument_identity.retrieval_eligible` rejects both
`retired_instrument:qqq` and `missing_instrument_identity`.

## 7. Lost learning opportunities

None of the following were retained. **This audit did not add any of them.**

| Opportunity | Risk classification |
|---|---|
| Session regime summary (lunch rotation, toxic volatility) | SAFE_DESCRIPTIVE_MEMORY |
| Direction/action distribution per phase | SAFE_DESCRIPTIVE_MEMORY |
| The conflicted -> bearish transition after 11:10 | SAFE_DESCRIPTIVE_MEMORY |
| Prompt/schema defects discovered mid-session | SAFE_DESCRIPTIVE_MEMORY |
| Conditions under which the bot declined to trade | REQUIRES_OUTCOME_VALIDATION |
| "Standing down here was correct" | COULD_CREATE_CONFIRMATION_BIAS |
| Avoided-loss or hypothetical-P&L claims | MUST_NOT_BE_STORED_AS_TRADING_TRUTH |

A no-trade day can honestly support descriptive memory. It cannot support
outcome memory: with zero fills there is no result to learn from, and storing
"the stand-down was right" would teach the bot to prefer inaction using evidence
that never tested the alternative.

## 8. Audit integrity

```
memory records inserted   : 0
vector stores created     : 0
files uploaded to OpenAI   : 0
production config changed  : none
order endpoints called     : none
network calls              : one read-only OpenAI vector-store listing
```

---

# APPENDIX A -- Remediation (2026-08-06, after the audit)

The audit conclusions above are unchanged. This appendix records how the three
persistence-integrity defects it proved were repaired. **No retrospective August 6
memory was added, and no memory-authoring pipeline was built.**

## A.1 Test pollution of live runtime stores

**Root cause, two parts.** `GLOBAL_MEMORY_DIR` was a module constant bound at
import time, so no env redirect could reach it. And several suites set a runtime
root to their own tmp directory, then **`os.environ.pop()`** it in teardown
instead of restoring the previous value -- deleting the redirect and silently
returning every later test to the production default. That is why
`stance_memory.json` kept changing even after isolation was first configured.

**Tests previously writing live state**
- `tests/test_phase_deploy1_multi_instance.py:198` -- appended real lessons to
  `data/global_memory/global_lessons.jsonl` (240 -> 266 records)
- `tests/test_brain_lifecycle_enforce.py:57` -- `ThesisLifecycleEngine(symbol="QQQ")`
  without `persist=False`, writing a QQQ thesis into the live `active_thesis.json`
- `test_brain_family_repair.py`, `test_brain_invalidation_repair.py`,
  `test_adaptive5_live_authority.py` -- popped roots in teardown

**Repair.** `tests/conftest.py` redirects `AI_BRAIN_DIR`, `AI_RETRIEVAL_DIR`,
`PERFORMANCE_TABLES_DIR`, `HTF_MEMORY_DIR` and `GLOBAL_MEMORY_DIR` to a
per-session temporary root at `pytest_configure`, and an autouse fixture
re-asserts them around **every** test so one careless teardown cannot leak.
`deployment.global_memory` now resolves its root per call.

`REPLAY_CANDLES_DIR` is deliberately **not** redirected: it is a read-only input
archive of committed candles, not a memory store.

**Mutation guard.** `pytest_sessionstart` hashes six protected live files;
`pytest_sessionfinish` re-hashes and fails the run if any changed. The write is
prevented, not cleaned up afterwards.

## A.2 Stale QQQ active thesis

`data/ai_brain/active_thesis.json` held a `no_trade_observation` thesis
(`TH_942090b5acb7`) created 2026-06-15, labelled **QQQ**.

**Root cause.** `_load` checked `active["symbol"]`, but the record stores the
instrument at the **file** level. `active.get("symbol")` was `None`, so the guard
never fired -- only the unrelated idle-expiry check incidentally kept it out of an
MNQ session.

**Repair.** Identity is read where it is actually written. A foreign or
identity-less thesis is **quarantined**: `_active` stays `None`, and
`engine.quarantined` reports the reason, stored instrument, thesis id and path.
The file is left byte-identical -- preserved as evidence, never relabelled MNQ,
never fed to Terra. An armed session now refuses to start on
`FOREIGN_THESIS_STATE`; disarmed diagnostics still run.

**No August 6 thesis was invented.** None existed; none was created.

## A.3 Cross-account peak equity

`capital_history.json` carried **no account binding of any kind**. Anchors
`20260706` through `20260805` all read `99990.53` -- an Alpaca paper balance that
reached the file through the equity leak repaired in `9af35f1` (2026-08-05 17:08).
`20260806: 50042.96` is the first same-account observation, written after that
fix. Drawdown pressure and Brain aggression were therefore being judged against a
peak belonging to a different venue and a different account.

**Repair.** Capital records now bind `venue`, `account_fingerprint`,
`account_mode`, `currency` and `schema_version` (v2). `identity_matches()` rejects
foreign, cross-venue, identity-less and schema-mismatched history. A rejected
record contributes **no peak**; the peak initializes from this account's own
verified balance and is labelled `initialized_from_verified_balance`. The rejected
record is preserved beside the new history as `rejected_foreign_history` with its
reason and anchor count -- not merged, not overwritten, not relabelled.

Correct current peak for the Topstep Combine: **$50,042.96**, from same-account
evidence only.

## A.4 Corrected production reachability

| State | Before | After |
|---|---|---|
| Live stores writable by tests | yes | **no** (redirected + guarded) |
| QQQ thesis loadable into MNQ | yes | **no** (quarantined) |
| Foreign peak drives drawdown | yes | **no** (excluded) |
| Armed startup blocked on contamination | no | **yes** |
| Retrieval corpus | 0 records | **0 records, unchanged** |

## A.5 What was NOT done

No retrospective memory inserted. No memory-authoring pipeline built. No
authorization issued. No order placed. Risk, sizing, prompt doctrine,
CandidateProducer and model selection untouched. The immutable replay archive was
not modified.

---

# APPENDIX B -- Archive of the retired QQQ active thesis (2026-08-06)

A.2 made the QQQ thesis unloadable. It still **sat at the canonical production
state path**, which is needless ambiguity: the guard is the only thing standing
between a retired-instrument record and an MNQ session, and a guard is a weaker
statement than absence. The record was moved out, not deleted and not relabelled.

## B.1 The move

| | |
|---|---|
| From | `data/ai_brain/active_thesis.json` |
| To | `data/replay_sessions/_quarantine/retired_instrument/QQQ/active_thesis_TH_942090b5acb7_20260615.json` |
| sha256 | `731218aa8d219af12f2b6250bc8f87851dc6c7f41b19a81349190791fa5b1d67` |
| Size | 1329 bytes |
| Instrument | QQQ (unchanged) |
| Thesis id | `TH_942090b5acb7`, created 2026-06-15T15:32:00+00:00 |
| Status | `ACTIVE / no_trade_observation` (unchanged) |

Method: `shutil.copy2` -> hash verify -> `os.remove` of the original. The hash was
recorded **before** the move and re-verified **after**; both match. The
destination is git-ignored (`.gitignore:116 data/replay_sessions/`), so the raw
record stays out of source control.

**No placeholder was created.** The canonical path is now absent, and absence is
read as "no active thesis" -- writing an empty stub would have invented a state
the organism never held.

A `QUARANTINE_PROVENANCE.json` sidecar records the original path, the hash, the
provenance (written by the test suite, not by a production session), and the
explicit negatives: `relabelled: false`, `modified: false`,
`replacement_created: false`, `production_reachable: false`.

## B.2 Reachability, verified after the move

| Probe | Result |
|---|---|
| MNQ loader active thesis | none |
| MNQ loader quarantine report | none (nothing foreign left to catch) |
| `_active_path()` | `data\ai_brain\active_thesis.json` |
| Thesis journal | `data\ai_brain\theses\20260807_theses.jsonl` |
| Retrieval store | `data\ai_retrieval\memory_store.jsonl` |
| Any production path under `_quarantine` | none |
| Retrieval records | 0 |

The launcher **names** the quarantine directory for telemetry and never opens it.
The directory name is read from `doctrine.instrument_identity.RETIRED_INSTRUMENTS`
rather than spelled in the launcher -- a bare retired symbol in the launcher is
precisely what DECON-3 forbids, and the doctrine module is the single authority.

## B.3 A separate defect found during preconditions

Verifying that the spent `PROD-20260806` authorization could not be reused
uncovered an unrelated fail-open. A **pre-Terra** authorization record has `None`
for `brain_model`, `brain_reasoning_effort` and `brain_contract_fingerprint`.
`SessionAuthorization.fingerprint()` joined those parts directly, so a legacy
record raised `TypeError` -- and because the launcher catches only
`AuthorizationRefused`, that propagated as an **unhandled crash** rather than a
stated refusal.

**Repair.** Every fingerprint part is coerced to `str`. A legacy record now
mismatches and returns `AUTHORIZATION_CORRUPT`: it fails **closed**, with a
reason.

## B.4 Protected-file state

`tests/conftest.py` `PROTECTED` still lists `data/ai_brain/active_thesis.json`.
It is now absent, hashed as `<absent>` at both sessionstart and sessionfinish, so
the mutation guard does not false-fail. The removal was **authorized by this
mission** and is asserted explicitly rather than left to look accidental. Every
other protected file is byte-identical.

## B.5 What was NOT done

The archived bytes were not edited, relabelled, re-dated or re-instrumented. No
MNQ thesis was created to replace it. No retrieval record was authored. The
immutable replay archive was not touched. No authorization was issued and no
order endpoint was reached.

---

# APPENDIX C -- A safe writer now exists (2026-08-06)

Section 4 of this audit named the gap: the bot archives everything and learns
nothing. `BUILD-SAFE-DESCRIPTIVE-SESSION-MEMORY` closes it **without inserting
anything from August 6**.

## C.1 What was built

A post-session authoring pathway that turns a completed session archive into a
bounded number of **descriptive observation** records: `authority CONTEXT_ONLY`,
`outcome_validated false`, `recommendation_authority none`,
`execution_authority none`. A second class, `outcome_validated`, is reserved in
the schema with **no writer implemented** -- it requires real fills,
reconciliation, bot attribution, fees and slippage evidence, and no August 6
record qualifies.

Full doctrine: [`docs/production/SAFE_DESCRIPTIVE_MEMORY.md`](../SAFE_DESCRIPTIVE_MEMORY.md).

## C.2 August 6 was analysed, not learned

| | |
|---|---|
| Mode | `DRY_RUN_ONLY` |
| Scans read | 172 |
| Quality-eligible | 167 (3 degraded + 2 fallback excluded) |
| Proposed segments | **10** |
| Written to `memory_store.jsonl` | **0** |
| Live corpus before | 0 records, 0 bytes |
| Live corpus after | **0 records, 0 bytes** (sha256 `e3b0c442...` unchanged) |

Proposals were written to
`data/replay_sessions/PROD-20260806/analysis/proposed_descriptive_memory/`,
which is git-ignored. Every archived file's hash still verifies and
`manifest.file_count` still matches `SHA256SUMS.txt`: the proposals are strictly
additive and no archived byte changed.

**No retrospective August 6 record was inserted into production memory.** The
dry run exists so the segmentation could be judged against real evidence before
anything durable is written, and the operator has not yet approved a write.

## C.3 Why nothing auto-writes

`OPERATOR_APPROVAL_REQUIRED = True`. The launcher exiting is not consent, and a
forgotten flag must never be the difference between analysing a session and
permanently learning from it -- so dry run is the default and a real write needs
`--commit-memory` **and** `--approve`.

Authoring is also post-session only, enforced structurally: no module reachable
from the scan loop can write to the corpus. Writing during a session would let
the organism retrieve its own developing conclusions an hour later and read them
as independent precedent.

## C.4 Section 4's claim, revisited

This audit said archives are not memory. That is still true, and is now
mechanised: the archive remains the immutable record of what happened, and the
corpus holds a small number of deliberately segmented descriptions that carry no
authority. What the corpus still cannot say is whether any decision was
**correct** -- zero trades have been taken, so there is no outcome to validate,
and the language law refuses to store the claim that standing down avoided
anything.


---

# APPENDIX D -- Vector v1 refused, v2 built (2026-08-06)

Appendix C recorded that a safe writer existed and that ten August 6 records had
been PROPOSED. They were then reviewed record by record before authoring. This
appendix records the outcome of that review. **Nothing in Appendix C is
rewritten; the earlier history stands as written.**

## D.1 The v1 proposals were reviewed and refused

The ten records themselves passed every check: language law 0 violations,
identity law 10/10, provenance 10/10, no account identity, no credentials, no
complete fingerprint. They were not the problem.

The **similarity space** was. Measured:

* `delivery_direction` was routed through a DIRECTIONAL normaliser that matched
  none of the ICT delivery states, so one dimension was on in all ten records
  and added +0.048..0.072 to every pair.
* `structure_state` and `liquidity_state` were unrepresented.
* the confidence and exhaustion dimensions were permanently zero.
* records #4/#5/#6 had byte-identical vectors while #5 differed materially.
* a "conflicted rotation" query spent three of five slots on one
  indistinguishable state.
* the volatility-expansion query's only match existed solely because of the dead
  dimension: 0.5345 with it, 0.4629 without.

Verdict: **REFINE_VECTOR_BEFORE_AUTHORING**. The corpus was at zero records, so
correcting the space cost nothing and delaying lost nothing.

## D.2 No v1 record was authored

**Zero.** The live corpus was 0 records / 0 bytes before the review and 0 records
/ 0 bytes after it, sha256 `e3b0c442...7852b855` unchanged throughout. The v1
proposals remain on disk, untouched, in
`analysis/proposed_descriptive_memory/` for comparison.

## D.3 v2 was built and re-run in dry-run mode

`descriptive.embedding.v2`, **55 dimensions**, vocabulary taken from the
producing modules rather than from one session's observations -- which
immediately surfaced two values the v1 lists had never contained
(`volatility:expanding`, seen 3 times on August 6, and `session:power_hour`).

The August 6 dry run was regenerated into
`analysis/proposed_descriptive_memory_v2/`: same 10 segments, **no duplicate
vectors, no pair above 0.95**, and the false volatility-expansion match gone
(0.4273, correctly below the floor). Diversity now comes from a per-session
analog cap of 2 rather than from three identical records competing.

Full doctrine and measurements:
[`docs/production/SAFE_DESCRIPTIVE_MEMORY.md`](../SAFE_DESCRIPTIVE_MEMORY.md),
Part II.

## D.4 The live corpus remains empty

| | |
|---|---|
| Mode | `DRY_RUN_ONLY` |
| v1 records authored | **0** |
| v2 records authored | **0** |
| Live corpus | **0 records, 0 bytes** |
| Authorizations issued | 0 |
| Orders placed | 0 |
| Immutable archive modified | no |

The Brain-contract fingerprint moved from `brain:96f4279d954c1311` to
`brain:6118d5eedf9fca60`, because retrieval now binds the vector space as well as
the policy. No replacement authorization was issued.


---

# APPENDIX E -- Equal-weight v2 not authored either (2026-08-06)

Appendix D recorded that vector v1 was refused and v2 built. The v2 proposals
were then reviewed the same way, and the same answer came back: **refine before
authoring.**

## E.1 What the equal-weight review found

All 13 v2 blocks carried weight 1.0, so market regime and narrative direction
counted the same as confidence dispersion. Measured on the bullish-expansion
query against segment #1 (0.5374): session phase, delivery, liquidity, active
draw and exhaustion each supplied 17.2% of the numerator while regime, direction
and narrative phase -- all three contradicting -- supplied exactly 0.

A four-profile bake-off then proved that **weighting alone cannot fix it**. A
probe differing only in direction still scores 0.8576 at load = 1.50, because a
contradiction contributes 0 to a cosine numerator rather than subtracting, and
one disagreement out of thirteen blocks is always a small fraction. No threshold
fits between the weakest valid and strongest invalid probe under any profile.

## E.2 What was changed

`descriptive.embedding.v2.1`: authority-tiered block weights (load 1.25 /
contextual 0.75 / diagnostic 0.50, with structure demoted and protected swings
and active draw promoted on explicit prompt citations), internal block bounding,
a **load-bearing contradiction gate**, a **query-completeness law**, and a
threshold re-derived from an insensitivity band (0.50 -> 0.60).

## E.3 Nothing was authored

| | |
|---|---|
| Mode | `DRY_RUN_ONLY` |
| v1 records authored | **0** |
| equal-weight v2 records authored | **0** |
| v2.1 records authored | **0** |
| Live corpus | **0 records, 0 bytes**, sha256 `e3b0c442...` unchanged |
| Authorizations issued | 0 |
| Orders placed | 0 |
| Immutable archive modified | no |

All three proposal generations remain side by side on disk, in their own ignored
directories, so each round of evidence stays comparable. Segmentation was not
changed and still produces 10 segments.

Full detail: [`docs/production/SAFE_DESCRIPTIVE_MEMORY.md`](../SAFE_DESCRIPTIVE_MEMORY.md), Part III.


---

# APPENDIX F -- Final review before the first write (2026-08-06)

Appendix E recorded that the equal-weight v2 proposals were not authored and
that weighting was refined. The weighted v2.1 proposals were then reviewed the
same way, and one defect remained: segments **#4 and #6** consumed both of the
session's allowed retrieval slots at cosine 0.9749, agreeing on every
load-bearing block and differing only in the structure witness (contextual) and
confidence (diagnostic).

## F.1 What was changed

A **semantic recurrence collapse** at retrieval time. Grouping is decided on
semantic fields -- identity, load-bearing market state, session and narrative
phase, and a quantised direction distribution within 0.10 per component --
**never on cosine**. A group consumes one retrieval slot and exposes every
occurrence, its spans, its member similarities and its real contextual and
diagnostic differences.

Exactly one group forms across the ten August 6 records: **{#4, #6}**. Segment #5
cannot join (its delivery is `mixed`). Segment #3 cannot join (session phase and
narrative phase differ) -- correctly, since #3 is the exhaustion segment. The
conflicted-rotation query now returns the group plus **#3**, a genuinely
distinct state, instead of the same state twice.

A second defect was found and fixed on the way: `structure_state` (the display
string, a mode of per-scan labels) disagreed with `structure_evidence` (the
embedded value, a segment mean) on records #3 and #4. Both now derive from one
computation. Segmentation was untouched and still produces 10 segments.

## F.2 Both chronological observations are preserved

Collapse is a **retrieval presentation rule**. Every record remains individually
on disk in JSONL. Nothing was merged, deleted or rewritten. Records from
different sessions never collapse, even when semantically identical.

## F.3 Final review of the ten proposals

| Check | Result |
|---|---|
| Schema | 10/10 valid |
| Language law | 10/10, 0 evaluative assertions |
| Identity law | 10/10 MNQ / CON.F.US.MNQ.U26 / PROD-20260806 |
| Provenance | 10/10 source-validated, not structure-tainted |
| Vector | 10/10 v2.1, 55 dims, manifest and fingerprint verified |
| Authority | 10/10 `CONTEXT_ONLY`, `outcome_validated false` |
| Forbidden fields | none |
| Recurrence | one group {#4, #6}; eight singletons |
| **Total violations** | **0** |

## F.4 Nothing was authored

| | |
|---|---|
| Mode | `DRY_RUN_ONLY` |
| v1 / equal-weight v2 / v2.1 records authored | **0 / 0 / 0** |
| Live corpus | **0 records, 0 bytes**, sha256 `e3b0c442...` unchanged |
| Authorizations issued | 0 |
| Orders placed | 0 |
| Immutable archive modified | no |

Recommendation returned: **APPROVE_ALL_10_FOR_AUTHORING**.

Full detail: [`docs/production/SAFE_DESCRIPTIVE_MEMORY.md`](../SAFE_DESCRIPTIVE_MEMORY.md), Part IV.
