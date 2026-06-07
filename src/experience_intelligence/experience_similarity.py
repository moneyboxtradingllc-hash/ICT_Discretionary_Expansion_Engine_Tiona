"""
Phase 3A — Experience Similarity.
Scores similarity between the current setup and historical intent records.
OBSERVE_ONLY — no decision influence, no execution changes.
"""

# Attribute weights (must sum to 100)
_WEIGHTS: dict[str, int] = {
    "playbook":           40,
    "direction":          20,
    "preferred_tool":     25,
    "qualification_tier": 10,
    "session":             5,
}

_MIN_SIMILARITY: float = 0.4   # 40 / 100 — floor for "similar enough"


def extract_current_attrs(snapshot: dict) -> dict:
    """Extract comparable setup attributes from the current scan snapshot."""
    pb   = snapshot.get("playbook",       {}) or {}
    qual = snapshot.get("qualification",  {}) or {}
    ti   = snapshot.get("trade_intent",   {}) or {}
    return {
        "playbook":           (pb.get("selected_playbook")  or "no_playbook").lower(),
        "direction":          (pb.get("direction")          or "neutral").lower(),
        "preferred_tool":     (ti.get("preferred_tool")     or "no_tool").lower(),
        "qualification_tier": (qual.get("status")           or "no_trade").lower(),
        "session":            (snapshot.get("session")      or "unknown").lower(),
    }


def score_record_similarity(record: dict, current_attrs: dict) -> float:
    """
    Score a single historical record's similarity to current_attrs.
    Returns 0.0–1.0 (0 = no match, 1.0 = perfect match).
    """
    rec_attrs = {
        "playbook":           (record.get("playbook")              or "no_playbook").lower(),
        "direction":          (record.get("direction")             or "neutral").lower(),
        "preferred_tool":     (record.get("preferred_tool")        or "no_tool").lower(),
        "qualification_tier": (record.get("quality_at_creation")   or "no_trade").lower(),
        "session":            (record.get("session_at_creation")   or "").lower(),
    }

    score = 0
    for attr, weight in _WEIGHTS.items():
        cur = current_attrs.get(attr, "")
        rec = rec_attrs.get(attr, "")
        if not cur or not rec:
            continue
        if cur == rec:
            score += weight
        elif attr == "preferred_tool":
            # Partial credit when same tool family (bullish_fvg ↔ bearish_fvg)
            cur_fam = cur.replace("bullish_", "").replace("bearish_", "")
            rec_fam = rec.replace("bullish_", "").replace("bearish_", "")
            if cur_fam == rec_fam and cur_fam not in ("no_tool", ""):
                score += weight // 2

    return round(score / 100, 4)


def find_matching_records(
    records: list[dict],
    current_attrs: dict,
    min_score: float = _MIN_SIMILARITY,
) -> list[dict]:
    """
    Filter `records` to those with similarity >= min_score.
    Returns list sorted descending by similarity_score.
    Each returned dict has an added 'similarity_score' field.
    """
    scored: list[dict] = []
    for r in records:
        sim = score_record_similarity(r, current_attrs)
        if sim >= min_score:
            scored.append({**r, "similarity_score": sim})
    scored.sort(key=lambda x: x["similarity_score"], reverse=True)
    return scored
