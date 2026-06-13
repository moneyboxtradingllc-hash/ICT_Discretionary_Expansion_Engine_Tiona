"""
Phase 5G.1 — Shared Market Context.

Single normalized market understanding, aggregated from the assembled
snapshot. Every council member (Phase 5G.2) reads THIS object — the same
context at the same moment — so local truths cannot drift from global truth.

AGGREGATION ONLY:
  - No decision logic.
  - No scoring changes.
  - No execution influence.
  - Never raises — every field degrades to a safe unknown/default.
"""

# PO3 alignment quality -> delivery confidence (0-100)
_PO3_DELIVERY_CONFIDENCE = {
    "full_distribution_alignment":  85,
    "manipulation_to_distribution": 70,
    "accumulation_building":        45,
    "mixed":                        25,
    "no_clear_alignment":           10,
}

_INTACT_PO3       = frozenset({"full_distribution_alignment", "manipulation_to_distribution"})
_INTACT_STRUCTURE = frozenset({"full", "strong", "partial"})

# Risk tier -> multiplier fallback when risk_multiplier is absent (old snapshots)
_TIER_MULTIPLIER = {"normal": 1.0, "reduced": 0.75, "minimal": 0.5, "blocked": 0.0}


def _preferred_candidate(snapshot: dict) -> dict:
    tb    = snapshot.get("toolbox", {}) or {}
    pref  = tb.get("preferred_tool", "") or ""
    cands = tb.get("tool_candidates", []) or []
    return next((c for c in cands if c.get("tool") == pref), {}) if cands else {}


def _current_price(snapshot: dict) -> "float | None":
    """Most granular last close; falls back to position monitor, then zone data."""
    tfs = snapshot.get("timeframes", {}) or {}
    for tf in ("1m", "3m", "5m", "15m"):
        lc = (tfs.get(tf) or {}).get("last_candle")
        if lc and lc.get("close") is not None:
            try:
                return round(float(lc["close"]), 4)
            except (TypeError, ValueError):
                pass

    pm_price = (snapshot.get("position_monitor", {}) or {}).get("current_price")
    if pm_price is not None:
        try:
            return round(float(pm_price), 4)
        except (TypeError, ValueError):
            pass

    pl = _preferred_candidate(snapshot).get("price_level", {}) or {}
    cp = pl.get("current_price")
    if cp is not None:
        try:
            return round(float(cp), 4)
        except (TypeError, ValueError):
            pass
    return None


def _delivery(snapshot: dict) -> tuple:
    """
    Derive (delivery_state, delivery_confidence, continuation_intact)
    from PO3 + structure, with ai_context fallback when PO3 is unavailable.
    """
    po3    = snapshot.get("po3", {}) or {}
    struct = snapshot.get("structure", {}) or {}
    ai_ctx = snapshot.get("ai_context", {}) or {}

    po3_align = (po3.get("alignment") or "").lower()

    # Direction: PO3 distribution first, then manipulation, then AI bias
    direction = None
    for tf in ("15m", "5m"):
        d = ((po3.get(tf) or {}).get("distribution_direction") or "").lower()
        if d in ("bullish", "bearish"):
            direction = d
            break
    if direction is None:
        for tf in ("15m", "5m"):
            m = ((po3.get(tf) or {}).get("manipulation_direction") or "").lower()
            if m in ("bullish", "bearish"):
                direction = m
                break

    if po3_align in _PO3_DELIVERY_CONFIDENCE:
        confidence = _PO3_DELIVERY_CONFIDENCE[po3_align]
        state = f"{direction}_delivery" if direction else po3_align
    else:
        # AB-2B — PO3/delivery absent. Delivery must NOT be synthesized from
        # structure bias (the old `{bias}_bias_only` fallback was a structure
        # leak into delivery state). When a structure bias EXISTS we record the
        # deliberate refusal; with nothing at all we degrade to "unknown".
        bias = (ai_ctx.get("directional_bias") or "neutral").lower()
        if bias in ("bullish", "bearish"):
            state, confidence = "insufficient_delivery_evidence", 0
        else:
            state, confidence = "unknown", 0

    struct_align = (struct.get("alignment") or "neutral").lower()
    continuation_intact = (
        po3_align in _INTACT_PO3 and struct_align in _INTACT_STRUCTURE
    )

    return state, confidence, continuation_intact


def _exhaustion_present(snapshot: dict, regime: dict) -> bool:
    if (regime.get("expansion_state") or "").lower() == "exhaustion_risk":
        return True
    expansion = snapshot.get("expansion", {}) or {}
    for tf in ("15m", "5m"):
        ex = expansion.get(tf) or {}
        if ex.get("state") == "exhaustion_risk" or ex.get("exhaustion_risk") == "high":
            return True
    return False


