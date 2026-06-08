"""
Phase 3A — Experience Query.
Reads historical intent archive and trade journal files.
OBSERVE_ONLY — no decision logic, no execution changes.
"""
import os
import json
from datetime import datetime, timedelta

import pytz

_EASTERN      = pytz.timezone("America/New_York")
_PROJECT_ROOT = os.path.dirname(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
)
_ARCHIVE_DIR = os.path.join(_PROJECT_ROOT, "data", "intent_archive")
_TRADES_DIR  = os.path.join(_PROJECT_ROOT, "data", "paper_trades")


def _date_range(days: int) -> list[str]:
    today = datetime.now(_EASTERN).date()
    return [(today - timedelta(days=d)).strftime("%Y%m%d") for d in range(days)]


def load_all_intent_records(symbol: str, days: int = 30) -> list[dict]:
    """Load all intent archive records for the past N days — flat list."""
    records: list[dict] = []
    for date_str in _date_range(days):
        fp = os.path.join(_ARCHIVE_DIR, f"{date_str}_{symbol}_intents.json")
        if not os.path.exists(fp):
            continue
        try:
            with open(fp, "r", encoding="utf-8") as f:
                data = json.load(f)
            records.extend(data.get("intents", []))
        except Exception:
            continue
    return records


def load_completed_trades(symbol: str, days: int = 30) -> list[dict]:
    """
    Load all closed trades from paper trade journal for past N days.
    Closed means order_status == 'closed' (set by mark_closed in trade_journal.py).
    """
    trades: list[dict] = []
    for date_str in _date_range(days):
        fp = os.path.join(_TRADES_DIR, f"{date_str}_{symbol}_paper_trades.json")
        if not os.path.exists(fp):
            continue
        try:
            with open(fp, "r", encoding="utf-8") as f:
                data = json.load(f)
            for t in data.get("trades", []):
                if t.get("order_status") == "closed":
                    trades.append(t)
        except Exception:
            continue
    return trades


def find_similar_setups(snapshot: dict, symbol: str, days: int = 30) -> list[dict]:
    """Find intent records with characteristics similar to the current snapshot."""
    from experience_intelligence.experience_similarity import (
        extract_current_attrs, find_matching_records,
    )
    records = load_all_intent_records(symbol, days)
    if not records:
        return []
    current_attrs = extract_current_attrs(snapshot)
    return find_matching_records(records, current_attrs)


def find_similar_playbook(playbook: str, symbol: str, days: int = 30) -> list[dict]:
    """Find all intent records with the given playbook name."""
    records = load_all_intent_records(symbol, days)
    return [r for r in records if (r.get("playbook") or "").lower() == playbook.lower()]


def find_similar_tool(tool: str, symbol: str, days: int = 30) -> list[dict]:
    """Find all intent records using the given preferred tool."""
    records = load_all_intent_records(symbol, days)
    return [
        r for r in records
        if (r.get("preferred_tool") or "").lower() == tool.lower()
    ]


def find_similar_session(session: str, symbol: str, days: int = 30) -> list[dict]:
    """Find all intent records created during the given session type."""
    records = load_all_intent_records(symbol, days)
    result  = []
    for r in records:
        rec_session = _derive_session_from_ts(r.get("created_at", ""))
        if rec_session and rec_session.lower() == session.lower():
            result.append(r)
    return result


def _derive_session_from_ts(timestamp_str: str) -> str:
    """
    Derive session label from a YYYYMMDDTHHMMSS timestamp (ET).
    Returns one of: pre_market, open, mid_day, power_hour, after_hours, ''.
    """
    if not timestamp_str or len(timestamp_str) < 15:
        return ""
    try:
        dt = datetime.strptime(timestamp_str[:15], "%Y%m%dT%H%M%S")
        dt = _EASTERN.localize(dt)
        t  = dt.hour * 60 + dt.minute
        if t < 9 * 60 + 30:   return "premarket"
        if t < 10 * 60 + 30:  return "open"
        if t < 15 * 60:       return "mid_day"
        if t < 16 * 60:       return "power_hour"
        return "after_hours"
    except Exception:
        return ""
