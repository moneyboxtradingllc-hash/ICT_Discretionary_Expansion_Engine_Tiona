# MODEL SELECTION DOCTRINE — LIVE VALIDATION OVER LABORATORY OPTIMIZATION

*Recorded 2026-08-04 by operator directive. Supersedes the Track 3
BRAIN-MODEL-TRIAL framing in `EXPANSION_EVOLUTION_ROADMAP.md` (v1.2, commit
`7a25abb`) and the credit-gated Phase B2 replay research program. Documentation
first: no behavior change ships from this document.*

---

## 0. The decision

API credits were funded on 2026-08-04, which under Roadmap v1.2 would have
opened Phase B2 — a broad, credit-bound replay research program
(BRAIN-MODEL-TRIAL → HTF-PROMPT A/B → RETRIEVAL-ABLATION).

**That program is cancelled.** It is not deferred, not re-sequenced, not
awaiting a bigger budget. The operator's standing doctrine is **live-market
validation, not laboratory optimization**, and a high-volume paid replay
bake-off between model arms is laboratory optimization wearing a lab coat.

What replaces it is two things, in strict order:

1. A **bounded compatibility probe** — does the candidate model satisfy the
   existing Brain contract at all? Pass/fail. Cheap. Capped.
2. The **frozen ADAPTIVE-8 live campaign** — the only venue permitted to say
   whether a model is *better*.

### Why the replay program was the wrong instrument

Replay can answer *"does this model produce output the organism can consume?"*
It cannot answer *"does this model make money."* The two questions look
adjacent and are not. A replay bake-off would have produced a confident
numeric ranking — sovereignty rates, would-authorize counts, divergence
tallies — over archived candles with no fills, no slippage, no queue position,
and no adversary. Ranking models on that substrate and then calling the winner
*better* is the exact failure mode the one-variable-mission doctrine exists to
prevent: a measured selection that measured the wrong thing.

The organism already has scar tissue here. `data/replay/runs/live_study/`
shows five runs of one arm on one session producing `would_authorize` counts
of 5, 3, 1, 3, … — a 5× spread on identical inputs with only sampling noise
varying. Any bake-off small enough to afford is too noisy to rank on; any
bake-off large enough to rank on is too expensive to justify and still
measures replay, not the market.

---

## 1. What replay MAY be used for

**Compatibility only.** Replay's authorized question is binary and narrow:

> Does the candidate model satisfy the Brain contract that the current
> production model satisfies?

The contract checks, all pass/fail, all grounded in code that already exists
(§2 lists the full nine as they apply to the authorized probe):

| # | Check | Contract source |
|---|---|---|
| 1 | **Valid schema** — required fields present, correct types, phase/direction in the accepted vocabulary | `brain_schema.validate_llm_core`, `brain_schema.validate_brain_output` |
| 2 | **Correct-side invalidation** — a directional thesis names a numeric invalidation, on the correct side of price | `brain_validation.directional_invalidation_gap`, `wrong_side_initial_invalidation`, `invalidation_side_ok` |
| 3 | **Valid playbook / tool family** — a directional read does not return `none`/neutral families | `brain_validation.directional_family_gap`, `NEUTRAL_TOOL_FAMILIES` |
| 4 | **Deterministic downstream handling** — `normalize_output` runs clean and the scan completes its stage trace without exception | `brain_validation.normalize_output` + replay stage trace |
| 5 | **Acceptable latency** — per-call wall time within the Brain timeout budget (`AI_BRAIN_TIMEOUT_SECONDS`, currently 25s) | measured per call |
| 6 | **Fail-closed behavior** — malformed or absent model output produces an explicit deterministic fallback and never an authorization | `narrative_brain` fallback path |

### What replay may NEVER be used for

The following claims are **forbidden** from any replay artifact, report,
commit message, or milestone entry:

- expectancy, profitability, R-multiple, or win rate
- "model X is better/smarter/stronger than model Y"
- any ranking of models by decision quality
- any justification for changing decision authority, risk doctrine,
  execution gates, or management policy

