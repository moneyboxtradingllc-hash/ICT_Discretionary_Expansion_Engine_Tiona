# Review candidate: existing-policy repair selected (NO DEPLOYMENT)

| Item | Value |
|---|---|
| Parent | `e948f37a0358b9ad4b27e1fe633dc7ddf12084b7` (accepted; its branch and evidence preserved; no newer dependency) |
| Final candidate | `a164f41ea5a39ad2c06d6207669d5999bbe9ef9f`, tree `e70488f56087e44dcba5944bbf754b4692c09b87` |
| Branch | `review/local-authority-existing-policy-release-20261028` |
| Brain | **`brain:10bbf12edd6376e0`**, measured; equal to Codex's projection for the exact diff |
| Retrieval | `retr:0c241bdb8234d1ba` (unchanged) |
| Closure | 50 |
| Protected sources | 32, unchanged |
| Ledger | `LEDGER_VERIFIED`, entry `LOCAL_AUTHORITY_EXISTING_POLICY_RELEASE_CANDIDATE_20261028` |

The superseded all-three preparation (`prepared/activation-awaiting-approval-20261028`, 9f0d2fb, `brain:893a252a0d555ebc`) was not used. Its partial suite was stopped. It stays only as preserved, unselected engineering history.

Nothing was merged, deployed, changed in an operator checkout or rebound. No credentials were used. No real SessionAuthorization was issued. There were no provider/model/venue/paid calls, no arming and no orders.

## 1. Exact source change

`src/market_data/local_authority.py` changes exactly as `03_REVIEW_CANDIDATE_CONFIG.diff`. The changed lines are identical; only the git header lines differ.

| Item | Value |
|---|---|
| New object | `PRODUCTION_EXISTING_POLICY_REPAIR_V1 = LocalAuthorityProfile("local_authority_existing_policy_repair/v1", True, False, False)` |
| Recognized production profiles | `_PRODUCTION_PROFILES = (PRODUCTION_PROFILE_V1, PRODUCTION_EXISTING_POLICY_REPAIR_V1)` |
| Compiled selection | `RELEASE_SELECTION = PRODUCTION_EXISTING_POLICY_REPAIR_V1` |

Flags: `member_order_witness=True`, `retained_support=False`, `delivery_change=False`.

Unchanged:

- the all-three profile (recognized, unselected);
- the offline objects and their execution-switch refusal;
- unknown, copy and look-alike refusals;
- the e948f37 clock repair;
- detectors, proofs, cognition/memory, telemetry, scope/D3 policy;
- risk, stop, size, frequency, execution and authorization.

Other changes:

- Measured pins: 3 examples and 4 tests.
- `tests/test_local_authority_release.py`:
  - the selection guard now asserts the exact repair literal;
  - OFF and all-three cases are explicitly labelled controlled fixtures;
  - the fingerprint test proves that flipping the literal either way rotates the fingerprint.
- `tests/local_authority_loop.py` gains an opt-in `watch="nearest"` choice for controlled watching replies (§3.4). Existing callers are unchanged.

## 2. Startup trace (actual compiled selection, no patching)

```
LOCAL AUTHORITY SELECTION    : requested local_authority_existing_policy_repair/v1, resolved local_authority_existing_policy_repair/v1
LOCAL AUTHORITY CASES        : member_order_witness
LOCAL AUTHORITY SOURCE       : src/market_data/local_authority.py:RELEASE_SELECTION (bound by the Brain contract fingerprint)
```

## 3. Release proofs (`tests/test_local_authority_existing_policy_release.py`)

Every normal-release case runs `run_production_scans(scans=0)`, then the real `ProductionLoop.__init__`, then its own `ProductionScanCycle`, using the **actual compiled selection**. Nothing patches the selection, cycle or producer.

Brain replies and quotes are CONTROLLED. The loop is disarmed, venue writes raise, and every run reports 0 orders, 0 tokens and 0 attempts. Execution switches are set only in the isolated test environment.

1. **Exact policy.**
   - `RELEASE_SELECTION is PRODUCTION_EXISTING_POLICY_REPAIR_V1`, with flags `(True, False, False)` and `release_selection()["cases"] == ["member_order_witness"]`.
   - Copies, the version string and a look-alike object all refuse.
