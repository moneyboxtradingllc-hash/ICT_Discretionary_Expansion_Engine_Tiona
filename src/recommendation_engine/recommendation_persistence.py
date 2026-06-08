"""
Phase 5E.1 — Recommendation Persistence.
Saves daily recommendation summaries to data/recommendations/.
Provides a durable record for human review of what was recommended and when.
OBSERVE_ONLY — no execution influence. No risk fields. No auto-apply fields.
"""
import json
import os
from datetime import datetime
import pytz

_EASTERN = pytz.timezone("America/New_York")
_PROJECT_ROOT = os.path.dirname(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
)
_REC_DIR = os.path.join(_PROJECT_ROOT, "data", "recommendations")

# 24 hours at 1-minute intervals — safety cap; normal market-hours usage is ~390/day
_MAX_ENTRIES_PER_FILE = 1440

_FORBIDDEN_FIELDS = {
    "allow_execution", "trade_authorized", "gate_status",
    "risk_multiplier", "position_size", "confidence_modifier_delta",
    "auto_apply",
}


def save_recommendations(symbol: str, rec_result: dict) -> dict:
    """
    Append this scan's recommendation result to the daily file for symbol.
    Returns a status dict. Never raises — failures are non-blocking.
    """
    try:
        return _save(symbol, rec_result)
    except Exception as exc:
        return {
            "saved":   False,
            "warning": f"recommendation persistence failed (non-blocking): {exc}",
        }


def _save(symbol: str, rec_result: dict) -> dict:
    os.makedirs(_REC_DIR, exist_ok=True)

    now_et   = datetime.now(_EASTERN)
    date_str = now_et.strftime("%Y%m%d")
    ts_str   = now_et.strftime("%Y%m%dT%H%M%S")
    filepath = os.path.join(_REC_DIR, f"{date_str}_{symbol}_recommendations.json")

    # Load existing entries for the day
    entries: list[dict] = []
    if os.path.exists(filepath):
        try:
            with open(filepath, encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, list):
                entries = data
        except Exception:
            entries = []

    # Build the new entry — no execution, risk, or auto-apply fields
    entry = {
        "timestamp":              ts_str,
        "symbol":                 symbol,
        "recommendation_count":   rec_result.get("recommendation_count", 0),
        "recommendation_quality": _derive_quality(rec_result.get("recommendation_count", 0)),
        "authority_level":        "observe_only",
        "confidence_modifier":    0,
        "recommendations":        _clean_recs(rec_result.get("recommendations", [])),
    }

    entries.append(entry)

    # Cap to max entries (oldest removed first)
    if len(entries) > _MAX_ENTRIES_PER_FILE:
        entries = entries[-_MAX_ENTRIES_PER_FILE:]

    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(entries, f, indent=2, default=str)

    return {
        "saved":       True,
        "filepath":    filepath,
        "entry_count": len(entries),
    }


def _clean_recs(recs: list) -> list:
    """Remove forbidden fields and enforce invariants on each recommendation."""
    result = []
    for rec in recs:
        if not isinstance(rec, dict):
            continue
        clean = {k: v for k, v in rec.items() if k not in _FORBIDDEN_FIELDS}
        clean["authority_level"]     = "observe_only"
        clean["confidence_modifier"] = 0
        result.append(clean)
    return result


def _derive_quality(count: int) -> str:
    if count == 0:
        return "none"
    if count == 1:
        return "limited"
    if count <= 3:
        return "developing"
    return "meaningful"
