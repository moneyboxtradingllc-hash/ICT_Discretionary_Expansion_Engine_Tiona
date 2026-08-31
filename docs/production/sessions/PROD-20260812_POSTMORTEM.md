# 2026-08-12 Production Session Postmortem — Startup Historical Backfill Wiring Failure and Market-Reality Closure

**Session `PROD-20260812` · TopstepX · MNQ `CON.F.US.MNQ.U26` · COMBINE_SIMULATED.**

Launched armed. Placed nothing. Nineteen scans, every one `NO_CANDLES`. Stopped
by operator decision nineteen minutes in, forty-one minutes before the failure
mode would have become invisible.

The runtime HEAD is recorded separately from every repair below. A fix is never
allowed to be recorded as the thing that ran.

| | |
|---|---|
| **Runtime HEAD** | **`911bcfa`** (v33) — the commit that actually ran |
| Runtime fingerprint | `brain:ad80a36160dfda67` |
| Post-session repair HEADs | `6271f1f` (v34), `790b652` (v35), `c0f4693` (v36) |
| **Final baseline** | **`c0f4693`** · tag `next-session-ready-v36-2026-08-12` |
| **Final fingerprint** | **`brain:4d41201cca49e6dd`** |
| Model | `gpt-5.6-terra` |
| Window | 09:30 – 14:00 America/New_York |
| Account | fingerprint only — no raw account id appears in this archive |

---

## 1. Executive summary

`PROD-20260812` was launched armed at approximately **11:29:01 ET**. Every
pre-launch gate was green: authorization verified and unspent, model resolved,
fingerprint matched, account flat with zero positions and zero working orders,
no production process running.

Production immediately returned `NO_CANDLES` and returned it nineteen times in a
row, once per sixty-second scan, until the session was stopped at approximately
**11:48:57 ET**. Terra never received sufficient authoritative market history to
reason. No candidate was produced, no mission or token was created, no order was
submitted, no fill occurred. The account remained flat and the authorization
remained UNSPENT.

**Root cause.** `TopstepXDataProvider._fetch_bars` resolves its history source
with `getattr(self._session, "bars_1m", None)`. The production launcher injects
`TopstepXLiveSession`, which did not implement `bars_1m`. The provider therefore
raised `DataFeedError: session exposes no historical bars endpoint` **before any
HTTP historical-bars request was made**. `_backfill_history` catches every
exception by design — warm-up may never kill startup — recorded the error in
`self._last_backfill`, and no caller ever read that field. Startup history was
silently zero. The process then accumulated live bars one minute at a time from
its own uptime.

**Risk.** Had the session remained running, approximately sixty post-launch bars
would have satisfied the existing coherence minimum at roughly **12:29 ET**,
permitting production reasoning on a chart created from process uptime rather
than from reconstructed market history. The first post-launch bar landed on
`15:30:00Z`, which is already a 15-minute boundary, so alignment would have
trimmed nothing and the full run would have counted.

---

## 2. Impact

**Actual impact.**

- Zero trades.
- Zero orders submitted.
- Zero financial or simulated P&L impact.
- Zero authorization spend — no `session_20260812.json` ledger, no
  `trade_mission_PROD-20260812_*.json`, no `submissions_PROD-20260812.jsonl`.
- Zero mission creation. Zero token creation.
- Terra never exercised discretionary authority.
- Account remained flat; zero working orders remained after shutdown.

**Potential impact had the session continued.**

- Terra could have reasoned from post-launch-only market history.
- Derived MTF structure built on that window would have been epistemically
  invalid while appearing well-formed.
- Runtime reconnect gaps were also unrepairable: `repair_gaps()` routes through
  the same `_backfill_history`, so the CANDLE-CONTINUITY 2a mid-session hole
  repair in `topstepx_production_loop.py` was inert on the production path.
- An authorization could remain valid while market-data acquisition semantics
  changed, because the market-reality path sat outside the production
  fingerprint closure.

**On the coherence guard — stated precisely.**

