# Thursday Oct 22 readiness: GO/NO-GO board (Wednesday Oct 21, ET)

Claims are labelled VERIFIED-RUN (executed, with evidence), VERIFIED-CODE (read from source), or INFERRED/UNPROVEN.
There are no optimistic status substitutions here.

## Verdict

| Decision | Verdict |
|---|---|
| **Supervised, DISARMED, READ-ONLY observation on Thursday** | **CONDITIONAL GO** (engineering side only). It needs every condition in section 7. Maurice separately authorizes the read-only access, and nothing here grants it. |
| Unattended operation, arming, or any funded trading | **NO-GO**. Stage 4 owner acceptance, current-Brain recognition on ratified sessions, sealed annotations and scoring, historical archive certification and supervised-rollout approval are all outstanding. |

## 1. Exact commit

- **Proposed launch source:** bdd852dd5d8b8b5590d124a4a9b722ddeba2e3d1 on `release/stage5-rc-20261022` (not merged, not
  deployed). Production `feature/latency-1-preauthorized-plans` is still cbfaddb, main is a1614ae, and review is
  a41c552. All three are unchanged and are ancestors of the candidate.
- **Source changes since the 5d18b4b audit source:** only `src/recognition_validation/child.py` (the Mac child-launch
  fix) and tests. The trading code is byte-identical to 5d18b4b.
- **Since production cbfaddb:** 39 production-path files carry the reviewed Stage 3/4 repairs (listed in
  `rehearsal/prod_path_changes.txt`). **Their Stage 4 owner acceptance is PENDING.** Maurice decides whether observation
  runs the candidate or the current production commit.
- **Ledger:** LEDGER_VERIFIED. The 32 protected sources and the 48-file closure are unchanged, with
  brain:3d9878ad3ff57f1f and retr:0c241bdb8234d1ba. The new entry is MAC_RUNTIME_PORTABILITY_20261021.

## 2. Mac runtime (VERIFIED-RUN on the operating Mac by the operator)

- **Host:** MacBook Air, Intel Core i5-8210Y at 1.60GHz (x86_64, no Rosetta), **macOS 10.14.6 Mojave (18G103)**, zsh
  5.3, Command Line Tools, no Homebrew.
- **Python:** python.org 3.12.7 at /Library/Frameworks/Python.framework/Versions/3.12. Git is Apple 2.20.1 at
  /usr/bin/git.
- **Dependencies:** all 47 pins install and match exactly (`pip install` rc=0), plus the pinned test runner.
- **Child launch:** the child-launch PATH finds /usr/bin/git, the child environment equals the allowlist, and every
  guard stays disarmed:
  - EXECUTION_ENABLED=false
  - ALLOW_PAPER_ORDERS=false
  - AI_BRAIN_LLM=false
  - TWO_BRAIN_MODE=off
  - TOPSTEPX_ARM_ORDERS=false
  - HTTP(S) proxy pointed at 127.0.0.1:9
- **Ledger:** LEDGER_VERIFIED on the Mac.

**Mac results:**

| Run | Source | Result |
|---|---|---|
| Full suite (3h18m) | 5d18b4b | 9,694 cases: 9,089 passed, 583 skipped, **22 failed, 10 errors** |
| Focused set | 77769dc (fix) | 179 cases: 178 passed, 1 failed |
| Fix check | bdd852d | 19/19 passed |

The 32 problems at 5d18b4b have two causes, both diagnosed and repaired:

1. **12 child launches refused.** macOS adds `LC_CTYPE=UTF-8` (Python's PEP 538 coercion, since C.UTF-8 does not exist on
   10.14) and `__CF_USER_TEXT_ENCODING` to every process, and the child allowlist refused them. This was observed on
   the Mac with `env -i ... python3 -I`. The owner-approved narrow fix admits exactly those two names with their fixed,
   non-secret value shapes; everything else is still refused.
2. **10 failures and 10 errors in the ledger tests.** The test fixture used `git init -b`, which needs git 2.28 or
   later. It now uses `init` plus `symbolic-ref`, and only the test changed.

At 77769dc the single failure was the new refusal control itself. On macOS, CoreFoundation rewrites a forged
`__CF_USER_TEXT_ENCODING` to the real value before Python starts, so the forgery cannot reach the child (a safe
outcome). On darwin the control now forges a non-UTF-8 LC_CTYPE, and at bdd852d it passes 19/19 on the Mac.

**UNPROVEN on the Mac:** the complete suite at the final source. The focused set plus the targeted re-check were
run, and the full Mac rerun takes about 3.3 hours. It can run overnight or Thursday morning:
`zsh ~/stage5_mac_verify.zsh full` with the script updated to the final source.

## 3. Supported-runtime full suite and disarmed rehearsal (VERIFIED-RUN, Linux, Python 3.12.3, 47/47 pins)

| Run | Source | Result |
|---|---|---|
| Full suite | 5d18b4b | 9,694 cases: 9,111 passed, 583 skipped, 0 failed |
| Disarmed rehearsal (same suite under the non-loopback-refusing guard) | 5d18b4b | 9,111 passed, 583 skipped, 0 failed |
| Guarded rehearsal | 77769dc | 9,696 cases: **9,113 passed, 583 skipped, 0 failed**. The 583 skips are identical, there are 2 added cases, 0 removed and no status changes; 3 connects went to the dead proxy and 0 to outside hosts. bdd852d differs from it only in one test file, which was re-run: 19/19 on Linux and 19/19 on the Mac. |

- **Network:** the 5d18b4b rehearsal made 3 connect attempts in total, all to the dead proxy at 127.0.0.1:9, and 0 to
  any outside host. **No order or any other byte left the host.**