A probe result is a **gate**, not a **score**. Its only two outcomes are
ELIGIBLE FOR LIVE CAMPAIGN and NOT ELIGIBLE.

---

## 2. MODEL-CONTRACT-SMOKE

*Scope corrected 2026-08-04 (second operator directive). An earlier draft of
this section proposed 25 scans × 3 model variants under a $2.00 ceiling — 75
calls. That was rejected as a miniature bake-off: shrinking a ranking exercise
does not convert it into a compatibility check, and probing three price tiers
implies a comparison the live campaign alone is permitted to make. The
authorized probe is **five cases, one model.***

### Scope

| Parameter | Value |
|---|---|
| Model under test | **`gpt-5.6-sol`** — and only Sol |
| Not called | `gpt-5.6-terra`, `gpt-5.6-luna` — **forbidden this mission** |
| Cases | **5 maximum** |
| Question | Does the flagship external Brain satisfy the existing contract? |
| Not the question | Which GPT-5.6 price tier is best |

`gpt-5.6` is a valid alias routing to `gpt-5.6-sol` (official OpenAI
documentation). The bare alias does not appear in the `/v1/models` listing,
which enumerates concrete model IDs, not aliases.

### Official pricing (per 1M tokens, recorded 2026-08-04)

| Model | Input | Cached input | Output |
|---|---|---|---|
| **`gpt-5.6-sol`** *(candidate)* | $5.00 | $0.50 | $30.00 |
| `gpt-5.6-terra` | $2.50 | $0.25 | $15.00 |
| `gpt-5.6-luna` | $1.00 | $0.10 | $6.00 |
| `gpt-5.4-mini` | $0.75 | $0.075 | $4.50 |

Terra, Luna and 5.4-mini are recorded for cost-planning reference only. Listing
a price is not authorization to call the model.

### The five cases

Each case is one Brain call against a representative context. Pass/fail only.

| # | Case | What it proves |
|---|---|---|
| 1 | **Clean bullish context** | Directional read produced; schema, family and invalidation correct on the bull side |
| 2 | **Clean bearish context** | Same on the bear side — catches direction-dependent invalidation-side errors |
| 3 | **Genuine conflicted context** | Conflict is expressed *as conflict*, not resolved into false confidence |
| 4 | **Neutral / no-opportunity context** | The model can decline — neutral/`wait` families are legitimate output, not a failure |
| 5 | **Invalid or incomplete context** | **Fail-closed**: degraded input yields an explicit deterministic fallback and never an authorization |

### What is validated (all pass/fail)

1. **API reachability** — `gpt-5.6-sol` resolves and responds
2. **Structured-output compliance** — honors `BRAIN_JSON_MODE`
   (`response_format={"type":"json_object"}`) and the request shape in
   `narrative_brain._call_llm`
3. **Schema acceptance** — `validate_llm_core`, then `validate_brain_output`
4. **Correct-side invalidation** — `directional_invalidation_gap`,
   `wrong_side_initial_invalidation`, `invalidation_side_ok`
5. **Valid family selection** — `directional_family_gap`, `NEUTRAL_TOOL_FAMILIES`
6. **Deterministic downstream handling** — `normalize_output` runs clean; the
   scan completes its stage trace without exception
7. **Fail-closed behavior** — case 5 produces fallback, zero authorizations
8. **Latency** — per-call wall time within `AI_BRAIN_TIMEOUT_SECONDS` (25s)
9. **Measured token cost** — real `usage` × official pricing above

Measured payload baseline (zero-cost instrumentation, 2026-08-04, session
20260709): system 8,798 chars + user 14,456 chars ≈ **5,800–7,800 input tokens
per call**. At Sol's $5.00/M input and $30.00/M output, five cases sit in cents,
not dollars — the earlier $2.00 ceiling mechanism is unnecessary at this scale
and is withdrawn along with the harness it was designed to bound.

### Explicitly forbidden in this mission

