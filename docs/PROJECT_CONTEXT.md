# Project Context — ICT Discretionary Expansion Engine (Tiona)

*Written 2026-10-02 against commit `95170d8` (2026-09-28, branch
`claude/optimistic-turing-bxpw5k` history). **Updated later on 2026-10-02 for the
deployed production build `cbfaddb` (LATENCY-1, branch
`feature/latency-1-preauthorized-plans`) and sessions PROD-20261001/02.** Purpose: let
any new session or person rebuild full context from the repository alone, so no
single chat is a single point of failure.*

**[ops]** below means taken from the operator's session reports to Maurice
(2026-10-01/02), not from the repo. Account IDs and balances are left out on purpose.

**How to read the confidence markers.** Statements marked **[code]** were checked
against source at this commit. **[doc]** means taken from a repo doc or commit
message and not independently re-verified. **[unverified]** means I could not
establish it from the repo — ask the owner. Section 13 lists what was *not* checked.

---

## 1. TL;DR

- An automated **MNQ futures trading bot** for a **TopstepX / ProjectX** account.
  ~96k lines of Python in `src/`, ~320 test files, ~70 docs, 103 commits. **[code]**
- Built around ICT-style concepts (liquidity sweeps, PO3, order blocks, displacement,
  protected swings) with a strict "organism" ethos: every decision leaves a
  recorded reason, evidence is never fabricated, and the system fails closed.
- Two lanes: a **production Brain lane** (an external LLM, `gpt-6-luna`, owns
  direction; the rest is deterministic machinery that qualifies, sizes, executes
  and protects) and a **deterministic brain-off lane** (rules only).
- It is **sim/practice-first**. Orders are disarmed by default; arming needs a
  durable, signed session authorization. Nothing here authorizes live money.
- Work is governed by **written rulings from Maurice** (architect). Tiona/Nas is
  the operator who runs sessions and relays results.
- September work: LLM-call cost control (wake controller), model identity
  enforcement, stair-step profit protection, TopstepX-resolved contract month,
  volume-at-price evidence, and an observe-only factual news layer (NEWS-2).
- **Production now runs LATENCY-1** (`cbfaddb`, `brain:0ec4ef07c75dbcef`). The Brain
  can publish a *pre-authorized conditional plan* (an exact zone + expiry); when price
  reaches the zone, mechanics execute it without calling the Brain again. Session
  PO3 is now context, not an entry veto. Size and risk are recomputed from the final
  executable quote. Two live sessions on this build (10/01 +$1,452.08, 10/02 −$42.20);
  **four defects are waiting on Maurice's rulings** (§12). **[code/ops]**
- **Branch split:** production and the NEWS-2/docs branch diverge at `49550b5`.
  NEWS-2 is **not** in the production build. See `CLAUDE.md` → "Which code is live".

## 2. People and working model

| Who | Role |
|---|---|
| **Tiona (Nas)** | Operator. Runs terminals/sessions, relays output. Prefers simple, step-by-step instructions with copy-pasteable commands *(from earlier chat history, not the repo)*. |
| **Maurice** | Architect. Issues formal written rulings on doctrine, risk rails and authority; code and doctrine changes follow his rulings *(from earlier chat history)*. A NinjaTrader lane also exists in the repo (`src/integrations/ninjatrader/`) and is not part of the TopstepX path. |
| **Claude** | Writes code and analysis, runs tests. Commit bodies record the reasoning. |

The repo is called "…Tiona" because it is the TopstepX-lane adaptation of the
engine; `docs/archive/deploy2_maurice_tiona_separation.md` records how the two
operators' instances were separated. **[doc]**

## 3. The two lanes

