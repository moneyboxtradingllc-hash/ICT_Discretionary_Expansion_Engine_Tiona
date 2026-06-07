from datetime import datetime


def _floor_timestamp(ts_str: str, n_minutes: int) -> str:
    """Return the ISO 8601 bucket start for ts_str rounded down to n_minutes."""
    if ts_str.endswith("Z"):
        ts_str = ts_str[:-1] + "+00:00"
    dt = datetime.fromisoformat(ts_str)
    total = dt.hour * 60 + dt.minute
    floored = (total // n_minutes) * n_minutes
    bucket = dt.replace(
        hour=floored // 60,
        minute=floored % 60,
        second=0,
        microsecond=0,
    )
    return bucket.isoformat()


def _aggregate(candles_1m: list, n_minutes: int) -> list:
    """
    Aggregate sorted 1m candles into n_minutes candles using floor bucketing.
    Incomplete trailing buckets are included — live scanning benefits from
    seeing the current in-progress bar rather than waiting for its close.
    """
    if not candles_1m:
        return []

    buckets: dict = {}
    order: list   = []

    for c in candles_1m:
        key = _floor_timestamp(c["timestamp"], n_minutes)
        if key not in buckets:
            buckets[key] = []
            order.append(key)
        buckets[key].append(c)

    result = []
    for key in order:
        bars = buckets[key]
        result.append({
            "timestamp": key,
            "open":      bars[0]["open"],
            "high":      max(b["high"]   for b in bars),
            "low":       min(b["low"]    for b in bars),
            "close":     bars[-1]["close"],
            "volume":    sum(b["volume"] for b in bars),
        })

    return result


def build_timeframes(candles_1m: list) -> dict:
    """
    Return a raw_data dict compatible with build_snapshot().
    Input: list of normalized 1m candle dicts (oldest first).
    Output: {"1m": [...], "3m": [...], "5m": [...], "15m": [...]}
    """
    return {
        "1m":  candles_1m,
        "3m":  _aggregate(candles_1m, 3),
        "5m":  _aggregate(candles_1m, 5),
        "15m": _aggregate(candles_1m, 15),
    }
