# August 5, 2026 -- Expansion Bot Production-Completion Ledger

Canonical, evidence-backed record of the work that turned this repository from a
set of individually-proven components into a complete TopstepX/MNQ production
organism.

- **Branch:** `ob-block-finder-and-evidence-diagnostics`
- **Commit range:** `de64dfa` (09:32) through `2178f09` (17:30), 32 commits
- **Full suite at time of writing:** 3317 passed
- **Orders placed while producing this document:** none

Every claim below is grounded in git history, committed source, committed tests,
committed evidence artifacts, or a live read-only query run against the account.
Claims that cannot be proven from the repository are marked
**UNVERIFIED FROM REPOSITORY**.

---

## 1. Executive summary

**What it was at 09:32.** A large, well-tested ICT analysis engine with a
TopstepX venue adapter attached. Nearly every individual component existed and
passed tests. What did not exist was a path connecting them. The Brain analysed
markets; the risk engine could size a trade; the execution runner could submit
one. Nothing called them in sequence.

**What prevented it operating as a production organism.** Four structural gaps,
each independently sufficient to prevent a real trade:

1. **No production caller.** `build_production_bracket()` had *zero* callers
   anywhere in the repository. `gated_submit` was reached only from smoke
   tooling running smoke caps. The production risk path was unreachable code.
2. **`--arm` did nothing.** The flag controlled a printed line and a startup
   check. No code path in the launcher produced a candidate or submitted an
   order.
3. **Smoke constants leaking into production.** The first-day smoke law ($20,
   10 points, 1 contract) was wired into default arguments that the production
   path silently inherited -- including at the final pre-submit recheck.
4. **Cross-instrument contamination.** The engine was built on an Alpaca/QQQ
   equities path. Several defaults still resolved to `QQQ`, and the capital
   engine read the **Alpaca** account balance during TopstepX scans.

**What it became by 17:30.** One authenticated pinned Topstep account feeding
one shared market runtime (one socket, one pump, one reconnect authority, many
subscribers), driving the authoritative scan pipeline into GPT-5.6 Luna, through
candidate production, adaptive all-in sizing, a gated single-attempt submit, a
bot-authored attached bracket, and full entry/exit reconciliation with
quote-to-fill slippage measurement -- governed by a durable, fingerprinted,
dated session authorization.

**Current readiness.** Production-ready, disarmed, authorized for `PROD-20260806`
(unspent). Account flat, zero working orders.

**Intentionally provisional.** The slippage reserve (2 ticks entry + 2 ticks
exit = $2.00/contract) is a conservative estimate, not a measurement. It is
explicitly *not* auto-calibrated, and its sample is **0/20 reliable observations,
0/10 complete round trips**. That is the correct starting state of a measurement
programme, not an outstanding defect.

---

## 2. Final production doctrine

```text
DATA SOURCE                        : TopstepX only
EXECUTION VENUE                    : TopstepX only
INSTRUMENT                         : MNQ only
ACTIVE CONTRACT                    : CON.F.US.MNQ.U26
PRODUCTION WINDOW                  : 09:30-14:00 America/New_York
MAXIMUM BOT TRADES PER SESSION     : 2
MAXIMUM ENTRY ATTEMPTS PER MISSION : 1
MAXIMUM ALL-IN RISK PER TRADE      : $250
MAXIMUM CONTRACTS                  : 15 MNQ
COMPOUNDING                        : OFF
PREFERRED STRUCTURAL-STOP RANGE    : 0-35 points
ABSOLUTE STRUCTURAL-STOP CEILING   : 40 points
EXTENDED VOLATILITY RANGE          : >35 through 40 points
STOP AUTHORITY                     : exact structural invalidation
TARGET AUTHORITY                   : current Luna-selected liquidity objective
BRACKET AUTHORITY                  : bot-authored BracketGeometry
TOPSTEP POSITION BRACKETS          : not authoritative
SLIPPAGE RESERVE                   : 2 ticks entry + 2 ticks exit
                                     $2.00 per contract, provisional,
                                     automatic recalibration disabled
```

**35 and 40 are eligibility boundaries, not stop distances.** The stop is always
the exact structural invalidation the thesis names. 35 is the boundary above
which a setup additionally requires supporting volatility evidence; 40 is the
boundary above which the setup is **rejected outright**. Neither number is ever
used as a stop distance, and a stop is never moved to land on one.

Source: `src/broker/topstepx_combine_risk.py`,
`src/broker/topstepx_session_authorization.py`,
`src/broker/topstepx_production_doctrine.py`.

---

## 3. Beginning-of-day defects

28 material defects. Proof levels: **LIVE** (observed against the venue),
**UNIT** (locked by committed test), **ARTIFACT** (committed evidence file).

### D-01 -- Production ceiling used the 10-point smoke value
- **Previous behavior:** `build_bracket(max_stop_points=...)` defaulted to the smoke ceiling; production callers inheriting the default got 10 points.
- **Production consequence:** every structural stop wider than 10 points rejected -- i.e. nearly every real setup.
- **Evidence:** `dc91fa9` diff of `src/broker/topstepx_combine_risk.py`.
- **Repair:** separate `build_production_bracket()` entry point where production doctrine is the only reachable path.
- **Commit:** `dc91fa9`  -  **Proof:** UNIT (`tests/test_production_stop_ceiling.py`)

### D-02 -- Production quantity silently capped at one contract
- **Previous behavior:** `size=1` default; no caller overrode it.
- **Production consequence:** a $250 risk budget executed as a ~$23 trade.
- **Repair:** `size_for_risk()` computes quantity from the stop; `build_production_bracket` rebuilds at the sized quantity.
- **Commit:** `dc91fa9`  -  **Proof:** UNIT

### D-03 -- No adaptive all-in sizing
- **Previous behavior:** no function related quantity to stop distance, fixed costs and slippage reserve.
- **Production consequence:** risk per trade varied uncontrolled with stop width.
- **Repair:** `size_for_risk()` -- see Section 8.
- **Commit:** `dc91fa9`  -  **Proof:** UNIT

### D-04 -- Final submit recheck reintroduced smoke defaults
- **Previous behavior:** `recheck_risk_at_submit` rebuilt the bracket via `build_bracket()` **without** passing caps, re-imposing size 1 / $20 / 10 points at the last gate.
- **Production consequence:** an approved 3-contract production bracket would shrink to 1 contract, or be rejected, microseconds before submission.
- **Repair:** the runner carries its own caps (defaulting to production doctrine) and passes the approved size through.
- **Commit:** `7008644`  -  **Proof:** UNIT (`tests/test_runner_gate_wiring.py`)
- **Note:** this was the **third** distinct instance of a smoke value leaking through a default argument.

