# EXPANSION BOT — CONTEXT-INTELLIGENCE ERA ROADMAP (v1.2)

*Drafted 2026-07-30; v1.1 same day after the HTF wiring audit; v1.2 same day
after the era's credit-free missions SHIPPED. Documentation only. Every claim is
repo-verified; corrections to earlier summaries are recorded in Part I so the
next era is built on the repo, not on a summary of the repo.*

---

# PART 0 — STATUS LEDGER (v1.2) AND THE FULL ARC

## Shipped 2026-07-30 (all pushed, all milestoned, suite 2530)

| Mission | Commit | Result |
|---|---|---|
| HTF-REPLAY | `78dc044` | Opt-in `htf` replay arm; 20 archived sessions seeded, memory_age 19 (live peaked at 5); recorded-mode parity 148/148 as invariants demand |
| HTF-FLAGS-AUDIT | `3b8c64a` | Split verdict: disagreement flag shows witness-grade separation (paired addendum: 13/20 sessions, magnitude concentrated in 2 days); gap flag rejected (latching, 84% of volume) |
| FLAG-SPLIT | `9c6569c` | Conflict flags = directional disagreement only; expected volume 57%→22% of scans; no-authority-reader source lock |
| HTF-MNQ-ACCUM | `e2e2f3c` | Money venue accumulates `MNQ.json` daily memory; write-only, author source-locked |
| MISSION-CONTROL | `2159e09` | The throne room: 7 guarded panels, self-contained, `data/ops/mission_control/MISSION_CONTROL.html` |

**The credit-free board is EMPTY.** Every remaining mission needs API credits
or a live venue session.

> **AMENDMENT 2026-08-04 — PHASE B2 CANCELLED.** Credits were funded
> 2026-08-04. The operator did **not** authorize the replay research program,
> nor any miniature replacement for it. Standing doctrine is live-market
> validation, not laboratory optimization: paid replay bake-offs are withdrawn
> at every scale. B2 is replaced by **MODEL-CONTRACT-SMOKE** — a five-case
> maximum, pass/fail contract probe against `gpt-5.6-sol` alone — and model
> selection is adjudicated solely by the frozen B1 live campaign. Replay proves
> compatibility; live proves value. See `docs/model_selection_doctrine.md` —
> that document governs where it and this roadmap disagree.

## The full arc (detail for A–D in Parts III–IV; standing law in Part II)

- **PHASE A — IGNITION** *(operator)*: A1 venue go (MNQ smoke order /
  TopstepX armed) → opens the campaign + starts MNQ memory. A2 API credits
  → funded 2026-08-04; unlocks the bounded compatibility probe (NOT the
  cancelled replay research program).
- **PHASE B — ONE CAMPAIGN, ONE GATE**: B1 live ADAPTIVE-8 (20–30 trades,
  10+ sessions, decision-authority frozen; Mission Control daily; EOD candle
  archive; friction ledger accumulates) — **the sole venue that may rank
  models**. B2 ~~replay research~~ → **MODEL-CONTRACT-SMOKE**: five cases max
  (bullish, bearish, conflicted, neutral, invalid), `gpt-5.6-sol` only,
  pass/fail — a gate and never a score. HTF-PROMPT A/B and RETRIEVAL-ABLATION
  are withdrawn in their replay-bake-off form.
- **PHASE C — ADJUDICATION**: ADAPTIVE-8 verdict; first real earn-back
  decision; TARGET-LOCK ships (first post-freeze behavior change);
  exit-policy trial (SimBroker counterfactuals on management_policies);
  friction verdict = the funded-eval arithmetic gate.
- **PHASE D — CONTEXT ORGANS** *(one at a time, witness-first, earn-back
  always)*: DAILY-THESIS → CONFLICT-1 → SMT-WITNESS → MACRO-TIME-WITNESS →
  DELIVERY-STATE-WITNESS → HTF-MEM depth (PWH/PWL, monthly, IPDA lookbacks;
  only after HTF-PROMPT proves consumption).
- **PHASE E — SECOND-SKILL INTELLIGENCE**: BASELINE-BENCH standing lab
  (random / simple-mechanical / Brain-minus-organ arms); shadow
  trade-management Brain (hold/trim/exit logged, SimBroker-scored);
  Mission Control replay scrubber.
- **PHASE F — FUNDED CAMPAIGN**: CAMPAIGN-MANAGER (drawdown headroom pacing,
  target distance, eval progression — feeds the RISK GATE ONLY, structurally
  invisible to the Brain); Topstep eval attempt gated on three measured facts:
  campaign expectancy verdict, friction ≤ threshold, target-lock live.
- **PHASE G — OLYMPUS HORIZON**: this repo becomes the Expansion Division —
  the proven template. New divisions get their own repos and native brains,
  inheriting doctrine, never runtime dependencies. Shared Risk/Memory/Review
  authorities; Mission Control grows into the org-wide throne room. Olympus
  is a federation of proven organisms, never a rewrite.

**Critical path:** credits + venue session → parallel campaigns →
adjudication opens the gates → context organs raise the Brain's ceiling one
measured piece at a time → the funded campaign is attempted on arithmetic,
not hope.

---

# PART I — AUDIT RESULTS (what the numbers actually are)

## 1. "50–55% sovereignty" — exact definition

Sovereignty is a **per-scan** predicate, owned by a single function:
`ai_brain/ecu.py::sovereign_conversion` (fails CLOSED). A scan is sovereign when
ALL of:

