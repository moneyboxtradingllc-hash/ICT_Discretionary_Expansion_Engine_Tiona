"""
DEPLOY-2C — Topstep runtime scan loop (Alpaca-free).

Tiona's Topstep path does NOT reuse Maurice's run_scan_loop (whose execution block
is Alpaca-paper specific). Instead it runs a lean cycle:

    fetch MNQU (Topstep provider) -> build_snapshot (full analysis: structure,
    liquidity, volatility, expansion, PO3, ECU Brain, qualification, playbook,
    risk, toolbox, adaptive context/friction/interpretation)
    -> TopstepRuntime.run_cycle (observe / propose / optional practice entry /
       read-only reconcile)
    -> save snapshot -> sleep

It imports NO Alpaca module and calls NO paper_execution reconciliation. Execution
is OFF by default (observe). Never raises out of the loop.
"""
import os
import time

from data_feed import get_provider
from data_feed.provider_interface import DataFeedError
from data_feed.timeframe_builder import build_timeframes
from market_data.snapshot_builder import build_snapshot
from state.market_memory import MarketMemory
from structure.po3_alignment_manager import Po3StabilityManager   # VECTOR-3
from broker.runtime import get_runtime


def run_topstep_scan_loop(symbol: str = "MNQU", data_provider: str = "topstep",
                          config=None):
    lookback = int(os.getenv("SCAN_LOOKBACK_BARS", "300"))
    interval = int(os.getenv("SCAN_INTERVAL_SECONDS", "60"))
    max_iter = int(os.getenv("MAX_SCAN_ITERATIONS", "0"))

    # Data provider (Topstep). Fails clearly; never falls back to Alpaca.
    try:
        provider = get_provider(data_provider)
    except DataFeedError as exc:
        print(f"[TOPSTEP SCAN LOOP ERROR] cannot initialise data provider: {exc}")
        return

    runtime = get_runtime("topstep", symbol, config)
    memory = MarketMemory(max_snapshots=20)
    po3_stability = Po3StabilityManager()

    print(f"[topstep] scan loop start | symbol={symbol} provider={data_provider} "
          f"execution={'ENABLED' if runtime.is_execution_enabled() else 'OBSERVE (default)'} "
          f"practice_only={os.getenv('TOPSTEP_PRACTICE_ONLY', 'true')}")

    scan = 0
    while True:
        scan += 1
        try:
            candles = provider.fetch_1m_candles(symbol, lookback)
            raw = build_timeframes(candles)
            snapshot = build_snapshot(raw, memory=memory, symbol=symbol,
                                      po3_stability=po3_stability)
            snapshot["topstep_runtime"] = runtime.run_cycle(snapshot, symbol)
            tr = snapshot["topstep_runtime"]
            print(f"  [topstep #{scan}] mode={tr['mode']} acct_ok={tr['account_ok']} "
                  f"practice_safe={tr['practice_safe']} "
                  f"decision={tr['decision'].get('direction')} "
                  f"order={tr['order_action']} ({tr['order_result'].get('reason', '')})")
        except DataFeedError as exc:
            print(f"  [topstep #{scan}] DATA ERROR: {exc}")
        except Exception as exc:  # noqa: BLE001
            print(f"  [topstep #{scan}] ERROR: {type(exc).__name__}: {exc}")

        if max_iter and scan >= max_iter:
            break
        if interval > 0:
            time.sleep(interval)
