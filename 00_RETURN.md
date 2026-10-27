# Dormant release connection: local-authority production profile (selection OFF)

Parent `6e30453b70022ee66240716b72683b798ad4f523`, tree `09429e544f9514754462a1950db19e854c706228`.
Final dormant review SHA `d41267635f80b43e191c0a5c86d99172236457bf`, tree
`12eb8a9f024af57a5e6dec4110731c2136ae14c7`, branch
`review/local-authority-release-connection-20261027` (one commit on the parent; the
accepted chronology branch is still at 6e30453). Brain `brain:9bb7ac73616bd5cf` (parent
`brain:5f43a3a434eec2eb`), retrieval `retr:0c241bdb8234d1ba` unchanged, closure 50, 32
protected sources unchanged (ledger `LEDGER_VERIFIED`, entry
`LOCAL_AUTHORITY_DORMANT_RELEASE_CONNECTION_20261027`).

No activation applied, no ratification, no merge, deployment, rebind, arming or order; no
provider, model, venue or paid call; no credentials or private Mac state. The delivered
compiled selection is `RELEASE_SELECTION = None`.

## 1. What changed (3 source files, all inside the existing closure)

| File | Change |
|---|---|
| `src/market_data/local_authority.py` | `PRODUCTION_PROFILE_V1 = LocalAuthorityProfile("local_authority_production/v1", True, True, True)`: the same three reviewed cases, consumed by the same unchanged proof functions. `resolve_profile` accepts that exact object even beside truthy execution switches. Offline objects keep their switch refusal. Unknown strings, dicts, copies and look-alikes stay DISABLED. `RELEASE_SELECTION = None` is the one compiled selection. `release_selection()` returns OFF for None, the exact production object, or raises `ProfileSelectionRefused` (`offline_profile_not_releasable`, `unknown_release_selection`, or the refusal reason). It never falls back. |
| `src/broker/topstepx_production_loop.py` | Constructor only: an optional `local_authority_profile=None` is forwarded to the cycle the loop builds itself. The real account provider, capital identity, session, contract and quote provider are unchanged. The constructor refuses a requested profile that conflicts with a supplied `scan_cycle`, or that the cycle refused. Calls with no selection are unchanged. No second cycle, no post-construction mutation, no subclass. |
| `tools/topstepx_production_session.py` | `run_production_scans` resolves the compiled selection before authorization and passes `selection["profile"]` into `ProductionLoop`. `main` refuses an invalid selection before authenticating, so no venue or model is touched. The startup banner prints `LOCAL AUTHORITY SELECTION / CASES / SOURCE` (OFF prints `OFF (legacy DISABLED; no local cases)`) and no account identifiers. |

Unchanged: candidate logic, the execution runner, orders, sizing, bracket/risk/management, the Brain constitution, scoped selection policy, protected `topstepx_session_authorization.py`, and every proof function. No new module, registry, JSON store, approval service or authority manager.

Source binding: `local_authority.py` and `tools/topstepx_production_session.py` are both in the Brain contract closure. Flipping only the literal (on a disposable copy) changes the fingerprint `brain:9bb7ac73616bd5cf -> brain:212feb88424b6d30`, so every prior SessionAuthorization stops verifying (permanent test `test_a_reviewed_selection_change_rotates_the_brain_contract_fingerprint`). Env, CLI, saved JSON or account records cannot select a profile.

## 2. UNAPPLIED activation diff (`activation/UNAPPLIED_ACTIVATION.diff`)

The diff changes one line at `src/market_data/local_authority.py:119`: `RELEASE_SELECTION = None` becomes `RELEASE_SELECTION = PRODUCTION_PROFILE_V1`. It is **UNAPPLIED and not ratified.**

If the owner later applies it, these changes come with it in the same reviewed commit:

