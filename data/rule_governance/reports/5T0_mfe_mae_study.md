# 5T.0 — MFE/MAE Study (2026-06-11)

**Data:** 39 archived intents (2026-06-05 → 06-10, QQQ only) + 5 journal trades (4 closed).
**Units:** QQQ points from zone midpoint. Excursions truncated at intent expiry (median 2 bars) — all MFE figures are FLOOR estimates. n is small, one week, range-dominated. Cohort *comparisons* are informative; absolute values are provisional.

## Headline distributions (points)

| Cohort | n | MFE med | MFE p75 | MFE max | MAE med | MAE=0 | MFE≥1.5pt |
|---|---|---|---|---|---|---|---|
| ALL | 39 | 0.78 | 2.28 | 9.63 | 0.00 | 30/39 | 13/39 |
| range_rotation | 28 | 0.83 | 2.05 | 9.63 | 0.00 | 22/28 | 9/28 |
| reversal_attempt | 5 | 0.25 | 2.28 | 2.81 | 0.00 | 4/5 | 2/5 |
| **reversal playbooks** | 27 | **0.38** | 1.02 | 2.81 | 0.00 | 4/27 | 4/27 |
| **continuation playbooks** | 12 | **2.33** | 6.96 | 9.63 | 0.00 | **12/12 MAE=0** | 9/12 |
| exp=exhaustion_risk | 7 | 0.52 | 1.25 | 2.36 | **0.18** | 3/7 | 1/7 |
| exp=early_expansion | 21 | 0.40 | 0.86 | 6.96 | 0.00 | 17/21 | 5/21 |
| exp=mature_expansion | 7 | 1.86 | 2.40 | 2.44 | 0.00 | 6/7 | 4/7 |

Closed-trade anchor: June 10 loss — rps 5.68 pts, realized −0.72R (stop fill slippage past −1R reference), held 172 min.

## Findings

**F1 — The 2R take-profit has been geometrically unreachable.** Under invalidation-based stops (June 10: 5.68 pts), +2R requires an 11.4-pt favorable excursion. Only 3/39 intents ever exceeded even 3 pts. The TP rule has likely never been in play; in range conditions only the stop was ever live. The same applies to +1R breakeven (5.7-pt move needed): **the entire 5E.8 rule set was dormant on real geometry.** This is the study's most important result — the management rules aren't mis-tuned, they are unreachable.

**F2 — The real problem is stop geometry, not target geometry.** Typical favorable excursion in range regimes ≈ 0.8–2 pts; typical structural-invalidation stop ≈ 5–6 pts. Reward:risk available ≈ 0.15–0.35R. No exit policy fixes a trade built on that ratio. RANGE-profile trades need a tighter stop model (zone-referenced, not deep structural invalidation) — recorded here as a **recommendation for a future entry-side phase**, deliberately NOT implemented in 5T (management scope only).

**F3 — Exhaustion-risk entries are the worst cohort on both sides** (lowest MFE p75 among populated cohorts, only cohort with median MAE > 0). Independent confirmation of R-001 / GF-5F-003.

**F4 — Continuation intents dominated reversal intents** (MFE med 2.33 vs 0.38; MAE=0 in 12/12). Caveat: several were never touched (price ran without retrace), inflating the cohort. Directionally: when delivery is real, excursions run multi-point — supporting longer winner-retention in TREND profile. Also note these continuations appeared *during range_rotation labels*, reinforcing the regime classifier's range bias (known risk).

**F5 — Intent expiry truncates outcome data badly** (median 2 bars of tracking). 5H.3 proxy resolution inherits this. Recommendation: lengthen intent outcome tracking window for governance purposes (future consideration; touches Phase 1X expiry logic).

## Recommended Parameter Table (v1 — evidence-anchored, floor-estimate caveat applies)

| Parameter | DEFENSIVE (=current) | RANGE | TREND |
|---|---|---|---|
| breakeven_trigger_r | 1.0 | 0.75 | 1.5 |
| take_profit_r | 2.0 (full) | 1.25 (full) | 2.0 (**partial 50%**) |
| partial_fraction | — | — | 0.5, remainder trails |
| trail | after BE, structure | after BE, structure (tight) | after partial, structure, **no ceiling** |
| thesis_exit | shadow only | shadow only | shadow only |
| stop model | unchanged | (future phase: zone-referenced) | unchanged |

DEFENSIVE remains the active default until 5T.3 enables profile dispatch. All values carry registry records and counterfactual measurement; none are doctrine.

*No production behavior changed by this study.*