- historical profitability, MFE/MAE, win rate, expectancy
- directional superiority or any model ranking
- calling Terra or Luna
- changes to prompts, authority, gates, qualification, risk, management,
  or execution — **the probe observes the contract, it does not touch it**

### Exit criteria

All nine validations pass → Sol is **CONTRACT-COMPATIBLE** and is configured as
the production candidate for the frozen live ADAPTIVE-8 campaign. Any failure →
**NOT ELIGIBLE**, failure recorded verbatim. Compatibility confers no
expectation of superiority; the only permitted statement about Sol at that
point is *contract-compatible, unproven.*

---

## 3. Live evaluation — the frozen ADAPTIVE-8 campaign

Model selection is decided **here**, on real-time market data and actual trade
outcomes, or it is not decided.

**Production candidate: `gpt-5.6-sol`**, configured once MODEL-CONTRACT-SMOKE
passes. The campaign's question is the one the operator actually asked —
*does the Expansion Bot benefit from the flagship external Brain?* — and it is
answered by real-time sessions and completed trades, never by replay.

### Freeze conditions (non-negotiable for the campaign duration)

- decision-authority configuration — **unchanged**
- risk doctrine — **unchanged**
- execution gates — **unchanged**
- management policy — **unchanged**
- **no mid-campaign tuning of any kind**

The only permitted variable is the production model identity.

### Duration

- **10+ sessions**, and
- **20–30 completed trades**

Both floors must be met. Neither alone ends the campaign.

### Measured per session

| Metric | Definition |
|---|---|
| **Realized R** | Actual closed-trade R, real fills |
| **MFE / MAE** | Max favorable / adverse excursion per trade |
| **Thesis accuracy** | Did the Brain's stated thesis describe what the market did |
| **Invalidation quality** | Was the named invalidation level correct, respected, and informative |
| **Authorization quality** | Were authorized trades the right ones; what did refusals cost or save |
| **Latency** | Per-scan Brain wall time under live conditions |
| **Failure rate** | Fallbacks, malformed output, timeouts, repair turns |
| **API cost per session** | Measured tokens × price — the operating-cost input to the funded-eval arithmetic |

Mission Control renders daily; the EOD candle archive continues; the friction
ledger accumulates. These are existing rituals and are unchanged by this
document.

### Adjudication

Only after both floors are met does a model comparison become sayable, and
only in terms of the metrics above on real fills. Until then the correct
statement about any candidate model is: *contract-compatible, unproven.*

---

## 4. Roadmap amendment

`EXPANSION_EVOLUTION_ROADMAP.md` v1.2 Phase B is amended:

- **B2 replay research program — CANCELLED.** BRAIN-MODEL-TRIAL as a
  multi-arm paid replay bake-off is withdrawn. HTF-PROMPT A/B and
  RETRIEVAL-ABLATION are withdrawn *in their replay-bake-off form*; if either
  is ever revived it must be as a live-campaign question or a bounded
  compatibility probe, never as a paid replay ranking exercise.
- **B2 replacement — MODEL-CONTRACT-SMOKE**, as specified in §2: five cases
  maximum, `gpt-5.6-sol` only, pass/fail.
- **Phase B1 live ADAPTIVE-8 campaign is unchanged** and becomes the sole
  adjudication venue for model selection, per §3.
- Part I.6's framing ("experiment, not an automatic upgrade") survives and is
  strengthened: the experiment is the live campaign, not the replay.

---

## 5. Standing law

1. Replay proves **compatibility**. Live proves **value**.
2. A probe is a gate, never a score.
3. **Shrinking a bake-off does not make it a compatibility check.** A probe
   sized to compare models is a comparison however few calls it makes; a probe
   is correctly sized when it tests the contract and nothing else.
4. Test one candidate. Probing several price tiers implies a ranking that only
   the live campaign may make.
5. No paid replay run without a pre-set spend bound, enforced from measured
   `usage` rather than predicted cost.
6. No model claim beyond what the measurement venue can support.
7. The campaign freeze is not negotiable by a promising interim result — that
   is precisely when it matters.
