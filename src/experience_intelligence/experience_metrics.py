"""
Phase 3A/3C — Experience Metrics.
Pure statistical computation from completed trade records.
Phase 3C adds optional linked_outcomes for MFE/MAE and linkage count fields.
OBSERVE_ONLY — no decision influence, no execution changes.
"""
from datetime import datetime

import pytz

_EASTERN = pytz.timezone("America/New_York")
_MIN_RATE_SAMPLE = 3   # minimum closed trades needed to compute win/loss rates


def _parse_ts(ts: str) -> datetime | None:
    if not ts:
        return None
    try:
        dt = datetime.strptime(ts[:15], "%Y%m%dT%H%M%S")
        return _EASTERN.localize(dt)
    except Exception:
        return None


def _r_multiple(trade: dict) -> float | None:
    """realized_pnl / risk_dollars. Returns None if data missing."""
    pnl  = trade.get("realized_pnl")
    risk = trade.get("risk_dollars")
    if pnl is None or not risk:
        return None
    try:
        r = float(pnl) / float(risk)
        return round(r, 4)
    except Exception:
        return None


def _hold_minutes(trade: dict) -> float | None:
    """Minutes between entry timestamp and closed_at."""
    t_open  = _parse_ts(trade.get("timestamp"))
    t_close = _parse_ts(trade.get("closed_at"))
    if t_open is None or t_close is None:
        return None
    diff = (t_close - t_open).total_seconds() / 60.0
    return round(diff, 2) if diff >= 0 else None


def _session_of(trade: dict) -> str:
    dt = _parse_ts(trade.get("timestamp"))
    if dt is None:
        return "unknown"
    t = dt.hour * 60 + dt.minute
    if t < 9 * 60 + 30:   return "pre_market"
    if t < 10 * 60 + 30:  return "open"
    if t < 15 * 60:       return "mid_day"
    if t < 16 * 60:       return "power_hour"
    return "after_hours"


def _playbook_of(trade: dict) -> str:
    ss = trade.get("snapshot_summary") or {}
    pb = ss.get("playbook") or {}
    if isinstance(pb, dict):
        return (pb.get("selected_playbook") or "unknown").lower()
    return "unknown"


def _win_rate_for(r_list: list[float]) -> float | None:
    n = len(r_list)
    if n < _MIN_RATE_SAMPLE:
        return None
    wins = sum(1 for r in r_list if r > 0)
    return round(wins / n * 100, 1)


def _best_worst(bucket: dict[str, list[float]]) -> tuple[str | None, str | None]:
    """Return (best_key, worst_key) by win rate among buckets with ≥2 trades."""
    rates = {}
    for key, rs in bucket.items():
        if len(rs) >= 2:
            rates[key] = sum(1 for r in rs if r > 0) / len(rs)
    if not rates:
        return None, None
    return max(rates, key=rates.get), min(rates, key=rates.get)


def compute_metrics(
    trades: list[dict],
    linked_outcomes: "list[dict] | None" = None,
) -> dict:
    """
    Compute all performance metrics from a list of closed trade records.
    Phase 3C: optional linked_outcomes enriches MFE/MAE and adds linkage counts.
    Fields are None when sample_size < _MIN_RATE_SAMPLE.
    """
    n = len(trades)

    _zero_counts = {
        "linked_trade_count": 0,
        "closed_trade_count": 0,
        "open_trade_count":   0,
    }

    _empty = {
        "sample_size":       0,
        "win_rate":          None,
        "loss_rate":         None,
        "average_r":         None,
        "average_hold_time": None,
        "average_mfe":       None,
        "average_mae":       None,
        "best_session":      None,
        "worst_session":     None,
        "best_playbook":     None,
        "worst_playbook":    None,
        **_zero_counts,
    }

    if n == 0 and not linked_outcomes:
        return _empty

    r_multiples  = [r for r in (_r_multiple(t)  for t in trades) if r is not None]
    hold_minutes = [h for h in (_hold_minutes(t) for t in trades) if h is not None]

    win_rate  = _win_rate_for(r_multiples)
    loss_rate = (
        round(sum(1 for r in r_multiples if r < 0) / len(r_multiples) * 100, 1)
        if len(r_multiples) >= _MIN_RATE_SAMPLE else None
    )
    avg_r    = round(sum(r_multiples)  / len(r_multiples),  4) if r_multiples  else None
    avg_hold = round(sum(hold_minutes) / len(hold_minutes), 2) if hold_minutes else None

    sessions  = {}
    playbooks = {}
    for t in trades:
        r = _r_multiple(t)
        if r is None:
            continue
        sessions.setdefault(_session_of(t),  []).append(r)
        playbooks.setdefault(_playbook_of(t), []).append(r)

    best_sess, worst_sess = _best_worst(sessions)
    best_pb,   worst_pb   = _best_worst(playbooks)

    # Phase 3C: derive MFE/MAE and linkage counts from linked outcomes
    closed_lo     = [lo for lo in (linked_outcomes or [])
                     if lo.get("linked") and lo.get("closed")]
    mfe_vals      = [lo["mfe"] for lo in closed_lo if lo.get("mfe") is not None]
    mae_vals      = [lo["mae"] for lo in closed_lo if lo.get("mae") is not None]
    avg_mfe       = round(sum(mfe_vals) / len(mfe_vals), 2) if mfe_vals else None
    avg_mae       = round(sum(mae_vals) / len(mae_vals), 2) if mae_vals else None

    linked_count  = sum(1 for lo in (linked_outcomes or []) if lo.get("linked"))
    closed_count  = len(closed_lo)
    open_count    = linked_count - closed_count

    return {
        "sample_size":        n,
        "win_rate":           win_rate,
        "loss_rate":          loss_rate,
        "average_r":          avg_r,
        "average_hold_time":  avg_hold,
        "average_mfe":        avg_mfe,        # Phase 3C: from linked closed outcomes
        "average_mae":        avg_mae,         # Phase 3C: from linked closed outcomes
        "best_session":       best_sess,
        "worst_session":      worst_sess,
        "best_playbook":      best_pb,
        "worst_playbook":     worst_pb,
        "linked_trade_count": linked_count,   # Phase 3C
        "closed_trade_count": closed_count,   # Phase 3C
        "open_trade_count":   open_count,     # Phase 3C
    }
