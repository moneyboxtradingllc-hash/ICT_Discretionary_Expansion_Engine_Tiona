# HTF CONFLICT-FLAG SEMANTICS AUDIT — 2026-07-30

*Track 2 of the Context-Intelligence Era roadmap. Doctrine on trial: "audit
semantics before wiring ANY reader — a naive conflict penalty would be a
miniature regime gate under a new field name." Audit only — NO code changed;
the flags remain computed-and-unread exactly as before. Evidence:
`data/replay/reports/htf_flag_harvest_20260730.json` (22 sessions, 13,043
scans, harvested via the HTF-REPLAY arm) and `htf_flag_audit_20260730.json`
(pre-registered questions Q1–Q5).*

## Verdict

**SPLIT.** The flag field conflates two signals with opposite audit outcomes:

1. **The disagreement flag (`htf_bias_X_vs_narrative_Y`) — semantics
   VALIDATED with measured discrimination.** First outcome evidence in the
   repo that multi-day context carries directional information.
2. **The gap flag (`unfilled_gap_up/down`) — REJECTED as a conflict signal.**
   It is not a conflict, it latches for entire sessions (84% of all flag
   volume), and its gating is defective.

## Structural findings (before any data)

- The "conflict" is measured against the **demoted mechanical
  `narrative_direction`** (a witness conduit since AUTHORITY-TIER3, commit
  `a820e7c`), not against the Brain's thesis.
- The gap flag is gated inside `if htf_bias in ("bullish","bearish")` —
  an unfilled gap on a neutral-bias day produces **no flag** (Q5 measured
  this suppression at **1,330 scans**).

## Measured results

**Q1 — availability.** `htf_bias` was directional on 10,542/13,043 scans
(81%), across 20 of 22 sessions. The flags are not a rare-path curiosity.

**Q2 — does the disagreement flag discriminate?** Forward move of the
mechanical narrative's direction (raw close deltas, points):

| Group | n (30m) | mean 15m | mean 30m | mean 60m | win 30m | session-mean 30m (n=20) |
|---|---|---|---|---|---|---|
| **DISAGREE** (flag fired) | 2,785 | −0.19 | **−0.94** | −0.51 | 44.7–47.2% | **−0.87** (35% of sessions +) |
| **AGREE** | 3,919 | +0.08 | **+1.05** | +1.08 | 54.1–60.6% | **+1.07** (60% of sessions +) |
| HTF neutral | 1,578 | −0.20 | −0.48 | −0.43 | ~51% | −0.37 |

Separation at 30m: **~2.0 points**, same sign at every horizon, and it holds
at the session level (35% vs 60% of session means positive) — so it is not a
few-big-days artifact of autocorrelated scan rows.

**Q3 — who is right in disagreements?** The HTF side: HTF-signed forward
moves are positive at every horizon (+0.19 / +0.94 / +0.51; win 52.7–55.1%).
When the multi-day ladder and the intraday mechanical narrative point in
opposite directions, the ladder tends to win.

**Q4 — the gap flag.** 6,212 of 7,410 total flagged scans (84%) are gap
flags. Seven sessions were flagged on 100% of scans — a gap that never fills
latches the "conflict" all day. That is a background *condition*, not a
per-scan signal (the R-001 lesson: a flag firing on most scans with no
per-scan variation cannot discriminate). Gap-fill behavior itself is mild
and thin: 8/17 first-flag sessions filled by EOD; 30m drift toward fill
+1.27 pts (64.7%, n=17 — descriptive only).

**Q5 — gating defect.** 1,330 unfilled-gap scans produced no flag solely
because `htf_bias` was neutral. The gap information is inconsistent even on
its own terms — and it is *already redundant*: `gap_context.side/filled`
rides the same `htf_memory` payload block unconditionally.

## Caveats (declared with the numbers)

Raw close-delta points, no stop/target geometry; 1-minute scan rows are
autocorrelated (session-level stats reported for that reason); the
narrative_direction being judged is a demoted witness, so the honest reading
of Q2/Q3 is "**HTF bias carries multi-day directional information the
intraday mechanical read lacks**" — which is precisely the Context-
Intelligence Era's load-bearing hypothesis, here receiving its first
positive outcome evidence. Effect sizes are mild (53–61% win rates), not
certainties — evidence for a *witness*, not for a veto.

## ADDENDUM (same day, operator methodology review) — paired within-session test

The operator asked whether one long directional day could be masquerading as
thousands of independent observations. A paired within-session comparison
(agree vs disagree 30m means inside the SAME session, both arms n≥10) answers
it, and **partially deflates the headline**:

- Agree beats disagree in **13/20 sessions** (sign-consistent but modest;
  one-sided binomial p≈0.13 — not significant on its own).
- Mean paired difference **+1.94 pts**, but **concentrated**: 2026-06-12
  (+15.1) and 2026-06-25 (+19.6) carry most of the magnitude; excluding those
  two, the mean paired diff is ≈ **+0.2 pts**.
- Consecutive 30m windows overlap (29 of 30 bars shared) — nominal scan
  counts vastly overstate effective sample size.

**Downgraded standing conclusion (operator phrasing, adopted):** HTF–intraday
directional agreement/disagreement appears to separate future directional
outcomes in the archived population — sign-consistent across most sessions
but magnitude-concentrated in two high-range sessions — and the signal has
NOT been tested as a Brain input, a trade-quality improvement, or an
expectancy improvement. Witness-grade evidence; grounds for the HTF-PROMPT
A/B, not for authority.

"The HTF side wins at every horizon" is hereby tightened: it is the same
disagree-population rows re-signed to the HTF direction (an arithmetic
mirror of the narrative result, not an independent test), per-scan,
overlapping windows, neutral-HTF excluded.

## Recommendations (queued as separate missions; nothing shipped here)

1. **FLAG-SPLIT (small repair):** remove `unfilled_*` from
   `htf_conflict_flags` — the information already lives in `gap_context`,
   unconditionally, without the latching or the neutral-bias gating defect.
   The conflict-flag list then means one thing only.
2. **Reader = the Brain, never a gate.** The validated disagreement flag's
   correct consumer is the HTF-PROMPT addendum (Track 4): *explain* the
   flag's semantics to the Brain and let the A/B measure the effect. No
   mechanical stage should read it — a 55% edge as a veto is the regime
   mistake with better branding.
3. **Do not prompt-inject the outcome claim.** The addendum explains what
   the flag means, not "HTF is usually right" — that stays a measured result
   in this artifact, re-testable, never a baked-in instruction.