- **Code paths reached:**

  | Area | Reached |
  |---|---|
  | Order gate `gated_submit` and its submit chain | reached |
  | `validate_final_quote` and the conditional-plan authority | 18/18 |
  | WakeRegistry | 21/21 |
  | Arming, authorization and mission limits | 64/65 |
  | Risk | 38/40 |
  | Freshness, lock, ledger and lifecycle | 30/31 |
  | Hard flatten and emergency liquidation | 11/11 |
  | Production loop and scan cycle | 64/70 |

  The functions not reached are listed in section 6.
- **Skips (583) are not passes.** Their reasons:

  | Reason | Count |
  |---|---|
  | Archived production snapshot absent | 149 |
  | Canonical store not present | 70 + 24 |
  | EXTERNAL_EVIDENCE_REQUIRED forensic artifacts | 68 |
  | A specific archived snapshot absent | 59 |
  | Archived 1m tape absent | 40 |
  | git-ignored v2/v2.1 proposals | 31 + 17 |
  | Historical MNQ tape absent | 23 |
  | 10:52 specimen absent | 21 |
  | LIVE_ENV_REQUIRED (TopstepX credentials) | 9 |
  | Historical corpus absent | 8 |
  | Other | 64 |

## 4. Missing archive cases

About 440 skipped cases need operator archives, recorded tapes or forensic artifacts that are not in the repository
and were not accessed:

- archived production snapshots;
- the canonical store;
- archived and historical 1m tapes;
- dated specimens;
- EXTERNAL_EVIDENCE_REQUIRED artifacts;
- the historical corpus.

**Historical archive certification therefore remains UNPROVEN.** The 9 LIVE_ENV_REQUIRED cases need live
credentials and were deliberately not run.

## 5. Stage 4 / Stage 5 state

- **Stage 4 owner acceptance: PENDING.** The candidate carries the Stage 3/4 production-path repairs; none is
  owner-accepted.
- **Stage 5 is offline harness mechanics only**:
  - Mode A/B replay, fresh child per trajectory, quote-wake/trigger/final quote, six-layer scoring, owner A/B repairs;
  - all labels are CONSTRUCTED or FICTIONAL;
  - **current-Brain recognition is UNPROVEN on ratified sessions**;
  - sealed owner annotations, corpus and scoring thresholds are not supplied;
  - **Mode C (live model transport) is disabled and out of scope.**
- **Reserved owner decisions:** D11 to D14, plus the B combined opportunity-timing criterion.

## 6. Remaining repairs and UNPROVEN coverage

None of these blocks disarmed read-only observation. All of them block arming.

**Production-path functions no test reaches (UNPROVEN):**

- `ProductionLoop._latch_terminal_contamination` / `_terminal_cognition_result` and
  `session_cognition_lock.record_contaminated`: the terminal cognition-contamination latch.
- `ExecutionRunner._reconcile_after_recording_failure`, `_emergency_recording_marker`, `adopt_venue_protection` and
  `mission_owned_working_orders`.
- `ProductionScanCycle._recover_active_path` and `in_decision_window`.
- `MissionState.bind_exit_attribution`, `combine_risk.all_in_risk_for` and `daily_loss_budget._tfield`.
- The live-session and client read and hub methods.
- `main()` itself, which needs live authentication.

**Proposed shortest fix:** targeted tests for the contamination latch and the recording-failure recovery. Target:
Friday Oct 23.

**Other findings:**

- `ExecutionRunner.revalidate_before_submit` is **dead code**. The live gate uses `_assess_freshness`, which was
  reached.
- The legacy `paper_execution` (Alpaca) tests `test_phase_2b_monitor_enforcer` and `test_phase_4b_broker_stop` make
  un-mocked HTTP attempts. These are off the TopstepX path and were refused by the dead proxy. The fix is to mock them.
- Mac full suite at the final source (section 2). Target: overnight or Thursday morning.

## 7. Conditions for Thursday's supervised read-only observation, with operator monitoring and rollback

1. **Authorization:** Maurice's separate read-only authorization, plus his choice of observation source (candidate
   bdd852d or production cbfaddb).
2. **Checkout:** a fresh checkout on the Mac at the chosen commit, with the operator's own `.env`, never committed.
   The `venv` is built from requirements.txt (the script showed all 47 pins install on this Mac).
3. **Command:** never pass `--arm`. Export
   `TOPSTEPX_ARM_ORDERS=false EXECUTION_ENABLED=false ALLOW_PAPER_ORDERS=false`, then run:
   - first `PYTHONPATH=src python3 tools/topstepx_production_session.py --proof --observe 60`;
   - then `--until-close` or `--scans N`.
4. **Confirm on screen before relying on output:**
   - `ARM STATE : DISARMED` and `ARMED : False`;
   - no `PRODUCTION SESSION REFUSED`;
   - the expected account label and contract;
   - `ACCOUNT STILL FLAT : True`;
   - "No order will be placed: the session is not armed."
5. **Monitor:**
   - quote and candle consumers attached;
   - reconnect count;
   - the scan cadence (60s);
   - any `HARD FLATTEN` or `RECOVERY` line, which means stop and review;
   - Brain call outcomes (validation and repair) and any cognition-lock refusal.
6. **Stop and rollback:** Ctrl-C (the pump joins, the hub closes once). Return to the production checkout at
   cbfaddb. There is no state migration.
7. **Mac caveats:**
   - **macOS 10.14 no longer receives security updates.** That is acceptable for supervised read-only observation;
     upgrade it before any credentialed unattended use.
   - This Intel Y-series MacBook Air runs the suite about 1.4x slower than the verification host.
   - Live scan latency on this Mac is UNPROVEN until observed.
   - The live read-only path (authentication, hubs, `main()`) has not run on this Mac.

If any check in condition 4 fails, observation does not start. The shortest fix and a Friday Oct 23 re-verification
apply.
