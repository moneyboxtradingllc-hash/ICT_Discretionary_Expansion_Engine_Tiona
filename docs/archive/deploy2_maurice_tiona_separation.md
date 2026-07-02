# DEPLOY-2 — Instance Separation Audit: Maurice (Alpaca/QQQ) vs Tiona (Topstep)

**Verdict up front: SEPARATION CLEAN. No defect found → no core code changed.**
Maurice stays exactly Alpaca/QQQ on his existing state; Tiona is a fresh,
fully-isolated Topstep instance starting from zero. Zero shared writable paths.
Regression **1083 passed** (+7 DEPLOY-2 safety tests).

What this audit added (deployment artifacts only, no core code): one tracked
template `instances/templates/topstep_150k.yaml`, two **local** instance configs
(`data/instances/maurice_alpaca/`, `data/instances/tiona_topstep/` — git-ignored),
and `tests/test_phase_deploy2_maurice_tiona_separation.py`.

## Phase 1 — Maurice instance audit
Maurice was the legacy single-project bot (no `data/instances/` existed). He is
now **formalized** as instance `maurice_alpaca` whose isolated paths point at his
**existing legacy `data/` directories** — nothing copied, moved, or overwritten;
his memory/vector/journal are preserved exactly in place.

| Field | Value |
|---|---|
| instance_id | `maurice_alpaca` |
| broker | **paper** (= Alpaca paper endpoint; `paper_broker` refuses non-paper URLs) |
| symbol / instrument | **QQQ** (`SCAN_SYMBOL=QQQ`) |
| execution_mode | **paper** (`PAPER_TRADING_ONLY=true`, `ALPACA_BASE_URL=https://paper-api.alpaca.markets`) |
| account_id | `alpaca_paper` |

Exact paths (all his existing, populated stores — file counts at audit time):
| Subsystem (env) | Path | Files |
|---|---|---|
| AI_BRAIN_DIR (memory) | `data/ai_brain` | 68 |
| AI_RETRIEVAL_DIR (vector) | `data/ai_retrieval` | 1 |
| PAPER_TRADES_DIR (journal) | `data/paper_trades` | 6 |
| LIVE_SNAPSHOTS_DIR (logs) | `data/live_snapshots` | 1548 |
| INTENT_ARCHIVE_DIR | `data/intent_archive` | 9 |
| ACTIVATION_REPORTS_DIR | `data/activation_reports` | 8 |
| RULE_GOVERNANCE_DIR | `data/rule_governance` | 3 |
| AI_SHADOW_DIR | `data/ai_shadow` | (unused) |
| NEWS_MEMORY_DIR | `data/news` | 3 |
| OPS_DIR (state) | `data/ops` | 4 |

**No Topstep fields exist in Maurice's config.** Alpaca credential path
(`.env` → `ALPACA_BASE_URL` paper) unchanged.

## Phase 2 — Tiona instance (did not exist → created fresh)
`tiona_topstep` did not exist. Created from `topstep_150k` template. **No Maurice
data copied.** All stores newly initialized and **empty (0 files)**.

| Field | Value |
|---|---|
| instance_id | `tiona_topstep` |
| broker | **topstep** (adapter is a **stub** — see Phase 4) |
| account_type | `practice_150k` |
| account_id | `TIONA-TS-150K-PRACTICE` |
| symbol | QQQ (template default; change in config if Tiona trades a different instrument) |
| execution_mode | paper |

Tiona paths (all under `data/instances/tiona_topstep/`, all 0 files at creation):
`memory/ai_brain`, `vector_store`, `journal`, `logs/live_snapshots`,
`memory/intent_archive`, `logs/activation_reports`, `memory/rule_governance`,
`memory/ai_shadow`, `news_memory`, `state`.

## Phase 3 — Cross-contamination check
| Subsystem | Maurice | Tiona | Differ? |
|---|---|---|---|
| memory (brain) | `data/ai_brain` | `data/instances/tiona_topstep/memory/ai_brain` | ✅ |
| vector store | `data/ai_retrieval` | `data/instances/tiona_topstep/vector_store` | ✅ |
| journal | `data/paper_trades` | `data/instances/tiona_topstep/journal` | ✅ |
| logs (snapshots) | `data/live_snapshots` | `data/instances/tiona_topstep/logs/live_snapshots` | ✅ |
| state (ops) | `data/ops` | `data/instances/tiona_topstep/state` | ✅ |
| news memory | `data/news` | `data/instances/tiona_topstep/news_memory` | ✅ |
| account_id | `alpaca_paper` | `TIONA-TS-150K-PRACTICE` | ✅ |
| broker adapter | paper (Alpaca) | topstep (stub) | ✅ |

