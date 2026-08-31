# Safe Descriptive Session Memory

**Mission:** BUILD-SAFE-DESCRIPTIVE-SESSION-MEMORY
**Date:** 2026-08-06
**Branch:** `ob-block-finder-and-evidence-diagnostics`
**Initial HEAD:** `4e2e532`
**Production Brain:** `gpt-5.6-terra`

---

## 1. Why archival is not learning

PROD-20260806 ended with **741 archived artifacts and 0 retrievable records**. The
session is perfectly reconstructable and completely un-consultable. An archive
answers "what happened on August 6". Memory answers "have I seen this before" --
and only the second one changes tomorrow's read.

The unsafe fix is obvious and wrong: append all 172 scans to the corpus. Two
things break immediately.

**Repetition masquerading as evidence.** 110 of 172 scans said `conflicted`. As
172 records they become 172 votes for the same thing, and a top-5 retrieval
returns five copies of one opinion.

**Self-confirmation.** Every scan on August 6 ended in `stand_down`. Stored
without qualification, tomorrow's retrieval says "the last hundred times this
state appeared, the system stood down" -- which is true, and says nothing about
whether standing down was right. The bot would be training on its own unverified
opinion and reading the result as independent precedent.

So the corpus stores **descriptions**, deliberately segmented, explicitly
labelled as carrying no authority.

---

## 2. Memory taxonomy

Two classes. They are not interchangeable and one does not mature into the other.

### Descriptive observation memory

| | |
|---|---|
| `memory_type` | `descriptive_observation` |
| `authority` | `CONTEXT_ONLY` |
| `outcome_validated` | `false` (enforced; a `true` fails validation) |
| `recommendation_authority` | `none` |
| `execution_authority` | `none` |
| Source | a completed session's archived scans |
| Requires a trade | **no** -- a no-trade session is a valid source |

It records what was observed: regime, volatility, session phase, delivery,
structure witness, liquidity configuration, protected levels, active draw, the
direction and action distributions, candidate count, and the stated reasons no
candidate existed.

It records what was **absent**, never that the absence was wise.

### Outcome-validated memory

Reserved. `memory_type` exists in the schema; **no writer is implemented**. It
may only be authored after a real entry fill, a real exit fill, complete
round-trip reconciliation, verified bot attribution, known fees and commissions,
slippage evidence, and a final outcome.

**No August 6 record qualifies. None was authored.** The system has taken zero
trades; there is no outcome to validate.

---

## 3. Context-only authority

Retrieved descriptive analogs are context. The boundary is enforced in four
independent places, because one is not enough:

1. **The record** carries `authority`, `outcome_validated`,
   `recommendation_authority` and `execution_authority` as stored fields.
2. **The writer** refuses any record whose fields contradict those values.
3. **The reader** (`retrieve_analogs`) drops a descriptive record whose
   `authority` is not `CONTEXT_ONLY` or whose `outcome_validated` is not `false`
   -- even though the writer should have made that impossible.
4. **The view** attaches `RC.ANALOG_FRAMING` to every analog individually, and
   the system prompt states the boundary in full.

The framing travels **with each record**, not once in a header. A single header
sentence is something a model can drift past by the fifth analog; a per-record
label cannot be separated from the data it labels.

A retrieved analog cannot: create a candidate, establish direction, supply a
missing invalidation, supply a liquidity objective, change risk, change sizing,
relax reward-to-risk, or bypass CandidateProducer. The schema has no risk or
sizing field to read, and tests 25-29 exercise the producer directly.

---

## 4. Segmentation law

Applied in order. `src/ai_retrieval/session_segmentation.py`.

1. **Quality.** A scan that was degraded, fell back, was malformed, came from an
   unsanctioned model, is not MNQ, has no contract identity, or is a test
   artifact contributes nothing. It is counted as an exclusion, never repaired.
2. **Signature.** Consecutive scans sharing a state signature form one run.
3. **Duration.** A run shorter than `MIN_SEGMENT_SCANS = 5` is a fluctuation, not
   a state. It is absorbed into its neighbour. Its scans still count toward the
   distributions, so the blip stays visible in the record without becoming a
   durable truth of its own. If absorbing a blip leaves two neighbours with the
   same signature, they **re-join** -- otherwise one stray scan permanently
   splits a homogeneous stretch and the corpus stores the same state twice.
4. **Ceiling.** If the cut still exceeds `SEGMENT_CEILING = 12`, the signature
   coarsens one rung down a fixed ladder (T0..T5) and the cut is redone.

Segments are **never truncated**. Truncating to fit the ceiling would silently
delete the afternoon.

The ceiling is a storage bound, not a target. A quiet session may produce three.

**The tier ladder**

| Tier | Signature |
|---|---|
| T0 | session_phase, market_regime, volatility_state, delivery_state, narrative_direction, narrative_phase, draw_present, protected_state |
| T1 | session_phase, market_regime, delivery_state, narrative_direction, narrative_phase, draw_present |
| T2 | session_phase, market_regime, narrative_direction, narrative_phase |
| T3 | session_phase, market_regime, narrative_direction |
| T4 | session_phase, narrative_direction |
| T5 | session_phase |

---

## 5. Quality filters

A scan contributes only when instrument is MNQ, contract identity is present,
`source == "llm"`, `fallback_reason` is absent, the parsed output is valid, the
model is sanctioned, and the artifact is not test-generated.

**On the model filter.** `SANCTIONED_MEMORY_MODELS = {gpt-5.6-terra,
gpt-5.6-luna}`, not simply the current production model. This is a deliberate,
documented widening of the mission's "resolved production model" wording.

PROD-20260806 ran `gpt-5.6-luna`, which was the sanctioned production model that
day and is now the *previous* one. Luna appears in `FORBIDDEN_MODELS` because it
may not be **run** today -- a live-execution question. Whether a read it produced
when it *was* the production model may be **described** is a different question.
Answering it with the execution list would have excluded all 167 eligible scans,
made this mission's dry run vacuous, and orphaned every past session at each
Brain upgrade. Every record stores `source_model` verbatim, so a consumer can
always narrow further.

---

## 6. Identity law

Every record carries `instrument`, `contract`, `session_date` and provenance.
Retrieval excludes retired instruments (QQQ), foreign instruments, identity-less
records, records marked ineligible, malformed schema, and expired records --
identity is checked **before** similarity, because a QQQ session can resemble an
MNQ one closely and similarity is exactly what would let equity evidence look
like a good analog for a futures decision.

**Contract scoping.** Absolute prices are contract-scoped. Across a rollover the
same number is a price on a different instrument-month, and comparing it to
today's book is a units error dressed as an analog. When the querying contract
differs from the recorded contract, `protected_high` and `protected_low` are
**withheld** and the analog is marked `levels_withheld: true` with a reason. The
categorical regime features remain retrievable -- "toxic volatility during lunch
rotation" survives a rollover; "29780.0" does not.

---

## 7. Retention

`MAX_AGE_DAYS = 60`, measured in **ET session dates**, not naive timestamps: a
record written at 15:58 ET and a query at 09:31 ET next morning are one session
apart, not 0.7 days, and a timestamp-difference rule would round that wrong twice
a day.

Expiry is a **retrieval** rule, not a retention rule. An expired record stays on
disk for audit; it simply stops being offered as an analog. A record whose age
cannot be established expires immediately -- unknown age is not young age.

---

## 8. Deduplication

`memory_id` is derived from schema version, session id, instrument, contract,
segment boundaries and source-artifact digest. Content is deliberately **not**
hashed into the id, so a different reading of the same segment collides and
surfaces as a conflict instead of quietly appending a second version of the same
moment.

| Situation | Result |
|---|---|
| First authoring | records written |
| Identical re-authoring | `ALREADY_AUTHORED_UNCHANGED`, 0 written |
| Same id, different `content_digest` | `MEMORY_CONFLICT_REFUSED` |

A conflict refuses the **whole batch**. A partial write would leave the session
half described and the operator reconstructing which half.

---

## 9. Operator workflow

```
launcher exits cleanly
  -> archive / integrity verification
  -> descriptive-memory DRY RUN            (default, no flag needed)
  -> policy validation                     (schema, language law, identity)
  -> durable authoring                     (OPERATOR_APPROVAL_REQUIRED)
```

```
python tools/author_descriptive_session_memory.py \
    --session-id PROD-20260806 \
    --archive-path data/replay_sessions/PROD-20260806
```

Dry run is what happens when the flag is forgotten. A real write needs
`--commit-memory` **and** `--approve`.

**Unattended automatic writes are DISABLED.** The launcher exiting is not
consent. `OPERATOR_APPROVAL_REQUIRED = True` for this first deployment.

The command refuses when the session is still active, the account is not flat,
the archive is incomplete, instrument identity conflicts, source artifacts are
unverifiable, or the session already has conflicting memories.

### Preconditions

Authoring requires: the final phase terminated cleanly with exit code 0, the
launcher proved flat, reconciliation shows 0 positions and 0 working orders, no
unresolved execution token, fills and round trips agree, and the manifest reads.

A non-final phase stopped externally does **not** by itself defer the session,
provided the final phase closed cleanly and the account was afterwards proven
flat. PROD-20260806 is exactly that case: phase A was killed by an external task
manager while flat, phase C ran to window close with exit 0. The anomaly is
recorded in provenance rather than used to erase a session whose end state is
fully evidenced. What *does* defer is an unproven end state.

