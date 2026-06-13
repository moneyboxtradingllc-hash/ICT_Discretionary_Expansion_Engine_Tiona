# MAP-2 — AI Brain Wiring Audit (read-only, at `6ad647f`)

Required after AB-4, before AB-5. Audit only — grep-verified producer/consumer
graph. Bottom line: the brain is now CONNECTED for observation and CONSUMED only
by logging/divergence/archive — zero authority wires, zero bypass paths.

## Every Brain producer

| Key | Written at | Producer |
|---|---|---|
| `snapshot["ai_retrieval"]` | scan_loop.py:917 | `ai_retrieval.retrieve_for_snapshot` (gated AI_RETRIEVAL_ENABLED) |
| `snapshot["ai_brain"]` | scan_loop.py:923 | `ai_brain.run_narrative_brain` (gated AI_BRAIN_ENABLED) |
| `snapshot["ai_divergence"]` | scan_loop.py:928 | `ai_brain.compute_divergence` |
| `data/ai_brain/stance_memory.json` | on each `record()` | `StanceMemory._save` |
| `data/ai_brain/divergence/*.json` | on divergence | `divergence._persist` |
| `data/ai_brain/*` (per-call record) | each scan | `brain_persistence.persist_brain_call` |
| `data/ai_retrieval/*` (store + logs) | backfill / retrieval | `vector_store`, `retrieval` |

## Every Brain consumer (grep-verified)

| Reader | Reads | Purpose | Authority? |
|---|---|---|---|
| `divergence.py:36` | `ai_brain.output` | compare vs wrapper, classify, log | **none** (measurement) |
| `narrative_brain.py:190` | `ai_retrieval.analogs` | populate own memory_matches | **none** (self) |
| `snapshot_store.py:70-71` | `ai_brain`, `ai_divergence` | archive | **none** (persistence) |

**No generation / qualification / playbook / toolbox / gate / risk / execution
module reads `snapshot["ai_brain"]`, `ai_retrieval`, or `ai_divergence`.**

## "narrative_direction" consumers are NOT the brain

The grep hits for `narrative_direction` outside `ai_brain/` all belong to the
**NA-1 `narrative_authority`** block (a separate producer): scan_loop console
line, `liquidity_objectives` param, `narrative_engine` output, and
`trade_journal.narrative_direction_at_entry` (reads `narrative_authority`, not
`ai_brain`). The AI Brain's `narrative_direction` field feeds nothing but
divergence + archive. Confirmed distinct producers.

## Field consumption map (brain output, 31 fields)

| Consumed (by divergence/self, observe) | Archived only (persisted, not consumed) |
|---|---|
| narrative_direction, phase_confidence, current_action, dominant_reasoning, direction_provenance, memory_matches (count) | market_story, narrative_phase, delivery/liquidity/protected interpretations, active_draw, allowed/forbidden_direction, preferred_*, recommended_*, invalidation_level, thesis_health, contradiction_flags, warnings, confidence_by_component, supporting/conflicting_analogs, reason, must_not_do |

No brain field reaches an authority decision. "Ignored by authority" = all 31.

## Bypass paths

**None.** There is no code path by which brain output (or retrieval, or
divergence) influences generation direction, qualification, playbook/toolbox
selection, the execution gate's authorization checks, risk sizing, broker
exposure, or order submission. The execution gate's 12 checks (FC-1/NA-1 era)
do not include any brain field. Static import guard (AB-4 T7-T9) holds:
`ai_brain/` and `ai_retrieval/` import none of those modules.

## Two-AI-path standing (unchanged from MAP-1, now measured)

- OLD wrapper (`ai_discretionary`): still the only AI consumed by decisions
  (debate score, fusion, NA-1 lens, ai_feedback) — advisory, 2 fields.
- NEW brain: full-context, memoried, retrieval-backed, **observe-only**, and now
  running in measured parallel (60% divergence over June 10/11).

## AB-5 readiness

MAP-2 confirms the brain is cleanly connected with no authority leakage and a
clean cutover surface. AB-5 (the generation/authority promotion + old-wrapper
retirement) may begin — gated observe→enforce, with the divergence corpus as the
evidence base for whether the brain's reads beat the wrapper's on forward returns.

**AB-5 may begin.**
