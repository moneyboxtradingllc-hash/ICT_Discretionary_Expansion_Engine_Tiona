# Release candidate for supervised, disarmed, read-only observation (not merged, not deployed)

Branch `release/stage5-rc-20261022`. **Proposed launch source: bdd852dd5d8b8b5590d124a4a9b722ddeba2e3d1.**

- It is 5d18b4b plus the owner-approved Mac child-launch fix in `src/recognition_validation/child.py` and its tests
  (ledger entry MAC_RUNTIME_PORTABILITY_20261021). The trading code is byte-identical to 5d18b4b.
- The rehearsal below ran at 5d18b4b and again at 77769dc. The 77769dc run gave 9,113 passed, 583 skipped and
  0 failed; see `rehearsal_77769dc/`.
- Every later commit is docs/evidence only.
- Nothing is merged into `feature/latency-1-preauthorized-plans` (production, cbfaddb) or `main` (a1614ae), and
  nothing is deployed or armed.
- The GO/NO-GO board is in `GO_NO_GO_BOARD.md`.

## 1. History reconciliation (VERIFIED-RUN)

The history is linear, with no divergent work to reconcile:

    main a1614ae -> production cbfaddb (2026-09-30) -> ... -> review a41c552 (2026-10-18)
                 -> audit 51eb3e1 -> gap closure c962a3d -> owner A/B 201c60c -> 5d18b4b

- cbfaddb, a41c552, 51eb3e1 and a1614ae are all ancestors of 5d18b4b.
- Nothing on production or review is missing from 5d18b4b (0 commits).
- 85 commits separate production from the candidate.
- **The candidate is NOT the code production runs today.** Between cbfaddb and a41c552 the Stage 3/4 repairs changed
  39 production-path files (Brain input, schema and validation, ECU, stance memory, campaign draw, lifecycle, premise
  and scope, conditional-plan authority, execution runner, production loop and session, combine risk, cognition
  lock, data feed and others; the full list is in `rehearsal/prod_path_changes.txt`). These are reviewed engineering
  repairs, but **Stage 4 owner acceptance of them is still pending**.
- Since a41c552, only the offline Stage 5 harness (`src/recognition_validation/`), its tests, docs and
  `tools/verify_engineering_ledger.py` changed.
- The 32 protected sources and the 48-file Brain and retrieval closure equal their ledger pins:
  brain:3d9878ad3ff57f1f, retr:0c241bdb8234d1ba, LEDGER_VERIFIED.
- Ratified trading policy is unchanged by any Stage 5 commit.

## 2. Actual production entrypoint and gates (VERIFIED-CODE)

The entrypoint is `tools/topstepx_production_session.py` `main()`. Without `--arm`, no order-capable branch exists.

1. **Authenticate, pin and resolve.** `TopstepXLiveSession.authenticate`, then `pin(account_id, expected_fingerprint)`
   (a fingerprint mismatch refuses), then `resolve_contract`.
2. **Start the market feed.** One `TopstepXMarketRuntime` is the only pump. The candle, quote and VAP consumers attach to
   it and start no pump of their own.
3. **Run the startup refusals.** `check_startup` refuses on any of:
   - ambiguous pump owner, or a dead pump thread;
   - no pinned account, no fingerprint, or no contract;
   - no market hub;
   - a retired, foreign or cross-contract instrument;
   - a doctrine conflict;
   - an armed session without a mission id;
   - authorization, window or provider refusals.

   Any refusal prints PRODUCTION SESSION REFUSED and exits with code 2.
4. **Open the lane.** `ProductionSession.open_lane` gives NORMAL or RECOVERY. RECOVERY reconciles and never re-enters.
   Telemetry passes `assert_clean`, so no credential is ever printed.
5. **Run the scans.** `run_production_scans` is entered with `--scans N` or `--until-close`:
   - `load_or_refuse_authorization`: armed sessions need a durable authorization;
   - `ProductionSessionMission`: mission limits and the daily loss budget;
   - `WakeRegistry`: event wakes;
   - per tick: `handle_pending_conditional_wake` (the zero-new-Brain trigger), then the scan.
6. **One scan** is `ProductionLoop` / `ProductionScanCycle`:
   - settled snapshot;
   - campaign Draw, lifecycle, premise and scope;
   - Brain call (ECU or non-ECU), with schema validation and repair;
   - cognition lock;
   - candidate or conditional-plan publication.
7. **Order gate (armed only).** `ExecutionRunner.gated_submit`, in order:
   - ledger;
   - external account check;
   - freshness (`_assess_freshness`: a stale candidate is destroyed);
   - objective and invalidation;
   - `recheck_risk_at_submit`;
   - optional refresh: re-assess, and halt if positions or orders appeared;
   - final quote: `conditional_plan_authority.validate_final_quote`, refused with
     `_halt_conditional_final_quote_refusal`;
   - protection.

   Only then does `ExecutionRunner.submit` call `ProductionSession.submit`.
8. **Risk.** `daily_loss_budget`, `topstepx_combine_risk` (trailing drawdown), and `topstepx_protection_authority` /
   `protection_state`.
