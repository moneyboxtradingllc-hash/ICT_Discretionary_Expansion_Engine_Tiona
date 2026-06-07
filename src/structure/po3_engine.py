"""
PO3 Engine — classifies each timeframe into a Power of 3 phase by interpreting
pre-computed mechanical evidence. No raw candle math here; inputs are already
processed structure, liquidity, volatility, and expansion dicts.
"""

TIMEFRAMES = ["15m", "5m", "3m", "1m"]

# Minimum score for a phase to "win" over no_phase
PHASE_THRESHOLD = 35

# Normalisation denominators — approximate max score per phase
_MAX = {"accumulation": 100, "manipulation": 100, "distribution": 110, "transition": 125}


# ── Compression Score ─────────────────────────────────────────────────────────

def _compression_score(dir_eff: float, body_dom: float, exp_score: int) -> int:
    """0 = fully expanded / directional, 100 = fully compressed / accumulating."""
    raw = (
        (1.0 - dir_eff) * 50
        + (1.0 - body_dom) * 30
        + max(0, 50 - exp_score) * 0.4
    )
    return max(0, min(100, round(raw)))


# ── Phase Scoring ─────────────────────────────────────────────────────────────

def _score_phases(struct: dict, liq: dict, vol: dict, exp: dict) -> dict:
    vol_state  = vol.get("state", "")
    atr_trend  = vol.get("atr_trend", "stable")
    exp_state  = exp.get("state", "")
    exp_score  = exp.get("expansion_score", 50)
    dir_eff    = exp.get("directional_efficiency", 0.5)
    body_dom   = exp.get("body_dominance", 0.5)
    disp       = exp.get("displacement_detected", False)
    exhaustion = exp.get("exhaustion_risk", "low")

    sweep      = liq.get("sweep_detected", False)
    reclaim    = liq.get("reclaim_detected", False)
    failed_bo  = liq.get("failed_breakout", False)

    bos        = struct.get("bos", False)
    mss        = struct.get("mss", False)
    struct_s   = struct.get("state", "")
    bias       = struct.get("bias", "neutral")

    comp       = _compression_score(dir_eff, body_dom, exp_score)
    clean_disp = disp and dir_eff >= 0.30   # displacement with at least some direction

    # ── Accumulation ──────────────────────────────────────────────────────────
    accum = 0
    if exp_state in ("compression", "early_expansion"):
        accum += 25
    if comp > 60:
        accum += 20
    if dir_eff < 0.25:
        accum += 20
    if struct_s in ("range_bound", "neutral"):
        accum += 15
    if atr_trend in ("falling", "stable") and vol_state not in ("toxic", "explosive"):
        accum += 10
    if not sweep and not clean_disp:
        accum += 10

    # ── Manipulation ──────────────────────────────────────────────────────────
    manip = 0
    if sweep:
        manip += 40
    if reclaim:
        manip += 25
    if failed_bo:
        manip += 25
    if sweep and reclaim:
        manip += 10  # complete sweep+reclaim → high confidence manipulation

    # ── Distribution ──────────────────────────────────────────────────────────
    distrib = 0
    distrib += 30 if clean_disp else (10 if disp else 0)
    if exp_state in ("healthy_expansion", "mature_expansion"):
        distrib += 25
    if dir_eff >= 0.40:
        distrib += 20
    if vol_state in ("expanding", "stable"):
        distrib += 10
    if exhaustion != "high":
        distrib += 10
    if struct_s in ("bullish_continuation", "bearish_continuation"):
        distrib += 15

    # ── Transition ────────────────────────────────────────────────────────────
    trans = 0
    if mss:
        trans += 50
    if bos and (sweep or reclaim):
        trans += 30
    if exp_state == "early_expansion" and (sweep or failed_bo):
        trans += 25
    if struct_s in ("bullish_reversal", "bearish_reversal"):
        trans += 20

    return {"accumulation": accum, "manipulation": manip,
            "distribution": distrib, "transition": trans}


# ── Direction Inference ───────────────────────────────────────────────────────

def _directions(phase: str, sweep_dir, bias: str) -> tuple:
    """Returns (manipulation_direction, distribution_direction)."""
    manip_dir = None
    dist_dir  = None

    if sweep_dir == "below_low":
        manip_dir = "bullish"   # swept sell stops → intent is bullish
    elif sweep_dir == "above_high":
        manip_dir = "bearish"   # swept buy stops → intent is bearish

    if phase == "distribution":
        dist_dir = manip_dir or (bias if bias in ("bullish", "bearish") else None)

    if phase not in ("manipulation", "transition", "distribution"):
        manip_dir = None

    return manip_dir, dist_dir