### D-05 -- No production caller existed
- **Previous behavior:** `tools/` contained only smoke tooling.
- **Production consequence:** the production path could not be executed at all.
- **Evidence:** AST audit -- `gated_submit` reachable only from `tools/topstepx_smoke_wait.py`.
- **Repair:** `src/broker/topstepx_production_session.py` + `tools/topstepx_production_session.py`.
- **Commit:** `6024419`  -  **Proof:** UNIT + LIVE (read-only lane open)

### D-06 -- `build_production_bracket()` had zero callers
- **Previous behavior:** the entire production sizing/ceiling path from `dc91fa9` was unreachable code.
- **Production consequence:** doctrine existed on paper only.
- **Repair:** called from `ProductionSession.build_runner`.
- **Commit:** `6024419`  -  **Proof:** UNIT (AST test asserts the call site)

### D-07 -- `--arm` reached no order-capable path
- **Previous behavior:** the flag affected a startup check, a printed line and a suppressed message. AST audit showed `submit`, `gated_submit`, `place_order`, `CandidateProducer`, `produce`, `issue`, `consume_attempt` all **ABSENT** from the launcher.
- **Production consequence:** arming was cosmetic.
- **Repair:** `ProductionLoop._scan_once` branches on `armed`; only that branch reaches `_execute` -> `gated_submit`.
- **Commit:** `bd68d9b`  -  **Proof:** UNIT (`tests/test_production_scan_loop.py`)

### D-08 -- No quote-to-fill measurement
- **Previous behavior:** the runner recorded fill-vs-candidate-reference drift and called it slippage.
- **Production consequence:** conflated market movement since thesis creation with execution quality; the cost model could never be calibrated.
- **Repair:** `src/broker/topstepx_slippage.py` -- capture an executable quote at submit, compare fill against it.
- **Commit:** `ca3831c`  -  **Proof:** UNIT

### D-09 -- Slippage components built but never called
- **Previous behavior:** `ca3831c` shipped measurement functions with no caller.
- **Repair:** capture at gate step 9b (after all gates, before attempt persistence); measurement at fill.
- **Commit:** `7008644`  -  **Proof:** UNIT (ordering test asserts capture precedes persistence)

### D-10 -- Candidate identity did not survive the lifecycle
- **Previous behavior:** nothing carried candidate identity from entry to exit; an exit would have to be matched by price or time proximity.
- **Production consequence:** exits paired to the wrong entry; round trips uncountable.
- **Repair:** `ExecutionContext` persisted atomically at entry, carrying candidate id, fingerprint, snapshot id, stop/target order ids.
- **Commit:** `7008644`  -  **Proof:** UNIT

### D-11 -- Session ledger did not persist known token IDs
- **Previous behavior:** `SessionLedger.save()` omitted `known_token_ids`; `load_or_new` restored only entries.
- **Production consequence:** after a restart the bot's own orders classified as `UNKNOWN_EXTERNAL` -- reading as an intruder on the account and tripping the pause law during recovery.
- **Repair:** persist and reload the token set.
- **Commit:** `6024419`  -  **Proof:** UNIT

### D-12 -- Venue `-SL` / `-TP` tags classified as unknown
- **Previous behavior:** `classify()` did not strip the venue's protective-leg suffixes, though `candidate_from_order_tag()` did.
- **Production consequence:** every stop/target exit marked unreliable, so **no round trip could ever accumulate** -- the slippage reserve could never become measured -- and the bot's own stop firing would trip the pause law.
- **Repair:** `PROTECTIVE_TAG_SUFFIXES` stripped in `classify()`, with the parent token still required to be known.
- **Commit:** `6024419`  -  **Proof:** UNIT

### D-13 -- Competing SignalR pump ownership
- **Previous behavior:** `TopstepXDataProvider` built its own session and connection; `ProductionSession` started its own pump thread. A process running both opened **two** sockets.
- **Production consequence:** two readers, each seeing part of the stream.
- **Repair:** `TopstepXMarketRuntime` -- one owner of connect/pump/reconnect/close.
- **Commit:** `0348a23`  -  **Proof:** UNIT + LIVE (1 connection, 1 pump owner observed)

### D-14 -- Event handlers silently replaced one another
- **Previous behavior:** `SignalRHub.on()` stored a **single** handler per event (`self._handlers[event] = handler`).
- **Production consequence:** attaching the quote provider to a hub the candle provider was already using would have **unsubscribed the candle provider** -- no error, no log, candles simply stop. Sharing one hub was unsafe in the opposite direction from the duplicate-pump hazard.
- **Repair:** handlers append; identical handler re-registration is a no-op; one event still counts once.
- **Commit:** `0348a23`  -  **Proof:** UNIT

### D-15 -- No pump drained the live hub
- **Previous behavior:** `SignalRHub` has no background reader; messages dispatch only when `pump()` is called. The first live proof returned `QUOTE RECEIVED: False` in an open market.
- **Production consequence:** every submit-time capture classified STALE; every measurement discarded.
- **Repair:** runtime-owned pump thread with an idle wait so a non-blocking `recv` cannot hot-spin.
- **Commit:** `6024419` (initial), `0348a23` (moved to the runtime)  -  **Proof:** LIVE

### D-16 -- Duplicate reconnect authority
- **Previous behavior:** both the data provider and the production session had their own reconnect-on-exception path.
- **Production consequence:** competing reconnects on one socket.
- **Repair:** `_reconnect()` on the runtime only; connection generation increments once; staleness persists until fresh post-reconnect data.
- **Commit:** `0348a23`  -  **Proof:** UNIT

### D-17 -- Account fingerprint not enforced at the pin
- **Previous behavior:** the launcher called `session.pin(account_id=...)` with no `expected_fingerprint`, then passed the env fingerprint downstream as if verified.
- **Production consequence:** pinning by id alone resolves whichever account now holds that id; the check that catches a changed configured account was skipped.
- **Repair:** `expected_fingerprint` passed at the pin.
- **Commit:** `3ca745b`  -  **Proof:** UNIT + LIVE

### D-18 -- Conflicting scan windows
- **Previous behavior:** `SCAN_START_TIME`/`SCAN_END_TIME` resolved to `08:30-15:00` (legacy equities), while production intent was `09:30-14:00`.
- **Production consequence:** a legacy env var could widen the live futures trading window by two hours.
- **Repair:** production window is a constant in `topstepx_session_authorization.py`; both values printed; enforced constant wins. `.env` subsequently aligned by operator instruction.
- **Commit:** `bd68d9b`  -  **Proof:** UNIT + LIVE (both windows printed)

### D-19 -- `SCAN_SYMBOL=QQQ`
- **Previous behavior:** the configured scan symbol was the retired equity instrument.
- **Production consequence:** the legacy scan loop would analyse equities.
- **Repair:** `.env` set to `MNQ` (config change; `.env` is not committed).
- **Commit:** n/a -- configuration  -  **Proof:** LIVE (line-diff verified, all other lines hash-identical)

