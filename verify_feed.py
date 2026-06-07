"""
Phase 1O.5 -- Alpaca Connectivity Verification

Standalone diagnostic script.
No execution. No orders. No broker actions. Data read only.

Run from the project root:
    python verify_feed.py
"""
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "src"))

from dotenv import load_dotenv
load_dotenv()

_DIVIDER_WIDE  = "=" * 60
_DIVIDER_THIN  = "-" * 60
_LOOKBACK_BARS = 300  # matches SCAN_LOOKBACK_BARS default


def _mask(val: str) -> str:
    if not val:
        return "(empty)"
    return val[:8] + "***" if len(val) > 8 else "***"


def _check(label: str, passed: bool, detail: str = ""):
    status = "OK " if passed else "FAIL"
    suffix = f"  -- {detail}" if detail else ""
    print(f"  [{status}]  {label}{suffix}")
    return passed


def _section(title: str):
    print()
    print(_DIVIDER_THIN)
    print(title)
    print(_DIVIDER_THIN)


def main():
    sys.stdout.reconfigure(encoding="utf-8")

    all_passed = True

    print(_DIVIDER_WIDE)
    print("Phase 1O.5 -- Alpaca Connectivity Verification")
    print(_DIVIDER_WIDE)

    # ── [1] Credentials ───────────────────────────────────────────
    _section("[1] Credentials")

    api_key    = os.getenv("ALPACA_API_KEY",    "").strip()
    secret_key = os.getenv("ALPACA_SECRET_KEY", "").strip()
    symbol     = os.getenv("SCAN_SYMBOL",       "QQQ")
    provider   = os.getenv("DATA_PROVIDER",     "alpaca")

    print(f"  ALPACA_API_KEY    : {_mask(api_key)}")
    print(f"  ALPACA_SECRET_KEY : {_mask(secret_key)}")
    print(f"  DATA_PROVIDER     : {provider}")
    print(f"  SCAN_SYMBOL       : {symbol}")

    creds_ok = bool(api_key and secret_key)
    all_passed &= _check("Credentials present", creds_ok,
                         "both API_KEY and SECRET_KEY found" if creds_ok
                         else "missing ALPACA_API_KEY or ALPACA_SECRET_KEY in .env")

    if not creds_ok:
        _print_summary(symbol, False, None, None, None, False)
        return

    # ── [2] Provider Init ─────────────────────────────────────────
    _section("[2] Provider Initialization")

    try:
        from data_feed.alpaca_provider import AlpacaProvider
        ap = AlpacaProvider()
        all_passed &= _check("AlpacaProvider init", True)
    except Exception as exc:
        all_passed &= _check("AlpacaProvider init", False, str(exc))
        _print_summary(symbol, False, None, None, None, False)
        return

    # ── [3] Fetch 1m bars ─────────────────────────────────────────
    _section(f"[3] Fetching {symbol} 1m bars  (lookback: {_LOOKBACK_BARS})")

    candles_1m = None
    try:
        candles_1m = ap.fetch_1m_candles(symbol, _LOOKBACK_BARS)
        bar_count  = len(candles_1m)
        fetch_ok   = bar_count > 0
        all_passed &= _check(
            "Bars returned",
            fetch_ok,
            f"{bar_count} bars" if fetch_ok else "0 bars — market closed or feed unavailable",
        )
    except Exception as exc:
        all_passed &= _check("Bars returned", False, str(exc))
        _print_summary(symbol, False, None, None, None, False)
        return

    if not candles_1m:
        _print_summary(symbol, False, 0, None, None, False)
        return

    latest     = candles_1m[-1]
    latest_ts  = latest.get("timestamp", "?")
    latest_cls = latest.get("close")

    print(f"  Bars received     : {bar_count}")
    print(f"  Latest timestamp  : {latest_ts}")
    print(f"  Latest close      : {latest_cls}")

    # ── [4] Candle Contract Validation ────────────────────────────
    _section("[4] Candle Contract Check")

    required_fields = ("timestamp", "open", "high", "low", "close", "volume")
    type_map        = {"timestamp": str, "open": float, "high": float,
                       "low": float, "close": float, "volume": float}

    sample      = candles_1m[-1]
    fields_ok   = all(f in sample for f in required_fields)
    all_passed &= _check(
        "Required fields present",
        fields_ok,
        ", ".join(required_fields) if fields_ok else
        "missing: " + ", ".join(f for f in required_fields if f not in sample),
    )

    types_ok = all(isinstance(sample.get(f), t) for f, t in type_map.items())
    all_passed &= _check(
        "Field types correct",
        types_ok,
        "timestamp=str, OHLCV=float" if types_ok else
        "type mismatch: " + ", ".join(
            f"{f}={type(sample.get(f)).__name__}" for f, t in type_map.items()
            if not isinstance(sample.get(f), t)
        ),
    )

    o, h, l, c = (sample.get(k, 0) for k in ("open", "high", "low", "close"))
    ohlcv_ok = (h >= l) and (h >= o) and (h >= c) and (l <= o) and (l <= c)
    all_passed &= _check("OHLCV sanity  (high >= low, OHLC in range)", ohlcv_ok)

    ts_parseable = False
    try:
        from datetime import datetime
        ts_str = sample["timestamp"]
        if ts_str.endswith("Z"):
            ts_str = ts_str[:-1] + "+00:00"
        datetime.fromisoformat(ts_str)
        ts_parseable = True
    except Exception:
        pass
    all_passed &= _check("Timestamp parseable by datetime.fromisoformat", ts_parseable)

    # ── [5] Timeframe Builder ─────────────────────────────────────
    _section("[5] Timeframe Builder  (1m -> 3m / 5m / 15m)")

    tf_ok = False
    try:
        from data_feed.timeframe_builder import build_timeframes
        raw_data  = build_timeframes(candles_1m)
        tf_counts = {tf: len(raw_data.get(tf, [])) for tf in ("1m", "3m", "5m", "15m")}

        for tf, n in tf_counts.items():
            ok = n > 0
            all_passed &= _check(f"{tf:>3} bars built", ok, f"{n} bars")

        tf_ok = all(n > 0 for n in tf_counts.values())
    except Exception as exc:
        all_passed &= _check("build_timeframes", False, str(exc))

    # ── Summary ───────────────────────────────────────────────────
    _print_summary(symbol, True, bar_count, latest_ts, latest_cls, tf_ok, all_passed)


def _print_summary(
    symbol, connected, bar_count, latest_ts, latest_cls, tf_ok, all_passed=None
):
    print()
    print(_DIVIDER_WIDE)
    print("RESULT")
    print(_DIVIDER_WIDE)

    yes_no = lambda v: "YES" if v else "NO"

    print(f"  Connection        : {yes_no(connected)}")
    print(f"  Symbol tested     : {symbol}")
    print(f"  Bars returned     : {bar_count if bar_count is not None else '--'}")
    print(f"  Latest timestamp  : {latest_ts if latest_ts else '--'}")
    print(f"  Latest close      : {latest_cls if latest_cls is not None else '--'}")
    print(f"  Timeframes OK     : {yes_no(tf_ok)}")

    if all_passed is not None:
        verdict = "PASS -- feed ready for Phase 1P" if all_passed else "FAIL -- resolve errors above before Phase 1P"
        print(f"  Overall           : {verdict}")

    print(_DIVIDER_WIDE)


if __name__ == "__main__":
    main()
