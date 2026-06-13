# Phase AB-4 — AI Brain Authority Wiring (OBSERVE MODE) — SHIPPED

The brain is connected: it consumes retrieval, emits the expanded package, runs
in parallel with the legacy wrapper, logs divergence, and persists stance across
restart — while remaining strictly observe-only. No generation/gate/execution
influence.

## What changed
- **Retrieval → brain** (`narrative_brain`): AB-3 analogs populate
  `memory_matches[]` and are split into `supporting_analogs` / `conflicting_analogs`;
  the brain's reasoning text incorporates an analog tally (support/conflict, W/L).
- **Expanded output** (`brain_schema`, 31 fields): added `protected_high_status`,
  `protected_low_status`, `dominant_reasoning`, `supporting_analogs`,
  `conflicting_analogs`, `recommended_playbook_family`, `recommended_tool_family`,
  `direction_provenance`. All persisted; nothing print-only.
- **Parallel + divergence** (`ai_brain/divergence.py`): every scan compares
  wrapper (ai_direction/confidence + debate) vs brain (narrative_direction/
  confidence), classifies disagreement (direction / confidence / narrative /
  playbook / liquidity), persists divergences to `data/ai_brain/divergence/`.
- **Stance persistence** (`stance_memory`): RAM ring buffer now persists to
  `data/ai_brain/stance_memory.json`; survives restart/replay/process restart.
- **Provenance** (`direction_provenance`): every brain conclusion carries
  `{source, structure_derived, retrieval_used}`; structure-derived conclusions
  are flagged (NA synthesis is delivery/liquidity/protected-led → structure_derived=false).

## Observe-only (proven)
`snapshot["ai_brain"]`, `snapshot["ai_divergence"]`, `snapshot["ai_retrieval"]`
are written + archived and consumed by NO generation/qualification/playbook/
toolbox/gate/execution path. Static import guard (T7-T9): `ai_brain/` imports
none of execution_gate/order_builder/paper_broker/risk_governor/qualify_trade/
classify_playbook/run_toolbox.

## June 10/11 replay divergence
659 scans compared (wrapper ai_direction vs reconstructed brain narrative).
**Divergence: 398 / 659 = 60%.** Top transitions (wrapper→brain): conflicted→neutral
(94), bearish→bullish (87), bearish→conflicted (69), neutral→bullish (44).
On the one resolved trade — the June 11 long — the wrapper said bullish@65 (trade
taken, −1.34R); the brain returned non-bullish (conflicted/bearish via delivery).
**The brain's divergent read aligned with the loss.** Aggregate forward-return
scoring of all 398 divergences is future work (AB-5+), not claimed here.

## Acceptance / regression
T1 retrieval→memory_matches ✓ · T2 reasoning includes retrieval ✓ · T3 schema
populated ✓ · T4 divergence logged+classified ✓ · T5 stance survives restart ✓ ·
T6 observe-only ✓ · T7-T9 no generation/gate/execution influence ✓ · T10/T11
June 10/11 replay ✓ · **T12 regression 983 passed, 0 failed.**
Rollback: `AI_BRAIN_ENABLED=false` (brain inert) — divergence auto-disables.

## Final report (7 questions)
1. **Brain consumes:** full two-sided market context (AB-1) + AB-3 retrieval analogs.
2. **Consumes the brain:** nobody with authority — reporting/logging/divergence only.
3. **Authority brain has:** none (observe). Reporting, logging, divergence, replay.
4. **Authority brain lacks:** generation, qualification, playbook, toolbox, gate,
   execution, broker exposure, order placement.
5. **Disagreement rate:** 60% of 659 June 10/11 scans.
6. **More aligned with reality:** on the only resolved trade, the brain (refused
   the losing long); broad outcome-correlation pending.
7. **Ready for authority promotion?** Architecturally yes (sensed, memoried,
   retrieval-backed, provenance-clean, observe-proven). Evidentially: promote
   only after AB-5 outcome-correlation confirms the 60% divergence favors the
   brain on forward returns, not just the single June 11 trade. MAP-2 next.