### D-20 -- Provider defaulted silently to Alpaca
- **Previous behavior:** `get_provider()` resolved `os.getenv("DATA_PROVIDER", "alpaca")`.
- **Production consequence:** an unset or blank variable meant the bot analysed equities while Topstep executed MNQ futures -- the exact outcome the module's own comment called "worth crashing to avoid".
- **Repair:** no default; unset/blank refuses; `alpaca` refuses as RETIRED; the error no longer offers it.
- **Commit:** `1e472d9`  -  **Proof:** UNIT (4 tests)

### D-21 -- Brain/ECU defaulted symbol identity to QQQ
- **Previous behavior:** `ecu.py` called `run_narrative_brain(snapshot, snapshot.get("symbol", "QQQ"), ...)`, and `build_snapshot` does **not** stamp `snapshot["symbol"]`.
- **Production consequence:** under `BRAIN_ECU_MODE=true` the canonical Brain call -- the thesis production consumes -- would tell Luna it was reading QQQ during an MNQ session, and key symbol-partitioned stance/persistence there.
- **Repair:** resolves `snapshot["symbol"] -> SCAN_SYMBOL -> PRODUCTION_INSTRUMENT`.
- **Commit:** `b44cd07`  -  **Proof:** UNIT
- **Status at discovery:** latent -- `ecu_enabled()` was `False`.

### D-22 -- Thesis persistence defaulted to QQQ
- **Previous behavior:** `ThesisLifecycleEngine` used `os.getenv("SCAN_SYMBOL", "QQQ")`.
- **Production consequence:** an unnamed MNQ engine could match and resurrect a stored QQQ thesis.
- **Repair:** falls through to `PRODUCTION_INSTRUMENT`.
- **Commit:** `b44cd07`  -  **Proof:** UNIT

### D-23 -- Volume witness loaded QQQ assumptions
- **Previous behavior:** `symbol or "QQQ"` in `baseline_table_path()` and `load_minute_baseline()`; `feed_source` hardcoded `"alpaca"`; `venue_scope` `"venue_limited_iex"`.
- **Production consequence:** MNQ volume compared against **equity percentiles**.
- **Repair:** absent identity yields *no* baseline (reported unavailable); retired/foreign identity refuses; feed source and venue scope now describe the TopstepX MNQ stream.
- **Commit:** `b44cd07`  -  **Proof:** UNIT

### D-24 -- Capital intelligence read Alpaca account equity during Topstep scans
- **Previous behavior:** `track_capital()` fell back to `paper_broker.get_account()` -- the **Alpaca** paper account -- and the result flowed into `capital_report` -> `build_snapshot()` -> the snapshot the Brain reads.
- **Production consequence:** drawdown pressure and aggression tier computed from an unrelated equities balance on every production scan. **This was live, not latent** -- the only reachable-and-firing contamination found.
- **Repair:** fallback removed; the caller supplies the pinned Topstep account, or capital contributes nothing.
- **Commit:** `9af35f1`  -  **Proof:** UNIT

### D-25 -- Retrieval lacked instrument-identity exclusion
- **Previous behavior:** `retrieve_analogs()` filtered on provenance and similarity only.
- **Production consequence:** QQQ-era analogs could be returned for an MNQ decision; a QQQ session can look *very* similar to an MNQ one, and similarity is exactly what would let equity evidence pass as a good analog.
- **Repair:** `doctrine/instrument_identity.py`; identity checked **before** similarity; missing identity is exclusion, not compatibility.
- **Commit:** `b44cd07`  -  **Proof:** UNIT
- **Status at discovery:** not firing -- `AI_RETRIEVAL_ENABLED` unset **and** `memory_store.jsonl` was 0 bytes.

### D-26 -- Unknown broker defaulted to the Alpaca paper adapter
- **Previous behavior:** `get_adapter()` -- "Unknown -> paper"; `paper` is a 454-line Alpaca `TradingClient` wrapper.
- **Production consequence:** silently routing an unrecognised venue to a retired one.
- **Repair:** `BrokerSelectionError` on missing or unknown broker.
- **Commit:** `9af35f1`  -  **Proof:** UNIT

### D-27 -- Overstated Alpaca-removal telemetry
- **Previous behavior:** startup printed `ALPACA RUNTIME: REMOVED` while `src/paper_execution/` remained on disk.
- **Production consequence:** a live-capable subsystem could be assumed dead. Telemetry that overstates a retirement is how that happens.
- **Repair:** `ALPACA PRODUCTION PATH: BLOCKED` / `ALPACA DATA PROVIDER: ARCHIVED` / `LEGACY ALPACA PAPER SUBSYSTEM: PRESENT - NOT PRODUCTION-REACHABLE`, computed from the filesystem, plus a `sys.modules` reachability refusal.
- **Commit:** `2ca29b8`  -  **Proof:** UNIT + LIVE

### D-28 -- No safe operator authorization issuer
- **Previous behavior:** arming required a durable record with no supported way to create one.
- **Production consequence:** either no arming, or hand-written JSON -- which the fingerprint law would reject anyway.
- **Repair:** `tools/topstepx_issue_session_authorization.py`, delegating to the authoritative module.
- **Commit:** `2ca29b8`, `2178f09`  -  **Proof:** UNIT + LIVE

---

## 4. Commit ledger

All 32 commits dated 2026-08-05 on this branch, chronological. Every hash in the
requested list was verified present and on-branch; **13 additional commits** from
the same day were absent from that list and are included here.

Full-suite results are recorded where measured at the time; entries marked `-`
were not separately recorded and are **UNVERIFIED FROM REPOSITORY**.