| | **Production Brain lane** | **Deterministic lane** |
|---|---|---|
| Entry | `tools/topstepx_production_session.py` → `broker/topstepx_production_loop.py` | `launch_topstepx_mnq_deterministic.sh` → `integrations.topstepx.deterministic.loop` |
| Direction author | External Brain (`gpt-6-luna`), validated by deterministic contracts | `deterministic_sim_author` (no LLM; `OPENAI_DISABLED_FOR_INTEGRATION=1`) |
| Risk constants | `topstepx_combine_risk.py`: preferred stop 35 pt, absolute 50 pt, max 15 contracts, max $350 risk. `topstepx_session_authorization.py`: daily loss budget $725, 2 trades/session, 1 attempt/mission, window 09:00–14:00 ET **[code]** | `deterministic/__init__.py`: target 35 pt, max stop 25 pt, $500/trade, max 30 contracts, 2 trades/day, daily loss ceiling $1,000, window 09:30–14:00 ET **[code]** |
| Arming | Durable session authorization + `--arm` | `TOPSTEPX_ARM_ORDERS`, pinned `false` by the launcher |
| Status | The active line. Deployed build: `cbfaddb` (LATENCY-1) on `feature/latency-1-preauthorized-plans` | Stable reference lane; proved the pipeline end to end in July (see §10) |

**Do not mix the constants.** They are different lanes with different owners.
The numbers in an older chat handoff (45 pt stop, $250, 09:30–16:07 ET) match
neither table above — see §13.

## 4. Production-lane pipeline

From `docs/EVENT_DRIVEN_BRAIN_WAKE_20260911.md` **[doc]**, call graph per scan:

```
tools/topstepx_production_session.py::run_production_scans
  -> ProductionLoop.scan_once
     -> reconcile_missions            continuous venue truth
     -> manage_open_position          continuous protection / break-even
     -> entry-authority-exhausted gate
     -> candle fetch, continuity repair, coherent window
     -> ProductionScanCycle.scan
        timeframes + HTF context -> continuity/revision convergence
        -> one executable quote -> snapshot_builder.build_snapshot
        -> sweep accounting -> active-path synthesis
        -> state transition + setup lifecycle -> council
        -> retrieval + telemetry -> structure-flip registry
        -> narrative_brain.run_narrative_brain
             build_brain_input -> authorized objective/invalidation catalogs
             -> BrainWakeController.observe   (final pre-provider gate)
             -> _call_llm -> normalize/repair/fallback
     -> brain_sleep_hold short-circuit
     -> CandidateProducer.produce   (sovereign LLM only)
     -> daily-loss governor, sizing, mission, risk, execution
```

Key properties: reconciliation and open-position management run **before** the
scan, so protection never waits on cognition. Stop authority is the **exact
structural invalidation**; target authority is the Brain-selected liquidity
objective; bracket authority is bot-authored geometry, **not** Topstep Position
Brackets (which must be disabled on the account) **[code: `topstepx_production_doctrine.py`]**.

### 4a. Changes in the production lineage after `49550b5` (all **[code]** at `cbfaddb`)

These commits have no message bodies; the descriptions come from their diffs.

| Commit | Mission | What it does |
|---|---|---|
| `a8ba9d5` (09-28) | BRAIN-SOVEREIGNTY-SESSION-PO3-CONTEXT-1 | Session PO3 becomes `AUTHORITY_CLASS = "CONTEXT_ONLY"`. Its phase is passed to the Brain as `session_phase_context` (a "permissive"/"caution" posture with a reason) and is no longer part of the hard authorization conjunction or the gate's blocking factors. The Brain may disagree with it and must explain why. Fingerprint → `brain:0cf842782313d826`. |
| `5387300`, `45f9e97` (09-29) | FINAL-QUOTE-ECONOMICS-1 | Just before submit the runner captures the **final executable quote** and reprices economics from it with the thesis levels held fixed (`_capture_final_executable_entry`, `_reprice_production_economics`). A missing or unusable quote, a wrong-side stop or target, or R:R below the gate → refuse; there is no fallback to the planned price. The quantity may be resized **down** at the final quote (`45f9e97`). Results are recorded as `final_quote_economics`. |
| `3f90e2d` (09-30) | LATENCY-1 | **Pre-authorized conditional plans.** A Brain answer of `current_action = "watching"` with an explicit future `plan_expires_at` and an exact execution-object zone publishes one plan. While it is armed, no new blocking Brain call starts. When the quote reaches the zone, `handle_pending_conditional_wake` rebuilds the mechanical scan and executes or refuses **without calling the Brain**. Mechanics may only execute or refuse; they cannot change direction, playbook, object or levels. Expiry or invalid evidence clears the plan. Timing is logged to `conditional_plan_events.jsonl`. Fingerprint → `brain:0ec4ef07c75dbcef`. |
| `cbfaddb` (09-30) | LATENCY-1 telemetry repair | Fixes provider-timing telemetry for plan events. Fingerprint unchanged. |

