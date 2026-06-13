# AI BRAIN — Gap List (target vs MAP-0) + Phase Plan

Target = the 20-section Full Narrative Intelligence Layer directive.
Baseline = MAP-0 (`docs/map0_system_wiring.md`) + AI-0 autopsy.

## GAP LIST (req# → state at MAP-0 → gap)

| # | Requirement | MAP-0 state | Gap |
|---|---|---|---|
| 1 | Market visibility (price, candles, ATR, session H/L, prior-day, overnight, gap) | AI got NO price on no-setup scans, NEVER candles; no prior-day/overnight refs exist | **Severe.** Price/candle starvation + missing data-plane organs |
| 2 | Structure visibility (witness) | received, but as authority not witness | Reframe to witness |
| 3 | Delivery visibility (direction/state/conf/evidence/PO3) | PO3 dirs sent raw; synthesized delivery_state NOT sent | Send synthesized delivery |
| 4 | Liquidity as objects (spent/unspent/draw/targets/prior-session) | events only, never levels/draw; no prior-session | Send objects + draw |
| 5 | Protected swings as first-class + approach/reject/violate | did not exist pre-NA-1; AI never saw them | Send protected state + price relation |
| 6 | Two-sided playbook visibility | AI saw only active (structure) direction | Send both sides |
| 7 | Two-sided toolbox every scan | monocular; bearish half never built | Send both sides (visibility); two-sided *generation* later |
| 8 | Position awareness | AI blind to open position | Send full position block |
| 9 | Memory (trade/setup/narrative/liquidity/prior-stance/lessons) | only 2-number confidence trend; AI amnesiac | Self-memory now; richer memory later |
| 10 | Vector/similarity retrieval | categorical overlap only, observe-only, consumed by nobody | Real retrieval later phase |
| 11 | New input builder (evidence not answer-key) | old builder fed conclusions, withheld evidence | **Replace** |
| 12 | New prompt role (story, not "agree?") | first 2 schema fields were agreement booleans | **Replace** |
| 13 | Machine-consumable output schema (23 fields) | 11 fields, 7 print-only, 2 consumed | **Replace** |
| 14 | AI authority (narrative/conflict/seeding/thesis/memory) | advisory 2-field + 1 fusion veto | Wire progressively |
| 15 | Generation chain: AI synthesizer, structure witness | structure-rooted generation | Rewire later (highest risk) |
| 16 | Persistence (input/raw/parsed/consumed/ignored/outcome/lesson) | reasoning discarded to print+archive | **Build** |
| 17 | Journaling (AI narrative/phase/draw/protected/lesson at entry) | NA-1 added some; AI brain fields absent | Extend journal |
| 18 | Console story display | "AI: bullish 65" only | New display |
| 19 | Model selection AFTER architecture | n/a | Honored: architecture first |
| 20 | Acceptance tests T1-T16 | none | **Build** |

## PHASE PLAN

- **AB-1 (THIS COMMIT) — Sensory + Schema + Memory + Persistence, OBSERVE-ONLY.**
  New `src/ai_brain/` package replacing the wrapper's input/prompt/schema/output.
  Fixes gaps 1-3,5,6,8,9(self),11,12,13,16,20. Deterministic synthesis core =
  NA-1 engine (real synthesis, not structure-in-costume); optional LLM path
  (`AI_BRAIN_LLM`). Wires NO consumer — proves the brain SEES and PARSES first.
- **AB-2 — Data-plane organs:** prior-day H/L/C, opening gap, overnight imbalance
  into the feed; liquidity objects + persistent draw (gaps 1,4). Unblocks the
  June-10→11 imbalance the system was blind to.
- **AB-3 — Real retrieval:** embedding/vector store over snapshots+trades+
  blocked/missed trades+narratives, replacing categorical overlap (gaps 10,9-rich).
- **AB-4 — Authority wiring (gated, observe→enforce):** brain feeds gate
  (narrative permit), thesis monitor (health), journal (entry fields), console
  (story display) (gaps 14,17,18). Evidence-graded like FC-1/NA-1.
- **AB-5 — Two-sided generation + AI playbook/toolbox seeding (gaps 7,15).**
  Highest risk; depends on AB-1..4 validated. This is where the structure-rooted
  generation lane is finally replaced — only after the brain is proven.

Rationale for the order: AB-1 first because AI-0 proved input starvation +
output discard are the ROOT; req 19 mandates architecture before models; and
the house rule is evidence-before-authority. Generation rewrite (the thing that
actually changes which trades exist) goes last, after the brain has logged a
body of observe-mode evidence.

## AB-1 acceptance (T1-T16) — status

T1 price+candles ✅ · T2 protected swings ✅ · T3 draw ✅ · T4 two-sided inventory ✅ ·
T5 position ✅ · T6 prior stance ✅ · T7 memory slot ✅ (real retrieval AB-3) ·
T8 schema parsed ✅ · T9 no print-only ✅ · T10/T11 authority DEFERRED, proven no
silent leak ✅ · T12 cannot bypass controls ✅ (static import guard) ·
T13 June 11 window: sees raid/protected-high/bearish delivery, never bullish ✅ ·
T14 knows long is open ✅ · T15 reasoning persists ✅ · T16 regression 911 passed ✅.

Rollback: `AI_BRAIN_ENABLED=false` (default) = zero behavior change. Old wrapper
remains live and untouched until AB-4 cutover, so nothing is destabilized.
