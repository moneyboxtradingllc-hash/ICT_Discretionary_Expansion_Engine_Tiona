# DEPLOY-1 — Cloneable Multi-Instance Architecture

Turns the single local project into a **cloneable, config-driven deployment
system**: one shared codebase (the bot's DNA), many independent instances, each
with its own memory, vector store, journal, logs, state, account, broker, and
risk profile. **Bot A never sees Bot B's memory or trades.**

Principle: **shared code · separate state · separate memory · separate execution
· separate learning.** Gated by being opt-in (no instance active ⇒ the single
project behaves exactly as before). Regression: 1034 → **1076 passed** (42 new
DEPLOY-1 + earlier NEWS-1 tests). No live money, no real accounts, no
client-facing automation — paper/stub only.

## Architecture mapping (spec → repo)
The spec's `shared_core/` is the existing **`src/`** (one codebase, not copied
per clone). The spec's `instances/<name>/{config,memory,…}` is realized under
**`data/instances/<instance_id>/`** (matches the Phase-5 explicit path
`data/instances/maurice_topstep/vector_store/`). Config **templates** live in
`instances/templates/` (tracked); per-instance state lives in
`data/instances/` (git-ignored — never committed).

```
src/                    ← SHARED CORE (ECU brain, playbooks, toolbox, validators,
                          news layer, execution framework)
  deployment/           ← NEW: instance config, runtime context, path isolation
  broker/               ← NEW: broker adapter abstraction (paper/topstep/tradestation)
instances/templates/    ← NEW: cloneable config templates (tracked)
tools/create_instance.py← NEW: clone command (Phase 8)
run_instance.py         ← NEW: launch command (Phase 9)
data/instances/<id>/    ← per-instance isolated state (git-ignored)
  config.yaml memory/ vector_store/ journal/ logs/ state/ news_memory/
```

## Phase 1 — Current-state audit (hardcoded global paths)
Two groups of stateful paths were found:

**(A) Already env-overridable** (isolation just sets the env var):
`AI_BRAIN_DIR` (stance/brain/divergence), `AI_RETRIEVAL_DIR` (vector store),
`RULE_GOVERNANCE_DIR`, `AI_SHADOW_DIR`, `NEWS_MEMORY_DIR`, `OPS_DIR`
(lock/heartbeat/state).

**(B) Hardcoded — the real contamination risks** (would make two instances
share state). Each was converted to read an env var with the **legacy default
preserved** (regression-safe; the constant remains as the patch-point existing
tests rely on):
| Module | Was | Now (env, default kept) |
|---|---|---|
| `paper_execution/trade_journal.py` | `data/paper_trades` (the JOURNAL) | `PAPER_TRADES_DIR` |
| `experience_intelligence/experience_query.py` | `data/paper_trades`, `data/intent_archive` | `PAPER_TRADES_DIR`, `INTENT_ARCHIVE_DIR` |
| `ai_retrieval/backfill.py` | `data/live_snapshots`, `data/paper_trades` | `LIVE_SNAPSHOTS_DIR`, `PAPER_TRADES_DIR` |
| `live_scan/snapshot_store.py` | `data/live_snapshots` | `LIVE_SNAPSHOTS_DIR` |
| `paper_activation/activation_report.py` | `data/activation_reports` | `ACTIVATION_REPORTS_DIR` |
| `operational_readiness/startup_authority.py` | `data/paper_trades` (writable probe) | `PAPER_TRADES_DIR` |

After this, **every** stateful subsystem resolves its directory through an env
var (inventory in `deployment/data_paths.SUBSYSTEM_ENV`), so one
`InstanceContext.activate()` redirects the entire state tree at once.

## Phase 2 — Instance config system (`deployment/instance_config.py`)
`InstanceConfig` defines instance_id, owner_name, broker, account_type,
account_id, symbol, contract_size, session_windows, execution_mode, a
`RiskProfile` (max_daily_loss, max_trades_per_day, risk_per_trade), the isolated
paths (memory/vector_store/journal/log/state/news_memory — auto-derived from
instance_id when omitted), and a `DivergenceConfig` (Phase 11). YAML
load/save/validate. `execution_mode: live` is **rejected** in DEPLOY-1.

## Phase 3 — Instance runtime context (`deployment/instance_context.py`)
`InstanceContext` is the one object that says *which instance is live and where
it may write*. `activate()` exports the instance's isolated paths into the
per-subsystem env vars (and `BOT_INSTANCE_ID`), `deactivate()`/context-manager
restores them. `current()` returns the active context. Because every state dir
is env-driven, activating an instance redirects **all** memory, vector, journal,
logs, state, and news memory into that instance's folder — **no module can then
write to a shared path.**

## Phase 4 — Memory isolation
`GLOBAL_MEMORY_DIR` (`data/global_memory/`) holds **broad market lessons only**;
`deployment/global_memory.record_lesson()` **rejects** any instance-scoped
payload (trade_id, account_id, pnl, stance_history, outcome, …). Everything
account-specific (trade/stance history, vector analogs, tool/playbook
preference learning, level/session/news-reaction history) lives in **instance
memory**, redirected per clone. Each clone has its own.

## Phase 5 — Vector store isolation
Each instance's `AI_RETRIEVAL_DIR` → `data/instances/<id>/vector_store/`. No
cross-instance retrieval (a clone only ever reads its own store) unless a future
config explicitly enables it.

