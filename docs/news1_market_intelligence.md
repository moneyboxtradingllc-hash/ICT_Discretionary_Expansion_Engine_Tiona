# NEWS-1 — Market Intelligence Layer Foundation

Gives the AI Brain awareness of information **outside price action** —
scheduled economic releases, breaking financial news, geopolitical shocks — as
an additional **evidence source**. The Brain decides what it means. This is a
market-AWARENESS system: **not** a trade engine, **not** a signal engine,
**not** a directional engine.

**Gated by `NEWS_LAYER_ENABLED` (default `false`).** When off, the pipeline is
bit-for-bit the pre-NEWS-1 system (regression: 1034 → **1061 passed**, the 27
additions are all new NEWS-1 tests). Offline + deterministic (local JSON
sources) = safe for paper trading. No authority, execution, trade-generation,
playbook, toolbox, risk-engine, or directional-ownership code was modified.

## Package (`src/news/`)
> The spec listed `news/`; like every other module it lives under `src/` so the
> existing `sys.path.insert(0,"src")` import convention resolves it.

| File | Phase | Responsibility |
|---|---|---|
| `calendar_provider.py` | 1 | `EconomicEvent`, `EconomicCalendarSnapshot`, `EconomicCalendarProvider` — scheduled macro releases → `{scheduled_event_window, event_name, minutes_to_event, impact_level}` |
| `breaking_news_provider.py` | 2 | `BreakingNewsEvent`, `BreakingNewsProvider` — market-moving headlines within an active window |
| `news_classifier.py` | 3 | `NewsAssessment` — category + `relevance_to_nasdaq` (none→critical) |
| `event_risk_engine.py` | 4 | `EventRiskAssessment` — risk state (normal / caution / high_risk / stand_down / post_event_digest) |
| `news_engine.py` | 5 | `news_enabled()`, `build_news_context()` — assembler + Brain entry point |
| `news_memory.py` | 6 | `NewsMemory`, `NewsMemoryRecord` — persistent event→response store (storage only, NO learning) |

Every function is **never-raise**: any provider/classifier/engine failure
degrades to empty/normal, never to an exception that could disturb a scan.

## Phase 1 — Economic Calendar
Tracks CPI, Core CPI, PPI, Core PPI, NFP, Unemployment, FOMC, Powell speeches,
Fed speakers, Treasury auctions, GDP, Retail Sales, ISM. Stores
`event_name, event_time, impact_level, country, actual, forecast, previous`.
Relative to the scan clock it computes the nearest upcoming event, `minutes_to_event`,
`scheduled_event_window`, and any just-passed event inside a 30-min digest
window. Default impact is assigned per event when the row omits it (CPI/FOMC/
NFP/PPI/GDP = high).

## Phase 2 — Breaking News
Ingests geopolitical/war/sanction/tariff/central-bank-surprise/AI-tech/SEC/
exchange-outage headlines from a local feed file, surfacing those within a
90-min active window. **No sentiment trading** — it only makes the headline
available for relevance/risk rating.

## Phase 3 — News Classification
`classify_news` assigns one of `economic_release, fed, geopolitical, technology,
earnings, government_policy, market_structure, unknown` and a
`relevance_to_nasdaq` of `none|low|medium|high|critical` (category floor, raised
by importance, escalated to critical on shock keywords like "emergency",
"exchange outage", "invasion"). It carries **no direction** — verified by test
`test_classifier_has_no_direction`.

## Phase 4 — Event Risk Engine
Combines calendar + breaking assessments into one **risk-awareness** state
(takes the higher of the two). Reference behaviour, all asserted by tests:
| Situation | risk_state |
|---|---|
| no event | `normal` |
| tracked event ≤60m | `caution` |
| high-impact event ≤15m (e.g. CPI in 10) | `high_risk` |
| high-impact event ≤5m (e.g. FOMC in 5) | `stand_down` |
| ≤30m after an event (e.g. 5m after CPI) | `post_event_digest` |
| breaking relevance high / critical | `high_risk` / `stand_down` |

