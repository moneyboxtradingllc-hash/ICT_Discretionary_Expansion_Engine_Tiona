"""
Phase 5C — Memory Record Builder.
Loads and normalizes prior intent/trade records into a common schema.
OBSERVE_ONLY — no decision logic, no execution influence.
"""
import json
import os

_PROJECT_ROOT = os.path.dirname(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
)
_INTENT_DIR = os.path.join(_PROJECT_ROOT, "data", "intent_archive")
_TRADES_DIR = os.path.join(_PROJECT_ROOT, "data", "paper_trades")

_CLOSED_STATUSES = {"closed", "externally_closed"}


def load_memory_records(symbol: str | None = None) -> list[dict]:
    """
    Load and normalize all available memory records for the given symbol.
    Returns a list of normalized dicts. Never raises — skips bad files/records.
    """
    records: list[dict] = []
    records.extend(_load_from_intent_archive(symbol))
    records.extend(_load_from_paper_trades(symbol))
    return records


# ── Intent Archive ────────────────────────────────────────────────────────────

def _load_from_intent_archive(symbol: str | None) -> list[dict]:
    records: list[dict] = []
    if not os.path.isdir(_INTENT_DIR):
        return records

    for fname in os.listdir(_INTENT_DIR):
        if not fname.endswith(".json"):
            continue
        if symbol and symbol.upper() not in fname.upper():
            continue
        fpath = os.path.join(_INTENT_DIR, fname)
        try:
            with open(fpath, encoding="utf-8") as f:
                raw = json.load(f)
        except Exception:
            continue

        intents = raw.get("intents", []) if isinstance(raw, dict) else raw
        if not isinstance(intents, list):
            continue
        sym = raw.get("symbol", "") if isinstance(raw, dict) else ""

        for intent in intents:
            try:
                rec = _normalize_intent(intent, sym or symbol or "")
                if rec:
                    records.append(rec)
            except Exception:
                continue

    return records


def _normalize_intent(intent: dict, symbol: str = "") -> dict | None:
    if not isinstance(intent, dict):
        return None

    intent_id = intent.get("intent_id", "")
    if not intent_id:
        return None

    outcome = _derive_intent_outcome(intent)

    # Pull context snapshot fields from scan_updates if present
    scan_updates = intent.get("scan_updates") or []
    first_snap = scan_updates[0] if scan_updates and isinstance(scan_updates[0], dict) else {}

    return {
        "intent_id":             intent_id,
        "trade_id":              intent.get("linked_trade_id") or None,
        "symbol":                (intent.get("symbol") or symbol or "").upper(),
        "timestamp":             intent.get("created_at") or intent.get("last_updated") or "",
        "playbook":              (intent.get("playbook") or "").lower(),
        "direction":             (intent.get("direction") or "").lower(),
        "preferred_tool":        (intent.get("preferred_tool") or "").lower(),
        "qualification":         (intent.get("quality_at_creation") or "").lower(),
        "session":               (intent.get("session") or first_snap.get("session") or "").lower(),
        "market_regime_label":   (intent.get("market_regime_label") or "unknown").lower(),
        "market_regime_family":  (intent.get("market_regime_family") or "unknown").lower(),
        "volatility_state":      (intent.get("volatility_state") or "unknown").lower(),
        "expansion_state":       (intent.get("expansion_state") or "unknown").lower(),
        "intent_score_gated":    _to_int(intent.get("gated_score_at_creation")),
        "ai_confidence":         _to_int(intent.get("ai_confidence_at_entry")),
        "mechanical_score":      _to_int(intent.get("mechanical_confidence_at_entry")),
        "realized_r":            _to_float(intent.get("realized_r")),
        "realized_pnl":          _to_float(intent.get("realized_pnl")),
        "mfe":                   _to_float(intent.get("mfe")),
        "mae":                   _to_float(intent.get("mae")),
        "holding_minutes":       _to_float(intent.get("holding_minutes")),
        "outcome":               outcome,
        "_source":               "intent_archive",
        "_status":               (intent.get("status") or "unknown").lower(),
    }


def _derive_intent_outcome(intent: dict) -> str:
    r = _to_float(intent.get("realized_r"))
    if r is not None:
        if r > 0:
            return "win"
        if r < 0:
            return "loss"
        return "breakeven"
    status = (intent.get("status") or "").lower()
    if status in ("open", "active"):
        return "open"
    return "unknown"


