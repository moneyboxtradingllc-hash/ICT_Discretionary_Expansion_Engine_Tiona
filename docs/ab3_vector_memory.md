# Phase AB-3 — Vector Memory & Narrative Retrieval (SHIPPED, observe-only)

Gives the AI Brain memory: "what have I seen that resembles this?" — true
embedding-based retrieval over market-state vectors, provenance-enforced,
consuming nothing with authority.

## Architecture

```
snapshot ──embed()──► state vector (EMBED_DIM)
                          │
data/live_snapshots ─backfill─► memory records ─add_record─► vector_store (JSONL, persistent)
data/paper_trades   ─backfill─►   (+ embedding)                   │
                                                                  ▼
current snapshot ─retrieve_analogs(authoritative_only)─► cosine rank ─► top-k analogs
                                                                  │           │
                                              provenance gate (reject tainted/unknown)
                                                                  ▼
                                              retrieval_logs/ (query vec, accepted, rejected)
                                                                  │
                                              snapshot["ai_retrieval"]  (OBSERVE-ONLY; consumed by nobody)
```

## Modules (`src/ai_retrieval/`)

| File | Role |
|---|---|
| `memory_schema.py` | MemoryRecord (market/narrative/playbook/outcome/provenance context); `classify_provenance`, `is_authoritative` |
| `embedding.py` | `embed()` → fixed-dim state vector (one-hot regime/vol/session/phase/direction + scalars); `cosine()`. Keyed on narrative/delivery/liquidity/protected-swing — NOT entry-model labels |
| `vector_store.py` | persistent append-only JSONL at `data/ai_retrieval/memory_store.jsonl`; survives restart |
| `retrieval.py` | `retrieve_analogs()` (authoritative-only by default) + audit logging; `retrieve_for_snapshot()` scan hook (gated `AI_RETRIEVAL_ENABLED`) |
| `backfill.py` | seed June 10/11 snapshots + trades |

## Memory schema (record)

market_context{timestamp,symbol,session,regime,volatility_state} ·
narrative_context{narrative_direction,narrative_phase,active_liquidity_draw,
protected_high,protected_low,delivery_direction,delivery_direction_source} ·
playbook_context{active_playbook,toolbox_state,entry_model} ·
outcome_context{trade_taken,trade_direction,win_loss_be,r_multiple,management_path} ·
provenance{direction_source,source_validated,structure_tainted}.

## Provenance enforcement (proof)

VALID: sweep_semantics, liquidity_reclaim, protected_swing, explicit_po3_transition,
delivery_protected, liquidity_draw, ai_brain, narrative_authority.
INVALID: structure, structure_bias, bias_only, directional_bias, bos, mss.

`is_authoritative(rec)` = source_validated AND NOT structure_tainted. Retrieval
with `authoritative_only=True` (default) excludes tainted AND unknown-provenance
records. Tests T2: structure_bias/bos/unknown → 0 returned, all rejected;
sweep_semantics → returned. Backfill does NOT propagate pre-firewall
`qualification.direction` as narrative truth — narrative_direction is populated
only when sweep provenance exists.

## June 10/11 corpus

Seeded: **667 records** (659 market + 8 trade) into `data/ai_retrieval/`.
**188 authoritative** (sweep-sourced); the remaining 479 are stored for audit
but non-authoritative by provenance — the honest posture for pre-firewall
history. The June 11 long is in the corpus as a `loss` (r=-1.34), retrievable
as a trade-outcome memory.

## Retrieval example (bearish manipulation / above_high raid context)

Query: range_rotation / unstable / bearish_delivery / manipulation / sell-side
draw / protected_high → returns sweep_semantics-sourced bearish analogs; 661
non-authoritative records rejected and logged. Observe-only.

## Authority

NONE. AB-3 retrieves and logs. `snapshot["ai_retrieval"]` is consumed by no
generation/qualification/playbook/toolbox/gate/execution path (T6 + static
import guard: ai_retrieval imports none of those modules). Brain consumption of
analogs into its `memory_matches[]` is AB-4.

## Acceptance / regression

T1 vector retrieval ✓ · T2 tainted never authoritative ✓ · T3 persists across
restart ✓ · T4 narrative retrieval without entry-model labels ✓ · T5 June 10/11
corpus loads ✓ · T6 observe-only ✓ · T7 retrieval logging complete ✓ ·
**T8 regression 973 passed, 0 failed.** Rollback: `AI_RETRIEVAL_ENABLED=false`
(default) — scan hook inert, zero behavior change.

## Next: MAP-1 (AI Brain audit) required before AB-4.
