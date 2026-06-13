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

---

## AB-2A — Structure-Authorship Firewall (SHIPPED, default ON)

Goal: make it structurally impossible for `structure_engine._bias` /
`ai_context.directional_bias` to author trade direction. Firewall only — no AI
Brain / narrative / delivery-as-outright-author / two-sided generation (AB-4/5).

**Module:** `src/generation_firewall/authorship.py` — single source of truth for
"what may author direction." Non-structure authoring sources only:
`delivery_protected` (PO3 distribution→manipulation direction), `liquidity_draw`
(sweep+reclaim semantics). Verdict: source present + structure agrees/silent →
that direction; source present + structure DISAGREES → `conflicted`; no source +
structure has a bias → `conflicted` (`structure_witness_only`, never bull/bear);
nothing → `neutral` (`fallback_none`).

**Wired at both authoring points:**
- `qualification._direction_with_source()` — live `qualify_trade` path now
  firewalled; emits `direction` + `direction_source`; structure conflict/vacuum
  surfaced as a witness WARNING.
- `playbook_classifier._direction()` — closed the step-3 structure re-entry
  (`ai_context.directional_bias`); under firewall it may only originate from the
  shared authoring rule. `direction_source` inherited into playbook output.
- Toolbox inherits `playbook.direction` (never authors). Intent inherits
  decision-authority direction (inherits qualification/playbook). Proven by test.

**June 11 (firewall ON):** 10:13 bullish structure + above_high sweep →
`conflicted` (not bullish); 13:17 bearish structure + below_low sweep →
`conflicted` (not bearish); a bearish read does NOT depend on structure being
bearish (delivery authors bearish with neutral structure) — so bullish structure
never *blocks* a bearish opportunity, it merely fails to author.

**Tests:** `tests/test_phase_ab2a_structure_firewall.py` (16) — requirements
1-7. **Regression: 927 passed, 0 failed.** Rollback:
`STRUCTURE_AUTHORSHIP_FIREWALL=false` restores the legacy structure-rooted path.

### Remaining structure consumers — witness-only vs dangerous (final audit)

| Consumer | Uses structure for | Verdict |
|---|---|---|
| `qualification._direction_with_source` | direction (firewalled) | **WAS dangerous → now witness-only** |
| `playbook_classifier._direction` step 3 | direction (firewalled) | **WAS dangerous → now witness-only** |
| `toolbox_engine` | inherits playbook direction | safe (never authored) |
| `trade_intent`/`decision_engine` | inherits qual/playbook direction | safe (never authored) |
| `narrative_engine._structure_lens` (NA-1) | witness lens, cannot override AI+Delivery | witness-only |
| `ai_brain/brain_input` | tagged `structure_WITNESS` | witness-only |
| `regime_features` | environmental feature, not direction | witness-only |
| `confidence_engine` | structure *alignment* (not bias) → score | witness-only |
| `ai_snapshot_formatter` | console display | witness-only |
| `playbook` scorers (lines 65, 296) | which playbook *fits* (scoring), not direction | witness-only |
| `shared_context._delivery` bias-fallback | `{bias}_bias_only` when PO3 absent | **witness-tainted, NOT read by the generation firewall** (firewall reads po3+liquidity directly). FLAG for AB-4: if narrative gains generation authority, its delivery lens must not inherit this fallback. |
| `ai_debate_engine` / `discretionary_ai` per-TF bias counts | feed debate verdict → gate `ai_verdict_supports_trade` | **PERMISSION-side advisory** — structure still has a voice in the gate's debate check (not generation). Out of AB-2A scope; flagged for AB-4 authority review. |

No remaining structure consumer can author generation direction. Two structure
voices remain in the PERMISSION lane (debate verdict) and one tainted-but-unused
delivery fallback — both flagged for AB-4, neither a generation-authorship leak.

---

## AB-2B — Structure Contamination Cleanup (SHIPPED, default ON)

Closed the two AB-2A-flagged side-door paths. All gated by the same
`STRUCTURE_AUTHORSHIP_FIREWALL` flag (default ON).

**1. AI debate verdict (`ai_debate_engine`).** Removed structure's directional
score from both cases: the `_struct_counts` block (+10 / +5) and the
`directional_bias` block (+5) no longer add points under the firewall —
structure now appears as `[witness]` commentary only. Since the verdict feeds
the gate's `ai_verdict_supports_trade` check, structure can no longer buy gate
support. New debate metadata: `structure_used_as_witness=true`,
`structure_contributed_to_direction_score=false`,
`structure_contributed_to_gate_support=false`, `debate_direction_source`
(∈ {ai_brain, delivery, liquidity, protected_swings, narrative_authority,
fallback_none}; taint guard forces fallback_none if a directional verdict
cannot trace to a non-structure source).

**2. Deterministic AI direction (`discretionary_ai._ai_direction`).** Dropped
the `directional_bias` (+3) and MTF-structure (+2) votes under the firewall.
The fallback AI's direction — which feeds the debate, fusion, and the NA-1 lens
— now derives only from PO3 / playbook / qualification / tool (all firewalled
or non-structure). Confidence *magnitude* from structural alignment is retained
(magnitude, not direction) and noted permission-side.

**3. Delivery fallback (`shared_context._delivery`).** Removed the
`{bias}_bias_only` synthesis. PO3 absent + structure bias present →
`insufficient_delivery_evidence` (conf 0); nothing at all → `unknown`. Never
bullish/bearish from structure. This also closes the NA-1 delivery-lens leak:
its string fallback (`startswith bullish/bearish`) can no longer match a
structure-tainted delivery state.

**June 11 (firewall ON):** 10:13 bullish structure adds 0 to the bullish debate
case; 10:29 structure-tainted bullish cannot produce prepare_long/bullish_bias;
10:20–10:40 bearish delivery (PO3) scores without any structure confirmation;
13:17 bearish structure adds 0 to the bearish case; PO3 absent never becomes
directional delivery.

**Tests:** `tests/test_phase_ab2b_contamination_cleanup.py` (16) + updated
`test_phase_5g_shared_context`. **Regression: 943 passed, 0 failed.** Rollback:
`STRUCTURE_AUTHORSHIP_FIREWALL=false` restores legacy structure scoring.

### Final structure-consumer classification (post AB-2B)

| Consumer | Classification |
|---|---|
| qualification `_direction` | **removed** from authorship (AB-2A) |
| playbook `_direction` step 3 | **removed** from authorship (AB-2A) |
| ai_debate `_struct_counts` directional score | **removed** under firewall (AB-2B) |
| ai_debate `directional_bias` score | **removed** under firewall (AB-2B) |
| discretionary_ai `_ai_direction` structure votes | **removed** under firewall (AB-2B) |
| shared_context `{bias}_bias_only` delivery | **removed** (AB-2B) |
| toolbox / trade_intent direction | witness-only safe (inherits firewalled direction) |
| NA-1 `_structure_lens` | witness-only safe (cannot override AI+Delivery) |
| ai_brain `structure_WITNESS` | witness-only safe (tagged) |
| ai_debate neutral `_struct_counts` conflict detect | permission-side safe (adds to NEUTRAL/stand-down only, never bull/bear) |
| discretionary_ai `_ai_confidence` structural alignment | permission-side safe (magnitude, not direction) |
| regime_features bias | permission-side safe (environmental feature) |
| confidence_engine alignment | permission-side safe (magnitude) |
| ai_snapshot_formatter / journal / display | witness-only safe (presentation) |

**No "still dangerous" structure consumer remains.** Every directional-authorship
and gate-support path is removed under the firewall; residual structure use is
witness-only or permission-side magnitude/neutral, none of it directional.