The coherence guard **delayed** exposure to bad history. It did not identify the
root cause, and it would eventually have permitted a newborn chart once enough
post-launch observations accumulated. It refuses on bar *count*, and sixty bars
observed since launch count identically to sixty bars of reconstructed history.
The guard is not the reason this session is safe; the operator's decision to
stop is.

---

## 3. Pre-incident state

Verified read-only before launch:

| | |
|---|---|
| Release | v33 · `911bcfa` · tag `next-session-ready-v33-2026-08-12` |
| Fingerprint | `brain:ad80a36160dfda67` |
| Tests | 4938 passed (as recorded in the v32/v33 release note; not re-measured pre-launch) |
| Model | `gpt-5.6-terra` |
| Authorization | `PROD-20260812` — VERIFY PASS, UNSPENT |
| Account | COMBINE_SIMULATED, `CON.F.US.MNQ.U26`, FLAT, 0 positions, 0 working orders |
| Risk envelope | $250 all-in · max 2 trades · 1 attempt per trade · max 15 MNQ |
| Stops | 35 preferred / 40 absolute |
| Compounding | OFF |
| Window | 09:30 – 14:00 ET |

**An unexpected Windows reboot occurred earlier the same morning** (last boot
`2026-08-12 05:32:20`). A full read-only recovery verification was performed
before any work resumed: HEAD, tag, working tree, recomputed fingerprint,
authorization verification, account state and process inventory all matched the
pre-reboot record. The authorization had been minted at `08:49:41Z` — before the
reboot — and survived it intact.

> **The Windows reboot did not cause the backfill defect.** The recovery check
> proved the release, fingerprint, authorization and broker state were
> unchanged. The defect was structural and pre-existing: it would have occurred
> on any armed launch of v33 or any earlier release carrying the same wiring.

---

## 4. Incident timeline

Times are America/New_York. Timestamps are taken from log file modification
times, the recovery-check `date` output, and git commit times; where evidence
does not fix a time precisely it is marked approximate.

| Time | Event |
|---|---|
| 05:32:20 | Machine boot after unexpected Windows update restart. |
| ~05:43 | Read-only reboot recovery verification. HEAD `911bcfa`, tag v33, fingerprint `brain:ad80a36160dfda67`, authorization PROD-20260812 VERIFY PASS / UNSPENT, account FLAT 0/0, no stale processes. **RECOVERY VERIFIED.** |
| 11:29:01 | Final read-only gate re-run inside the window: authorization PASS, fingerprint match, account FLAT 0/0, no stale mission for `PROD-20260812`, no live process. |
| ~11:29 | **Production launched ARMED** — `--arm --mission-id PROD-20260812 --until-close`. Banner healthy: `ARM STATE: ARMED`, window enforced, `gpt-5.6-terra`, fingerprint `...dfda67`, 1 hub / 1 pump / 1 reconnect authority, quote age 0.04s, trade age 0.03s. |
| ~11:30 | **scan 1: `NO_CANDLES`** — *"the contiguous tail is only 5 bar(s) and none survive alignment to a 15-minute boundary"*. **Initially and incorrectly explained as ordinary mid-session warm-up.** See §7. |
| ~11:31 onward | scan 2 reports *"only 1 contiguous bars inside a 300-minute horizon; 60 required"*, then 2, 3, 4 … The count rises **exactly +1 per 60-second scan**. |
| ~11:40 | The +1/minute progression contradicts the warm-up explanation. Source-level trace of the startup path begins while the session is still armed. |
| ~11:44 | Trace establishes: `provider.start()` **does** call `_backfill_history(minutes_back=240)`; `TopstepXLiveSession` has no `bars_1m` (`hasattr` False, MRO `[TopstepXLiveSession, object]`); `_fetch_bars` raises before any request; the exception is swallowed into `_last_backfill`; no caller reads it. |
| ~11:47 | Operator orders **STOP / PRESERVE** rather than waiting for the forensic to complete while armed. |
| **11:48:57** | Production process (PID 10536) terminated. **19 scans, all `NO_CANDLES`, zero exceptions.** Post-shutdown verification: authorization VERIFY PASS and UNSPENT, record byte-identical (mtime 04:49, md5 `933e2477a15c2050c6abb3d7c1121a7d`), no ledger, no mission, no token, no submissions, account FLAT 0 positions / 0 working orders. |
| 12:13:53 | **v34 `6271f1f`** committed — historical capability restored, warm-up telemetry surfaced, armed startup fitness gate and newborn-chart veto added. |
| 12:21:51 | v34 read-only real-venue preflight: 240 bars returned, oldest `12:21:00Z` (08:21 ET), warm-up error `None`. Armed authority verdict FIT on 216 continuous bars predating process start. |
| ~12:22 | `PROD-20260812` **retired unspent**; retirement note written. |
| 12:44:16 | **v35 `790b652`** committed — authorization market-reality closure, 11 → 16 bound sources, fingerprint moves to `brain:14b7263ca6e5807d`. |
| 12:51:10 | v35 read-only preflight: 240 bars, error `None`, fingerprint `...e5807d`, `ARM STATE: DISARMED`. |
| 12:58:33 | **v36 `c0f4693`** committed — `timeframe_builder.py` bound, 17 sources, fingerprint moves to `brain:4d41201cca49e6dd`. Branch and tags v34/v35/v36 pushed. |
| 13:03:08 | v36 read-only preflight: 240 bars, oldest `13:03:00Z` (09:03 ET), newest `17:02:00Z` (13:02 ET), error `None`, armed authority FIT on 258 continuous bars, account FLAT 0/0, DISARMED. |