- The literal Brain pins (`brain:9bb7ac73616bd5cf` in 3 examples and 4 tests) become `brain:212feb88424b6d30`.
- `test_delivered_release_selection_is_the_literal_none` is replaced by its ON counterpart. It is deliberately the guard that fails if the literal moves without review.
- A ledger entry is added.
- A fresh durable SessionAuthorization is issued against the new fingerprint, through the existing CLI.

## 3. Proof through the real callers (`tests/test_local_authority_release.py`, 45 cases)

All runs are disarmed (`armed=False`). Sockets are denied, and any venue write raises. Every run reports 0 orders, 0 tokens and 0 attempts. Brain replies and quotes are CONTROLLED, so they prove wiring and admission, not natural recognition or intent. The selection-ON cases monkeypatch the compiled literal. They are a controlled fixture, not the frozen launch. Execution switches are set true only inside the isolated test environment.

| Proof | Result |
|---|---|
| Frozen OFF launch, through `run_production_scans(scans=0)` and the real `ProductionLoop.__init__` | Builds the real default `ProductionScanCycle` with DISABLED (`default_disabled`), with the loop's account provider and the session quote provider. 5m and 15m tapes reach no local composite and no local candidate. |
| Controlled selection, same launcher and constructor | The cycle holds `local_authority_production/v1` with the real bindings. The 5m Friday composite reaches the actual candidate at 16:25/16:26/16:27 UTC, the same minutes as the accepted offline control. 16:24 refuses as `campaign_lifecycle_refused` first, in both ECU modes. |
| Plan / brainless trigger / final quote (both ECU modes) | A `watching` plan binds `routes.delivery_change = ldc:…` with process session `LA-OFFLINE`. The brainless trigger yields `QUALIFIED_CANDIDATE_OBSERVED`. The final quote returns `(True, None)` when healthy and `(False, conditional_plan_local_authority_changed)` after revocation. |
| Consumer integrity | A copied snapshot and a revoked issue both refuse at the actual CandidateProducer. |
| Refusals | An offline profile beside any switch refuses. Unknown, copy, look-alike, string, dict, `True` and `1` all refuse. Offline objects cannot be release selections even when disarmed. Profile conflict with a supplied cycle refuses. A refused requested profile fails construction. An invalid selection makes `main` return 2 before `TopstepXLiveSession` is constructed, and `run_production_scans` raises before `load_or_refuse_authorization`. Armed with the selection ON and no durable record gives `NO_SESSION_AUTHORIZATION`, and the loop is never built. |
| Owner confirming-bar extreme challenge | Still a regression. At 15m, a new high in the confirming bucket (17:05) and a gapped run each fail to reuse the healthy proof id, and neither is turned into a blanket no-trade assertion. |

`traces/` holds the raw launch-built bindings, per-minute outcomes, candidates and the full composite packet for OFF 5m, selected 5m and selected 15m.

## 4. Full 15m coverage

The constructed chronology uses Friday's tape. Every 1m bar from 15:00 UTC is split into three lawful 1m legs (open → first extreme → second extreme → close), whose aggregate is the original bar, so each original 5m bucket becomes one 15m bucket. The tape is then moved −2h. It is clearly synthetic, not a historical session (`tests/local_authority_loop.py::stretched_tape`).

**Bearish, both ECU modes, real settled ingestion → producers → publication → Brain input → Draw/Lifecycle/tool → actual CandidateProducer:**

- Life `15m` swing high, the earlier 15m raid, the 15m body-open break and the 15m structure break, with a 3m predecessor failure.
- `completed_at` 17:15 UTC, and the failure settled strictly before completion.
- Earliest availability: no composite at the 17:10–17:13 cutoffs (the 17:00 bucket is still forming); first at the 17:14 cutoff.
- Candidates at 17:16/17:17/17:18.
- The default-OFF launch publishes no composite on the same tape.

Matched negatives in both ECU modes: a gapped run (one settled 1m bar removed inside the run) and a new extreme in the confirming bucket never republish the healthy proof id. A copied snapshot refuses at the consumer.