In practice only **FVG** plans can publish: `ote_after_reclaim` and `rejection_block`
choices carry no exact zone and are refused with `conditional_plan_zone_unavailable`. **[ops]**

## 5. Brain and model governance

- **Single authority**: `src/ai_brain/production_model.py`. `PRODUCTION_MODEL =
  "gpt-6-luna"`. Forbidden as production models: `gpt-5.6` (alias→Sol),
  `gpt-5.6-sol`, `gpt-5.6-terra`, the previous `gpt-5.6-luna` (needs fresh
  authorization), `gpt-6-sol`, `gpt-6-astra`, and `gpt-4o-mini`. For an armed session the model must be explicit or the session
  refuses. **[code]**
- **Luna now, Terra later**: Luna was chosen for the PRAC validation period on cost
  (a Terra segment on 2026-08-19 spent 739,891 tokens over 29 scans, all stand-downs).
  Terra is *reserved* for the Combine phase and returns only via a fresh
  authorization, never a config toggle. **[code comment, dated 2026-08-19]**
- **Provider identity is enforced** (`49550b5`): `_call_llm` compares the served
  model to the requested one; mismatch or missing → fail closed with
  `provider_model_mismatch`, no repair, no retry on another model. **[doc]**
- **Brain contract fingerprint**: hash over 30 ordered source files + the retrieval
  policy fingerprint (rule and list in `docs/REPOSITORY_CERTIFICATION_20260910.md`).
  Authorizations bind to it. **Production (`cbfaddb`): `brain:0ec4ef07c75dbcef`**,
  recomputed here with pinned dependencies and matching the pin in
  `tests/test_brain_fingerprint_portability.py`. The NEWS-2/docs branch is
  `brain:3a09895222765f22` (same as `49550b5`). The fingerprint is only correct when
  computed with dependencies installed (see `CLAUDE.md`). **[code]**
- **Model selection doctrine** (`docs/model_selection_doctrine.md`, 2026-08-04):
  replay proves *compatibility*, live proves *value*. Paid replay bake-offs are
  cancelled. Only the frozen live **ADAPTIVE-8** campaign (10+ sessions and 20–30
  completed trades, no mid-campaign tuning) may say a model is better. Until then a
  model is "contract-compatible, unproven." **[doc]**
- **Wake controller** (`src/ai_brain/wake_controller.py`): lets only the *paid Brain*
  sleep; the mechanical organism never does. `BRAIN_WAKE_MODE` = `OFF` (template
  default) / `AUDIT` (counterfactual accounting, still calls the LLM) / `ENFORCE`
  (earned HOLD returns `brain_sleep_hold` before any provider call). Max-silence
  backstop default 300 s. **[code/doc]**
  - History: `ed810ec` fixed a shape bug that made ENFORCE structurally unable to
    suppress (541/541 scans "malformed evidence"). `PROD-20260922` was the first
    session where ENFORCE suppressed calls (38 of 593 scans held). `713f1cc` added
    `HELD`, `BUDGET_EXHAUSTED`, `GOVERNOR_UNPROVEN` dispositions so that was not
    misreported as an accounting failure. **[doc]**
  - The original wake doc says historical acceptance is **not proven** (the three
    real pre-provider replay bundles were absent) and ENFORCE was not approved by
    that work. Operators have since run ENFORCE sessions; treat enabling it as an
    owner decision. **[doc, partly unverified]**
- **ECU mode** (`BRAIN_ECU_MODE`, default off): when on, the Brain thesis is produced
  *inside* snapshot building, before later facts exist; the wake controller always
  WAKEs in that mode. The legacy `launch_paper_session_fc.ps1` sets it on. **[doc]**

## 6. Position management and protection

All **[doc]** from commit subjects/bodies unless noted:

- Every trade is a **mission** under a **session authorization**; the single attempt
  is consumed by the *attempt*, not the fill (a venue rejection spends it).
  Code: `topstepx_mission_state.py`, `topstepx_mission_recovery.py`,
  `topstepx_mission_reconciler.py`, `topstepx_session_authorization.py`. **[code]**
