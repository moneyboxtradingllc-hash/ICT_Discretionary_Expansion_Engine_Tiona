\# FORENSIC DISCOVERY LEDGER



\## ICT Discretionary Expansion Engine



\---



\## FD-001 — Execution Layer Innocence



Date: 2026-06-18



Finding:

Execution layer was never the issue.



Proof:

Tiona’s forensic scans proved:



\* no broker errors

\* no bracket failures

\* no account failures

\* no submission failures



Truth:

Execution only acts on upstream authority.



Doctrine:

Always audit authority before blaming execution.



Status:

LOCKED



\---



\## FD-002 — Qualification Veto Dominance



Date: 2026-06-18



Finding:

qualification.status=no\_trade fully suppresses:



\* playbook generation

\* toolbox activation

\* candidate generation

\* execution path



Truth:

Qualification is a hard gate.



Doctrine:

No qualification = no playbook.

No playbook = no toolbox.

No toolbox = no execution.



Status:

LOCKED



\---



\## FD-003 — Safe-Harbor Discovery



Date: 2026-06-18



Finding:

Lower-timeframe sweep/reclaim can exist inside dangerous HTF conditions.



But current architecture hard-vetoes it.



Truth:

Dangerous HTF does not always mean no opportunity.



Doctrine:

Mainline needs native exception-lane architecture.

Not patch doctrine.



Status:

UNDER ARCHITECTURAL REVIEW



\---



\## FD-004 — Strategy Latency Was Innocent



Date: 2026-06-18



Finding:

Deep runtime audit proved:



qualification\_ms ≈ fast

playbook\_ms ≈ fast

risk\_ms ≈ fast

toolbox\_ms ≈ fast

proposed\_decision\_ms ≈ fast



Truth:

Strategy is not the latency bottleneck.



Doctrine:

Never assume AI/strategy is slow without timing proof.



Status:

LOCKED



\---



\## FD-005 — Broker Maintenance Bottleneck



Date: 2026-06-18



Finding:

Hot path bottlenecks:



\* reconcile\_ms

\* account\_check\_ms

\* position\_check\_ms

\* open\_orders\_ms



Truth:

Broker maintenance was choking scans.



Doctrine:

Neutral scans should use cache.

Actionable trades require fresh preflight.



Status:

APPROVED FOR MAINLINE REVIEW



\---



\## FD-006 — Sandbox Branch Value



Date: 2026-06-18



Finding:

Tiona’s branch exposed structural weaknesses faster than mainline.



Truth:

Parallel testing accelerates forensic discovery.



Doctrine:

Sandbox branches are reconnaissance engines.



Mainline absorbs principles, not patches.



Status:

LOCKED



\---



\## FD-007 — QQQ vs MNQ Environment Truth



Date: 2026-06-18



Finding:

QQQ was acting as low-volatility sparring.

MNQ/NQ is the real combat environment.



Truth:

Mainline was designed for futures volatility.



Doctrine:

QQQ is useful for behavioral observation.

MNQ/NQ is required for timing validation.



Status:

LOCKED



























\---



\## FD-008 — Mainline Authority Stack Optimization Discovery



Date: 2026-06-18



Finding:

Mainline Expansion Bot has a real multi-layer authority structure, but the authority stack must be optimized before serious futures deployment.



Current authority stack includes:



\* Data / Snapshot Builder

\* Structure / Liquidity / Volatility / Expansion / PO3

\* Regime

\* Narrative Authority

\* AI Brain ECU

\* Qualification

\* Playbook

\* Risk

\* Toolbox

\* Market Commander

\* Decision Authority

\* Execution Gate

\* Broker Runtime



Truth:

The bot is no longer primarily mechanical.



The last seven days shifted the system from mechanical signal logic toward a genuine intelligence/authority organism.



However, intelligence density creates potential latency, authority compression, over-neutralization, and delayed execution if not architected correctly.



Doctrine:

Separate the bot into three lanes:



1\. Fast Hot Path



&#x20;  \* deterministic

&#x20;  \* no blocking LLM calls

