# AB-5A — AI Brain Pressure Test (forensic, no authority changes)

Replay of June 10 + 11 (659 scans) comparing the legacy Wrapper against the new
Brain, every directional divergence forward-validated against real 1-minute bars
at 5/15/30/60 min. Analysis only — no code/authority/generation/execution changed.

## Divergence scoreboard (forward-validated)

659 scans → **299 directional divergences**.

| Verdict | Count | % |
|---|---|---|
| **Brain better** | 152 | 50% |
| Wrapper better | 141 | 47% |
| Equal | 6 | 2% |
| Inconclusive | 0 | 0% |

**Honest read: the aggregate is near-even (50 vs 47).** The Brain is NOT broadly
more accurate scan-by-scan. Its edge is concentrated and qualitative, not
statistical breadth — see below.

## The finding that matters: precision of refusal at the dangerous points

The two scans where the Wrapper actually drove a trade are exactly where the
Brain diverged and was right to:

| Decision point | Wrapper | Brain | 60-min reality | Who was right |
|---|---|---|---|---|
| **10:29 long entry** | bullish@65 (trade taken) | **conflicted** (AI bull vs delivery bear) | **−1.63** | **Brain** — refused the long that lost −1.34R |
| **13:17 short attempt** | bearish@74 (trade attempted) | **conflicted** (AI bear vs delivery bull, below_low sweep) | **+11.85** | **Brain** — refused a short into an 11.85-pt rally |
| 10:41 re-long | bullish@78 | conflicted | +0.40 | Wrapper (marginal) |
| 11:04 | bullish@76 | bullish@65 (agree) | +4.06 | both right (not a divergence) |

On **both** real trade decisions the Brain's conflicted stance was correct and
the Wrapper's conviction was wrong or dangerous. The Brain's value is **refusal
precision where it counts**, not scan-by-scan directional superiority.

## Where the Brain is NOT better

At 10:31 the Brain went bullish@0 (a `below_low` sweep on that scan flipped its
delivery read) while the Wrapper's bearish@40 matched the −1.7 move. The Brain's
sweep-semantics can be fooled by transient lower-TF sweeps. The 50/47 split is
real: the Brain abstains a lot (conflicted/neutral), which neither wins nor loses
on directional moves — it trades breadth for safety.

## Retrieval & memory contribution (critical, honest)

**In the current deterministic Brain, retrieval and memory do NOT change the
conclusion.** Direction is computed by the NA synthesis (delivery + liquidity +
protected swings); retrieved analogs populate `memory_matches` / supporting /
conflicting and the reasoning text, but cannot flip the direction. Verified by
construction: `_deterministic()` derives direction from `build_narrative`, then
attaches analogs as context.

- **Would the Brain reach the same conclusion without memory? YES** (deterministic core).
- Retrieval currently contributes **explainability** (analog support/conflict,
  prior outcomes) — not decision-changing signal.
- Memory (stance) contributes **consistency/continuity** across scans — not
  direction.
- This is a finding, not a defect: it means the LLM Brain (AB-1 `AI_BRAIN_LLM`)
  is where retrieval would actually shape reasoning; the deterministic core
  treats memory as evidence to display, not a vote.

## Narrative analysis (the June 11 stories)

- **10:29 — Wrapper story:** "bullish reversal after a confirmed sweep+reclaim;
  buy the IFVG." **Brain story:** "AI says bullish but PO3/sweep delivery is
  bearish (buy-side raid) — conflicted, no author." Difference: the Brain
  consumes *delivery direction* (sweep semantics) as a co-equal vote; the
  Wrapper folds it into a single bullish number.
- **13:17 — Wrapper story:** "bearish reversal, short it." **Brain story:**
  "AI bearish but a below_low sweep implies bullish delivery — conflicted."
  Difference: again delivery-vs-AI conflict detection the Wrapper lacks.

## Final verdict

1. **What the Brain sees that the Wrapper cannot:** provenance-separated delivery
   direction (sweep semantics), protected-swing state, active liquidity draw, and
   its own prior stance — as *distinct* inputs, not collapsed into one bull/bear
   scalar. This is what produced the correct conflict calls at 10:29 and 13:17.
2. **Retrieval contributes:** explainability (analogs + prior outcomes); it does
   not currently change conclusions in the deterministic core.
3. **Memory contributes:** cross-scan stance continuity; not direction.
4. **Narrative contributes:** the conflict detection (AI vs delivery) that the
   Wrapper's single scalar cannot express — the source of both June 11 saves.
5. **What the Brain understood on June 11 that the Wrapper missed:** that a
   confirmed sweep's delivery direction contradicted the AI/structure bias on
   both the long (10:29) and the short (13:17) — so both trades were conflicted,
   not convictions.
6. **Genuinely superior?** Not in breadth (50 vs 47). **Yes in precision at the
   decision points that produced real trades** — it refused both losers.
7. **Where:** conflict detection / refusal, driven by provenance-clean delivery.
8. **Evidence for promotion?** Yes, but narrow: promote the *refusal* capability,
   not generation. The breadth data does not support letting the Brain author
   trades.
9. **Safest first authority to grant:** a **Brain VETO** at the execution gate —
   the Brain may BLOCK/downgrade a trade when it returns `conflicted` or a
   `forbidden_direction` opposing the proposed trade, but may NOT create trades.
   This mirrors FC-1/NA-1 (a gate veto, can only reduce trading), and the data
   shows it would have correctly blocked both June 11 trades while leaving the
   11:04 agreed-bullish and the afternoon rally untouched. Generation authority
   (AB-5B) should wait for outcome-correlation evidence the Brain's *directional*
   calls beat the Wrapper's — which this study does NOT yet show.

## Deliverables status
June 10/11 replay ✓ · divergence analysis ✓ · retrieval analysis ✓ · narrative
analysis ✓ · scoreboard ✓ · authority recommendation ✓. No AB-5B, no authority
/generation/execution changes. Harness: `ab5a_pressure_test.py` (reproducible).
