def _range_acceleration(candles: list) -> float:
    """Ratio of recent avg range to older avg range. >1 = expanding, <1 = contracting."""
    if len(candles) < 4:
        return 1.0
    half = max(2, len(candles) // 2)
    recent = candles[-half:]
    older = candles[-2 * half:-half] or candles[:half]
    recent_avg = sum(c["range"] for c in recent) / len(recent)
    older_avg = sum(c["range"] for c in older) / len(older)
    if older_avg == 0:
        return 1.0
    return round(recent_avg / older_avg, 3)


def _directional_efficiency(candles: list) -> float:
    """Net price displacement / total range traveled. 1.0 = perfectly directional."""
    if len(candles) < 2:
        return 0.5
    net = abs(candles[-1]["close"] - candles[0]["open"])
    total = sum(c["range"] for c in candles)
    if total == 0:
        return 0.0
    return round(min(net / total, 1.0), 3)


def _body_dominance(candles: list) -> float:
    """Average body_size / range. 1.0 = all body, 0.0 = all wick."""
    valid = [c for c in candles if c["range"] > 0]
    if not valid:
        return 0.5
    return round(sum(c["body_size"] / c["range"] for c in valid) / len(valid), 3)


def _score(atr_trend: str, range_accel: float, body_dom: float, dir_eff: float) -> int:
    s = 50
    s += {"rising": 15, "stable": 0, "falling": -15}.get(atr_trend, 0)
    s += max(-25, min(30, (range_accel - 1.0) * 40))  # accel contribution
    s += (body_dom - 0.5) * 20                         # body quality
    s += (dir_eff - 0.4) * 10                          # directional efficiency
    return max(0, min(100, round(s)))


def _state(score: int, dir_eff: float) -> str:
    if score <= 15:
        return "liquidity_vacuum"
    if dir_eff < 0.20 and score > 65:
        return "toxic"       # violent but no direction
    if dir_eff < 0.30 and score > 55:
        return "unstable"    # choppy
    if score >= 82:
        return "explosive"
    if score >= 58:
        return "expanding"
    return "stable"


def classify_volatility(candles: list, atr_result: dict) -> dict:
    if not candles or atr_result.get("atr") is None:
        return {
            "state": "unknown",
            "atr": None,
            "atr_trend": "unknown",
            "volatility_score": 0,
            "range_acceleration": 1.0,
        }

    # Volatility describes CURRENT conditions, so the conviction ratios read a
    # bounded recent window. Unsliced they run over the whole normalized history
    # (~2000 candles live) and decay toward zero as history grows — the same
    # defect LEG-SCOPE fixed in expansion_detector, which carries a duplicate of
    # _directional_efficiency that was fixed there and missed here.
    #
    # The consequence was not a skewed number but two unreachable states:
    # _state() guards `explosive` and `expanding` behind `dir_eff < 0.20` and
    # `< 0.30`, and with dir_eff pinned near 0.04 both guards were always true.
    # Anything scoring above 65 became `toxic`, anything above 55 `unstable`,
    # and `expanding` was never emitted at all — which in turn made
    # narrative_builder's `vol_15m in ("expanding", "stable")` a half-dead test.
    from structure import po3_config as cfg
    window = candles
    if cfg.leg_scope_enabled() and len(candles) > cfg.LEG_MAX_CANDLES:
        window = candles[-cfg.LEG_MAX_CANDLES:]

    atr_trend = atr_result["atr_trend"]
    range_accel = _range_acceleration(window)
    dir_eff = _directional_efficiency(window)
    body_dom = _body_dominance(window)
    score = _score(atr_trend, range_accel, body_dom, dir_eff)

    return {
        "state": _state(score, dir_eff),
        "atr": atr_result["atr"],
        "atr_trend": atr_trend,
        "volatility_score": score,
        "range_acceleration": range_accel,
    }