&#x20;  \* trade/no-trade decision

&#x20;  \* candidate selection

&#x20;  \* execution gate

&#x20;  \* broker action



2\. Slow Intelligence Lane



&#x20;  \* AI thesis

&#x20;  \* narrative context

&#x20;  \* memory retrieval

&#x20;  \* market interpretation

&#x20;  \* background updates

&#x20;  \* cached authority state



3\. Post-Trade Learning Lane



&#x20;  \* MFE/MAE review

&#x20;  \* thesis correctness review

&#x20;  \* timing review

&#x20;  \* memory updates

&#x20;  \* adaptive learning feedback



Rule:

AI may own narrative authority, but fresh AI calls must not block execution.



The fast lane consumes the latest valid cached intelligence state.



Status:

APPROVED FOR MAINLINE ARCHITECTURE REVIEW



\---



\## FD-009 — Mainline Must Absorb Principles, Not Sandbox Patches



Date: 2026-06-18



Finding:

Tiona’s branch exposed valuable weaknesses:



\* qualification veto dominance

\* missing safe-harbor exception lane

\* trade-management gaps

\* liquidity TP disconnect

\* oversized stop vulnerability

\* break-even safety problem

\* broker maintenance latency

\* forensic logging necessity



Truth:

These are valuable reconnaissance findings, but Tiona’s bot is not the same organism as mainline.



Tiona’s branch is an experimental sandbox.



Mainline must not copy patches directly.



Doctrine:

Sandbox branch findings must be translated into mainline-native architecture.



Bad:

Copy patch into mainline.



Good:

Extract structural principle, audit mainline, design native doctrine.



Status:

LOCKED



\---



\## FD-010 — Timing Intelligence Is the Next Mainline Battleground



Date: 2026-06-18



Finding:

Playbook and Toolbox already provide real entry-model intelligence.



The system can generate and rank tools such as:



\* FVG

\* IFVG

\* Rejection Block

\* Order Block

\* OTE

\* Liquidity Sweep

\* Breaker / Continuation models



Truth:

Tool selection exists.



But timing optimization is not yet mature.



The missing layer is not “which tool is valid?”



The missing layer is:



Which valid entry offers the best timing, lowest heat, best asymmetry, and cleanest strike location?



Doctrine:

Do not rebuild Toolbox.



Add or formalize Timing Intelligence between:



Toolbox

→ Timing Intelligence

→ Execution Gate



Timing Intelligence should evaluate:



\* heat

\* entry proximity

\* invalidation efficiency

\* premium/discount alignment

\* liquidity objective alignment

\* narrative alignment

\* urgency

\* chase risk



Status:

NEXT MAJOR MAINLINE AUDIT TARGET



\---



\## FD-011 — Mainline Live-Market Readiness Question



Date: 2026-06-18



Finding:

The bot may be approaching the point where more architecture alone cannot answer the next questions.



Remaining questions include:



\* Can it execute in real futures volatility?

\* Is timing late or early?

\* Does it chase?

\* Does it correctly refuse bad conditions?

\* Does Market Commander over-neutralize?

\* Does the AI Brain update fast enough?

\* Does the Toolbox select the right weapon in combat?



Truth:

Some truths cannot be discovered inside QQQ or offline architecture work.



NASDAQ futures exposure is required to validate timing and execution behavior.



Doctrine:

Mainline should not wait for every future feature before controlled Topstep practice.



But it must enter practice only with:



\* clear forensic logging

\* practice-only protection

\* small size

\* no live funded exposure

\* controlled observation goal

\* no blind automation trust



Status:

UNDER DEPLOYMENT REVIEW





---


## FAILED_BREAKOUT SENSOR DOCTRINE DEBT

Recorded 2026-08-14, STEP 4B.12 §5. Offline measurement only — no AI calls, no
provider calls, trading DISARMED.


### The defect

`structure/liquidity_engine.analyze_liquidity` publishes `failed_breakout`, and
that field has been `False` on every scan this bot has ever run. Not because the
pattern never occurred — because the predicate is unsatisfiable through TWO
INDEPENDENT contradictions.