---

## 10. Brain-contract binding

`brain_contract_fingerprint()` now folds in `retrieval_contract_fingerprint()`,
which hashes the **resolved policy values**: schema version, authority label,
max analogs, min similarity, max age, cross-contract level policy, and the
framing text. Hashing the source file would miss a value arriving from
configuration; hashing resolved values cannot.

Changing any of those invalidates every previously issued authorization. That is
the point: retrieval changes what the Brain *receives*, and an authorization that
binds only the model and prompt would still verify while the payload moved
underneath it.

**No new authorization was issued during this mission.**

---

## 11. August 6 dry-run results

Command run with `--dry-run`; live store unchanged at 0 records, 0 bytes.
Proposals written to
`data/replay_sessions/PROD-20260806/analysis/proposed_descriptive_memory/`
(git-ignored).

```
TOTAL SCANS            : 172
QUALITY-ELIGIBLE       : 167
  excluded source_degraded            : 3
  excluded source_llm_failed_fallback : 2
SIGNATURE TIER         : T0
RAW RUNS               : 66
PROPOSED SEGMENTS      : 10
PHASE EXIT ANOMALIES   : A EXTERNAL_TASK_STOP -- CAUSE UNPROVEN
                         B INTENTIONAL_STOP_WHILE_FLAT (semantic repair)
```

| Segment (ET) | n | Session phase | Regime | Volatility | Direction | Action | Code phase |
|---|---|---|---|---|---|---|---|
| 09:30:24-10:04:49 | 24 | ny_open | range_rotation | unstable | conflicted | stand_down | A |
| 10:06:03-11:02:33 | 11 | morning_continuation | range_rotation | toxic | neutral | stand_down | A,B |
| 11:05:02-11:30:31 | 22 | morning_continuation | range_rotation | toxic | conflicted | stand_down | B |
| 11:31:44-11:48:47 | 15 | lunch | range_rotation | toxic | conflicted | stand_down | B |
| 11:50:02-12:07:10 | 15 | lunch | range_rotation | toxic | conflicted | stand_down | B |
| 12:08:22-12:22:55 | 13 | lunch | range_rotation | toxic | conflicted | stand_down | B |
| 12:40:02-13:00:32 | 18 | lunch | chop | toxic | neutral | stand_down | B,C |
| 13:01:45-13:16:28 | 13 | afternoon | chop | stable | neutral | stand_down | C |
| 13:17:38-13:31:20 | 12 | afternoon | chop | stable | conflicted | stand_down | C |
| 13:32:33-14:00:24 | 24 | afternoon | range_rotation | stable | bearish | stand_down | C |

All ten: `candidate_count 0`, `trade_count 0`, `liquidity_state
two_sided_pools`, `protected_high/low` null, `outcome_validated false`,
`authority CONTEXT_ONLY`, 47-dimension feature vector.

`no_candidate_reasons` are mechanical statements of absence:
`action_declines_entry`, `direction_not_established`, `no_protected_structure`,
`no_active_draw`. The final segment carries only `action_declines_entry` --
direction *was* established (bearish) and protected structure did appear.

**The three code phases are preserved in provenance.** Segments spanning the
11:02/12:41 boundaries record `["A","B"]` and `["B","C"]`. Historical production
observations were read as historical fact; no scan was re-run through current
code, so nothing here is counterfactual.

---

## 12. August 7 retrieval simulation

The ten proposals were loaded into an **isolated temporary store**; the live
store was never touched. Six representative queries, as-of session date
2026-08-07.

| Query | Returned | Top similarity | Selected |
|---|---|---|---|
| 1 bullish expansion | **0** | -- | none |
| 2 bearish delivery | **0** | -- | none |
| 3 conflicted rotation | 5 | 1.0000 | 11:50:02-12:07:10 |
| 4 neutral lunch range | 4 | 0.7715 | 12:40:02-13:00:32 |
| 5 exhaustion | 5 | 1.0000 | 11:05:02-11:30:31 |
| 6 volatility expansion | 1 | 0.5345 | 13:32:33-14:00:24 |

Queries 1 and 2 returning **nothing** is the correct answer, not a failure:
August 6 contained no bullish expansion and no clean bearish-delivery segment.
The corpus honestly has no analog, and the floor (`MIN_SIMILARITY = 0.5`) says so
rather than offering the nearest unrelated thing.

Every returned analog carried `authority: CONTEXT_ONLY` and
`outcome_validated: false`. A rollover probe (query contract `...Z26`) returned
the same segments with `levels_withheld: true` and the price fields removed. An
expiry probe as-of 2026-10-20 returned 0 with all 10 rejected as `expired`, and
all 10 remained on disk.

---

## 13. Two defects found while building this

**The descriptive records embedded into the wrong vector space.** A descriptive
record stores its state flat; `embedding._key_fields` dispatched on
`"narrative_context" in rec`, so descriptive records fell through to the
live-snapshot reader, matched none of its keys, and embedded as a near-zero
vector. They were stored successfully and were then **never retrievable** --
every one of the six simulated queries returned 0. Silent, and visible only as
"returned: 0". Fixed by teaching the one existing encoder to read the record
directly, rather than adding a second encoder: two encoders would mean two vector
spaces in one store, and cosine between them is arithmetic without meaning.
`EMBED_DIM` is unchanged at 47.

**One stray scan permanently split a homogeneous stretch.** After absorbing a
short run, the segmenter did not re-join neighbours that then shared a signature.
On the real August 6 data this produced two lunch segments identical in every
field the signature reads. Fixed; the cut went from 11 segments to 10.

---

## 14. What is still NOT learned

- **Whether any decision was correct.** Zero trades have been taken. There is no
  outcome evidence, and none is invented.
- **Whether standing down avoided anything.** That is a counterfactual the
  organism never ran. The language law refuses to store the claim.
- **What works.** Descriptive memory can say "this state occurred and no
  candidate followed". It cannot say "this state pays".
- **Cross-session statistics.** No aggregation, expectancy or scoring is built.
- **Anything from August 6 itself.** The dry run was analysed; **no record was
  inserted into the live corpus.**

---

## 15. Future outcome-memory requirements

Before an `outcome_validated` writer may exist:

1. Real entry fill with venue confirmation.
2. Real exit fill with venue confirmation.
3. Complete round-trip reconciliation.
4. Verified bot attribution (not a manual or external close).
5. Known fees and commissions (measured $1.22 round trip).
6. Slippage evidence from the passive measurement program.
7. Final outcome and R-multiple.

Outcome records must remain a separate class with a separate authority label.
A descriptive record must never be upgraded in place -- an observation that later
acquires an outcome is a *new* record, because the observation itself was made
without knowing it.

---

## 16. Files

| File | Role |
|---|---|
| `src/ai_retrieval/retrieval_contract.py` | the bound policy + its fingerprint |
| `src/ai_retrieval/descriptive_memory.py` | schema, identity, retention, language law |
| `src/ai_retrieval/session_segmentation.py` | archive reader + segmentation law |
| `src/ai_retrieval/memory_authoring.py` | preconditions, dedup, dry-run/commit |
| `src/ai_retrieval/retrieval.py` | type-aware view, expiry, contract scoping |
| `src/ai_retrieval/embedding.py` | descriptive branch (47 dims, unchanged) |
| `src/ai_brain/production_model.py` | retrieval policy folded into the fingerprint |
| `src/ai_brain/brain_prompt.py` | the authority boundary, stated to Terra |
| `tools/author_descriptive_session_memory.py` | the bounded operator command |
| `tools/topstepx_production_session.py` | descriptive-memory telemetry |
| `tests/test_descriptive_session_memory.py` | 47 tests over the 38 required proofs |

---

# PART II -- Vector v2

**Mission:** REFINE-DESCRIPTIVE-MEMORY-VECTOR-V2
**Date:** 2026-08-06
**HEAD in:** `64d5d3e`

Everything above describes the doctrine, which did not change. What changed is
the geometry the doctrine runs in.

## 17. Why v1 was refused before authoring

The ten proposed August 6 records were read one by one before any of them was
allowed into the corpus. The records were clean. The similarity space was not.

**Root cause: a dead delivery block.** `delivery_direction` was routed through
`embedding._norm_dir()`, which matches the DIRECTIONAL vocabulary
(bullish/bearish/conflicted/neutral). The values this system actually emits are
the PO3 alignment states -- `accumulation_building`, `mixed`,
`full_distribution_alignment`, `manipulation_to_distribution`. None of them
begins with a directional token, so every one fell through to `none`.

