# MAP-1 — AI Brain Audit (read-only, at `ba895cc`)

Required before AB-4. Audit only — no code changed. The critical finding up
front: **there are TWO AI paths in the bot right now, and they have opposite
authority.**

| | OLD wrapper (`ai_layer/discretionary_ai`) | NEW brain (`ai_brain/`, AB-1) |
|---|---|---|
| Output | 11 fields (2 consumed: ai_direction, ai_confidence) | 23-field machine-consumable schema |
| Input | starved compact input (no price on no-setup scans, no candles, no position, no self-memory) | full two-sided context + price + candles + position + self-memory + retrieval |
| Memory | none (amnesiac) | StanceMemory (self) + AB-3 vector store |
| Authority | **ADVISORY — consumed** (debate score, fusion, NA-1 lens, ai_feedback) | **OBSERVE-ONLY — consumed by nobody** |
| Default | always on | `AI_BRAIN_ENABLED` (on in fc launch) |

AB-4 is the cutover: retire the old wrapper from the consumed path, give the new
brain its (gated) authority. MAP-1 maps the new brain's current standing.

## 1. What the AI sees (inputs)

NEW brain input (`ai_brain/brain_input.build_brain_input`), per scan:
- **market**: current_price, per-TF candles (bodies/wicks/close), volatility_state, expansion_state
- **structure_WITNESS**: per-TF bias/state/bos/mss — explicitly tagged witness
- **delivery**: state, confidence, continuation_intact, exhaustion, PO3 phase + manipulation/distribution direction
- **liquidity**: sweep events, nearest buy/sell-side, active_draw
- **protected_swings**: protected_high/low + approach/reject/violate status
- **playbook_toolbox**: BOTH directions' inventory (bullish live-scored + bearish inventory)
- **position**: open?/direction/entry/unrealized/stop/thesis_health
- **stance_history**: last stance, prior 5, thesis anchor, changed_since_last
- **governance_context**: regime, council dominant, NA direction/forbidden
- **conflicts/warnings**: from NA-1
- **degraded[]**: explicit list of anything missing (candles, price, prior-session levels)

Fixes the AI-0 starvation: price/candles/position/self-memory/two-sided/protected
all now present; missing inputs are surfaced, not silent.

## 2. What the AI remembers

- **Self-memory** (`ai_brain/stance_memory.StanceMemory`): RAM ring buffer of the
  brain's own prior stances; answers "what did I say last scan / when the thesis
  began / what changed." Ends the amnesia. (RAM — cross-restart persistence is AB-4+.)
- **Vector memory** (AB-3 `ai_retrieval/`): persistent JSONL store, 667 seeded
  June 10/11 records, survives restart. Provenance-enforced.

## 3. What the AI retrieves

AB-3 `retrieve_analogs()` — nearest historical market-state analogs by cosine
similarity, authoritative-only (structure-tainted/unknown provenance excluded),
with outcome (win/loss/R), prior narrative, prior playbook, management path.
Currently surfaced in `snapshot["ai_retrieval"]` (gated `AI_RETRIEVAL_ENABLED`).
NOT yet fed into the brain's `memory_matches[]` slot — that wiring is AB-4.

## 4. What consumes the AI (evidence-traced)

- **NEW brain output** (`snapshot["ai_brain"]`): written at `scan_loop:922`,
  compacted into the archive at `snapshot_store:66`. **Consumed by no
  generation/permission/execution path.** (The `"ai_brain"` strings in
  `ai_debate_engine`/`authorship` are a reserved source LABEL for AB-4, not
  consumption.) → observe-only, confirmed by grep.
- **AB-3 retrieval** (`snapshot["ai_retrieval"]`): written `scan_loop:916`,
  consumed by nobody. → observe-only.
- **OLD wrapper** (`ai_discretionary`): consumed by `ai_feedback` (post-trade
  scoring), the AI debate (`ai_direction` +10 to a case), confidence fusion, and
  the NA-1 delivery/AI lens. → **advisory, live.** This is the AI that currently
  touches decisions, via 2 fields.

## 5. What authority the AI has

- NEW brain: **none.** Pure observation + persistence.
- OLD wrapper: **advisory only** — `ai_direction`/`ai_confidence` feed the debate
  verdict (one input among many), fusion (blocks only on strong_disagreement),
  and the NA-1 lens (which itself is observe-only unless `NARRATIVE_AUTHORITY=
  enforce`). It cannot author generation direction (firewalled AB-2A/2B/2C) and
  cannot place/size/approve trades.

## 6. What authority the AI does NOT have (either path)

Generation direction (firewalled) · qualification direction · playbook selection ·
toolbox selection · trigger/entry · **execution gate approval** · risk multiplier ·
max-trades / daily-loss · broker exposure (Broker Supremacy) · stop submission ·
order submission. None of these read `snapshot["ai_brain"]`.

## 7. AI Brain standing summary

```
SEES:      full two-sided context + price/candles/position (AB-1) ✓
REMEMBERS: own stances (RAM) + 667-record vector store (persistent) ✓
RETRIEVES: authoritative historical analogs w/ outcomes (AB-3) ✓
CONSUMED:  by nobody — observe-only ✓
AUTHORITY: none (new brain); old wrapper advisory-only via 2 fields
```

## AB-4 readiness

MAP-1 complete. The new brain is fully sensed, memoried, and retrieval-backed,
and verifiably consumed by no authority path. AB-4's scope is now well-defined:
1. feed AB-3 analogs into the brain's `memory_matches[]`;
2. wire the brain's narrative output as a gated authority (gate permit / playbook
   seed) replacing the old wrapper's advisory role;
3. retire the old 2-field wrapper from the consumed path;
4. persist stance memory across restarts.
Each gated observe→enforce, with the June 11 replay harness, exactly as FC-1/NA-1.

**AB-4 may begin.**