CONTROL-FLOW CONTRADICTION

    high  branch reached only when   last_close >= ref_high
          body requires              last_close <  ref_high
    low   branch reached only when   last_close <= ref_low
          body requires              last_close >  ref_low

CANDIDATE-UNIVERSE CONTRADICTION

    ref_high = max(pierced_highs), and membership of that pool already
    guarantees                       prior <= ref_high
    the predicate requires           prior >  ref_high
                                     (symmetric on the low side)

The second is the deeper one. The proposition cannot live beneath
`if pierced_highs:` at all: pool membership asserts the prior close sat INSIDE
the level, a failed breakout asserts it sat BEYOND it. Deleting the `elif` would
have looked like a repair and left the branch exactly as dead.

Measured on the real MNQ tape, 1000 evaluations:

    sweep_detected TRUE        412
    failed_breakout TRUE         0


### What the repository does and does not establish

A REACHABLE SIBLING EXISTS. `structure/manipulation_detector._failed_breakout`
carries the only docstring in the repo for the concept —

    "Closed beyond a level, then closed back inside — a breakout that failed."

— and implements exactly the arithmetic the liquidity engine's dead branch
attempts, without the pierced-pool nesting. Over those same 1000 evaluations it
fired 202 times (1m 55, 3m 87, 5m 60, 15m 0). Both sensors are published into
`snapshot["liquidity"][tf]`: the dead one as `failed_breakout`, the live one as
a component of `["manipulation"]["components"]`.

So "failed breakout" is NOT an impossible market event, and the concept is not
undocumented. What remains UNRESOLVED is which sensor expresses this bot's
doctrine, because the two disagree on the two questions that matter:

    reference level   manipulation: max(highs) / min(lows)
                      liquidity:    a pierced pool containing the prior close
    bars examined     manipulation: any adjacent pair in the lookback
                      liquidity:    the last bar against the previous slot

Neither is derivable from the other, and nothing in the repo adjudicates.


### Consumer exposure

`playbooks/playbook_classifier._score_failed_breakout_reversal` awards +40 for
the liquidity field. That contribution is structurally unreachable. The family
remains reachable on MSS (+20), BOS (+15) and reclaim (+15), so the implemented
scoring surface is not the surface its source code describes. NOT PROVEN: that
any playbook winner ever changed, that any trade was missed, or that the family
is entitled to those points.

Other consumers of the dead field: `toolbox/tool_readiness`, `toolbox/toolbox_engine`
(+20), `structure/po3_engine`, `qualification/trade_qualification_engine`,
`ai_layer/narrative_builder`, `ai_layer/confidence_engine`,
`ai_layer/ai_snapshot_formatter`, `market_data/market_events`.


### Standing prohibition

NO predicate repair, NO re-plumbing of the sibling sensor, NO deletion or
redistribution of the +40, NO threshold change — until failed-breakout market
doctrine is independently ruled. Those are four separate rulings and none of
them is an epistemics repair.


### What WAS done

Capability representation only. `analyze_liquidity` now publishes
`proposition_capability` and `capability_reason` alongside the unchanged
booleans, distinguishing three states previously collapsed into `False`:

    EVALUATED              detector able, evidence present, pattern absent
    UNEVALUABLE_EVIDENCE   detector able, required evidence unavailable
    UNAVAILABLE_SENSOR     detector cannot evaluate the proposition at all

`failed_breakout` is permanently UNAVAILABLE_SENSOR with reason
PREDICATE_UNREACHABLE_DOCTRINE_UNRESOLVED. Sensor unavailability outranks
evidence unavailability: it would be unevaluable with perfect evidence, so
reporting it as an evidence problem would imply better evidence could fix it.

Pinned by `tests/test_liquidity_sensor_capability.py`, including a
non-vacuous exhaustion proof (4000 generated series: sweeps > 0 confirms the
search space is live, failed_breakout == 0 confirms the predicate is dead).


### Retired requirement

