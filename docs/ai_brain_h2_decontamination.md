# AI-BRAIN-H2 — Production LLM Input Decontamination (SHIPPED, observe-only)

Removed structure-direction from the production LLM Brain input and confirmed
the AB-5A-R clean result reproduces on TRUE production input. No authority,
generation, gate, or execution wired.

## Phase 1 — production input audit (what reached the LLM)
| Field (build_brain_input) | Structure? | Directional? | Classification |
|---|---|---|---|
| `structure_WITNESS.bias` | yes | **yes (bullish/bearish)** | **CONTAMINATED** |
| `structure_WITNESS.state` | yes | yes (`bullish_continuation`) | **CONTAMINATED** |
| `structure_WITNESS.bos/mss` | yes | no (events) | WITNESS |
| `governance_context.narrative_authority_direction` | no | yes (suggested side) | isolate |
| `governance_context.narrative_forbidden` | no | yes | isolate |
| `governance_context.council_dominant` | partly | yes | isolate |
| `delivery.*` (PO3 phase + sweep-sourced direction) | no | clean evidence | SAFE |
| `liquidity.*`, `protected_swings`, `market`, `position`, `stance_history`, `conflicts/warnings` | no | — | SAFE |

The real contaminant was **`structure_WITNESS.bias`** — the AB-5A-S 13:17 leak
where structure-bearish overrode clean delivery-bullish. (`ai_context.directional_bias`
named in the directive was never actually placed in the payload by build_brain_input;
removed from any path regardless.)

## Phase 2 — removed / isolated
- **Removed from payload:** `structure_WITNESS.bias`, `structure_WITNESS.state`
  (directional); `governance.narrative_authority_direction`, `narrative_forbidden`,
  `council_dominant` (directional "suggested side").
- **Isolated as witness:** structure now appears ONLY in `STRUCTURE_WITNESS`,
  carrying non-directional facts (swing levels + `bos_event`/`mss_event` booleans)
  plus a hard disclaimer: *"STRUCTURE WITNESS ONLY — NOT DIRECTIONAL AUTHORITY."*
- **Kept (clean evidence):** delivery (PO3 phase + provenance-sourced direction),
  liquidity (events/pools/draw), protected swings — these are the legitimate
  basis for direction and were never structure.

## Phase 3 — prompt safety contract
BRAIN_SYSTEM_PROMPT now states: structure is witness only; cannot define
direction; cannot override delivery/liquidity/protected swings; on conflict,
trust the clean evidence and mention it. Direction must come from delivery,
liquidity, protected swings, active draw.

## Phase 4 — taint guard
`scan_payload_taint()` serializes the payload MINUS `STRUCTURE_WITNESS` and
rejects forbidden terms (`directional_bias`, `*_bias`, `bias_only`,
`structure_summary`, unlabeled `"bias"` key). `run_narrative_brain` runs it
BEFORE any LLM call: contaminated → `source="contaminated_input"`, no LLM call,
logged, deterministic fallback. No silent pass-through.

## Phase 5/6 — production blind reconstruction (real build_brain_input)
Harness feeds snapshots WITH real mechanical structure bias (from bars) and uses
the production input builder — NO manual stripping. Decontamination happens in
build_brain_input.

Primary 09:38–11:00: never bullish, first bearish + first short candidate at
**10:06**, 10:29 long forbidden, **0 contaminated calls**.

**3-run stability (10:00–10:42, production input):**
| Run | first_bearish | first_short | bullish_narrs | long_cands | 10:29 forbids long | short in 10:20–40 | contaminated |
|---|---|---|---|---|---|---|---|
| 1 | 10:00 | 10:00 | 0 | 0 | True | True | 0 |
| 2 | 10:00 | 10:00 | 0 | 0 | True | True | 0 |
| 3 | 10:00 | 10:00 | 0 | 0 | True | True | 0 |

**More stable than AB-5A-R** (whose window Run 1 flickered bullish) — removing
structure direction entirely, rather than only neutralizing `ai_context`,
eliminated the flicker. All pass criteria met.

## Phase 7 — tests / regression
`tests/test_phase_ai_brain_h2_decontamination.py` (9): no directional bias in
payload, no bull/bear structure terms, structure isolated+non-directional in
STRUCTURE_WITNESS, taint guard rejects/passes, prompt contract present, 13:17
clean bullish delivery, contaminated-input skips LLM + logs. **Regression: 1015
passed, 0 failed.**

## Final questions
1. **Exact contaminating fields:** `structure_WITNESS.bias`,
   `structure_WITNESS.state`, and directional governance fields
   (narrative_authority_direction, narrative_forbidden, council_dominant).
2. **Removed or isolated?** Directional fields removed; structure isolated to a
   non-directional, disclaimer-labeled STRUCTURE_WITNESS.
3. **Matches AB-5A-R philosophy?** Yes — and more strictly (AB-5A-R neutralized
   ai_context but still passed structure_WITNESS.bias; H2 removes structure
   direction entirely).
4. **Reproduces the clean result?** Yes — and improves it (0 bullish flicker
   across 3 runs vs AB-5A-R's Run-1 flicker).
5. **10:29 long forbidden in all 3 production runs?** Yes.
6. **10:20–10:40 short window in all 3?** Yes.
7. **Remaining structure-derived contamination paths?** None — taint guard
   reports 0 across all runs; structure direction is fully removed. Delivery/PO3
   direction and protected swings remain (intended clean evidence, not structure).
8. **Is the LLM Brain input now production-clean?** **Yes.**

## Status
Production LLM input is decontaminated and confirmed clean in live-sequence
replay. The AB-5A-S leakage is closed. Per directive: STOP — no authority, no
veto, no AB-5B. The Brain now reasons from clean evidence on the real production
path; the one concrete blocker identified at AB-5A-R is resolved.