- Stops are bound to **structural invalidation identity** (`5dc7fd0`); post-fill
  establishment is staged and verified (`eb5cb0d`; stages recorded per `713f1cc`:
  POST_FILL_AUTHORIZED → STRUCTURAL_STOP_PROVEN → STRUCTURAL_PROTECTION_VERIFIED →
  STRUCTURAL_BASELINE_ARMED).
- Profit protection: break-even bound to trade lifecycle identity (`ce95a26`);
  deterministic **stair-step** protection (`c0e741e`); `989ae89`
  *PROTECTION-2_5R-FIRST* lets a position "breathe" before trailing begins.
  *"Miss Juicy"* appears in that commit subject as a nickname; its meaning is not
  defined anywhere in the repo **[unverified]**.
- Safety nets: hard flatten and emergency liquidation modules
  (`topstepx_hard_flatten.py`, `topstepx_emergency_liquidation.py`), auto-flatten
  before the close (`c082381`), pre-submit candidate freshness refusals (`5db34d4`),
  protected-swing invalidation truth (`64e451f`).
- Daily-loss governor (`daily_loss_budget.py`): refuses on *proven* exhaustion
  (`BUDGET_EXHAUSTED`) vs *cannot establish truth* (`GOVERNOR_UNPROVEN`).
  `DAILY_LOSS_BUDGET_USD = 725` is an "OWNER LAW (2026-08-31)" — a budget, not a
  guarantee (a gapping stop can exceed it). **[code]**
- Account protection state is **not measurable** via the API; it requires a dated,
  account-bound operator attestation (`topstepx_protection_authority.py`). **[doc]**

## 7. News layer

- `src/news/news_engine.py` (NEWS-1): **off by default** (`NEWS_LAYER_ENABLED`). Fail-open
  bug fixed in `95170d8`: missing/stale sources now yield `risk_state="unknown"`,
  never "normal".
- `src/news/factual/` (NEWS-2, new): official-source calendars (BLS, FOMC, FRED
  dates; ForexFactory only as cross-check), reconciliation that keeps conflicts
  visible, MNQ overnight move from TopstepX bars, delayed-close VIX/VXN/10Y labelled
  as such, headline records without sentiment, and an empty, fenced,
  non-sovereign interpretation slot. `authority=observe_only`, `brain_input=False`,
  no model calls. Owner ruling 2026-09-27: *facts and provenance in code; no model
  pre-interprets the world.* Tools: `tools/news2_refresh.py`,
  `tools/news2_event_window_audit.py`. **[doc]**
- **NEWS-2 is not in the production build.** It lives on the
  `claude/optimistic-turing-bxpw5k` / docs lineage only. Maurice's 10/01
  authorization lists NEWS-2 among the changes that are not to be made. **[code/ops]**

## 8. TopstepX venue facts

(`docs/topstepx_integration.md`, verified against official docs 2026-08-04 **[doc]**)

- REST `https://api.topstepx.com`; user hub `https://rtc.topstepx.com/hubs/user`;
  market hub `https://rtc.topstepx.com/hubs/market`. SignalR JSON protocol is
  implemented natively on `websockets` (no `signalrcore`).
- **Account pinning law**: refuse rather than choose when zero/multiple accounts
  match, `canTrade` or `isVisible` is false, or the fingerprint changed. Prefer
  `TOPSTEPX_ACCOUNT_ID` over name. List order is never a preference.
- **Contract discovery**: only `activeContract == true`; refuse ambiguity (mid-roll)
  and invalid tick metadata. Since `8ea3480` (2026-09-20) **TopstepX is the
  contract-month authority** and the launcher and authorization verify against the
  venue-resolved contract.
- Read-only is structural: `TopstepXReadOnlySession` has no write methods, and a
  positive endpoint allowlist denies anything unknown.
- Redaction (`topstepx_redaction.py`): total masking, JWT-shape matching,
  non-reversible account fingerprints, `assert_clean` write guard.
- Sizing is bounded by the Topstep **trailing drawdown** (`TOPSTEP_ACCOUNT_SIZE`
  = 50K/100K/150K in `.env`). Fixed round-trip costs measured at $1.22/contract;
  slippage reserve is 2 ticks/side and **not yet measured** (needs 20 reliable
  observations / 10 round trips). **[code]**

## 9. Evidence, sessions, and ops