### Release progression

**v34 — `6271f1f`** · `next-session-ready-v34-2026-08-12`
Historical capability restored to the real `TopstepXLiveSession`; startup history
telemetry surfaced; armed startup history-fitness authority added; newborn-chart
provenance veto added; runtime gap repair restored; production-faithful
object-graph regression added. **4975 tests passed. 12/12 startup-history
mutations caught. `PROD-20260812` retired unspent.** Real-venue preflight
returned 240 bars with no warm-up error.

**v35 — `790b652`** · `next-session-ready-v35-2026-08-12`
Market-data acquisition and fitness code found to be outside the authorization
fingerprint. Bound `topstepx_live_session.py`, `topstepx_provider.py`,
`startup_history_authority.py`, `candle_continuity.py`, and the production
entrypoint via a new repo-root-anchored tuple. Fingerprint moved
`brain:ad80a36160dfda67` → `brain:14b7263ca6e5807d`. **4998 tests passed.
Closure mutations 8/8 after closing one survivor; startup-history 12/12.**

**v36 — `c0f4693`** · `next-session-ready-v36-2026-08-12`
Transitive audit found `timeframe_builder.py` still outside closure. Bound as
`timeframe_construction`. Fingerprint moved `brain:14b7263ca6e5807d` →
`brain:4d41201cca49e6dd`. **5002 tests passed. Closure mutations 9/9;
startup-history 12/12. Branch and tags pushed.** Read-only venue preflight
healthy, account flat, trading DISARMED.

---

## 5. Root cause

### The call chain

```
tools/topstepx_production_session.py          (production entrypoint)
  └─ TopstepXLiveSession                      (write-capable session, injected)
      └─ TopstepXDataProvider(session=session)
          └─ provider.start("MNQ", runtime=runtime)
              └─ _backfill_history(minutes_back=240)
                  └─ _fetch_bars(240)
                      └─ getattr(session, "bars_1m", None)   →  None
                      └─ raise DataFeedError(
                             "session exposes no historical bars endpoint")
                  └─ except Exception  →  report["error"] = ...   (swallowed)
              └─ startup continues
                  └─ canonical history = whatever was already on disk
                  └─ live bars accumulate at one per minute from process start
```

`bars_1m` existed on `TopstepXReadOnlySession` and on `topstepx_adapter`. It did
not exist on `TopstepXLiveSession`, which is the only session class the
production launcher constructs. The underlying capability was never missing:
`TopstepXLiveSession` already holds a `TopstepXClient`, and
`TopstepXClient.bars()` is the identical method
`TopstepXReadOnlySession.bars_1m` delegates to. Only the write-capable session
never declared that it could read history.