2. **Normal launch, both ECU modes.**
   - The cycle resolves the repair object with the loop's real account provider and the session quote provider, session id and contract.
   - The banner prints only `member_order_witness`.
3. **Obscured same-direction generation, both ECU modes.** This is the accepted Friday 15:37–15:57 UTC member-order fixture.
   - The witness-backed successor proof (`order_basis = constituent_member_order_witness`) reaches the actual CandidateProducer at **15:57**.
   - Earlier minutes are still refused by the existing mechanical gates (`stop_distance_above_cap`, `reward_below_qualification`).
   - A copied snapshot and a revoked issue refuse at the consumer.
4. **Member-order-dependent watching plan, both ECU modes.**
   - The plan publishes at 15:50 on the nearest lawful bullish 1m FVG zone (29232.5–29237.0). It binds `member_order_fact = mof:…`, `routes = {}`, with contract and process.
   - At 15:51 the brainless trigger returns `QUALIFIED_CANDIDATE_OBSERVED` (16.25-point stop, disarmed).
   - The actual final quote returns `(True, None)`, then `(False, conditional_plan_local_authority_changed)` after revocation.
   - A withdrawn current witness refuses at the trigger.

   Fixture choice: on the first-catalog zone, the trigger is refused, correctly, by the existing guards.
   - At 15:58: `conditional_plan_review_required: active-path transfer evidence changed after plan publication`.
   - At 15:51 on a distant zone: `extended_volatility_unsupported`.

   The controlled reply therefore uses the nearest zone with a real invalidation inside the doctrine's preferred stop range. No economics changed. `evidence/probe_*` holds the record.
5. **Unselected families.**
   - No normal-release scan carries `retained_support` or `delivery_change` refinements.
   - In the former composite window (Friday 16:22–16:27, both ECU modes), no `raid_reclaim_delivery_change` reaches the Brain input and no `ldc:` proof reaches any outcome.
   - Native routes stay available.
6. **Unchanged coverage, re-run in the full suite.**
   - Mirrored order, same-minute 12:23 refusal, wrong life, gaps, duplicates, forming bars, revision/restart/rolling coverage, copied/revoked publisher, healthy native control.
   - D3 scoped positives/refusals.
   - Clock tests, startup/authorization refusals, and conditional/final-quote checks.
   - The all-three experimental tests (labelled controlled).

## 4. Activated controls (`mutants/`, each on a disposable copy of the frozen tree)

The unmutated copy passes. Every mutant turns the release assertions red:

| Mutant | Edit | Result |
|---|---|---|
| P1 | Loop constructor forwarding dropped | KILLED |
| P2 | All-three profile selected | KILLED |
| P3 | `retained_support` enabled on the repair object | KILLED |
| P4 | `delivery_change` enabled on the repair object | KILLED |

## 5. Complete source-isolated offline suite at a164f41 (`suite/`, `orchestration/`)

16 shards, each in its own `--no-hardlinks` clone, with every collection root.

- **10,058 collected = 10,058 unique JUnit cases.** 368 files, disjoint, equal to the collection.
- **9,475 passed, 583 skipped, 0 failed, 0 errors.**
- 583 skips across the same environment reason kinds as the accepted runs; none added.
- All 16 receipts:
  - exit 0, with the frozen HEAD before and after;
  - tree `e70488f5…`;
  - one tracked-bytes digest `80fae9135877403c876af583f5db3e20eef4708a80e6e9b71e738da4d62803dc`;
  - clean, no hardlinks, 16 distinct checkouts.

## 6. Preflight

See `02_OPERATOR_PREFLIGHT_TEMPLATE.md`. It uses existing controls only. It records the expected banner, fingerprint and fresh-authorization step for this already-configured source. It grants no authority.

## 7. Honest limits

- The all-three bullish 15m composite stays **UNPROVEN** and unselected. Retained-support adoption and the delivery-change family are not part of this release.
- Controlled replies prove mechanical composition only. They do not show natural recognition, Friday intent, profitability or comprehensive coverage. This is not a claim of autonomous production readiness.
- No armed operator process was run.
- `test_ops1_startup_authority::test_clean_config_grants_authority` fails only under my ad-hoc runner environment, on the parent too. It passes in the isolated suite.
- Reserved:
  - Codex: release acceptance;
  - Maurice: operational/session decisions;
  - the operator: deployment, checkout, authorization and preflight.
