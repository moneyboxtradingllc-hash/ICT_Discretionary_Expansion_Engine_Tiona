# Final-scope return: local failure clock correction (selection OFF, activation UNAPPLIED)

Parent `d41267635f80b43e191c0a5c86d99172236457bf` (tree `12eb8a9f…`; its source and evidence are preserved and its branch is unchanged). Final frozen SHA `e948f37a0358b9ad4b27e1fe633dc7ddf12084b7`, tree `838123e479e2939630075db483e212a20d2ae190`, branch `review/local-authority-failure-clock-20261027`. It is one commit on d412676 and has no changed dependency.

| Measure | Value |
|---|---|
| Brain | `brain:58528ed2e83d1c29` (parent `brain:9bb7ac73616bd5cf`) |
| Retrieval | `retr:0c241bdb8234d1ba` (unchanged) |
| Closure | 50 |
| Protected sources | 32, unchanged |
| Ledger | `LEDGER_VERIFIED`, entry `LOCAL_AUTHORITY_FAILURE_CLOCK_20261027` |
| Compiled selection | `RELEASE_SELECTION = None` |

No strategy, doctrine, detector, owner rule, proof family, eligibility, economics, risk, stop, sizing, management, frequency or Brain change was made. Nothing was merged, deployed, rebound, armed or ordered. There were no provider, model, venue or paid calls and no credentials.

## 1. The one repair (`src/market_data/local_authority.py::failure_available_at`)

**Defect.** The function returned the native `settled_edge_time`. `snapshot_builder.settled_source_provenance` defines that field as the **open** of the failure bucket's terminal 1m constituent; it is `None` on 1m. The body-open and structure completion edges, by contrast, are bucket **closes** (`source_bar_time + timeframe`).

The strict comparison `failure_available_at < completed_at` therefore mixed the two clock domains:

- a 3m failure looked one minute earlier than it was knowable;
- a failure whose bucket closed exactly at the completion edge passed the strict ordering.

**Correction.** The function now returns the close of the failure's settled source bucket, `source_bar_time + timeframe`, which is the same domain as the completion edges.

- The native `settled_edge_time` is only validated: it must name a constituent minute of that bucket (`source <= edge < close`, on the minute grid).
- An inconsistent or unreadable edge, an unknown timeframe or an unreadable source returns `None`. Unprovable input proves nothing.
- 1m is unchanged (`source + 1 minute`).
- Native fields, ids and timestamps are read and never rewritten. Nothing is added to arbitrary metadata.
- The strict `<` ordering, same-minute refusal, scoped D3 native R, campaign_scope, snapshot_builder and ActivePath are untouched.
- The downstream transfer guard is unchanged.
- No order bypass is claimed.

## 2. Before and after, real producers (stretched constructed 15m tape)

This is the owner's construction: the simultaneous variant flattens only the 17:09–17:11 1m bars to lawful OHLC 29240. No producer, certificate, packet or validator is patched.

| Trajectory | Native failure (source / settled edge) | Parent clock | Repaired clock | Completion | Repaired producer result |
|---|---|---|---|---|---|
| Healthy | 3m 17:09 / 17:11 | 17:11 | **17:12** | 17:15 | Composite published, first at the 17:14 cutoff. Nothing earlier (prefix). Failure strictly precedes completion. |
| Simultaneous | 3m 17:12 / 17:14 | 17:14 (false pass) | **17:15** | 17:15 | **No composite at any cutoff.** Refusal `confirmation_not_after_settled_failure`. |

Evidence:

- **Parent reproduction** (`evidence/parent_reproduction.log`): the new tests run on unmodified d412676, 16 failed and 3 passed. The healthy packet claims 17:11 instead of 17:12; the simultaneous clock claims 17:14 instead of 17:15.
- **Repaired traces** (`evidence/REPAIRED_TRAJECTORIES.json`): the native failures, the parent clock vs. the repaired clock, the packet and the refusal reasons.
- **Proof id:** the healthy proof id changes (`ldc:fc2204eca7bf…`) because the failure clock is part of the bound packet. Prior plan bindings and authorizations therefore do not carry over.

## 3. Permanent tests (`tests/test_local_authority_failure_clock.py`, 21 cases)

- **Source semantics.** The clock equals the source bucket close for:
  - 1m with no edge;
  - 1m with an edge;
  - 3m healthy and 3m simultaneous;
  - 3m with no edge;
  - 5m and 15m.

  The input dict is unchanged after every call.
- **Malformed or mismatched input returns `None`:**
  - an edge outside the bucket, or naming the next bucket;
  - an edge before the bucket opened, or at the bucket close;
  - an edge off the minute grid, or unreadable;
  - an unknown timeframe;
  - a missing or malformed source.

  The legacy edge alone is never the availability.
- **Real producer walks:**
  - healthy: the 3m-failure/15m-composite is preserved with prefix chronology, and the native clocks are intact;
  - simultaneous: no packet and no route at any cutoff, with the refusal reason present.
