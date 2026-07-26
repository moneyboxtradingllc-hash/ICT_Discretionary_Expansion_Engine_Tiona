"""Timeframe hierarchy — directional authority and the phase inside it.

A retracement is not a contradiction of trend. It is evidence of trend when
interpreted correctly. The prior model treated 15m-bearish plus 5m-bullish as
conflicting information and fell through to range_rotation, which meant the
regime engine could not name a trend during the exact condition it most needed
to: a pullback inside one.

The hierarchy this encodes:

  HTF (15m)  establishes directional AUTHORITY, and holds it until price
             violates the structural level that would invalidate it.
  LTF (5m)   describes the PHASE inside that authority — continuation when it
             agrees, retracement when it opposes while authority stands.
  1m         is execution and does not vote on authority.

Authority is not the same as agreement. A lower timeframe moving against the
higher timeframe only removes authority when it breaks the higher timeframe's
invalidation level. Short of that, opposition IS the retracement.

Also home to the structural features regime_features declared but never
computed. Every one is drawn from a bounded recent window, per LEG-SCOPE:
metrics must describe the current market condition, not the whole dataset.
"""
from structure.structure_engine import find_swings

# Bounded context windows. Swing sequence needs enough candles for fractal
# pivots to form, few enough that it describes the current auction.
SEQ_WINDOW   = 60
RANGE_WINDOW = 60

_BULL, _BEAR, _NEUTRAL = "bullish", "bearish", "neutral"


def swing_sequence(candles: list, window: int = SEQ_WINDOW) -> dict:
    """HH / HL / LH / LL counts from bounded recent swings.

    These were returned as hardcoded zeros by regime_features. They are the
    most basic statement of structure available and nothing downstream could
    read them.
    """
    empty = {"higher_highs": 0, "lower_highs": 0, "higher_lows": 0, "lower_lows": 0,
             "sequence": "unknown", "swing_highs": 0, "swing_lows": 0,
             "window": 0, "detail": "insufficient candles"}
    if not candles:
        return empty
    recent = candles[-window:]
    highs, lows = find_swings(recent)
    if len(highs) < 2 and len(lows) < 2:
        return {**empty, "window": len(recent),
                "swing_highs": len(highs), "swing_lows": len(lows),
                "detail": f"only {len(highs)} swing highs / {len(lows)} swing lows in window"}

    hh = sum(1 for a, b in zip(highs, highs[1:]) if b > a)
    lh = sum(1 for a, b in zip(highs, highs[1:]) if b < a)
    hl = sum(1 for a, b in zip(lows, lows[1:]) if b > a)
    ll = sum(1 for a, b in zip(lows, lows[1:]) if b < a)

    if hh > lh and hl >= ll:
        seq = "higher_highs_higher_lows"
    elif lh > hh and ll >= hl:
        seq = "lower_highs_lower_lows"
    elif hh > lh or hl > ll:
        seq = "mixed_bullish_lean"
    elif lh > hh or ll > hl:
        seq = "mixed_bearish_lean"
    else:
        seq = "balanced"

    return {"higher_highs": hh, "lower_highs": lh, "higher_lows": hl, "lower_lows": ll,
            "sequence": seq, "swing_highs": len(highs), "swing_lows": len(lows),
            "window": len(recent),
            "detail": f"HH={hh} LH={lh} HL={hl} LL={ll} over {len(recent)} candles"}


def range_metrics(candles: list, window: int = RANGE_WINDOW) -> dict:
    """Range size and where the close sits inside it — both previously literals."""
    if not candles:
        return {"range_size": 0.0, "close_position_in_range": 0.0,
                "range_high": None, "range_low": None, "window": 0}
    recent = candles[-window:]
    hi = max(c["high"] for c in recent)
    lo = min(c["low"] for c in recent)
    size = hi - lo
    close = recent[-1]["close"]
    pos = ((close - lo) / size) if size > 0 else 0.0
    return {"range_size": round(size, 2), "close_position_in_range": round(pos, 3),
            "range_high": hi, "range_low": lo, "window": len(recent)}


def range_state(candles: list, window: int = RANGE_WINDOW) -> dict:
    """Is the range expanding or contracting? Compares the recent half-window
    against the one before it, so the answer describes now rather than the
    dataset average."""
    if not candles or len(candles) < 8:
        return {"range_state": "unknown", "recent_range": 0.0, "prior_range": 0.0,
                "ratio": 1.0, "detail": "insufficient candles"}
    recent = candles[-window:]
    half = len(recent) // 2
    new, old = recent[half:], recent[:half]
    r_new = max(c["high"] for c in new) - min(c["low"] for c in new)
    r_old = max(c["high"] for c in old) - min(c["low"] for c in old)
    ratio = (r_new / r_old) if r_old > 0 else 1.0
    state = "expanding" if ratio >= 1.20 else "contracting" if ratio <= 0.80 else "stable"
    return {"range_state": state, "recent_range": round(r_new, 2),
            "prior_range": round(r_old, 2), "ratio": round(ratio, 3),
            "detail": f"recent {r_new:.2f} vs prior {r_old:.2f} = {ratio:.2f}x -> {state}"}


