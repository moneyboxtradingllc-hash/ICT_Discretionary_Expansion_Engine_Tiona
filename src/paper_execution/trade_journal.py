"""
Paper Trade Journal — Phase 2A/2B.

Persists all paper trade attempts and lifecycle updates to
data/paper_trades/YYYYMMDD_SYMBOL_paper_trades.json.

No execution. Pure file I/O only.
"""
import os
import json
from datetime import datetime, timedelta
import pytz

_EASTERN      = pytz.timezone("America/New_York")
_PROJECT_ROOT = os.path.dirname(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
)
_TRADES_DIR   = os.path.join(_PROJECT_ROOT, "data", "paper_trades")


# ── File path helpers ─────────────────────────────────────────────────────────

def _journal_filepath(symbol: str) -> str:
    date_str = datetime.now(_EASTERN).strftime("%Y%m%d")
    return os.path.join(_TRADES_DIR, f"{date_str}_{symbol}_paper_trades.json")


def _journal_filepath_for_date(symbol: str, date_str: str) -> str:
    return os.path.join(_TRADES_DIR, f"{date_str}_{symbol}_paper_trades.json")


def _load_file(filepath: str) -> dict:
    """Load a journal file. Returns empty structure on failure."""
    if not os.path.exists(filepath):
        return {"trades": []}
    try:
        with open(filepath, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {"trades": []}


def _save_file(filepath: str, data: dict) -> bool:
    """Save journal data to filepath. Returns True on success."""
    os.makedirs(_TRADES_DIR, exist_ok=True)
    try:
        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, default=str)
        return True
    except Exception:
        return False


# ── Phase 2A public API ───────────────────────────────────────────────────────

def load_today_trades(symbol: str) -> list:
    """Return today's trade list (empty list if file absent or corrupt)."""
    return _load_file(_journal_filepath(symbol)).get("trades", [])


def append_trade(record: dict, symbol: str) -> bool:
    """
    Append one trade record to today's journal.
    Returns True on success, False on I/O failure.
    """
    fp   = _journal_filepath(symbol)
    data = _load_file(fp)
    data.setdefault("date",   datetime.now(_EASTERN).strftime("%Y%m%d"))
    data.setdefault("symbol", symbol)
    data["trades"].append(record)
    return _save_file(fp, data)


def count_submitted_today(symbol: str) -> int:
    """Count trades with order_status == 'submitted' for today."""
    return sum(
        1 for t in load_today_trades(symbol)
        if t.get("order_status") == "submitted"
    )


def total_risk_today(symbol: str) -> float:
    """Sum of risk_dollars for submitted trades today (conservative loss estimate)."""
    return sum(
        float(t.get("risk_dollars", 0))
        for t in load_today_trades(symbol)
        if t.get("order_status") == "submitted"
    )


def intent_already_journaled(intent_id: str, symbol: str) -> bool:
    """True if a submitted trade for this intent_id already exists today."""
    return any(
        t.get("intent_id") == intent_id and t.get("order_status") == "submitted"
        for t in load_today_trades(symbol)
    )


def make_record(
    *,
    trade_id: str,
    symbol: str,
    intent_id: str | None,
    intent_type: str,
    side: str,
    qty: int,
    entry_reference: float,
    stop_reference: float | None,
    risk_per_share: float,
    risk_dollars: float,
    order_status: str,
    alpaca_order_id: str | None,
    reason: str,
    snapshot_summary: dict | None = None,
) -> dict:
    """Build a canonical trade journal record."""
    return {
        "trade_id":           trade_id,
        "timestamp":          datetime.now(_EASTERN).strftime("%Y%m%dT%H%M%S"),
        "symbol":             symbol,
        "intent_id":          intent_id,
        "intent_type":        intent_type,
        "side":               side,
        "qty":                qty,
        "entry_reference":    round(float(entry_reference), 4),
        "stop_reference":     round(float(stop_reference), 4) if stop_reference is not None else None,
        "risk_per_share":     round(float(risk_per_share), 4),
        "risk_dollars":       round(float(risk_dollars), 2),
        "order_status":       order_status,
        "alpaca_order_id":    alpaca_order_id,
        "reason":             reason,
        "snapshot_summary":   snapshot_summary or {},
        # Phase 2B lifecycle fields (default values)
        "avg_fill_price":     None,
        "filled_qty":         None,
        "exit_submitted":     False,
        "exit_order_id":      None,
        "exit_price_reference": None,
        "exit_reason":        None,
        "realized_pnl":       None,
        "closed_at":          None,
        "close_reason":       None,
        # Phase 4A closure fields (set by trade_reconciliation)
        "entry_price":        None,
        "exit_price":         None,
        "realized_r":         None,
        "holding_minutes":    None,
        "final_status":       None,
    }


# ── Phase 2B: multi-day search and update API ─────────────────────────────────