1. `brain_thesis.source == "llm"` — the **healthy live LLM path** authored it.
   Every degraded source (deterministic fallback, llm_failed_fallback,
   contaminated_input, brain_disabled, ecu_error) fails the predicate. AB-7
   inherited theses must show a healthy *current-cycle* candidate.
2. Direction is `bullish` or `bearish` **with an opportunity** — `conflicted` and
   `neutral` are non-sovereign *by definition*.
3. A `playbook_family` or `tool_family` is present (the conversion).

So the metric answers: **"On what fraction of scans was the Brain constitutionally
eligible to author fresh exposure?"** It is NOT % of trades authored, NOT % of
decisions surviving the gate chain, NOT a share of authority.

Measured (live_brain_study_20260710_095943.json):

| Session | Recorded era | Repair OFF | Repair ON |
|---|---|---|---|
| 2026-07-08 (224 scans) | 27 (12.1%) | 89.5 (40.0%) | 89 (39.7%) |
| 2026-07-09 (148 scans) | 18 (12.2%) | 73.4 (49.6%) | 81.8 (55.3%) |

"50–55%" was the 0709 session only. Honest range: **~40–55%** live, ~12% recorded.

**Selectivity ≠ quality (operator doctrine, adopted verbatim):** as sovereignty
rose 12%→55%, `would_authorize` fell 7→3.2 — the sovereign Brain is provably more
*selective* than the mechanical era. Whether that selectivity is *better* is an
open empirical question, and the study's own crude forward scores lean cautionary:
deduplicated `new_authorize_outcomes` show the live arms' newly authorized entries
scored 6/19 favorable (repair-off) and 3/7 (repair-on), with avg adverse excursion
~4–5 pts vs ~2 pts favorable (MFE/MAE points only — no stop geometry, no R, tiny
n, duplicate rows present in the artifact). Standing conclusion: **"The sovereign
Brain appears more selective than the previous mechanical pathway, but the quality
of that selectivity remains an empirical question."**

## 2. "Conflicted reads" — the resolver's target population is real

`conflicted` is a legal schema direction (`brain_schema.py`), with its own tighter
lifecycle age caps (`thesis_lifecycle.py:195`). Per the sovereignty autopsy, ~41%
of non-sovereign scans are conflicted reads — the Brain legitimately saying "the
evidence is split." This population is the direct target of the Narrative Conflict
Resolver (Track 4). It is the single largest *legitimate* sovereignty blocker.

## 3. Regime demotion — TWO independent evidentiary legs

`validation_suite_20260709_161212.json`: determinism gate PASS, would-authorize
0 → 7 with regime demoted — the gate blocked everything with no demonstrated
discrimination. **Caveat carried honestly:** that experiment measured the funnel,
not outcomes (SimBroker was REPLAY-3, later). The second leg: R-001, which
re-imported the demoted regime label as a veto basis, blocked a net **+3.06R**
population over 22 sessions — the label acting as a gate was measured actively
harmful. Demotion stands on both legs. Re-promotion only via earn-back governance
with human approval (standing doctrine; the Delivery-State Witness is a NEW organ
with NO inherited authority and no automatic path back).

## 4. Live substrate — two distinct populations, kept explicit

- **Journal population:** 19 QQQ paper trades, all 2026-06-09 → 06-12.
- **Trusted adaptive substrate (DECON-2 purified):** 5 of those 19 (0W/4L/1BE).
- Zero live trades in the seven weeks since. "Architecture-rich, evidence-poor"
  confirmed with numbers attached. The 5-trade figure is the *trusted substrate*,
  not the total history — the distinction stays explicit everywhere.

## 5. HTF — audited: HALF-WIRED (was "exists, wiring unverified" in v1.0)

Full verdict in `docs/audits/HTF_WIRING_AUDIT_20260730.md`. Four defects:

