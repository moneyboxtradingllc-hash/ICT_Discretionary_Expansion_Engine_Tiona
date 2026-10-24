# CISD causal contract: PROPOSAL (authority DISABLED)

Base `f6e4013646e9d139a9fe71586ea4e60391e06c61`. Prepared offline under Maurice's 2026-10-24 delegation. There were no
model, provider or venue calls and no production source change.

| Item | Status |
|---|---|
| CISD fact definition, identity, availability (`cisd_shadow.py`) | PROPOSED; policy-independent tests pass |
| CISD as Brain evidence vs. independent transfer proof (O1) | **OWNER DECISION, UNANSWERED: UNPROVEN** |
| Any CISD authority route | **DISABLED**. No production module imports the shadow, and `_authoritative_opposing_origin` still accepts only `rejected_raid_reclaim` (asserted by test) |
| Recognition certification of the owner chart | **UNPROVEN** |
| D3=B/STRICT/INDEPENDENT_SUPPORTING_LIFE, roles 5m/15m, K=1, D0=a, D4=a | Unchanged, asserted by test |

## 1. Fact (what the shadow computes, nothing more)

Bearish CISD on timeframe T is defined as follows (the bullish case mirrors it):

1. **Settled buckets.** A T-bucket exists only when all of its constituent 1m bars are present and
   `open_time + T <= settled_through`. Production's scan cutoff is the opening time of the last 1m bar, so
   `settled_through = cutoff + 1m`. If any bar is malformed, duplicated, naive-time, bool-valued or non-finite, the
   whole request is refused.
2. **Selected extreme.** The caller names the bucket that printed the extreme high (`extreme_at`). That bucket must be
   settled, and its high must be the maximum over the run through that bucket. Which extreme gets selected is O2.
3. **Delivery run.** Take the maximal run of contiguous bullish-delivery buckets (close > open) ending at the last such
   bucket at or before the extreme. The anchor is the run's first open. A doji ends the run by default (O4).
4. **Break.** The break is the first later settled bucket whose close is strictly below the anchor (`STRICT`; O4 allows
   `INCLUSIVE`).
5. **Supersession.** If a later bucket prints above the extreme before any break, the status is `SUPERSEDED`. If
   there is a gap in the scanned range, the status is `UNAVAILABLE/tape_gap`: the validator never reads across a hole.
6. **Identity and clock.**
   - `occurrence_id = cisd_body_open_break:<contract>:<T>:<direction>:<run first open time>:<anchor>:<break bucket open time>`.
   - `available_at = break bucket open + T`.
   - Once `CONFIRMED`, the result is immutable at every later cutoff.

The result depends only on its arguments, and bars at or after `settled_through` are ignored. So continuous
evaluation, prefix replay and a cold restart all give the same identity. The test checks every minute from 12:05 to
13:15 ET, with shuffled input order.

## 2. Archived trace (2026-10-23 December-contract tape; facts, not recognition)

| 5m bucket (ET) | O | H | L | C | Delivery |
|---|---|---|---|---|---|
| 11:45 | 29231.75 | 29271.00 | 29217.00 | 29271.00 | bullish (run start, anchor) |
| 11:50 | 29270.25 | 29285.50 | 29260.50 | 29273.75 | bullish |
| 11:55 | 29273.75 | 29298.00 | 29256.75 | 29293.50 | bullish (run end) |
| 12:00 | 29293.50 | 29306.00 | 29277.75 | 29290.00 | bearish (extreme 29306) |
| 12:05–12:15 | | | | 29284.25 / 29245.50 / 29242.50 | bearish, all closes above anchor |
| **12:20** | 29241.75 | 29249.50 | 29204.00 | **29215.25** | **first close below 29231.75; available 12:25** |

The shadow returns `CONFIRMED` at 12:25 ET and `PENDING` at 12:24. The 29231.75 anchor is consistent with the chart's
blue line (about 29232). That this anchor is the owner's rule is an inference, not a machine-readable annotation.

How this relates to the recorded mechanics (retained occurrences):

- Rejected buy-side raids of the 5m/3m 29294.5 high ran from 11:55 to 12:10 ET.
- A 1m bearish structure break printed at 12:13.
- From 12:17 to 12:21, the bearish displacement itself swept and reclaimed successive 1m/3m lows: below_low at
  29250.75, 29238.0, 29234.25 and 29218.75. A 1m protected low was violated at 12:20.
- ActivePath lets the latest raid replace an unconfirmed hypothesis (`_apply` step 1). So at 12:24 it publishes owner
  `none` with a forming **bullish** hypothesis, as Codex recorded.

Under the existing proof family, a bearish delivery change that takes out sell-side liquidity on the way down therefore
cannot become a bearish origin. That is the precise mechanical boundary. Whether to change it is O1/O5, not an
engineering defect.

