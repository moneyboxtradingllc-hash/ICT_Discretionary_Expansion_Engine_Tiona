# Toolbox & Playbook Inventory Audit (read-only, at `7357d48`)

Complete inventory. No code changes. Source of truth: `toolbox/tool_library.py`
(VALID_TOOLS + _ELIGIBLE), `playbooks/playbook_classifier.py` (scorers),
`toolbox/toolbox_engine.py` (_SCORERS), `toolbox/tool_readiness.py` (readiness),
`ai_brain/ecu.py` + `playbook_classifier` ECU branch (Brain origination).

## Phase 1 — Playbook inventory (master table)

| # | Playbook | Source file | Originating module | Direction | Active/Legacy | Reachable? |
|---|---|---|---|---|---|---|
| 1 | liquidity_sweep_reversal | tool_library.py + playbook_classifier.py | playbook_classifier (`_score_liquidity_sweep_reversal`) | Both | Active | YES |
| 2 | trend_continuation | same | `_score_trend_continuation` | Both | Active | YES |
| 3 | manipulation_to_distribution | same | `_score_manipulation_to_distribution` | Both | Active | YES |
| 4 | failed_breakout_reversal | same | `_score_failed_breakout_reversal` | Both | Active | YES |
| 5 | opening_drive | same | `_score_opening_drive` | Both | Active | YES |
| 6 | range_expansion | same | `_score_range_expansion` | Both | Active | YES |

**Answers:** Total playbooks = **6**. Reachable = **6**. Legacy = **0**.
Orphaned = **0**. (Names like `accumulation_before_expansion`,
`bullish_continuation`, `bearish_reversal`, `distribution`, `late_continuation`
are NARRATIVE/market-state/PO3-phase labels — NOT playbooks. `fvg_continuation`,
`ote_after_breakout`, `ote_into_distribution` are non-canonical tool aliases
resolved by `normalize_tool`, not playbooks.)

## Phase 2 — Toolbox inventory (master table, 22 canonical tools)

All defined in `tool_library.VALID_TOOLS`; each has a scorer
(`toolbox_engine._SCORERS`) and a readiness fn (`tool_readiness`). 11 families ×
2 directions.

| # | Tool | Family | Dir | Scorer | Readiness | Reachable? |
|---|---|---|---|---|---|---|
| 1/2 | bullish_fvg / bearish_fvg | fvg | B/B | ✓ | ✓ | YES |
| 3/4 | bullish_ifvg / bearish_ifvg | ifvg | B/B | ✓ | ✓ | YES |
| 5/6 | bullish_order_block / bearish_order_block | order_block | B/B | ✓ | ✓ | YES |
| 7/8 | bullish_breaker / bearish_breaker | breaker | B/B | ✓ | ✓ | YES |
| 9/10 | bullish_rejection_block / bearish_rejection_block | rejection_block | B/B | ✓ | ✓ | YES |
| 11/12 | bullish_ote_retracement / bearish_ote_retracement | ote_retracement | B/B | ✓ | ✓ | YES |
| 13/14 | bullish_mss_retest / bearish_mss_retest | mss_retest | B/B | ✓ | ✓ | YES |
| 15/16 | bullish_ote_after_reclaim / bearish_ote_after_reclaim | ote_after_reclaim | B/B | ✓ | ✓ | YES |
| 17/18 | bullish_opening_fvg / bearish_opening_fvg | opening_fvg | B/B | ✓ | ✓ | YES |
| 19/20 | bullish_opening_order_block / bearish_opening_order_block | opening_order_block | B/B | ✓ | ✓ | YES |
| 21/22 | bullish_range_break_retest / bearish_range_break_retest | range_break_retest | B/B | ✓ | ✓ | YES |

