# Phase 2: protected-structure continuity and authority reconciliation

**Disposition.** The factual-continuity part is complete, with no production change. The protected high is already
carried with its original identity across the ownership change, so there is no wiring defect. The authority part is a
proven contract gap. Friday and C2 are both legitimate refusals under current ratified authority. The one route that
would let a pre-death life bear a transfer is unratified, so it is left **unimplemented and disabled**, and a single
narrow rule is proposed in 05. Permanent tests now pin both halves.

**Run conditions.** This is an offline review only:

- no merge, deploy, arm or order;
- no model, provider or venue call, and no credentials;
- production stays disarmed;
- a previous session authorization is not reused.

## 1. Identity

| Item | Value |
|---|---|
| Parent (frozen, verified before any work) | `357668ea8742cb4a7916580908be6fff5a0b82d7`, tree `7dc4bb9ead0420b8352a155d9cfcd688109026a7`, clean |
| Final (frozen) | **`736c610d86e6618e979efd388521deeb9bf669e6`**, tree `55d162a8b78ae91028fb76c5d574fb8352d24658`. Two commits on the parent: `a24ab45` (tests, fixture, ledger) and `736c610` (one test made order-insensitive after its own full-suite failure; see 04) |
| Branch | `review/protected-structure-reconciliation-20261025` (pushed, not merged) |
| Diff | 3 files, +969 lines, no `src/` change: `tests/test_protected_structure_continuity.py` (10 cases), `tests/fixtures/session_20261023_settled_tape.json` (settled bars only, copied unchanged from the f6e4013 reference fixture), one appended ledger entry |
| Pins | `brain:62fe5ecf46d75dc4`, `retr:0c241bdb8234d1ba`, closure 49 and the 32 protected sources are all **unchanged** |
| Ledger | Entry `PROTECTED_STRUCTURE_RECONCILIATION_20261025`; `verify_engineering_ledger.py` at the final SHA returns LEDGER_VERIFIED (protected_verified 32, network_requests 0) |
| Not imported | The f6e4013 binder, its ledger, fingerprints and expectations. f6e4013 and 0df06ea are preserved untouched |

## 2. Answers required by §8

1. **Was the fact lost or already present?** Already present.
   - At every Friday cutoff from 16:48Z on, the producer's current life is published in `protected_swings.by_timeframe`
     with its original identity, and it reaches the transported Brain input unchanged in both lanes: 1m high 29263.0,
     `1m:swing_high:29263`, registered 16:48Z, `buy_side_raid_rejected`.
   - C2's 5m 29500@03:04 behaves the same way.
   - Nothing is re-dated or re-minted, and the same-price life that died at 16:46 is not confused with it.
   - Classification: **NO WIRING DEFECT**.
2. **Which authority rule applies?** Three rules govern this:
   - `ActivePath._apply` step 2 binds a supporting life only when it is observed inside its own leg.
   - `_transfer_proof` requires the new owner's intact expected-side bearing.
   - D0=a and D3=B STRICT both consume that proof. D3 B1 states it explicitly: "B1 already requires an intact to-side
     bearing". The 2026-10-09 selection is "D0=a … D3=B; D3_TIME=STRICT; BEARING=INDEPENDENT_SUPPORTING_LIFE".

   No dated decision says whether a life registered while the incumbent owned the tape may become the opposing bearing.
3. **Exact first rejected witness.**
   - Friday: at 17:15Z the bearish owner becomes active (1m break @29154.25), after the 17:08 bullish 1m 29195 death
     and the 17:09 1m `rejected_raid_reclaim` origin. The first failing `_transfer_proof` conjunct is the missing
     load-bearing structure (`G7`), and it stays the first failure through 17:40.
   - C2: the same conjunct fails at 03:07–03:14.
   - The local leg death is published as a local failure (`active_leg_failure_status: occurred`, retained released
     life). The campaign premise stays UNKNOWN; it is not a campaign failure.
4. **Minimal correction.** None is authorized.
   - The only change that gives Friday a bearing would change who may establish a transfer. That is the f6-style route,
     and the identical facts would promote C2 to `confirmed_transfer`.
   - No ratified witness distinguishes Friday from C2. Neither has a post-death event naming the retained life, and
     neither has a D3-B raid after D. Friday's only bearish catalog life (5m 29294.5) was raided at 15:55–16:05, before
     the 17:08 death.
   - So the route stays **UNAPPROVED / DISABLED**. 05 states the narrowest rule (Q-BEARING-R): it changes nothing on
     Friday, C2 or W5 and needs ratification.
5. **Complete-path positive and activated negatives.**
   - Positive: the existing W5 D3-B route reaches a real bearish CandidateProducer candidate in both lanes. Its bearing
     (5m 29519.75) is registered at 14:29, after the 14:23 death.
   - Matched negative: the same life registered before the death gives no bearing and no proof.
   - Activated mutations, all caught with a healthy twin (03 §5):
     - lost fact transport;
     - stale identity;
     - future context;
     - duplicate progression;
     - the f6 C2 promotion, which also breaks the four existing C2 pins.
6. **Reserved doctrine gap.** Q-BEARING-R (05 §1). It is proposed, not chosen; it is not a global yes/no about older
   highs.

## 3. Classification of every investigated claim

| Claim | Classification | Evidence |
|---|---|---|
| Friday 29263 high "lost" to cognition | **NO WIRING DEFECT** (fact present) | 02 row 1; N1 both lanes; lost_transport mutant |
| Friday new owner has no bearing / no transfer | **INCOMPLETE AUTHORITY CONTRACT** (not implemented) | 01 §3, 02 witness table, 05 |
| Friday refusal at 17:15+ under current authority | **LEGITIMATE REFUSAL** | 02 traces; candidate refused at every cutoff |
| C2 surviving 5m 29500 does not promote | **LEGITIMATE REFUSAL** | 02 row 2; f6 contrast 03 §3 |
| Local leg death vs campaign failure | Correctly separated (no defect) | retained-leg row; campaign premise UNKNOWN |
| Restart / duplicate cutoff / future suffix | No defect for this mission (horizon limitation recorded) | N3, N4; logs/horizon.log |
| Ladder / progression replay | No defect | N7; duplicate_progression mutant |

## 4. Verification

- **Full suite.** The complete isolated `tests/` suite ran at the final SHA 736c610 with 9,734 collected cases in 358
  files. The shard union equals the collection, and the shards are file-disjoint. Result: **9,151 passed, 583 skipped,
  0 failed, 0 errors** (+34 subtests). Skips are the same 583 archive and credential classes as before.
- **Earlier failing run.** The first run at a24ab45 had 1 failure in my own new test (it compared catalog row order).
  That run is preserved, and the fix is the second commit (04 §4).
- **Focused results.** Extracted from the same JUnit (04 §3).
- **New tests.** 10/10 pass on the final tree.
- **Probes.** The Friday probe covers both lanes over 281 minutes with 0 differences between lanes. The C2 probe ran
  at the parent and at f6e4013. The W5, horizon and future-context probes are in `probes/` and `logs/`.

## 5. What remains unproved

- current-Brain recognition and narrative quality;
- any executable Friday trade (none is claimed; every captured action was stand_down);
- fills, live venue and Mac runtime;
- the frequency effect of Q-BEARING-R.

CISD O1 is unchanged and out of scope. See 05 §2.
