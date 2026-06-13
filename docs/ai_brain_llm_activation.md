# AI-BRAIN-L — Real LLM Brain Activation (SHIPPED, observe-only)

The Brain now actually thinks. `AI_BRAIN_LLM=true` invokes GPT with the full
context payload; the model produces the narrative; code injects only the
retrieval/provenance fields. No authority, generation, or execution wired.

## What changed
- **`_call_llm`** rewritten to a full call record: model, prompt, user payload,
  raw response, **token usage**, fallback reason. Validates the LLM against a
  lenient CORE schema (narrative fields the model owns), not the full 31-field
  schema (which includes code-injected analog/provenance fields).
- **`run_narrative_brain`** — explicit, LOGGED fallback (no silent masking):
  `source ∈ {llm, deterministic, llm_failed_fallback, degraded}`. On LLM success
  the narrative is merged onto the full template and code injects
  `memory_matches`/`supporting_analogs`/`conflicting_analogs`/`direction_provenance`.
  On failure it logs a WARNING with the reason and falls back to deterministic.
- **Prompt** (`brain_prompt`) now requests the AB-4 narrative fields and tells the
  model NOT to emit analog/provenance fields (system-injected) but to cite the
  provided `memory_retrieval` analogs in `dominant_reasoning`.
- **Persistence** captures model/prompt/payload/raw/usage/fallback_reason per call.
- **Launch** (`launch_paper_session_fc.ps1`): `AI_BRAIN_LLM=true`, model gpt-4o-mini
  (observe-only — the brain still consumes nothing).

## Runtime evidence (real GPT calls)
- Single-scan 10:29: `source=llm`, usage 2696 tokens.
- 5-point comparison replay: **4 successful LLM calls + 1 explicit fallback,
  10,330 total tokens** → nonzero OpenAI input/output usage (dashboard sanity ✓).
- June 11 full-replay through `run_narrative_brain` previously showed 0 LLM calls
  with the flag OFF; with the flag ON the path fires (proven above).

## June 11 comparison — Wrapper vs Deterministic vs LLM Brain

| Decision | Wrapper | Deterministic | **LLM Brain** | 60-min reality |
|---|---|---|---|---|
| 10:00 buy-side raid | neutral | bearish | **bearish** | (raid → rejection) |
| 10:05 bearish response | conflicted | bearish | **bearish** | down |
| **10:29 LONG** | **bullish** (lost −1.34R) | conflicted | **bearish** | **−1.63** |
| 11:00 protected low | conflicted | bullish | **bullish** | up (rally) |
| **13:17 SHORT** | **bearish** (rally ahead) | conflicted | conflicted* | **+11.85** |

\* 13:17: the LLM returned an out-of-enum phase (`early_expansion`) → explicit
fallback to deterministic (conflicted). In an isolated retry the LLM returned
`bullish`/forbid-bearish. Either way it did NOT endorse the short.

**Key finding:** at 10:29 the LLM Brain produced a clear **bearish** read where
the deterministic core only managed "conflicted" and the wrapper was decisively
wrong (bullish). The LLM added decisiveness in the correct direction — the first
evidence the LLM contributes signal beyond the deterministic NA synthesis. Full
10:29 LLM output (real call):
> direction=bearish, phase=manipulation, forbidden=bullish, PH_status=approaching,
> draw=sell_side, story="bearish delivery state with exhaustion risks; price
> approaching protected high 702.5 but exhibiting weakness", dominant_reasoning=
> "bearish delivery and exhaustion as it nears the protected high",
> must_not_do=["initiate bullish trades without confirmation of reversal"].

## Honest reliability note
gpt-4o-mini occasionally emits a `narrative_phase` outside the 7-value enum
(e.g. `early_expansion`) → schema-core rejection → explicit deterministic
fallback. This is caught and logged, never silent. Tightening the prompt /
mapping phase synonyms is a future hardening item, not this phase.

## Tests / regression
`tests/test_phase_ai_brain_llm.py` (7, LLM mocked — zero network in regression):
enabled→LLM invoked; disabled→deterministic; failure→explicit logged fallback;
success→full schema; persistence captures LLM fields; build_narrative-alone is
not a brain package; core validator. **Regression: 990 passed, 0 failed.**

## Status
The real LLM Brain is ON in observe mode. No authority promotion, no generation,
no execution changes. STOP here per directive — next evaluation happens against
the real LLM Brain, not the deterministic core.