| # | Commit | Time | Files | Mission / behavior introduced | Suite |
|---|---|---|---|---|---|
| 1 | `de64dfa` | 09:32 | 6 | SMOKE-RISK-20 -- first-day smoke law ($20, 10pt) | - |
| 2 | `ec01bac` | 09:38 | 2 | READINESS-DUAL-CAP -- report the cap actually in force | - |
| 3 | `d23838a` | 09:56 | 1 | MNQ-DATA-BLOCKER -- retrieveBars unusable; provider not built | - |
| 4 | `fa35b48` | 10:22 | 2 | MNQ-BARS-WINDOW -- round the bars window to a completed minute | - |
| 5 | `ee122b5` | 10:22 | 1 | MNQ-BARS-UPSTREAM -- support evidence | - |
| 6 | `5088f73` | 10:37 | 1 | MNQ-BARS-FORENSIC -- reference provider was mock-only | - |
| 7 | `a81c617` | 11:01 | 4 | TOPSTEPX-DATA-PROVIDER -- native MNQ 1m candles from the hub | - |
| 8 | `d4a37c0` | 11:12 | 1 | TOPSTEPX-COLLECTOR -- candle accumulation toward warm-up | - |
| 9 | `b2914f7` | 11:38 | 5 | MANUAL-RECONCILE -- origin attribution, liquidity objectives, no stale brackets | - |
| 10 | `89f20c9` | 11:48 | 2 | RUNNER-LEDGER-FRESHNESS-WIRING -- gates guard the submit path (D-05 precursor) | - |
| 11 | `09167a6` | 11:57 | 2 | LUNA-CANDIDATE-PRODUCER -- validated thesis to immutable candidate | - |
| 12 | `3d27107` | 12:07 | 2 | TOPSTEPX-COLDSTART -- "no event yet" is warming up, not stale | - |
| 13 | `8b1a312` | 12:17 | 4 | TOPSTEPX-SMOKE-WAIT -- write-capable session, one-trade wait | - |
| 14 | `20e41b4` | 12:57 | 5 | SMOKE-DURABLE-ATTEMPT -- one attempt survives a crash | - |
| 15 | `9651859` | 13:02 | 3 | TOPSTEPX-EXEC-SMOKE -- venue refused attached brackets; attempt spent | ARTIFACT |
| 16 | `c244098` | 13:07 | 4 | TOPSTEPX-EXEC-SMOKE-B -- second attempt rejected identically | ARTIFACT |
| 17 | `7c59d1a` | 13:12 | 5 | TOPSTEPX-EXEC-SMOKE-C -- bracketless entry filled and flattened clean | ARTIFACT / LIVE |
| 18 | `8213920` | 13:27 | 6 | LEDGER-ORDER-JOIN -- Trade.orderId join; commissions close the P&L gap (D-12 area) | - |
| 19 | `53f72aa` | 13:37 | 7 | TOPSTEPX-SIGNED-TICKS -- signed bracket ticks; venue corrected the docs | - |
| 20 | `43caeed` | 13:52 | 4 | TOPSTEPX-EXEC-SMOKE-F -- bot-authored attached protection verified | ARTIFACT / LIVE |
| 21 | `dc91fa9` | 14:16 | 4 | PRODUCTION-STOP-CEILING-40 -- D-01, D-02, D-03 | - |
| 22 | `ca3831c` | 14:25 | 5 | LIVE-SLIPPAGE-EVIDENCE-CAPTURE -- D-08 | - |
| 23 | `7008644` | 14:37 | 5 | WIRE-LIVE-SLIPPAGE-CAPTURE -- D-04, D-09, D-10 | 3120 |
| 24 | `6024419` | 14:51 | 5 | WIRE-PRODUCTION-SLIPPAGE-CALLER -- D-05, D-06, D-11, D-12, D-15 | 3159 |
| 25 | `0348a23` | 15:07 | 7 | SINGLE-TOPSTEP-MARKET-PUMP -- D-13, D-14, D-16 | 3200 |
| 26 | `3ca745b` | 15:16 | 2 | PIN-LAW-ENFORCED -- D-17 | 3201 |
| 27 | `bd68d9b` | 16:00 | 5 | WIRE-PRODUCTION-SCAN-LOOP -- D-07, D-18 | 3245 |
| 28 | `1e472d9` | 16:25 | 2 | TOPSTEPX-ONLY -- D-20 | 3248 |
| 29 | `b44cd07` | 16:40 | 11 | DECON-3A-BLOCK-QQQ-RETRIEVAL -- D-21, D-22, D-23, D-25 | 3276 |
| 30 | `9af35f1` | 17:08 | 12 | DECON-3B-REMOVE-ALPACA-RUNTIME -- D-24, D-26 | 3276 |
| 31 | `2ca29b8` | 17:24 | 7 | PRODUCTION-AUTHORIZATION-CLI -- D-27, D-28 | 3314 |
| 32 | `2178f09` | 17:30 | 2 | PRODUCTION-AUTHORIZATION-ROLE-CHECK -- Combine role + simulated venue | 3317 |

---

## 5. Production architecture

```text
TopstepXLiveSession.authenticate()  +  .pin(expected_fingerprint=...)
  src/broker/topstepx_live_session.py, src/broker/topstepx_client.py:pin_account
        |
TopstepXMarketRuntime  (one hub / one pump thread / one reconnect authority)
  src/broker/topstepx_market_runtime.py
    .connect() .start(owner_id) ._pump_forever() ._reconnect() .stop()
        |
        |-- candle consumer   TopstepXDataProvider   src/data_feed/topstepx_provider.py
        |                       MinuteCandleAggregator, _on_trade, fetch_1m_candles
        |
        \-- quote consumer    LiveQuoteProvider      src/broker/topstepx_quote_provider.py
                                .capture() -> QuoteCapture
        |
ProductionScanCycle.scan()         src/live_scan/production_scan_cycle.py
    build_timeframes -> htf_engine.update -> track_capital -> build_snapshot
    -> analyze_transition -> setup_tracker -> shared context + council
    -> retrieve_for_snapshot -> canonical Brain thesis
        |
GPT-5.6 Luna                       src/ai_brain/narrative_brain.py:run_narrative_brain
    (or the ECU canonical block, src/ai_brain/ecu.py)
        |
CandidateProducer.produce()        src/broker/luna_candidate_producer.py
        |
CandidateSnapshot                  src/broker/topstepx_candidate_freshness.py
    .fingerprint(), LiquidityObjective, assess()
        |
build_production_bracket()         src/broker/topstepx_combine_risk.py
    classify_stop_distance, size_for_risk, BracketGeometry.signed_stop_ticks
        |
ExecutionRunner.gated_submit()     src/broker/topstepx_execution_runner.py
    20-step gate sequence; quote captured at 9b; attempt persisted; token burned
        |
attached bot-authored protection   BracketGeometry.as_order_payload
        |
entry reconciliation               ProductionSession.reconcile_entry
  src/broker/topstepx_production_session.py  -> measure_entry_slippage
        |
ExecutionContext (atomic)          src/broker/topstepx_slippage.py
        |
exit reconciliation                ProductionSession.reconcile_exit
                                     -> measure_exit_slippage
        |
SlippageLedger                     src/broker/topstepx_slippage.py:SlippageLedger
    .record(), .round_trips(), .sample_status()
        |
final flat-state reconciliation    ProductionLoop.final_flat_state
  src/broker/topstepx_production_loop.py
```

Orchestration: `ProductionLoop.scan_once()` / `_execute()`
(`src/broker/topstepx_production_loop.py`); launcher
`tools/topstepx_production_session.py`; authorization
`src/broker/topstepx_session_authorization.py`.

---

## 6. Intelligence-input inventory

Produced by `build_snapshot()` and carried into the Brain payload by
`ai_brain/brain_input.py:build_brain_input()`.

| Engine | Present |
|---|---|
| Market structure | yes |
| Liquidity | yes |
| PO3 | yes (with `Po3StabilityManager` hysteresis) |
| Volatility | yes (with `ExpansionStabilityManager` hysteresis) |
| Session state | yes |
| Delivery state | yes |
| Protected levels | yes (`ProtectedSwingTracker`) |
| Playbook families | yes |
| Tool families | yes |
| Thesis lifecycle | yes (`ThesisLifecycleEngine`) |
| Adaptive context | yes (ADAPTIVE-1C, observe-only) |
| Adaptive friction | yes |
| Vector-retrieval analogs | yes (gated `AI_RETRIEVAL_ENABLED`) |
| HTF memory | yes (`HtfMemoryEngine`) |
| Volume witness | yes (gated `VOLUME_WITNESS`) |

