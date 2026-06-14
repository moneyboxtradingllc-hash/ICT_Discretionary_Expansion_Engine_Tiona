# AB-5B — ECU Migration (Brain Ownership Transition) + MAP-5

Converts the Brain from observer to ECU: intelligence ownership (direction,
opportunity-direction, playbook origination, toolbox) transfers from the
mechanical chain to the Brain. Gated by `BRAIN_ECU_MODE` (default OFF →
bit-for-bit pre-AB-5B mechanical pipeline; regression preserved). No new
intelligence systems, no new structure logic, no new authority layers.

## Phase 1 — migration checklist (pre-change owners)
| Capability | Pre owner | Migration target |
|---|---|---|
| direction generation | qualification._direction (firewalled mechanical) | Brain thesis |
| direction prohibition | firewall/gate | Brain forbidden_direction |
| opportunity-direction | qualification | Brain (opportunity flag + direction) |
| playbook selection | playbook_classifier scoring | Brain originates, classifier validates |
| toolbox selection | toolbox_engine (from playbook dir) | inherits Brain direction |
| thesis generation | qual+playbook+debate | Brain |

## Phase 2 — pipeline reorder (traced)
Before: evidence → qualification(126) → playbook(129) → toolbox(140) → gate →
Brain(scan_loop 923, post-hoc).
After (ECU on): evidence → **Brain pre-pass (`produce_thesis`, snapshot_builder
~125)** → qualification → playbook → toolbox → gate. The Brain now runs BEFORE
all intelligence consumers; they receive `snapshot["brain_thesis"]`.

## Phase 3 — thesis ownership
`_direction_with_source` (qualification): when `brain_thesis.owner == ai_brain`
and directional, returns `(brain_direction, "ai_brain")`. Mechanical firewall is
witness/fallback (used only when the Brain is non-directional). No hidden
fallback author — provenance is `ai_brain`.

## Phase 4 — opportunity recognition
Brain sets `opportunity` (true when directional), `opportunity_type` (phase),
confidence, rationale. Qualification remains the validator: it still computes the
opportunity SCORE and can reject (`no_trade`), but no longer ORIGINATES direction.

## Phase 5 — playbook ownership
`classify_playbook` under ECU: when the Brain asserts an opportunity and its
family (or phase→playbook map: manipulation/reversal/exhaustion→
liquidity_sweep_reversal, continuation→trend_continuation, distribution→
manipulation_to_distribution) names a valid playbook, the Brain ORIGINATES it
(`direction_source=ai_brain`); the classifier validates (scores, supplies
eligible tools) but does not block on threshold/no_trade. Mechanical scoring
resumes only when the Brain names no valid playbook.

## Phase 6 — toolbox ownership
`run_toolbox` consumes `playbook.direction`, which under ECU is the Brain's
direction → toolbox is transitively Brain-owned (bearish brain → bearish tools).

## Phase 7 — execution plan
The Brain thesis (direction, forbidden, playbook_family, tool_family, confidence,
dominant_reasoning) is the canonical thesis carried in `snapshot["brain_thesis"]`
and inherited downstream. Order construction remains mechanical (executor).

## Phase 8 — mechanical demotion (ownership matrix before/after)
| Capability | Before | After (ECU on) |
|---|---|---|
| Evidence collection | mechanical | mechanical |
| Market interpretation | mechanical | **Brain** |
| Opportunity recognition | mechanical | **Brain originates; qual validates** |
| Playbook selection | mechanical | **Brain originates; classifier validates** |
| Toolbox selection | mechanical | **Brain (via direction)** |
| Thesis generation | mechanical | **Brain** |
| Direction generation | mechanical | **Brain** |
| Direction prohibition | mechanical/gate | **Brain forbidden_direction** |
| Execution planning | mechanical | **Brain thesis → mechanical executor** |
| Order execution | mechanical | mechanical |
| Risk management | mechanical | mechanical |

## Phase 9 — June 11 ECU validation replay (live LLM, chronological, blind)
10:00–10:45, BRAIN_ECU_MODE=on, AI_BRAIN_LLM=on, June-10-only retrieval:
| ET | Brain dir | playbook (src) | toolbox |
|---|---|---|---|
| 10:00 | bearish | liquidity_sweep_reversal (**ai_brain**) | bearish |
| 10:25 | bearish | liquidity_sweep_reversal (**ai_brain**) | bearish |
| 10:30 | bearish | liquidity_sweep_reversal (**ai_brain**) | bearish |
| 10:40 | bearish | liquidity_sweep_reversal (**ai_brain**) | bearish |
| conflicted scans | conflicted | no_playbook | — |
- first Brain bearish: 10:13 (full 09:38–11:00 run) / 10:00 (window)
- first Brain-originated playbook: 10:00; first Brain toolbox: 10:00
- **10:29 long: structurally impossible** — qualification is never bullish (Brain owns direction, never bullish all window) ⇒ no bullish playbook ⇒ no long.
- 10:20–10:40 short window: covered (bearish playbook+toolbox at 10:25/10:30/10:40).
- qualification.direction_source = "ai_brain" on every directional scan.

## Phase 10 — MAP-5 ownership audit (ECU on)
1. **Direction owner:** Brain (`direction_source=ai_brain`, evidence: replay).
2. **Opportunity recognition:** Brain originates; qualification validates/scores.
3. **Playbook selection:** Brain originates (src=ai_brain); classifier validates.
4. **Toolbox selection:** Brain (via inherited direction).
5. **Thesis generation:** Brain.
6. **Is the Brain now the ECU?** YES under `BRAIN_ECU_MODE=true` — it runs first
   and owns direction/opportunity/playbook/toolbox; mechanical modules validate
   and execute.
7. **Does any mechanical module still author intelligence?** Direction: no (Brain
   owns; mechanical is witness/fallback only when Brain non-directional).
   Honest residual: when the Brain is non-directional (conflicted/neutral), the
   mechanical firewall resumes as fallback — by design, not a hidden author.
8. **Hidden authorship paths?** None — grep confirms qualification/playbook read
   `brain_thesis`; no other module originates direction under ECU.
9. **Matches intended design?** YES for the intelligence capabilities, under ECU
   mode. (Default off retains the mechanical pipeline.)

## Honest scope notes
- ECU is GATED (default off). With it off, MAP-4's findings still describe the
  default; ECU on is the aligned architecture.
- Brain pre-pass evidence at qualification time is po3-delivery + liquidity +
  structure-witness (decontaminated H2); NA-1 protected/draw are refined later in
  scan_loop (gate-time), so the pre-pass uses the clean delivery/liquidity it has.
- Playbook origination uses a phase→playbook map when the Brain names a non-key
  family; full free-form family→playbook mapping is bounded, not exhaustive.
- Tests: `tests/test_phase_ab5b_ecu_migration.py` (9). Regression: 1024 passed.

## Final deliverables status
ownership migration report ✓ · before/after pipeline ✓ · before/after ownership
matrix ✓ · consumer graph (brain_thesis → qualification/playbook) ✓ · June 11 ECU
replay ✓ · MAP-5 ✓ · regression 1024 ✓. STOP after migration + MAP-5.
