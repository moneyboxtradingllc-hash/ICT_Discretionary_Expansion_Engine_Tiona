"""
Phase 5A — Regime Feature Extractor.
Derives scored feature signals from the assembled snapshot.
OBSERVE_ONLY — no decision logic, no execution influence.
"""
from regime_classification.structure_hierarchy import (
    swing_sequence, range_metrics, htf_authority, classify_relationship,
    range_state, dealing_range,
)

# The vocabulary detect_expansion._state() actually emits.
_EXPANDING_STATES   = ("early_expansion", "healthy_expansion", "mature_expansion")
_CONTRACTING_STATES = ("compression",)


def extract_regime_features(snapshot: dict, raw_data=None, settled_data=None,
                            *, allow_uncadenced: bool = False) -> dict:
    """
    Extract regime feature signals from a fully assembled snapshot.
    Returns the 12 public fields plus internal flags used by regime_classifier.
    Never raises.

    CONTINUITY-2E: two series, deliberately. `raw_data` is realtime (forming
    higher-timeframe bucket included); `settled_data` has unfinished buckets
    removed. Reads that describe NOW take raw; statistics that claim CONFIRMED
    structure take settled.
    """
    try:
        return _extract(snapshot, raw_data, settled_data,
                        allow_uncadenced=allow_uncadenced)
    except Exception:
        return _zero_features()


def _settled_series(settled_data, raw_data, tf: str) -> list:
    """The settled series for `tf`, or the realtime one when no settled view was
    supplied.

    The fallback is the CONTINUITY-2D policy, not a hole: candles arriving here
    are already normalised, and normalisation whitelists the `complete`/`members`
    flags away, so this layer cannot re-derive settledness on its own. A caller
    that supplies no settled view has told us nothing about completeness, and 2D
    ruled that unlabelled history is treated as settled because inventing
    incompleteness would silently delete real structure.

    In production `snapshot_builder` always supplies it; that is pinned by test
    rather than assumed here.
    """
    series = (settled_data or {}).get(tf)
    if series is None:
        return (raw_data or {}).get(tf) or []
    return series