```text
news_context: intentionally disabled
```

**Instrument-identity enforcement.** `src/doctrine/instrument_identity.py`
defines `PRODUCTION_INSTRUMENT = MNQ`, `PRODUCTION_CONTRACT =
CON.F.US.MNQ.U26`, and `RETIRED_INSTRUMENTS` / `RETIRED_VENUES`.
`retrieval_eligible(record)` is called inside `retrieve_analogs()` **before**
similarity scoring, and rejects: retired instrument, foreign instrument, retired
venue, records flagged `RETIRED_HISTORICAL` or `production_eligible: false`, and
**records with no instrument identity at all**. `record_instrument()` looks in
top-level fields and in `market_context` / `metadata` / `provenance` -- the
vector-memory schema nests the symbol under `market_context`, and a guard that
missed that nest would have excluded every legitimate MNQ record too.

---

## 7. Candidate and freshness lifecycle

**Luna sovereignty.** Only `source == "llm"` with no `fallback_reason` and a
non-empty parsed output may author a candidate
(`ProductionScanCycle.is_sovereign`).

- **Neutral / conflicted** -> `NO_CANDIDATE`, no token, no order, keep scanning.
- **Degraded / fallback** -> `BRAIN_DEGRADED` with the exact warning or exception
  captured. Reported as a **Brain failure**, never as a market stand-down -- a
  `fallback_reason` counts as degradation even when `source` still reads `llm`.
- **Directional but incomplete** (missing invalidation, objective, playbook or
  tool family) -> `NO_CANDIDATE`. Missing fields are never fabricated.

**CandidateProducer** resolves the thesis against mechanical evidence only:
objectives are enumerated from the snapshot (`enumerate_objectives`), so a
candidate can never target a level that exists solely in prose. Ambiguity is a
refusal (`NoCandidate`).

**Identity carried:** candidate id, candidate fingerprint (a hash of the
*thesis* -- direction, entry, invalidation, objective identity and price,
contract, account, narrative), snapshot id, structural invalidation identity,
liquidity-objective identity and price, volatility context, creation time,
Brain-response digest, mechanical-evidence digest, engine-inventory digest.

**Supersession.** A newer candidate replaces the prior one
(`ProductionLoop.active_candidate`, `CandidateProducer._supersede`). Stale
candidates are never carried between scans.

**Pre-submit revalidation.** `assess()` re-checks 18 drift conditions
immediately before submission. The module deliberately exposes **no** repair,
adjust, widen or move function -- a stale candidate is destroyed, not fixed.

**Token and attempt.** The token is minted *after* every gate passes (not at
thesis time), bound to the whole thesis, and **burned before the request
leaves**. The attempt is persisted durably (write + fsync + re-read verify)
before submission, via `on_attempt_consumed`. A rejected or unknown-outcome
submission **spends** the attempt; there is no retry within a trade mission.

---

## 8. Risk and adaptive sizing

```text
quantity x ( structural_stop_points x $2.00
             + $1.22 measured fixed round-trip cost
             + $2.00 provisional slippage reserve )  <=  $250
```

MNQ = $2.00 per point per contract; tick 0.25 = $0.50.
Fixed cost is **measured**: fees $0.72 + commissions $0.50 round trip
(`friction_per_contract()` reports
`fixed_source: "measured: live Mission C/F Trade.fees + Trade.commissions,
2026-08-05"`). Slippage is **provisional** and reports
`slippage_is_measured: false`.

Verified by executing `size_for_risk()` at current HEAD:

| Stop | Qty | All-in per contract | All-in total | Lane |
|---|---|---|---|---|
| 10 pts | 10 | $23.22 | $232.20 | `NORMAL_STOP_RANGE` |
| 20 pts | 5 | $43.22 | $216.10 | `NORMAL_STOP_RANGE` |
| 35 pts | 3 | $73.22 | $219.66 | `NORMAL_STOP_RANGE` |
| 40 pts | 3 | $83.22 | $249.66 | `EXTENDED_VOLATILITY_STOP_RANGE` |
| 41 pts | -- | -- | -- | `STOP_DISTANCE_REJECTED` |

Rules:
- **Whole contracts only** -- the quantity floor is integral.
- **15-contract cap** independent of the risk budget.
- **No compounding** -- the budget does not grow with the balance.
- **Friction is never removed to make a trade fit.** If one contract cannot fit
  under $250 all-in, the setup is **rejected**.
- **Wide structural stops are rejected, not squeezed.** Above 40 points the
  setup is refused; the invalidation is the thesis and is not adjustable.
- **Targets are never moved farther** to manufacture reward-to-risk; the R:R
  floor (1.5) is applied to the authentic geometry.
- Stops in the extended lane (>35 through 40) additionally require supporting
  volatility evidence (`extended_volatility_supported()`), otherwise rejected.

---

## 9. Signed-bracket doctrine

The venue corrected the documentation: *"Ticks should be less than zero when
longing."* Commit `53f72aa`.

```text
LONG  : stop ticks negative,  target ticks positive
SHORT : stop ticks positive,  target ticks negative
```

### Mission F -- LIVE proof

Source: `data/integration/topstepx/execution_smoke_20260805T174823Z.json`
(committed in `43caeed`), mission `exec-smoke-20260805-F`.

| Item | Value |
|---|---|
| Direction / size | long, 1 MNQ |
| Entry order | `3368041519`, ack 181 ms |
| Entry fill | **29760.5**, position `811804558` |
| Stop order | `3368041520` -- type 4, side 1, size 1, stop **29750.5**, parent `3368041519` |
| Target order | `3368041521` -- type 1, side 1, size 1, limit **29780.5**, parent `3368041519` |
| Observed ticks | stop 40, target 80 |
| Protection checks | **10 of 10 PASS** (position qty, stop/target exist, both qty 1, both correct side, both distances, no duplicate protection) |
| Flatten | accepted; `/api/Position/closeContract` |
| Cleanup | both protective legs cancelled (`3368041520`, `3368041521`) |
| Final state | 0 positions, 0 working orders, `durable_state: COMPLETE`, `clean: true` |
| Write calls | 4 (place, closeContract, cancel, cancel) |
| Balance before | $50,043.68 |
| Balance now | $50,042.96 |
| Net movement | **-$0.72** |

Fee/commission evidence from the committed session ledger
(`data/integration/topstepx/session_20260805.json`): per contract per side
fees $0.36 + commissions $0.25; entry order `3368041519` at 29760.5, exit order
`3368041611` at 29760.75 with gross P&L $0.50. Gross +$0.50 - fees $0.72 -
commissions $0.50 = **-$0.72**, reconciling exactly to the observed balance
movement.

