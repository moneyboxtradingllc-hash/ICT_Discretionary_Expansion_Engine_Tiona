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


def _leg_start_index(candles: list, struct: dict) -> int | None:
    """Index at which the current auction leg began — the EXACT occurrence of the
    most recent structural pivot. None when structure offers no such occurrence.

    STEP 4B.12 §4 UNIT 4 — PRICE VALIDATES GEOMETRY, IT DOES NOT OWN IDENTITY.

    This used to take the swing PRICE and scan backwards for a candle whose
    extreme equalled it. Its docstring argued the price "should equal a candle
    extreme exactly" -- true, and beside the point. It equals every candle that
    ever TOUCHED the level, and the reversed scan took the most recent one, so a
    revisit could steal the leg origin from the swing that made it.

    Measured over 1000 lookups: 48 wrong occurrences, all 48 because a later
    candle revisited a level; 30 changed a leg metric. Decoy side HIGH 36 /
    LOW 12, and two distinct forms:

        a revisit outranking its OWN pivot                   40
        a revisit outranking the OTHER side's NEWER pivot     8

    The second form is the one that shows why price could never have been a safe
    identity mechanism. The search matched each side independently and returned
    `max(...)`, so it asked "which of these two prices was TOUCHED most
    recently" when the question is "which of these two authoritative
    OCCURRENCES happened most recently". On 1m at 15:55 a high revisit at 15:51
    outranked a swing low made at 15:45, and the leg began at a candle that was
    not a pivot on either side.

    The producer now publishes the pivot index of the exact occurrence each
    level came from, in THIS list's index space, so identity is carried rather
    than reconstructed. The "later of the two sides" doctrine is unchanged; only
    the identity mechanism is.
    """
    if not isinstance(struct, dict) or not candles:
        return None
    found = []
    for key in ("last_swing_high_pivot_index", "last_swing_low_pivot_index"):
        idx = struct.get(key)
        # NO PRICE FALLBACK. An absent, malformed or out-of-range index means
        # the occurrence cannot be identified in this series, and unknown must
        # stay unknown -- `_leg_slice` already owns the bounded fallback window.
        # Searching by price here is exactly the second identity authority this
        # unit exists to delete.
        if isinstance(idx, bool) or not isinstance(idx, int):
            continue
        if 0 <= idx < len(candles):
            found.append(idx)
    return max(found) if found else None


def _leg_slice(candles: list, struct: dict) -> list:
    """The candles composing the current auction leg, always bounded.

    Falls back to a fixed recent window rather than the full history when no
    pivot is available — the unbounded window is the defect being fixed, so no
    path may reintroduce it while leg scoping is enabled.
    """
    from structure import po3_config as cfg
    if not cfg.leg_scope_enabled():
        return candles
    n = len(candles)
    idx = _leg_start_index(candles, struct)
    leg_len = (n - idx) if idx is not None else cfg.LEG_FALLBACK_CANDLES
    leg_len = max(cfg.LEG_MIN_CANDLES, min(cfg.LEG_MAX_CANDLES, leg_len))
    return candles[-leg_len:] if leg_len < n else candles


def _follow_through(candles: list, tf: str = None) -> int:
    """Consecutive candles at the tail moving in the same direction.

    STEP 4B.12 §4 UNIT 5 — CONSECUTIVE MEANS CONSECUTIVE MARKET BARS.

    This counted adjacent ARRAY elements. When a venue-open bucket has no
    observation, `build_timeframes` emits no bucket at all, so its neighbours
    become array-adjacent and this walked straight through the hole. Measured
    over 1000 evaluations: 29 of 426 multi-bar runs spanned a missing expected
    bucket, from three unique holes (15m 18:00, 3m 18:09, 5m 18:10). On 3m at
    18:14 it reported a FOUR-bar bearish run where market time supports ONE.

    Credit is unchanged -- `min(run * 5, 15)`, same baseline, same state gates.
    Only the evidentiary input is corrected: the run must be market-contiguous.

    `tf` is optional so existing callers and fixtures keep working; without it
    the continuity authority infers the step from the observations themselves.
    """
    from market_data.evidence_continuity import authoritative_trailing_run
    verdict = authoritative_trailing_run(candles, tf, lambda c: c.get("direction"))
    return verdict["authoritative_run"]


def _observed_follow_through(candles: list) -> int:
    """The raw array run, preserved as an OBSERVATION.

    MODEL B: seeing six same-direction neighbours is a true statement about the
    array. It is simply not proof that six consecutive market bars occurred, so
    it may not buy deterministic credit. The observation is kept rather than
    overwritten -- `market_events` already publishes exactly this distinction.
    """
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


def detect_expansion(candles: list, atr_result: dict, tf: str = None,
                     struct: dict = None) -> dict:
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

    LEG-SCOPE: `struct` (this timeframe's analyze_structure output) scopes the
    conviction ratios — directional_efficiency, body_dominance,
    range_acceleration — to the current auction leg instead of the whole
    history. Without it they decay toward neutral as history grows and stop
    describing present behaviour. Omitting `struct` still bounds the window
    (LEG_FALLBACK_CANDLES); only PO3_LEG_SCOPED_METRICS=off restores the
    unbounded legacy read.
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
            "leg_candles": 0,
            "leg_scoped": False,
        }

    atr = atr_result["atr"]
    atr_trend = atr_result["atr_trend"]

    # Local import keeps the legacy path free of the structure package when the
    # gate is unused (tf is None), and avoids a hard import cycle.
    from structure import po3_config as cfg
    gate_on = cfg.gate_enabled() and tf is not None

    # ── ATR dead-band ─────────────────────────────────────────────────────────
    disp_threshold = max(atr * cfg.K_ATR, cfg.f_disp(tf)) if gate_on else atr * cfg.K_ATR

    # ── Leg scope ─────────────────────────────────────────────────────────────
    # Conviction ratios describe the CURRENT auction leg, not the whole dataset.
    # follow-through / displacement / exhaustion are already tail-bounded and
    # keep reading the full series.
    leg = _leg_slice(candles, struct)
    dir_eff = _directional_efficiency(leg)
    body_dom = _body_dominance(leg)
    range_accel = _range_acceleration(leg)
    # UNIT 5: the tf is the horizon the continuity authority needs to know
    # which buckets the venue was scheduled to print. Telemetry keeps the raw
    # observation beside the authorised credit so the distinction stays visible.
    follow_count = _follow_through(candles, tf)
    observed_follow = _observed_follow_through(candles)
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
        # Telemetry: which slice the conviction ratios actually described.
        "leg_candles": len(leg),
        "leg_scoped": len(leg) < len(candles),
        # UNIT 5 — OBSERVATION vs AUTHORITY, both kept, both named explicitly.
        #
        # NOT `follow_through_run`. `snapshot_builder` nests the displacement
        # block one level down as `expansion[tf]["displacement"]`, and that
        # block has published `follow_through_run` = the OBSERVED array run
        # since long before this unit -- `market_events` consumes it under that
        # meaning. Publishing a sibling of the same name carrying the opposite
        # proposition would be the §4 hazard in mirror form: not changing an
        # existing fact's meaning, but minting a new fact that contradicts an
        # established name one level away. Neither key existed here before, so
        # nothing is renamed and no consumer is disturbed -- both are simply
        # spelled out. When they differ, an expected bucket had no observation
        # and deterministic credit was withheld; that scar is readable here.
        "follow_through_authorised_run": follow_count,
        "follow_through_observed_run": observed_follow,
    }