- Sessions are named `PROD-YYYYMMDD`. Durable artifacts (gitignored `data/`) include
  the session ledger, flight recorder, decision/candidate ledger, wake decisions
  (`data/replay_sessions/<session>/memory_retrieval/brain_wake_decisions.jsonl`),
  AI-call ledger, slippage ledger. Post-session tools in `tools/`:
  `topstepx_session_outcome_report.py`, `topstepx_trade_postmortem.py`,
  `topstepx_evidence_export.py`, `reconcile_session_activity.py`,
  `seal_session_archive.py`, `topstepx_candle_coverage_audit.py`.
  Written postmortems: `docs/production/sessions/` (PROD-20260806 … 20260812).
- Candidate accounting must reconcile: every scan ends in a terminal disposition
  (`CANDIDATE_DECISION_ACCOUNTING_FAILURE` fires on unclassified scans).
- Session authorization/verification tools: `tools/topstepx_issue_session_authorization.py`,
  `tools/verify_authorization.py`, `tools/prac_release_preflight.py`,
  `tools/preflight_account_state.py`.
- Launchers: `.sh` for macOS/Linux and `.ps1` for Windows. The TopstepX lane got its
  macOS launcher on 2026-08-26 so a second operator could run it.

### 9a. Session-day sequence (as run for PROD-20261001) **[ops]**

1. Maurice issues a written authorization bound to the exact branch, SHA, model,
   fingerprint and session date. That authorizes *readiness*, not arming.
2. The operator checks venue settings in the TopstepX UI and records the dated
   **protection attestation** (Position Brackets OFF, bot-attached brackets).
3. Issue and verify the session authorization (`PROD-YYYYMMDD`, state UNSPENT).
4. Run `--final` production preflight. **24 gates** must pass: clean tracked source,
   known fingerprint, PRAC/simulated account pin, contract resolved, flat, no bot
   orders, protection attested, risk constants, brain enabled, production model,
   zero provider calls during preflight, and a valid session authorization.
5. Stop and report. Arm only on Maurice's separate explicit ARM / GO.
6. After the close: a session report labelled VERIFIED / INFERRED / UNKNOWN, a
   build-aware scorecard, and an explicit "no code/config/.env change" statement.

### 9b. Live sessions on the current build (`cbfaddb`) **[ops]**

| Session | Net | What happened |
|---|---|---|
| **PROD-20261001** | **+$1,452.08** (2 trades, 2 wins) | T1 long 4 (ordinary `enter`, final quote resized 6→4): target hit, +2.67R. T2 short 7: +1.99R, the first live proof of the 2.5R stair locking profit. **T2 came through Defect 1** (a verbose "watching:" answer treated as an immediate entry, outside the zone the Brain authorized). 9 plans published, 7 triggered, trigger→mechanics decision about 3 s; 0 plan executions. Brain timeouts 91/284 (32%), about 64% failed 09:30–11:30. |
| **PROD-20261002** | **−$42.20** (1 fill) | T1 refused before submit (RISK_DRIFTED; the refusal likely avoided a loss). T2 was the **first trade executed from a LATENCY-1 plan**, 2.3 s from trigger to submit. A 1-tick fill pushed all-in risk to $352.20 against the $350 cap → POST_FILL_REFUSED → flatten. The flatten returned no order ID → session **CONTAMINATED** for the remaining 3 h 17 min (Defect A). Timeouts 28/358 (7.8%). |

Scorecard (a ledger, not a grade): current build 2 sessions, +$1,409.88; all builds
14 sessions, 14 trades, −$362.46. Management is the **2.5R stair**, confirmed by
Maurice for 10/02.

## 10. History (condensed)

Eras reconstructed from `git log` and `docs/evolution/TIMELINE.md` **[doc]**:

