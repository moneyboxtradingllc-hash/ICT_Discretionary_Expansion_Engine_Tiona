# Readiness assessment for a supervised TRADING session on 2026-10-23 (America/New_York)

Requested by Maurice via Codex (2026-10-23 02:33Z). Prepared offline from the existing record only: no live run, no
provider call, no order, no merge. Labels: VERIFIED-RUN (executed, evidence exists), VERIFIED-CODE (read from the
frozen source), OWNER-RESERVED, UNPROVEN, UNKNOWN.

## Verdict: NOT READY under the existing ratified requirements

The board in force (`GO_NO_GO_BOARD.md` §Verdict; `final_ffe00ae/CLOSEOUT_REPORT.md` last line) states: arming or
funded trading is **NO-GO** until Stage 4 owner acceptance, current-Brain recognition on ratified sessions, sealed
annotations and scoring, historical archive certification and supervised-rollout approval are complete. None of these
has changed since. Tomorrow's session is therefore possible only through explicit owner decisions (section 4), not
through any engineering result available tonight.

## 1. Exact identity

| Item | Value | Status |
|---|---|---|
| Candidate source | ffe00aef3db7fb2339780ed0fa9016149923c96e, tree 57cc69c03882efc9bd1d6a7921f4fea6792a31cc (`release/stage5-rc-20261022`, not merged) | VERIFIED-RUN |
| Production source today | `feature/latency-1-preauthorized-plans` cbfaddb; 85 commits behind; 39 production-path files differ | VERIFIED-CODE |
| Protected pins | LEDGER_VERIFIED: 32 pins, 48-file Brain/retrieval closure, brain:3d9878ad3ff57f1f, retr:0c241bdb8234d1ba | VERIFIED-RUN |
| Brain model contract | `gpt-6-luna` (Luna tier); an armed session refuses unless `AI_BRAIN_MODEL` equals it; model fallback NONE; JSON mode enforced; reasoning effort API default; Brain contract fingerprint …f57f1f | VERIFIED-CODE (`ai_brain/production_model.py`, startup telemetry) |
| Retrieval | AI retrieval DISABLED; descriptive memory empty (0 records) | VERIFIED-CODE |
| Runtime | operator Mac, macOS 10.14.6, Python 3.12.7, 47/47 pins; full suite 9,116 passed / 583 skipped / 0 failed | VERIFIED-RUN |

## 2. Requirement-by-requirement evidence