def dealing_range(structure: dict, last_price: float,
                  equilibrium_band: float = 0.10) -> dict:
    """The operative range and where price sits inside it.

    Owned here so regime and context cannot disagree about it — regime runs
    first in snapshot_builder, so context consumes this rather than recomputing.
    """
    for tf in ("15m", "5m"):
        st = (structure or {}).get(tf) or {}
        hi, lo = st.get("last_swing_high"), st.get("last_swing_low")
        if isinstance(hi, (int, float)) and isinstance(lo, (int, float)) and hi > lo:
            mid = (hi + lo) / 2
            if not isinstance(last_price, (int, float)):
                return {"source_tf": tf, "high": hi, "low": lo, "midpoint": round(mid, 2),
                        "position": None, "zone": "unknown"}
            pos = (last_price - lo) / (hi - lo)
            zone = ("premium" if pos > 0.5 + equilibrium_band else
                    "discount" if pos < 0.5 - equilibrium_band else "equilibrium")
            return {"source_tf": tf, "high": hi, "low": lo, "midpoint": round(mid, 2),
                    "position": round(pos, 3), "zone": zone}
    return {"source_tf": None, "high": None, "low": None, "midpoint": None,
            "position": None, "zone": "unknown"}


def htf_authority(structure_tf: dict, last_price: float, tf: str = "15m") -> dict:
    """Does the higher timeframe hold directional authority, and is it intact?

    Authority survives a counter-move; it dies when price closes through the
    structural level that would invalidate the trend. For a bearish HTF that is
    the last swing high — until price takes it, a rally is a retracement.
    """
    st = structure_tf or {}
    bias = str(st.get("bias") or _NEUTRAL).lower()
    if bias not in (_BULL, _BEAR):
        return {"timeframe": tf, "bias": _NEUTRAL, "invalidation": None,
                "intact": False, "detail": f"{tf} structure bias is {bias} — no authority"}

    invalidation = st.get("last_swing_high") if bias == _BEAR else st.get("last_swing_low")
    if not isinstance(invalidation, (int, float)) or not isinstance(last_price, (int, float)):
        return {"timeframe": tf, "bias": bias, "invalidation": invalidation,
                "intact": True,
                "detail": f"{tf} {bias} authority; invalidation level unavailable, assumed intact"}

    intact = last_price < invalidation if bias == _BEAR else last_price > invalidation
    side = "below" if bias == _BEAR else "above"
    return {"timeframe": tf, "bias": bias, "invalidation": invalidation, "intact": intact,
            "detail": (f"{tf} {bias} authority {'intact' if intact else 'VIOLATED'} — "
                       f"price {last_price} {'is' if intact else 'is NOT'} {side} "
                       f"invalidation {invalidation}")}


def classify_relationship(authority: dict, ltf_bias: str) -> dict:
    """The phase the lower timeframe describes inside the higher timeframe's
    authority. This is the distinction the old model could not draw."""
    htf_bias = (authority or {}).get("bias", _NEUTRAL)
    intact = bool((authority or {}).get("intact"))
    ltf = str(ltf_bias or _NEUTRAL).lower()

    if htf_bias not in (_BULL, _BEAR):
        return {"relationship": "no_authority",
                "reason": ("HTF structure has no directional authority. Local "
                           f"{ltf} movement cannot be classified as retracement.")}
    if not intact:
        return {"relationship": "authority_violated",
                "reason": (f"{htf_bias} HTF authority violated — price traded through "
                           f"invalidation {(authority or {}).get('invalidation')}.")}
    if ltf not in (_BULL, _BEAR):
        return {"relationship": "continuation",
                "reason": f"{htf_bias} HTF authoritative; local structure {ltf}, no opposition."}
    if ltf == htf_bias:
        return {"relationship": "continuation",
                "reason": f"{htf_bias} HTF authoritative and local structure agrees."}
    return {"relationship": "retracement",
            "reason": (f"{authority.get('timeframe')} {htf_bias} structure remains "
                       f"authoritative. {ltf.capitalize()} local movement classified as "
                       f"retracement because it has not violated HTF invalidation "
                       f"{(authority or {}).get('invalidation')}.")}