def _extract(snapshot: dict, raw_data=None, settled_data=None, *,
             allow_uncadenced: bool = False) -> dict:
    structure  = snapshot.get("structure",  {}) or {}
    volatility = snapshot.get("volatility", {}) or {}
    expansion  = snapshot.get("expansion",  {}) or {}
    liquidity  = snapshot.get("liquidity",  {}) or {}
    po3        = snapshot.get("po3",        {}) or {}
    ai_ctx     = snapshot.get("ai_context", {}) or {}

    s15 = structure.get("15m", {}) or {}
    s5  = structure.get("5m",  {}) or {}

    bias_15 = (s15.get("bias") or "neutral").lower()
    bias_5  = (s5.get("bias")  or "neutral").lower()
    bos_15  = bool(s15.get("bos",  False))
    bos_5   = bool(s5.get("bos",   False))
    mss_15  = bool(s15.get("mss",  False))
    mss_5   = bool(s5.get("mss",   False))

    v15       = volatility.get("15m", {}) or {}
    vol_state = (v15.get("state") or "normal").lower()

    e15             = expansion.get("15m", {}) or {}
    e5              = expansion.get("5m",  {}) or {}
    exp_state_15    = (e15.get("state") or "normal").lower()
    exp_score_15    = int(e15.get("expansion_score", 0) or 0)
    displacement_15 = bool(e15.get("displacement_detected", False))
    exp_state_5     = (e5.get("state") or "normal").lower()
    displacement_5  = bool(e5.get("displacement_detected", False))

    # detect_expansion._state() emits compression / early_expansion /
    # healthy_expansion / mature_expansion / exhaustion_risk. It has never
    # returned "expanding" or "contracting", so both flags below were permanently
    # False — trend_score's +15 and chop_score's +15 could not fire, and
    # chop_score's `elif not is_expanding` +5 always did.
    is_expanding     = exp_state_15 in _EXPANDING_STATES or exp_state_5 in _EXPANDING_STATES
    is_contracting   = exp_state_15 in _CONTRACTING_STATES and exp_state_5 in _CONTRACTING_STATES
    displacement_any = displacement_15 or displacement_5

    sweep_reclaim_any = False
    for tf in ("15m", "5m", "3m", "1m"):
        liq = (liquidity.get(tf) or {})
        if liq.get("sweep_detected") and liq.get("reclaim_detected"):
            sweep_reclaim_any = True
            break

    po3_15      = po3.get("15m", {}) or {}
    po3_5       = po3.get("5m",  {}) or {}
    po3_dist_15 = (po3_15.get("distribution_direction") or "").lower()
    po3_dist_5  = (po3_5.get("distribution_direction")  or "").lower()

    both_aligned_bull = bias_15 == "bullish" and bias_5 == "bullish"
    both_aligned_bear = bias_15 == "bearish" and bias_5 == "bearish"
    both_neutral      = bias_15 == "neutral"  and bias_5 == "neutral"

    # ── Timeframe hierarchy ───────────────────────────────────────────────────
    # 15m establishes directional authority and holds it until price violates the
    # level that would invalidate the trend; 5m describes the phase inside that
    # authority. Computed here because is_bullish / is_bearish depend on it.
    ctx_candles = (raw_data or {}).get("5m") or (raw_data or {}).get("15m") or []
    last_price = ctx_candles[-1]["close"] if ctx_candles else None
    # DOCTRINE: direction comes from Liquidity and PO3, never from structure.
    # `structure` is passed for CONFIRMATION reporting only. narrative_authority
    # is built later in snapshot_builder than this runs, so the liquidity draw is
    # usually absent here and PO3 authors instead — authority #2 of the order.
    authority = htf_authority(s15, last_price, "15m",
                              narrative=snapshot.get("narrative_authority"),
                              po3=po3, liquidity=liquidity)
    relationship = classify_relationship(authority, bias_5)
    # CONTINUITY-2E (2026-08-11). swing_sequence calls find_swings, which
    # confirms a pivot against neighbours on BOTH sides -- so a forming 15m
    # bucket was supplying right-side confirmation for structure published as
    # confirmed. That is the exact defect 2D fixed in analyze_structure,
    # reproduced one layer over: measured on the live tape, a 15m swing high of
    # 29,805.0 rested on a 6-of-15 bucket and vanished when it closed higher.
    #
    # Settled evidence only. The realtime reads below (last price, range
    # metrics, range state) keep the forming bar on purpose -- they describe now.
    # STEP 4B.12 §4 UNIT 1 — the sequence is computed from PIVOTS, so it needs
    # the same canonical neighbourhood authority as every other swing consumer.
    # Evidence is built for whichever timeframe actually supplied the series;
    # `swing_sequence` then projects it onto its own bounded window rather than
    # being handed swings from a wider history.
    # LUNA-SWING-SEQUENCE-TRUTH-1 (2026-09-01). SUFFICIENCY, NOT PRESENCE.
    #
    # This used to take 15m whenever a 15m series EXISTED and fall through to 5m
    # only when it was entirely absent. Measured live: 19 settled 15m bars were
    # present, `find_swings` returned ZERO pivots from them ("only 0 swing highs
    # / 0 swing lows in window"), the guard never fired because the series was
    # not empty, and the sequence reported `unknown` while 59 settled 5m bars and
    # 99 settled 3m bars sat unconsulted.
    #
    # "Candles exist" was never the question. The question is whether the
    # candidate timeframe produced enough confirmed pivots to state a
    # relationship, and that is the EXISTING sufficiency law inside
    # `swing_sequence` -- read here rather than re-implemented.
    seq, _seq_tf, _seq_attempts = None, None, []
    for _tf, _minutes in (("15m", 15), ("5m", 5), ("3m", 3)):
        _cands = _settled_series(settled_data, raw_data, _tf)
        if not _cands:
            _seq_attempts.append("%s: no settled series" % _tf)
            continue
        from market_data.swing_evidence import build_swing_evidence
        _ev = build_swing_evidence(_cands, (raw_data or {}).get(_tf), _minutes)
        _try = swing_sequence(_cands, swing_evidence=_ev,
                              allow_uncadenced=allow_uncadenced)
        _seq_attempts.append("%s: %d highs / %d lows" % (
            _tf, _try.get("swing_highs", 0), _try.get("swing_lows", 0)))
        if _try.get("sequence") != "unknown":
            seq, _seq_tf = _try, _tf
            break
        if seq is None:
            seq, _seq_tf = _try, _tf      # keep the first attempt's detail
    if seq is None:
        # The `ctx_candles` fallback carries no known timeframe, so no evidence
        # can be resolved for it and its pivots are withheld. Failing closed is
        # the doctrine: unavailable evidence may not license legacy array
        # adjacency.
        seq = swing_sequence(ctx_candles, swing_evidence=None,
                             allow_uncadenced=allow_uncadenced)
        _seq_tf = None
    seq = dict(seq)
    seq["source_timeframe"] = _seq_tf
    seq["fallback_trace"] = _seq_attempts
    rng = range_metrics(ctx_candles)
    rng_state = range_state(ctx_candles)
    deal_range = dealing_range(structure, last_price)
    htf_authoritative = authority["bias"] in ("bullish", "bearish") and authority["intact"]

    # A retracement must not erase the dominant bias. Requiring 5m agreement meant
    # a pullback — definitionally 5m-opposed — flipped is_bearish to False, so
    # trend_down could not fire even at trend_score 55 and the label fell to
    # `unknown`. Authority is ADDED to the legacy agreement test, never subtracted,
    # so nothing that previously read directional stops doing so.
    is_bullish = (bias_15 == "bullish" and bias_5 in ("bullish", "neutral")) or \
                 (htf_authoritative and authority["bias"] == "bullish")
    is_bearish = (bias_15 == "bearish" and bias_5 in ("bearish", "neutral")) or \
                 (htf_authoritative and authority["bias"] == "bearish")

    db = (ai_ctx.get("directional_bias") or "neutral").lower()
    directional_slope = (
        1 if "bullish" in db else (-1 if "bearish" in db else 0)
    )

    mss_any  = mss_15 or mss_5
    po3_bull = po3_dist_15 in ("bullish", "up") or po3_dist_5 in ("bullish", "up")
    po3_bear = po3_dist_15 in ("bearish", "down") or po3_dist_5 in ("bearish", "down")

    # ── Trend Score ───────────────────────────────────────────────────────────
    # `both_aligned` previously gated the +35, so a retracement took the +15
    # branch and the engine could not name a trend during a pullback inside one.
    trend_score = 0
    if both_aligned_bull or both_aligned_bear:
        trend_score += 35
    elif htf_authoritative and relationship["relationship"] == "retracement":
        # A retracement is evidence of trend, not a contradiction of it. The HTF
        # still owns direction; only the local phase differs.
        trend_score += 35
    elif bias_15 not in ("neutral", ""):
        trend_score += 15
    if bos_15:
        trend_score += 15
    if bos_5:
        trend_score += 10
    if mss_any:
        trend_score += 5
    if is_expanding:
        trend_score += 15
    if displacement_any:
        trend_score += 5
    if (is_bullish and po3_bull) or (is_bearish and po3_bear):
        trend_score += 10
    if directional_slope != 0:
        trend_score += 5

    # ── Chop Score ────────────────────────────────────────────────────────────
    chop_score = 0
    if both_neutral:
        chop_score += 40
    if not bos_15 and not bos_5:
        chop_score += 20
    if is_contracting:
        chop_score += 15
    elif not is_expanding:
        chop_score += 5
    if vol_state == "low":
        chop_score += 15
    if po3_bull and po3_bear:
        chop_score += 10

    # ── Reversal Score ────────────────────────────────────────────────────────
    reversal_score = 0
    if sweep_reclaim_any:
        reversal_score += 40
    if mss_15:
        reversal_score += 30
    elif mss_5:
        reversal_score += 20
    if (is_bullish and directional_slope < 0) or (is_bearish and directional_slope > 0):
        reversal_score += 10

    structure_bias = "bullish" if is_bullish else ("bearish" if is_bearish else "neutral")

    return {
        # Public interface (12 fields from spec)
        "range_size":              float(rng["range_size"]),
        "atr_proxy":               float(exp_score_15),
        "directional_slope":       float(directional_slope),
        "higher_highs":            seq["higher_highs"],
        "lower_highs":             seq["lower_highs"],
        "higher_lows":             seq["higher_lows"],
        "lower_lows":              seq["lower_lows"],
        "swing_sequence":          seq["sequence"],
        "swing_source_timeframe":  seq.get("source_timeframe"),
        "swing_fallback_trace":    seq.get("fallback_trace") or [],
        "close_position_in_range": float(rng["close_position_in_range"]),
        # Hierarchy telemetry — authority and the phase inside it.
        "htf_authority":           authority,
        "htf_relationship":        relationship["relationship"],
        "htf_reasoning":           relationship["reason"],
        "swing_detail":            seq["detail"],
        "bias_15m":                bias_15,
        "bias_5m":                 bias_5,
        "range_state":             rng_state["range_state"],
        "range_state_detail":      rng_state["detail"],
        "dealing_range":           deal_range,
        "volatility_state":        vol_state,
        "expansion_state":         exp_state_15,
        "structure_bias":          structure_bias,
        "chop_score":              min(chop_score,     100),
        "trend_score":             min(trend_score,    100),
        "reversal_score":          min(reversal_score, 100),
        # Internal flags for regime_classifier
        "is_bullish":              is_bullish,
        "is_bearish":              is_bearish,
        "is_expanding":            is_expanding,
        "is_contracting":          is_contracting,
        "displacement_any":        displacement_any,
        "exp_score_15":            exp_score_15,
        "mss_any":                 mss_any,
        "sweep_reclaim_any":       sweep_reclaim_any,
    }


