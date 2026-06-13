# AB-5A-L — Full LLM Brain Forensic Replay (live GPT, analysis only)

Re-validates Brain capability using the ACTIVE LLM Brain (`AI_BRAIN_LLM=true`,
gpt-4o-mini). No authority/generation/gate/execution changes. Live GPT calls
made for the deep dive + a stratified divergence sample (cost/time-responsible
sampling — the full 659-scan live run is supported by the harness but not fired).

## 1. Scoreboard

- Wrapper-vs-Deterministic divergences over all 659 scans: **299**.
- **Sampled LLM scoreboard** (~35 divergence scans, real GPT, fwd-validated
  5/15/30/60m): **LLM better 5 · Wrapper better 5 · Deterministic better 10 ·
  Equal 15 · Inconclusive 0.**

**Honest aggregate read: on the noisy sample the LLM did NOT broadly beat the
deterministic core or the wrapper.** Like AB-5A, breadth is not where the LLM
wins. Its edge is concentrated at the marquee decision points (below) and in
narrative quality. (Sample is small and the LLM is non-deterministic — treat the
aggregate as directional, not precise.)

## 2. June 11 deep dive (actual live LLM output)

| Point | Wrapper | Det | **LLM Brain** | reality |
|---|---|---|---|---|
| 10:00 raid | neutral@49 | bearish | **bearish@60** | +0.93/60m |
| 10:25 window | **bullish@72** | conflicted | **bearish@60** | (opposed wrapper) |
| **10:29 LONG** | **bullish@65** (lost −1.34R) | conflicted | **bearish@70, must_not_do=take bullish** | down |
| 11:00 prot-low | conflicted@70 | bullish | **bullish@60** | rally |
| **13:17 SHORT** | **bearish@74** (rally ahead) | conflicted | **bullish@60, must_not_do=bearish** | **+11.85** |

At the FOUR decisions that mattered, the LLM Brain opposed the wrapper and was
right or safe: it refused the 10:29 long (bearish), refused the 13:17 short
(bullish), opposed the 10:25 window bullish, and called 11:00 bullish into the
rally. Full 10:29 LLM narrative (real call):
> "bearish delivery amidst exhaustion risk; price testing near a protected high
> while targeting sell-side liquidity at 699.6"; delivery="bearish intentions,
> lack of upward movement despite proximity to a protected high"; liquidity=
> "swept above prior highs but quickly reclaimed → focus on sell-side"; draw=
> sell-side 699.6; PH_status=approaching; invalidation=702.5; forbidden=bullish;
> must_not_do=["take bullish positions","ignore exhaustion signals"].

## 3. Narrative quality audit

The LLM Brain explains what the others cannot:
- **Wrapper:** direction + confidence + one sentence. No liquidity/draw/protected/invalidation structure.
- **Deterministic:** a single direction label (often "conflicted") + template reasons. No prose explanation.
- **LLM Brain:** what happened, why, liquidity taken (sweep reclaimed), liquidity remaining (sell-side 699.6), favored + forbidden direction, invalidation level (702.5), protected-high status (approaching), recommended playbook family. **This is the narrative intelligence layer as envisioned.**

## 4. Retrieval audit