**Shared writable paths between the two instances: NONE** (verified live). The
only intentionally-shared store is global market memory (`data/global_memory/`),
which holds broad lessons only and rejects instance-scoped data.

## Phase 4 — Launch plan (exact commands)
**Maurice** — his existing launcher remains his operational path (it sets all his
FC execution flags). The instance command is also available:
```
# operational (unchanged, sets his full FC env): 
powershell -File launch_paper_session_fc.ps1
# instance-abstraction equivalent (loads only his config + existing state):
python run_instance.py --instance maurice_alpaca --start
```
> Note: `run_instance.py --start` activates Maurice's paths and runs the paper
> scan loop, but does NOT replicate the execution-flag env his `.ps1` sets — for
> live paper sessions Maurice should keep using `launch_paper_session_fc.ps1`.
> The paper adapter is real: `supports_orders=True` once Alpaca env is loaded
> (`connected` reflects `ALPACA_BASE_URL`).

**Tiona**:
```
python run_instance.py --instance tiona_topstep --start
```
**The Tiona Topstep adapter is a STUB.** `is_connected()==False`,
`supports_orders==False`, and `submit_order()` raises `NotConnectedError`.
`run_instance.py --start` will **refuse** to trade Tiona (guard: only a connected
paper adapter may start). Tiona **cannot submit orders** — no pretense otherwise.
She can run the scan/brain/journal pipeline in isolation, but execution awaits a
real Topstep integration in a future, explicitly-authorized phase.

## Phase 5 — Safety tests (`tests/test_phase_deploy2_*`, 7 tests / 9 properties)
Built reproducibly from the committed templates in a temp dir (never touches the
real stores). All green:
1. Maurice writes land in Maurice's store (journal resolves to his path, not Tiona's). ✅
2. Tiona writes go to Tiona only. ✅
3. Maurice vector records invisible to Tiona. ✅
4. Tiona vector records invisible to Maurice. ✅
5. Maurice journal byte-unchanged after Tiona activity. ✅
6. Tiona journal starts empty. ✅
7. Maurice broker = paper (Alpaca paper, paper-only). ✅
8. Tiona broker = topstep (stub; `submit_order` raises). ✅
9. No shared account state / writable paths. ✅

## Phase 6 — Final verdict
1. **Is Maurice still Alpaca / QQQ?** **Yes** — broker paper (Alpaca paper),
   symbol QQQ, execution paper.
2. **Is Maurice's existing memory preserved?** **Yes** — his instance points at
   the existing `data/` stores (ai_brain 68 files, journal 6, snapshots 1548, …);
   nothing copied/moved/overwritten.
3. **Is Maurice untouched by Tiona setup?** **Yes** — no shared paths; the safety
   test proves his journal is byte-identical after Tiona writes.
4. **Is Tiona fresh?** **Yes** — every store created empty (0 files), no inherited
   Maurice data.
5. **Is Tiona isolated?** **Yes** — all state under `data/instances/tiona_topstep/`;
   zero overlap with Maurice.
6. **Can both be launched separately?** **Yes** — distinct instance_ids/configs;
   each launch loads only its own config + state.
7. **Is any Topstep execution adapter still stubbed?** **Yes** — Tiona's Topstep
   adapter is a stub; it cannot submit orders (no live money).
8. **Exact launch commands?**
   - Maurice: `python run_instance.py --instance maurice_alpaca --start`
     (or his existing `launch_paper_session_fc.ps1`).
   - Tiona: `python run_instance.py --instance tiona_topstep --start`
     (refused at execution — Topstep stub).

## Deliverables
instance separation report ✓ · Maurice config summary ✓ · Tiona config summary
(created) ✓ · path comparison table ✓ · launch commands ✓ · safety tests (7/9
properties) + regression (1083) ✓. **No separation defect → no core code change.
No live account connection changes.** STOP after the audit.
