# MAP-3 — Post-H2 Production Brain Wiring Audit (read-only, at `feeee2c`)

Producer/consumer map of the production Brain after H2. No code changed (no
wiring defect found). Grep-verified.

## Phase 1 — input producer map (build_brain_input payload)

| Field group | Producer | Classification |
|---|---|---|
| `market.{current_price,candles}` | timeframe_builder / bars | SAFE |
| `market.{volatility_state,expansion_state}` | volatility/expansion engines (via market_regime) | SAFE |
| `delivery.{state,confidence,po3_15m phase/manip/dist dir,po3_alignment}` | shared_context + po3_engine (sweep-sourced, AB-2C provenance) | SAFE (clean delivery) |
| `liquidity.{events,nearest_buy/sell_side,active_draw}` | liquidity_engine + narrative_authority draw | SAFE |
| `protected_swings.{protected_high/low + status}` | ProtectedSwingTracker (NA-1) | SAFE |
| `STRUCTURE_WITNESS.{swing levels, bos_event, mss_event, _disclaimer}` | structure_engine — **non-directional only** | WITNESS |
| `stance_history` | StanceMemory (persistent) | MEMORY |
| `memory_retrieval / memory_matches` | ai_retrieval (June-corpus, provenance-filtered) | RETRIEVAL |
| `governance_context.regime` | regime_classifier | GOVERNANCE (environmental) |
| `conflicts`, `warnings` | narrative_authority flags | OTHER (textual) |
| `position` | position_monitor | SAFE |

**No directional structure reaches the prompt.** `structure_WITNESS.bias` and
directional `state` (removed in H2) are absent; structure carries only swing
levels + event booleans + a disclaimer. Taint guard confirms (Phase 7).

## Phase 2 — prompt payload sections
| Section | Purpose | Producer | Directional structure? |
|---|---|---|---|
| MARKET | price/candles/vol/expansion | feed + engines | no |
| DELIVERY | delivery state + PO3 direction (sweep-sourced) | shared_context/po3 | no |
| LIQUIDITY | sweep events, pools, active draw | liquidity engine/NA | no |
| PROTECTED_SWINGS | protected high/low + status | NA-1 tracker | no |
| STRUCTURE_WITNESS | swing levels + bos/mss events + disclaimer | structure engine | **no (witness only)** |
| STANCE_HISTORY | prior brain stances | StanceMemory | no |
| MEMORY_RETRIEVAL | analogs | ai_retrieval | no |
| GOVERNANCE | regime label only | regime classifier | no |
Confirmed: **no directional structure fields exist** in the payload.

## Phase 3 — Brain output map (31 fields)
All 31 fields are produced by the LLM (clean path) or normalization/retrieval
(memory_matches, supporting/conflicting_analogs, direction_provenance code-
injected). **Persistence:** `data/ai_brain/<ts>_QQQ.json` (full record),
`snapshot["ai_brain"]` (compact, archived by snapshot_store). **Consumers:** see
Phase 4 — none with authority.

## Phase 4 — consumer map (grep-verified)
| Brain field / block | Consumer | Purpose | Class |
|---|---|---|---|
| `snapshot["ai_brain"]` | `ai_brain/divergence.py:36` | compare vs wrapper, classify, log | OBSERVE/REPORTING |
| `snapshot["ai_brain"]` | `snapshot_store.py:70` | archive | REPORTING |
| `snapshot["ai_divergence"]` | `snapshot_store.py:71` | archive | REPORTING |
| brain output fields | — anywhere else | — | none |

**Only two readers of `snapshot["ai_brain"]`: divergence + snapshot_store.** No
generation/qualification/playbook/toolbox/gate/risk/execution module reads it
(grep over those packages: NONE).

## Phase 5 — authority audit (grep evidence, not inference)
| Category | Brain influence? | Evidence |
|---|---|---|
| generation | **NO** | no producer reads ai_brain output |
| qualification | **NO** | qualification runs before brain; no read |
| playbook selection | **NO** | playbook_classifier: no ai_brain read |
| toolbox selection | **NO** | toolbox_engine: no ai_brain read |
| gate approval | **NO** | execution_gate: no ai_brain reference (grep NONE) |
| risk | **NO** | risk_governor: no ai_brain reference |
| execution | **NO** | execution_engine: no ai_brain reference |
| broker exposure | **NO** | position/broker: no ai_brain reference |
| order placement | **NO** | order_builder/paper_broker: no ai_brain reference |