# ── Paper Trades Journal ──────────────────────────────────────────────────────

def _load_from_paper_trades(symbol: str | None) -> list[dict]:
    records: list[dict] = []
    if not os.path.isdir(_TRADES_DIR):
        return records

    for fname in os.listdir(_TRADES_DIR):
        if not fname.endswith(".json"):
            continue
        if symbol and symbol.upper() not in fname.upper():
            continue
        fpath = os.path.join(_TRADES_DIR, fname)
        try:
            with open(fpath, encoding="utf-8") as f:
                raw = json.load(f)
        except Exception:
            continue

        trades = raw if isinstance(raw, list) else raw.get("trades", [])
        if not isinstance(trades, list):
            continue

        for trade in trades:
            try:
                rec = _normalize_trade(trade)
                if rec:
                    records.append(rec)
            except Exception:
                continue

    return records


def _normalize_trade(trade: dict) -> dict | None:
    if not isinstance(trade, dict):
        return None

    trade_id = trade.get("trade_id", "")
    if not trade_id:
        return None

    outcome  = _derive_trade_outcome(trade)
    snap_sum = trade.get("snapshot_summary") or {}

    # Playbook: explicit > snapshot_summary > intent_type fallback
    playbook = (
        trade.get("playbook")
        or snap_sum.get("playbook")
        or trade.get("intent_type")
        or ""
    ).lower()

    # Session: explicit > snapshot_summary
    session = (trade.get("session") or snap_sum.get("session") or "").lower()

    return {
        "intent_id":             trade.get("intent_id") or None,
        "trade_id":              trade_id,
        "symbol":                (trade.get("symbol") or "").upper(),
        "timestamp":             trade.get("timestamp") or trade.get("entry_time") or "",
        "playbook":              playbook,
        "direction":             (trade.get("direction") or trade.get("intent_type") or "").lower(),
        "preferred_tool":        (trade.get("preferred_tool") or "").lower(),
        "qualification":         (trade.get("qualification_status") or "").lower(),
        "session":               session,
        "market_regime_label":   (trade.get("market_regime_label") or "unknown").lower(),
        "market_regime_family":  (trade.get("market_regime_family") or "unknown").lower(),
        "volatility_state":      (trade.get("volatility_state") or "unknown").lower(),
        "expansion_state":       (trade.get("expansion_state") or "unknown").lower(),
        "intent_score_gated":    _to_int(trade.get("intent_score_gated") or trade.get("gated_score")),
        "ai_confidence":         _to_int(trade.get("ai_confidence_at_entry")),
        "mechanical_score":      _to_int(trade.get("mechanical_confidence_at_entry")),
        "realized_r":            _to_float(trade.get("realized_r")),
        "realized_pnl":          _to_float(trade.get("realized_pnl")),
        "mfe":                   _to_float(trade.get("mfe")),
        "mae":                   _to_float(trade.get("mae")),
        "holding_minutes":       _to_float(trade.get("holding_minutes")),
        "close_reason":          trade.get("close_reason") or trade.get("exit_reason") or None,
        "ai_value_label":        (trade.get("ai_value_label") or "unknown").lower(),
        "ai_was_directionally_correct": trade.get("ai_was_directionally_correct"),
        "outcome":               outcome,
        "_source":               "paper_trades",
        "_status":               (trade.get("order_status") or "unknown").lower(),
    }


def _derive_trade_outcome(trade: dict) -> str:
    r = _to_float(trade.get("realized_r"))
    if r is not None:
        if r > 0:
            return "win"
        if r < 0:
            return "loss"
        return "breakeven"
    status = (trade.get("order_status") or "").lower()
    if status in _CLOSED_STATUSES:
        return "unknown"
    if status in ("open", "submitted", "partially_filled"):
        return "open"
    return "unknown"


# ── Helpers ───────────────────────────────────────────────────────────────────

def _to_int(val) -> int | None:
    try:
        return int(val) if val is not None else None
    except (TypeError, ValueError):
        return None


def _to_float(val) -> float | None:
    try:
        return float(val) if val is not None else None
    except (TypeError, ValueError):
        return None