The positive-control gate for `failed_breakout` ahead of the OLD/TRUTHFUL/FINAL
liquidity differential is RETIRED — not waived. The premise that a valid
positive control exists under the current predicate was falsified. The
differential reports the column as sensor-unavailable rather than boolean-negative.


### AMENDMENT — 2026-08-14, precision corrections

DOCUMENTED LOCAL SEMANTICS ≠ CANONICAL DOCTRINE. The manipulation detector
supplies a documented local definition. It is NOT established as the
authoritative bot-wide meaning, because a second producer using the same English
name exists and nothing adjudicates between their evidence universes.

    DOCUMENTED LOCAL SEMANTICS   manipulation_detector implementation
    SECOND IMPLEMENTATION        liquidity_engine, dead
    CANONICAL BOT-WIDE DOCTRINE  UNRESOLVED

UNREACHABILITY IS PROVEN BY CONSTRUCTION, not by sampling. The two algebraic
contradictions are the proof. The 4000 fixed-seed generated series are a
NON-VACUOUS REGRESSION OVER AN ACTIVE SEARCH SPACE — they show neighbouring
sweep behaviour is live while the dead branch stays silent in that population.
Calling that an exhaustion proof would overclaim, and the construction proof is
the stronger of the two anyway.


### FAILED_BREAKOUT BRAIN CONTRACT DEBT

Traced 2026-08-14 by serializing the real Terra payload rather than reading
source. `brain_prompt` line 113 instructs Terra "failed break implies
failed_breakout_reversal", while:

    dead liquidity sensor        did not reach Terra at all
    live manipulation sensor     did not reach Terra at all
    canonical doctrine           UNRESOLVED

Terra has been given a routing doctrine for evidence the mechanical layer never
delivered. NOT repaired: no prompt-line deletion, no wiring of the sibling into
Terra or into the +40 scorer, no scorer change, no threshold change, until
Step 5 / doctrine adjudication.

What IS now delivered is capability, not evidence:
`liquidity.sensors["liquidity_engine.failed_breakout"] = UNAVAILABLE_SENSOR`
with reason and an explicit scope note. A capability record states what one
sensor can do; it makes no claim about the market and does not speak for any
other sensor.

A DEFECT I INTRODUCED AND CORRECTED, recorded because the class matters: the
first archive-summary line read "no failed-breakout evidence exists in either
direction". That was FALSE on the very snapshot it was measured against —
manipulation reported positives on 3m and 1m of that same scan. A sensor's
incapacity was stated as a fact about the market. Now sensor-scoped and pinned
by a test that fails on any global phrasing.


### DEAD_SENSOR_BOOLEAN_MIRRORED_AS_DERIVED_FACT

`market_events.py:406` republishes the dead `failed_breakout` boolean into the
DERIVED_FACTS layer. Neither scoring nor cognition — a permanent `False` sitting
in the derived-fact layer with no capability beside it. Deferred to the
event-layer authority audit, recorded so it is not lost.


### THE BORDER CHECKPOINT

`build_brain_input` is where epistemics were being discarded. Measured before the
repair, on the real tape:

    'failed_breakout'         in Terra payload: False
    'proposition_capability'  in Terra payload: False
    'UNAVAILABLE_SENSOR'      in Terra payload: False
    'prior_close_authority'   in Terra payload: False
    'ai_context' / 'summary'  in Terra payload: False

`liquidity["events"]` was a positive-only comprehension, so "detector ran, no
sweep" and "detector could not answer" were byte-identical to Terra. Note also
that `ai_context.summary` — where the archive formatter writes — is NOT part of
the Terra payload: improving it improves the forensic record, not cognition.

Repaired with two ORTHOGONAL channels: `events[]` unchanged (positive facts),
plus `evaluation[]` stating evaluability for EVERY timeframe. Every timeframe
deliberately: emitting rows only for exceptional timeframes would have made
Terra infer DETECTOR_EVALUATED from a missing row, which is absence-as-semantics
one layer later.

