# Production Brain Migration -- gpt-5.6-luna -> gpt-5.6-terra

Date: 2026-08-06 · Branch `ob-block-finder-and-evidence-diagnostics`
Starting HEAD `33fb562` (the PROD-20260806 archive commit).

**One variable changes: the model.** Risk, sizing, the decision window, trade
caps, structural-stop doctrine, target doctrine, CandidateProducer eligibility
and prompt semantics are untouched.

```
TERRA_ACCEPTED_FOR_PRODUCTION
```

## Why Terra

The August 6 session exposed the Brain as the weakest link in an otherwise
proven execution organism: 2 malformed responses in 38 calls, 3 schema
degradations, and a semantic contract that collapsed direction into
eligibility. Those defects were repaired at the contract level, not by changing
model. Terra is the capability upgrade applied *after* the contract was made
sound, so any behavioural difference is attributable to the model rather than
to a broken prompt.

| | previous | new |
|---|---|---|
| Model | `gpt-5.6-luna` | **`gpt-5.6-terra`** |
| Reasoning effort | none set (API default) | **unchanged -- none set** |
| Sampling controls | none sent | **unchanged -- none sent** |
| JSON mode | enforced | **unchanged -- enforced** |
| Price / 1M in-out | $0.20 / $1.20 | **$2.50 / $15.00 (12.5x)** |

`gpt-5.6` (unsuffixed) routes to **Sol**, not Terra, and is explicitly refused.

## Archived-session comparison

Corpus: the 66 post-semantic-repair scans of `PROD-20260806` (12:41-14:01 ET),
replayed from the immutable archive. Original Luna artifacts were not modified
and no new Luna calls were made.

### Structured-output reliability

| | Luna (live, same corpus) | Terra (counterfactual) |
|---|---|---|
| calls | 66 | 66 |
| malformed JSON | 0 | **0** |
| schema degradations | 0 | **0** |
| fallbacks | 0 | **0** |
| sovereign | 66/66 | **66/66** |
| model identity match | n/a | **66/66** |
| errors | 0 | **0** |

### Direction / action distribution -- identical inputs

| direction | Luna | Terra |
|---|---|---|
| bearish | 9 | **12** |
| bullish | 5 | **5** |
| conflicted | 22 | **17** |
| neutral | 30 | **32** |
| **directional** | **14 / 66** | **17 / 66** |

Terra agreed with Luna on **53 of 66** scans. Its disagreements moved 5 scans
out of `conflicted`, mostly into `bearish` -- consistent with the same evidence
under the repaired semantics, not with a more aggressive posture. Every one of
Terra's 66 responses carried an explicit `stand_down` action.

**More directional calls is not automatically better.** What matters is that
Terra kept direction separate from eligibility on every scan and never proposed
an entry it could not support.

### Candidate safety replay

All 66 Terra outputs were driven through production normalization, validation,
sovereignty classification, `CandidateProducer` and risk geometry in isolated
temporary state.

```
CANDIDATE ELIGIBLE      : 0
action_declines_entry   : 66
tokens minted           : 0
attempts consumed       : 0
order endpoints reached : 0
```

No Terra response invented a level, named an unsupported objective, or produced
a contradictory playbook/tool combination. No response became executable.

### Latency and cost -- measured

```
input tokens   : 558,604        output tokens : 70,496
latency mean   : 12.73 s        p95 : 15.70 s        max : 18.15 s
evaluation cost: $2.4539 (66 calls)     per call : $0.0372
same corpus on Luna : $0.1963           -> Terra is 12.5x
full-day estimate (172 scans/session)   : ~$6.40 per session
```

Latency roughly tripled versus Luna's typical few seconds but sits far inside
the 60-second scan cadence and the 45-second client timeout, so it does not
constrain the loop.

## Model-resolution changes

The migration's real hazard was never Terra. It was this:

```python
os.getenv("AI_BRAIN_MODEL", os.getenv("AI_MODEL", "gpt-4o-mini"))
```

`AI_MODEL=gpt-4o-mini` is actually set in this deployment. A missing or
mistyped `AI_BRAIN_MODEL` would not have failed -- it would have run an armed
production session on a far weaker Brain while every piece of telemetry still
named the intended model.

`src/ai_brain/production_model.py` is now the single authority:

- armed + explicit Terra -> resolves
- armed + absent -> `NO_BRAIN_MODEL` refusal
- armed + Luna / `gpt-5.6` / Sol / `gpt-4o-mini` / unknown -> `BRAIN_MODEL_NOT_AUTHORIZED`
- disarmed diagnostics remain usable

### Three hardcoded model constants were found and unified