def _reversal_present(snapshot: dict) -> bool:
    liquidity = snapshot.get("liquidity", {}) or {}
    structure = snapshot.get("structure", {}) or {}
    for tf in ("15m", "5m", "3m", "1m"):
        liq = liquidity.get(tf) or {}
        if liq.get("sweep_detected") and liq.get("reclaim_detected"):
            return True
    for tf in ("15m", "5m"):
        if (structure.get(tf) or {}).get("mss"):
            return True
    return False


def _risk_multiplier(snapshot: dict) -> float:
    risk = snapshot.get("risk", {}) or {}
    raw  = risk.get("risk_multiplier")
    if raw is not None:
        try:
            return max(0.0, min(1.0, float(raw)))
        except (TypeError, ValueError):
            pass
    tier = (risk.get("risk_tier") or "").lower()
    return _TIER_MULTIPLIER.get(tier, 1.0)


def build_shared_market_context(snapshot: dict, symbol: "str | None" = None) -> dict:
    """
    Phase 5G.1 — Build the SharedMarketContext from an assembled snapshot.
    Aggregation only. Never raises.
    """
    try:
        return _build(snapshot or {}, symbol)
    except Exception as exc:  # noqa: BLE001
        return _empty_context(symbol, error=str(exc))


def _build(snapshot: dict, symbol: "str | None") -> dict:
    regime = snapshot.get("market_regime", {}) or {}
    qual   = snapshot.get("qualification", {}) or {}
    pb     = snapshot.get("playbook", {}) or {}
    sl     = snapshot.get("setup_lifecycle", {}) or {}
    tb     = snapshot.get("toolbox", {}) or {}

    pref_c       = _preferred_candidate(snapshot)
    trigger_prep = pref_c.get("trigger_prep") or {}

    delivery_state, delivery_conf, continuation_intact = _delivery(snapshot)

    return {
        "context_version":      "5G.1",
        "symbol":               symbol or snapshot.get("symbol") or "UNKNOWN",
        "timestamp":            snapshot.get("timestamp", ""),
        "session":              snapshot.get("session", "unknown"),
        # Regime view
        "regime":               (regime.get("regime_label") or "unknown").lower(),
        "regime_confidence":    int(regime.get("confidence", 0) or 0),
        "volatility_state":     (regime.get("volatility_state") or "unknown").lower(),
        "expansion_state":      (regime.get("expansion_state") or "unknown").lower(),
        # Delivery view
        "delivery_state":       delivery_state,
        "delivery_confidence":  delivery_conf,
        "continuation_intact":  continuation_intact,
        "exhaustion_present":   _exhaustion_present(snapshot, regime),
        "reversal_present":     _reversal_present(snapshot),
        # Opportunity view
        "qualification_status": (qual.get("status") or "no_trade").lower(),
        "qualification_score":  int(qual.get("opportunity_score", 0) or 0),
        "playbook":             (pb.get("selected_playbook") or "no_playbook").lower(),
        "playbook_direction":   (pb.get("direction") or "neutral").lower(),
        # Toolbox view
        "toolbox_tool":         (tb.get("preferred_tool") or "no_tool").lower(),
        "trigger_status":       (trigger_prep.get("raw_trigger_status") or "n/a").lower(),
        # Setup + risk view
        "setup_age":            int(sl.get("age_scans", 0) or 0) if sl.get("active") else 0,
        "risk_multiplier":      _risk_multiplier(snapshot),
        # Market state
        "current_price":        _current_price(snapshot),
    }


def _empty_context(symbol: "str | None", error: str = "") -> dict:
    return {
        "context_version":      "5G.1",
        "symbol":               symbol or "UNKNOWN",
        "timestamp":            "",
        "session":              "unknown",
        "regime":               "unknown",
        "regime_confidence":    0,
        "volatility_state":     "unknown",
        "expansion_state":      "unknown",
        "delivery_state":       "unknown",
        "delivery_confidence":  0,
        "continuation_intact":  False,
        "exhaustion_present":   False,
        "reversal_present":     False,
        "qualification_status": "no_trade",
        "qualification_score":  0,
        "playbook":             "no_playbook",
        "playbook_direction":   "neutral",
        "toolbox_tool":         "no_tool",
        "trigger_status":       "n/a",
        "setup_age":            0,
        "risk_multiplier":      1.0,
        "current_price":        None,
        "context_error":        error,
    }
