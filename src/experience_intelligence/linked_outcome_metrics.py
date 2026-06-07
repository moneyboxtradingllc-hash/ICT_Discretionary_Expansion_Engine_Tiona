"""
Phase 3C — Linked Outcome Metrics.
Computes richer per-trade outcome stats from linked intent+trade pairs.
OBSERVE_ONLY — never modifies decisions, execution, or trade behavior.
"""
from datetime import datetime
import pytz

_EASTERN = pytz.timezone("America/New_York")


def compute_linked_metrics(
    links: list[dict],
    intents: list[dict],
    trades: list[dict],
) -> list[dict]:
    """
    Compute per-linked-pair outcome metrics.
    Returns one metric dict per link result (linked or not).
    Never raises.
    """
    try:
        return _compute_all(links, intents, trades)
    except Exception as exc:
        return [{"linked": False, "closed": False,
                 "warnings": [f"linked metrics error: {exc}"]}]


def _compute_all(
    links: list[dict],
    intents: list[dict],
    trades: list[dict],
) -> list[dict]:
    intent_by_id = {i.get("intent_id"): i for i in intents if i.get("intent_id")}
    trade_by_id  = {_trade_id(t): t     for t in trades   if _trade_id(t)}

    results = []
    for link in links:
        if not link.get("linked"):
            results.append({
                "intent_id":    link.get("intent_id"),
                "trade_id":     None,
                "linked":       False,
                "link_confidence": "none",
                "closed":       False,
            })
            continue
        intent_id = link.get("intent_id")
        trade_id  = link.get("trade_id")
        intent    = intent_by_id.get(intent_id) or {}
        trade     = trade_by_id.get(trade_id)   or {}
        results.append(_compute_one(intent_id, trade_id, intent, trade, link))
    return results


def _compute_one(
    intent_id: str,
    trade_id: str,
    intent: dict,
    trade: dict,
    link: dict,
) -> dict:
    closed = trade.get("order_status") == "closed"

    pnl        = trade.get("realized_pnl")
    risk       = trade.get("risk_dollars")
    realized_r = None
    if pnl is not None and risk and risk > 0:
        realized_r = round(float(pnl) / float(risk), 4)

    # MFE/MAE: prefer intent archive (tracked during setup), fall back to trade
    mfe = intent.get("mfe") if intent.get("mfe") is not None else trade.get("mfe")
    mae = intent.get("mae") if intent.get("mae") is not None else trade.get("mae")

    # Intent scores from trade snapshot
    ss   = trade.get("snapshot_summary") or {}
    iscr = ss.get("intent_score")        or {}

    duration         = _minutes_between(trade.get("timestamp"), trade.get("closed_at"))
    intent_to_entry  = _minutes_between(
        intent.get("created_at") or intent.get("timestamp"),
        trade.get("timestamp"),
    )

    return {
        "intent_id":                      intent_id,
        "trade_id":                       trade_id,
        "linked":                         True,
        "link_confidence":                link.get("confidence", "none"),
        "closed":                         closed,
        "realized_r":                     realized_r,
        "mfe":                            mfe,
        "mae":                            mae,
        "intent_score_raw":               iscr.get("raw_score"),
        "intent_score_gated":             iscr.get("gated_score"),
        "planned_risk_dollars":           intent.get("planned_risk") or risk,
        "actual_risk_dollars":            risk,
        "realized_pnl":                   pnl,
        "entry_price":                    trade.get("entry_price"),
        "exit_price":                     trade.get("exit_price"),
        "stop_reference":                 intent.get("stop_reference"),
        "trade_duration_minutes":         duration,
        "trigger_to_entry_delay_minutes": None,   # Phase 3D: requires trigger timestamp
        "intent_to_entry_delay_minutes":  intent_to_entry,
    }


def build_trade_id_lookup(trades: list[dict]) -> dict:
    """Public helper: build trade_id → trade dict for fast lookup."""
    return {_trade_id(t): t for t in trades if _trade_id(t)}


def _trade_id(trade: dict):
    return (
        trade.get("trade_id")
        or trade.get("alpaca_order_id")
        or trade.get("order_id")
        or trade.get("id")
    )


def _parse_ts(ts: str):
    if not ts:
        return None
    try:
        dt = datetime.strptime(ts[:15], "%Y%m%dT%H%M%S")
        return _EASTERN.localize(dt)
    except Exception:
        return None


def _minutes_between(ts_start: str, ts_end: str):
    t1 = _parse_ts(ts_start)
    t2 = _parse_ts(ts_end)
    if t1 is None or t2 is None:
        return None
    diff = (t2 - t1).total_seconds() / 60.0
    return round(diff, 2) if diff >= 0 else None
