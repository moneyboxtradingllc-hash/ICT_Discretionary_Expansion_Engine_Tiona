"""
Phase 5B — AI Outcome Scorer.
Scores whether the AI was directionally helpful after a trade closes.
OBSERVE_ONLY — no decision logic, no execution influence.

Rules:
  realized_r > 0 + AI agreed with playbook  → helpful
  realized_r > 0 + AI disagreed             → harmful  (disagreement was wrong)
  realized_r < 0 + AI agreed with playbook  → harmful  (agreement was wrong)
  realized_r < 0 + AI disagreed             → helpful  (disagreement was right)
  realized_r == 0                            → neutral
  data missing                               → unknown
"""

_TERMINAL_CLOSED = frozenset({"closed", "externally_closed"})


def score_ai_outcome(trade_record: dict) -> dict:
    """
    Score AI usefulness after trade closure.
    Never raises. Returns safe 'unknown' result on any error.
    confidence_modifier is ALWAYS 0. authority_level is ALWAYS 'observe_only'.
    """
    try:
        return _score(trade_record or {})
    except Exception as exc:
        return _safe_unknown([f"ai outcome scoring error: {exc}"])


def _score(trade: dict) -> dict:
    order_status = (trade.get("order_status") or "").lower()
    realized_r   = trade.get("realized_r")

    if order_status not in _TERMINAL_CLOSED:
        return _safe_unknown(["trade not yet closed"])
    if realized_r is None:
        return _safe_unknown(["realized_r unknown — cannot score"])

    r             = float(realized_r)
    side          = (trade.get("side") or "buy").lower()
    trade_dir     = "bullish" if side == "buy" else "bearish"
    ai_dir        = (trade.get("ai_direction_at_entry") or "unknown").lower()
    agree_pb      = trade.get("ai_agreement_with_playbook")
    fusion_status = (trade.get("confidence_fusion_status_at_entry") or "unknown").lower()
    ai_conf       = int(trade.get("ai_confidence_at_entry", 0) or 0)

    # Missing data guard
    if agree_pb is None:
        return _safe_unknown(["ai_agreement_with_playbook not recorded at entry"])

    agree_pb = bool(agree_pb)

    # Directional correctness
    ai_was_correct = _directional_correctness(ai_dir, trade_dir, r)

    # Agreement outcome label
    agree_risk = trade.get("ai_agreement_with_risk")
    ai_agreement_outcome = _agreement_outcome(agree_pb, agree_risk)

    # Confidence quality
    ai_confidence_quality = _confidence_quality(ai_conf, r)

    # Value label (primary signal per spec rules)
    if r == 0.0:
        ai_value_label = "neutral"
    elif r > 0:
        ai_value_label = "helpful" if agree_pb else "harmful"
    else:
        ai_value_label = "harmful" if agree_pb else "helpful"

    reason = _build_reason(r, ai_dir, trade_dir, agree_pb, ai_value_label)

    return {
        "scored":                       True,
        "ai_was_directionally_correct": ai_was_correct,
        "ai_agreement_outcome":         ai_agreement_outcome,
        "ai_confidence_quality":        ai_confidence_quality,
        "ai_value_label":               ai_value_label,
        "reason":                       reason,
        "authority_level":              "observe_only",
        "confidence_modifier":          0,
    }


def _directional_correctness(ai_dir: str, trade_dir: str, r: float):
    if ai_dir == "unknown" or ai_dir == "neutral":
        return None
    ai_aligned = (
        (ai_dir == "bullish" and trade_dir == "bullish")
        or (ai_dir == "bearish" and trade_dir == "bearish")
    )
    if ai_aligned:
        return r > 0
    else:
        # AI opposed trade direction
        return r < 0  # AI was right if the trade lost


def _agreement_outcome(agree_pb: bool, agree_risk) -> str:
    agree_risk_bool = bool(agree_risk) if agree_risk is not None else True
    if agree_pb and agree_risk_bool:
        return "full_agreement"
    if agree_pb and not agree_risk_bool:
        return "playbook_only"
    if not agree_pb and agree_risk_bool:
        return "risk_only"
    return "full_disagreement"


def _confidence_quality(ai_conf: int, r: float) -> str:
    if r > 0:
        if ai_conf >= 50:
            return "good"
        if ai_conf >= 30:
            return "neutral"
        return "poor"
    if r < 0:
        if ai_conf >= 70:
            return "poor"  # overconfident on a loser
        if ai_conf >= 50:
            return "neutral"
        return "good"      # appropriately cautious
    return "neutral"


def _build_reason(r: float, ai_dir: str, trade_dir: str, agree_pb: bool, label: str) -> str:
    dir_str   = "bullish" if trade_dir == "bullish" else "bearish"
    outcome   = "won" if r > 0 else ("lost" if r < 0 else "breakeven")
    agree_str = "agreed with" if agree_pb else "disagreed with"
    return (
        f"AI {agree_str} {dir_str} playbook; "
        f"trade {outcome} (realized_r={r:.4f}); AI label={label}"
    )


def _safe_unknown(notes: list) -> dict:
    return {
        "scored":                       False,
        "ai_was_directionally_correct": None,
        "ai_agreement_outcome":         "unknown",
        "ai_confidence_quality":        "unknown",
        "ai_value_label":               "unknown",
        "reason":                       notes[0] if notes else "unknown",
        "authority_level":              "observe_only",
        "confidence_modifier":          0,
    }