9. **Emergency stop and shutdown.**
   - `hard_flatten_due` triggers `topstepx_hard_flatten` at the window end; the loop flattens and stops.
   - `topstepx_emergency_liquidation` handles emergencies.
   - Shutdown is `candles.stop()` then `runtime.stop()`, with "pump joined, hub closed once".
   - The deterministic lane's STOP file is `data/integration/topstepx/deterministic/STOP`.

Note: `ExecutionRunner.revalidate_before_submit` has **no caller**; it is dead code. The live gate applies the same
freshness law through `_assess_freshness`, which the rehearsal reached.

## 3. Disarmed end-to-end rehearsal (VERIFIED-RUN, `rehearsal/`)

- **Run:** the complete suite at 5d18b4b in a fresh remote clone (Linux, Python 3.12.3, 47/47 pins), under
  `rehearsal_guard.py`. The guard refuses every non-loopback socket connect and records every connect attempt.
  `sys.monitoring` records the first test that reaches each production-path function.
- **Results:** 9,694 cases; 9,111 passed, 583 skipped, 0 failed.
- **No live order submission:** 3 connect attempts in total, all to the runner's dead proxy at 127.0.0.1:9, 0 refused
  non-loopback, so no byte left the host.
  - All 3 came from the legacy `paper_execution` (Alpaca) tests: `test_phase_2b_monitor_enforcer` (2) and
    `test_phase_4b_broker_stop` (1).
  - Those tests do not fully mock the network. This is a test-isolation finding, and the code is not on the
    TopstepX production path.
  - Every order path in the suite used fakes or refusing doubles, and none reached a real venue.
- **Code paths reached (1,211 production functions in all), by category:**

  | Category | Reached |
  |---|---|
  | Conditional plan and final quote (conditional_plan_authority, wake_registry) | 39/39 |
  | Arming, authorization and mission limits | 64/65 |
  | Order gate (execution_runner 59/64, production_session 23/23) | see split |
  | Risk | 38/40 |
  | Freshness, cognition lock, ledger and lifecycle | 30/31 |
  | Hard flatten and emergency liquidation | 11/11 |
  | Production loop and scan cycle | 64/70 |
  | Entrypoint module (`main()` needs live authentication) | 16/19 |

  First-hit tests include:
  - `gated_submit`: test_production_caller::TestSubmitPath::test_submit_attaches_the_live_quote_and_still_never_fills
  - `validate_final_quote`: test_po3_participation_binding::test_real_po3_plan_capture_brainless_trigger_and_final_quote[ecu]
- **Scenario coverage:** the rehearsal suite exercises, through those functions:
  - ordinary and conditional candidates in both ECU modes;
  - brainless (zero-new-Brain) triggers;
  - final-quote refusal;
  - restart and revision;
  - stale data;
  - mission limits;
  - hard flatten and emergency liquidation;
  - safe shutdown.

  The per-function first test is in `REHEARSAL_FUNCTION_FIRST_HIT.json`, and the per-module table is in
  `REHEARSAL_GATE_COVERAGE.json`.

**UNPROVEN** (defined on the production path, reached by no test):

- `ProductionLoop._latch_terminal_contamination`, `_terminal_cognition_result` and
  `topstepx_session_cognition_lock.record_contaminated`: the terminal cognition-contamination latch.
- `ExecutionRunner._reconcile_after_recording_failure`, `_emergency_recording_marker`, `adopt_venue_protection` and
  `mission_owned_working_orders`: recording-failure and adoption recovery.
- `ProductionScanCycle._recover_active_path` and `in_decision_window`.
- `MissionState.bind_exit_attribution`, `topstepx_combine_risk.all_in_risk_for` and `daily_loss_budget._tfield`.
- The live-session and client read and hub methods that need a real venue.
- `main()` itself, `_flat_and_clear` and `candle_count`, which only run against a live read-only account.

## 4. Reproducing it

- Runtime: Python 3.12.3 with `requirements.txt` (UTF-16, 47 pins) plus pytest 9.1.1, pluggy 1.7.0, iniconfig 2.3.1
  and packaging 26.3.
- Run in an emptied environment with orders disarmed and the HTTP(S) proxy pointed at 127.0.0.1:9.
- On the Mac: `docs/recognition_validation/mac_verification/stage5_mac_verify.zsh`.
- For the rehearsal: `rehearsal/tools/rehearsal_shards.py` with `rehearsal_guard.py` on the same 12-shard plan.

## 5. Read-only observation command (only after Maurice separately authorizes read-only access)

On the Mac, in a fresh checkout of this branch at 5d18b4b, with the operator's own `.env` (never committed), never
with `--arm`:

    export TOPSTEPX_ARM_ORDERS=false EXECUTION_ENABLED=false ALLOW_PAPER_ORDERS=false
    PYTHONPATH=src python3 tools/topstepx_production_session.py --proof --observe 60
    PYTHONPATH=src python3 tools/topstepx_production_session.py --until-close     # disarmed scans; prints "No order will be placed"

**Rollback:** stop the process with Ctrl-C (the pump joins and the hub closes) and return to the production checkout at
cbfaddb. There is no state migration to undo.

The authority to connect, arm or trade is not granted by this document.
