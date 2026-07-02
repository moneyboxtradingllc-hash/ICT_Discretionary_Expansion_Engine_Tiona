# DECON-1 — Topstep Purge (Mainline is TradeStation-only)

Date: 2026-07-02

## Doctrine

The mainline bot was never designed for Topstep. Topstep belongs to Tiona's
separate bot, in its own repository. Every Topstep runtime, adapter, scan loop,
env flag, entry store, test fixture, and state file in this repo was
architectural contamination and has been removed — not unified, not made
dormant, not kept "just in case."

Mainline broker surface after DECON-1: `paper` (Alpaca paper, the live QQQ
path) + `tradestation` (stub adapter, the designated live-money path).

## Removed — production code

- `src/broker/topstep_adapter.py` (ProjectX adapter)
- `src/broker/topstep_entry_store.py` (Topstep entry-context store)
- `src/broker/runtime.py` (DEPLOY-2C runtime split — existed solely to host
  `TopstepRuntime`; its `AlpacaPaperRuntime` wrappers had zero production
  consumers)
- `src/data_feed/topstep_provider.py` (ProjectX bars provider)
- `src/live_scan/topstep_scan_loop.py` (Topstep scan loop)
- Topstep branches removed from: `src/broker/factory.py`,
  `src/broker/__init__.py`, `src/data_feed/__init__.py`,
  `src/deployment/instance_config.py`, `run_instance.py`,
  `src/live_scan/scan_loop.py` (comment), `tools/create_instance.py` (usage)

## Removed — tests

- `tests/test_phase_topstep1_adapter.py`
- `tests/test_phase_deploy2_topstep_data_feed.py`
- `tests/test_phase_deploy2c_topstep_execution.py`
- `tests/test_phase_deploy2d_topstep_lifecycle.py`
- `tests/test_phase_deploy2_maurice_tiona_separation.py`
- `tests/test_phase_deploy1_multi_instance.py`: Topstep broker cases retargeted
  to `tradestation` (no mainline coverage weakened)
- `tests/test_adaptive7_live_size_enforcement.py`: obsolete
  `TestBrokerRuntimeUntouched` guard removed (its guard target,
  `broker/runtime.py`, no longer exists)

## Removed — config / env / launch / tools / state

- `.env`: TIONA TOPSTEP block (TOPSTEP_USERNAME/API_KEY/ACCOUNT_ID/ENV/
  BASE_URL/EXECUTION_ENABLED) deleted
- `.env.topstep.example` deleted; `.gitignore` un-exception removed
- `instances/templates/topstep_150k.yaml`, `topstep_50k.yaml` deleted
- `launch_tiona_topstep_practice.ps1` deleted
- `tools/test_topstep_connection.py`, `tools/topstepx_connection_report.py` deleted
- `data/topstep/` deleted (entry_context.jsonl contained only fake test
  entries — DECON: test pollution, no real trades)
- `data/instances/tiona_topstep/` deleted

## Archived — docs (historical record only)

- `docs/archive/tiona_topstep_setup_guide.md`
- `docs/archive/deploy2_maurice_tiona_separation.md`

## Result

`grep -RIn -i "topstep|projectx|tiona" src tests tools` → zero matches.
Mainline bot is TradeStation-only (Alpaca paper remains the paper spine).
