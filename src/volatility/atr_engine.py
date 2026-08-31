MIN_CANDLES = 5
TREND_LOOKBACK = 3   # candles back to compare for ATR trend
TREND_THRESHOLD = 0.08  # 8% change to call rising/falling
DEFAULT_PERIOD = 14


def atr_source_window(candles: list, period: int = DEFAULT_PERIOD) -> list:
    """The EXACT candles `calculate_atr` averaged. STEP 3D.

    A magnitude witness publishes `body / atr = 1.52`. The NUMERATOR rests on
    one candle; the DENOMINATOR rests on this window. Naming only the anchor as
    the witness's evidence claimed half a proposition -- repair any bar in here
    and the ratio moves, which is exactly what the anchor-time audit measured
    (the same 16:00 body read 1.52x, 1.59x and 1.60x as ATR drifted).

    ONE OWNER. The slicing rule is `_sma_atr`'s and is not restated elsewhere:
    `usable = min(period, len-1)`, then `candles[-(usable + 1):]`. The extra
    OLDER bar is not an off-by-one -- true range needs the PREVIOUS close, so
    that bar really is evidence even though it contributes no TR of its own.

    Returns [] when `calculate_atr` would refuse to produce an ATR at all, so a
    caller can never attach a source window to a number that does not exist.
    """
    if not candles or len(candles) < MIN_CANDLES:
        return []
    usable = min(period, len(candles) - 1)
    if usable < 1:
        return []
    return list(candles[-(usable + 1):])


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