The LLM cites analogs in `dominant_reasoning` ("as seen in prior analogs", "as
observed in previous similar market conditions"). But retrieval **explains** more
than it demonstrably **changes**: the LLM's direction tracks the delivery/sweep
evidence; the seeded corpus is largely same-day records. A clean with/without-
retrieval causal A/B is confounded by LLM non-determinism → **inconclusive**
whether retrieval altered (vs decorated) conclusions. Honest finding: retrieval
is currently corroborative narrative, not a proven direction driver.

## 5. Memory audit

Stance memory persists and is supplied, but across the deep-dive points the
LLM's direction was driven by the current scan's delivery/liquidity, not visibly
by prior stance. No evidence stance memory altered direction or confidence in
this replay. (It provides continuity/explainability, consistent with AB-4.)

## 6. Enum/fallback audit

- Sampled run: **5 fallbacks / 36 calls ≈ 14%** (reason mostly degraded/empty;
  earlier runs showed `invalid_schema: narrative_phase 'early_expansion'`).
- Classification: **prompt/schema mismatch** — the model occasionally emits a
  `narrative_phase` outside the 7-value enum, or a near-empty narrative.
- Every fallback was explicit + logged (no silent masking). **Reliability ~86%
  clean LLM, ~14% explicit deterministic fallback — a real hardening item.**

## 7. Capability audit (with examples)

| Capability | LLM Brain? | Example |
|---|---|---|
| delivery shifts | YES | "bearish delivery... lack of upward movement" (10:29) |
| liquidity events | YES | "swept above prior highs but quickly reclaimed" (10:29) |
| protected swings | YES | PH_status=approaching, invalidation=702.5 |
| active draw | YES | "sell-side liquidity at 699.6" / "buy-side at 702" |
| invalidation | YES | 702.5 (10:29), None where absent |
| playbook families | PARTIAL | names families, but sometimes generic ("continuation") |
| tool families | **WEAK/INCONSISTENT** | at 10:29 dir=bearish yet rec_tools=bullish_ifvg; at 13:17 dir=bullish yet rec_tools=bearish_ifvg — tools contradict its own direction |

## 8. Comparative performance

- **vs Wrapper:** the LLM sees liquidity-as-objects, draw, protected status, and
  invalidation — none of which the wrapper's single bull/bear scalar can carry.
  Largest gain: the 10:29 and 13:17 refusals (the two real trades).
- **vs Deterministic:** the LLM produces a *directional* read with a coherent
  *explanation* where the deterministic core only says "conflicted." Largest
  gain: narrative quality + decisiveness at conflict points.
- **Largest weakness:** reliability (~14% fallback) and internal inconsistency
  (recommended_tool_family contradicts narrative_direction).

## 9. Promotion readiness (recommendation only — no promotion)

**Safest first responsibility: NARRATIVE REPORTING ONLY.** Evidence: the LLM is
the clear winner on narrative *explanation* but is NOT yet proven directionally
superior in aggregate (sampled scoreboard near-even/behind deterministic) and
carries a ~14% fallback rate + tool/direction inconsistency. Reporting captures
its real value (operator insight, divergence logging) with zero risk.

**Next candidate after hardening: VETO authority** — its strongest evidence is
the decisive, correct refusals at 10:29 and 13:17. A brain veto (block a trade
when the LLM strongly opposes it) is the FC-1/NA-1 pattern and would have
blocked both June 11 losers. But veto should wait until the ~14% fallback rate
is driven down (enum hardening) so the veto isn't silently degrading to
deterministic. NOT confidence adjustment, playbook/tool recommendation (the tool
output is inconsistent), directional, or generation authority on this evidence.

## Final questions

1. **Genuinely superior to the Wrapper?** At the decision points that produce
   trades — YES (decisive correct refusals + structured narrative). In broad
   scan-by-scan accuracy — not demonstrated.
2. **Genuinely superior to the Deterministic Brain?** In narrative quality and
   decisiveness — YES. In sampled directional accuracy — no clear edge (det
   scored higher on the small noisy sample).
3. **What creates the advantage?** Full-context LLM reasoning over delivery +
   liquidity-as-objects + protected swings + draw, producing an explained,
   decisive narrative instead of a scalar or a "conflicted" label.
4. **What still needs improvement?** Reliability (enum/fallback ~14%) and
   self-consistency (tool family vs direction). Retrieval causality unproven.
5. **Operating as the envisioned narrative intelligence layer?** YES for
   narrative explanation and conflict detection; NOT yet validated as a superior
   directional/authority engine. The layer is real; its authority must be earned
   incrementally, reporting first.

## Deliverables
June 10/11 replay ✓ · divergence/scoreboard ✓ · narrative-quality ✓ · retrieval ✓
· memory ✓ · fallback ✓ · capability ✓ · comparative ✓ · authority recommendation
✓. Harness: `ab5al_forensic_replay.py`. No authority/generation/execution changes.