## Phase 6 — hidden path audit
`narrative_direction` appears in `ai_retrieval/{embedding,retrieval,backfill,
memory_schema}.py`, `scan_loop.py:299`, `trade_journal.py:215` — **all are
NA-1 (`narrative_authority`) or memory-record fields, NOT the Brain's output.**
Verified: embedding/retrieval read `narrative_context.narrative_direction` (memory
records) or `narrative_authority.narrative_direction`; scan_loop:299 prints the
NA line; trade_journal:215 stores `narrative_authority` at entry. **No
undocumented Brain consumer, no legacy/debug/bypass consumer.** Identical
consumer set to MAP-2.

## Phase 7 — taint guard verification
- **Insertion:** `narrative_brain.py:30` import; `:243` `scan_payload_taint(brain_input)`.
- **Execution:** computed BEFORE any LLM call. Control flow:
  `if _llm_enabled() and not taint_clean:` → contaminated branch (`source=
  contaminated_input`, **no `_call_llm`**, logged) → `elif _llm_enabled():` →
  `_call_llm` (only reached when clean) → `else:` deterministic.
- **Can contaminated input reach GPT?** **No** — the LLM call (`:252`) is in the
  `elif` reached only when `taint_clean` is True. **Can it bypass the guard?**
  No — the guard runs unconditionally before the branch. The repair call (`:269`)
  is inside the clean-success branch only.

## Phase 8 — end-to-end wiring diagram
```
Market data ─► engines (structure/liquidity/vol/expansion/po3)
                 │
   ┌─────────────┼───────────────────────────────┐
   ▼             ▼                                 ▼
 delivery     liquidity + protected swings     STRUCTURE (engine)
 (clean)      + active draw (clean)                 │ bias/state
   │             │                                  │ (DROPPED at H2)
   └──► build_brain_input ◄── stance memory ◄── ai_retrieval analogs
                 │                                  │ non-directional
                 │                         STRUCTURE_WITNESS (levels/events)
                 ▼
         TAINT GUARD ──contaminated──► deterministic fallback (logged)
                 │ clean
                 ▼
              GPT (LLM Brain)
                 ▼
        normalize → repair → output (31 fields)
                 ▼
   ┌─────────────┴─────────────┐
   ▼                           ▼
 divergence (compare/log)   snapshot_store (archive)      ← DEAD-END (observe)
   │
   └─► NO authority / generation / gate / execution lane
```
Witness lane: STRUCTURE_WITNESS (non-directional). Retrieval lane: ai_retrieval→
memory_matches. Memory lane: StanceMemory→stance_history. **Authority lane:
none. Execution lane: none.**

## Phase 9 — MAP-2 → MAP-3 diff
- **H2 removals:** `structure_WITNESS.bias`, directional `state`, and directional
  governance fields (narrative_authority_direction/forbidden, council_dominant)
  removed from the LLM payload.
- **H2 additions:** non-directional `STRUCTURE_WITNESS` (+disclaimer); prompt
  safety contract; `scan_payload_taint` guard; `source="contaminated_input"`
  path; H1 normalize/repair fields in the persisted record.
- **Consumer changes:** none — still divergence + snapshot_store only.
- **Authority changes:** none — still observe-only.

## Phase 10 — classification
**B — Narrative Intelligence Layer, operating in REPORTING/OBSERVE mode.** It
performs genuine market-narrative synthesis (delivery/liquidity/protected/
retrieval → direction/phase/draw/invalidation/forbidden), which is more than a
Reporting Engine (A); but its OUTPUT is consumed only by divergence-logging and
archival, so it has none of (C) decision-support wiring, (D) authority, or (E)
execution. Capability = B; consumption = reporting-only.

## Final questions
1. **Wired correctly?** Yes — clean inputs, observe-only, no authority leak.
2. **Clean?** Yes.
3. **Structure-derived directional contamination remain?** No — taint guard
   passes; structure isolated to non-directional witness.
4. **Hidden authority?** No — only divergence + snapshot_store read it.
5. **Hidden execution influence?** No — no execution/gate/risk module references it.
6. **Undocumented consumers?** No — the narrative_direction grep hits are NA-1/
   memory records, not the Brain.
7. **MAP-3 cleaner than MAP-2?** Yes — H2 closed the structure-summary input
   leak (the AB-5A-S defect); consumption unchanged (still observe-only).
8. **Exact current role:** an observe-only Narrative Intelligence Layer —
   produces a clean, machine-readable market narrative, persisted and compared to
   the legacy wrapper via divergence, consumed by no decision path.
9. **Next logical phase:** AB-5B — a GATED, observe→enforce authority trial of
   the safest-first authority (Brain VETO at the gate), behind a flag, measured
   on the divergence corpus. NOT started here (per directive).

STOP — audit only. No authority, no AB-5B, no generation/execution changes.
