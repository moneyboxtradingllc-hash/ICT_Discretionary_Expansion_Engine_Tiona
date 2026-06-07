"""
Phase 3C — Intent-to-Trade Linker.
Links intent archive records to paper trade journal records.
OBSERVE_ONLY — never modifies decisions, execution, or trade behavior.

Linking priority (highest to lowest confidence):
  1. exact intent_id match            → confidence=high
  2. setup_id match                   → confidence=high
  3. direction + tool + time window   → confidence=medium
  4. playbook + direction + time window → confidence=low

Each intent is matched at most once; each trade is claimed at most once.
"""
from datetime import datetime
import pytz

_EASTERN   = pytz.timezone("America/New_York")
_PROX_MIN  = 30   # default proximity window in minutes


def link_intents_to_trades(
    intents: list[dict],
    trades: list[dict],
    proximity_minutes: int = _PROX_MIN,
) -> list[dict]:
    """
    Link each intent record to its best matching trade record.
    Returns one link-result dict per intent.
    Never raises.
    """
    try:
        return _link_all(intents, trades, proximity_minutes)
    except Exception as exc:
        return [_no_link(None, [f"linkage error: {exc}"])]


def _link_all(intents: list[dict], trades: list[dict], prox: int) -> list[dict]:
    used_trade_ids: set = set()
    results = []
    for intent in intents:
        result = _link_one(intent, trades, used_trade_ids, prox)
        results.append(result)
        if result["linked"] and result.get("trade_id"):
            used_trade_ids.add(result["trade_id"])
    return results


def _link_one(intent: dict, trades: list[dict], used: set, prox: int) -> dict:
    intent_id = intent.get("intent_id")
    warnings: list[str] = []

    # ── Method 1: exact intent_id ─────────────────────────────────────────────
    if intent_id:
        candidates = [
            t for t in trades
            if t.get("intent_id") == intent_id and _trade_id(t) not in used
        ]
        if candidates:
            if len(candidates) > 1:
                warnings.append("multiple possible matches")
            return _link_result(intent_id, candidates[0], "intent_id", "high", warnings)

    # ── Method 2: setup_id ────────────────────────────────────────────────────
    setup_id = intent.get("setup_id")
    if setup_id:
        candidates = [
            t for t in trades
            if t.get("setup_id") == setup_id and _trade_id(t) not in used
        ]
        if candidates:
            if len(candidates) > 1:
                warnings.append("multiple possible matches")
            return _link_result(intent_id, candidates[0], "setup_id", "high", warnings)

    # ── Methods 3/4: time-proximity ───────────────────────────────────────────
    i_ts  = _parse_ts(intent.get("created_at") or intent.get("timestamp"))
    i_dir = (intent.get("direction") or "").lower()

    # Method 3: direction + preferred_tool + proximity
    i_tool = (intent.get("preferred_tool") or "").lower()
    if i_ts and i_dir and i_tool:
        match = _best_proximity_match(trades, used, prox, i_ts,
                                      direction=i_dir, tool=i_tool)
        if match:
            t, diff, n_cands = match
            if n_cands > 1:
                warnings.append("multiple possible matches")
            return _link_result(intent_id, t, "proximity_tool", "medium", warnings)

    # Method 4: playbook + direction + proximity
    i_pb = (intent.get("playbook") or "").lower()
    if i_ts and i_pb and i_dir:
        match = _best_proximity_match(trades, used, prox, i_ts,
                                      direction=i_dir, playbook=i_pb)
        if match:
            t, diff, n_cands = match
            if n_cands > 1:
                warnings.append("multiple possible matches")
            return _link_result(intent_id, t, "proximity_playbook", "low", warnings)

    return _no_link(intent_id, warnings)


def _best_proximity_match(
    trades: list[dict],
    used: set,
    prox: int,
    i_ts,
    direction: str = "",
    tool: str = "",
    playbook: str = "",
) -> "tuple | None":
    """Return (trade, diff_minutes, n_candidates) for the nearest matching trade."""
    hits: list[tuple] = []
    for t in trades:
        if _trade_id(t) in used:
            continue
        t_ts = _parse_ts(t.get("timestamp"))
        if t_ts is None or i_ts is None:
            continue
        diff = abs((t_ts - i_ts).total_seconds()) / 60.0
        if diff > prox:
            continue
        ss   = t.get("snapshot_summary") or {}
        pb   = ss.get("playbook") or {}
        tb   = ss.get("toolbox")  or {}
        t_dir  = (pb.get("direction")          or "").lower()
        t_tool = (tb.get("preferred_tool")      or "").lower()
        t_pb   = (pb.get("selected_playbook")   or "").lower()
        if direction and t_dir != direction:
            continue
        if tool and t_tool != tool:
            continue
        if playbook and t_pb != playbook:
            continue
        hits.append((t, diff))
    if not hits:
        return None
    hits.sort(key=lambda x: x[1])
    return hits[0][0], hits[0][1], len(hits)


def _link_result(intent_id, trade: dict, method: str, confidence: str,
                 warnings: list[str]) -> dict:
    return {
        "intent_id":    intent_id,
        "linked":       True,
        "link_method":  method,
        "confidence":   confidence,
        "trade_id":     _trade_id(trade),
        "trade_status": trade.get("order_status"),
        "warnings":     warnings,
    }


def _no_link(intent_id, warnings: list[str]) -> dict:
    return {
        "intent_id":    intent_id,
        "linked":       False,
        "link_method":  None,
        "confidence":   "none",
        "trade_id":     None,
        "trade_status": None,
        "warnings":     warnings,
    }


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