| When | What |
|---|---|
| Jun–early Jul 2026 | Original multi-symbol engine (Alpaca/Topstep-era), memory, retrieval, adaptive loops; July 10 retirement of legacy AI wrappers (TIER-2A/B), volume witness |
| Jul 11–12 | Evidence-driven audits: rule R-001 was **demoted** enforce→shadow after it fired on 58.8% of all scans; the narrative-gate audit (NA-1) ended **NO CHANGE**. The repo records NO CHANGE/REJECTED results as prominently as wins |
| Jul 22–23 | Deterministic lane fixes (risk-based sizing, warm-up 2,000 bars, P&L from broker, date-aware session, window to 14:00). Two sessions: −$470, then +$962 (net +$492). **N=2 — pipeline proven, edge not proven** (`docs/BOT_STATE_2026-07-23.md`) |
| Jul 24–28 | Large ICT-structure build (order blocks, MARKET-CONTEXT, PO3 reconcile, displacement confluence); authority doctrine: *direction from Liquidity and PO3; structure confirms only*; TopstepX lane without NinjaTrader; Topstep MLL modelled |
| Aug 4–6 | Model-selection doctrine; Terra migration; native TopstepX integration phases 0–3 |
| Aug 19–20 | Luna chosen for PRAC; risk-doctrine migration (ceiling to 50 pt, risk to $350) |
| Aug 31–Sep 3 | Owner-law daily loss budget; `LUNA-*` lineage missions (venue-minted close lineage, protective child lineage, daily-governor attribution); Brain switches + instrument template |
| Sep 4–10 | `PROD-20260904` venue-rejection-with-no-order-id incident and review; a run of `PROD-20260908/09` forensic/accounting repairs; repository recertification (LF fingerprint, PyYAML pin) |
| Sep 10–15 | Pre-Brain wake shadow audit, wake controller, stair-step protection, fill-latency observability, structural-risk evidence, VAP evidence |
| Sep 20–28 | TopstepX contract-month authority; wake evidence-shape fix; decision accounting for held scans; protection 2.5R-first; swing invalidation truth; freshness refusals; **GPT-6 Luna** (Sep 25); provider-identity enforcement (Sep 27); **NEWS-2** (Sep 28, off the production line) |
| Sep 28–30 | Production line: Session PO3 demoted to context (`a8ba9d5`); final-quote economics (`5387300`, `45f9e97`); **LATENCY-1** pre-authorized conditional plans (`3f90e2d`) and telemetry repair (`cbfaddb`). 9/29: a flatten close contaminated the session (first Defect A). 9/30: 23% Brain timeouts |
| Oct 1–2 | First two live sessions on LATENCY-1 (§9b). Maurice is reviewing the evidence before issuing the next mission |

## 11. Architectural laws (recurring lessons)

1. **Silent drops** are the fingerprint of every hard bug — record a reason for every
   discarded candidate.
2. **One input must not veto a consensus** (one timeframe's exhaustion, one neutral
   TF collapsing a 3-of-4).
3. **Fixed constants over variable instruments** break (a 25 pt cap across
   instruments with 20× different point values). Borrow *laws*, never *numbers*.
4. **A key I looked for being absent is not the thing being absent.** Read the
   producer's actual shape; fixtures that mirror a bug hide it.
5. **"No" vs "cannot tell"** are separate states and must stay separate.
6. **Observe before authority.** New intelligence is observe-only until ruled on.
7. **Don't claim what the venue can't support** — replay for compatibility, live for value.

## 12. Open items and known gaps

### Waiting on Maurice's rulings (reported 2026-10-01/02; no fix made yet)

Code references were checked at `cbfaddb`. Status: as of 2026-10-02, Maurice said he is
reviewing the evidence before issuing any next mission. No code was changed.

1. **Defect A (high): a flatten close with no order ID contaminates the session.**
   The emergency `POSITION_CLOSE` returns success with no venue order ID
   (SUBMISSION_UNKNOWN). The daily-loss governor then sees an in-session trade it
   cannot attribute → `CONTAMINATED` / `unattributable_in_session_trade`
   (`daily_loss_budget.py:65,267`) → `GOVERNOR_UNPROVEN` → every later entry is refused.
   This cost 9/29 (30 candidates blocked) and 10/02 (3 h 17 min, 60 refusals).
2. **Defect B (medium; touches risk/sizing, which are frozen): entry slippage counted twice
   after the fill.** The post-fill check (`topstepx_execution_runner.py` around
   1478–1517, `all_in_risk_for`) measures gross risk from the actual fill and *also*
   charges the full provisional slippage reserve (2 ticks in + 2 out). Combined with
   sizing to within $2.80 of the $350 cap, any 1-tick slip on a 10-lot forces a flatten,
   which then triggers Defect A.