**Bullish 15m: exact first missing witness, no fabrication.**

The price mirror of the same constructed tape (and the 5 other anchor/shift variants I tried) never reaches the composite. In every variant the bullish path forms *natively* instead.

The first divergence from the bearish run is at the 16:41 UTC cutoff (`witness/bullish_15m_first_divergence.log`):

- In the mirror, the bearish predecessor's 3m protected high 29226.0 (registered 16:38, violated by the 16:39 bar) releases ownership at 16:41.
- The 15m sell-side raid then becomes a native `rejected_raid_reclaim` bullish origin at 16:42.
- The bearish run has no mirrored 3m low at that point (its load-bearing low is 29216.25 from 15:29), so its predecessor survives and the composite is needed.

The asymmetry comes from 3m protected-swing registration on the mirrored chronology. Repairing it would be a recognition change, which is outside this mission, so I did not force it.

The bullish composite stays proved on 5m: the accepted constructed mirror reaches the bullish candidate, and the 5m body-break helpers cover 15m bullish. **Bullish 15m producer-to-candidate composite coverage is therefore not claimed.**

The 5m Friday composite cases remain regression controls.

## 5. Activated mutants (`mutants/`, each on a disposable copy of the frozen tree)

Unmutated: every named test passes (exit 0). Each mutant turned its targeted tests red while the healthy OFF baseline (normal launch DISABLED + literal None) stayed green.

| Mutant | Edit | Result |
|---|---|---|
| R1 | Loop omits constructor forwarding (and its refusal) | KILLED |
| R2 | Offline execution-switch guard removed | KILLED |
| R3 | Unknown profile accepted | KILLED |
| R4 | Invalid release selection falls back to legacy OFF | KILLED |
| R5 | Launcher drops the selection | KILLED |
| R6 | Profile conflict with a supplied cycle silently ignored | KILLED |
| R7 | Production profile refused beside execution switches | KILLED |

## 6. Complete source-isolated offline suite at the frozen SHA (`suite/`, `orchestration/`)

This is the accepted corrected orchestration. Each of 16 workers/shards had its own `git clone --no-hardlinks` checkout of `d412676`, with its own HOME/TMPDIR/basetemp/runtime roots. Sockets and DNS were denied and the execution switches were false. Every collection root was included.

- **10,022 collected = 10,022 unique JUnit cases.** Missing 0, extra 0. 366 files, file-disjoint, matching the collection.
- **9,439 passed, 583 skipped, 0 failed, 0 errors.** The parent's 9,977 plus the 45 new cases.
- Skips: 583 across the same 40 environment reason kinds as the accepted run (archived snapshots/stores absent, operator-local forensic artifacts, `LIVE_ENV_REQUIRED`). None was added.
- Receipts (16):
  - all exit 0, with HEAD = frozen SHA before and after;
  - tree `12eb8a9f…`;
  - one tracked-bytes digest before and after, `9f69d67d738bd37eb152da4a8a428bdf152da910af5ccc04a93ae1aa8678822a`;
  - clean status, no hardlinked tracked files, 16 distinct checkouts.

## 7. Startup/preflight template

See `02_STARTUP_PREFLIGHT_TEMPLATE.md`. It uses only the existing operational controls.

## 8. Honest limits

- Selection-ON evidence is a controlled fixture. The frozen normal launch is OFF and stays OFF until the owner applies the diff.
- Controlled Brain replies and quotes prove mechanical composition only. They do not show natural recognition, Friday intent, profitability or production readiness.
- Bullish 15m composite coverage is not established (§4). Bearish 15m is constructed, not historical.
- I could not run a whole armed operator process, by design. Armed refusal is shown only through the existing authorization path.
- `test_ops1_startup_authority::test_clean_config_grants_authority` fails under my ad-hoc runner environment on the parent too, and passes under the isolated orchestration. It is not affected by this change.
- The decisions reserved for Maurice are unchanged: ratifying the local contract, applying activation, and session authorization.