**Answers:** Total tools = **22**. Reachable = **22** (every tool has a scorer +
readiness + appears in ≥1 playbook's eligible list). Legacy = **0** canonical
(aliases `fvg_continuation`/`breaker_retest`/`ote_after_breakout` are legacy
*names* resolved to canonical by `normalize_tool`, not separate tools).
Orphaned = **0**.

Eligibility note (which playbook exposes which tools): a tool is only *selectable
in a scan* if the selected playbook's eligible list contains it. Coverage:
- opening_fvg / opening_order_block → **only** `opening_drive`.
- range_break_retest → **only** `range_expansion`.
- All other tools appear across reversal/continuation/m2d/failed-breakout.

## Phase 3 — Ownership audit

**Playbooks** — Originator: mechanical `classify_playbook` (default) OR the Brain
under ECU (`brain_thesis.playbook_family` / phase→playbook map). Consumer:
`run_toolbox` (eligible tools), gate (regime matrix forbids families), trade_intent.
- Brain-selectable under ECU? **YES for 3** (liquidity_sweep_reversal,
  trend_continuation, manipulation_to_distribution — via the phase→playbook map);
  **conditionally for the other 3** (failed_breakout_reversal, opening_drive,
  range_expansion — only if the Brain literally emits that exact family string).
- Selection mechanical? Default yes. Selection Brain-owned? Yes under ECU (origination).

**Tools** — Originator: `toolbox_engine.run_toolbox` (mechanical `_score_tool`
ranking over the playbook's eligible list). Consumer: order_builder (entry zone),
gate (trigger), trade_intent.
- Brain-selectable under ECU? **NO** — `run_toolbox` does NOT read `brain_thesis`
  or `recommended_tool_family` (grep-confirmed). The Brain influences the eligible
  SET (via playbook+direction) but not which specific tool wins.
- Selection mechanical? **YES** (toolbox_engine scoring). Brain-owned? **NO.**

## Phase 4 — Reachability audit
- **Playbooks (mechanical mode):** all 6 reachable via scoring (≥45 threshold).
- **Playbooks (ECU mode, Brain origination):** 3 reachable via phase map; 3
  (failed_breakout_reversal, opening_drive, range_expansion) reachable only if the
  Brain names them verbatim — **NO in practice**, because the LLM's
  `recommended_playbook_family` observed values are phase-like / LSR /
  confirmation_required, and the phase map only routes to LSR / trend_continuation
  / m2d.
- **Tools:** all 22 reachable IN PRINCIPLE (scorer + readiness + eligibility).
  Per scan, only the eligible set of the selected playbook is reachable. opening_*
  tools require `opening_drive`; range_break_retest requires `range_expansion` —
  so under ECU those tools are effectively unreachable (their playbooks aren't
  Brain-routable). NO for opening_*/range_break_retest under ECU; YES under mechanical.

## Phase 5 — Brain capability audit (ECU mode)
What the Brain can currently EMIT (and what it maps to):
- `narrative_direction` ∈ {bullish, bearish, conflicted, neutral} → qualification
  /playbook direction (OWNED).
- `narrative_phase` ∈ {accumulation, manipulation, distribution, reversal,
  continuation, exhaustion, transition, neutral, conflicted} → playbook via map:
  manipulation/reversal/exhaustion→liquidity_sweep_reversal;
  continuation→trend_continuation; distribution→manipulation_to_distribution;
  accumulation/transition/neutral/conflicted→none.
- `recommended_playbook_family` (free text) → used if it equals a scorer key.
- `recommended_tool_family` → **emitted but NOT consumed** by run_toolbox.

**Can the Brain presently select actual tools?** **NO.** It selects DIRECTION and
(via origination) PLAYBOOK, which determine the eligible tool SET; the specific
tool is chosen by mechanical scoring. Evidence: `run_toolbox` reads `playbook` +
`risk` only; `recommended_tool_family` has zero consumers (grep).

## Phase 6 — Final questions
1. **Every playbook:** liquidity_sweep_reversal, trend_continuation,
   manipulation_to_distribution, failed_breakout_reversal, opening_drive,
   range_expansion (6).
2. **Every tool:** the 22 in the Phase-2 table.
3. **Reachable playbooks:** all 6 (mechanical); 3 reliably under ECU.
4. **Reachable tools:** all 22 in principle; per scan only the selected playbook's
   eligible set; opening_*/range_break_retest effectively unreachable under ECU.
5. **Playbooks the Brain can originate today:** liquidity_sweep_reversal,
   trend_continuation, manipulation_to_distribution (3 via phase map; others only
   if named verbatim).
6. **Tools the Brain can originate today:** **none individually** — it originates
   the playbook/direction (eligible set), not the specific tool.
7. **Does ECU own actual tool selection?** **NO.**
8. **If not, what layer owns it?** `toolbox_engine` (mechanical `_score_tool`
   ranking over the eligible set).
9. **Is "toolbox: bearish" a real tool selection or directional inheritance?**
   **Directional inheritance** — the eligible set is bearish because the Brain's
   direction is bearish; the Brain did not pick `bearish_ifvg` vs `bearish_breaker`.
10. **Exact gap between ECU ownership and full toolbox ownership:**
    (a) `run_toolbox` does not read `brain_thesis.recommended_tool_family` — tool
    RANKING within the eligible set is mechanical;
    (b) the Brain can only route to 3 of 6 playbooks (phase map), so 3 playbooks
    and their exclusive tools (opening_*, range_break_retest) are unreachable
    under ECU;
    (c) `recommended_tool_family` is produced but unconsumed.
    Closing the gap = wire `recommended_tool_family` into `run_toolbox` selection
    + broaden the phase→playbook map (or have the Brain emit canonical playbook
    keys). NOT implemented (inventory only).

## Deliverables
Complete playbook inventory ✓ · complete toolbox inventory ✓ · reachability matrix
✓ · ownership matrix ✓ · Brain capability matrix ✓. No modifications.