# ── Notes ─────────────────────────────────────────────────────────────────────

def _notes(phase: str, comp: int, dir_eff: float,
           sweep: bool, reclaim: bool, failed_bo: bool,
           sweep_dir, disp: bool, mss: bool, bos: bool) -> list:
    n = []
    if phase == "accumulation":
        if comp > 70:
            n.append("Tight price compression — accumulation building")
        if dir_eff < 0.15:
            n.append("Very low directional efficiency — price going nowhere")
    elif phase == "manipulation":
        if sweep and reclaim:
            n.append(f"Sweep {sweep_dir} with reclaim — manipulation likely complete")
        elif failed_bo:
            n.append("Failed breakout signals manipulation attempt")
        elif sweep:
            n.append(f"Sweep {sweep_dir} detected — reclaim not yet confirmed")
    elif phase == "distribution":
        if disp:
            n.append("Displacement candle confirmed — distribution active")
        if dir_eff >= 0.55:
            n.append("High directional efficiency — clean delivery")
    elif phase == "transition":
        if mss:
            n.append("MSS detected — structural shift in progress")
        if bos:
            n.append("BOS confirmed — expansion beginning")
    return n


# ── Per-TF Analysis ───────────────────────────────────────────────────────────

def analyze_po3(struct: dict, liq: dict, vol: dict, exp: dict) -> dict:
    scores  = _score_phases(struct, liq, vol, exp)
    best    = max(scores, key=scores.get)
    best_s  = scores[best]
    phase   = best if best_s >= PHASE_THRESHOLD else "no_phase"

    phase_conf = 0
    if phase != "no_phase":
        phase_conf = min(100, round(best_s / _MAX.get(phase, 100) * 100))

    dir_eff   = exp.get("directional_efficiency", 0.5)
    body_dom  = exp.get("body_dominance", 0.5)
    exp_score = exp.get("expansion_score", 50)
    comp      = _compression_score(dir_eff, body_dom, exp_score)

    sweep_dir = liq.get("sweep_direction")
    sweep     = liq.get("sweep_detected", False)
    reclaim   = liq.get("reclaim_detected", False)
    failed_bo = liq.get("failed_breakout", False)
    disp      = exp.get("displacement_detected", False)
    mss       = struct.get("mss", False)
    bos       = struct.get("bos", False)
    bias      = struct.get("bias", "neutral")
    exp_state = exp.get("state", "")

    manip_dir, dist_dir = _directions(phase, sweep_dir, bias)

    return {
        "phase":                  phase,
        "phase_confidence":       phase_conf,
        "manipulation_direction": manip_dir,
        "distribution_direction": dist_dir,
        "compression_score":      comp,
        "sweep_involved":         sweep or failed_bo,
        "expansion_involved":     disp or exp_state in ("healthy_expansion", "mature_expansion"),
        "notes":                  _notes(phase, comp, dir_eff, sweep, reclaim,
                                         failed_bo, sweep_dir, disp, mss, bos),
    }


# ── Cross-TF Alignment ────────────────────────────────────────────────────────

def _po3_alignment(results: dict) -> str:
    phases = [results.get(tf, {}).get("phase", "no_phase") for tf in TIMEFRAMES]

    d_count   = sum(1 for p in phases if p == "distribution")
    m_count   = sum(1 for p in phases if p == "manipulation")
    a_count   = sum(1 for p in phases if p == "accumulation")
    nop_count = sum(1 for p in phases if p == "no_phase")

    if d_count >= 3:
        return "full_distribution_alignment"

    # HTF building (accumulation or manipulation) + LTF beginning to deliver
    htf_setup  = phases[0] in ("accumulation", "manipulation") \
                 or phases[1] in ("accumulation", "manipulation")
    ltf_deliver = phases[2] in ("distribution", "transition") \
                  or phases[3] in ("distribution", "transition")
    if htf_setup and ltf_deliver:
        return "manipulation_to_distribution"

    if a_count >= 2 and d_count == 0 and m_count == 0:
        return "accumulation_building"

    if nop_count >= 3:
        return "no_clear_alignment"

    return "mixed"


# ── Snapshot Entry Point ──────────────────────────────────────────────────────

def analyze_po3_snapshot(structure: dict, liquidity: dict,
                          volatility: dict, expansion: dict) -> dict:
    results = {
        tf: analyze_po3(
            structure.get(tf, {}),
            liquidity.get(tf, {}),
            volatility.get(tf, {}),
            expansion.get(tf, {}),
        )
        for tf in TIMEFRAMES
    }
    results["alignment"] = _po3_alignment(results)
    return results