**Attribution -- honest status.** The committed ledger records both Mission F
orders as `MANUAL_OPERATOR` with `bot_filled_trade_count: 0`. That artifact was
written **before** D-11 (token persistence) and D-12 (`-SL`/`-TP` suffixes) were
repaired: the ledger reconciled with an empty `known_token_ids` set, so the
bot's own tag matched no known token. The artifact is therefore *evidence of the
defect*. The repaired attribution is **UNIT-proven only**; it has **not** been
re-proven live against that data, and the historical artifact was deliberately
not rewritten.

Missions A, B (`9651859`, `c244098`) were venue rejections of attached brackets;
Mission C (`7c59d1a`) was a bracketless entry filled and flattened clean. All are
live artifacts, distinct from the mocked integration proofs in Section 10.

---

## 10. Live proofs versus simulated proofs

| Capability | Unit-tested | Mocked E2E | Live read-only | Live order-tested | Evidence |
|---|---|---|---|---|---|
| Historical bars | yes | yes | **yes** | n/a | `fa35b48`; 300 bars / 0.211 s |
| Live quote flow | yes | yes | **yes** | n/a | 29759.75 / 29760.25, age 0.00 s |
| Candle construction | yes | yes | **yes** | n/a | 542 -> 543 under one pump |
| Shared pump ownership | yes | yes | **yes** | n/a | 1 conn / 1 pump / 2 subscribers |
| Account pin | yes | yes | **yes** | n/a | fingerprint enforced, `3ca745b` |
| Luna reachability | yes | yes | **yes** | n/a | `luna_health` verdict PASS, 10/10 checks |
| Candidate production | yes | yes | **yes** (reached producer) | no | live scans hit `CandidateProducer`, refused on window |
| Adaptive sizing | yes | yes | no | **no** | Section 8 table computed at HEAD |
| Signed bracket | yes | yes | n/a | **yes** | Mission F |
| Attached protection | yes | yes | n/a | **yes** | Mission F, 10/10 checks |
| Entry fill | yes | yes | n/a | **yes** | Missions C and F |
| Flatten | yes | yes | n/a | **yes** | Missions C and F |
| Order cleanup | yes | yes | n/a | **yes** | Mission F, both legs cancelled |
| Production scan loop | yes | yes | **yes** (disarmed) | **no** | 3 live scans, all counters zero |
| Durable authorization | yes | yes | **yes** | n/a | `PROD-20260806` issued, 0 write calls |
| Slippage capture wiring | yes | yes | **yes** (quote captured) | **no** | no fill has been measured |
| Slippage statistical calibration | **no** | **no** | **no** | **no** | 0/20 observations, 0/10 round trips |

No mocked proof in this table is described as live. The production scan loop,
adaptive sizing and slippage measurement have **never executed against a real
fill** -- Missions C and F predate the production caller and used smoke
geometry (1 MNQ, 10-point protective distance).

---

## 11. Market-runtime ownership

```text
ONE HUB
ONE PUMP THREAD
ONE RECONNECT AUTHORITY
MANY SUBSCRIBERS
```

**Prior hazard.** `TopstepXDataProvider()` constructed its own read-only session
and called its own `connect_market_hub()`; `ProductionSession` started its own
pump thread. A process running both would have opened **two SignalR
connections** -- not merely two readers on one socket (D-13).

**Handler-clobbering.** `SignalRHub.on()` kept one handler per event, so forcing
both consumers onto a single hub would have silently unsubscribed the first
(D-14). Sharing was unsafe in the opposite direction from duplication.

**Final component.** `src/broker/topstepx_market_runtime.py:TopstepXMarketRuntime`
owns `connect()`, `start(owner_id)`, `_pump_forever()`, `_reconnect()`,
`stop()`. `start()` from a different owner raises `MarketHubOwnershipError`
(`MARKET_HUB_ALREADY_OWNED`) and starts **no** thread; the same owner is
idempotent. Consumers attach via `attach()` / `note_subscriber()` and never
drain the socket.

**Reconnect generation.** `_reconnect()` replays the subscription plan in order
and increments `connection_generation` exactly once per failure.

**Stale-until-fresh law.** Freshness is **not** restored by reconnecting. A
reopened socket has delivered nothing, so `is_stale()` stays true until real
post-reconnect data arrives.

**Shutdown ordering.** detach consumers -> signal owner -> join pump thread ->
close hub **once**. A second `stop()` does not close again; a consumer never
closes a hub it does not own.

`ProductionSession` owns no transport: it has no `_pump_forever`, starts no
thread, and AST tests assert it never calls `pump`, `reconnect`, `close` or
`connect_market_hub`. Startup refuses on ambiguous ownership, a dead pump
thread, a contract mismatch, or a quote provider attached to a foreign hub.

---

## 12. Slippage measurement

**Executable reference.** `capture_quote()` snapshots the in-memory
`GatewayQuote` at the submit boundary -- synchronous allocation only, no HTTP,
no poll, no sleep, no second connection. A buy is referenced to the **ask**, a
sell to the **bid**.

**Entry formulas.** Long: `fill - ask`. Short: `bid - fill`.
**Exit formulas.** Measured against the reference appropriate to the exit type:
TARGET against the liquidity-objective price, STOP against the structural stop,
and a flatten against the **current executable price** -- never against a price
it was never aimed at.

**Sign convention.** Positive = adverse. Favorable slippage stays **negative**
rather than being clamped to zero; discarding favorable observations would bias
the eventual reserve upward.

**Reliability exclusions.** Eight classes mark an observation unreliable --
including missing quote, crossed or inverted book, stale market data, unknown
attribution, contract mismatch and quantity mismatch. Unreliable observations
are still **persisted** (they are evidence) but excluded from statistics.

**Partial fills** collapse to a quantity-weighted average first
(`aggregate_fills`), so one order yields **one** observation. Counting each row
would inflate the sample and manufacture round trips that never happened.

**Pairing.** `SlippageLedger.round_trips()` pairs strictly by
`(candidate_id, contract, direction)` -- identity threaded through
`ExecutionContext`, never reconstructed from price or timestamp proximity.

**Reserve.** 2 ticks entry + 2 ticks exit = $2.00 per MNQ round trip,
`measured: false`, `AUTOMATIC RESERVE UPDATES: disabled`. Thresholds:
`MIN_RELIABLE_OBSERVATIONS = 20`, `MIN_ROUND_TRIPS = 10`.

```text
0/20 reliable observations
0/10 complete round trips
```

This is the **valid starting state** of the measurement programme, not a
production blocker. The observations can only be earned through genuine
qualified production trades; requiring them before production begins would make
them unreachable. Evidence is collected passively -- no trade is ever placed for
the purpose of measurement.

---

## 13. Session and trade authorization

