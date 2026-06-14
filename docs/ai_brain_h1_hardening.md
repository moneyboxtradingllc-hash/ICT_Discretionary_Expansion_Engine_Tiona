# AI-BRAIN-H1 — LLM Brain Hardening (SHIPPED, observe-only)

Reliability hardening only. No authority, generation, gate, or execution wired.
Goal: the LLM Brain consistently produces valid, complete, internally coherent
narrative output.

## Pipeline (per scan, observe-only)
```
LLM call → normalize_output() → needs_repair()? → [repair LLM call] → re-normalize
        → still incomplete? → EXPLICIT logged fallback to deterministic
        → else accept (merge code-injected analog/provenance fields) → validate
```

## What was built
- **`brain_validation.py`** — `normalize_output` (deterministic, non-fallback):
  enum-synonym → valid phase; tool/playbook family coherence vs direction
  (incoherent → neutralized); forbidden_direction coherence; **fill** empty
  completable fields (tool/playbook family, protected statuses, draw, forbidden)
  with safe defaults; strip unsupported analog citations. `needs_repair` —
  triggers an LLM repair ONLY for genuine content gaps (missing direction/phase,
  empty or shallow `dominant_reasoning`); everything else is filled, not repaired.
- **Prompt** hardened: "do not answer with only a label", enum list enforced,
  tool/forbidden coherence rules, citation rule.
- **Repair prompt** (`REPAIR_PROMPT_TEMPLATE`): original output + errors + schema
  + "correct only invalid fields, no new facts".
- **`_call_llm`** gained a repair turn; **persistence** captures raw, parsed,
  normalization_notes, repair_attempted, repair_errors, repair_usage, fallback.

## Fallback-rate rerun (live GPT)
Same AB-5A-L-style stratified sample (22 scans, real calls):
**fallback rate = 0/22 = 0.0%** (target <5% ✓). 14 repairs, 4 normalizations,
all 22 accepted as `source=llm`. Zero silent fallbacks (every fallback path logs
`_log.warning` + records `fallback_reason`). Zero unlogged schema/tool issues.

## June 11 decision checks (live, post-hardening)
| Point | source | dir | phase | forbidden | tools | coherent | reasoning full | repair |
|---|---|---|---|---|---|---|---|---|
| 10:25 | llm | bearish | manipulation | bullish | none | ✓ | ✓ | yes |
| 10:29 | llm | bearish | manipulation | bullish | none | ✓ | ✓ | no |
| 11:00 | llm | bullish | exhaustion | bearish | confirmation_required | ✓ | ✓ | yes |
| 13:17 | llm | **bearish** | manipulation | bullish | bearish | ✓ | ✓ | no |

All four: valid phase, coherent tools (no contradiction), forbidden coherent,
full-story reasoning. 10:29 correctly bearish (refuses the losing long).

## Final report
1. **What caused fallbacks (the 14%)?** Three drivers: (a) out-of-enum
   `narrative_phase` (`early_expansion`, `range_rotation`); (b) empty
   `recommended_playbook_family`/`recommended_tool_family`; (c) shallow/label-only
   `dominant_reasoning`. (a)+(b) are now normalized/filled deterministically;
   (c) triggers a repair turn.
2. **Enum/schema fixed:** 9-value phase enum enforced + synonym map; core-vs-full
   schema split; deterministic fill of completable fields.
3. **Tool contradictions fixed:** bearish-narrative-with-bullish-tools (and
   inverse) are neutralized to `confirmation_required`; conflicted/neutral forced
   to neutral families; forbidden_direction never equals own direction.
4. **Reasoning depth improved:** yes — the depth gate forces ≥4 story elements
   and ≥60 chars; shallow output is repaired (14/22 scans needed and got repair).
5. **Fallback rate <5%?** Yes — **0.0%** on the rerun sample (small sample; the
   repair turn is the mechanism, so true rate depends on repair success — see
   caveat).
6. **10:29 and 13:17 complete & coherent?** Yes — both produce full, schema-valid,
   internally coherent narratives.
7. **Reliable enough for another forensic replay?** For SCHEMA/COHERENCE
   reliability — yes. For DIRECTIONAL reliability — **no, and this is the honest
   limit of H1**: the live LLM is non-deterministic on direction (13:17 returned
   bullish in AB-5A-L but bearish here). Hardening guarantees the output is
   well-formed and coherent; it does NOT make the direction stable or correct.
   Any directional/authority claim must account for this variance — which is
   exactly why authority remains unpromoted.

## Tests / regression
`tests/test_phase_ai_brain_h1_hardening.py` (16, LLM mocked): enum normalize,
repair triggers, fill-not-repair, tool coherence (T4/5/6), forbidden coherence,
citation strip/keep, explicit-fallback logging, persistence, 10:29/13:17
coherence. **Regression: 1006 passed, 0 failed.**

## Status
LLM Brain is schema-hardened in observe mode. No authority promoted, no AB-5B.
Open item for the next phase: directional non-determinism (consider temperature
control, multi-sample voting, or a deterministic-delivery tiebreak) before any
veto/authority is considered.
