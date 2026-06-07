"""
Phase 1X — Intent Archive + Outcome Tracker.

Archives high-quality trade intents to data/intent_archive/ and tracks
outcome metrics (MFE, MAE, zone touch, trigger readiness) across scans.

No execution. No orders. No broker actions. Archive and observation only.
"""
import os
import json
from datetime import datetime
import pytz

from intent_archive.outcome_tracker import calculate_outcome, should_expire

_EASTERN      = pytz.timezone("America/New_York")
_PROJECT_ROOT = os.path.dirname(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
)
_ARCHIVE_DIR  = os.path.join(_PROJECT_ROOT, "data", "intent_archive")


def _archive_filepath(symbol: str) -> str:
    date_str = datetime.now(_EASTERN).strftime("%Y%m%d")
    return os.path.join(_ARCHIVE_DIR, f"{date_str}_{symbol}_intents.json")


def _load_archive(filepath: str) -> list:
    if not os.path.exists(filepath):
        return []
    try:
        with open(filepath, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data.get("intents", [])
    except Exception:
        return []


def _save_archive(filepath: str, symbol: str, intents: list):
    os.makedirs(_ARCHIVE_DIR, exist_ok=True)
    data = {
        "date":    datetime.now(_EASTERN).strftime("%Y%m%d"),
        "symbol":  symbol,
        "intents": intents,
    }
    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, default=str)


def _make_archive_key(symbol: str, snapshot: dict) -> str:
    """
    Stable key for same-setup detection — excludes zone so records survive
    minor zone drift between scans.
    Strips the last two underscore-segments (zone_low, zone_high) from setup_id.
    Falls back to playbook+direction+tool_family if setup_id is absent.
    """
    sl       = snapshot.get("setup_lifecycle", {})
    setup_id = (sl.get("setup_id") or "").strip()
    if setup_id:
        parts = setup_id.split("_")
        if len(parts) >= 3:
            return "_".join(parts[:-2])

    ti        = snapshot.get("trade_intent", {})
    pb        = snapshot.get("playbook", {})
    playbook  = (pb.get("selected_playbook") or "no_playbook").lower()
    direction = (pb.get("direction") or "neutral").lower()
    tool      = (ti.get("preferred_tool") or "no_tool").lower()
    tool_fam  = tool.replace("bullish_", "").replace("bearish_", "")
    date_str  = datetime.now(_EASTERN).strftime("%Y%m%d")
    return f"{symbol}_{date_str}_{playbook}_{direction}_{tool_fam}"


def _should_archive(snapshot: dict) -> bool:
    """True when the current snapshot warrants creating or updating an archive record."""
    ti   = snapshot.get("trade_intent", {})
    iscr = snapshot.get("intent_score", {})
    if ti.get("intent_created", False):
        return True
    if iscr.get("scored", False) and iscr.get("raw_score", 0) >= 55:
        return True
    return False


def _make_new_record(symbol: str, snapshot: dict, archive_key: str) -> dict:
    ti   = snapshot.get("trade_intent", {})
    iscr = snapshot.get("intent_score", {})
    sl   = snapshot.get("setup_lifecycle", {})
    now  = datetime.now(_EASTERN).strftime("%Y%m%dT%H%M%S")
    return {
        "intent_id":               f"{symbol}_{now}",
        "archive_key":             archive_key,
        "setup_id":                sl.get("setup_id"),
        "intent_type":             ti.get("intent_type", "none"),
        "direction":               ti.get("direction", "neutral"),
        "playbook":                snapshot.get("playbook", {}).get("selected_playbook", "no_playbook"),
        "preferred_tool":          ti.get("preferred_tool", "no_tool"),
        "entry_zone":              ti.get("entry_zone"),
        "raw_score_at_creation":   iscr.get("raw_score", 0),
        "gated_score_at_creation": iscr.get("gated_score", 0),
        "quality_at_creation":     iscr.get("gated_quality", "no_intent"),
        "status":                  "open",
        "created_at":              now,
        "last_updated":            now,
        "bars_since_creation":     1,
        "mfe":                     0.0,
        "mae":                     0.0,
        "zone_was_touched":        False,
        "trigger_became_ready":    False,
        "expiration_reason":       None,
        "scan_updates":            [],
    }


