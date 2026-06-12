# Phase FC-3 — Fable 5 Authority Path

Status: DESIGN (per Full-Capability Directive — "do not leave it permanently
in shadow; design the promotion path").

The Fable 5 shadow evaluator (`src/ai_layer/shadow_ai_evaluator.py`,
Phase AI-SHADOW) sees the same compact snapshot as the live AI and emits an
independent stance. This document defines its three-stage authority ladder
and the requirements gate for each stage. Stage transitions are env-flag
flips plus, for Stage 3, one wiring change that is specified below.

---

## Stage 1 — OBSERVATION (current; active in `launch_paper_session_fc.ps1`)

```
AI_SHADOW_ENABLED=true
AI_SHADOW_MODE=setups_only
AI_SHADOW_AUTHORITY=observe        # default; flag added in Stage 2 build
```

Behavior: stance recorded in `snapshot["ai_shadow"]` and `data/ai_shadow/`;
zero execution influence. Every submitted trade gets a shadow stance.

**Exit requirements (to Stage 2):**
- ≥ 20 closed trades with a recorded shadow stance
- Disagreement scoring exists: for every trade where shadow stance opposed
  the live direction (or said `stand_down`), record whether the shadow was
  right (trade lost) or wrong (trade won)
- Shadow "saves" (correct disagreements) ≥ shadow "costs" (wrong
  disagreements) in R terms over the sample

## Stage 2 — INFLUENCE (advisory; no veto)

```
AI_SHADOW_AUTHORITY=influence
```

Behavior: shadow disagreement becomes a *scalar* input, not a block:
- Strong opposite stance (confidence ≥ 70) applies a risk-multiplier haircut
  (e.g. effective multiplier × 0.5) through the existing `order_builder`
  multiplier path — same mechanism as the Risk Governor and regime cap
- Shadow agreement leaves sizing untouched (no positive boost — asymmetric
  by design; an uncalibrated yes is worth less than an uncalibrated no)
- Each haircut logged to the divergence ledger for outcome resolution

Wiring: one read in `order_builder.build_order()` (multiplier min-chain) +
ledger event emission. Fail-open: missing/erred shadow result = no haircut.

**Exit requirements (to Stage 3):**
- ≥ 50 closed trades under influence mode
- Haircut counterfactuals net-positive in R (the ledger already computes
  saved_r for thesis events; same arithmetic)
- Latency p95 within scan budget; API failure rate < 5% of setup scans

## Stage 3 — AUTHORITY (gate veto)

```
AI_SHADOW_AUTHORITY=veto
AI_SHADOW_VETO_MIN_CONFIDENCE=70
```

Behavior: new gate check `ai_shadow_permits` in
`execution_gate.evaluate_gate()` — blocks only when the shadow stance is
`stand_down` or directly opposite the trade intent at confidence ≥
threshold. Identical wiring pattern to FC-1's `council_permits_trade`.

Constitution (inviolable at every stage):
- **Fail-open**: timeout, error, missing key, garbage JSON → check passes.
  An external API outage must never halt trading; a broken evaluator gets
  fixed, not obeyed.
- The divergence ledger keeps scoring vetoes after promotion — demotion
  (flip back to `influence`/`observe`) is as cheap as promotion.

## Rollback at any stage

`AI_SHADOW_AUTHORITY=observe` (one env flip). `AI_SHADOW_ENABLED=false`
removes it entirely.
