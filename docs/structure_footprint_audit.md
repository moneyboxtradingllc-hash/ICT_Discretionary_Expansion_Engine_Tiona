# Structure Footprint Audit (read-only) — every structure wire at `cddd5f2`

Post AB-2A (generation firewall) + AB-2B (contamination cleanup). Classifications
reflect CURRENT behavior with `STRUCTURE_AUTHORSHIP_FIREWALL` default ON. "Neutralized
under firewall" = the dangerous score/authorship is gated off by default; the legacy
path only returns if the flag is set false. No changes made — audit only.

Legend: SW=safe witness · SWARN=safe warning · DA=dangerous authorship ·
DP=dangerous permission · DD=dangerous disguised path.

## The producer (root of the disguised path)

| File / func / line | Field | Affects | Class | Recommended action |
|---|---|---|---|---|
| `ai_layer/narrative_builder._directional_bias` (9, 325, 335) | structure per-TF `bias` → manufactures `ai_context.directional_bias` | feeds everything labeled "narrative bias" | **DD** | keep as witness label; never re-grant authority. Long-term: rename to `structure_bias_witness` so it can't masquerade as narrative |
| `narrative_builder._market_state` / narrative label (44,49,53,225) | `mss`,`bos`,`htf bias` → `market_narrative`, `market_state`, coherence | qualification `_narrative_pts` (score), AI input | **DD (contained)** | demote: narrative label must not encode structure direction once AI Brain owns narrative (AB-4) |
| `market_data/snapshot_builder` (94) | copies `narrative.directional_bias` into `ai_context` | propagation only | SW | keep (carrier) |

## DANGEROUS AUTHORSHIP — all neutralized under firewall

| File / func / line | Field | Affects | Class | State / action |
|---|---|---|---|---|
| `qualification._direction` (229, 237) | `directional_bias`, PO3 | qualification direction | **DA** | **neutralized**: live path uses `_direction_with_source` → firewall. Legacy fn only on rollback. Keep gated |
| `playbooks.playbook_classifier._direction` (215, 231) | `directional_bias` (step 3) | playbook direction | **DA** | **neutralized** under firewall (AB-2A). Keep gated |
| `discretionary_ai._ai_direction` (140, 143-144) | `directional_bias` +3, MTF bias +2 | deterministic AI direction → debate/fusion/NA-1 | **DA** | **neutralized** under firewall (AB-2B). Keep gated |

## DANGEROUS PERMISSION — structure can lift score/support

| File / func / line | Field | Affects | Class | Recommended action |
|---|---|---|---|---|
| `ai_debate_engine._struct_counts` bullish/bearish (51-52, 109-117, 268-276) | per-TF bias count → +10/+5 | debate verdict → gate `ai_verdict_supports_trade` | **DP** | **neutralized** under firewall (AB-2B → witness commentary). Keep gated |
| `ai_debate_engine` ctx_bias (151, 318) | `directional_bias` → +5 | debate verdict → gate | **DP** | **neutralized** under firewall (AB-2B). Keep gated |
| `qualification._structure_pts` (119-120, 185) | `alignment` → opportunity_score | qualification STATUS (candidate/qualified) → setup existence | **DP** | demote: structure alignment should not lift qualification toward "qualified"; replace with delivery/liquidity weight (AB-5) |
| `playbook_classifier` scorers — mss/bos (128-129, 291, 326) and `_context`/struct (59,122,146,169,274,365) | `mss`,`bos`,alignment → playbook score | which playbook is SELECTED (setup existence) | **DP** | demote to witness or replace with delivery-led playbook scoring (AB-5). mss/bos are events (non-directional) but still gate setup existence |
| `risk/risk_governor` (93 +) | structure (penalty/restriction inputs) | risk tier / multiplier (permission/exposure) | **DP** | keep as a *restrictive* witness only (may tighten, must never loosen); verify it can't lift risk toward allow |
| `toolbox/toolbox_engine._context_score` + scorers (44-60, 92,139,158,175,189,222,241,302) | alignment, per-TF state | tool score / readiness (not direction) | **DP (mild)** | demote: tool readiness may use structure as confluence witness, not as a score that promotes a tool to actionable |
| `toolbox/tool_readiness` (78,191,234,281,317,395,440,502) | structure state/swings | trigger readiness gating | **DP (mild)** | audit each: keep only where structure is a *level* reference, demote score lifts |
| `regime_classification/regime_features` + `regime_classifier` (21,31-36,58,72) | bias, bos, mss, directional_bias | regime label → permission matrix (cap/trigger/age) | **DP** | keep as environmental feature (regime is a constraint, not directional authority); flag for AB-4 review that regime label is not structure-direction in disguise |

## DANGEROUS DISGUISED PATH — structure under another name