def _search_recent_files(symbol: str, days: int = 7) -> list[tuple[str, str, list]]:
    """
    Yield (date_str, filepath, trades) for the last `days` trading days.
    Most recent day first.
    """
    results = []
    today = datetime.now(_EASTERN).date()
    for d in range(days):
        date_str = (today - timedelta(days=d)).strftime("%Y%m%d")
        fp       = _journal_filepath_for_date(symbol, date_str)
        if not os.path.exists(fp):
            continue
        data   = _load_file(fp)
        trades = data.get("trades", [])
        if trades:
            results.append((date_str, fp, trades))
    return results


def find_active_trade(symbol: str, side: str) -> tuple[dict | None, str | None]:
    """
    Find the most recent active (not closed, not exited) trade for symbol+side.
    Searches up to 7 recent days.
    Returns (record, filepath) or (None, None).
    Active means: order_status in (submitted, accepted, filled, partially_filled)
                  AND exit_submitted is False.
    """
    active_statuses = {"submitted", "accepted", "filled", "partially_filled"}
    for _, fp, trades in _search_recent_files(symbol):
        # Reverse to get most recent entry first
        for t in reversed(trades):
            if (
                t.get("side") == side
                and t.get("order_status", "") in active_statuses
                and not t.get("exit_submitted", False)
            ):
                return t, fp
    return None, None


def _update_trade_in_file(trade_id: str, filepath: str, **fields) -> bool:
    """
    Load `filepath`, find the trade by trade_id, update fields, save.
    Returns True on success.
    """
    try:
        with open(filepath, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception:
        return False

    trades  = data.get("trades", [])
    updated = False
    for i, t in enumerate(trades):
        if t.get("trade_id") == trade_id:
            trades[i].update(fields)
            updated = True
            break

    if not updated:
        return False

    data["trades"] = trades
    return _save_file(filepath, data)


def _find_trade_filepath(trade_id: str, symbol: str) -> tuple[dict | None, str | None]:
    """Find which file contains trade_id. Returns (record, filepath)."""
    for _, fp, trades in _search_recent_files(symbol):
        for t in trades:
            if t.get("trade_id") == trade_id:
                return t, fp
    return None, None


def update_trade_status(trade_id: str, status: str, fields: dict, symbol: str) -> bool:
    """
    Update order_status and any additional fields for the given trade_id.
    Searches recent days to find the correct file.
    Returns True on success.
    """
    _, fp = _find_trade_filepath(trade_id, symbol)
    if fp is None:
        return False
    return _update_trade_in_file(trade_id, fp, order_status=status, **fields)


def mark_exit_submitted(
    trade_id: str,
    exit_order_id: str | None,
    exit_price_reference: float,
    reason: str,
    symbol: str,
) -> bool:
    """
    Mark a trade as having an exit order submitted.
    Preserves all original entry data.
    """
    _, fp = _find_trade_filepath(trade_id, symbol)
    if fp is None:
        return False
    return _update_trade_in_file(
        trade_id, fp,
        exit_submitted       = True,
        exit_order_id        = exit_order_id,
        exit_price_reference = round(float(exit_price_reference), 4),
        exit_reason          = reason,
        exit_submitted_at    = datetime.now(_EASTERN).strftime("%Y%m%dT%H%M%S"),
    )


def mark_closed(
    trade_id: str,
    realized_pnl: float,
    closed_at: str,
    reason: str,
    symbol: str,
    *,
    realized_r: float | None = None,
    holding_minutes: float | None = None,
    entry_price: float | None = None,
    exit_price: float | None = None,
    final_status: str | None = "closed",
) -> bool:
    """
    Mark a trade as fully closed with realized P&L and closure metrics.
    Sets order_status='closed'. Called by trade_reconciliation (Phase 4A).
    """
    _, fp = _find_trade_filepath(trade_id, symbol)
    if fp is None:
        return False
    return _update_trade_in_file(
        trade_id, fp,
        order_status    = "closed",
        realized_pnl    = round(float(realized_pnl), 4),
        closed_at       = closed_at,
        close_reason    = reason,
        realized_r      = round(float(realized_r), 4) if realized_r is not None else None,
        holding_minutes = round(float(holding_minutes), 2) if holding_minutes is not None else None,
        entry_price     = round(float(entry_price), 4) if entry_price is not None else None,
        exit_price      = round(float(exit_price), 4) if exit_price is not None else None,
        final_status    = final_status or "closed",
    )


# ── Phase 4A: find any non-terminal trade ──────────────────────────────────────

_TERMINAL_STATUSES = frozenset({
    "closed", "canceled", "cancelled", "rejected", "expired", "done_for_day", "stopped",
})


def find_any_active_trade(symbol: str) -> tuple[dict | None, str | None]:
    """
    Find the most recent non-terminal trade for symbol, regardless of side.
    Searches up to 7 recent days, most recent entry first.
    Non-terminal means: order_status not in closed/canceled/rejected/expired.
    """
    for _, fp, trades in _search_recent_files(symbol):
        for t in reversed(trades):
            if t.get("order_status", "") not in _TERMINAL_STATUSES:
                return t, fp
    return None, None
