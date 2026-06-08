"""
Phase 5C — Similarity Search.
Finds prior setups most similar to the current snapshot.
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

    # Load records
    records = load_memory_records(sym)

    # Deduplicate: prefer trade record over intent-only for same trade_id
    seen_trade_ids: set[str] = set()
    seen_intent_ids: set[str] = set()
    deduped: list[dict] = []
    for rec in records:
        tid = rec.get("trade_id")
        iid = rec.get("intent_id")
        if tid and tid in seen_trade_ids:
            continue
        if not tid and iid and iid in seen_intent_ids:
            continue
        if tid:
            seen_trade_ids.add(tid)
        if iid:
            seen_intent_ids.add(iid)
        deduped.append(rec)

    # Score and filter
    scored: list[dict] = []
    for rec in deduped:
        rec_features = build_record_features(rec)
        sim = score_similarity(query, rec_features)
        if sim["similarity_score"] < min_similarity:
            continue
        scored.append({**rec, **sim})

    # Sort descending by similarity
    scored.sort(key=lambda x: x["similarity_score"], reverse=True)
    top = scored[:limit]

    # Build top_matches list
    top_matches = [_format_match(m) for m in top]

    # Outcome summary — closed trades only
    closed = [m for m in scored if m.get("outcome") in _CLOSED_OUTCOMES]
    outcome_summary = _build_outcome_summary(closed)

    if len(closed) < _MIN_CLOSED_FOR_SUMMARY:
        notes.append("Insufficient similar closed trades for outcome summary")

    notes.append("Memory result is observe-only and does not affect decisions")

    return {
        "enabled":               True,
        "authority_level":       "observe_only",
        "confidence_modifier":   0,
        "query_built":           True,
        "match_count":           len(top),
        "closed_match_count":    len(closed[:limit]),
        "top_matches":           top_matches,
        "similar_outcome_summary": outcome_summary,
        "warnings":              warnings,
        "notes":                 notes,
    }


def _format_match(rec: dict) -> dict:
    return {
        "similarity_score": rec.get("similarity_score", 0.0),
        "matched_features": rec.get("matched_features", []),
        "reason":           rec.get("reason", ""),
        "intent_id":        rec.get("intent_id"),
        "trade_id":         rec.get("trade_id"),
        "symbol":           rec.get("symbol"),
        "timestamp":        rec.get("timestamp"),
        "playbook":         rec.get("playbook"),
        "direction":        rec.get("direction"),
        "preferred_tool":   rec.get("preferred_tool"),
        "session":          rec.get("session"),
        "regime_label":     rec.get("market_regime_label"),
        "volatility_state": rec.get("volatility_state"),
        "expansion_state":  rec.get("expansion_state"),
        "realized_r":       rec.get("realized_r"),
        "mfe":              rec.get("mfe"),
        "mae":              rec.get("mae"),
        "outcome":          rec.get("outcome"),
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
        "enabled":               True,
        "authority_level":       "observe_only",
        "confidence_modifier":   0,
        "query_built":           False,
        "match_count":           0,
        "closed_match_count":    0,
        "top_matches":           [],
        "similar_outcome_summary": {},
        "warnings":              warnings or [],
        "notes":                 ["Memory result is observe-only and does not affect decisions"],
    }