### Why the existing tests missed it

`tests/test_topstepx_data_provider.py::TestStartupBackfillClosesTheRestartHole`
proved warm-up works — against `BackfillSession`, a test double defined in that
file as *"a venue that CAN answer for history, unlike the plain fake"*, which
implements `bars_1m`.

The double had **more capability than the real production object**. The suite
therefore proved one half of a contract whose other half nothing checked. The
same file even contains a test whose comment reads `# FakeSession has no
bars_1m`, asserting that a session without the endpoint *degrades gracefully* —
encoding the defect's symptom as acceptable behaviour while no test asserted
that the production session was not such an object.

> **General testing failure: a production interface-parity defect was hidden by a
> richer test double.**

### Why the tape looked the way it did

The pre-launch canonical store's last contiguous run was Aug-11 `15:01–15:05Z` —
exactly five bars, after a gap at `14:41 → 15:01` — which is scan 1's *"only 5
bar(s)"*. Those five do not survive alignment up to a 15-minute boundary, so the
aligned window was empty. The first live-built bar arrived at `15:30:00Z`, and
`contiguous_tail()` returns **only the last contiguous run**, so the Aug-11
remnant was discarded and the count restarted at 1 and climbed one per minute.

---

## 6. Contributing factors

Separate from the root cause.

**A. Interface asymmetry.** `TopstepXReadOnlySession` exposed `bars_1m`;
`TopstepXLiveSession` did not. Two session implementations, one provider
expectation, no test binding them to a single interface.

**B. Warm-up failure invisibility.** `_last_backfill` recorded the exception
faithfully. The production launcher never printed or inspected it. The
`CANDLE CONSUMER: attached (N -> M candles)` line that might have hinted at it
prints only under `--proof`, which an armed launch does not pass.

**C. Fail-open startup semantics.** `_backfill_history` deliberately never
raises — correct for a tolerant, general-purpose provider, and unsafe for an
ARMED production context that had no separate authority gate to compensate.

**D. Observation-count limitation.** The coherence law could establish that a
recent window was long enough, continuous and aligned. It could not distinguish
historical reconstruction from process-born data.

**E. Missing provenance authority.** No startup law required authoritative
history to predate process start.

**F. Authorization closure incompleteness.** Market-data acquisition — and,
until the v36 transitive audit, timeframe construction — could change without
invalidating the production authorization.

**G. Production-parity test gap.** The test object graph was not the production
object graph.

---

## 7. Detection

The first `NO_CANDLES` was **not** sufficient to identify the defect. A single
insufficient-history refusal is indistinguishable from a legitimately thin tape.

The decisive observation was that the **candle count increased exactly +1 per
60-second production scan**:

```
scan  2: only  1 contiguous bars inside a 300-minute horizon; 60 required
scan  3: only  2 contiguous bars ...
scan  4: only  3 contiguous bars ...
...
scan 19: only 18 contiguous bars ...
```

A record being reconstructed from venue history does not arrive one bar per
minute. That progression demonstrated the active contiguous record was being
grown from live process uptime, and it triggered the source-level trace of the
startup path.

### Recorded operator correction

The first explanation offered for scan 1 was that the process had attached
mid-session at 11:29 and the buffer was still warming, and that it would clear on
its own. **That was an unverified inference stated with more confidence than the
evidence supported, and it was explicitly withdrawn.** It was challenged on the
grounds that startup canonical backfill exists precisely so that a mid-session
launch does not begin market history at process boot — and the challenge was
correct.

This is retained in the postmortem deliberately. Observed behaviour must be
traced to its source before it is labelled expected; an explanation that sounds
architecturally plausible is not evidence, and a plausible wrong explanation is
more dangerous than an open question because it stops the investigation.

---

## 8. Why no trade occurred

The actual chain:

1. Candidate production requires a coherent market-history window.
2. The window remained insufficient through all nineteen scans.
3. Terra was therefore never given an authoritative opportunity to reason.
4. No candidate existed.
5. With no candidate, no mission, token, bracket or order path was ever entered.

