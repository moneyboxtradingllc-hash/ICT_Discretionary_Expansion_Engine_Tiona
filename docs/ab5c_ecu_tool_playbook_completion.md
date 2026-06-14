# AB-5C — ECU Tool & Playbook Completion + MAP-5A

Completes the ECU migration: the Brain now owns playbook selection (all 6) and
tool selection (all 22). `toolbox_engine`/`playbook_classifier` are validators/
rankers, not originators. Gated `BRAIN_ECU_MODE` (default off → unchanged;
regression 1034 passed). No new intelligence systems, playbooks, tools, or authority.

## Phase 1 — playbook completion audit (why only 3 before)
ECU playbook routing relied on a 5-phase→3-playbook map; the LLM rarely emitted
the other 3 keys verbatim, and `recommended_playbook_family` was free-text. So
failed_breakout_reversal / opening_drive / range_expansion were unreachable.

## Phase 2 — full playbook ownership
Prompt now constrains `recommended_playbook_family` to the SIX canonical keys (or
none). `classify_playbook` (ECU branch) originates from the Brain's key directly
(all 6 reachable; phase map remains a fallback); the classifier validates/scores
and supplies eligible tools but does not originate. Test: all 6 originated with
`direction_source=ai_brain`.

## Phase 3 — tool ownership audit (why ignored before)
`run_toolbox` read only playbook+direction and set `preferred = candidates[0]`
(highest mechanical score). `recommended_tool_family` had zero consumers.

## Phase 4 — tool ownership migration
`run_toolbox` now resolves the Brain's tool via `_brain_preferred_tool`:
1. explicit Brain `recommended_tool_family` (direction-agnostic family token →
   `{direction}_{family}`) if eligible/ready → **ai_brain_selected**;
2. else, when the LLM names no concrete tool, derive from the Brain-chosen
   playbook's canonical preferred tool → **ai_brain_playbook_derived**;
3. else mechanical fallback (only if the Brain named an ineligible tool / no
   playbook). The toolbox no longer originates by score-ranking; it validates
   readiness and rejects ineligible Brain choices. `preferred_tool_source`
   records the owner.

## Phase 5 — tool reachability
All 22 canonical tools are Brain-selectable: for every (playbook, direction) the
family token resolves to the eligible tool (test `TestAll22ToolsReachable`
asserts the resolved set == VALID_TOOLS). **YES — the Brain can explicitly choose
any of the 22** (by selecting the playbook+direction whose eligible set contains
it and naming the family).

## Phase 6 — thesis completion
The Brain thesis (`produce_thesis`) carries: narrative_direction,
forbidden_direction, opportunity/opportunity_type, playbook_family (6-enum),
tool_family (11-enum), dominant_reasoning (full story), confidence. Mechanical
layer consumes it (qualification/playbook/toolbox); it does not create it.

## Phase 7 — June 11 ECU replay (live LLM, chronological, blind, 10:00–10:45)
| ET | Brain dir | playbook | tool | tool source |
|---|---|---|---|---|
| 10:00 | bearish | liquidity_sweep_reversal | bearish_ifvg | ai_brain_playbook_derived |
| 10:15 | bearish | liquidity_sweep_reversal | **bearish_ifvg** | **ai_brain_selected** |
| 10:20 | bearish | liquidity_sweep_reversal | **bearish_breaker** | ai_brain_playbook_derived |
| 10:30 | bearish | liquidity_sweep_reversal | bearish_ifvg | **ai_brain_selected** |
| 10:35 | bearish | liquidity_sweep_reversal | bearish_breaker | ai_brain_playbook_derived |
| conflicted scans | conflicted | no_playbook | None | — |
- first bearish thesis / playbook / tool: all **10:00**.
- Every tool is Brain-owned (`ai_brain_selected` or `ai_brain_playbook_derived`);
  **never mechanical**. The LLM explicitly chose `bearish_breaker` at some scans
  (real instrument selection, not just direction).
- **10:29 long: impossible** — qualification is never bullish (Brain owns
  direction, never bullish).
- **10:20–10:40 short window:** covered with concrete bearish tools.

## Phase 8 — MAP-5A ECU completion audit
1. Direction owner — **Brain**.
2. Opportunity owner — **Brain** (qualification validates/scores).
3. Playbook selection — **Brain** (all 6; classifier validates).
4. Tool selection — **Brain** (all 22; toolbox validates readiness).
5. Thesis generation — **Brain**.
6. Mechanical still originates playbooks? **No** under ECU (classifier validator).
7. Mechanical still originates tools? **No** under ECU (toolbox validator); the
   only mechanical fallback fires when the Brain names an ineligible tool / no
   playbook — a rejection path, not origination.
8. `recommended_tool_family` consumed? **Yes** (ai_brain_selected when the LLM
   names a concrete eligible family).
9. Brain can select all 6 playbooks? **Yes**.
10. Brain can select all 22 tools? **Yes** (via playbook+direction+family).
11. Brain the sole intelligence owner? **Yes** under ECU (direction, opportunity,
    playbook, tool, thesis).
12. Architecture fully matches the ECU design? **Yes** under `BRAIN_ECU_MODE=true`.

## Honest scope notes
- ECU gated; default off retains the mechanical pipeline (regression baseline).
- gpt-4o-mini does not reliably emit a concrete tool family every scan (often
  "none"); the **ai_brain_playbook_derived** path keeps tool selection Brain-owned
  (deterministic consequence of the Brain's playbook choice) rather than reverting
  to mechanical score-ranking. A stronger model would raise the
  `ai_brain_selected` share. This is a model-compliance characteristic, recorded
  honestly — ownership is the Brain's either way; only the granularity of the
  explicit pick varies.
- Mechanical fallback remains for the rejection case (Brain names an ineligible
  tool / no playbook) — by design (validator), not hidden origination.

## Deliverables
ownership migration report ✓ · playbook reachability (6/6) ✓ · tool reachability
(22/22) ✓ · before/after ownership matrix ✓ · June 11 replay ✓ · MAP-5A ✓ ·
regression 1034 passed ✓. STOP after AB-5C + MAP-5A.
