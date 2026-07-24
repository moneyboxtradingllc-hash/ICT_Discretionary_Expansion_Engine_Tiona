"""Manipulation confluence — did the market ENGINEER liquidity and transition
from balance into repricing?

The question is deliberately NOT "find a sweep". A liquidity sweep is one
expression of manipulation, not its definition. `analyze_liquidity` inspects only
candles[-1], so it answers "is a sweep completing on this exact bar" — a sweep
three candles ago reads as no manipulation at all. Manipulation is a PHASE; it
persists after the bar that created it. Every detector here therefore scans a
lookback window rather than the closing bar.

Detection only. Scoring and telemetry live here too, but no phase decision is
made — po3_engine consumes `score` and weighs it against the other phases, which
keeps that module free of raw candle math as its own docstring requires.

Weights are the operator's initial specification, NOT tuned. Telemetry lands
before tuning on purpose: the point is to see WHY a move was classified, not
merely whether the final label matched.
"""
from structure.structure_engine import find_swings
from structure import po3_config as cfg

# Component weights — operator-specified starting values, unvalidated.
W_EXTERNAL_SWEEP = 30
W_INTERNAL_RAID  = 20
W_FAILURE_SWING  = 20
W_FAILED_BREAKOUT = 15
W_REJECTION      = 15
W_RECLAIM        = 15
W_RAPID_REVERSAL = 15

CONFIRMED_AT = 50   # initial classification bands, unvalidated
POSSIBLE_AT  = 25

_MIN_CANDLES = 6


def _rng(c):
    r = c.get("range")
    return r if r is not None else (c["high"] - c["low"])


def _upper_wick(c):
    w = c.get("upper_wick")
    return w if w is not None else c["high"] - max(c["open"], c["close"])


def _lower_wick(c):
    w = c.get("lower_wick")
    return w if w is not None else min(c["open"], c["close"]) - c["low"]


# ── Individual evidence detectors ─────────────────────────────────────────────

def _external_sweep(window, highs, lows):
    """A swing extreme pierced and rejected — the outermost resting liquidity."""
    if not window:
        return False, "no window", None
    ext_high = max(highs) if highs else None
    ext_low = min(lows) if lows else None
    for c in reversed(window):
        if ext_high is not None and c["high"] > ext_high and c["close"] < ext_high:
            return True, f"pierced external high {ext_high} closed {c['close']}", "above_high"
        if ext_low is not None and c["low"] < ext_low and c["close"] > ext_low:
            return True, f"pierced external low {ext_low} closed {c['close']}", "below_low"
    return False, "no external extreme pierced and rejected", None


def _internal_raid(window, highs, lows):
    """An INTERNAL swing taken and rejected — stops inside the range, not the
    outer extreme. Distinct from an external sweep and frequently the only
    liquidity event present on continuation setups."""
    if not window:
        return False, "no window", None
    ext_high = max(highs) if highs else None
    ext_low = min(lows) if lows else None
    internal_highs = [h for h in highs if ext_high is None or h < ext_high]
    internal_lows = [l for l in lows if ext_low is None or l > ext_low]
    for c in reversed(window):
        for h in internal_highs:
            if c["high"] > h and c["close"] < h:
                return True, f"raided internal high {h} closed {c['close']}", "above_high"
        for l in internal_lows:
            if c["low"] < l and c["close"] > l:
                return True, f"raided internal low {l} closed {c['close']}", "below_low"
    return False, "no internal level raided", None


def _failure_swing(highs, lows):
    """Classic failure swing: the market fails to extend, then breaks the
    intervening pivot. Bearish — a LOWER high followed by a break of the prior
    low. Bullish — a HIGHER low followed by a break of the prior high.

    This is the one manipulation form that needs no sweep at all: price never has
    to take liquidity to fail."""
    if len(highs) >= 2 and len(lows) >= 1:
        if highs[-1] < highs[-2] and lows[-1] < lows[-2 if len(lows) >= 2 else -1]:
            return True, f"lower high {highs[-1]} < {highs[-2]}, prior low broken", "bearish"
    if len(lows) >= 2 and len(highs) >= 1:
        if lows[-1] > lows[-2] and highs[-1] > highs[-2 if len(highs) >= 2 else -1]:
            return True, f"higher low {lows[-1]} > {lows[-2]}, prior high broken", "bullish"
    return False, "no failure swing in swing sequence", None


def _failed_breakout(window, highs, lows):
    """Closed beyond a level, then closed back inside — a breakout that failed."""
    if len(window) < 2:
        return False, "window too short", None
    ref_high = max(highs) if highs else None
    ref_low = min(lows) if lows else None
    for i in range(len(window) - 1, 0, -1):
        prev_c, c = window[i - 1]["close"], window[i]["close"]
        if ref_high is not None and prev_c > ref_high and c < ref_high:
            return True, f"closed above {ref_high} then back below", "above_high"
        if ref_low is not None and prev_c < ref_low and c > ref_low:
            return True, f"closed below {ref_low} then back above", "below_low"
    return False, "no failed breakout", None


def _rejection(window):
    """A dominant wick with the close pushed to the far third — price was
    offered at a level and refused, independent of any named liquidity pool."""
    for c in reversed(window):
        r = _rng(c)
        if r <= 0:
            continue
        up, lo = _upper_wick(c), _lower_wick(c)
        if up / r >= 0.5 and (c["close"] - c["low"]) / r <= 0.4:
            return True, f"upper wick {up:.2f} of {r:.2f} range, close near low", "bearish"
        if lo / r >= 0.5 and (c["high"] - c["close"]) / r <= 0.4:
            return True, f"lower wick {lo:.2f} of {r:.2f} range, close near high", "bullish"
    return False, "no rejection candle in window", None