- **Launch-built loop, both ECU modes:** a controlled selection fixture with execution switches set in the test environment only. In the simultaneous case no composite route reaches the Brain input or any candidate. Zero orders, tokens and attempts.
- **Existing coverage re-run unchanged and passing:**
  - revisions, current ownership, copied, revoked and duplicate inputs;
  - same-minute refusal (12:23), scoped exclusion;
  - healthy 5m and 15m candidates;
  - conditional plan, brainless trigger and final quote, in both ECU modes;
  - startup and authorization refusals.

  `evidence/focused_after_fix.*`: **180 passed** across the clock, member-order, delivery-change, composition and release suites.

## 4. Activated controls (`mutants/`, each on a disposable copy of the frozen tree)

The unmutated copy passes. All three mutants were killed by the clock tests:

| Mutant | Edit | Result |
|---|---|---|
| C1 | Legacy terminal-open clock restored (the old defect) | KILLED |
| C2 | Edge consistency unchecked | KILLED |
| C3 | Strict ordering relaxed to `<=` | KILLED |

## 5. Complete source-isolated offline suite at e948f37 (`suite/`, `orchestration/`)

This is the accepted orchestration: 16 shards, each in its own `--no-hardlinks` clone, with every collection root.

- **10,043 collected = 10,043 unique JUnit cases.** Missing 0, extra 0. 367 files, disjoint, equal to the collection.
- **9,460 passed, 583 skipped, 0 failed, 0 errors.** That is d412676's 10,022 plus the 21 new cases.
- 583 skips across the same 40 environment reason kinds; none added.
- All 16 receipts:
  - exit 0, with the frozen HEAD before and after;
  - tree `838123e4…`;
  - one tracked-bytes digest `949641bc9c661c488fdfee1da2b33c4ef765c13acf0cb2d347d84c529516422b`;
  - clean status, no hardlinks, 16 distinct checkouts.

## 6. Bullish 15m composite: **UNPROVEN** (coverage question, not redesign)

No producer, certificate, owner rule or detector was changed, and no retired life was selected. A native bullish label and the 5m positive are not counted as 15m composite proof.

Bounded attempts on lawful synthetic tapes (`evidence/bullish_15m/`, plus the owner's own variants):

1. **Exact mirror of the bearish construction.**
   - First divergence at the 16:41 cutoff: the mirrored bearish predecessor's 3m protected high 29226.0 (registered 16:38, violated by the 16:39 bar) releases ownership.
   - The 15m sell-side raid then becomes a native `rejected_raid_reclaim` bullish origin.
   - The bearish run has no mirrored 3m swing there.
   - Classification: **legitimate native route**. It reflects a 3m protected-swing registration difference on that chronology, not a wiring defect.
2. **Mirror with only the 16:40–16:41 bars clipped below 29226** (the predecessor survives).
   - An **earlier lawful 5m composite** (5m life, 5m body, 3m failure, completed 16:45) is adopted at the 16:44 cutoff and preempts the 15m branch.
   - Classification: **legitimate earlier alternative**. The brief says not to force it to refuse.
3. **Owner variants** (included in the owner package): earlier 5m composites, an unsupported native path, and an AUTHORITY_UNKNOWN consumer result.

**Earliest blocker:** on every lawful bullish construction tried, an earlier valid route (a native 15m origin or a 5m composite) is admitted before a 15m composite graph exists. No complete authentic bullish 15m composite graph was reached, so no consumer predicate was ever exercised for one.

The bearish 15m composite reaches the actual CandidateProducer in both ECU modes, so the consumer wiring is direction-agnostic code. But by the contract, **bullish 15m composite producer-to-candidate coverage stays UNPROVEN**. I did not run an open-ended search.

## 7. Activation (UNAPPLIED) and startup

- `activation/UNAPPLIED_ACTIVATION.diff`, regenerated at e948f37: one line, `local_authority.py:119`, `RELEASE_SELECTION = None` becomes `RELEASE_SELECTION = PRODUCTION_PROFILE_V1`.
- Measured on a disposable copy, the prospective fingerprint would be `brain:893a252a0d555ebc`. The previously reported `brain:212feb88424b6d30` is stale and not reusable. No alias or migration exists.
- Applying the diff later also requires, in the same reviewed commit:
  - repinning the 7 Brain literals;
  - replacing the OFF-literal guard test;
  - a ledger entry;
  - a full isolated suite;
  - a fresh durable SessionAuthorization through the existing CLI.
- `02_STARTUP_PREFLIGHT_TEMPLATE.md` uses the existing controls only. It grants no trading permission.

## 8. Honest limits

- The bullish 15m composite is UNPROVEN (§6).
- Selection-ON runs are controlled fixtures; the frozen launch is OFF.
- Controlled Brain replies and quotes prove mechanical composition only, not natural recognition, Friday intent, profitability or readiness.
- No armed operator process was run.
- `test_ops1_startup_authority::test_clean_config_grants_authority` fails only under my ad-hoc runner environment, on the parent too. It passes in the isolated suite.
- Reserved for Maurice: doctrine reconciliation, release disposition, activation and session authorization.
