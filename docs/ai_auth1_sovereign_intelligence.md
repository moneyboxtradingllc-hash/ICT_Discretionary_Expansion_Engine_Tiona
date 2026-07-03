# AI-AUTH-1 — Sovereign Intelligence (legacy wrapper purge)

Date: 2026-07-03 (pre-session, before ADAPTIVE-8 session 1 — the campaign
validates the purified chain from scan #1)

One organism. One brain. One sovereign intelligence. Everything else observes.

## Authority map BEFORE (wrapper had FIVE live vetoes + one latent wire)

| Seam | File | Wrapper authority |
|---|---|---|
| 1 | execution_gate.py | `ai_verdict_supports_trade` (debate stance) in would_authorize |
| 2 | execution_gate.py | fusion `strong_disagreement` blocked would_authorize |
| 3 | decision_engine.py | wrapper/debate authored direction (priorities 3–4); debate stand_down veto on weak quals |
| 4 | intent_builder.py | debate stand_down forced no-intent (hard veto) |
| 5 | intent_scorer.py | wrapper fed up to 10 pts of the gated execution score (threshold 70) |
| 6 (latent) | narrative_engine.py `_ai_lens` | read the wrapper; dormant only because PIPE-1 assembles NA before the wrapper runs — would spring alive on any ordering change, feeding the ENFORCE narrative veto |

## Purge (Option B — formal demotion to shadow observability)

The wrapper (`ai_discretionary` / `ai_debate` / `confidence_fusion`) still runs
every scan and is fully recorded (forensics, AB-4 divergence, ai_feedback,
Fable-5 shadow comparison, prints) — but it can no longer veto, author
direction, alter authorization, or score the execution threshold:

- **Gate:** both wrapper checks removed from `would_authorize`; recorded as
  `ai_debate_stance_observed` / `fusion_status_observed` (telemetry only).
- **Decision engine:** direction chain is now setup > playbook (Brain-owned
  under ECU) > neutral; debate stand_down rule removed; all wrapper reads
  removed. `decision.confidence` still reports `combined_confidence` — it is
  the ADAPTIVE-6 defensive consumption target and gates nothing.
- **Intent builder:** debate stance no longer vetoes intent creation.
- **Intent scorer:** `_score_ai_alignment` re-sourced to the ECU Brain thesis
  (direction agreement 7 + conviction ≥55 → 3). Wrapper contributes zero.
- **Narrative engine:** `_ai_lens` re-sourced to `snapshot["ai_brain"]` output
  — kills the latent wire; live behavior unchanged (lens empty pre-Brain under
  PIPE-1 ordering, exactly as before).

## Authority map AFTER

| Authority | Sole owner |
|---|---|
| direction / bias | ECU Brain thesis → qualification/playbook/toolbox (mechanical witnesses as fallback when Brain non-directional) |
| confidence (authoritative) | none gates on a confidence number; fused value is reporting + adaptive defensive target only |
| participation / veto | mechanical constitution: risk governor, regime matrix, narrative authority (Brain/delivery-fed), council (mechanical members), promoted rules, adaptive DEFENSIVE_ONLY, ops/supremacy/EOD |
| execution approval | execution gate (wrapper-free) → 11-layer execution engine |
| thesis lifecycle | ThesisLifecycleEngine (Brain candidate in, stabilized thesis out) |

## Phase 4 — `_thesis_executable` reconnected

The MC witness read `t.get("status")`; production exposes
`thesis_state.thesis_status` and `thesis_lifecycle.active_thesis.status`. It
could never fire live (the old unit test used a fixture matching the bug, not
production). Now reads both real keys. MC remains shadow.

## Regression lock

`tests/test_ai_auth1_sovereignty.py` (17 tests): A sovereign direction,
B wrapper-cannot-veto, C fusion-invariance, D wrapper-free execution inputs +
Brain-sourced alignment scoring, E MC observe_only + no-consumer source guard +
reconnected witness, F source-level wrapper-free locks on the authority
modules. Registered as the third deliberate scoped revision in the
constitutional guard tests.

Updated pinned tests: 5e4 test-06 (fusion veto → observability invariance),
NA-1 fixtures (AI lens now Brain-form), MC thesis fixture (production key).

Suite: 1388 tests OK. Performance substrate hash-verified untouched.
