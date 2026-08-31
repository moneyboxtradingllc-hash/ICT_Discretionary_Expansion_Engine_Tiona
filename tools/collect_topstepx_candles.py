"""Accumulate Topstep-native MNQ 1m candles.

    python tools/collect_topstepx_candles.py [--hours N]

Runs the TopstepXDataProvider and lets it fill its rolling cache one candle per
minute of market time. Candles persist to data/market_data/topstepx/ and reload
on restart, so warm-up accrues across sessions rather than restarting from zero.

READ-ONLY. It resolves a contract, subscribes to quotes and trades, and writes
candle files. It holds no order path and cannot place, cancel or close anything.

Progress is mirrored to data/market_data/topstepx/collector_status.json so the
count can be checked without interrupting the run.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src"))

from dotenv import load_dotenv

load_dotenv()

from data_feed import get_provider                      # noqa: E402
from data_feed.provider_interface import DataFeedError   # noqa: E402

WARMUP_TARGET = int(os.getenv("SCAN_LOOKBACK_BARS", "300"))


def status_path(provider) -> str:
    return os.path.join(provider.store_dir, "collector_status.json")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--hours", type=float, default=6.0)
    ap.add_argument("--report-every", type=float, default=60.0)
    a = ap.parse_args(argv)

    os.environ.setdefault("DATA_PROVIDER", "topstepx")
    provider = get_provider("topstepx")
    d = provider.describe()
    print("=" * 74)
    print("TOPSTEPX CANDLE COLLECTOR — read-only, no order path")
    print("=" * 74)
    print(f"provider  : {d['provider']}  source={d['source']}")
    print(f"contract  : {d['contract_id']} ({d['contract_name']})  tick={d['tick_size']}")
    print(f"reloaded  : {d['closed_candles']} candle(s) from previous sessions")
    print(f"target    : {WARMUP_TARGET} candles for engine warm-up")
    print("-" * 74)

    deadline = time.time() + a.hours * 3600
    last_report = 0.0
    try:
        while time.time() < deadline:
            time.sleep(2.0)
            if time.time() - last_report < a.report_every:
                continue
            last_report = time.time()
            d = provider.describe()
            n = d["closed_candles"]
            dev = d["developing"] or {}
            now_et = datetime.now(timezone.utc).astimezone(timezone(timedelta(hours=-4)))
            print(f"[{now_et:%H:%M:%S} ET] candles={n:4d}/{WARMUP_TARGET} "
                  f"remaining={max(WARMUP_TARGET - n, 0):4d}  "
                  f"forming={dev.get('timestamp', '-')} "
                  f"c={dev.get('close', '-')} v={dev.get('volume', '-')}  "
                  f"age={d['feed_age_seconds']:.1f}s stale={d['stale']}"
                  if d["feed_age_seconds"] is not None else
                  f"[{now_et:%H:%M:%S} ET] candles={n} (no feed events yet)")
            try:
                os.makedirs(provider.store_dir, exist_ok=True)
                with open(status_path(provider), "w", encoding="utf-8") as fh:
                    json.dump({"updated_utc": datetime.now(timezone.utc).isoformat(),
                               "candles_collected": n,
                               "warmup_target": WARMUP_TARGET,
                               "remaining": max(WARMUP_TARGET - n, 0),
                               "source": d["source"], "contract": d["contract_id"],
                               "feed_age_seconds": d["feed_age_seconds"],
                               "stale": d["stale"], "diagnostics": d["diagnostics"]},
                              fh, indent=2)
            except OSError:
                pass
    except KeyboardInterrupt:
        print("\ninterrupted by operator")
    finally:
        d = provider.describe()
        print("-" * 74)
        print(f"collected {d['closed_candles']} candle(s); "
              f"{max(WARMUP_TARGET - d['closed_candles'], 0)} short of warm-up")
        print(f"persisted to {provider.store_dir}")
        provider.stop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
