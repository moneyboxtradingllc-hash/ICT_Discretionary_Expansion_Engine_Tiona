"""
Phase 5C — Feature Vector.
Converts snapshots and memory records into comparable feature vectors.
Weighted categorical + numeric similarity scoring.
OBSERVE_ONLY — no decision logic, no execution influence.
"""

# Weights for categorical matches (must sum to 100 when numeric=10 is added)
_CAT_WEIGHTS: dict[str, int] = {
    "symbol":               10,
    "market_regime_label":  20,
    "playbook":             20,
    "direction":            15,
    "preferred_tool":       10,
    "session":              10,
    "qualification":         5,
    "volatility_state":      5,
    "expansion_state":       5,
}
_NUMERIC_WEIGHT = 10
_MAX_SCORE = sum(_CAT_WEIGHTS.values()) + _NUMERIC_WEIGHT  # 110


def build_query_features(snapshot: dict) -> dict:
    """Extract comparable feature fields from the current live snapshot."""
    qual  = snapshot.get("qualification", {}) or {}
    pb    = snapshot.get("playbook",      {}) or {}
    tb    = snapshot.get("toolbox",       {}) or {}
    reg   = snapshot.get("market_regime", {}) or {}
    fus   = snapshot.get("confidence_fusion", {}) or {}
    ai    = snapshot.get("ai_discretionary",  {}) or {}
    score = snapshot.get("intent_score",  {}) or {}

    return {
        "symbol":              (snapshot.get("symbol") or "").upper(),
        "market_regime_label": (reg.get("regime_label")    or "unknown").lower(),
        "market_regime_family":(reg.get("regime_family")   or "unknown").lower(),
        "playbook":            (pb.get("selected_playbook") or "").lower(),
        "direction":           (pb.get("direction")         or qual.get("direction") or "").lower(),
        "preferred_tool":      (tb.get("preferred_tool")    or "").lower(),
        "qualification":       (qual.get("status")          or "").lower(),
        "session":             (snapshot.get("session")     or "").lower(),
        "volatility_state":    (reg.get("volatility_state") or "unknown").lower(),
        "expansion_state":     (reg.get("expansion_state")  or "unknown").lower(),
        "intent_score_gated":  _safe_int(score.get("gated_score") or score.get("raw_score")),
        "ai_confidence":       _safe_int(ai.get("ai_confidence")),
        "mechanical_score":    _safe_int(fus.get("mechanical_score")),
    }


def build_record_features(record: dict) -> dict:
    """Extract comparable feature fields from a memory record."""
    return {
        "symbol":              (record.get("symbol")             or "").upper(),
        "market_regime_label": (record.get("market_regime_label") or "unknown").lower(),
        "market_regime_family":(record.get("market_regime_family") or "unknown").lower(),
        "playbook":            (record.get("playbook")           or "").lower(),
        "direction":           (record.get("direction")          or "").lower(),
        "preferred_tool":      (record.get("preferred_tool")     or "").lower(),
        "qualification":       (record.get("qualification")      or "").lower(),
        "session":             (record.get("session")            or "").lower(),
        "volatility_state":    (record.get("volatility_state")   or "unknown").lower(),
        "expansion_state":     (record.get("expansion_state")    or "unknown").lower(),
        "intent_score_gated":  record.get("intent_score_gated"),
        "ai_confidence":       record.get("ai_confidence"),
        "mechanical_score":    record.get("mechanical_score"),
    }


def score_similarity(query: dict, record: dict) -> dict:
    """
    Compute weighted similarity between a query and a record feature vector.
    Returns similarity_score (0.0–1.0), matched_features, missing_features, reason.
    """
    raw_score      = 0
    matched        = []
    missing        = []

    # Categorical scoring
    for feat, weight in _CAT_WEIGHTS.items():
        q_val = query.get(feat) or ""
        r_val = record.get(feat) or ""
        if not q_val or not r_val:
            missing.append(feat)
            continue
        # unknown/empty on either side — don't count for or against
        if q_val in ("unknown", "") or r_val in ("unknown", ""):
            missing.append(feat)
            continue
        if q_val == r_val:
            raw_score += weight
            matched.append(feat)

    # Numeric proximity scoring
    numeric_feats = ["intent_score_gated", "ai_confidence", "mechanical_score"]
    numeric_scores = []
    for feat in numeric_feats:
        q_val = query.get(feat)
        r_val = record.get(feat)
        if q_val is not None and r_val is not None:
            prox = max(0.0, 1.0 - abs(q_val - r_val) / 100.0)
            numeric_scores.append(prox)
    if numeric_scores:
        avg_prox   = sum(numeric_scores) / len(numeric_scores)
        raw_score += avg_prox * _NUMERIC_WEIGHT

    similarity = raw_score / _MAX_SCORE if _MAX_SCORE > 0 else 0.0
    similarity = min(1.0, max(0.0, round(similarity, 4)))

    reason_parts = []
    for f in matched:
        label = f.replace("market_regime_label", "regime").replace("_", " ")
        reason_parts.append(label)
    reason = ", ".join(reason_parts) if reason_parts else "no strong matches"

    return {
        "similarity_score":  similarity,
        "matched_features":  matched,
        "missing_features":  missing,
        "reason":            reason,
    }


def _safe_int(val) -> int | None:
    try:
        return int(val) if val is not None else None
    except (TypeError, ValueError):
        return None