1. **Under-specified to the Brain, not absent** (operator's precision, adopted):
   on the QQQ live lane the data path is clean (scan_loop → snapshot["htf_memory"]
   → Brain payload) but `_call_llm` appends prompt addenda for news / volume /
   adaptive / friction / commander and **none for HTF** — the model receives the
   blob and may infer some meaning from field names; it was never given the
   interpretation contract every other witness organ got.
2. **`htf_conflict_flags` decorative** — computed (`snapshot_builder:326-334`),
   zero readers. Semantics never validated ("HTF bearish + intraday bullish" may
   be a retracement inside delivery, not a penalizable contradiction). **Doctrine:
   audit semantics before wiring ANY reader — a naive conflict penalty would be a
   miniature regime gate under a new field name.**
3. **Replay never feeds HTF** (`replay_session.py:208` passes no `htf_context`) —
   every Brain study on record measured an HTF-blind Brain. Worse, this is a
   **live/replay context mismatch**: live QQQ payloads carried HTF data, replayed
   payloads did not, so replay did not faithfully reproduce the live decision
   environment. Baselines remain valid for the system actually tested; they must
   be labeled HTF-blind.
4. **The money venue has no multi-day memory at all** — `data/htf_memory/` holds
   only QQQ.json (5 daily records, frozen 2026-07-09, confidence capped 60/100);
   no MNQ file; the deterministic lane's `facts_provider.py` has zero
   PDH/PDL/yesterday facts. The 20-condition author trades with no concept of
   yesterday.

## 6. The Brain runs on `gpt-4o-mini`

`ai_layer/ai_api_adapter.py` — provider OpenAI, default `gpt-4o-mini`, 30s
timeout. The entire discretionary judgment layer rides a mini-tier model. The
study harness supports model arms; BRAIN-MODEL-TRIAL is already the authorized
next mission from the freeze queue. Framed as an **experiment, not an automatic
upgrade** (operator doctrine): the question is not whether a stronger model is
smarter but whether it improves *measurable decision quality* enough to justify
cost, latency, and operational behavior — same scans, same payload, same prompt,
same validation/repairs, only the model varies; measure sovereignty, JSON
validity, repair rate, directional stability, conflict rate, invalidation
correctness, thesis quality, would-authorize behavior, cost, latency.

---

# PART II — ERA DOCTRINE

1. **Decision-Authority Freeze, not a development freeze.** During the ADAPTIVE-8
   campaign, nothing that changes live trading behavior ships (entry authority,
   direction, thresholds, qualification, gates, risk limits, sizing, management).
   Safe to develop: read-only dashboards, audit tooling, telemetry, friction
   reporting, passive memory accumulation, witness organs demonstrably outside
   every authority path, replay infrastructure, offline studies.
2. **Witness-first, earn-back always.** New organs enter as non-directional
   evidence + telemetry; authority is earned through measured gradients, never
   granted by architecture.
3. **Replay-parity doctrine** *(new — from the HTF audit)*: replay must reproduce
   the live decision environment. Any context present in live payloads and absent
   from replay (or vice versa) is an experimental-consistency defect, not a
   feature gap. HTF-REPLAY is the first repair under this doctrine.
4. **Market truth ≠ account truth.** The Brain never sees account state; campaign
   intelligence meets market intelligence only at the risk gate.
5. **One variable per mission → replay verdict → commit → milestone.**
   [NO CHANGE] remains publishable.
6. **No auto re-promotion.** Demoted judges stay demoted.

---

# PART III — MISSION TRACKS (operator's revised order, adopted)

## Track 0 — Preserve the current experiment
Decision-authority freeze holds; continue the venue campaign (MNQ smoke order /
TopstepX armed lane → ADAPTIVE-8's 20–30 real trades, 10+ sessions); collect real
outcomes; no live behavioral changes. Friction ledger (FC-0B promotion to
per-venue intended-vs-realized reporting) accumulates alongside — telemetry only.

## Track 1 — Repair experimental truth: **HTF-REPLAY**
The walker reconstructs daily HTF state from archived real candles and feeds
`htf_context` into replay snapshots. Prerequisite for all HTF measurement.
**Implementation invariants (operator contract, verbatim):**
1. Only archived real candles are used.
2. No future candle may enter the HTF state.
3. HTF state at scan T uses only data available before T.
4. Replay remains deterministic.
5. Existing HTF-blind studies remain reproducible.
6. HTF-enabled replay is a separately labeled arm.
7. No live decision-authority changes.
8. No prompt changes in this mission.
9. No HTF conflict flags gain authority.
10. Every replay scan can prove the exact HTF state it used (records available,
    latest completed daily candle, memory age, bias, confidence, untapped
    candidates).

## Track 2 — Finish auditing existing HTF before adding new HTF
Remaining audit items: engine unit semantics; QQQ live wiring regression lock;
payload size/shape in real calls; **conflict-flag semantics audit → keep with a
validated reader, or delete** (decorative state is forbidden state); MNQ passive
accumulation (**HTF-MNQ-ACCUM**: start recording MNQ daily records now — write-only,
campaign-safe; Brain consumption is a SEPARATE later mission gated on depth,
quality, semantics, replay support, and A/B evidence).

## Track 3 — ~~Measure the Brain's ceiling: **BRAIN-MODEL-TRIAL**~~ → **MODEL-CONTRACT-SMOKE**
> **CANCELLED 2026-08-04 in its replay-bake-off form.** The original text —
> "controlled experiment per Part I.6, model arms compared WITH HTF context
> fed, model choice made on measured results" — is withdrawn: those measured
> results would have been replay results, and replay cannot rank models.
> Replaced by a bounded compatibility probe (gate, not score) plus live
> adjudication in the frozen ADAPTIVE-8 campaign. Part I.6's "experiment, not
> an automatic upgrade" framing survives — the experiment is now the live
> campaign. See `docs/model_selection_doctrine.md`.

## Track 4 — Contextual intelligence (one organ at a time, witness-first)
1. **HTF-PROMPT** — the interpretation contract (`HTF_MEMORY_ADDENDUM`,
   presence-gated like `VOLUME_WITNESS_ADDENDUM`). Two clean A/Bs now exist:
   *data absent vs present-unexplained* (replay, via Track 1) and
   *present-unexplained vs present-explained* (the addendum). Validated in replay
   before any live flag flips.
2. **DAILY-THESIS** — Daily Market Thesis ritual: primary/alternative thesis,
   confirmation, invalidation, lifecycle states (ACTIVE → STRENGTHENING /
   WEAKENING → INVALIDATED → REPLACED), graded at the close into a bias-accuracy
   table. Anchoring answered by the mandatory alternative + explicit invalidation.
3. **CONFLICT-1** — Narrative Conflict Resolver, INSIDE the Brain (prompt +
   schema: `conflict_severity`, `dominant_evidence`, `unresolved_evidence`,
   `resolution_event`), never a mechanical judge beside it. A conflicted read
   becomes a gradeable prediction: did the named resolution event occur, which
   side resolved, was dominant evidence identified correctly. Target: the ~41%
   conflicted population.
4. **SMT-WITNESS** — ES↔NQ cross-market divergence, VOLUME-WITNESS recipe.
5. **MACRO-TIME-WITNESS** — ICT macro windows / silver bullet / midnight & true
   day open as labeled evidence, never a confidence bonus.
6. **DELIVERY-STATE-WITNESS** — new taxonomy, telemetry-only, no inherited
   authority; may petition through earn-back if gradients prove discrimination.
7. **RETRIEVAL-ABLATION** — does AB-4 memory earn its payload?

## Track 5 — Operational intelligence
**MISSION-CONTROL** (the throne room — funnel depth + refusing authority, thesis +
sovereignty + conflict state, Commander posture, risk incl. drawdown headroom,
venue health, P&L, kill switch; stretch: replay scrubber) · **BASELINE-BENCH**
(standing arms: random-entry, simple mechanical ICT, Brain-without-retrieval,
Brain-without-HTF/SMT, full Brain — isolates each organ's incremental value) ·
**CAMPAIGN-MANAGER** (account-lifecycle pacing; feeds the risk gate ONLY,
structurally invisible to the Brain).

## Track 6 — Future authority (post-campaign, earn-back gated)
Shadow trade-management Brain (hold/trim/exit reads logged, SimBroker
counterfactual scoring) · first real earn-back adjudication on live substrate ·
**TARGET-LOCK** (daily target lock — the one absent Olympus risk item; changes
live behavior, so it waits for the campaign verdict) · any authority change for
organs whose evidence earned the petition.

---

# PART IV — SEQUENCING

```
NOW (no credits, no live needed, campaign-safe)
  Track 1  HTF-REPLAY                 ← first: repairs the test environment
  Track 2  conflict-flag semantics audit · HTF-MNQ-ACCUM (passive)
  Track 5  Mission Control · friction-ledger scaffolding

CREDITS FUNDED 2026-08-04 — amended sequencing
  Track 3  MODEL-CONTRACT-SMOKE (gpt-5.6-sol ONLY, five cases max,
           pass/fail contract gate — NOT a bake-off, NOT a ranking)
  then     LIVE ADAPTIVE-8 campaign decides the production model
           (10+ sessions, 20-30 trades, frozen config, no mid-campaign tuning)
  WITHDRAWN Track 4  HTF-PROMPT A/B, RETRIEVAL-ABLATION  (as replay A/Bs)
  Track 4  DAILY-THESIS → CONFLICT-1 remain, as live-campaign questions

WITNESS BUILDS (parallel, one at a time)
  Track 4  SMT → macro-time → delivery-state

LIVE
  Track 0  ADAPTIVE-8 campaign under decision-authority freeze

POST-CAMPAIGN
  Track 6  adjudication · earn-back · target lock · shadow management
```

**The era's thesis, sharpened by the audit:** the bot may not need a new
higher-timeframe brain — it already has one that was built, partially wired,
insufficiently explained, omitted from replay, and never brought to the venue
where it will trade. Repair the test environment first (HTF-REPLAY), measure the
reader's ceiling second (model trial), then feed the Brain context one measured
organ at a time. Nothing in this roadmap grants authority; everything in it earns
the right to ask.

---

*Amendment history: v1.0 `883e8b6` (pre-audit) → v1.1 this commit (post-audit:
HTF verdict folded in, selectivity caveat added with forward-score evidence,
replay-parity doctrine added, tracks reordered per operator review, HTF-REPLAY
invariants adopted verbatim).*


---

# AMENDMENT 2026-08-18 — RELEASE STATE FOR THE 2026-08-19 SUPERVISED PRAC SESSION

*Documentation only. Every number below is repo-verified against the pushed
release; nothing here grants authority, and nothing here claims a market result.*

## PHASE TRANSITION

The project moves from **ARCHITECTURE / REPAIR** to **CONTROLLED PERFORMANCE
VALIDATION**. The next milestone is *observed behaviour*, not more architecture.

Stated precisely, because the distinction is the whole point:

* **PROVEN (engineering):** the software is ready for a supervised PRAC session.
* **UNPROVEN (market):** that Terra plus this mechanics / risk / execution
  architecture produces positive expectancy over a meaningful sample. That must
  be earned from real PRAC observations. Profitability is **not** claimed here.

## RELEASE HEAD

    db5a0054126ecddc33aadfb7a25e9b8616a2becc      local == remote
    previous certified base: 33ec23ad2ac9dbd0610aa930e9d8e4bc94b7b4ab

| Commit | Mission | Result |
|---|---|---|
| `7415449` | CONTINUITY-AUTHORITY | A provider bar inside a scheduled halt may not prove the market was open |
| `c583a1e` | EXEC-PRICE-ANCHOR-1 | Terra's absolute structural invalidation and objective survive the actual fill |
| `33a422b` | BAR-HALT-OBSERVATION-1 | Read-only observer to adjudicate historical bars during the CME MNQ halt |
| `db5a005` | PRAC-RELEASE-1 | Operator-attested protection authority and a read-only PRAC arm-eligibility preflight |

## FULL REPOSITORY CERTIFICATION

    6047 passed · 0 failed · 0 errors · 0 skipped · 0 xfailed
    34 subtests · 2 warnings

Baseline before this program was **5891 passed**; net additive growth **+156
tests**. Nothing was skipped, xfailed or weakened to obtain green. No runtime
evidence was staged.

## BRAIN CONTRACT

    previous   brain:2d3923b7a49da439
    current    brain:82f2d336796dbbb4      (recomputed x3, identical, source frozen)

Session-authorization bindings remain: brain fingerprint, brain model, retrieval
state, account, contract, date/expiry. A stale prior fingerprint is refused with
`AUTHORIZATION_BRAIN_CONTRACT_CHANGED`.

**Known test-environment caveat, not a production defect.**
`TestAuthorizationBindsTheBrain` can fail when that file is run STANDALONE,
because `.env` `AI_RETRIEVAL_ENABLED=true` leaks into a test that authorizes
`retrieval_enabled=false`. The isolated full suite controls the environment and
passes; 10/10 pass when `AI_RETRIEVAL_ENABLED=false` is matched explicitly.

## CONTINUITY AUTHORITY — CLOSED (55/55)

    PROVIDER HISTORICAL BAR EXISTS  !=  AUTHORITY TO CLAIM EXECUTED-TRADE OPPORTUNITY

Model B: **preserve the observation, gate the credit.** A provider bar inside an
authoritative scheduled break stays visible, keeps its OHLCV, and remains
provider evidence — but carries `trade_opportunity_authority = false`. The old
mutable-archive test is now hermetic.

The 2026-08-17 contradiction is **preserved, not erased**: CME publishes a
16:15–16:30 ET MNQ halt; the ProjectX archive holds 15/15 bars for those minutes
while correctly holding none of the sixty 17:00–18:00 maintenance minutes.

## EXEC-PRICE-ANCHOR-1 — CLOSED (62/62)

Production-reachable. Success path:

    Terra invalidation + objective → latest-quote risk recheck → MARKET entry
    → provisional attached tick brackets → ACK → full requested quantity proven
    → exact parent-only fills → VWAP → post-fill authorization against the
    ORIGINAL absolutes → actual-fill risk/R → exact child ownership
    → modify STOP → immediate STOP readback proof
    → modify TARGET → TARGET readback proof
    → final joint protection verification → entry established

Incomplete / unknown fill:

    venue read → cancel exact parent → IMMEDIATE FRESH venue read
    → flatten current/raced exposure → cancel mission-owned residual children
    → bounded repetition → final terminal readback

Safe recovery requires simultaneously: parent not working, position == 0, and
mission-owned working orders == 0.

    ACK != FILL     FILL != FULL FILL     FULL FILL != STRUCTURAL PROTECTION

## BAR-HALT-OBSERVATION-1 — READY (30/30)

`python tools/topstepx_halt_observer.py` — read-only, records `GatewayTrade`,
`GatewayQuote` and the post-window `retrieveBars` response independently, for
16:10 → 16:35 ET around the 16:15–16:30 halt.

Classification remains **HISTORICAL BAR AUTHORITY / PROVENANCE INSUFFICIENT**.
ProjectX has **not** been proven defective — its history endpoint documents
`t/o/h/l/c/v` and never promises a bar implies executed trades. This observer
exists to settle that empirically. **It is not a prerequisite for the morning
PRAC session.**

## ACCOUNTS

| Role | Account | Fingerprint | Status |
|---|---|---|---|
| **PRACTICE — tomorrow's only eligible lane** | `11111111` PRAC-V2-FIXTURE-00000000 | `acct:aaaaaaaaaaaa` | ACTIVE |
| RETIRED — forbidden | `33333333` 50KTC-TEST-FIXTURE-A | `acct:cccccccccccc` | HAZARD CLOSED |
| FUTURE COMBINE — forbidden this release | `22222222` 50KTC-TEST-FIXTURE-B | `acct:bbbbbbbbbbbb` | NOT AUTHORIZED |

The Combine is refused **by identity, not convention**. There is no PRAC →
Combine fallback.

## PROTECTION-AUTHORITY-1 — CLOSED

Account-side bracket settings are **not machine-readable**: `/api/Account/search`
publishes six fields and none is a bracket setting. The former doctrine
self-certification (a constant compared against itself, which could never fail)
is retired as authority. Production protection owner is `bot_attached_brackets`.

Operator visually confirmed on PRAC 11111111: **Position Brackets OFF, Auto OCO
OFF**.

    artifact     data/integration/topstepx/protection_authority_attestation.json
    fingerprint  prot:8a925d5481553bcd
    valid for    2026-08-19   (date-bound; venue settings can change overnight)
    confirmed_by operator / Maurice Phillips
    measurable_by_api  false

Independent `PA.verify(2026-08-19)`: no refusal reasons — AUTHORIZED.

## PRAC RELEASE SOFTWARE — READY (PREP 23/23)

    python tools/prac_release_preflight.py                 # PREP
    python tools/prac_release_preflight.py --final         # session morning

All 23 gates PASS for session date 2026-08-19: source clean · brain fingerprint ·
account is PRAC · fingerprint is PRAC · not a forbidden account · simulated ·
canTrade · visible · contract resolved · flat · no bot working orders · foreign
orders reported · protection authority · max risk 250 · max contracts 15 ·
preferred stop 35 · absolute ceiling 40 · min R:R 1.0 · attached brackets (not
BRACKETLESS) · brain enabled · model resolves `gpt-5.6-terra` · zero provider
calls during preflight · session authorization deferred.

    PREP_COMPLETE = true      ARM_ELIGIBLE = false

`ARM_ELIGIBLE=false` is **correct tonight** — only FINAL mode, with a
date-bound session authorization, can produce it. Neither mode arms anything.

## TOMORROW MORNING — NEXT ACTIVE MILESTONE: FIRST SUPERVISED PRAC SESSION

1. `git rev-parse HEAD` → expect `db5a0054126ecddc33aadfb7a25e9b8616a2becc`
2. Verify tracked `src/ tests/ tools/` clean
3. Verify the TopstepX UI still shows PRAC 11111111, Position Brackets OFF, Auto OCO OFF
4. Verify the protection attestation is still valid for 2026-08-19
5. `python tools/prac_release_preflight.py` → expect 23/23
6. Issue the 2026-08-19 date-bound SESSION AUTHORIZATION (canonical tool)
7. Verify it against PRAC account, MNQ U26, `brain:82f2d336796dbbb4`, retrieval state, protection authority, session date
8. `python tools/prac_release_preflight.py --final`
9. Require all FINAL gates pass and `ARM_ELIGIBLE = true`
10. **ONLY THEN** explicitly ARM PRACTICE
11. Supervise the first **naturally occurring** Terra candidate
12. Do **not** force or re-roll Terra
13. If Terra stands down, that is a valid outcome

## FIRST NATURAL PRAC TRADE — WAITING

The first PRAC execution should certify the whole chain: market truth → Terra
inference → candidate → structural invalidation → objective → risk → execution
token → market submit → provisional brackets → full fill → VWAP → post-fill
risk/R → stop absolute re-anchor → stop readback → target absolute re-anchor →
target readback → final protection → reconciliation.

**This is not proven merely because the software path is tested.** It requires a
real naturally occurring candidate.

## REMAINING NON-BLOCKING DEBTS

Distinct from tomorrow's PRAC eligibility:

1. **BAR-HALT empirical observation** — READY, 16:10 ET, read-only
2. **IFVG-ONTOLOGY-1** — IFVG observable, execution-quarantined
3. **OPENING-FVG-1** — `opening_fvg` remains production-dark
4. **PAPER-FVG-1 / BRAIN-CONTRACT-FVG-1** — existing debt
5. **Smoke P&L / self-trade telemetry** — smoke fills reported `0 trades / $0`
   because `customTag=None` did not match the bot-trade filter. Does **not**
   reopen the certified production execution path.
6. **Strict OCO sibling-trigger cancellation** — never directly observed. Not claimed.
7. **Naturally occurring Terra end-to-end proof** — OPEN, next major live evidence
8. **Combine release** — NOT AUTHORIZED; a future phase, after PRAC evidence

## STATUS BLOCK

    CONTINUITY AUTHORITY          CLOSED
    EXEC-PRICE-ANCHOR-1           CLOSED
    BAR-HALT-OBSERVATION-1        READY
    RETIRED ACCOUNT HAZARD        CLOSED
    PROTECTION-AUTHORITY-1        CLOSED
    PRAC RELEASE SOFTWARE         READY — PREP 23/23
    SESSION AUTHORIZATION         NOT ISSUED — morning gate
    ARM PRACTICE                  NOT ARMED
    FIRST NATURAL PRAC TRADE      WAITING
    COMBINE                       NOT AUTHORIZED

**Release ruling: SOFTWARE READY FOR 2026-08-19 SUPERVISED PRAC — YES.**

Not claimed: profitable expectancy, production/Combine certification, a certified
first Terra trade, or adjudicated halt semantics. All four remain unproven.


---

# AMENDMENT 2026-08-18 (NIGHT) — FULL-STACK RELEASE SMOKE **PASS**

*Supersedes the earlier 2026-08-18 amendment on release identity, protection
authority and smoke status. Documentation only.*

## RELEASE HEAD

    e6b6dd0      pushed · local == remote

**Tomorrow's identity check must expect `e6b6dd0`**, not `db5a005` or `70ce548`.

| Commit | Mission |
|---|---|
| `7415449` | CONTINUITY-AUTHORITY |
| `c583a1e` | EXEC-PRICE-ANCHOR-1 |
| `33a422b` | BAR-HALT-OBSERVATION-1 |
| `db5a005` | PRAC-RELEASE-1 |
| `70ce548` | DOCS — initial 2026-08-19 release-state amendment |
| `a2c9a5a` | PROTECTION-AUTHORITY-2 correction |
| `e6b6dd0` | Release-smoke wrapper: live-quote anchoring matching production authority |

## BRAIN CONTRACT

    frozen     brain:82f2d336796dbbb4      recomputed x3 identical after the final canary
    stale      brain:2d3923b7a49da439      must be refused

It did **not** move under PROTECTION-AUTHORITY-2 or the wrapper correction —
neither altered fingerprint-covered production sources.

## TEST STATE — stated precisely

    FULL PRODUCTION REPOSITORY    6080 passed / 0 failed / 0 errors / 34 subtests
                                  certified AFTER a2c9a5a (PROTECTION-AUTHORITY-2)
    FINAL RELEASE-SMOKE GUARDS    36 / 36

The final change (`e6b6dd0`) touched only `tools/topstepx_release_smoke.py` and
`tests/test_release_smoke_guards.py`; no `src/` module changed. **No second
full-repository run was performed after `e6b6dd0`,** and this ledger does not
claim one.

## PROTECTION-AUTHORITY-2 — CLOSED (a semantic error we made, and corrected)

v1 conflated two different TopstepX systems. The only venue evidence we ever had
was `errorCode=2 "Brackets cannot be used with Position Brackets."` — which names
**Position Brackets alone**. It never proved Auto-OCO must be off.

    AXIS A - MECHANISM      position_brackets    = confirmed_disabled
                            account_bracket_mode = auto_oco_order_based
    AXIS B - PRICE AUTHOR   protection_owner     = bot_attached_brackets

Auto-OCO supplies the **order-based OCO linkage**; the bot authors the actual
`stopLossBracket` / `takeProfitBracket` parameters, and Terra/mechanics retain
structural price authority. Auto-OCO never chooses the invalidation or objective.

    attestation schema      protection_authority.v2
    current fingerprint     prot:9c17bf2c9e7dd3e0
    superseded v1           prot:8a925d5481553bcd   (refused, never reinterpreted)

The software never changed the venue UI. The **incorrect requirement** induced
the operator's change; the requirement has been corrected.

## AUTO-OCO CORRECTION — LIVE EVIDENCE

    Auto-OCO OFF   order 3420877831   MARKET BUY 1   REJECTED   fillVolume 0   (no reason field)
    Auto-OCO ON    order 3420932370   MARKET BUY 1   FILLED @ 29545.75
                   -> stop 3420932371 · target 3420932372 · exactly one pair,
                      target linked to stop by venue OCO semantics

Only that configuration changed between the two attempts. This **supports** the
corrected model; it is not proof of TopstepX's undocumented internals.

## CANARY 2 — POST-FILL FAIL-CLOSED PROOF (not a re-anchor proof)

The wrapper anchored to a stale reference (29528.25) while the fill landed at
29545.75.

    authorized stop 29518.25 · target 29548.25   vs fill 29545.75
    -> stop distance 27.5 pts · risk $55.00 · reward 2.5 pts · R = 0.091
    -> reward_below_gate

The execution system **refused** to re-anchor, moved neither leg, repaired
nothing, entered fail-closed recovery, flattened, cleared residuals and proved
terminal state.

    P&L -2.00 · fees -0.72 · commissions -0.50 · net -3.22
    balance 151,273.86 -> 151,270.64        residual 0.00

Cause: **smoke-wrapper stale reference**, not production's submit-time price
authority.

## FINAL WRAPPER CORRECTION

Production convention recovered from its own slippage contract:

    BUY entry_slippage = fill_price - captured_best_ask   ->  BUY reference = ASK

    quote authority   LiveQuoteProvider
    freshness         MAX_QUOTE_AGE_SECONDS = 30.0  (production max_market_age)
    no fallback       to last-closed or stale history bars
    observed          bid 29540.50 · ask 29541.00 · age 0.193 s

## FULL-STACK RELEASE SMOKE — **PASS**

### PHASE A — REAL EXTERNAL AI, CERTIFIED

    source llm · requested gpt-5.6-terra · returned gpt-5.6-terra
    fingerprint brain:82f2d336796dbbb4 · latency 24.44 s
    tokens prompt 21,730 · completion 1,526 · reasoning 331 · total 23,256
    input  real MNQ feed · 300 bars · 31 snapshot sections · 4 tool instances
    output 33 parsed fields
    Terra  bearish / distribution / confidence 70 / current_action = stand_down
           tool family ["none"] · invalidation null · objective null
    marker prior_session_levels_absent
    provider calls 1 · orders 0 · fills 0

A valid `stand_down` counts as PASS. **No Terra re-roll occurred.**

### PHASE B — FINAL LIVE EXECUTION CANARY

    tag EXPBOT-smoke-3f85ce5b2036 · account 11111111 / acct:aaaaaaaaaaaa
    contract CON.F.US.MNQ.U26 · BUY · 1 MNQ · MARKET
    reference 29541.00 (live ask) · authorized stop 29531.00 · target 29561.00
    provisional -40 / +80 ticks
    place response {"orderId":3420996966,"success":true,"errorCode":0,"errorMessage":null}
    ACK 191 ms · fill 1 @ 29540.75 (0.25 favourable vs captured ask)

**Post-fill authorization — PASS**

    stop distance 9.75 pts · risk $19.50 · reward 20.25 pts · R = 2.077 -> AUTHORIZED
    no thesis repair · no stop movement · no target movement · no size repair

**Live children**

    stop 3420996967 · target 3420996968      exactly one pair, no duplicates

Uncorrected, the venue's fill-relative attachment would have left stop 29530.75
and target 29560.75.

**Live re-anchor — CERTIFIED by venue readback, not by modify acknowledgement**

    STOP    requested 29531.00 -> readback 29531.00 · child 3420996967 · proven
    TARGET  requested 29561.00 -> readback 29561.00 · child 3420996968 · proven
    JOINT   verified = true · anchored_to_structure = true · established = true
            OCO linkage survived both modifications

This is the live proof EXEC-PRICE-ANCHOR-1 was built to obtain.

**Cleanup — CERTIFIED**

    flatten 3420997172
    safe true · parent_working false · position_quantity 0 · mission_orders []
    terminal true · foreign orders untouched · no orphan · no residual

**Accounting**

    P&L -9.00 · fees -0.72 · commissions -0.50 · net -10.22
    balance 151,270.64 -> 151,260.42        residual 0.00

**Account isolation** — only PRAC `11111111` received broker writes. Combine
`22222222` and retired `33333333` untouched. No PRAC → Combine fallback exists.

## POST-SMOKE RELEASE STATE

    PREP after canary   23/23 · PREP_COMPLETE true
    venue               flat · 0 bot working orders
    protection          valid v2 attestation
    brain               enabled · gpt-5.6-terra · brain:82f2d336796dbbb4
    session auth        NOT ISSUED
    armed               false

## EXEC-PRICE-ANCHOR-1 — NOW **LIVE-VENUE CERTIFIED**

Observed end to end against TopstepX PRAC:

    live quote -> MARKET submit -> provisional attached OCO -> ACK -> full fill
    -> actual VWAP -> post-fill risk authorization -> exact stop child
    -> stop absolute modification -> stop readback -> exact target child
    -> target absolute modification -> target readback -> joint structural
    protection -> controlled flatten -> residual cleanup -> verified flat

This does **not** become "natural Terra trade certified". The canary geometry was
diagnostic.

## NATURAL TERRA → BROKER TRADE — **NOT YET PROVEN**

Phase A proved real production Terra works. Phase B proved the real production
execution lifecycle works. They were deliberately kept separate, because merging
them into a forced "AI-authored" trade would read stronger and prove less.

Remaining theorem: a **naturally occurring** Terra candidate under unmodified
doctrine → production risk authorization → execution → broker lifecycle, with no
forcing and no re-rolling.

    Status: WAITING FOR NATURAL PRAC OCCURRENCE

## STATUS BOARD

    CONTINUITY AUTHORITY          CLOSED
    EXEC-PRICE-ANCHOR-1           CLOSED — LIVE VENUE CERTIFIED
    BAR-HALT-OBSERVATION-1        READY — scheduled 16:10 ET, read-only
    RETIRED ACCOUNT HAZARD        CLOSED
    PROTECTION-AUTHORITY-2        CLOSED — Position Brackets OFF,
                                  Auto-OCO order mode ON, bot owns bracket prices
    PRAC RELEASE SOFTWARE         READY — PREP 23/23
    EXTERNAL AI INTEGRATION       CERTIFIED — real gpt-5.6-terra
    FULL-STACK RELEASE SMOKE      PASS
    SESSION AUTHORIZATION         NOT ISSUED — expected morning gate
    ARM PRACTICE                  NOT ARMED
    NATURAL TERRA->BROKER TRADE   WAITING
    COMBINE                       NOT AUTHORIZED

**SOFTWARE + LIVE VENUE STACK READY FOR 2026-08-19 SUPERVISED PRAC: YES.**

## PHASE

**CONTROLLED PERFORMANCE VALIDATION.** Not architecture development, not release
repair, not smoke-test development. The engineering propositions needed for PRAC
are proven. Do not add trading concepts because the roadmap has open space.

The remaining major unknown is **market performance**: does Terra plus the
certified mechanics / risk / execution system generate positive expectancy over a
meaningful sample? That is learned from real supervised PRAC observations.

## TOMORROW MORNING — THE ONLY REMAINING RELEASE ACTIONS

1. Verify the TopstepX UI: account **PRAC 11111111**, Position Brackets **OFF**, Auto-OCO **ON**
2. Verify `git rev-parse HEAD` → **`e6b6dd0`**
3. `python tools/prac_release_preflight.py` → require **23/23**
4. Issue the date-bound **2026-08-19 SESSION AUTHORIZATION**
5. `python tools/prac_release_preflight.py --final`
6. Require all FINAL gates PASS and **`ARM_ELIGIBLE = true`**
7. Explicitly **ARM PRACTICE**
8. Supervise
9. Wait for a **naturally occurring** Terra candidate
10. Do **not** re-roll Terra — a stand-down is a valid trading-system outcome

No further software work should be required before the session unless an actual
release gate fails.

## AFTER THE MORNING SESSION

Review the first natural candidate for: Terra thesis · candidate identity ·
structural invalidation · objective · quantity · risk · execution token · live
quote · submit · provisional protection · fill · VWAP · post-fill economics ·
stop re-anchor · target re-anchor · final protection · lifecycle · realized
result. That closes **NATURAL TERRA→BROKER PRAC-1** when it occurs legitimately.
No forced trade is required.

## 16:10 ET SECONDARY OBSERVATION

`python tools/topstepx_halt_observer.py` — read-only, records `GatewayTrade`,
`GatewayQuote` and `retrieveBars` across the CME 16:15–16:30 halt. **Not a
prerequisite** to the morning session.

## WHAT IS AND IS NOT CLAIMED

**Not claimed:** positive expectancy proven · profitable bot proven · Combine
certified · funded account certified · natural Terra trade certified · ProjectX
halt-bar semantics adjudicated.

**Proven tonight:** real external Terra integration · real PRAC MARKET order
transport · Auto-OCO order-based bracket compatibility · exactly one attached
protective pair · full-fill authority · post-fill economic authorization ·
fail-closed recovery on unlawful geometry · live absolute stop re-anchor · live
stop venue readback · live absolute target re-anchor · live target venue readback
· final joint OCO protection · controlled flatten · exact cleanup · accounting
reconciliation to zero residual · wrong-account isolation · PREP-before and
PREP-after readiness.