3. **Defect 1 (high): verbose "watching:" answers become immediate entries.** Plans are
   recognised only when `current_action` is exactly `"watching"`
   (`luna_candidate_producer.py:1219`, `topstepx_production_loop.py:1088-1090`), and
   `NON_ENTRY_ACTIONS` (`luna_candidate_producer.py:1441`) does not include it.
   `"watching: … do not enter at the current price"` therefore takes the ordinary entry
   path. This produced 10/01 T2 outside the authorized zone. It did not recur on 10/02
   (all answers were the bare token), but it is still unfixed. Suggested fail-closed
   rule: anything starting with "watching" is either a plan or refused, never an entry.
4. **LATENCY-1 telemetry/accounting.** (a) Refused plans record stale economics and a
   `submission_started` event copied from an earlier trade (`_execute_conditional_plan`
   reads `runner.final_quote_economics` regardless of outcome). (b) New `conditional_plan_*`
   reasons and `tool_not_detected` are UNCLASSIFIED → `CANDIDATE_DECISION_ACCOUNTING_FAILURE`
   (18 on 10/01, 22 on 10/02). (c) The mission exit is recorded as "unattributed".

### Other live observations **[ops]**

- **Brain provider timeouts** (`APITimeoutError`): 9/30 23%, 10/01 32% (clustered at the
  open), 10/02 7.8%. Completed calls take p50 about 30 s, max about 46 s. Cause unknown.
  Timeout tuning is frozen. A read-only timeout autopsy request from Maurice was
  withdrawn the same day. Degraded scans fail closed (no candidate, no plan).
- **Plan coverage:** 12 (10/01) and 20 (10/02) "watching" answers could not publish,
  because only FVG objects carry an exact zone. While a plan is armed the Brain is
  mostly silent; this is by design but was raised as an observation.
- **Window-end exit leaves a mission unreconciled:** after 14:00 ET,
  `should_continue()` ends the loop on a flat venue read without a final reconcile, so
  10/01 T2's mission file stayed `POSITION_OPEN`. Minor; the venue facts are recoverable.

### Carried from earlier

- **Wake ENFORCE historical acceptance** was not proven when written (replay bundles
  absent). Decide whether ENFORCE is acceptable for the Combine phase. **[doc]**
- **ADAPTIVE-8 live campaign**: model comparison is not yet sayable; Terra is held
  for the Combine phase. **[doc]**
- **Reissue authorizations** after any Brain-contract change. This is routine now:
  every session gets a fresh, SHA-bound authorization (§9a).
- **Slippage reserve is unmeasured**; automatic reserve updates are disabled. **[code]**
  Live fills so far: 11 ticks (10/01 T1) and 1 tick (10/02 T2). See also Defect B.
- **Account protection attestation** (Position Brackets disabled) is operator-supplied,
  never measured. It is recorded fresh each session date (§9a). **[doc/ops]**
- **NEWS-2** is a foundation only: observe-only, nothing consumes it yet, and it is not
  in the production build. **[doc/code]**
- Older notes that may be stale (from 2026-07-23): 5m zone-width anomaly, the 25 pt cap
  trimming 51% of 15m stops, ATR-relative survivability bands. Re-check before acting.

## 13. Provenance and what was NOT verified

- First built **from the repository only** (code, docs, `git log`) on 2026-10-02 by Claude.
  Later the same day it was updated from the production branch's code and diffs plus the
  operator's 10/01–10/02 session reports to Maurice (marked **[ops]**).
  The long-running Claude Code session that produced most commits was
  **not** read; its reasoning is only as visible as the commit bodies make it.
- **Constants mismatch: settled in practice.** An older chat's handoff described a
  "frozen doctrine" of 40 threshold, 45 pt stop allowance, $250, 15 contracts,
  2 trades, 09:30–16:07 ET. Maurice's PROD-20261001 authorization and the 24/24
  preflight used the **code** values: $350 max all-in risk, 15 contracts, 35 pt
  preferred / 50 pt absolute stop, R:R ≥ 1.0, 2 trades, 1 attempt, 09:00–14:00 ET.
  The old handoff numbers are superseded. **[ops]**
- Account IDs, credentials, and personal emails are intentionally absent.
- Test status: full suite green on 3.13 (see §14); not run on the certified 3.14.5.
- `docs/map0_system_wiring.md`, `docs/ai_brain_*`, and the `ab*` docs were not
  re-read; consult them for module-level wiring detail.

## 14. Verified test baseline