Stated precisely: **the existing guard prevented immediate exposure but did not
permanently prevent newborn-chart authority.** It would have released at sixty
post-launch bars. The v34 provenance lock is what closes that gap; on the day,
the operator's STOP/PRESERVE decision is what closed it.

Terra did not decline these setups. Terra was never asked.

---

## 9. Corrective actions

### v34 — `6271f1f`

1. `TopstepXLiveSession.bars_1m` — explicit delegated capability to
   `self._client.bars()`. Contract-scoped, not account-scoped: the provider
   resolves a contract during `start()` but never pins an account, and requiring
   one would have reintroduced the same silent failure through another door.
2. Provider warm-up telemetry surfaced in the startup banner: attempted,
   requested horizon, bars returned, bars added, oldest/newest returned,
   canonical bar count, canonical first/last, continuity, gaps, error.
   `returned` is recorded separately from `added` so "the venue gave nothing"
   can never again be confused with "the store already had it".
3. Armed startup history-fitness gate (`src/data_feed/startup_history_authority.py`),
   running inside `check_startup` — before Terra, candidate production,
   mission/token creation, or order authority.
4. Canonical freshness requirement (newest bar age ceiling).
5. Coherent and aligned recent-window requirement, delegating to the same
   `coherent_window` call the scan loop uses so startup and scanning cannot
   disagree about what coherent means.
6. History provenance requirement — the coherent window must contain bars
   predating process start.
7. Newborn-chart veto, refusing on provenance rather than on count.
8. Production-faithful object-graph regression
   (`tests/test_startup_history_authority.py`), instantiating a real
   `TopstepXLiveSession` with an injected transport.
9. Runtime gap-repair regression proving repair reaches the venue through the
   production session type, and fails closed without stitching when the venue
   cannot heal the hole.

The authority condition is deliberately **history fitness, never `added > 0`**: a
warm-up may legitimately add nothing because the canonical store already holds
every minute the venue offered, and may add hundreds of stale bars while leaving
the session with no coherent recent history at all.

### v35 — `790b652`

10. Authorization market-reality closure expansion, 11 → 16 sources.
11. Bound: `broker/topstepx_live_session.py`, `data_feed/topstepx_provider.py`,
    `data_feed/startup_history_authority.py`, `data_feed/candle_continuity.py`,
    and `tools/topstepx_production_session.py` via a new repo-root-anchored
    `_CONTRACT_SOURCES_REPO`.
    `candle_continuity.py` was bound deliberately, not as a courtesy: it holds
    the fitness algorithm itself, and binding the four obvious files while
    leaving it out would have reproduced the defect one layer down.
    The entrypoint was bound rather than relocated because moving the gate into
    an already-bound module would not close the hole — whatever module owns the
    gate is still *called* from the entrypoint, and the entrypoint can decline to
    call it.
12. End-to-end proof through the real verifier: mutate any bound market-reality
    source and a signed authorization raises
    `AUTHORIZATION_BRAIN_CONTRACT_CHANGED`; restore and it verifies again.
13. Missing-vs-empty source hashing distinction. This closed a **surviving
    mutant** from the first closure campaign: without the `<missing>` marker, an
    absent bound source hashed identically to an empty one.
14. No-overbinding regression: editing `topstepx_mission_reconciler.py` must not
    invalidate a live authorization.

### v36 — `c0f4693`

15. Bound `data_feed/timeframe_builder.py` as `timeframe_construction`
    (17 sources). Audited first: 93 lines, stdlib `datetime` only, no transitive
    dependencies left behind it.
16. End-to-end chart-pipeline closure test —
    `test_the_whole_chart_pipeline_is_bound_end_to_end` — pinning every hop:

```
venue acquisition        broker/topstepx_live_session.py
  → canonical 1m         data_feed/topstepx_provider.py
  → continuity law       data_feed/candle_continuity.py
  → startup fitness      data_feed/startup_history_authority.py
  → timeframe construction  data_feed/timeframe_builder.py
  → MTF synthesis        market_state/mtf_market_state.py
  → Terra
```

---

## 10. Verification evidence

