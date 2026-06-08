"""
Phase 5C — Similarity Search.
Finds prior setups most similar to the current snapshot.
Phase 5E.1 — Deduplication moved to memory_record_builder (load_memory_records).
             closed_match_count and outcome_summary now use the same top-K population.
OBSERVE_ONLY — no decision logic, no execution influence.
"""
from memory_search.memory_record_builder import load_memory_records
from memory_search.feature_vector import (
    build_query_features,
    build_record_features,
    score_similarity,
)

_CLOSED_OUTCOMES = {"win", "loss", "breakeven"}
_MIN_CLOSED_FOR_SUMMARY = 5


def find_similar_setups(
    snapshot: dict,
    symbol: str | None = None,
    limit: int = 10,
    min_similarity: float = 0.55,
) -> dict:
    """
    Search memory for setups similar to the current snapshot.
    Returns observe-only result dict. Never raises.
    """
    try:
        return _search(snapshot, symbol, limit, min_similarity)
    except Exception as exc:
        return _empty_result(warnings=[f"similarity search failed (non-blocking): {exc}"])


def _search(
    snapshot: dict,
    symbol: str | None,
    limit: int,
    min_similarity: float,
) -> dict:
    warnings: list[str] = []
    notes:    list[str] = []

    # Resolve symbol
    sym = (
        symbol
        or snapshot.get("symbol")
        or (snapshot.get("qualification") or {}).get("symbol")
        or None
    )

    # Build query
    query = build_query_features(snapshot)
    if sym:
        query["symbol"] = sym.upper()

    # Load records — deduplication is handled inside load_memory_records
    records = load_memory_records(sym)

    # Score and filter
    scored: list[dict] = []
    for rec in records:
        rec_features = build_record_features(rec)
        sim = score_similarity(query, rec_features)
        if sim["similarity_score"] < min_similarity:
            continue
        scored.append({**rec, **sim})

    # Sort descending by similarity
    scored.sort(key=lambda x: x["similarity_score"], reverse=True)
    top = scored[:limit]

    # Closed records within the top-K only (aligned population)
    closed_top = [m for m in top if m.get("outcome") in _CLOSED_OUTCOMES]

    # Total closed above threshold (informational transparency field)
    total_closed_above_threshold = sum(
        1 for m in scored if m.get("outcome") in _CLOSED_OUTCOMES
    )

    # Build top_matches list
    top_matches = [_format_match(m) for m in top]

    # Outcome summary derived from closed_top only — matches closed_match_count
    outcome_summary = _build_outcome_summary(closed_top)

    if len(closed_top) < _MIN_CLOSED_FOR_SUMMARY:
        notes.append("Insufficient similar closed trades for outcome summary")

    notes.append("Memory result is observe-only and does not affect decisions")

    return {
        "enabled":                        True,
        "authority_level":                "observe_only",
        "confidence_modifier":            0,
        "query_built":                    True,
        "match_count":                    len(top),
        "closed_match_count":             len(closed_top),
        "total_closed_above_threshold":   total_closed_above_threshold,
        "top_matches":                    top_matches,
        "similar_outcome_summary":        outcome_summary,
        "warnings":                       warnings,
        "notes":                          notes,
    }


def _format_match(rec: dict) -> dict:
    return {
        "similarity_score":  rec.get("similarity_score", 0.0),
        "matched_features":  rec.get("matched_features", []),
        "reason":            rec.get("reason", ""),
        "record_source":     rec.get("record_source"),
        "data_completeness": rec.get("data_completeness"),
        "intent_id":         rec.get("intent_id"),
        "trade_id":          rec.get("trade_id"),
        "symbol":            rec.get("symbol"),
        "timestamp":         rec.get("timestamp"),
        "playbook":          rec.get("playbook"),
        "direction":         rec.get("direction"),
        "preferred_tool":    rec.get("preferred_tool"),
        "session":           rec.get("session"),
        "regime_label":      rec.get("market_regime_label"),
        "volatility_state":  rec.get("volatility_state"),
        "expansion_state":   rec.get("expansion_state"),
        "realized_r":        rec.get("realized_r"),
        "mfe":               rec.get("mfe"),
        "mae":               rec.get("mae"),
        "outcome":           rec.get("outcome"),
    }


def _build_outcome_summary(closed: list[dict]) -> dict:
    if not closed:
        return {
            "sample_size": 0,
            "win_rate":    None,
            "average_r":   None,
            "average_mfe": None,
            "average_mae": None,
        }

    wins  = sum(1 for m in closed if m.get("outcome") == "win")
    rs    = [m["realized_r"] for m in closed if m.get("realized_r") is not None]
    mfes  = [m["mfe"]        for m in closed if m.get("mfe")        is not None]
    maes  = [m["mae"]        for m in closed if m.get("mae")        is not None]

    return {
        "sample_size": len(closed),
        "win_rate":    round(wins / len(closed) * 100, 1) if closed else None,
        "average_r":   round(sum(rs)   / len(rs),   2) if rs   else None,
        "average_mfe": round(sum(mfes) / len(mfes), 2) if mfes else None,
        "average_mae": round(sum(maes) / len(maes), 2) if maes else None,
    }


def _empty_result(warnings: list[str] | None = None) -> dict:
    return {
        "enabled":                       True,
        "authority_level":               "observe_only",
        "confidence_modifier":           0,
        "query_built":                   False,
        "match_count":                   0,
        "closed_match_count":            0,
        "total_closed_above_threshold":  0,
        "top_matches":                   [],
        "similar_outcome_summary":       {},
        "warnings":                      warnings or [],
        "notes":                         ["Memory result is observe-only and does not affect decisions"],
    }
