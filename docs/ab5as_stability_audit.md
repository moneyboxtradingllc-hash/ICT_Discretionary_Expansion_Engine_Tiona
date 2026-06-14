# AB-5A-S — LLM Brain Directional Stability Audit (evidence only)

Frozen inputs, identical retrieval (verified deterministic), empty/frozen memory.
`_call_llm` called directly N times per point to isolate RAW LLM judgment from
the repair pipeline. No authority/generation/execution/gate changes.

**Rep count:** N=12 per point (72 live GPT calls). The directive specified 25;
25×6=150 sequential live calls exceeds a single session window, so N=12 was run
(enough to band stability at ~8% resolution). Harness is parameterized
(`STABILITY_N`) for a full 25-rep run.

## Directional stability scorecard

| Point | Consensus | Band | Direction distribution (N=12) |
|---|---|---|---|
| 10:00 | **100%** | HIGH | bearish 12 |
| 10:05 | 50% | **UNSTABLE** | neutral 6 / conflicted 5 / bearish 1 |
| 10:25 | 58% | **UNSTABLE** | bearish 7 / bullish 4 / conflicted 1 |
| 10:29 | 75% | MODERATE | bearish 9 / conflicted 3 / **bullish 0** |
| 11:00 | 92% | HIGH | bullish 11 / bearish 1 |
| 13:17 | 92% | HIGH | bearish 11 / bullish 1 |

Confidence is tight everywhere (sd 2.8–6.4). Retrieval **stable=True** at every
point (deterministic store). Memory frozen (empty). 0 LLM failures across 72 calls.

## Retrieval & memory stability
- **Retrieval:** identical inputs → identical analog IDs + scores + order at all
  6 points. Deterministic cosine over a fixed store. **Not** a source of instability.
- **Memory:** frozen empty stance per run. **Not** a source of instability.
- Therefore all observed directional variance is **LLM-intrinsic** (or driven by
  genuinely ambiguous input), not retrieval/memory drift.

## Thesis consistency
- 10:00 / 11:00 / 13:17: stable thesis (one direction dominates ≥92%).
- 10:29: stable REJECTION thesis — 0/12 bullish; variance is only bearish↔conflicted
  (both reject the long). Same thesis, different label.
- 10:05: **severe variance** but non-directional (neutral↔conflicted) — the input
  had NO sweep/delivery signal, so "no clear read" is itself consistent.
- 10:25: **severe variance, directional** (bearish↔bullish) — the genuine instability.

## Critical analysis
1. **Most stable:** 10:00 (100%), 11:00 (92%), 13:17 (92%).
2. **Least stable:** 10:05 (50%, non-directional), 10:25 (58%, directional split).
3. **Instability correlates with input signal clarity, not retrieval:** the
   unstable points are where delivery/liquidity is ambiguous — 10:05 has NO sweep
   (no delivery signal → neutral/conflicted split); 10:25 is an extended, mixed
   state. The stable points all have a clear sweep+reclaim. Retrieval conflict is
   ruled out (deterministic).
4. **Not random — clusters at ambiguous market states.** Clear-signal scans are
   stable; ambiguous scans split. That is the expected (and somewhat reassuring)
   failure mode, but it is still real directional non-determinism at 10:25.
5. **Does the Brain consistently invalidate the 10:29 long? YES.** 0/12 bullish
   (9 bearish + 3 conflicted). It never endorses the losing long. **Robust.**
6. **Does the Brain consistently REJECT the 13:17 short? NO — the opposite.**
   It is 11/12 **bearish**, i.e. it stably ENDORSES the short. And that short
   faced a +11.85 rally — so the Brain is **stable but stably WRONG** here.
   Important correction to earlier phases: prior "brain refused the short" was the
   DETERMINISTIC core (conflicted) and a 1/12 minority LLM sample, NOT the LLM's
   stable behavior.
7. **Robust enough for authority? No, not uniformly.** 10:29 (reject long) and
   10:00/11:00 are trustworthy; 10:05/10:25 are unstable; 13:17 is stable-but-wrong.

## The most important finding (structure leakage into the LLM)
At 13:17 the reconstructed input carried a **below_low sweep → bullish delivery**
semantics (correct — the rally followed), yet the LLM returned **bearish 11/12**.
The LLM overrode the correct delivery signal. The likely cause: `brain_input`
includes `ai_context` (`directional_bias` = structure, and `market_narrative` =
the structure-tainted summary text), and at 13:17 the structure bias was bearish.
**The LLM anchors on the structure-tainted narrative text in its own input** —
a leakage path the generation firewall (AB-2A/B/C) never closed because it lives
in the LLM input, not the deterministic lane. This is evidence, not a fix.

## Final questions
1. **Is the LLM Brain stable?** Partially — stable at clear-signal points,
   unstable at ambiguous ones. Form is reliable (H1); judgment is not uniformly.
2. **Stable at the points where trades occur?** 10:29 yes (robust long-rejection);
   13:17 yes in variance but **stably wrong**; the ambiguous 10:25 is unstable.
3. **Trustworthy points:** 10:00, 11:00, and 10:29 (for long-invalidity).
4. **Unreliable points:** 10:05 (non-directional churn), 10:25 (directional split),
   13:17 (stable but contradicts correct delivery → wrong).
5. **What causes instability:** input ambiguity (no/weak delivery signal) +
   LLM-intrinsic variance at extended states; plus structure-tainted summary text
   in the LLM input anchoring direction (13:17).
6. **LLM / retrieval / memory / market-ambiguity?** Retrieval and memory are
   deterministic (cleared). Instability is **LLM-intrinsic + market-ambiguity**,
   with a distinct **input-contamination** effect (structure summary) at 13:17.

## Verdict
Reliability of FORM is solved (H1). Reliability of JUDGMENT is **not**: the Brain
is stable where the signal is clear, non-deterministic where it is ambiguous, and
— critically — stably wrong at 13:17 because its input still carries the
structure-tainted narrative summary. Authority remains unjustified. Open items
(no fixes here): (a) directional non-determinism at ambiguous states; (b) the
structure-summary leakage into the LLM input.

Harness: `ab5as_stability_audit.py` (`STABILITY_N` configurable). Evidence only —
no fixes, no authority, no AB-5B.
