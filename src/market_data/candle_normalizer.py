def normalize_candle(raw: dict, session_label: str) -> dict:
    o = raw["open"]
    h = raw["high"]
    l = raw["low"]
    c = raw["close"]
    v = raw.get("volume", 0)

    body_top = max(o, c)
    body_bottom = min(o, c)

    return {
        "timestamp": raw["timestamp"],
        "open": o,
        "high": h,
        "low": l,
        "close": c,
        "volume": v,
        "range": round(h - l, 2),
        "body_size": round(body_top - body_bottom, 2),
        "upper_wick": round(h - body_top, 2),
        "lower_wick": round(body_bottom - l, 2),
        "direction": "bullish" if c > o else "bearish" if c < o else "neutral",
        "session_label": session_label,
    }


def normalize_candles(raw_candles: list, session_fn) -> list:
    return [normalize_candle(c, session_fn(c["timestamp"])) for c in raw_candles]