**Durable session authorization** (`src/broker/topstepx_session_authorization.py`).
Two distinct controls: **2 bot trades per session**, **1 entry attempt per child
trade mission**. The attempt is consumed by the **attempt**, not by a fill -- a
venue rejection spends it exactly like an execution, because the alternative is
retrying into a venue whose state is unknown.

**Bound terms:** session id, session date, account fingerprint, contract id,
decision window, maximum trades, maximum attempts per trade, maximum all-in
risk, maximum contracts, preferred and absolute stop ceilings, compounding,
issued-at, authorization fingerprint. The fingerprint is a hash **of the terms
themselves**, so a limit hand-edited on disk fails verification instead of being
honoured.

**Refusals:** corrupt record, account mismatch, contract mismatch, expired date
(authorizations do not roll over), window mismatch, and any term above doctrine
(>2 trades, >1 attempt, >$250, >15 contracts, >35 preferred, >40 absolute,
compounding on).

**Child missions.** A second trade mission may open only when the first is
terminal and reconciled, positions are zero, working orders are zero, no
unresolved submit exists, no unknown external activity exists, the window is
open, and the session maximum is not reached. Never two active at once; a third
is refused.

**Restart persistence.** `load_existing()` reloads child missions so a restarted
process inherits the spent allowance; a reloaded mission with a consumed attempt
returns `may_attempt_entry() -> False`.

**Issuer CLI.** `tools/topstepx_issue_session_authorization.py` -- authenticates
read-only, pins with the expected fingerprint, verifies Combine role and
simulated venue, resolves the MNQ contract, then delegates to `SA.issue(...)`.
It contains no `hashlib`/`sha256` and cannot reach an order endpoint (both
locked by test). Reissuing an identical unspent authorization is idempotent and
**keeps the original record**, so `issued_at` -- and therefore the fingerprint --
does not drift.

**`--until-close`.** The window governs **entries**; exposure governs **exit**.
The loop scans while the window is open, and past 14:00 continues only while a
position or working order remains, then stops. Leaving at 14:00 with exposure
open would abandon it to its brackets with nobody reconciling.

**Issued authorization:**

```text
session : PROD-20260806
date    : 2026-08-06
state   : UNSPENT
```

Account fingerprint and full authorization fingerprint deliberately omitted.

---

## 14. Alpaca/QQQ decommission

Standing doctrine: TopstepX only, MNQ only, `CON.F.US.MNQ.U26`, window
09:30-14:00 ET; Alpaca and QQQ permanently retired.

- **Provider fallback removed** -- no default; unset, blank, `alpaca` and unknown
  all refuse (D-20).
- **QQQ symbol defaults removed** -- ECU, thesis lifecycle, volume witness
  (D-21, D-22, D-23); `.env` `SCAN_SYMBOL` set to `MNQ` (D-19).
- **Alpaca capital-equity contamination cut** -- `track_capital()` no longer
  reads the Alpaca paper account; the production loop supplies the pinned
  Topstep balance (D-24). This was the only *live, firing* contamination found.
- **Retrieval identity law** -- identity checked before similarity; unlabelled
  records excluded (D-25).
- **Archived QQQ evidence** -- `archive/legacy_alpaca_qqq/` holds
  `performance_QQQ/`, `htf_memory_QQQ.json` and `alpaca_provider.py.retired`
  with a `HISTORICAL -- NOT PRODUCTION INPUT` README and the metadata block
  `status = RETIRED_HISTORICAL`, `instrument = QQQ`, `venue = ALPACA`,
  `production_eligible = false`, `retrieval_eligible = false`.
  **Records were not relabelled as MNQ** -- equity history is not futures
  history, and renaming would have turned a clean empty MNQ table into a
  contaminated one that merely looked populated.
- **Local Alpaca credential keys removed** -- `ALPACA_API_KEY`,
  `ALPACA_SECRET_KEY`, `ALPACA_BASE_URL` deleted from `.env`
  (`ALPACA_DATA_URL` was not present). No value was read or printed.
  **Local deletion is not revocation** -- these must be revoked at Alpaca.
- **Alpaca data provider archived** -- `src/data_feed/alpaca_provider.py` no
  longer exists; `import data_feed.alpaca_provider` raises `ModuleNotFoundError`.
- **Legacy paper subsystem remains** -- `src/paper_execution/` (454-line Alpaca
  `TradingClient` wrapper plus ~11 modules, ~14 importers reaching
  `operational_readiness`, `paper_activation`, `capital_intelligence`). It is
  unreachable from the production launcher and fails closed now that
  `ALPACA_BASE_URL` is absent. Its removal is a separate scoped mission.

Startup telemetry, verified live:

```text
ALPACA PRODUCTION PATH:
BLOCKED

ALPACA DATA PROVIDER:
ARCHIVED

LEGACY ALPACA PAPER SUBSYSTEM:
PRESENT -- NOT PRODUCTION-REACHABLE

QQQ PRODUCTION PATH:
BLOCKED
```

`retired_paths_reachable()` inspects `sys.modules` at startup and refuses if the
launcher has actually loaded any Alpaca or `paper_execution` module -- the
question is not whether retired code exists on disk, but whether this process
pulled it in.

---

## 15. Final operator workflow

Authorization issuer -- **has been run**:

```powershell
python tools\topstepx_issue_session_authorization.py --session-id PROD-20260806 --date 2026-08-06
```

Reserved production launcher -- **has not been run**:

```powershell
python tools\topstepx_production_session.py --arm --mission-id PROD-20260806 --until-close
```

---

## 16. Current account reconciliation

```text
balance                              : $50,042.96
positions                            : 0
working orders                       : 0
authorization                        : issued and unspent (PROD-20260806)
launcher                             : not running
orders placed during final authorization : 0
```

Account role: Trading Combine, simulated venue environment, `canTrade=true`.
Read-only verification made 0 write calls.

---

## 17. Remaining limitations

1. **The slippage reserve has never been calibrated from production fills.**
   It remains the provisional $2.00/contract estimate at 0/20 observations and
   0/10 round trips.
2. **No real production round trip has occurred through the final launcher.**
   Missions C and F proved the venue path using smoke geometry, before the
   production caller existed. Adaptive sizing, the scan-to-execution loop and
   slippage measurement have never run against a real fill.
3. **The legacy Alpaca paper subsystem physically remains.** Blocked and
   unreachable from production, but present.
4. **The MNQ retrieval corpus is effectively empty.** `memory_store.jsonl` was
   0 bytes; MNQ must earn its own history. Retrieval is also gated off
   (`AI_RETRIEVAL_ENABLED` unset).
5. **Bot attribution is unit-proven, not re-proven live.** The committed
   Mission F ledger still shows `MANUAL_OPERATOR` / `bot_filled_trade_count: 0`
   from before D-11 and D-12 were repaired (see Section 9).
6. **The MNQ candle cache is shallow** -- ~567 persisted 1m candles at the time
   of writing; deeper engines benefit from more warm-up.