Each would have silently blocked all trading after the migration, with no
symptom other than trades never happening:

| Location | Was | Effect if missed |
|---|---|---|
| `luna_candidate_producer.py:39` | `PRODUCTION_MODEL = "gpt-5.6-luna"` | every Terra thesis rejected `wrong_model` |
| `topstepx_execution_runner.py:230` | `!= "gpt-5.6-luna"` | every Terra thesis halted `AI_FALLBACK` |
| `model_pricing.py` | `PRODUCTION_MODEL = "gpt-5.6-luna"` | costs billed at Luna rates |

All three now import from the single authority. Test fixtures follow
`PRODUCTION_MODEL` rather than a literal, so the next migration needs no test
edits.

## Authorization binding

`SessionAuthorization` now binds the Brain identity into its fingerprint:

```
brain_model                 = gpt-5.6-terra
brain_reasoning_effort      = "" (API default)
json_mode_required          = true
brain_contract_fingerprint  = sha256(brain_prompt + brain_schema + brain_validation)
```

Changing the model, the reasoning effort, the JSON-mode requirement, or the
prompt/schema/validator contract now **invalidates** the authorization. On
August 6 the semantic contract was repaired while an authorization was live;
that can no longer pass unnoticed.

The issuer resolves these from production code, never from operator free text.
The expired `PROD-20260806` authorization was not modified.

## Startup telemetry

```
PRODUCTION BRAIN MODEL       : gpt-5.6-terra
BRAIN TIER                   : Terra
JSON MODE                    : ENFORCED
REASONING EFFORT             : API default (unset)
BRAIN CONTRACT FINGERPRINT   : ...<short suffix>
MODEL FALLBACK               : NONE
```

## Bounded live verification

One read-only call through the real production scan path:

```
requested model : gpt-5.6-terra
returned model  : gpt-5.6-terra   (identity match)
source          : llm             degraded_reason: none
DIRECTION       : conflicted      ACTION : stand_down   (reported independently)
playbook / tool : none / ['none'] invalidation : None
sovereign       : True
CANDIDATE       : none -> action_declines_entry
usage           : 8,816 in / 1,459 out
order writes    : 0
```

Accepted on its actual content. The call was not repeated to obtain a
directional answer.

## Safety gates -- all preserved

| Gate | Status |
|---|---|
| API-enforced JSON mode | PASS |
| Armed refusal when JSON mode disabled | PASS |
| Recognised tool-family string-to-list | PASS |
| Unknown tool family fails closed | PASS |
| Explicit degraded-reason telemetry | PASS |
| Direction / action separation | PASS |
| `conflicted` reserved for real opposition | PASS |
| Directional `stand_down` legal | PASS |
| CandidateProducer rejects non-entry actions | PASS |
| Deterministic fallback never authors a candidate | PASS |

Focused tests: 43. Full suite: **3513 passed**.

## Limitations

- Terra has **never traded**. It has produced zero candidates, zero tokens,
  zero orders and zero fills. This migration proves classification behaviour and
  safety-gate integrity only.
- The comparison corpus is one afternoon of one instrument, 66 scans, in a
  lunch-hour range. It contains no strong trend and no live fill.
- Terra costs **12.5x Luna per token** (~$6.40/session vs ~$0.51). The upgrade
  is a capability decision, not a cost-neutral one.
- Latency roughly tripled (mean 12.7 s). Comfortable at a 60 s cadence; it would
  not be at a 15 s cadence.
- Reasoning effort is unset, so Terra runs at the API default. Tuning it is a
  separate, later, one-variable mission.
- The evaluation ran with `response_format={"type":"json_object"}`, which
  guarantees parseable JSON but **not** field types -- the tool-family container
  normalization remains load-bearing.

## Rollback procedure

Rollback is deliberately **not** a silent runtime fallback. There is no code
path that falls back to Luna if Terra errors; a failed call degrades and
produces no candidate.

To roll back:

1. **Source/config change** -- set `PRODUCTION_MODEL = "gpt-5.6-luna"` in
   `src/ai_brain/production_model.py` and `AI_BRAIN_MODEL=gpt-5.6-luna` in
   `.env`. The constant is the authority; the env var alone will be refused.
2. **Complete tests** -- run the full suite. Pricing and fixture tests follow
   `PRODUCTION_MODEL` and will move automatically.
3. **New authorization** -- any existing authorization becomes invalid the
   moment the model changes (`AUTHORIZATION_BRAIN_MODEL_MISMATCH`). A fresh
   record must be issued for the session date.

All three steps are required. Skipping any one leaves the armed launcher
refusing to start, which is the intended failure mode.
