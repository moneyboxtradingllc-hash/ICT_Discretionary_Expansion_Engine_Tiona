# AI_BRAIN_LLM Truth Audit (evidence only, at `a92a821`)

No fixes, no changes. Establishes whether the AI Brain actually invokes an LLM
and whether that LLM influences conclusions.

## Bottom line

**The new AI Brain made ZERO LLM calls during AB-5A and makes zero in the default/
live config.** Its conclusions are produced by the deterministic NA synthesis +
retrieval. The LLM path exists, is wired, and is reachable — but is gated OFF by
default and was never enabled. The only GPT in the system is the LEGACY wrapper
(`ai_discretionary`), which the Brain consumes second-hand as one arbitration lens.

## 1. LLM call inventory

| File | Function | Purpose | Active? |
|---|---|---|---|
| `ai_brain/narrative_brain.py:142 _call_llm` | brain's OpenAI chat.completions call | the ONLY brain-native LLM path | gated `AI_BRAIN_LLM`, default false |
| `ai_brain/narrative_brain.py:36 _llm_enabled` | reads `AI_BRAIN_LLM` | gate | default "false" |
| `ai_layer/ai_api_adapter.py:218 _call_chat_completions` | legacy wrapper GPT call | OLD wrapper (`discretionary_ai`) | **active** (live) |
| `ai_layer/ai_api_adapter.py:192 _call_responses_api` | legacy wrapper alt path | OLD wrapper | active |
| `ai_layer/ai_api_adapter.py:249 call_external_ai` | legacy wrapper entry | OLD wrapper | active |
| `narrative_authority/narrative_engine.py` | — | NA synthesis | **NO LLM — pure deterministic (grep: none)** |

The Brain's `_call_llm` uses `_openai` imported from `ai_api_adapter`; it is the
single brain LLM site.

## 2. AI_BRAIN_LLM status

- **Default:** `"false"` — `narrative_brain.py:37`:
  `os.getenv("AI_BRAIN_LLM", "false").lower().strip() == "true"`.
- **Set anywhere?** No — grep of all `.ps1`/`.sh`/`.env`/`.json` (incl.
  `launch_paper_session_fc.ps1`) finds no assignment. The fc launch sets
  `AI_BRAIN_ENABLED=true` and `AI_RETRIEVAL_ENABLED=true` but NOT `AI_BRAIN_LLM`.
- **Runtime value:** false (unset → default).
- **Environment/config source:** none; only the in-code default.

## 3. Runtime replay verification (instrumented)

June 11 replayed through `run_narrative_brain` with `_call_llm` / `_deterministic`
instrumented:

```
scans / brain evaluations:        322
LLM calls (_call_llm invoked):    0
deterministic-core calls:         322
```

**Zero LLM calls.** And the AB-5A harness (`ab5a_pressure_test.py`) is even
further removed: it called `build_narrative` (the deterministic NA engine)
DIRECTLY — it never invoked `run_narrative_brain` at all, so the LLM path was not
even reachable in AB-5A.

Force test: with `AI_BRAIN_LLM=true` and a key present, `_call_llm` was invoked
once but returned `source="deterministic"` (call failed/invalid → fell back).
Even forced-on, output was deterministic in this environment.

Contrast — the OLD wrapper on June 11 (archived): `external_success=321`,
`reused=134`, `fallback=1` of 322. GPT was very active — but only for the legacy
wrapper, never the Brain.

## 4-6. Producer table (10:29 long AND 13:17 short — identical producers)

Both decisions ran with `AI_BRAIN_LLM=false` → deterministic core.

| Field | Producer |
|---|---|
| narrative_direction | **deterministic** — `build_narrative` NA arbitration |
| phase_confidence / confidence | **deterministic** — NA |
| forbidden_direction | **deterministic** — NA |
| narrative_phase | **deterministic** — NA `_classify_phase` |
| active_liquidity_draw | **deterministic** — `liquidity_objectives` |
| dominant_reasoning | **deterministic** (NA reasons) + **retrieval** text (analog tally) |
| supporting_analogs | **retrieval** (vector store) |
| conflicting_analogs | **retrieval** (vector store) |
| recommended_playbook_family | **deterministic** — NA narrative_phase |
| recommended_tool_family | **deterministic** — toolbox inventory |
| memory_matches | **retrieval** |
| direction_provenance | **deterministic** (computed from NA lenses) |
| **GPT/LLM (brain-native)** | **0 fields** |

Indirect GPT: NA's `_ai_lens` (`narrative_engine.py:82`) reads
`ai_discretionary.ai_direction` — the LEGACY wrapper's GPT output — as ONE of
three arbitration lenses (AI vs Delivery vs Structure-witness). So at 10:29 the
"AI=bullish@65" half of the conflict IS the legacy GPT; the Brain then arbitrated
it against (deterministic) delivery. The Brain made no GPT call itself, but its
direction is partly a function of the wrapper's GPT direction, deterministically
arbitrated.

## 7. LLM influence audit

A true enabled-vs-disabled A/B with a live, schema-valid LLM response cannot be
run in this environment (forced-on fell back to deterministic). Structurally:
when `AI_BRAIN_LLM=false` (default/all real runs), `_call_llm` is never called
and `_deterministic` produces 100% of output. When forced true without a valid
response, the same `_deterministic` runs via fallback. Therefore in every run
performed to date, **the LLM changed nothing because it never produced output.**

## 8. Deterministic dependency

- **Direction originates:** `narrative_engine._build` arbitration (AI lens +
  delivery lens + structure-witness). The delivery lens is deterministic
  (PO3/sweep); the AI lens is the legacy wrapper's GPT direction.
- **Confidence originates:** NA (`narrative_confidence`), deterministic.
- **Narrative/phase originates:** NA `_classify_phase`, deterministic.
- **Output composition:** ~**100% deterministic / retrieval**, **0% brain-LLM-
  generated**. Of the 31 output fields, brain-native LLM produced none; retrieval
  produced the analog fields; deterministic NA produced the rest.

## 9. Final verdict

A. **Was GPT/LLM used during AB-5A?** No — by the Brain: zero. (The AB-5A harness
   called `build_narrative` directly; no brain orchestrator, no LLM path.)
B. **If yes, how many?** N/A — zero brain LLM calls.
C. **What produced Brain conclusions?** Deterministic NA synthesis + vector
   retrieval (analogs). Indirectly, the legacy wrapper's GPT direction enters as
   one NA arbitration lens.
D. **June 11 decisions generated by GPT or deterministic logic?** Deterministic
   logic (NA), arbitrating a legacy-GPT AI-lens against deterministic delivery.
E. **Is the current Brain an LLM-powered reasoning system?** No — not as run. It
   is a deterministic narrative engine with an LLM path present but inactive.
F. **Deterministic engine with LLM infra present but inactive?** Yes — exactly.
G. **% of Brain conclusions from GPT?** Brain-native LLM: **0%.** Indirect (the
   GPT AI-lens feeding one of three NA arbitration inputs): non-zero but
   deterministically mediated; the brain emits no GPT-authored field.

## Deliverables
Code evidence (inventory + gate) ✓ · runtime evidence (0/322) ✓ · replay evidence
✓ · producer table ✓ · call counts ✓ · final verdict ✓. No fixes, no redesign.