The consequence was not "delivery was ignored". It was worse: index 40 was ON in
all ten records and in five of six queries, so every pair received a free shared
component. Measured inflation was **+0.048 to +0.072** on every above-floor pair.
One record pair (#9-#10) crossed the floor purely on it, and the
volatility-expansion query's only "match" scored **0.5345 with the dead block and
0.4629 without** -- the entire result was the artifact.

**Also proven:** `structure_state` and `liquidity_state` were not represented at
all; the two confidence scalars were hardcoded `None` on the memory path; the
exhaustion scalar was never populated; records #4/#5/#6 had byte-identical
vectors while #5 differed materially in delivery and structure; and ranking ties
fell through to JSONL append order.

**Two vocabularies were also incomplete against their own producers** --
`volatility_classifier` emits `expanding` (3 August 6 scans) and `session_engine`
emits `power_hour`; neither appeared in the v1 lists, so both encoded as
all-zeros. Phase 1 caught these precisely because the vocabulary was rebuilt from
the producers rather than from one session's observations.

The corpus was still at **0 records**, so the space was replaced rather than
migrated.

## 18. Authoritative vocabularies

Every list is copied from the module that PRODUCES the value.

| # | Field | Authoritative source | Supported | Seen Aug 6 | In similarity |
|---|---|---|---|---|---|
| 1 | market regime | `regime_classification/regime_classifier.py::_FAMILIES` | 9 (+`unknown`) | range_rotation, chop, unknown | yes |
| 2 | volatility state | `volatility/volatility_classifier.py::_state` | 6 (+`unknown`) | toxic, stable, unstable, **expanding** | yes |
| 3 | session phase | `market_data/session_engine.py::_SESSIONS` | 7 (+`closed`) | ny_open, morning_continuation, lunch, afternoon, premarket | yes |
| 4 | narrative phase | `ai_brain/brain_validation.py::VALID_PHASES` | 9 | 6 of 9 | yes |
| 5 | narrative direction | `ai_brain/brain_validation.py::VALID_DIRECTIONS` | 4 | all 4 | yes, as a **distribution** |
| 6 | delivery state | `structure/po3_engine.py::_po3_alignment` | 5 | 4 of 5 | yes |
| 7 | liquidity state | derived from `liquidity.nearest_buy_side` / `nearest_sell_side` | 4 | two_sided_pools (161), buy_side_only (6) | yes |
| 8 | structure evidence | `STRUCTURE_WITNESS[tf].bos_event` / `.mss_event` | counts 0-4 | bos 0-4, mss 0-1 | yes, as counts |
| 9 | active draw | `liquidity.active_draw` | present / absent | 85 / 87 | yes, two-state |
| 10 | protected structure | `ai_brain/brain_input.py::_protected.rel` | high: none/violating/approaching/below; low: none/violating/approaching/above | none, approaching | **presence only** |
| -- | exhaustion | `shared_context/shared_market_context.py::_exhaustion_present` | true / false | 79 / 93 | yes, two-state |

`unknown`, `none` and `closed` appear in NO vocabulary list. They are the
all-zeros case, not a category.

Metadata only, never in similarity: dominant action, action distribution,
candidate count, trade count, no-candidate reasons, source model, code phase,
memory id, session id, the `structure_state` display string, and protected price
levels. Matching on the bot's own prior decisions would be a self-confirming
loop.

## 19. Dimension map -- `descriptive.embedding.v2`, **55 dimensions**

| Range | Size | Group | Kind |
|---|---|---|---|
| `[0:9)` | 9 | market_regime | one-hot |
| `[9:15)` | 6 | volatility_state | one-hot |
| `[15:22)` | 7 | session_phase | one-hot |
| `[22:31)` | 9 | narrative_phase | one-hot |
| `[31:35)` | 4 | direction_distribution | distribution, L2-normalised |
| `[35:40)` | 5 | delivery_state | one-hot |
| `[40:43)` | 3 | structure_evidence | `[bos/4, mss/4, quiet]` |
| `[43:47)` | 4 | liquidity_state | one-hot |
| `[47:49)` | 2 | active_draw | two-state |
| `[49:50)` | 1 | protected_high | presence |
| `[50:51)` | 1 | protected_low | presence |
| `[51:53)` | 2 | exhaustion | two-state |
| `[53:55)` | 2 | confidence | `[mean/100, (max-min)/100]` |

Manifest fingerprint `emb:0110829ec9b77839`. Every index is covered exactly once;
`block_weights` are all 1.0 and live in the manifest so a future reweighting
changes the fingerprint and invalidates authorizations.

## 20. Missing-value law

> An unknown or unsupported categorical value contributes **all zeros** for its
> group, plus a note in `embedding_notes`. No shared `none` or `unknown`
> dimension exists anywhere in the vector.

Two incomplete records must never resemble each other *because* they are
incomplete -- that is the v1 defect wearing a different name. Where "none" is a
real market fact rather than an absence of evidence -- no active draw, no
exhaustion -- it is encoded as an explicit two-state block, and genuine
unknown-ness is both slots zero. A record that fails to embed is refused, not
guessed at: an absent `STRUCTURE_WITNESS` raises rather than being read as quiet.

## 21. Direction as a distribution

Segment #10 read bearish 8 / conflicted 8 / neutral 6 / bullish 2 across 24
scans. v1 stored `dominant_direction: "bearish"` and could not tell it from a
uniformly bearish segment. v2 stores the proportions, requires them to sum to
1.0 over the eligible scan count, and refuses an incomplete or
unsupported-vocabulary distribution.

The block is **L2-normalised** so every record contributes equal magnitude from
direction regardless of how mixed it was -- otherwise a mixed segment would be
systematically quieter, and "how mixed" would be confounded with "how strongly
it matches anything".

## 22. Structure, liquidity, confidence, exhaustion

**Structure** reads the underlying `bos_event`/`mss_event` flags directly, so
there is no display string to parse and no unparseable string that could be
misread as quiet. Counts are divided by 4 (structurally bounded -- four
timeframes) and capped at 1.0, so no abnormal reading can dominate cosine.

**Liquidity** distinguishes `two_sided_pools`, `buy_side_only`, `sell_side_only`
and `no_pools`. For a directional system buy-only and sell-only are opposite
situations; v1 called both `one_sided_pool` and embedded neither.

**Confidence** is `mean/100` and `(max-min)/100` from `phase_confidence_summary`.
A value outside 0-100 is **rejected, not clipped** -- a 140 is a defect, and
flattening it destroys the evidence that it happened. No delivery-confidence
feature was invented; there is no such segment-level measurement.

**Exhaustion** was NOT removed. Investigation found an independent producer,
`shared_market_context._exhaustion_present`, which split 79/93 across August 6
while `narrative_phase` read exhaustion only 23 times. It is not a restatement,
so per the mission it was populated rather than deleted.

## 23. Recurrence collapse and per-session diversity

Chronological segments are preserved: when the market leaves a state and returns
to it, those are two segments. Non-adjacent segments are never merged.

But retrieval must not present one session's repetitions as independent votes.
Two records from the **same** session with an identical vector fingerprint
collapse to one representative that consumes one slot and exposes
`recurrence_count`, `recurrence_spans` and `recurrence_memory_ids`.
Representative selection is deterministic: scan count, then duration, then
segment start, then memory id. **Confidence is deliberately not a criterion** --
a more confident occurrence is not a more correct one.

Records from **different** sessions never collapse; the same state on another day
is independent evidence.

`MAX_ANALOGS_PER_SOURCE_SESSION = 2`. Even when v2 tells segments apart, one
quiet Thursday must not speak five times. 2 leaves room for a state and its
neighbour and no more.

## 24. Deterministic ranking

```
similarity desc -> session_date desc -> scan_count desc
                -> segment_duration desc -> memory_id asc
```

Applied in that order, after collapse, before top-k, and reported as
`ranking_tuple` on every returned analog. v1 sorted on similarity alone; Python's
stable sort then fell through to JSONL append order, so ranking depended on the
order records happened to be written.

**One space per ranking.** A corpus holding any descriptive record is read in
v2; legacy 47-dimension AB-3 records are excluded with a reason and never ranked
alongside. Cosine between the two would return a number rather than fail.

## 25. Threshold analysis

Re-derived under v2, not inherited. Ten probes against the ten-record corpus:

| Query | Top similarity | Verdict at 0.5 |
|---|---|---|
| bullish expansion (absent state) | 0.4647 | excluded |
| volatility expansion (absent state) | **0.4273** | excluded |
| bearish delivery (partial state) | **0.5129** | included |
| neutral lunch range | 0.7237 | included |
| near-neighbour of #4 | 0.8277 | included |
| conflicted rotation | 0.9377 | included |
| exact-state replay of #4 | 0.9378 | included |
| exhaustion | 0.9467 | included |

The genuinely-absent states top out at **0.465**; the weakest legitimate analog
sits at **0.513**. The gap straddles 0.50 almost exactly. Lowering to 0.45 admits
both false matches; raising to 0.55 kills the legitimate bearish-delivery analog.

**`MIN_SIMILARITY` stays at 0.5 -- re-derived, not inherited.**

## 26. August 6 v2 dry-run result

`DRY_RUN_ONLY`. Live store unchanged at 0 records / 0 bytes / sha256
`e3b0c442...`. Proposals in
`data/replay_sessions/PROD-20260806/analysis/proposed_descriptive_memory_v2/`
(git-ignored). v1 proposals left untouched beside them for comparison.

172 scans read, 167 quality-eligible (3 degraded + 2 fallback excluded), tier T0,
66 raw runs, **10 segments** -- unchanged from v1, because segmentation was not
the defect.

| # | ET span | n | Delivery | BOS/MSS | Exhaustion | Nonzero | Vector |
|---|---|---|---|---|---|---|---|
| 1 | 09:30:24-10:04:49 | 24 | full_distribution_alignment | 2/0 | false | 13 | `vec:ceb713c4bf2cf119` |
| 2 | 10:06:03-11:02:33 | 11 | mixed | 1/0 | false | 14 | `vec:c7f35f71477722e9` |
| 3 | 11:05:02-11:30:31 | 22 | accumulation_building | 1/0 | **true** | 12 | `vec:cb2cdb573d7af151` |
| 4 | 11:31:44-11:48:47 | 15 | accumulation_building | 1/0 | **true** | 12 | `vec:a9ae4286aad623c8` |
| 5 | 11:50:02-12:07:10 | 15 | **mixed** | 1/0 | false | 12 | `vec:343e527cd5084099` |
| 6 | 12:08:22-12:22:55 | 13 | accumulation_building | **0/0** | **true** | 12 | `vec:34449feaa28af777` |
| 7 | 12:40:02-13:00:32 | 18 | mixed | 1/0 | false | 12 | `vec:0f4735dcd2d146a4` |
| 8 | 13:01:45-13:16:28 | 13 | mixed | 1/1 | false | 15 | `vec:b292209c4f2c34df` |
| 9 | 13:17:38-13:31:20 | 12 | accumulation_building | 0/0 | false | 13 | `vec:e0ae4b14b8d50a17` |
| 10 | 13:32:33-14:00:24 | 24 | accumulation_building | 1/0 | **true** | 16 | `vec:d46e90da2b43ff9d` |

**Exact duplicate vectors: NONE** (v1 had a three-way group).
**Pairs above 0.95: NONE.** The single pair above 0.90 is #4-#6 at **0.949** --
two genuinely near-identical recurrences of one lunch state, which is truthful.
#5 now separates from both at 0.786, on delivery, structure and exhaustion.

**One universally-on categorical dimension remains**: `liquidity_state:
two_sided_pools`. Unlike the v1 dead block this is a real shared market fact with
three reachable alternatives -- August 6 itself produced `buy_side_only` in 6
scans.

## 27. August 7 simulation under v2

Isolated temporary store; the live corpus was never touched. As-of session date
2026-08-07.

| Query | Pre-collapse | Cap drops | Returned | Top | Selected |
|---|---|---|---|---|---|
| 1 bullish expansion | 0 | 0 | **0** | 0.4647 | none |
| 2 bearish delivery | 1 | 0 | 1 | 0.5129 | #1 09:30-10:04 |
| 3 conflicted rotation | 9 | 7 | **2** | 0.9377 | #4, #6 |
| 4 neutral lunch range | 3 | 1 | 2 | 0.7237 | #7, #2 |
| 5 exhaustion | 7 | 5 | 2 | 0.9467 | **#3 11:05-11:30** |
| 6 volatility expansion | 0 | 0 | **0** | 0.4273 | none |

Recurrence collapse did not fire -- no two v2 vectors are identical, so there was
nothing to collapse. **Diversity came from the per-session cap**, which is the
better outcome: the three lunch segments stopped consuming three slots because
they became distinguishable, not because they were merged.

Cross-contract probe (`...Z26`): same segments returned, `levels_withheld: true`,
price fields removed, categorical features intact. Expiry probe at 2026-10-20:
0 returned, all 10 rejected `expired`, all 10 still on disk.

## 28. Known limitation, stated not tuned away

The bullish-expansion query returns nothing at the bound threshold, but its top
unfiltered score moves between **0.465 and 0.587** depending on how much of the
state the query specifies. Every point of that comes from features the query and
the 09:30 segment genuinely share -- ny_open, `full_distribution_alignment`
delivery, BOS=2, two-sided pools, active draw, no exhaustion, similar confidence.
It is a real partial-state analog, not a v1-style artifact, and it never
approaches the ~0.94 a true state match produces.

The underlying cause is that all 13 blocks carry weight 1.0, so regime and
direction -- the two most decision-relevant features -- count the same as
exhaustion or active draw. **Block weighting deserves its own bounded mission.**
It was not adjusted here, because tuning weights until one probe produces a
desired number is exactly what the mission forbade.

Mitigations already in place: the analog is returned with its real
`market_regime` and `dominant_direction`, labelled `CONTEXT_ONLY`, with
`outcome_validated: false`, and the system prompt states that today's evidence
always wins.

## 29. Contract binding

| | Before | After |
|---|---|---|
| Brain contract | `brain:96f4279d954c1311` | **`brain:6118d5eedf9fca60`** |
| Retrieval contract | `retr:e6822e52679fcd12` | **`retr:a325e314e4098956`** |
| Embedding manifest | -- | **`emb:0110829ec9b77839`** |

The retrieval contract now binds embedding version, dimension count, manifest
fingerprint, category ordering, normalization law, missing-value law, similarity
threshold, max analogs, max analogs per source session, recurrence-collapse
policy, tie-break order, retention age, authority label and the contract-level
withholding policy. Changing any of them invalidates every previously issued
authorization.

**No replacement authorization was issued.**

## 30. v2 files

| File | Role |
|---|---|
| `src/ai_retrieval/embedding_v2.py` | vocabularies, manifest, encoder, fingerprints |
| `src/ai_retrieval/retrieval_contract.py` | the bound policy, now including the vector space |
| `src/ai_retrieval/retrieval.py` | space gate, recurrence collapse, session cap, ranking |
| `src/ai_retrieval/descriptive_memory.py` | v2 schema + normalised protected levels |
| `src/ai_retrieval/session_segmentation.py` | authoritative underlying fields |
| `src/ai_retrieval/memory_authoring.py` | segment-level structure and exhaustion |
| `tests/test_descriptive_vector_v2.py` | 73 tests over the 52 required proofs |

---

# PART III -- Block weighting and the contradiction gate (v2.1)

**Mission:** REFINE-DESCRIPTIVE-MEMORY-BLOCK-WEIGHTING
**Date:** 2026-08-06
**HEAD in:** `dc47f60`

## 31. The equal-weight limitation, measured

All 13 v2 blocks carried weight 1.0. The per-block contribution ledger shows
what that meant for the bullish-expansion query against segment #1
(cosine 0.5374):

| Block | Dot | Share of numerator |
|---|---|---|
| session_phase | +1.0000 | 17.2% |
| delivery_state | +1.0000 | 17.2% |
| liquidity_state | +1.0000 | 17.2% |
| active_draw | +1.0000 | 17.2% |
| exhaustion | +1.0000 | 17.2% |
| confidence | +0.5486 | 9.5% |
| structure_evidence | +0.2500 | 4.3% |
| **market_regime** | **0** | **0%** (contradicts) |
| **direction_distribution** | **0** | **0%** (contradicts) |
| **narrative_phase** | **0** | **0%** (contradicts) |

Five secondary blocks supplied 86% of the numerator while all three
load-bearing contradictions supplied nothing.

**The structural cause: a contradiction contributes 0, it never subtracts.** In
a one-hot block, disagreement removes that block's term from the numerator but
leaves its norm in both denominators. Weights enter the numerator as `w^2`
(both coordinates are scaled) and the denominators as `w^2` as well, so raising
a load-bearing weight raises a contradictory pair's denominator without raising
its numerator. That helps -- but only linearly in the number of blocks.

## 32. Why weighting alone was proven insufficient

Four named profiles were evaluated against twelve synthetic semantic probes
built from the authoritative vocabularies (exact state, one/two contextual
differences, same-direction-different-delivery, opposite direction, opposite
regime, both opposite, incompatible volatility, dual contradiction with full
contextual agreement, and the delivery-vs-thesis case).

| Profile | load / context / diagnostic | Weakest VALID | Strongest INVALID | Margin |
|---|---|---|---|---|
| EQUAL_V2 | 1.00 / 1.00 / 1.00 | 0.8039 | 0.9020 | **-0.0980** |
| MINIMAL_CHANGE | 1.00 / 0.75 / 0.50 | 0.8645 | 0.8795 | **-0.0151** |
| AUTHORITY_TIERED_A | 1.25 / 0.75 / 0.50 | 0.8662 | 0.8662 | **0.0000** |
| AUTHORITY_TIERED_B | 1.50 / 0.75 / 0.50 | 0.8576 | 0.8576 | **0.0000** |

**No profile separates them.** A probe differing from the base state in nothing
but direction scores **0.8576 even at load = 1.50**, because twelve of thirteen
blocks still agree and one disagreement out of thirteen is always a small
fraction. No threshold can sit between 0.8576 and 0.8662.

That is a property of cosine over agreement-only blocks, not of the weights
chosen. **Weighting orders records; it cannot express "this record contradicts
the question."**

## 33. Amended authority taxonomy

The proposed taxonomy was amended twice, each time against a citation in
`src/ai_brain/brain_prompt.py`, not against a desired August 6 output.

**STRUCTURE demoted** from load-bearing to contextual:

> "STRUCTURE is a WITNESS, not the authority. It lags; it counts liquidity raids
> as strength. **Weigh it last.**"

plus the six-point STRUCTURE SAFETY CONTRACT ("STRUCTURE is WITNESS ONLY. It
cannot define direction... cannot override DELIVERY / LIQUIDITY / PROTECTED
SWINGS"). Treating structure as load-bearing would contradict the system's own
mandatory contract.

**PROTECTED SWINGS and ACTIVE DRAW promoted** to load-bearing:

> "DELIVERY, LIQUIDITY, and PROTECTED SWINGS are load-bearing."
> "Direction MUST come from delivery, liquidity, protected swings, **active
> draw**, and clean narrative evidence -- never from structure."

| Tier | Blocks | Weight |
|---|---|---|
| Load-bearing | market_regime, volatility_state, direction_distribution, delivery_state, liquidity_state, active_draw, protected_high, protected_low | **1.25** |
| Contextual | session_phase, narrative_phase, structure_evidence, exhaustion | **0.75** |
| Diagnostic | confidence | **0.50** |

Confidence is never market authority: it says how strongly the prior system
expressed an observation, not whether the observation was right.

## 34. Internal block normalization

> Every block is bounded to a maximum norm of 1.0 **before** its weight is
> applied, so no block gains authority from dimension count or from several
> coordinates being active at once.

| Block | Before | After | Note |
|---|---|---|---|
| one-hot / two-state / presence | 0 or 1 | unchanged | already unit-or-zero |
| direction_distribution | 1.0 | unchanged | already L2-normalised |
| structure_evidence | up to 1.414 | **/ sqrt(2)**, max 1.0 | intensity preserved: bos=1 and bos=4 stay different |
| confidence | up to 1.414 | **/ sqrt(2)**, max 1.0 | same |

Intensity was deliberately **not** normalised away -- bounding caps the block's
reach without flattening a 4-BOS reading into a 1-BOS one.

## 35. The load-bearing contradiction gate

Contradiction is handled where it belongs: as a rule.

```
CONTRADICTION_BLOCKS            = market_regime, volatility_state,
                                  delivery_state, liquidity_state
DIRECTION_AGREEMENT_MIN         = 0.35
MAX_LOAD_BEARING_CONTRADICTIONS = 1
```

A block counts as contradicted only when **both** sides state a value and they
disagree -- silence is never evidence of disagreement. Direction is compared as
a **distribution**, not a label: a segment reading bearish 8 / conflicted 8 /
neutral 6 / bullish 2 agrees 0.617 with a conflicted query and is not a
contradiction, while pure bullish against pure conflicted is 0.000 and is.

One contradiction is permitted so a near-neighbour disagreeing on a single field
stays retrievable. Two is refused -- which is precisely the invariant that
matching session phase, active draw and exhaustion must not overturn
contradictions in both regime and direction.

| Probe | Contradictions | Outcome |
|---|---|---|
| exact state | none | kept, 1.0000 |
| one contextual diff | none | kept, 0.9518 |
| two contextual diffs | none | kept, 0.9036 |
| same direction, different delivery | delivery | kept, 0.8662 |
| opposite direction only | direction | kept, 0.8662 |
| opposite regime only | regime | kept, 0.8662 |
| **opposite direction + opposite regime** | regime, direction | **EXCLUDED** |
| **dual contradiction, all context agrees** | regime, direction | **EXCLUDED** |

## 36. Query-completeness law

An unstated block contributes nothing to the numerator **and** nothing to `|q|`,
so an underspecified query scores *higher*. That is what moved the v2
bullish-expansion score between 0.465 and 0.587 depending on how much of the
state the query bothered to state.

```
MANDATORY_QUERY_BLOCKS = market_regime, volatility_state,
                         direction_distribution, delivery_state,
                         liquidity_state
```

| | |
|---|---|
| Missing a mandatory block | **query REFUSED**, `INCOMPLETE_QUERY_MISSING_MANDATORY_BLOCKS` |
| Missing an optional block | completeness factor multiplied into the score, reported |
| Completeness score | `(sum w^2 over stated blocks) / (sum w^2 over all)` |
| Telemetry | `completeness`, `incomplete_query`, `missing_mandatory_blocks` |

Refusal is the only treatment that cannot be gamed by asking less.

## 37. Threshold re-derivation

With the gate active, the threshold no longer has to separate "contradicts the
question" from "resembles it" -- a job no threshold could do. Its only remaining
job is suppressing weak non-contradicting matches.

| | |
|---|---|
| Strongest surviving invalid match | **none** -- all removed by the gate |
| Weakest legitimate August 6 analog | **0.7194** (neutral lunch, #7) |
| Weakest synthetic non-contradicting probe | **0.8662** |
| Returned counts at 0.40 / 0.50 / 0.60 / 0.70 | **identical for every query** |

The choice is insensitive across `[0.40, 0.70]`, so it was taken from inside
that flat band rather than fitted to a record: **0.5 -> 0.60**, leaving ~0.12
headroom under the weakest observed legitimate match. At 0.80 the neutral-lunch
analogs start dropping, which is the upper edge.

## 38. Sensitivity

Gate decisions and returned sets are **identical** at load = 1.15, 1.25 and
1.35. Scores move by at most 0.005. No invariant flips.

## 39. August 6 rerun -- `descriptive.embedding.v2.1`

`DRY_RUN_ONLY`, proposals in
`analysis/proposed_descriptive_memory_v2_1/` (git-ignored). v1 and equal-weight
v2 proposals untouched beside it. Live store unchanged at 0 records / 0 bytes.

172 scans read, 167 eligible, tier T0, 66 raw runs, **10 segments** --
segmentation was not touched and did not change. **No duplicate vectors.** One
pair above 0.90: #4-#6 at **0.9749**.

| Query | Gated | Returned | Top | Selected |
|---|---|---|---|---|
| 1 bullish expansion | 10 | **0** | -- | none |
| 2 bearish delivery | 10 | **0** | -- | none |
| 3 conflicted rotation | 5 | 2 | 0.9991 | #4, #6 |
| 4 neutral lunch | 8 | 2 | 0.7312 | #8, #7 |
| 5 exhaustion | 5 | 2 | 0.9999 | **#3 11:05-11:30** |
| 6 volatility expansion | 10 | **0** | -- | none |

Incomplete forms of queries 1, 3 and 5 were all **REFUSED** with the missing
mandatory block named.

**Does bearish delivery still return segment #1?** No. Under v2 it returned #1
at 0.5129 despite #1 reading *conflicted* in a *range rotation*. It is now
excluded on `['market_regime', 'direction_distribution']` with a direction
agreement of **0.000**. The exclusion is semantic, not a score.

**Does an incomplete bullish-expansion query still reach 0.587?** No. It cannot
be asked -- regime and direction are mandatory. The complete form is gated on
regime + volatility + direction against all ten records.

## 40. Phase 13 -- recurrence observation, not acted on

#4 and #6 still occupy both same-session slots. They now score **0.9749** and
differ in exactly two blocks: `structure_evidence` (bos=1 vs quiet) and
`confidence` -- one contextual, one diagnostic. Their contradiction report is
**empty**: they agree on every load-bearing block.

Classification: **SEMANTIC_RECURRENCE_POLICY_REVIEW_REQUIRED.**

They are not merged, because the recurrence policy is explicitly out of scope
for this mission and because they *are* distinct chronological observations of a
state the market left and returned to. But a 0.975 pair separated only by a
witness-tier flag is, for retrieval purposes, arguably one observation. That is
a policy question -- semantic recurrence versus exact-vector recurrence -- and
it deserves its own bounded mission rather than a judgement call here.

## 41. Authority boundary -- unchanged

Weighting and gating change **which** records are selected and **in what order**.
They touch nothing else. Every returned analog still carries
`authority: CONTEXT_ONLY`, `outcome_validated: false`,
`recommendation_authority: none`, `execution_authority: none`. The record schema
still contains no risk, sizing, reward-to-risk, invalidation or objective field,
and no module on the execution path imports the weight map -- asserted
statically over `luna_candidate_producer`, `topstepx_execution_runner` and
`topstepx_production_loop`.

## 42. Contract identities

| | Before | After |
|---|---|---|
| Embedding version | `descriptive.embedding.v2` | **`descriptive.embedding.v2.1`** |
| Manifest | `emb:0110829ec9b77839` | **`emb:6c2305128fcfd4c5`** |
| Retrieval contract | `retr:a325e314e4098956` | **`retr:4f47a37e8725b17f`** |
| Brain contract | `brain:6118d5eedf9fca60` | **`brain:8ced919ee82fba0a`** |
| Threshold | 0.50 | **0.60** |

**No replacement authorization was issued.**

## 43. Remaining limitations

**Single-contradiction records remain retrievable at ~0.87.** A record
disagreeing on regime alone, or on direction alone, still returns. That is
deliberate -- constraint 6 requires a near-neighbour disagreeing on one field to
stay retrievable -- but it means a "conflicted lunch" query can surface a
"neutral lunch" segment. The analog carries its real direction, so the Brain can
see the disagreement.

**The gate is categorical for four blocks and distributional for one.** Volatility
`toxic` vs `explosive` counts as a full contradiction even though they are
adjacent on a severity ladder. An ordered-vocabulary distance would be more
faithful, and would need its own mission.

**Every probe is synthetic or from one session.** PROD-20260806 is still the only
identity-clean completed MNQ session. The synthetic probes test representation
geometry; they are not historical market observations, and they are labelled as
such wherever they appear.

---

# PART IV -- Semantic recurrence collapse

**Mission:** REFINE-SEMANTIC-RECURRENCE-COLLAPSE
**Date:** 2026-08-06
**HEAD in:** `8e2680a`

## 44. Exact-vector recurrence versus semantic recurrence

The v2 rule grouped two records only when their **feature vectors were
byte-identical**. That is too narrow. August 6 segments #4 and #6:

| | #4 | #6 |
|---|---|---|
| Every load-bearing block | identical | identical |
| Session phase / narrative phase | lunch / transition | lunch / transition |
| Direction distribution | conflicted 1.00 | conflicted 1.00 |
| Structure witness | bos=1 | quiet |
| Confidence mean | 67.73 | 73.69 |
| Cosine | **0.9749** | |

They differ only in a **contextual** block and a **diagnostic** one, so their
vectors are not identical, exact-vector collapse never fired, and the two
consumed **both** of the session's allowed retrieval slots. A future Terra query
would have received one quiet Thursday as two independent precedents -- the
exact self-confirmation this memory class exists to prevent.

**Recurrence is now decided on semantic fields, never on cosine.** A high
similarity score is not evidence that two observations are the same observation:
two records can score 0.97 while disagreeing on delivery, and delivery is
load-bearing.

## 45. The matching law

**Must match exactly -- identity**
`session_id`, `instrument`, `contract`, `memory_type`, `authority`,
`outcome_validated`, `embedding_version`, `embedding_manifest_fingerprint`.

**Must match exactly -- load-bearing market state**
`market_regime`, `volatility_state`, `delivery_state`, `liquidity_state`,
`active_draw_present`, plus protected-high and protected-low **presence** (the
level itself is contract-scoped and never a grouping feature).

**Must match exactly -- contextual, in this first implementation**
`session_phase`, `narrative_phase`. Doctrine does not yet establish that a lunch
observation and a morning one are the same observation, so the conservative
choice is to keep them apart. August 6 shows this is the operative constraint:
**segment #3 agrees with #4/#6 on every load-bearing field and on direction**,
and is held out only by session phase and narrative phase -- correctly, since #3
is the exhaustion segment.

**Direction distribution -- tolerance**
`DIRECTION_COMPONENT_TOLERANCE = 0.10`, applied by **quantising** each
proportion into buckets of that width. Quantisation is deterministic and
order-independent; a pairwise-tolerance rule would chain transitively and could
group two records further apart than the tolerance allows. It is conservative in
the other direction: two records within tolerance that straddle a bucket edge
simply do not group.

**Permitted differences inside a group -- contextual**
`structure_evidence`, `structure_state`, `exhaustion_present`. Reported on the
analog as `contextual_differences`.

**Permitted differences inside a group -- diagnostic**
`phase_confidence_summary`. Confidence must never *prevent* two identical market
observations from being recognised as the same observation, and must never
*decide* which one represents the group.

## 46. Prohibited grouping

A group never forms across a difference in: instrument, contract, source
session, market regime, volatility, delivery, liquidity, active draw, protected
presence, a materially different direction distribution, embedding version,
manifest identity, authority label, or outcome-validation state. A record whose
key cannot be built (missing or unsupported direction vocabulary) never groups --
unknown identity is not sameness.

**Records from different sessions never collapse**, even when semantically
identical. The same state on another day is independent evidence, and that is
the whole point of a corpus.

Fourteen negative probes and four positive probes were run; all held.

## 47. Retrieval-only, and where it sits in the pipeline

```
identity filter -> version filter -> expiry filter -> CONTRADICTION GATE
   -> similarity -> threshold -> rank
   -> SEMANTIC RECURRENCE COLLAPSE
   -> per-session cap -> top-k
```

Collapsing after top-k would already have spent the slots; capping before
collapse would drop occurrences that were about to merge anyway. Gating before
collapse guarantees a contradicting record can never appear inside a group.

**All records remain individually in JSONL.** Collapse is a presentation rule,
not a deletion.

## 48. Representative law and metadata

```
similarity desc -> scan_count desc -> segment_duration desc
                -> segment_start asc -> memory_id asc
```

Similarity leads so the group is represented by its most query-relevant
occurrence. **Confidence is not a criterion.** It still sits in the vector at
diagnostic weight 0.50 and can therefore move similarity -- what it may never be
is a rule in the ordering.

Every returned group exposes: `recurrence_type`
(`exact_same_session` / `semantic_same_session`), `recurrence_count`,
`occurrence_spans`, `grouped_memory_ids`, `member_similarities`,
`representative_memory_id`, `contextual_differences`, `diagnostic_differences`.

## 49. August 6 result

Exactly **one** group forms across the ten records: **{#4, #6}**. Everything else
is a singleton. #5 cannot join -- its delivery is `mixed`, not
`accumulation_building`.

Conflicted-rotation query, before and after:

| | v2.1 (before) | v2.1 + semantic collapse |
|---|---|---|
| Slot 1 | #4 (0.9991) | **#4, representing {#4, #6}** (0.9991) |
| Slot 2 | #6 (0.9739) -- the same state again | **#3** (0.8988) -- a genuinely distinct state |

The group reports its real differences: structure evidence
`bos=1 / quiet` and confidence mean `67.73 / 73.69`.

| Query | Gate exclusions | Semantic groups | Returned | Top |
|---|---|---|---|---|
| conflicted rotation | 5 | {#4,#6} rep #4 | 2 (#4-group, #3) | 0.9991 |
| neutral lunch | 8 | none | 2 (#8, #7) | 0.8712 |
| exhaustion | 5 | {#4,#6} rep #4 | 2 (**#3**, #4-group) | 0.9999 |
| bullish expansion | 10 | none | **0** | -- |
| bearish delivery | 10 | none | **0** | -- |
| volatility expansion | 10 | none | **0** | -- |

Caps unchanged: `MAX_ANALOGS = 5`, `MAX_ANALOGS_PER_SOURCE_SESSION = 2`,
`MIN_SIMILARITY = 0.60`.

## 50. A second defect found and fixed

`structure_state` (display) was the **mode** of the per-scan witness labels while
`structure_evidence` (embedded, and what the vector reads) was the segment
**mean**. The two disagreed: August 6 records #3 and #4 both displayed
`witness_quiet` while carrying `bos_count = 1`.

Two fields describing the same underlying witness must not be able to disagree,
so the display string is now derived from the same evidence the vector reads.
`structure_state` appears in no signature tier, so segmentation is unaffected --
still 10 segments, verified.

## 51. Contract identities

| | Before | After |
|---|---|---|
| Embedding version | `descriptive.embedding.v2.1` | unchanged (geometry untouched) |
| Manifest | `emb:6c2305128fcfd4c5` | unchanged |
| Retrieval contract | `retr:4f47a37e8725b17f` | **`retr:d850b777e73c7d08`** |
| Brain contract | `brain:8ced919ee82fba0a` | **`brain:cf9d16baeb09cc23`** |

The manifest is unchanged because the vector space did not move -- only the
policy that reads it. The retrieval contract and therefore the Brain contract
did change, because retrieval now presents different analogs.

**No replacement authorization was issued.**


## 52. Policy repair -- representative selection is confidence-free

The law in section 48 said **confidence is not a criterion**, and the ordering
began with full-vector cosine while the confidence block sat in that vector at
diagnostic weight 0.50. Confidence could therefore decide the representative
indirectly. A failing test caught it; the assertion was rewritten around the
contradiction rather than the contradiction removed. That was wrong, and it is
now fixed properly.

**Ordinary retrieval similarity is unchanged** -- it keeps using the complete
weighted v2.1 vector, because diagnostic confidence may modestly influence
general analog ranking.

**Representative selection alone** runs on `representative_projection()`: the
stored vector with every group named in `REPRESENTATIVE_EXCLUDED_GROUPS`
(currently `("confidence",)`) zeroed on **both** sides, so no confidence value
reaches the numerator or either norm. Indices are resolved from the manifest by
group name, never hardcoded -- asserted by a test that parses the function and
fails on any integer literal. Nothing is mutated and no second vector space is
persisted.

```
representative similarity desc  (confidence excluded)
  -> scan_count desc -> duration desc -> segment_start asc -> memory_id asc
```

Every group reports `member_similarities` (full retrieval) **and**
`member_representative_similarities` (confidence-free), so the choice is
auditable.

**Effect on August 6.** For a quiet-structure query the representative of
{#4, #6} is now **#6** -- an exact structural match at representative similarity
**1.0000**, against #4's 0.9747. For a bos=1 query it is **#4**. The group
membership is identical in both cases; only its spokesman moves, and it moves
with market evidence rather than with a confidence number. Perturbing one
member's confidence by 35 points does not move it at all.

| | Before | After |
|---|---|---|
| Retrieval contract | `retr:d850b777e73c7d08` | **`retr:a1adff81501bb186`** |
| Brain contract | `brain:cf9d16baeb09cc23` | **`brain:0212947f0133fc76`** |
| Manifest | `emb:6c2305128fcfd4c5` | unchanged -- geometry untouched |


## 53. Retrieval enablement is explicit, never inferred

**ENFORCE-MEMORY-RETRIEVAL-ENABLEMENT-AUTHORITY (2026-08-07).**

The ten August 6 records were authored, verified and committed. The next morning
at 08:21 ET, before the window opened, `AI_RETRIEVAL_ENABLED` was found **absent
from `.env`**. `retrieve_for_snapshot` short-circuits on that flag before
touching the store, so the first memory-enabled session would have run
memory-blind: ten records on disk, zero reaching Terra, and every other
telemetry line -- record count, authority, retention, manifest -- reading
healthy.

That is the silent-degradation class this system keeps re-encountering: the
retired data-provider fallback, the smoke-cap leak, the unset JSON-mode flag.
Setting the variable would have made one day work while preserving the failure
mode for every day after.

### The law

```
NON-EMPTY DESCRIPTIVE CORPUS + RETRIEVAL DISABLED = ARMED STARTUP REFUSED
```

Refusal reason: `MEMORY_PRESENT_BUT_RETRIEVAL_DISABLED`, raised before execution
arming, authorization consumption, order submission or the scan loop. Disarmed
diagnostics still run -- you must be able to inspect a blind system without
arming it.

**Retrieval is never inferred from the corpus being non-empty.** It is stated.
Absence, blank and every unrecognised value resolve to DISABLED.

### One resolver

`ai_retrieval.retrieval.retrieval_enabled()` is the single parser, sharing the
sanctioned truthy set `("on", "true", "1", "yes")` with the Brain's JSON-mode
predicate. The original check accepted only the literal `"true"`, so
`AI_RETRIEVAL_ENABLED=on` would have read enabled to an operator and disabled to
the runtime. A test fails if any second module parses the variable.

`retrieval_startup_state()` returns `ready` / `empty-allowed` /
`MEMORY_PRESENT_BUT_RETRIEVAL_DISABLED`, and the launcher prints
`AI RETRIEVAL` and `MEMORY STARTUP STATE` alongside the record counts.

### Authorization binding

`SessionAuthorization.retrieval_enabled` is recorded at issue, folded into the
authorization fingerprint, and compared against the runtime resolver by
`verify()`.

| Authorization | Runtime | Result |
|---|---|---|
| true | true | valid |
| true | false | `AUTHORIZATION_RETRIEVAL_STATE_MISMATCH` |
| false | true | `AUTHORIZATION_RETRIEVAL_STATE_MISMATCH` |
| legacy (field absent) | any | reads `False`, fails closed, no `TypeError` |

### Why NOT the Brain-contract fingerprint

The expectation was that retrieval enablement should also enter
`brain_contract_fingerprint()`. It should not, and the distinction is worth
stating.

That fingerprint identifies **code and policy**: the prompt, schema and
validator sources, plus the resolved retrieval *policy* (threshold, weights,
manifest, recurrence law, caps). All of it is environment-independent. Folding a
per-session runtime toggle into it would mean:

* the same code produces two different Brain-contract identities depending on an
  ambient environment variable;
* a disarmed diagnostic (flag off) no longer shares a contract identity with the
  armed run it exists to inspect;
* every authorization is invalidated by a toggle, including authorizations for
  legitimately memory-disabled sessions;
* the refusal surfaces as `AUTHORIZATION_BRAIN_CONTRACT_CHANGED` -- a misleading
  reason, when a precise one now exists.

The requirement -- *an authorization created for a memory-enabled Brain cannot
validate under a memory-disabled runtime* -- is met exactly by the authorization
field, with the correct reason. The binding chain:

```
AI_RETRIEVAL_ENABLED (env)
  -> retrieval_enabled()                    [one resolver]
       -> retrieval_startup_state()         -> armed startup refusal      (gate 1)
       -> SessionAuthorization.retrieval_enabled  [recorded at issue]
            -> fingerprint()                [tamper-evident]
            -> verify()                     -> RETRIEVAL_STATE_MISMATCH   (gate 2)
```

Two independent gates. Retrieval **policy** stays bound to the Brain contract,
because that is code.

### Residual gap, stated

Both gates fire at startup. A flag flipped *mid-session* would silently empty
retrieval without tripping either, because `retrieve_for_snapshot` re-reads the
environment per scan and is observe-only by contract. Per-scan retrieval
telemetry would surface it; that is a separate bounded mission and is not
claimed here.

### Verification tool

`tools/verify_retrieval_enablement.py` -- read-only, calls the same hook the
scan loop calls against the live corpus, and asserts non-vacuously that
`enabled is True` and `corpus_size` matches the store. It lives in `tools/`
deliberately: `load_dotenv()` resolves `.env` by walking up from the *calling
file*, so a probe written outside the repository loads no environment at all and
then reports "disabled" for the wrong reason. That happened during this mission
and produced a green result on an empty list before it was caught.


## 54. Per-scan retrieval telemetry

**ADD-PER-SCAN-MEMORY-RETRIEVAL-TELEMETRY (2026-08-07).**

Memory that works but cannot be audited teaches nothing. After a session we must
be able to answer, from machine-countable evidence rather than prose: was
retrieval enabled on this scan, did the hook touch the corpus, what was excluded
and why, which analogs reached Terra, from which sessions, did recurrence
collapse anything, did the per-session cap fire.

### Two live defects found while tracing the call path

`narrative_brain` re-queried retrieval whenever the scan's result carried no
analogs:

```python
if not retr.get("analogs"):
    retr = retrieve_analogs(snapshot, k=5, authoritative_only=True,
                            min_similarity=0.0, persist_log=False)
```

* **Threshold bypass.** `min_similarity=0.0` ignored the bound
  `MIN_SIMILARITY` (0.60). Terra could be shown analogs the retrieval contract
  had already rejected.
* **Enablement bypass.** `retrieve_analogs` has no enablement gate of its own --
  only `retrieve_for_snapshot` checks `AI_RETRIEVAL_ENABLED`. So this second
  call read the corpus even with retrieval switched off. Yesterday's
  "memory-blind" conclusion was therefore incomplete: the corpus was empty then,
  so nothing surfaced, but from today it would have.

Both are closed by the law this mission needed anyway:

```
ONE SCAN -> ONE RETRIEVAL RESULT -> Brain payload AND telemetry
```

The caller owns retrieval; the Brain consumes what it is given. Recomputing for
telemetry would double the work and could produce evidence describing a
different query than the one Terra actually saw.

### Schema `memory_retrieval_telemetry.v1`

Per scan: identity (`session_id`, `scan_id`, ET timestamp, instrument,
contract), `retrieval_enabled`, `startup_memory_state`, query completeness and
missing mandatory blocks, corpus size, the stage counters below, contradiction
reason counts, recurrence groups, session-cap exclusions, the bound policy
values in force, safe analog metadata, `retrieval_error` and
`retrieval_duration_ms`.

Never logged: credentials, account id, complete fingerprints, authorization
fingerprint, raw prompt, raw model response, or prices when levels are withheld.
Memory ids appear as 8-character suffixes.

### Stage accounting

A record has exactly one terminal state, and the states sum to the corpus:

```
QUERY_INCOMPLETE + IDENTITY_REJECTED + VERSION_REJECTED + EXPIRED
  + CONTRADICTION_GATED + BELOW_THRESHOLD + RECURRENCE_COLLAPSED
  + SESSION_CAP_EXCLUDED + RETURNED  ==  CORPUS
```

`stage_accounting_reconciles` is asserted per scan. Two subtleties are modelled
explicitly rather than glossed:

* **Recurrence members are not exclusions.** They were eligible and merged into
  a representative, so they are counted as grouped observations.
* **A refused query never stages the corpus**, so every record's terminal state
  is `QUERY_INCOMPLETE`. Without that term a correctly refused scan reported a
  phantom mismatch.

### Contradiction reasons

`contradiction_gated_count` counts **records**; `contradiction_reason_counts`
counts **occurrences**, which is larger when one record contradicts on several
blocks. On the August 6 corpus a bullish-expansion query gates 10 records with
36 reason occurrences. Presenting occurrences as record totals would overstate
the corpus by more than 3x.

### Per-scan enablement and mid-session transitions

Every scan records the resolved retrieval state, and a change from the previous
scan emits `retrieval_state_transition: enabled_to_disabled` or
`disabled_to_enabled`. That closes the residual gap left by the enablement
mission: both of its gates fire at startup only, so a flag flipped mid-session
was previously invisible. It is now visible on the very next scan. This mission
is observability -- it does not stop or mutate a live session.

### Storage

`data/replay_sessions/<SESSION_ID>/memory_retrieval/retrieval_scans.jsonl`,
append-only, newline-delimited, inside the normal session archive root.

**Telemetry is evidence, not memory.** It is never written to
`data/ai_retrieval/memory_store.jsonl` and can never become retrievable
historical context.

**A write failure degrades observability, not safety.** Telemetry is not
execution authority, and refusing to trade because a log file could not be
opened would convert a reporting fault into a trading fault. The failure is
returned as `RETRIEVAL_TELEMETRY_WRITE_FAILED`, flagged per scan, and raised to
`degraded_observability: true` in the session summary -- never swallowed.

### Session summary

Machine-countable at session end: total scans, enabled/disabled scans, state
transitions, scans with and without analogs, incomplete-query scans, retrieval
errors, total analog presentations, unique memory ids, unique source sessions,
recurrence groups and collapsed members, contradiction-gated records and reason
counts, session-cap exclusions, levels-withheld presentations, authority values
seen.

### Linkage

`snapshot["memory_retrieval_telemetry_id"]` ties the Brain artifact to the exact
retrieval record that fed it, so an audit can trace Brain output -> telemetry ->
historical analog ids.

### August 6 corpus simulation

| Query | Gated (records / reason occurrences) | Recurrence | Cap | Returned | Reconciles |
|---|---|---|---|---|---|
| conflicted rotation | 5 / 12 | 1 semantic group | 2 | 2 | yes |
| exhaustion | 5 / 12 | 1 semantic group | 2 | 2 | yes |
| bullish expansion | 10 / 36 | -- | 0 | 0 | yes |
| incomplete query | 0 / 0 | -- | 0 | 0 | yes (all `QUERY_INCOMPLETE`) |

---

# Part V — Session closure, identity recovery and authoring projections

*(SUPPORT-OPERATOR-TERMINATED-SESSION-CLOSURE / BUILD-VERIFIED-MEMORY-AUTHORING-PROJECTION, 2026-08-07)*

## 55. Two ways a session may legitimately end

The original law demanded four launcher artifacts **by name**. That conflated
evidence with filenames. PROD-20260807 was stopped by the operator at 13:11 ET
with its stdout buffered to nothing, so it wrote none of them — and a session
whose end state was entirely knowable became unauthorable for a filing reason.
The alternative, inventing the four files, would have put a forged launcher exit
into the evidence chain. Neither is acceptable.

An operator stopping the bot is a normal lifecycle event, not an anomaly.

| Class | Evidence |
|---|---|
| `NATIVE_LAUNCHER_CLOSE` | artifacts the launcher wrote as it exited — **path unchanged** |
| `OPERATOR_TERMINATED_CLOSE` | a post-session attestation built from durable independent evidence |

The classes never substitute silently. An attestation is consulted **only** when
the native artifacts are absent, and one that claims `NATIVE_LAUNCHER_CLOSE` is
rejected outright: only a launcher can evidence its own exit, and a launcher
does not write attestations.

## 56. The invariants, not the filenames

Eight load-bearing invariants, all required in both classes:

`observation_ended` · `observation_end_known` · `final_positions_known` ·
`final_working_orders_known` · `execution_context_resolved` ·
`execution_accounting_consistent` · `termination_reason_known` ·
`source_evidence_durable`

Each fact carries its provenance: `FACT_OBSERVED_LIVE`,
`FACT_VERIFIED_AFTER_TERMINATION` or `FACT_UNAVAILABLE`. A fact whose provenance
is `UNAVAILABLE` is `UNPROVEN` **however confidently it is asserted**, and any
unproven load-bearing invariant returns
`OPERATOR_TERMINATED_CLOSURE_INSUFFICIENT`. The attestation cannot lower the
bar; it can only meet it by a different route.

`session_closure_attestation.v1` must not be backdated: an attestation stamped
before the session end it describes, or in the future, is rejected.

## 57. Session-level contract identity recovery

PROD-20260807 recorded **no per-scan contract** — the same ProductionLoop defect
that left telemetry under `UNSCOPED`. Recovery requires:

- at least one **authoritative session-bound** source, and
- **no contradictory** contract evidence.

Two distinct contracts refuse rather than pick one. When recovery succeeds the
record says so explicitly and never claims the value was original:

```
contract_identity_provenance : RECOVERED_SESSION_LEVEL
per_scan_contract_original   : ABSENT
identity_recovery_sources    : [session authorization record]
```

The alternative mode is `ORIGINAL_PER_SCAN`. Provenance is emitted for native
closes too, deliberately — "no deviation" must never have to be inferred from
silence.

## 58. Partial observation is not observed absence

A session stopped at 13:11 saw nothing afterwards. That is **not** evidence that
nothing happened afterwards. Every record from a partially observed session
carries:

```
source_session_completion    : OPERATOR_TERMINATED
observation_window_start_et  : 09:30:51
observation_window_end_et    : 13:11:17
configured_window_completed  : false
partial_observation_claim    : NO OBSERVATION AFTER observation_window_end_et.
                               This is NOT a claim that no opportunities
                               existed after that time.
```

Without this, a reader seeing no afternoon records would read them as an
observed absence of afternoon setups.

## 59. Verified authoring projections

A sealed archive stores one file per scan; the authoring pipeline reads three
parallel trees plus an index. Reshaping that in a scratchpad is exactly what
must never become the authoring path — a scratchpad has no provenance, so
nothing stops an undocumented semantic edit from entering memory.

`memory_authoring_projection_manifest.v1` records, for every projected file, its
`source_archive_path`, `source_sha256`, `projected_sha256` and which of **four**
operations produced it:

`COPY_BYTE_IDENTICAL` · `NORMALIZE_LAYOUT_ONLY` · `DERIVE_INDEX` ·
`RECOVER_SESSION_METADATA`

There is no fifth. Anything needing one is a semantic transformation and does
not belong in a projection.

Authoring accepts a `NATIVE_SESSION_LAYOUT` or a
`VERIFIED_AUTHORING_PROJECTION` — never an arbitrary directory — and fails
closed on: unverified projection, mismatched archive hash, session mismatch,
runtime identity mismatch, missing closure evidence, unproven contract identity,
an undocumented operation, or any altered projected file.

## 60. Two pre-existing defects found while proving this

Recorded rather than quietly tolerated; both are asserted by tests so they
cannot rot unnoticed.

**Live memory ids predate the v2.2 migration.** `memory_id` hashes the schema
version. The migration set `schema_version` to `descriptive.v2.2` on every
record but preserved ids derived under `descriptive.v2.1`, so a live record
cannot reproduce its own id — and re-authoring August 6 would append ten
duplicates instead of colliding with itself as the doctrine intends. Fixing it
means deciding whether to re-id the corpus or drop the schema version from the
identity. **Operator's call.**

**Re-authoring stamps today's Brain contract.** `build_records` reads the
fingerprint from the *current* production model, so re-authoring a historical
session labels it with the wrong contract. August 6 records carry `33fc76`;
re-authoring today produces `2ec41c`.

---

> **Correction to §54 (v2.1 → v2.2 migration):** that migration was
> INCOMPLETE. It updated `schema_version` while preserving ids derived under
> the old one, leaving every record unable to reproduce its own identity. See
> §62.

# Part VI — Memory identity and historical contract provenance

*(REPAIR-V2_2-DESCRIPTIVE-MEMORY-IDENTITY / BIND-HISTORICAL-BRAIN-CONTRACT-PROVENANCE, 2026-08-07)*

## 61. The memory-id reproducibility law

> **Every stored record must reproduce its own `memory_id` from its own current
> fields.** A record that cannot is not identifiable; it is merely labelled.

Identity fields: `schema_version`, `session_id`, `instrument`, `contract`,
`segment_start`, `segment_end`, `source_artifact_digest`.

Market semantics, the embedding version and the Brain contract are **excluded**
— deliberately. A *different reading* of the same segment must collide with the
first so it surfaces as a conflict, instead of quietly appending a second
version of the same moment.

`schema_version` **remains identity-bearing.** It was not removed to make a
migration convenient.

## 62. Representation migrations must re-derive ids

The v2.1 → v2.2 migration (§54) re-embedded all ten records and set
`schema_version` to `descriptive.v2.2` — but carried the old ids across
unchanged. **That migration was incomplete.** Because `memory_id` hashes the
schema version, all ten stored ids became underivable, and the collision that
makes re-authoring safe could no longer happen: re-authoring PROD-20260806 minted
ten fresh ids and would have appended ten duplicates of observations already
held.

Corrected by re-deriving the ids. Ledger:
`data/replay_sessions/_migrations/descriptive.v2.2-memory-id-repair/mapping.json`
(mapping sha `7333998ea5008e4c…945e3946`), 10 → 10, 0 collisions, 0 semantic
changes, 0 vector changes.

**Law:** any migration that changes an identity-bearing field must re-derive
`memory_id` in the same operation, and record old → new in a durable ledger.
Historical session artifacts are **not** rewritten — a runtime record that named
an old id keeps naming it, and the ledger resolves it forward.

## 63. Who reasoned vs what represented it

`build_records` stamped `brain_contract_fingerprint()` — the contract of the
**authoring** code — into `brain_contract_fingerprint_suffix`. Re-authoring a
historical session therefore relabelled it with today's contract.
PROD-20260806 ran `gpt-5.6-luna`, yet its records carried `33fc76`, a Terra-era
value present only because that was current when they were written.

Two facts had been collapsed into one field. They are now separate, and the
second can never impersonate the first:

| Field | Meaning | Source |
|---|---|---|
| `source_brain_contract_fingerprint` | contract that produced the historical reasoning | session evidence **only** |
| `source_runtime_head` | commit that ran | session archive |
| `authoring_contract_fingerprint` | implementation that built the representation | current code, **labelled** |

Resolution order for the source contract: archived Brain artifact → session
authorization record → `UNRECORDED_AT_RUNTIME`. **Never current code.**

| Session | Source contract | Evidence |
|---|---|---|
| PROD-20260806 | `UNRECORDED_AT_RUNTIME` (head `7253640`) | `UNRECOVERABLE_FROM_EVIDENCE` |
| PROD-20260807 | `brain:0212947f0133fc76` | session authorization record |

August 6 predates the field entirely. Saying so beats guessing — and the runtime
commit pins the contract sources exactly even though the digest was never stored.

Ledger:
`data/replay_sessions/_migrations/historical-brain-contract-provenance/mapping.json`.
10 records, 0 semantic drift, 10 contract stamps corrected.

**Changing authoring code does not rewrite who produced historical reasoning.**