- Environment: CPython 3.13 in a fresh virtualenv built from the pinned
  `requirements.txt` (converted from UTF-16LE for the venv) plus `pytest==9.1.1`.
  Python 3.11 cannot import the code (see `CLAUDE.md`).
- Focused run: `test_production_brain_model`, `test_model_identity_consistency`,
  `test_provider_model_identity_20260927`, `test_news2_factual_foundation` →
  **136 passed, 1 skipped**.
- **Full suite** on `a389193` (source identical to `95170d8`; docs-only difference),
  2026-10-02, CPython 3.13, `python -m pytest -q -p no:cacheprovider`:
  **7,649 passed, 585 skipped, 0 failed, 0 errors, 34 subtests passed** in 6 min 35 s
  (9 warnings: class-scoped fixture deprecations, `websockets.legacy`, `datetime.utcnow()`).
  The skips need operator evidence or credentials, as in earlier certifications.
- For comparison: last certified run (`docs/REPOSITORY_CERTIFICATION_20260910.md`,
  commit `ce95a26`+) was 7,838 collected / 7,255 passed / 0 failed / 583 skipped on
  CPython 3.14.5; `713f1cc` reported 7,537 passed / 584 skipped / 0 failed.
  Re-run before relying on any number here.

## 15. Glossary

- **ICT** — Inner Circle Trader methodology (liquidity, PO3, order blocks…).
- **PO3** — Power of 3 (accumulation → manipulation → distribution) session phases.
- **OB / OTE** — order block / optimal trade entry.
- **MNQ** — Micro E-mini Nasdaq-100 future ($2.00 per index point).
- **MLL** — Topstep Maximum Loss Limit (trailing drawdown) that bounds sizing.
- **PRAC / Combine** — Topstep practice account vs. the evaluation account.
- **PROD-YYYYMMDD** — a production session id.
- **Luna / Terra / Sol** — model tiers (cheapest → flagship); Luna is production now.
- **Brain** — the external LLM that owns directional thesis in the production lane.
- **ECU** — Brain mode that produces the thesis inside snapshot building (default off).
- **VAP** — volume at price evidence. **BE** — break-even. **OCO** — one-cancels-other.
- **Mission** — one trade's lifecycle under a session authorization (1 attempt).
- **Organism** — the repo's name for the whole mechanical system.
- **LATENCY-1** — pre-authorized conditional plans: the Brain authorizes one exact zone
  in advance, and the trigger is executed mechanically with no Brain call.
- **Conditional plan / "watching"** — the Brain action that publishes such a plan;
  requires `plan_expires_at` and an exact execution-object zone.
- **Final-quote economics** — size and risk recomputed from the last executable quote
  just before submit; can only resize down or refuse.
- **CONTAMINATED** — daily-loss governor state when an in-session trade cannot be
  attributed; blocks new entries (`GOVERNOR_UNPROVEN`).
- **2.5R stair** — current profit-protection management (no trailing until 2.5R,
  then stepwise stop amendments).

## 16. Doc index (by purpose)

- *Start here*: `CLAUDE.md`, this file. Session handoffs: `docs/handoffs/`.
- *Doctrine/governance*: `model_selection_doctrine.md`, `REPOSITORY_CERTIFICATION_20260910.md`,
  `production/GPT_5_6_TERRA_MIGRATION.md`, `fc3_fable5_authority_path.md`.
- *Brain/cognition*: `EVENT_DRIVEN_BRAIN_WAKE_20260911.md`, `PRE_BRAIN_WAKE_SHADOW_AUDIT_20260910.md`,
  `ai_brain_*`, `ab*` series, `na1_narrative_authority.md`.
- *Venue*: `topstepx_integration.md`, `topstep_combine_reset_runbook.md`.
- *State/history*: `BOT_STATE_2026-07-23.md`, `evolution/TIMELINE.md`,
  `production/AUGUST_5_2026_PRODUCTION_COMPLETION_LEDGER.md`, `production/sessions/`.
- *Wiring/audits*: `map0…map4`, `architecture/FORENSIC_DISCOVERY_LEDGER.md`,
  `audits/`, `structure_footprint_audit.md`.
- *Intelligence layers*: `news1_market_intelligence.md`, `EXPANSION_EVOLUTION_ROADMAP.md`.
