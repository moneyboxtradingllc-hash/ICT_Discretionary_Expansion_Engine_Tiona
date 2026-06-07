MIN_CANDLES = 5
TREND_LOOKBACK = 3   # candles back to compare for ATR trend
TREND_THRESHOLD = 0.08  # 8% change to call rising/falling


def _true_ranges(candles: list) -> list:
    trs = []
    for i in range(1, len(candles)):
        h = candles[i]["high"]
        l = candles[i]["low"]
        prev_c = candles[i - 1]["close"]
        trs.append(max(h - l, abs(h - prev_c), abs(l - prev_c)))
    return trs


def _sma_atr(candles: list, period: int) -> float:
    usable = min(period, len(candles) - 1)
    if usable < 1:
        return 0.0
    trs = _true_ranges(candles[-(usable + 1):])
    return sum(trs) / len(trs) if trs else 0.0


def calculate_atr(candles: list, period: int = 14) -> dict:
    if len(candles) < MIN_CANDLES:
        return {"atr": None, "atr_trend": "unknown"}

    current_atr = _sma_atr(candles, period)

    atr_trend = "stable"
    if len(candles) >= period + 1 + TREND_LOOKBACK:
        prior_atr = _sma_atr(candles[:-TREND_LOOKBACK], period)
        if prior_atr > 0:
            change = (current_atr - prior_atr) / prior_atr
            if change > TREND_THRESHOLD:
                atr_trend = "rising"
            elif change < -TREND_THRESHOLD:
                atr_trend = "falling"

    return {
        "atr": round(current_atr, 2),
        "atr_trend": atr_trend,
    }