def _rapid_reversal(window, atr):
    """Liquidity created, then price left it fast.

    A pure "extreme is one ATR from the close" test fires on any trending
    window — measuring window-low to last close during a downtrend always
    clears an ATR. A reversal additionally requires that the extreme was SET and
    then ABANDONED: it must sit far enough back to be a turn rather than the
    current bar, and price must not have revisited it since.
    """
    if len(window) < 4 or not atr or atr <= 0:
        return False, "window too short or no atr", None
    last = window[-1]["close"]
    hi_i = max(range(len(window)), key=lambda i: window[i]["high"])
    lo_i = min(range(len(window)), key=lambda i: window[i]["low"])
    tail = max(2, len(window) // 4)   # extreme must predate the closing bars

    # A reversal is a round trip: price travelled INTO the extreme, then away
    # from it. Abandonment alone is not enough — in a pure trend the window
    # extreme sits at index 0 and is never revisited, which satisfies
    # "abandoned" while describing no reversal whatsoever.
    hi = window[hi_i]["high"]
    if hi_i >= 1 and hi_i <= len(window) - 1 - tail and hi - last >= atr:
        approach = hi - min(c["low"] for c in window[:hi_i + 1])
        if approach >= atr and max(c["high"] for c in window[hi_i + 1:]) < hi:
            return True, (f"rose {approach:.2f} into high {hi} ({len(window)-1-hi_i} bars "
                          f"back), reversed {hi - last:.2f} (atr {atr:.2f})"), "bearish"

    lo = window[lo_i]["low"]
    if lo_i >= 1 and lo_i <= len(window) - 1 - tail and last - lo >= atr:
        approach = max(c["high"] for c in window[:lo_i + 1]) - lo
        if approach >= atr and min(c["low"] for c in window[lo_i + 1:]) > lo:
            return True, (f"fell {approach:.2f} into low {lo} ({len(window)-1-lo_i} bars "
                          f"back), reversed {last - lo:.2f} (atr {atr:.2f})"), "bullish"

    return False, "no round-trip reversal at an abandoned extreme", None


# ── Confluence ────────────────────────────────────────────────────────────────

def detect_manipulation(candles: list, atr: float = None) -> dict:
    """Score manipulation by confluence over a lookback window.

    Returns score (0-100, capped), a classification band, and a per-component
    breakdown carrying points AND the observation that earned them — every
    component is reported whether present or absent, so a zero is auditable
    rather than merely missing.
    """
    components, directions = [], []

    def add(name, present, points, detail, direction=None):
        components.append({"name": name, "present": bool(present),
                           "points": points if present else 0,
                           "weight": points, "detail": detail})
        if present and direction:
            directions.append(direction)

    if not candles or len(candles) < _MIN_CANDLES:
        return {"score": 0, "classification": "none", "direction": None,
                "components": [], "lookback": 0,
                "reason": f"insufficient candles ({len(candles) if candles else 0})"}

    window = candles[-cfg.MANIP_LOOKBACK:]
    # Swings come from RECENT structure. find_swings over the full history
    # returns pivots from unrelated legs — the same unbounded-window defect
    # LEG-SCOPE fixed in expansion.
    highs, lows = find_swings(candles[-cfg.MANIP_CONTEXT:])

    present, detail, d = _external_sweep(window, highs, lows)
    add("external_sweep", present, W_EXTERNAL_SWEEP, detail,
        "bearish" if d == "above_high" else "bullish" if d else None)

    present, detail, d = _internal_raid(window, highs, lows)
    add("internal_raid", present, W_INTERNAL_RAID, detail,
        "bearish" if d == "above_high" else "bullish" if d else None)

    present, detail, d = _failure_swing(highs, lows)
    add("failure_swing", present, W_FAILURE_SWING, detail, d)

    present, detail, d = _failed_breakout(window, highs, lows)
    add("failed_breakout", present, W_FAILED_BREAKOUT, detail,
        "bearish" if d == "above_high" else "bullish" if d else None)

    present, detail, d = _rejection(window)
    add("rejection", present, W_REJECTION, detail, d)

    present, detail, d = _rapid_reversal(window, atr)
    add("rapid_reversal", present, W_RAPID_REVERSAL, detail, d)

    raw = sum(c["points"] for c in components)
    score = min(100, raw)
    classification = ("manipulation_confirmed" if score >= CONFIRMED_AT else
                      "manipulation_possible" if score >= POSSIBLE_AT else "none")
    direction = max(set(directions), key=directions.count) if directions else None

    return {"score": score, "raw_score": raw, "classification": classification,
            "direction": direction, "components": components,
            "lookback": len(window)}


def format_manipulation(m: dict) -> str:
    """Human-readable audit trail — the discretionary-trader-legible form."""
    lines = ["Manipulation Score:", ""]
    for c in m.get("components", []):
        lines.append(f"  {c['name']:<18} {('+' + str(c['points'])) if c['points'] else '0':>5}"
                     f"   {c['detail']}")
    lines += ["", f"  Total: {m.get('score', 0)}/100",
              "", f"  Classification: {m.get('classification', 'none')}"]
    if m.get("direction"):
        lines.append(f"  Direction: {m['direction']}")
    return "\n".join(lines)