DETECTOR_EVALUATED is deliberately not FALSE_PROVEN. `find_swings` and other
dependencies remain inside the unfinished adjacency audit, so it means only "the
current detector executed under the prerequisites presently modeled".

Verified on the real tape at the 18:11 observation hole:

    15m  DETECTOR_EVALUATED
     5m  DETECTOR_EVALUATED
     3m  UNEVALUABLE_EVIDENCE   PREVIOUS_SLOT_CLOSE_UNAVAILABLE
     1m  DETECTOR_EVALUATED

Field-level authority survives end to end: the 15m and 5m buckets are degraded
yet their CLOSE is proven, so they stay evaluable, while the 3m bucket whose
terminal constituent IS the missing minute does not.

Pinned by tests/test_brain_liquidity_evaluability_contract.py (16 tests),
including that CASE B and CASE C — the pair that used to collide — serialize
differently, and that the manipulation sibling does not leak into the payload.


### §9 RESIDUE + §10 — ONE LAW, REPAIRED AT THE AUTHORING BOUNDARY

Two failures that looked unrelated turned out to be the same collapse reached
through different control flow:

    A. UNVERIFIED SCHEDULE. `is_expected` answers False for every minute of a
       date outside the verified ranges, so `expected_buckets` returns [] and
       the caller read that as "no expected slot sits between these bars". What
       the calendar actually said was "I have no jurisdiction here". Silence
       from an authority that never had jurisdiction became proof of absence,
       and the array neighbour was asserted to be the previous market slot.

    B. CALENDAR FAILURE. The exception path returned UNCADENCED_LEGACY, whose
       consumer bridged to `candles[-2]`.

    UNKNOWN SCHEDULE IS NOT AN EMPTY SCHEDULE.

Both now converge on PRIOR_CADENCE_UNKNOWN, deliberately NOT folded into the two
states it superficially resembles: PRIOR_NO_OBSERVATION claims a slot was
expected and not observed (absence PROVEN), and PRIOR_CLOSE_UNPROVEN presupposes
a previous bucket was identified. Neither is true here. An unverified schedule is
not a data gap; the unknown belongs to cadence.

WHY A CAPABILITY-ONLY REPAIR WAS REJECTED. Publishing
capability=UNEVALUABLE_EVIDENCE while still COMPUTING sweep/reclaim from a
bridged close repairs what Terra is told and leaves the booleans intact for the
scoring, routing and positive-trigger consumers that never read capability --
two different realities inside one engine, Terra told UNEVALUABLE while a scorer
is handed True. The refusal therefore lives at the AUTHORING boundary and the
capability label is derived from that same decision.

A VALUE IS NOT AN AUTHORISATION. The resolver asked `prior_close is not None`; a
float is not evidence that the float may author a proposition, and a bridged
close is a perfectly good float. Replaced by one exhaustive table:

    PRIOR_ADJACENT         may author   (cadence KNOWN, no slot between)
    PRIOR_AUTHORITATIVE    may author   (terminal constituent observed)
    PRIOR_CLOSE_UNPROVEN   may NOT
    PRIOR_NO_OBSERVATION   may NOT
    PRIOR_CADENCE_UNKNOWN  may NOT
    PRIOR_UNCADENCED       may NOT
    anything unrecognised  may NOT      (unknown never authorises)

Reasons now name the ACTUAL missing prerequisite -- a calendar-authority failure
reported as a "close unavailable" would tell a reader that better price data
could repair it, and nothing is wrong with the candles in that case:

    PREVIOUS_SLOT_CLOSE_UNPROVEN
    PREVIOUS_SLOT_NOT_OBSERVED
    EXPECTED_SLOT_AUTHORITY_UNAVAILABLE
    NO_CADENCE_SUPPLIED

The legacy bridge survives only as an EXPLICIT opt-in
(`analyze_liquidity(..., allow_uncadenced=True)`, mirroring `find_fvgs`), used by
`market_events._sweep_at` alone. That module is proven NONCANONICAL: repo-wide no
file under `src/` imports it; its only consumers are two test modules. The
earlier DEAD_SENSOR_BOOLEAN_MIRRORED_AS_DERIVED_FACT entry is therefore semantic
debt, not a production Brain path.