| File / func / line | Field | Affects | Class | State / action |
|---|---|---|---|---|
| `shared_context._delivery` bias fallback (96-103) | `directional_bias` → delivery state | delivery → NA-1 lens, council | **DD** | **removed** (AB-2B): now `insufficient_delivery_evidence`/`unknown`, never `{bias}_bias_only`. Keep removed |
| `narrative_authority.narrative_engine._structure_lens` (125) | `directional_bias` as witness lens | NA-1 narrative direction (cannot override AI+Delivery) | SW | keep (NA-1 already treats as witness/flag-raiser) |
| `ai_debate_engine.debate_direction_source` taint guard (AB-2B) | rejects structure-labeled source | debate metadata | SWARN | keep (this is the guard) |

## SAFE WITNESS — log / display / journal / context only

| File / func / line | Field | Affects | Class |
|---|---|---|---|
| `ai_brain/brain_input` (124, 141-144) | structure tagged `structure_WITNESS` (bias/state/bos/mss) | AI Brain input (observe) | SW |
| `ai_layer/ai_input_builder._structure_summary` (17-22, 191) | bias/state/bos/mss/swings | external AI input (advisory) | SW |
| `ai_layer/ai_snapshot_formatter` (8-14, 638, 684) | bias/bos/mss | console display | SW |
| `narrative_authority/protected_swings` (71, 82-93) | `last_swing_high/low` | protected-level registration (mechanical level, not direction) | SW |
| `toolbox/price_levels` (176-177, 356) | `last_swing_high/low` | zone/level construction (price geometry, not direction) | SW |
| `ai_debate_engine` swing refs (225, 392) | `last_swing_*` | invalidation-level text in evidence | SW |
| `discretionary_ai` swing refs (414,421,481,486) | `last_swing_*` | invalidation thesis text (fallback narrative) | SW |
| `state/market_memory` (164-165) | structure `state` change flag | memory delta tracking | SW |
| `structure/po3_engine` (44-45, 47, 94-96, 132-197, 181-183) | bias/bos/mss | PO3 phase computation (consumes structure as one input among sweep/displacement) | SW* |
| `structure/structure_engine` (89-90) | alignment computation | internal | SW |
| `ai_connectivity_test` (27) | literal "neutral" | test stub | SW (dead in scan path) |

\* po3_engine consumes structure bos/mss to classify PO3 phase. PO3's directional
output (`manipulation_direction` / `distribution_direction`) was found to inherit
structure `bias` via a fallback (`_directions` line 120) — a LIVE disguised path
into AB-2A's firewall. **CLOSED by AB-2C** (2026-06-13): the fallback is removed,
PO3 directions are sweep/liquidity-sourced only, carry provenance, and the firewall
rejects any PO3 direction without a valid non-structure source. PO3 phase scoring
still uses structure bos/mss/state (non-directional, witness/score magnitude only).
See `docs/po3_independence_audit.md`.

## SAFE WARNING — conflict/lag only

| File / func / line | Field | Affects | Class |
|---|---|---|---|
| `qualification` structure-conflict warning (515 +, AB-2A) | `directional_bias` witness | qualification `warnings[]` | SWARN |
| `ai_debate_engine._score_neutral` conflict detect (435-438) | per-TF bias count | NEUTRAL/stand-down score only (never bull/bear) | SWARN |
| `qualification._qual_warnings` / `_reasons` (321, 340-344, 406) | bos/mss/alignment | warning + reason text | SWARN |
| `narrative_builder` warnings | structure vs expansion mismatch | `ai_context.warnings[]` | SWARN |
| `confidence_engine` alignment (42) | structure `alignment` → confidence magnitude | confidence score (magnitude, not direction) | SWARN |

## Summary

- **DANGEROUS AUTHORSHIP (3):** all neutralized under firewall (AB-2A/2B); legacy paths gated, default off.
- **DANGEROUS PERMISSION (≈8 sites):** debate score + ctx_bias neutralized (AB-2B). **Still live (score-lift, non-directional):** qualification `_structure_pts` (alignment→status), playbook mss/bos scoring (→ which playbook), toolbox/tool_readiness structure scoring, risk penalties, regime features. These lift *setup existence / readiness*, not direction. They are the AB-5 generation-rewrite surface.
- **DANGEROUS DISGUISED PATH:** delivery `{bias}_bias_only` removed (AB-2B); `directional_bias` producer still manufactures structure-as-narrative (contained — every authorship/permission consumer firewalled). PO3-from-structure flagged for AB-4 confirmation.
- **SAFE WITNESS / WARNING:** the majority — display, journal, AI input (tagged witness), level/zone geometry, conflict/lag warnings, confidence magnitude.

**Net:** no remaining DANGEROUS AUTHORSHIP and no remaining directional DANGEROUS PERMISSION is *live by default*. The live residue is non-directional permission score-lift (qualification status, playbook selection, tool readiness, risk, regime) — the surface AB-5 must convert from structure-scored to delivery/liquidity/AI-Brain-scored — plus one contained disguised producer (`directional_bias`) and one indirect structure→PO3→delivery path to confirm in AB-4.