## Phase 6 — Journal isolation
Each instance's `PAPER_TRADES_DIR` → `data/instances/<id>/journal/`. No shared
trade journal, performance stats, or account state — proven by the independence
test (A's trade `A1` is invisible to B and vice-versa).

## Phase 7 — Broker adapter layer (`src/broker/`)
`BrokerAdapter` ABC (get_account / get_position / submit_order / capability).
The core calls `get_adapter(config)`; it never imports a specific broker.
- **paper** — wraps the existing Alpaca paper broker (paper-only; refuses live URLs).
- **topstep**, **tradestation** — **stubs**: interface only, `is_connected()==False`,
  `submit_order()` raises `NotConnectedError` (DEPLOY-1 connects no live money).
Instance config's `broker` field selects the adapter; unknown ⇒ safe paper default.

## Phase 8 — Clone command (`tools/create_instance.py`)
```
python tools/create_instance.py --template topstep_50k --instance maurice_topstep \
    --owner "Maurice" --account-id TS-50K-001
```
Creates `data/instances/maurice_topstep/` with `config.yaml` + isolated
`memory/ vector_store/ journal/ logs/ state/ news_memory/`. Shared code is **not**
copied. Refuses to overwrite an existing instance.

## Phase 9 — Launch command (`run_instance.py`)
```
python run_instance.py --instance maurice_topstep
```
Loads **only** that instance's config + state, `activate()`s its context
(redirecting all writes), selects its broker adapter, prints the isolation map.
Default is a dry plan; `--start` begins the paper scan loop **only** for a
connected paper adapter (stub brokers are refused — no live money).

## Phase 10 — Independence test (`tests/test_phase_deploy1_multi_instance.py`)
Two instances `test_bot_a` / `test_bot_b`, same market input:
- separate journals — `append_trade("A1")` / `append_trade("B1")`; A's journal
  contains A1 not B1, B's contains B1 not A1. ✓
- separate vector stores / news memory / state dirs (no path overlap). ✓
- **modify Bot A memory ⇒ Bot B does not see it**: a NewsMemory record written
  under A returns 1 for A, **0** for B. ✓
- per-instance divergence config. ✓
All 15 DEPLOY-1 tests green; clone command builds an isolated tree carrying the
instance_id in every path.

## Phase 11 — Behavioral divergence support (`DivergenceConfig`)
Per-instance, **allowed not forced**: confidence_calibration, tool_preference_
weights, playbook_preference_weights, risk_profile, scan_cadence_seconds,
session_preference, allowed_playbooks, allowed_tools. Defaults are neutral
(calibration 1.0, all playbooks/tools allowed) so clones diverge only as their
separate memory/config evolve — no artificial divergence.

## Producer → Consumer map
```
InstanceConfig (yaml) ─► InstanceContext.activate()
                              │ sets env: AI_BRAIN_DIR, AI_RETRIEVAL_DIR,
                              │ PAPER_TRADES_DIR, LIVE_SNAPSHOTS_DIR, OPS_DIR,
                              │ NEWS_MEMORY_DIR, … (+ BOT_INSTANCE_ID)
                              ▼
   trade_journal · stance_memory · vector_store · news_memory · snapshot_store ·
   experience_query · backfill · activation_report · startup_authority · ops
                              │  (each resolves env → instance folder)
                              ▼
            data/instances/<id>/{journal,memory,vector_store,logs,state,news_memory}

   broker.factory.get_adapter(config) ─► Paper | Topstep(stub) | TradeStation(stub)
   global_memory (data/global_memory) ─► broad lessons only (instance-scoped rejected)
```

## Phase 12 — DEPLOY-1 audit
1. **Clone without rebuilding?** **Yes** — `create_instance.py` makes config +
   folders; code stays shared in `src/`.
2. **Isolated memory per clone?** **Yes** — `AI_BRAIN_DIR`/instance memory per id;
   global memory separated and guarded.
3. **Isolated vector search?** **Yes** — `AI_RETRIEVAL_DIR` per instance; no
   cross-instance retrieval.
4. **Isolated journal/state?** **Yes** — `PAPER_TRADES_DIR`/`OPS_DIR` per
   instance; independence test proves no leakage.
5. **Multiple brokers?** **Yes** — adapter layer + factory (paper live; topstep/
   tradestation stubs).
6. **Topstep & TradeStation from one core?** **Yes** — both are adapters selected
   by config; core is broker-agnostic.
7. **Two Topstep accounts as separate instances?** **Yes** — two instance_ids,
   two config.yaml, two isolated state trees, two account_ids.
8. **Can Bot A learn differently than Bot B?** **Yes** — separate memory/vector/
   journal + per-instance DivergenceConfig.
9. **Any shared-state contamination?** **No** — every state path is env-redirected
   per instance; the independence test asserts zero cross-visibility; global
   memory rejects instance-scoped data.
10. **Deployable multi-instance architecture now?** **Yes (foundation)** — clone +
    launch + isolation + adapters + tests, paper/stub only. Live broker
    connection and client automation are explicitly deferred.

## Acceptance criteria
One shared codebase ✓ · multiple independent instances ✓ · no accidental shared
memory ✓ · no accidental shared account state ✓ · no accidental shared journal ✓ ·
config-driven broker/account/risk ✓ · instance-specific learning ✓ · regression
passes (1076) ✓.

## Deliverables
instance config system ✓ · InstanceContext ✓ · isolated memory paths ✓ · isolated
vector stores ✓ · isolated journals ✓ · isolated logs ✓ · broker adapter
abstraction ✓ · clone command ✓ · launch command ✓ · independence tests ✓ ·
DEPLOY-1 audit ✓. **STOP after DEPLOY-1.** No real accounts, no live money, no
client-facing automation.