## 3. Source mapping (where each consumer sits today, and what O1 would touch)

| Concern | Current code at f6e4013 | Under O1=a (evidence only) | Under O1=b (transfer route) |
|---|---|---|---|
| Settled tape | `production_scan_cycle._producer_prefix` / `build_timeframes`; `settled_source` provenance | Read-only; CISD computed from the same settled series | Same |
| Origin family | `active_path.ActivePath._apply` (raid opens a hypothesis); `state()["origin"]["proof_family"]` | Unchanged | New origin event type plus plumbing in `_apply`/`extract_occurrences`; ledger identity v1/v2 rules |
| Family gate | `narrative_continuity._authoritative_opposing_origin` (only `rejected_raid_reclaim`) | Unchanged | Register the family. This is a Brain-closure file, so the fingerprint changes and a fresh authorization is required |
| Transfer proof | `narrative_continuity._transfer_proof`: died_at < origin_at, opposing active owner, progression, intact bearing | Unchanged | Unchanged conditions; CISD supplies only the origin |
| Campaign scope | `campaign_scope.campaign_scope_proof` (D3-B STRICT: 5m/15m supporting reclaimed raid strictly after death) | Unchanged | Unchanged. A CISD origin does not satisfy D3 by itself |
| Brain input | `ai_brain/brain_input.py` (5m path cap 80; settled vs forming) | Add one descriptive `cisd_facts` block labelled `authority: DISABLED` | Same block plus the transfer proof it supports |
| Entry/plan consumers | `build_narrative_continuity`, `output_direction_hold`, `candidate_direction_authorized`, CandidateProducer, plan validation | Unchanged (no new authority) | Inherit authority only through `_transfer_proof` and the existing gates |
| Restart | Mandatory canonical settled-prefix reconstruction (`_prepare_chronology`, `_rebuild_derived_state`) | Recompute; never persist a conclusion | Same; any ledger row is an observation only |
| PO3 tool formation | `toolbox/price_levels.po3_reversal_order_block` | Unrelated; not a transfer proof | Unrelated |

## 4. Tests and activated controls (`tests/test_cisd_shadow_contract.py`, 15 cases)

The cases cover:

- archived bucket OHLC;
- archived CISD identity;
- the forming bucket never counting as a fact;
- every-cutoff prefix/restart/order equivalence and immutability;
- a missing constituent minute;
- the strict-vs-inclusive boundary (fictional equal close);
- supersession by a new extreme (fictional);
- the mirrored bullish case;
- five unreadable-tape refusals;
- settled/maximal-extreme and invalid-request refusals;
- the production route rejecting the family, with a non-vacuous `rejected_raid_reclaim` control, D3 policy unchanged,
  and no `src` reference.

Activated mutants, each caught:

| Mutant | Result |
|---|---|
| Partial buckets accepted | 1 failed |
| Inclusive default | 1 failed |
| Unsettled buckets used | 4 failed |
| Gap guard removed | 1 failed |

## 5. Owner-decision appendix (nothing below is chosen)

| # | Decision | Options | Changes trading policy? |
|---|---|---|---|
| **O1** | Role of CISD | (a) additional recognition evidence under existing gates; (b) independent transfer-proof origin family | (a) No authority change. (b) **Yes**: new origin family, Brain fingerprint change, fresh authorization |
| O2 | Which extreme anchors the run | rejected-raid bar; current protected swing; session extreme since the incumbent's origin; owner-annotated | Yes under (b); descriptive only under (a) |
| O3 | Timeframes and conflict | 5m only; 5m/15m; precedence when T-CISDs disagree; 1m/3m excluded or context-only | Yes under (b) |
| O4 | Boundary and doji | STRICT vs INCLUSIVE; doji ends or continues the run; body close (proposed) vs wick | Yes under (b) |
| O5 | Relation to incumbent death | CISD must follow proved load-bearing death (the current `_transfer_proof` order), or may precede it and await it | **Yes**. Relaxing died_at < origin_at changes the transfer law |
| O6 | Revocation | close back beyond the anchor; beyond the run extreme; on opposite CISD; on session end | Yes under (b) |
| O7 | D3 relationship | Keep D3-B STRICT unchanged (proposed), or amend it | Amending D3 is an explicit policy change and is **not proposed**; the instruction is to preserve it |
| O8 | Contrary local raids | Whether sell-side raids printed inside a bearish displacement may replace a CISD-backed bearish hypothesis (section 2) | Yes under (b) |
| O9 | Persistence | Recompute only (proposed) vs ledger observation rows | No (engineering), if O1=b |

What none of the options does:

- The noon short is a separate, earlier opportunity, and the 12:20 candle cannot justify it retroactively.
- Current-Brain recognition, entry geometry and fill at either marked price stay **UNPROVEN**.
- Ratifying O1-O9 would authorize an implementation and its review, not a trading session.