| | |
|---|---|
| Release | v36 |
| Commit | `c0f4693` |
| Tag | `next-session-ready-v36-2026-08-12` |
| Fingerprint | `brain:4d41201cca49e6dd` |
| Bound sources | 17 (16 `src`-anchored + 1 repo-anchored) |
| Tests | **5002 passed, 0 failed**, 34 subtests |
| Mutations | closure **9/9** caught · startup-history **12/12** caught · **0 survivors** |

Real-venue read-only preflight at 13:03:08 ET:

```
bars returned by venue      : 240
oldest returned             : 2026-08-12T13:03:00Z   (09:03 ET)
newest returned             : 2026-08-12T17:02:00Z   (13:02 ET)
warm-up error               : None
BRAIN CONTRACT FINGERPRINT  : ...49e6dd
ARM STATE                   : DISARMED

armed authority verdict     : FIT — no refusals
coherent window             : 258 bars, continuous
window oldest               : 2026-08-12T12:45:00Z
window predates process     : True
```

Broker: COMBINE_SIMULATED · `CON.F.US.MNQ.U26` · FLAT · 0 open positions ·
0 working orders.
Authorization: **no active 2026-08-12 authorization.**
Trading: **DISARMED.**

> The `canonical continuous: False` line in every preflight is expected and is
> not a defect: the persisted store spans Aug 4 – Aug 12 and contains overnight
> and weekend seams. That is precisely why fitness is judged on a bounded
> coherent window rather than on the whole tape.

---

## 11. What went well

- STOP/PRESERVE was chosen before the history window could bootstrap itself into
  apparent sufficiency, with forty-one minutes of margin.
- No trade lifecycle was entered at any point.
- Authorization durability made it possible to *prove* no spend occurred rather
  than assume it: absence of ledger, mission, token and submission artifacts,
  plus a byte-identical authorization record.
- Broker reconciliation independently proved flat / 0 / 0 after shutdown.
- Evidence logs survived and were sufficient to reconstruct the failure exactly,
  including the pre-launch tape shape that explains scan 1.
- The armed production launch exposed an object-graph parity defect that the
  unit and integration suites did not represent.
- The corrective work produced permanent regressions and mutation locks rather
  than a one-line repair; one closure mutant survived the first campaign and was
  closed rather than accepted.
- v36 binds the complete chart pipeline, from venue acquisition through
  timeframe construction and MTF synthesis, into the authorization contract.

---

## 12. What did not go well

- Production historical capability was absent from `TopstepXLiveSession`.
- The warm-up failure was silent in normal production telemetry.
- An armed startup could proceed after a failed backfill.
- Process-born candles could eventually satisfy observation-count coherence.
- Runtime gap repair was unknowingly inert for the same reason.
- Tests did not exercise the actual production object graph.
- Market-data authority was outside authorization closure.
- Timeframe construction remained outside closure until the v36 transitive audit.
- The initial explanation of scan 1 was stated more confidently than the evidence
  supported, and would have delayed detection had it not been challenged.

---

## 13. Permanent engineering laws added / reaffirmed

> **Truth before tuning.**
>
> **Fix reality before tuning intelligence.**
>
> **Absence may never masquerade as continuity.**
>
> **Observation count may never masquerade as elapsed market time.**
>
> **Process uptime may never masquerade as market history.**
>
> **A warm-up failure that cannot be seen is a warm-up failure that gets
> launched on.**
>
> **Determinism must not manufacture evidence.**
>
> **The authorization must die when the definition of production market reality
> changes.**
>
> **A test double with more capability than the real production object is not a
> production-parity test.**
>
> **Authority determines source closure, not directory membership.**
>
> **The AI is the last thing consulted, not the first thing trusted.**

---

## 14. Next-session entry criteria

On the next trading date:

1. Start from **v36 / `c0f4693`**.
2. Confirm a clean working tree and tag `next-session-ready-v36-2026-08-12`.
3. Recompute and confirm the fingerprint: **`brain:4d41201cca49e6dd`**.
4. Perform a read-only real-venue history preflight
   (`python tools/topstepx_production_session.py`, no `--arm`, `--scans 0`).
