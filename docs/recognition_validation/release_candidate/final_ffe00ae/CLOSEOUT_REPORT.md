# Independent RC review closeout: final engineering and evidence package (frozen source ffe00ae)

This answers Codex's review for Maurice (2026-10-21 23:50Z). It supersedes the readiness board's commit and UNPROVEN
lines where they differ. Claims are labelled VERIFIED-RUN, VERIFIED-CODE or INFERRED. **Nothing here authorizes
connecting, deploying, arming or trading.**

## Frozen source

- **Commit:** ffe00aef3db7fb2339780ed0fa9016149923c96e, tree 57cc69c03882efc9bd1d6a7921f4fea6792a31cc, on
  `release/stage5-rc-20261022`.
- **Since bdd852d:** tests and docs only. `git diff bdd852d ffe00ae -- src tools` is empty, so the trading and safety
  code is unchanged.
- **Since owner source 201c60c:** only `src/recognition_validation/child.py` changed under src/ and tools/.
- **Ledger:** LEDGER_VERIFIED. The 32 protected pins and 48 closure entries are unchanged, with brain:3d9878ad3ff57f1f
  and retr:0c241bdb8234d1ba. The new entry is RC_REVIEW_CLOSEOUT_20261022.
- **Not done:** merge, deploy, arming, orders, or any provider, model or venue call.

## Items 1 to 5

1. **Windows-only test failure fixed (test only).** `test_posix_git_outside_the_os_directories_is_reachable` split a
   simulated PATH on ":", which also splits the Windows interpreter's "C:" drive. It now compares the whole string.
2. **Source pins fixed.** `stage5_mac_verify.zsh` takes the frozen SHA as a required argument: 40 hex characters,
   checked out, HEAD asserted. It also records clean status before and after the run, writes per-node accounting and
   writes a SHA-256 manifest. RELEASE_CANDIDATE.md section 5 and this report name ffe00ae. Earlier results stay
   labelled with their own sources: 5d18b4b, 77769dc and bdd852d. None is relabelled.
3. **Final-source Mac suite** (VERIFIED-RUN by the operator; evidence in `MAC_FINAL_SUMMARY.md`). The raw sanitized
   bundle was emailed to Maurice by the operator with sha256 b5eb2303a358a0c068e8cb942241ea24f10512e38acb970679ba7e4732c79c25.

   | Item | Result |
   |---|---|
   | Host | macOS 10.14.6, Intel i5-8210Y x86_64 |
   | Python and git | Python 3.12.7, git 2.20.1 |
   | Pins | 47/47 |
   | Checkout | clean, at ffe00ae |
   | Child finds git; env equals allowlist; disarmed | yes |
   | Ledger | LEDGER_VERIFIED |
   | Focused set | **179/179 passed** |
   | **Complete suite** | **9,699 cases: 9,116 passed, 583 skipped, 0 failed, 0 errors** (3h37m) |

4. **Mac accounting reconciled from raw per-node JUnit**, computed on the Mac by the script from
   `stage5_mac_verify_20261021T165911Z/evidence/full.junit.xml`, source 5d18b4b.

   | Outcome | Count |
   |---|---|
   | Passed | 9,089 |
   | Skipped | 583 |
   | Failure only | 12 |
   | Error only | 10 |
   | Failure and error on the same node | **0** |
   | **Total cases** | **9,694** |

   pytest's own line was "12 failed, 9089 passed, 583 skipped, 10 errors". The earlier board figure "22 failed, 10
   errors" double-counted: the operator summary's "22 failed" already counted any failure or error.
   - The 12 failures are the child launches (CHILD_ENV_NOT_ALLOWLISTED).
   - The 10 errors are the ledger tests failing in their fixture (`git init -b` on git 2.20).
   - An earlier evidence folder, `stage5_mac_verify_20261021T025001Z` (5d18b4b, focused set, 1,336 recorded cases),
     belongs to the first-night run, which the operator stopped. It is a partial run and is not counted as a result.