def update_archive(snapshot: dict, symbol: str) -> dict:
    """
    Phase 1X — Intent Archive + Outcome Tracker entry point.

    1. Decides whether to create a new record (intent_created OR raw_score>=55).
    2. Loads the day's archive file (creates if absent).
    3. Finds or creates a matching open record using a stable setup key.
    4. Updates MFE/MAE, zone_was_touched, trigger_became_ready for ALL open records.
    5. Applies expiration logic to each open record.
    6. Saves the updated archive.
    7. Returns a compact summary dict.

    No execution. No orders. No broker actions.
    """
    filepath      = _archive_filepath(symbol)
    intents       = _load_archive(filepath)
    should_create = _should_archive(snapshot)
    archive_key   = _make_archive_key(symbol, snapshot) if should_create else None

    # Find existing open record matching this setup
    matching_record = None
    if archive_key:
        for record in intents:
            if record.get("archive_key") == archive_key and record.get("status") == "open":
                matching_record = record
                break

    # Create new record if warranted
    created_new   = False
    new_record_id = None
    if should_create and matching_record is None:
        rec = _make_new_record(symbol, snapshot, archive_key)
        intents.append(rec)
        matching_record = rec
        created_new     = True
        new_record_id   = rec["intent_id"]

    # Update all open records
    expired_count = 0
    now_str       = datetime.now(_EASTERN).strftime("%Y%m%dT%H%M%S")

    for record in intents:
        if record.get("status") != "open":
            continue

        # Guard against missing key from older records loaded from disk
        if "scan_updates" not in record:
            record["scan_updates"] = []

        # Newly created records start at bars=1 — don't double-count
        if record.get("intent_id") != new_record_id:
            record["bars_since_creation"] = record.get("bars_since_creation", 0) + 1

        outcome = calculate_outcome(snapshot, record)

        record["mfe"] = round(max(record.get("mfe", 0.0), outcome["mfe_candidate"]), 4)
        record["mae"] = round(max(record.get("mae", 0.0), outcome["mae_candidate"]), 4)

        if outcome["zone_touched_this_scan"]:
            record["zone_was_touched"] = True
        if outcome["trigger_ready_this_scan"]:
            record["trigger_became_ready"] = True

        record["last_updated"] = now_str
        record["scan_updates"].append({
            "scan_time":   now_str,
            "price":       outcome.get("current_price"),
            "mfe":         record["mfe"],
            "mae":         record["mae"],
            "zone_touched": record["zone_was_touched"],
        })
        record["scan_updates"] = record["scan_updates"][-50:]

        expire, reason = should_expire(record, snapshot, outcome)
        if expire:
            record["status"]            = "expired"
            record["expiration_reason"] = reason
            expired_count += 1

    # Persist
    archive_saved = True
    try:
        _save_archive(filepath, symbol, intents)
    except Exception:
        archive_saved = False

    open_records = [r for r in intents if r.get("status") == "open"]
    open_count   = len(open_records)

    primary = (
        matching_record
        if matching_record and matching_record.get("status") == "open"
        else None
    )
    if primary is None and open_records:
        primary = open_records[-1]

    if primary:
        return {
            "archive_updated":    archive_saved,
            "active_intent_id":   primary["intent_id"],
            "active_status":      primary["status"],
            "mfe":                primary["mfe"],
            "mae":                primary["mae"],
            "zone_touched":       primary["zone_was_touched"],
            "bars_active":        primary["bars_since_creation"],
            "new_record_created": created_new,
            "open_count":         open_count,
            "expired_this_scan":  expired_count,
        }

    return {
        "archive_updated":    archive_saved,
        "active_intent_id":   None,
        "active_status":      None,
        "mfe":                0.0,
        "mae":                0.0,
        "zone_touched":       False,
        "bars_active":        0,
        "new_record_created": created_new,
        "open_count":         open_count,
        "expired_this_scan":  expired_count,
    }
