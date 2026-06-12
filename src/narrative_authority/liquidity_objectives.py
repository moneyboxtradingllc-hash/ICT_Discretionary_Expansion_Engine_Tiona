"""
Phase NA-1 — Liquidity Objective / Draw-on-Liquidity Model (v1).

June 11 gap: the architecture had liquidity memory (was a level swept?)
but no liquidity objective (where is price being drawn?). This module asks
the prospective question.

v1 model — deterministic, intraday-only:
  - Resting pools come from the liquidity engine's nearest buy-side /
    sell-side levels per timeframe (highest timeframe wins).
  - The active draw points TOWARD the unspent pool on the side of the
    narrative direction, and AWAY from a freshly raided (protected) level:
    once buy-side is spent (protected high), the working draw is the
    sell-side below — and vice versa.
  - Prior-session levels (June 10 close / June 11 open volume imbalance)
    are NOT yet modeled: the data plane carries no overnight reference
    levels. That is v2 scope (see docs/na1_narrative_authority.md) and is
    surfaced honestly as a model limitation, not silently approximated.

Never raises.
"""

_TF_PRIORITY = ("15m", "5m", "3m", "1m")


def _nearest(liquidity: dict, key: str) -> "float | None":
    for tf in _TF_PRIORITY:
        val = (liquidity.get(tf) or {}).get(key)
        if val is not None:
            try:
                return float(val)
            except (TypeError, ValueError):
                continue
    return None


def compute_liquidity_draw(snapshot: dict, swings: dict,
                           narrative_direction: str) -> "dict | None":
    """
    Returns {"side", "level", "basis"} for the active draw, or None when no
    objective can be established. Never raises.
    """
    try:
        liquidity = snapshot.get("liquidity", {}) or {}
        buy_side  = _nearest(liquidity, "nearest_buy_side_liquidity")
        sell_side = _nearest(liquidity, "nearest_sell_side_liquidity")
        ph        = (swings or {}).get("protected_high")
        pl        = (swings or {}).get("protected_low")

        # Direction-led draw: price seeks the pool in its delivery direction.
        if narrative_direction == "bearish" and sell_side is not None:
            return {"side": "sell_side", "level": round(sell_side, 4),
                    "basis": "bearish delivery toward resting sell stops"}
        if narrative_direction == "bullish" and buy_side is not None:
            return {"side": "buy_side", "level": round(buy_side, 4),
                    "basis": "bullish delivery toward resting buy stops"}

        # No directional narrative: a fresh raid implies the opposite pool
        # is the working objective (buy-side spent -> sell-side draw).
        if ph is not None and sell_side is not None:
            return {"side": "sell_side", "level": round(sell_side, 4),
                    "basis": "buy-side spent at protected high — opposite pool is the objective"}
        if pl is not None and buy_side is not None:
            return {"side": "buy_side", "level": round(buy_side, 4),
                    "basis": "sell-side spent at protected low — opposite pool is the objective"}

        return None
    except Exception:  # noqa: BLE001
        return None
