# data/news — NEWS-1 source files

The News Intelligence Layer (`src/news/`) reads scheduled events and breaking
headlines from local JSON here. Empty arrays = no events = `risk_state: normal`
(the safe production default). A live feed can replace these files later without
changing the layer's contract.

- `economic_calendar.json` — list of `{event_name, event_time(ISO), impact_level?, country?, actual?, forecast?, previous?}`
- `breaking_news.json` — list of `{headline, source?, timestamp(ISO), category?, importance?, summary?}`
- `news_memory.jsonl` — append-only event→response observations (NEWS-1 Phase 6, storage only)

Overridable paths: `NEWS_CALENDAR_PATH`, `NEWS_BREAKING_PATH`, `NEWS_MEMORY_DIR`.
Layer is gated by `NEWS_LAYER_ENABLED` (default `false`).