7. **`data/global_memory/global_lessons.jsonl` holds 240 records with no
   instrument identity.** Currently harmless: `deployment/global_memory.py` has
   zero importers. If ever wired in, those records would be excluded by the
   identity law.
8. **The extended-volatility lane (>35-40 points) has never been exercised
   live.**

---

## 18. Tiona alignment requirements

A neutral checklist for auditing any independent TopstepX/MNQ bot. It assumes
nothing about that repository's files or architecture; the Maurice column is a
**reference implementation**, not something to copy.

| # | Requirement | Why it exists | Maurice reference | Required proof | Common failure mode found here |
|---|---|---|---|---|---|
| 1 | The production risk path has a real caller | Doctrine that nothing calls is decoration | `topstepx_production_session.py` | Trace a call graph from the launcher to the sizing function | Sizing function had **zero** callers |
| 2 | Arming gates the only order-capable branch | A flag that changes a printed line is not a safety control | `topstepx_production_loop.py` | Disarmed run reaches the boundary and stops; armed run reaches submit | `--arm` reached no order path |
| 3 | Test/smoke constants cannot reach production | Default arguments silently inherit | `build_production_bracket` separate entry point | Assert production sizing differs from smoke at every gate incl. final recheck | Occurred **three** separate times |
| 4 | Final pre-submit recheck preserves approved size and caps | The last gate is the easiest to overlook | `recheck_risk_at_submit` | Approved quantity survives to the payload | Recheck re-imposed 1 contract / $20 / 10 pts |
| 5 | One market connection, one pump, one reconnect authority | Two readers each see part of the stream | `TopstepXMarketRuntime` | Count sockets, threads, owners at runtime | Two components each opened their own connection |
| 6 | Event dispatch supports many subscribers | Single-handler maps silently unsubscribe the first consumer | `SignalRHub.on` | Two consumers both receive the same event once | Second consumer silently replaced the first |
| 7 | Something actually drains the socket | Many SignalR clients require explicit pumping | runtime pump thread | Observe a quote arriving in an open market | Provider attached to a hub nobody read |
| 8 | Freshness is not restored by reconnecting | A reopened socket has delivered nothing | `is_stale()` | Stale stays true until post-reconnect data | -- |
| 9 | Account pin verifies an expected fingerprint | Pinning by id resolves whichever account holds that id | `pin_account(expected_fingerprint=...)` | Mismatch refuses | Launcher pinned without verifying |
| 10 | Instrument identity is explicit and required | Symbol-partitioned stores are defeated by one default | `doctrine/instrument_identity.py` | Unlabelled record excluded, not assumed compatible | Several defaults resolved to a retired symbol |
| 11 | Account equity comes from the trading venue | Cross-venue balances corrupt risk state | `ProductionLoop._topstep_account` | Trace the equity source on a live scan | Capital engine read a **different broker's** balance |
| 12 | Retired venues cannot be selected or defaulted to | Silent fallback is worse than a crash | `data_feed.get_provider` | Unset/blank/unknown all refuse | Provider defaulted to the retired venue |
| 13 | Bracket tick signs match venue convention | Docs may be wrong; the venue is authoritative | `signed_stop_ticks()` | A live accepted bracket with verified sides | Documentation contradicted the venue |
| 14 | Protection is proven, not assumed | An unprotected filled position is the worst state | `verify_protection` | Post-fill check of existence, side, qty, price, duplicates | -- |
| 15 | The bot owns stop/target economics; the venue only hosts them | Platform presets are not the thesis | `BracketGeometry` | Bot-authored prices survive serialization | -- |
| 16 | Attempt consumption is durable **before** the request leaves | A crash mid-submit must not permit a second entry | `MissionState.consume_attempt` | Kill the process after submit; restart does not re-enter | In-memory latch reset on restart |
| 17 | Rejected or unknown submissions consume the attempt | Retrying into unknown venue state is how doubles happen | `_reconcile_uncertain` | Venue rejection leaves the mission terminal | -- |
| 18 | Candidate identity survives entry to exit | Otherwise exits pair by price or time guessing | `ExecutionContext` | Round trip paired by candidate id | No identity was carried |
| 19 | Attribution joins trade to parent order | Venues may strip custom tags from trade records | `classify(row, tokens, order_index)` | Bot fill attributed to the bot | Trade records carried no tag |
| 20 | Venue-derived protective legs attribute to the bot | Suffixed tags read as unknown | `PROTECTIVE_TAG_SUFFIXES` | Stop/target fill classified as bot | Would have blocked all round trips |
| 21 | Attribution state survives restart | An empty token set makes your own orders look foreign | persisted `known_token_ids` | Restart still recognises own orders | Token set was not persisted |
| 22 | Slippage is quote-to-fill, never inferred from P&L | P&L conflates market movement with execution quality | `topstepx_slippage.py` | Show the captured quote beside the fill | Reference drift was labelled slippage |
| 23 | Unmeasured cost assumptions are labelled provisional | An estimate presented as a measurement is worse than no number | `slippage_is_measured: false` | Cost model states its source | -- |
| 24 | Partial fills collapse to one observation | Per-row counting manufactures round trips | `aggregate_fills` | One order yields one observation | -- |
| 25 | Trade count and attempt count are separate controls | "Two trades" and "one attempt" are different laws | `ProductionSessionMission` | Rejected attempt still spends the trade mission | -- |
| 26 | Authorization is durable, dated and fingerprinted | A process flag does not survive a restart | `SessionAuthorization` | Hand-edited term fails verification | -- |
| 27 | Authorizations do not roll over | Yesterday's permission is not today's | date binding | Expired record refuses | -- |
| 28 | The decision window gates entries, not position management | Abandoning an open position at the bell is worse | `--until-close` | Position still managed after the window | Fixed scan counts cannot express this |
| 29 | Telemetry claims match reality | Overstated retirement makes live paths look dead | `legacy_paper_subsystem_state()` | Status computed, not hardcoded | Printed `REMOVED` while code remained |
| 30 | Degraded AI is reported as AI failure, not market silence | Otherwise an outage becomes evidence about price | `BRAIN_DEGRADED` | Degraded scan distinguishable from no-setup | -- |
| 31 | Setups are rejected, not reshaped, when they exceed limits | Moving an invalidation changes the thesis | `RiskRejection` | Over-ceiling stop refused, not squeezed | -- |
| 32 | Historical evidence from a retired instrument is quarantined, not relabelled | Renaming makes an empty table look populated | `archive/legacy_alpaca_qqq/` | Retired records non-retrievable | -- |

---

## 19. Final readiness statement

```text
PRODUCTION-READY
DISARMED
AUTHORIZED FOR PROD-20260806
AUTHORIZATION UNSPENT
ACCOUNT FLAT
NO WORKING ORDERS
```

The first real production session must be explicitly launched during the valid
August 6 decision window.
