"""
Phase 5B — AI Feedback Builder.
Extracts AI state at trade entry time for post-outcome scoring.
OBSERVE_ONLY — no decision logic, no execution influence.
"""


def build_ai_feedback_from_snapshot(snapshot: dict) -> dict:
    """
    Extract AI feedback fields from the assembled snapshot at entry time.
    Never raises. Returns safe defaults on any error.
    confidence_modifier is ALWAYS 0. authority_level is ALWAYS 'observe_only'.
    """
    try:
        return _build(snapshot or {})
    except Exception:
        return _safe_default()


def _build(snapshot: dict) -> dict:
    ai_disc = snapshot.get("ai_discretionary", {}) or {}
    fusion  = snapshot.get("confidence_fusion", {}) or {}
    debate  = snapshot.get("ai_debate",        {}) or {}
    fv      = debate.get("final_verdict",      {}) or {}

    ai_direction      = (ai_disc.get("ai_direction") or "neutral").lower()
    ai_confidence     = int(ai_disc.get("ai_confidence", 0) or 0)
    _agree_pb_raw = ai_disc.get("agreement_with_playbook")
    _agree_rs_raw = ai_disc.get("agreement_with_risk")
    agree_playbook = bool(_agree_pb_raw) if _agree_pb_raw is not None else None
    agree_risk     = bool(_agree_rs_raw) if _agree_rs_raw is not None else None
    ai_mode           = (ai_disc.get("ai_mode") or "internal").lower()
    ai_external_used  = ai_mode in ("external", "hybrid")
    ai_fallback_used  = bool(ai_disc.get("fallback_used", False))
    ai_fallback_reason = ai_disc.get("fallback_cause") or ai_disc.get("fallback_reason") or None
    ai_model_used     = ai_disc.get("model") or None

    mech_conf         = int(fusion.get("mechanical_score", 0) or 0)
    fusion_ai_conf    = int(fusion.get("ai_confidence",    ai_confidence) or ai_confidence)
    fusion_status     = (fusion.get("fusion_status") or "unknown").lower()
    conf_delta        = abs(mech_conf - fusion_ai_conf)

    dom_thesis  = (fv.get("dominant_thesis")      or "neutral").lower()
    stance      = (fv.get("recommended_stance")   or "stand_down").lower()
    bull  = int((debate.get("bullish_thesis",  {}) or {}).get("case_strength", 0) or 0)
    bear  = int((debate.get("bearish_thesis",  {}) or {}).get("case_strength", 0) or 0)
    neut  = int((debate.get("neutral_thesis",  {}) or {}).get("case_strength", 0) or 0)
    verdict_conf = fv.get("verdict_confidence") or max(bull, bear, neut)

    return {
        "ai_direction_at_entry":             ai_direction,
        "ai_confidence_at_entry":            ai_confidence,
        "ai_agreement_with_playbook":        agree_playbook,
        "ai_agreement_with_risk":            agree_risk,
        "ai_external_used":                  ai_external_used,
        "ai_fallback_used":                  ai_fallback_used,
        "ai_fallback_reason":                ai_fallback_reason,
        "ai_model_used":                     ai_model_used,
        "mechanical_confidence_at_entry":    mech_conf,
        "confidence_fusion_status_at_entry": fusion_status,
        "confidence_delta_at_entry":         conf_delta,
        "ai_debate_dominant_thesis":         dom_thesis,
        "ai_debate_recommended_stance":      stance,
        "ai_debate_verdict_confidence":      int(verdict_conf or 0),
        "authority_level":                   "observe_only",
        "confidence_modifier":               0,
    }


def _safe_default() -> dict:
    return {
        "ai_direction_at_entry":             "unknown",
        "ai_confidence_at_entry":            0,
        "ai_agreement_with_playbook":        None,
        "ai_agreement_with_risk":            None,
        "ai_external_used":                  False,
        "ai_fallback_used":                  False,
        "ai_fallback_reason":                None,
        "ai_model_used":                     None,
        "mechanical_confidence_at_entry":    0,
        "confidence_fusion_status_at_entry": "unknown",
        "confidence_delta_at_entry":         0,
        "ai_debate_dominant_thesis":         "unknown",
        "ai_debate_recommended_stance":      "unknown",
        "ai_debate_verdict_confidence":      0,
        "authority_level":                   "observe_only",
        "confidence_modifier":               0,
    }