5. Require: warm-up error `None`; current historical coverage; a sufficient
   coherent and aligned window; history predating process start.
6. Verify COMBINE_SIMULATED · `CON.F.US.MNQ.U26` · flat · 0 working orders.
7. Resolve `gpt-5.6-terra`.
8. **Mint a NEW date-bound authorization for that session date.** An
   authorization carries `session_date` and `verify()` refuses on rollover with
   `AUTHORIZATION_EXPIRED`; it cannot be minted in advance.
9. Verify the authorization read-only.
10. Remain **DISARMED** until an explicit `GO LIVE`.
11. Launch only inside the 09:30 – 14:00 ET production window.
12. Observe the first *healthy* production scan before treating startup as
    complete — a green banner is not a healthy session.

> **Do not reuse `PROD-20260812`. It was intentionally retired unspent.**

---

## 15. Final incident classification

| | |
|---|---|
| **Severity** | Production safety / epistemic integrity defect |
| **Outcome** | NO TRADE / NO LOSS / NO ORDER |
| **Root cause** | Production historical-bars interface parity failure |
| **Secondary defects** | Invisible warm-up failure · newborn-chart bootstrap possibility · inert runtime gap repair · incomplete authorization market-reality closure |
| **Resolution** | CLOSED in v34 – v36 |
| **Final production baseline** | v36 · `c0f4693` · `brain:4d41201cca49e6dd` |
| **Status** | **DISARMED — READY FOR NEXT-SESSION DATE-BOUND AUTHORIZATION** |

---

## 16. Evidence references

Preserved artifacts, resolved against the repository:

| Artifact | Path |
|---|---|
| Runtime stdout, all 19 scans | `data/integration/topstepx/prod20260812_stdout.log` |
| v34 post-patch venue preflight | `data/integration/topstepx/prod20260812_postpatch_preflight.log` |
| v35 venue preflight | `data/integration/topstepx/prod20260812_v35_preflight.log` |
| v36 venue preflight | `data/integration/topstepx/prod20260812_v36_preflight.log` |
| Authorization retirement note | `data/integration/topstepx/retired_authorizations/RETIREMENT_NOTE_PROD-20260812.json` |
| Retired authorization record † | `data/integration/topstepx/retired_authorizations/session_auth_PROD-20260812.RETIRED_superseded_by_V34.json` |
| Canonical 1m store † | `data/market_data/topstepx/CON_F_US_MNQ_U26.jsonl` |
| Startup-history / parity regressions | `tests/test_startup_history_authority.py` |
| Closure governance regressions | `tests/test_authorization_source_closure.py` |
| Startup fitness authority | `src/data_feed/startup_history_authority.py` |
| Historical delegation | `src/broker/topstepx_live_session.py` |

Release commits and tags:

| Release | Commit | Tag |
|---|---|---|
| v33 (runtime) | `911bcfa` | `next-session-ready-v33-2026-08-12` |
| v34 | `6271f1f` | `next-session-ready-v34-2026-08-12` |
| v35 | `790b652` | `next-session-ready-v35-2026-08-12` |
| v36 | `c0f4693` | `next-session-ready-v36-2026-08-12` |

**† Preserved on disk, deliberately NOT committed.** An authorization record is
never committed, retired or not (`.gitignore`, *durable production session
state*), and `data/market_data/` is likewise excluded. The retirement note that
summarises the record IS committed, as are the postmortems that cite the
canonical store. These two rows document where the artifacts live on the
production machine, not paths recoverable from a clone.

**Mutation campaign scripts are not preserved in the repository.** Both were run
from the session scratchpad
(`…/scratchpad/mutate.py`, `…/scratchpad/mutate_closure.py`), which is
session-scoped and not durable. Their *results* are recorded in §10 and their
targets are enumerated in §9; the campaigns are reproducible from those lists.
Preserving the scripts under `data/integration/topstepx/` is an open option.

---

*Recorded 2026-08-12. Documentation only — no production code, configuration,
authorization or broker state was modified in the writing of this postmortem.*
