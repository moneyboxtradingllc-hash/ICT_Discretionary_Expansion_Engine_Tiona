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


def _displacement_detected(candles: list, threshold: float) -> bool:
    """A displacement candle has body >= threshold and a clear direction.

    VECTOR-3: `threshold` is now the ATR dead-band result
    max(atr * K_ATR, F_disp[tf]) so that a collapsed ATR can no longer let a
    physically trivial candle (0.03-0.25pt) read as displacement.
    """
    if not candles or threshold <= 0:
        return False
    for c in candles[-5:]:
        if c["body_size"] >= threshold and c["direction"] != "neutral":
            return True
    return False


# ── VECTOR-3 Absolute Magnitude Gate ──────────────────────────────────────────

def _window_significance(candles: list, window: int) -> float:
    """Recent physical travel, in points, over the last `window` candles.

    significance = max(net_displacement, rolling_range). Net displacement catches
    a clean directional leg; rolling range catches a choppy-but-wide window. On
    flat tape both collapse together, driving kappa to 0.
    """
    if not candles:
        return 0.0
    w = candles[-window:] if window > 0 else candles
    net_disp = abs(w[-1]["close"] - w[0]["open"])
    window_span = max(c["high"] for c in w) - min(c["low"] for c in w)
    return max(net_disp, window_span)


def _kappa(significance: float, f_win: float, band_mult: float) -> float:
    """Magnitude confidence in [0,1]. 0 below F_win, ramps linearly to 1 at
    F_win*(1+band_mult). Continuous by construction — no cliff."""
    if f_win <= 0:
        return 1.0
    band = f_win * band_mult
    if band <= 0:
        return 1.0 if significance >= f_win else 0.0
    k = (significance - f_win) / band
    return max(0.0, min(1.0, round(k, 4)))


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


def detect_expansion(candles: list, atr_result: dict, tf: str = None) -> dict:
    """Detect expansion / displacement for one timeframe.

    VECTOR-3: when `tf` is supplied and the magnitude gate is enabled, two
    absolute-point gates are applied so scale-invariant ratio saturation on flat
    tape can no longer manufacture high-conviction expansion:

      1. ATR dead-band — displacement threshold = max(atr*K_ATR, F_disp[tf]).
      2. Window significance — kappa in [0,1] from recent physical travel
         attenuates dir_eff / body_dom / score toward neutral; kappa==0 also
         forces displacement False (magnitude_gated).

    When `tf` is None or VECTOR3_MAGNITUDE_GATE=off, behaviour is bit-for-bit
    legacy. `magnitude_gated`/`kappa` are always emitted (additive keys).
    """
    if not candles or atr_result.get("atr") is None:
        return {
            "state": "unknown",
            "expansion_score": 0,
            "displacement_detected": False,
            "directional_efficiency": 0.0,
            "body_dominance": 0.5,
            "exhaustion_risk": "low",
            "kappa": 0.0,
            "magnitude_gated": True,
        }

    atr = atr_result["atr"]
    atr_trend = atr_result["atr_trend"]

    # Local import keeps the legacy path free of the structure package when the
    # gate is unused (tf is None), and avoids a hard import cycle.
    from structure import po3_config as cfg
    gate_on = cfg.gate_enabled() and tf is not None

    # ── ATR dead-band ─────────────────────────────────────────────────────────
    disp_threshold = max(atr * cfg.K_ATR, cfg.f_disp(tf)) if gate_on else atr * cfg.K_ATR

    dir_eff = _directional_efficiency(candles)
    body_dom = _body_dominance(candles)
    range_accel = _range_acceleration(candles)
    follow_count = _follow_through(candles)
    displacement = _displacement_detected(candles, disp_threshold)
    exhaustion = _exhaustion_risk(candles)

    score = _score(body_dom, dir_eff, follow_count, range_accel, atr_trend)

    # ── Window significance gate ──────────────────────────────────────────────
    if gate_on:
        significance = _window_significance(candles, cfg.SIG_WINDOW)
        kappa = _kappa(significance, cfg.f_win(tf), cfg.KAPPA_BAND_MULT)
    else:
        kappa = 1.0
    magnitude_gated = kappa <= 0.0

    if gate_on:
        # Attenuate the ABOVE-NEUTRAL component toward 0.5 / 50 by kappa.
        dir_eff = round(0.5 + (dir_eff - 0.5) * kappa, 3)
        body_dom = round(0.5 + (body_dom - 0.5) * kappa, 3)
        score = round(50 + (score - 50) * kappa)
        if magnitude_gated:
            displacement = False   # sub-floor travel cannot be delivery

    return {
        "state": _state(score, body_dom, dir_eff, displacement, exhaustion),
        "expansion_score": score,
        "displacement_detected": displacement,
        "directional_efficiency": dir_eff,
        "body_dominance": body_dom,
        "exhaustion_risk": exhaustion,
        "kappa": kappa,
        "magnitude_gated": magnitude_gated,
    }
