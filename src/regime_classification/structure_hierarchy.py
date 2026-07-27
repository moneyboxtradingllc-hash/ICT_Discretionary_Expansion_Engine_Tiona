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


def _draw_direction(narrative: dict):
    """Direction implied by the active liquidity objective — what price is
    attacking. The primary directional authority."""
    draw = (narrative or {}).get("active_liquidity_draw")
    if not isinstance(draw, dict):
        return None, None
    side = str(draw.get("side") or "").lower()
    if side == "sell_side":
        return _BEAR, draw
    if side == "buy_side":
        return _BULL, draw
    return None, draw


def _po3_direction(po3: dict, tf: str):
    """Direction implied by the institutional campaign. Second authority.

    Reads PO3's own sweep-derived outputs only. AB-2C removed the structure-bias
    fallback deliberately and this must not reintroduce it.
    """
    block = (po3 or {}).get(tf) or {}
    for key in ("delivery_direction", "distribution_direction", "manipulation_direction"):
        d = str(block.get(key) or "").lower()
        if d in (_BULL, _BEAR):
            return d, f"po3.{tf}.{key}"
    return None, None


def htf_authority(structure_tf: dict = None, last_price: float = None,
                  tf: str = "15m", narrative: dict = None, po3: dict = None,
                  liquidity: dict = None) -> dict:
    """Standing directional authority, sourced top-down per doctrine.

        1. LIQUIDITY  — what is price attacking (active_liquidity_draw)
        2. PO3        — what institutional phase is delivering
           STRUCTURE  — CONFIRMATION ONLY, never authors direction

    narrative_direction is deliberately NOT an authority tier. It reads as one,
    but narrative_engine falls back to `direction = struct_dir` in witness mode
    (AI and delivery lenses silent — the normal case with the brain off), so
    admitting it would launder structure back into direction.

    Structure requires confirmed pivots before it can update, so it is
    retrospective by construction and lags the live auction. It previously
    authored direction here, which meant the authority model — and everything
    consuming it: market_context, PO3 reconciliation, the order-block anchor —
    inherited that lag. Measured on 2026-07-27 at 09:49, price 28,481 while
    every higher-timeframe swing sat 150-220 points above it.

    Structure is still REPORTED, as confirmation evidence. It is never consulted
    for direction, and no fallback path may restore it.

    Returns bias/intact/invalidation plus the source that authored it. Neutral
    when no live objective exists — an honest absence, not a failure.
    """
    st = structure_tf or {}
    confirmation = {"structure_bias": str(st.get("bias") or _NEUTRAL).lower(),
                    "bos": bool(st.get("bos")), "mss": bool(st.get("mss")),
                    "note": "structure confirms completed movement; it does not author direction"}

    bias, source, detail_src = _NEUTRAL, None, ""
    d, draw = _draw_direction(narrative)
    if d:
        bias, source = d, "liquidity.active_liquidity_draw"
        detail_src = f"draw {draw.get('side')} @ {draw.get('level')}"
    if bias == _NEUTRAL:
        d, src = _po3_direction(po3, tf)
        if d:
            bias, source, detail_src = d, src, src

    # NO narrative_direction tier. It looks like a third authority but it is a
    # structure conduit: _structure_lens reads ai_context.directional_bias, which
    # is derived from structure, and narrative_engine's witness-mode branch sets
    # `direction = struct_dir` outright whenever the AI and delivery lenses are
    # silent — the normal case with the brain off. Measured Friday RTH: narrative
    # sat in structure-only witness mode on 8 of 17 samples.
    #
    # Admitting it here would re-promote structure under a different abstraction,
    # which is precisely what the doctrine forbids. Only Liquidity and PO3 author.

    if bias not in (_BULL, _BEAR):
        return {"timeframe": tf, "bias": _NEUTRAL, "invalidation": None,
                "intact": False, "source": None, "confirmation": confirmation,
                "detail": ("no live liquidity objective, PO3 delivery direction or "
                           "narrative direction — no directional authority")}

    # Invalidation follows the objective, NOT a structure swing. Structure swings
    # lag and produced 37-77pt stops against a 25pt cap.
    invalidation = (narrative or {}).get("invalidation_level")
    if not isinstance(invalidation, (int, float)):
        invalidation = ((narrative or {}).get("protected_high") if bias == _BEAR
                        else (narrative or {}).get("protected_low"))

    if not isinstance(invalidation, (int, float)) or not isinstance(last_price, (int, float)):
        return {"timeframe": tf, "bias": bias, "invalidation": None, "intact": True,
                "source": source, "confirmation": confirmation,
                "detail": (f"{bias} authority from {source} ({detail_src}); "
                           f"no invalidation level published, assumed intact")}

    intact = last_price < invalidation if bias == _BEAR else last_price > invalidation
    side = "below" if bias == _BEAR else "above"
    return {"timeframe": tf, "bias": bias, "invalidation": invalidation,
            "intact": intact, "source": source, "confirmation": confirmation,
            "detail": (f"{bias} authority from {source} ({detail_src}) "
                       f"{'intact' if intact else 'VIOLATED'} — price {last_price} "
                       f"{'is' if intact else 'is NOT'} {side} invalidation {invalidation}")}


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