def _zero_features() -> dict:
    return {
        "range_size": 0.0, "atr_proxy": 0.0, "directional_slope": 0.0,
        "higher_highs": 0, "lower_highs": 0, "higher_lows": 0, "lower_lows": 0,
        "swing_sequence": "unknown", "close_position_in_range": 0.0,
        "htf_authority": {"timeframe": None, "bias": "neutral", "invalidation": None,
                          "intact": False, "detail": "feature extraction failed"},
        "htf_relationship": "no_authority",
        "htf_reasoning": "feature extraction failed — no authority claimed",
        "swing_detail": "feature extraction failed",
        "bias_15m": "neutral", "bias_5m": "neutral",
        "range_state": "unknown", "range_state_detail": "feature extraction failed",
        "dealing_range": {"source_tf": None, "high": None, "low": None,
                          "midpoint": None, "position": None, "zone": "unknown"},
        "volatility_state": "unknown", "expansion_state": "unknown",
        "structure_bias": "neutral",
        "chop_score": 0, "trend_score": 0, "reversal_score": 0,
        "is_bullish": False, "is_bearish": False, "is_expanding": False,
        "is_contracting": False,
        "displacement_any": False, "exp_score_15": 0,
        "mss_any": False, "sweep_reclaim_any": False,
    }