| Requirement | Evidence | Status |
|---|---|---|
| Account and contract pinning | Pin law refuses on missing/ambiguous/foreign account or fingerprint mismatch (Codex re-ran 14 checks); live startup record 2026-10-23T00:45:43–00:46:01Z accepted the rebound reset-account pin; contract CON.F.US.MNQ.Z26 for quotes and candles | VERIFIED-RUN (bounded) |
| Startup connectivity | Startup-record check CLOSED by Codex (feed advanced 180→181, flat, disarmed, clean shutdown telemetry) | VERIFIED-RUN (bounded) |
| Ratified sizing / risk limits | Max 2 bot trades/session, 1 attempt/trade, all-in risk doctrine max $350/trade, configured daily loss budget $725 (module default; the binding value is the one signed into the session authorization), stop 0–35 pts preferred, 50 pts ceiling, max 15 MNQ, compounding OFF; authorization refuses anything above doctrine (`AUTHORIZATION_EXCEEDS_DOCTRINE`) | VERIFIED-CODE |
| Decision window / hard flatten | Enforced window 09:00–14:00 America/New_York; hard flatten at window end runs regardless of `--arm` | VERIFIED-CODE |
| Integrated decision-to-order path | `gated_submit` → freshness → objective/invalidation → submit-time risk recheck → final quote → protection → `submit`, reached in the offline suite **only against refusing venue doubles** (S4-06). Never executed against the live venue at ffe00ae | VERIFIED-RUN offline; **UNPROVEN live** |
| Current-Brain decisions | Stage 5 harness is offline mechanics with CONSTRUCTED/FICTIONAL labels; Mode C (live model transport) disabled; no live `gpt-6-luna` call has been made at this source; sealed owner annotations, corpus and scoring thresholds not supplied | **UNPROVEN** |
| Order/position reconciliation and management | Reconcile/manage and hard-flatten/emergency-liquidation paths reached in tests (11/11 flatten/liquidation functions). Unreached: live user hub (`connect_user_hub`), `order_by_id`, `recent_trades`, `_recover_active_path`, `bind_exit_attribution`, client `close_position_partial`/`order_history`/`trade_history` | Offline only; live **UNPROVEN** |
| Stop / shutdown controls | Ctrl-C (pump join, hub close), STOP file `data/integration/topstepx/deterministic/STOP`, hard flatten at window end, emergency liquidation | VERIFIED-CODE; shutdown telemetry seen in startup record only |
| Armed-session authorization | Armed run requires a signed per-date authorization (`tools/topstepx_issue_session_authorization.py --session-id --date`) matching account fingerprint, contract, Brain model/contract and retrieval state, within doctrine | Not issued for the reset account (UNKNOWN until issued) |
| Reset runbook trading steps (`docs/topstep_combine_reset_runbook.md` 5–8) | Fresh authorization with a NEW session id; flat/tradeable check; **manual Auto OCO / bracket check in the Topstep UI (a reset appears to clear it; the 2026-08-10 rejection occurred while it was off)**; read-only preflight before arming | Not done (excluded by every authorization so far) |
| Supervised operating procedure | No ratified operating contract (D10) for an armed or continuous session at ffe00ae; Codex's observation draft is NOT AUTHORIZED | **OWNER-RESERVED** |
| Stage 4 acceptance | All rows S4-01…S4-11 and T01…T22 PENDING owner acceptance; no engineering defect established | **OWNER-RESERVED** |
| Archive certification | ~440 archive/credential-dependent cases skipped, never counted green | UNPROVEN |
| Operator host | macOS 10.14 receives no security updates (board: upgrade before credentialed unattended use) | Known caveat |
| Account mode | 50K Combine reset account; `simulated` flag was not recorded in the sanitized evidence | UNKNOWN |

## 3. What is complete vs. what is not

- **Completed engineering:** frozen source, pins, full suites (Linux and Mac), disarmed rehearsal with network guard,
  Stage 3/4 repairs (unaccepted), corrected tooling, rebind helper.
- **Startup proof:** connectivity, pinning, feed, flatness and shutdown telemetry for one disarmed run (closed).
- **Current-Brain recognition evidence:** none on ratified sessions; no live model call at this source.
- **Owner-dependent acceptance:** Stage 4 acceptance, D01/D03/D04/D10/D11/D13 (D11–D14 are proposals), source choice,
  minimum-history requirement (S4-08), operating contract.

## 4. Genuine owner choices and their consequences

1. **Source.** ffe00ae carries the reviewed Stage 3/4 repairs but has never run armed live. The production branch is
   what previously ran on the account (armed sessions are recorded, e.g. `docs/production/sessions/PROD-20260812_POSTMORTEM.md`;
   whether cbfaddb itself ran armed is not verified here), but it lacks those repairs and so carries the defects they
   fixed. Either choice is an owner decision.
2. **Stage 4 acceptance.** Accept the bounded evidence (sign-off) or explicitly waive it for one session. Without
   either, the board's NO-GO stands.
3. **Brain recognition requirement.** Supply/await ratified-session recognition evidence, or explicitly accept that the
   first live `gpt-6-luna` decisions at this source will be made with orders enabled.
4. **Operating contract (D10).** Signed daily loss budget for the authorization (configured default $725; doctrine caps
   above apply), session duration within the 09:00–14:00 ET window, supervision and stop criteria, model-call/spend
   bound, handling of any existing position or order.
5. **Combine exposure.** A rule breach on the 50K Combine fails the evaluation (reset cost). Trailing-drawdown room is
   read from the venue at scan time, so it is UNKNOWN until then.

## 5. If the owner chooses to proceed tomorrow

Operator steps, all before 09:00 ET, all within the existing runbook, none performed yet: confirm Auto OCO / brackets in
the Topstep UI; issue the signed session authorization with a new session id and the owner's signed daily loss budget;
run the read-only account preflight (flat, no working orders, tradeable); then the armed supervised session under the
owner's operating contract, with Tiona present and able to stop it. Each step needs Maurice's explicit authorization;
this assessment grants none.

Prepared without any live action. Nothing here authorizes connecting, arming, trading, merging or deploying.
