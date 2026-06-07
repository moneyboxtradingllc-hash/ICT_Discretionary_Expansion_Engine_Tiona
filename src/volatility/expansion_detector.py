def _directional_efficiency(candles: list) -> float:
    if len(candles) < 2:
        return 0.5
    net = abs(candles[-1]["close"] - candles[0]["open"])
    total = sum(c["range"] for c in candles)
    if total == 0:
        return 0.0
    return round(min(net / total, 1.0), 3)


def _body_dominance(candles: list) -> float:
    valid = [c for c in candles if c["range"] > 0]
    if not valid:
        return 0.5
    return round(sum(c["body_size"] / c["range"] for c in valid) / len(valid), 3)


def _range_acceleration(candles: list) -> float:
    if len(candles) < 4:
        return 1.0
    half = max(2, len(candles) // 2)
    recent = candles[-half:]
    older = candles[-2 * half:-half] or candles[:half]
    r_avg = sum(c["range"] for c in recent) / len(recent)
    o_avg = sum(c["range"] for c in older) / len(older)
    if o_avg == 0:
        return 1.0
    return round(r_avg / o_avg, 3)


def _follow_through(candles: list) -> int:
    """Count consecutive candles at the tail moving in the same direction."""
    if len(candles) < 2:
        return 0
    last_dir = candles[-1]["direction"]
    if last_dir == "neutral":
        return 0
    count = 1
    for i in range(len(candles) - 2, -1, -1):
        if candles[i]["direction"] == last_dir:
            count += 1
        else:
            break
    return count


def _displacement_detected(candles: list, atr: float) -> bool:
    """A displacement candle has body >= 50% of ATR and a clear direction."""
    if not candles or atr <= 0:
        return False
    threshold = atr * 0.50
    for c in candles[-5:]:
        if c["body_size"] >= threshold and c["direction"] != "neutral":
            return True
    return False


def _exhaustion_risk(candles: list) -> str:
    """High wick ratio + shrinking bodies on recent candles = distribution / exhaustion."""
    recent = [c for c in candles[-3:] if c["range"] > 0]
    if not recent:
        return "low"
    avg_wick = sum((c["upper_wick"] + c["lower_wick"]) / c["range"] for c in recent) / len(recent)
    avg_body = sum(c["body_size"] / c["range"] for c in recent) / len(recent)
    if avg_wick > 0.60 and avg_body < 0.35:
        return "high"
    if avg_wick > 0.45 or avg_body < 0.45:
        return "medium"
    return "low"


def _score(body_dom: float, dir_eff: float, follow_count: int,
           range_accel: float, atr_trend: str) -> int:
    s = 50
    s += (body_dom - 0.5) * 40               # body quality: -20 to +20
    s += (dir_eff - 0.4) * 30                # directional efficiency: -12 to +18
    s += min(follow_count * 5, 15)            # follow-through streak: up to +15
    s += max(-10, min(15, (range_accel - 1.0) * 20))
    s += {"rising": 5, "stable": 0, "falling": -8, "unknown": 0}.get(atr_trend, 0)
    return max(0, min(100, round(s)))


def _state(score: int, body_dom: float, dir_eff: float,
           displacement: bool, exhaustion: str) -> str:
    if exhaustion == "high":
        return "exhaustion_risk"
    if score < 25:
        return "compression"
    if score < 45:
        return "early_expansion" if displacement else "compression"
    if score >= 68 and body_dom >= 0.50 and dir_eff >= 0.50:
        return "healthy_expansion"
    if score >= 52:
        return "mature_expansion"
    return "early_expansion"


def detect_expansion(candles: list, atr_result: dict) -> dict:
    if not candles or atr_result.get("atr") is None:
        return {
            "state": "unknown",
            "expansion_score": 0,
            "displacement_detected": False,
            "directional_efficiency": 0.0,
            "body_dominance": 0.5,
            "exhaustion_risk": "low",
        }

    atr = atr_result["atr"]
    atr_trend = atr_result["atr_trend"]

    dir_eff = _directional_efficiency(candles)
    body_dom = _body_dominance(candles)
    range_accel = _range_acceleration(candles)
    follow_count = _follow_through(candles)
    displacement = _displacement_detected(candles, atr)
    exhaustion = _exhaustion_risk(candles)

    score = _score(body_dom, dir_eff, follow_count, range_accel, atr_trend)

    return {
        "state": _state(score, body_dom, dir_eff, displacement, exhaustion),
        "expansion_score": score,
        "displacement_detected": displacement,
        "directional_efficiency": dir_eff,
        "body_dominance": body_dom,
        "exhaustion_risk": exhaustion,
    }
