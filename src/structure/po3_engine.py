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

    # VECTOR-3 — when the expansion read was magnitude-gated (sub-floor physical
    # travel), suppress the bonuses that derive conviction from the now-neutralised
    # ratio metrics. disp is already forced False upstream; this additionally stops
    # the attenuated dir_eff (~0.5) from leaking the dir_eff>=0.40 distribution
    # bonus. Volatility/structure/liquidity-sourced bonuses are unaffected.
    gated      = exp.get("magnitude_gated", False)

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
    # Confluence, not "find a sweep". manipulation_detector scores external
    # sweeps, internal raids, failure swings, failed breakouts, rejections and
    # rapid reversals over a lookback window, and carries a per-component
    # breakdown for audit. A sweep is one expression of manipulation; a failure
    # swing needs no liquidity taken at all.
    #
    # Legacy fallback: callers that build `liq` by hand (and every existing test)
    # supply no "manipulation" block, so the original sweep/reclaim/failed_bo
    # scoring still applies for them — unchanged, bit for bit.
    manip_block = liq.get("manipulation")
    if isinstance(manip_block, dict) and "score" in manip_block:
        manip = int(manip_block.get("score") or 0)
    else:
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
    if not gated and exp_state in ("healthy_expansion", "mature_expansion"):
        distrib += 25
    if not gated and dir_eff >= 0.40:
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

    # VECTOR-3 — sub-floor physical movement cannot author HIGH-CONVICTION phases.
    # The mission: "tiny clean candles on flat tape must not produce expansion,
    # distribution, MANIPULATION, or delivery-state labels." A sweep that crosses an
    # equal high by a cent on a 0.6pt window is noise, not an institutional raid; a
    # micro "MSS" on dead tape is not a structural shift. When this timeframe is
    # magnitude-gated, only accumulation/no_phase may score — manipulation,
    # distribution and transition are zeroed. Real raids/breaks move price above the
    # window floor (kappa>0, not gated) and are unaffected.
    if gated:
        manip = 0
        distrib = 0
        trans = 0

    return {"accumulation": accum, "manipulation": manip,
            "distribution": distrib, "transition": trans}


# ── Direction Inference ───────────────────────────────────────────────────────

def _directions(phase: str, sweep_dir, bias: str) -> tuple:
    """
    Returns (manipulation_direction, manip_source,
             distribution_direction, dist_source).

    Phase AB-2C — PO3 directional outputs derive ONLY from sweep/liquidity
    semantics. The pre-AB-2C fallback
        distribution_direction = manipulation_direction OR structure_bias
    is REMOVED: when no sweep direction exists, distribution_direction is None
    with source 'fallback_none'. Structure bias never authors a PO3 direction.
    `bias` is accepted only to be ignored (kept for signature stability /
    witness logging); it is intentionally unused.
    """
    manip_dir = None
    manip_src = "fallback_none"
    dist_dir  = None
    dist_src  = "fallback_none"

    if sweep_dir == "below_low":
        manip_dir, manip_src = "bullish", "sweep_semantics"   # swept sell stops → bullish intent
    elif sweep_dir == "above_high":
        manip_dir, manip_src = "bearish", "sweep_semantics"   # swept buy stops → bearish intent

    if phase == "distribution" and manip_dir is not None:
        # Distribution direction inherits the SWEEP-derived manipulation
        # direction only. No structure-bias fallback (AB-2C).
        dist_dir, dist_src = manip_dir, "sweep_semantics"

    if phase not in ("manipulation", "transition", "distribution"):
        manip_dir, manip_src = None, "fallback_none"

    return manip_dir, manip_src, dist_dir, dist_src


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

    manip_dir, manip_src, dist_dir, dist_src = _directions(phase, sweep_dir, bias)

    # VECTOR-3 — additive evidence the stability manager (po3_alignment_manager)
    # consumes for phase dead-band + alignment hysteresis. Pure: derived only from
    # this scan's inputs. A material event permits immediate (non-hysteretic)
    # phase/alignment change because it reflects real structural displacement.
    runner_up = sorted(scores.values(), reverse=True)[1] if len(scores) > 1 else 0
    # A material event must clear the magnitude floor — a sweep/break on sub-floor
    # tape is noise and must NOT grant an immediate (non-hysteretic) alignment move.
    gated_tf = exp.get("magnitude_gated", False)
    material_event = (not gated_tf) and bool(
        mss
        or sweep                                  # genuine raid (price moved above floor)
        or disp                                   # displacement is floor-gated upstream
        or exp_state in ("healthy_expansion", "mature_expansion")
    )

    # AB-2C — delivery direction is the strongest available PO3 direction, with
    # provenance. distribution preferred over manipulation; both sweep-derived.
    if dist_dir is not None:
        delivery_dir, delivery_src = dist_dir, dist_src
    elif manip_dir is not None:
        delivery_dir, delivery_src = manip_dir, manip_src
    else:
        delivery_dir, delivery_src = None, "fallback_none"

    return {
        "phase":                  phase,
        "phase_confidence":       phase_conf,
        "manipulation_direction": manip_dir,
        "distribution_direction": dist_dir,
        # AB-2C — provenance for every PO3 directional output. Valid non-structure
        # sources only; structure can never appear here.
        "manipulation_direction_source": manip_src,
        "distribution_direction_source": dist_src,
        "delivery_direction":            delivery_dir,
        "delivery_direction_source":     delivery_src,
        "compression_score":      comp,
        # VECTOR-3 additive fields (consumed by po3_alignment_manager; ignored by
        # all legacy consumers).
        "phase_scores":           scores,
        "winner_score":           best_s,
        "runner_up_score":        runner_up,
        "material_event":         material_event,
        "magnitude_gated":        exp.get("magnitude_gated", False),
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