5. **Delegated offline gaps.**
   - **Contamination latch.** The persisted latch and its restart were already exercised by
     `test_session_contamination_repair`. The one remaining branch is a failed durable write, and the new
     `tests/test_terminal_latch_persistence_failure.py` covers it with a clean-governor healthy control. Activated
     mutants: 3 of 3 killed.
   - **Recording failure, recovery and adoption.** Already exercised by `test_production_submission_recorder`
     (`_reconcile_after_recording_failure`, `_emergency_recording_marker`) and `test_protection_state_authority`
     (`adopt_venue_protection`). The earlier "unreached" claim came from the coverage-instrument defect below.
   - **Legacy Alpaca HTTP attempts.** The two tests patched the wrong module, and one patch was missing. They now
     patch the bound names. Under the guard they make **0** connect attempts.

## Supported-runtime final suite (VERIFIED-RUN, Linux, Python 3.12.3, 47/47 pins, `linux_guarded_suite/`)

- **Run:** fresh remote clone at ffe00ae; 12 file-disjoint shards whose union equals the collection.
- **Results:** 9,699 cases; **9,116 passed, 583 skipped, 0 failed**. The skips are identical to the 77769dc run, with
  3 added cases and 0 removed. The Mac and Linux totals are identical.
- **Network:** the guard recorded **0 socket connect attempts** in the whole suite, and every non-loopback connect would
  have been refused.
- **Bound on the egress claim:** this covers in-process `socket.connect`/`connect_ex` during the suite only. It is not
  a packet capture, and it does not cover subprocess trees. The trajectory children carry their own network deny and
  dead proxy.
- **Function-reach coverage:** first-hit recording of production-path functions, not an outcome proof for every
  refusal.

| Area | Reached |
|---|---|
| Conditional plan and final quote | 18/18 |
| WakeRegistry | 21/21 |
| Session authorization | 22/22 |
| Mission state | 19/20 |
| Mission recovery | 6/6 |
| Mission reconciler | 17/17 |
| Execution runner | 62/64 |
| Production session | 23/23 |
| Daily loss | 7/7 |
| Combine risk | 20/21 |
| Protection | 12/12 |
| Freshness | 8/8 |
| Cognition lock | 4/4 |
| Session ledger | 14/14 |
| Lifecycle | 5/5 |
| Hard flatten and emergency liquidation | 11/11 |
| Production loop | 30/32 |
| Scan cycle | 36/38 |
| Entrypoint | 16/19 |

**Still unreached (UNPROVEN, listed by name):**

- **Dead code, with no caller anywhere** (VERIFIED-CODE): `revalidate_before_submit`, `mission_owned_working_orders`
  and `combine_risk.all_in_risk_for`.
- **Needs the live account or venue:** `main`, `_flat_and_clear` and `candle_count` in the entrypoint; the live-session
  `_token`, `close`, `connect_market_hub`, `connect_user_hub`, `order_by_id` and `recent_trades`; the client's
  `available_contracts`, `close_position_partial`, `order_by_id`, `order_history`, `ping` and `trade_history`.
- **Other unreached:**
  - `ProductionLoop._capital_identity` and `_topstep_account`;
  - `ProductionScanCycle._recover_active_path` and `in_decision_window`. `_recover_active_path` is referenced only by
    `test_active_path_state`, whose 11 archive-dependent cases are skipped;
  - `MissionState.bind_exit_attribution`.

**Coverage-instrument correction.** The earlier rehearsal recorder compared un-normalised `co_filename` text. Test files
that import through `tests/../src/...` were therefore never matched (shards 6 and 7 recorded only 17 and 12
functions). The UNPROVEN list in the d9e5fbe board over-stated the gaps. The recorder now normalises paths, re-arms
before every test, and cannot raise. In this run every shard recorded between 395 and 910 functions, with 0 re-arms
and 0 callback errors.

## Owner-reserved and UNPROVEN (unchanged)

- Stage 4 owner acceptance; the choice of observation source (ffe00ae or production cbfaddb); separate read-only
  access.
- Current-Brain recognition on ratified sessions, sealed annotations, corpus and scoring thresholds.
- Historical archive certification: about 440 skipped cases need operator archives.
- Mode C (live model transport).
- Controlled observation.
- D11 to D14 and the combined opportunity-timing criterion.

The board's CONDITIONAL GO for supervised, disarmed, read-only observation is an engineering recommendation with these
prerequisites open. It is not authorization. **Unattended or funded operation: NO-GO.**