## Phase 5 — Brain Integration
`snapshot_builder` runs a **gated** news pre-pass (after regime, **before** the
ECU pre-pass) so the Brain receives the context:
```
if news_enabled(): snapshot["news_context"] = build_news_context(timestamp)
```
`build_brain_input` passes `news_context` through into the LLM payload **only
when present** (absent ⇒ payload identical to pre-NEWS-1). `narrative_brain`
appends `NEWS_CONTEXT_ADDENDUM` to the system prompt **only when** the payload
carries `news_context` — the base `BRAIN_SYSTEM_PROMPT` is untouched otherwise.

`news_context` shape (canonical Phase-5 fields + non-directional extras):
```json
{ "risk_state": "high_risk", "active_event": "CPI", "minutes_to_event": 6.0,
  "breaking_news_active": true, "breaking_news_category": "technology",
  "summary": "CPI in 6m (high impact); breaking technology (relevance medium); risk=high_risk",
  "scheduled_event_window": true, "impact_level": "high",
  "breaking_news_relevance": "medium", "reasons": [...], "directional": false }
```
The addendum permits the Brain to **reduce confidence / lower certainty / wait /
stand down**, and forbids it from **deriving direction from news** or
**creating a trade from a headline**. Price action remains primary. There is no
direction/side/buy/sell field anywhere in `news_context` (verified by
`test_news_context_has_no_direction_or_trade`).

## Phase 6 — News Memory
Append-only JSONL store of `{event, timestamp, direction_before,
direction_after, market_response, volatility_profile}`. `by_event()` recalls
prior observations for an event type. **Storage only — no learning/inference
logic** (deferred, per spec). This is the substrate a future phase will use for
"have I seen this type of event before?".

## Producer → Consumer map
```
local JSON ─► EconomicCalendarProvider ─┐
              BreakingNewsProvider ─► news_classifier ─► event_risk_engine
                                                              │
                                          build_news_context (news_engine)
                                                              │  (gated)
        snapshot_builder pre-pass ─► snapshot["news_context"] │
                                                              ▼
                       build_brain_input  ─►  narrative_brain (+addendum)
                                                              ▼
                                       AI Brain  (weighs as CONTEXT only)
                                                              │
                            (price/delivery/liquidity still OWN direction)

  NewsMemory  ◄── (future) records event→response;  NEWS-1 = storage only
```
**Producers:** calendar/breaking providers, classifier, risk engine.
**Consumer:** the AI Brain (read-only context). **Non-consumers (unchanged):**
qualification, playbook classifier, toolbox, risk governor, execution gate —
none read `news_context`; news cannot reach a trade decision.

## MAP-NEWS-1 audit
1. **Detect scheduled economic events?** ✅ `EconomicCalendarProvider` (CPI/FOMC/
   NFP/… with minutes-to-event + window). Tested.
2. **Detect breaking news?** ✅ `BreakingNewsProvider` (active-window headlines). Tested.
3. **Classify event type?** ✅ 8 categories via `classify_news`. Tested.
4. **Classify relevance?** ✅ `relevance_to_nasdaq` none→critical. Tested.
5. **Classify risk?** ✅ 5 risk states via `event_risk_engine`. Tested (all 5).
6. **Feed the Brain?** ✅ gated `snapshot["news_context"]` → `build_brain_input`
   → prompt addendum. Tested (pass-through + omission + addendum separation).
7. **Store event memory?** ✅ `NewsMemory` JSONL, storage-only. Tested.
8. **Does news generate trades?** **NO.** `news_context` has no direction/side/
   buy/sell field; the addendum forbids direction/trade from news; no
   trade-path module consumes it. Tested (`test_news_context_has_no_direction_or_trade`,
   `test_classifier_has_no_direction`).
9. **Does the Brain remain ECU?** **YES.** News is one more evidence input the
   Brain weighs; direction/opportunity/playbook/tool ownership is unchanged
   (no AB-5x code touched).
10. **Production-safe for paper trading?** **YES.** Gated default-off
    (bit-for-bit when off), every component never-raises and degrades to
    `normal`/empty, offline deterministic sources, regression **1061 passed**.

## Deliverables
NEWS-1 implementation (`src/news/`, 6 modules) ✓ · gated Brain integration ✓ ·
tests (27, all green) ✓ · regression (1061 passed) ✓ · producer/consumer map ✓ ·
MAP-NEWS-1 (10/10) ✓. **STOP after NEWS-1 + MAP-NEWS-1. NEWS-2 not started.**
