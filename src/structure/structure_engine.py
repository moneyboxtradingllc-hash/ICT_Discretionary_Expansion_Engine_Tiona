MIN_CANDLES = 4


def find_swings(candles: list) -> tuple:
    """
    Returns (swing_highs, swing_lows) as ordered lists of price values.
    Lookback adapts to dataset size for short timeframes.
    """
    n = len(candles)
    lookback = 3 if n >= 10 else 2 if n >= 6 else 1

    highs, lows = [], []
    for i in range(lookback, n - lookback):
        h = candles[i]["high"]
        l = candles[i]["low"]

        if all(candles[i - j]["high"] < h for j in range(1, lookback + 1)) and \
           all(candles[i + j]["high"] < h for j in range(1, lookback + 1)):
            highs.append(h)

        if all(candles[i - j]["low"] > l for j in range(1, lookback + 1)) and \
           all(candles[i + j]["low"] > l for j in range(1, lookback + 1)):
            lows.append(l)

    return highs, lows


def _bias(highs: list, lows: list) -> str:
    if len(highs) >= 2 and len(lows) >= 2:
        if highs[-1] > highs[-2] and lows[-1] > lows[-2]:
            return "bullish"
        if highs[-1] < highs[-2] and lows[-1] < lows[-2]:
            return "bearish"
    return "neutral"


def analyze_structure(candles: list) -> dict:
    if len(candles) < MIN_CANDLES:
        return {
            "bias": "neutral",
            "state": "insufficient_data",
            "last_swing_high": None,
            "last_swing_low": None,
            "bos": False,
            "mss": False,
        }

    highs, lows = find_swings(candles)

    last_swing_high = round(highs[-1], 2) if highs else None
    last_swing_low = round(lows[-1], 2) if lows else None
    bias = _bias(highs, lows)
    last_close = candles[-1]["close"]

    # Break of Structure: price closes beyond the most recent swing point
    bos_bullish = last_swing_high is not None and last_close > last_swing_high
    bos_bearish = last_swing_low is not None and last_close < last_swing_low
    bos = bos_bullish or bos_bearish
    bos_dir = "bullish" if bos_bullish else "bearish" if bos_bearish else None

    # Market Structure Shift: BOS fires against the current structural bias
    mss = (bos and bias == "bearish" and bos_dir == "bullish") or \
          (bos and bias == "bullish" and bos_dir == "bearish")

    if mss:
        state = f"{bos_dir}_reversal"
    elif bos and bias == "bullish":
        state = "bullish_continuation"
    elif bos and bias == "bearish":
        state = "bearish_continuation"
    elif last_swing_high and last_swing_low and last_swing_low < last_close < last_swing_high:
        state = "range_bound"
    else:
        state = "neutral"

    return {
        "bias": bias,
        "state": state,
        "last_swing_high": last_swing_high,
        "last_swing_low": last_swing_low,
        "bos": bos,
        "mss": mss,
    }


def compute_alignment(tf_results: dict) -> str:
    """Scores cross-timeframe bias agreement. Ignores neutral/insufficient timeframes."""
    biases = [
        v.get("bias") for v in tf_results.values()
        if isinstance(v, dict) and v.get("bias") not in (None, "neutral")
        and v.get("state") != "insufficient_data"
    ]
    if not biases:
        return "neutral"
    dominant = max(set(biases), key=biases.count)
    ratio = biases.count(dominant) / len(biases)
    if ratio == 1.0:
        return "full"
    if ratio >= 0.75:
        return "strong"
    if ratio >= 0.5:
        return "partial"
    return "mixed"