THE MASKING COINCIDENCE IS GONE. `len(settled) < 2` produced UNCADENCED_LEGACY,
which used to bridge; it was masked only because MIN_CANDLES (4) exceeds 2 -- a
coincidence of constants, not an authority contract. The protection is now the
table, so it holds at any MIN_CANDLES. Pinned by a test.

Real tape, production path unchanged where cadence IS known; the 18:11 hole now
reports the sharper reason:

    15m DETECTOR_EVALUATED · 5m DETECTOR_EVALUATED
     3m UNEVALUABLE_EVIDENCE  PREVIOUS_SLOT_CLOSE_UNPROVEN
     1m DETECTOR_EVALUATED

Pinned by tests/test_cadence_authority_boundary.py (23 tests), including a REAL
positive control -- the same geometry produces a genuine sweep under
authoritative cadence and no positive under each non-authorising state -- and a
both-worlds test proving the deterministic booleans and the Terra payload cannot
disagree about whether a sweep happened.


### §11/§12 — THE CHAIN, NOT THE SEAMS

Every unit before this proved one seam. A chain of correct seams is not itself a
guarantee, and this project already has two proofs of that: `ai_context.summary`
was perfectly truthful and never reached Terra at all, and the §10 hole published
an honest `prior_close_authority` beside a capability that contradicted it.

One path under test, raw 1m to the serialized Terra payload, eight cases each ONE
perturbation away from the healthy tape:

    A healthy          positive event + DETECTOR_EVALUATED on all four TFs
    B interior gap     bucket degraded, CLOSE still proven, proposition evaluable
    C terminal gap     PREVIOUS_SLOT_CLOSE_UNPROVEN
    D slot absent      PREVIOUS_SLOT_NOT_OBSERVED
    E cadence unknown  EXPECTED_SLOT_AUTHORITY_UNAVAILABLE
    F calendar failure EXPECTED_SLOT_AUTHORITY_UNAVAILABLE, no bridge despite a
                       perfectly usable array-neighbour number
    G failed_breakout  UNAVAILABLE_SENSOR, unchanged by every other failure
    H archived input   UNKNOWN / PRODUCER_DID_NOT_STATE_CAPABILITY, nothing
                       backfilled as historical knowledge

THREE FINDINGS, in order of severity.

1. FORENSIC CAUSE WAS BEING DESTROYED. E and F were BYTE-IDENTICAL everywhere
downstream -- snapshot, archive and payload alike -- because `cadence_rule` died
inside the resolver. "We hold no calendar authority for this date" and "the
calendar machinery raised" are the same proposition-level consequence and Terra
rightly gets one reason for both, but they are different incidents and a forensic
reader could not tell them apart. `prior_cadence_rule` is now published into the
snapshot for diagnostics, and a test asserts it does NOT reach Terra.

The collision test NAMES the sanctioned pair rather than dropping the assertion:

    _INTENTIONALLY_IDENTICAL_TO_TERRA = {("E_cadence_unknown", "F_calendar_failure")}

so an unexpected collision still fails, and a separate test proves the sanctioned
one remains separable in diagnostics. Same to Terra must never quietly become
lost everywhere.

2. A LATENT CRASH in the fix for (1). `prior` is rebound to the float
`prior_close` mid-function, so reading `.get("cadence_rule")` at the return
raised AttributeError. Captured before the rebind now. No unit test would have
caught it -- none reaches that path with a cadence_rule present.

3. THE FIXTURE WAS TOO SHORT and the engine was right. Forty minutes gives 15m
two settled buckets, fewer than MIN_CANDLES, so CASE A came back
INSUFFICIENT_OBSERVATIONS there. Rebuilt at 120 minutes (8x15 = 24x5 = 40x3) with
the pool placed to be a confirmed fractal high on all four timeframes at once. A
positive control that cannot reach a timeframe proves nothing about it.

Pinned by tests/test_raw_to_terra_integrated.py (21 tests).
