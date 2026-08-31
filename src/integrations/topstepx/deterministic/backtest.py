"""DETERMINISTIC_MNQ_SIM_ONLY — offline expectancy backtest.

Replays the deterministic lane over historical MNQ 1m bars using the SAME real
mechanical pipeline the live loop uses (facts_provider.build_facts -> author),
then simulates each authorized trade forward to its target / structural stop /
end-of-day, honoring the live rules: the configured ET decision window, ONE open
position, MAX 2 trades/day, 16.5pt stop cap, 35pt fixed target, modeled costs.

HONESTY NOTES (read the report footer):
  * In-sample. A backtest estimates whether an edge is PLAUSIBLE; it does not
    prove one. Out-of-sample forward sim is the real confirmation.
  * 1m intrabar ambiguity: if a bar's range spans BOTH stop and target, we cannot
    know which filled first from OHLC — we assume STOP first (pessimistic) and
    count these separately (`ambiguous_bars`).
  * Fill model: market entry at the NEXT bar's open + 1 tick adverse slippage
    (no look-ahead). Commission is UNKNOWN -> modeled 0 but flagged.
  * Single contract month (whatever the bars file contains).

NEVER calls OpenAI (the mechanical pipeline runs with the Brain gated off).
"""
from __future__ import annotations

import argparse
import datetime as _dt
import json
import os
from typing import Optional

from integrations.topstepx.deterministic import (
    POINT_VALUE, TICK_SIZE, TARGET_POINTS, MAX_STOP_POINTS, MAX_RISK_DOLLARS,
    MAX_CONTRACTS, SLIPPAGE_TICKS, DECISION_WINDOW, TIMEZONE, MAX_TRADES_PER_DAY,
    DAILY_LOSS_CEILING, COMMISSION_PER_CONTRACT,
)
from integrations.topstepx.deterministic import author as AUTH
from integrations.topstepx.deterministic import facts_provider as FP
from integrations.topstepx.deterministic import risk as R

LOOKBACK = 400          # trailing bars fed to the pipeline (matches the live loop)
SESSION_EXIT_HM = "16:00"   # force flat by RTH close if neither target nor stop hit
LONG, SHORT = "long", "short"


def _tick(x: float) -> float:
    return round(round(x / TICK_SIZE) * TICK_SIZE, 6)


def _modeled_entry_costs(qty: int) -> float:
    """Per-trade modeled cost: 1 tick slippage on entry + commission (if known)."""
    slip = SLIPPAGE_TICKS * TICK_SIZE * POINT_VALUE * qty
    comm = (float(COMMISSION_PER_CONTRACT) * qty) if COMMISSION_PER_CONTRACT else 0.0
    return slip + comm


def _parse_ts(ts: str) -> _dt.datetime:
    """Robust ISO parse (handles NT's 7-digit fractional seconds)."""
    s = str(ts)
    if "." in s:
        head, tail = s.split(".", 1)
        # keep up to 6 fractional digits, preserve any tz offset suffix
        off = ""
        for i, ch in enumerate(tail):
            if ch in "+-" or (ch == "Z"):
                off = tail[i:]
                tail = tail[:i]
                break
        s = head + "." + tail[:6] + off
    dt = _dt.datetime.fromisoformat(s)
    return dt


def _et(dt: _dt.datetime) -> _dt.datetime:
    try:
        from zoneinfo import ZoneInfo
        z = ZoneInfo(TIMEZONE)
        return dt.astimezone(z) if dt.tzinfo else dt.replace(tzinfo=z)
    except Exception:
        return dt


def simulate_trade(bars: list, entry_idx: int, direction: str, fill: float,
                   stop: float, target: float, exit_deadline_idx: int) -> dict:
    """Walk bars[entry_idx+1 .. exit_deadline_idx] and resolve the trade.

    Returns exit_reason in {target, stop, ambiguous_stop, time}, exit price,
    points P&L (signed), and the resolving bar index. Pure function (testable).
    """
    for j in range(entry_idx + 1, min(exit_deadline_idx, len(bars) - 1) + 1):
        hi = float(bars[j]["high"]); lo = float(bars[j]["low"])
        if direction == LONG:
            hit_t = hi >= target
            hit_s = lo <= stop
            if hit_t and hit_s:
                return {"exit_reason": "ambiguous_stop", "exit_price": stop,
                        "points": stop - fill, "exit_idx": j}
            if hit_s:
                return {"exit_reason": "stop", "exit_price": stop,
                        "points": stop - fill, "exit_idx": j}
            if hit_t:
                return {"exit_reason": "target", "exit_price": target,
                        "points": target - fill, "exit_idx": j}
        else:  # SHORT
            hit_t = lo <= target
            hit_s = hi >= stop
            if hit_t and hit_s:
                return {"exit_reason": "ambiguous_stop", "exit_price": stop,
                        "points": fill - stop, "exit_idx": j}
            if hit_s:
                return {"exit_reason": "stop", "exit_price": stop,
                        "points": fill - stop, "exit_idx": j}
            if hit_t:
                return {"exit_reason": "target", "exit_price": target,
                        "points": fill - target, "exit_idx": j}
    # Neither hit by the deadline -> time exit at the deadline bar's close.
    k = min(exit_deadline_idx, len(bars) - 1)
    close = float(bars[k]["close"])
    pts = (close - fill) if direction == LONG else (fill - close)
    return {"exit_reason": "time", "exit_price": close, "points": pts, "exit_idx": k}


def _day_key(dt: _dt.datetime) -> str:
    return dt.strftime("%Y-%m-%d")


def _in_window(dt: _dt.datetime) -> bool:
    hm = dt.strftime("%H:%M")
    return DECISION_WINDOW[0] <= hm <= DECISION_WINDOW[1]


def _session_exit_idx(bars, entry_idx, ets) -> int:
    """Last bar index on the same ET day at/under the RTH close cutoff."""
    day = _day_key(ets[entry_idx])
    last = entry_idx
    for j in range(entry_idx + 1, len(bars)):
        if _day_key(ets[j]) != day:
            break
        if ets[j].strftime("%H:%M") <= SESSION_EXIT_HM:
            last = j
        else:
            break
    return last


def run_backtest(bars: list, lookback: int = LOOKBACK, progress: bool = False) -> dict:
    bars = [b for b in bars if b.get("high") is not None and b.get("low") is not None]
    ets = [_et(_parse_ts(b["timestamp"])) for b in bars]
    n = len(bars)
    trades = []
    day_trades: dict = {}
    day_realized: dict = {}   # $ pnl per ET day
    evaluated = authorized = blocked_session = 0

    i = lookback
    while i < n - 1:
        dt = ets[i]
        if not _in_window(dt):
            i += 1
            continue
        day = _day_key(dt)
        if day_trades.get(day, 0) >= MAX_TRADES_PER_DAY:
            i += 1
            continue
        evaluated += 1
        if progress and evaluated % 250 == 0:
            print(f"  ...evaluated {evaluated} window-bars ({day} {dt.strftime('%H:%M')})")

        window = bars[i - lookback + 1: i + 1]
        try:
            snap, decision, gate = FP.build_mnq_snapshot(window)
            facts = FP.build_facts_from_snapshot(snap, decision, gate, float(bars[i]["close"]))
        except Exception as e:  # pragma: no cover - defensive; a bad window is NO_TRADE
            i += 1
            continue

        realized_loss = max(0.0, -day_realized.get(day, 0.0))
        d = AUTH.evaluate(facts, account_known=True, position_known=True,
                          orders_known=True, reconciliation_ok=True,
                          realized_daily_loss=realized_loss,
                          can_enter=True, can_enter_reason="backtest")
        if not d.authorized:
            i += 1
            continue
        authorized += 1

        direction = d.direction
        structural_stop = d.structural_stop
        # Fill at next bar open + 1 tick adverse slippage (no look-ahead).
        nxt_open = float(bars[i + 1]["open"])
        slip = SLIPPAGE_TICKS * TICK_SIZE
        fill = _tick(nxt_open + slip) if direction == LONG else _tick(nxt_open - slip)
        stop = _tick(structural_stop)
        stop_dist = (fill - stop) if direction == LONG else (stop - fill)

        # Risk-based size from the ACTUAL (post-slippage) stop distance. A stop
        # that slipped past the cap sizes to 0 -> the live bridge would emergency-
        # flatten -> scratch (cost only, modeled at 1 contract).
        qty = R.contracts_for_stop(stop_dist)
        if stop_dist <= 0 or qty < 1:
            costs = _modeled_entry_costs(1)
            pnl_usd = round(-costs, 2)
            trades.append({
                "day": day, "entry_time": dt.isoformat(), "direction": direction,
                "fill": fill, "stop": stop, "target": None, "stop_distance": round(stop_dist, 4),
                "contracts": 0, "exit_reason": "scratch_stop_over_cap", "exit_price": fill,
                "points": 0.0, "pnl_usd": pnl_usd, "R": 0.0, "bars_held": 0,
            })
            day_trades[day] = day_trades.get(day, 0) + 1
            day_realized[day] = day_realized.get(day, 0.0) + pnl_usd
            i += 1
            continue

        dollars_per_point = POINT_VALUE * qty
        target = _tick(fill + TARGET_POINTS) if direction == LONG else _tick(fill - TARGET_POINTS)
        exit_deadline = _session_exit_idx(bars, i, ets)
        res = simulate_trade(bars, i, direction, fill, stop, target, exit_deadline)

        costs = _modeled_entry_costs(qty)
        pnl_pts = round(res["points"], 4)
        pnl_usd = round(pnl_pts * dollars_per_point - costs, 2)
        r_mult = round(pnl_pts / stop_dist, 4) if stop_dist else 0.0
        trades.append({
            "day": day, "entry_time": dt.isoformat(), "direction": direction,
            "fill": fill, "stop": stop, "target": target, "stop_distance": round(stop_dist, 4),
            "contracts": qty, "exit_reason": res["exit_reason"], "exit_price": round(res["exit_price"], 4),
            "points": pnl_pts, "pnl_usd": pnl_usd, "R": r_mult,
            "bars_held": res["exit_idx"] - i,
        })
        day_trades[day] = day_trades.get(day, 0) + 1
        day_realized[day] = day_realized.get(day, 0.0) + pnl_usd
        # Skip ahead past the trade so we never overlap positions.
        i = max(i + 1, res["exit_idx"] + 1)

    return _metrics(trades, bars, ets, evaluated, authorized)


def _metrics(trades, bars, ets, evaluated, authorized) -> dict:
    wins = [t for t in trades if t["pnl_usd"] > 0]
    losses = [t for t in trades if t["pnl_usd"] < 0]
    scratches = [t for t in trades if t["pnl_usd"] == 0]
    ambiguous = [t for t in trades if t["exit_reason"] == "ambiguous_stop"]
    over_cap = [t for t in trades if t["exit_reason"] == "scratch_stop_over_cap"]
    gross_win = sum(t["pnl_usd"] for t in wins)
    gross_loss = -sum(t["pnl_usd"] for t in losses)
    total = round(sum(t["pnl_usd"] for t in trades), 2)
    n = len(trades)

    # Equity curve + max drawdown ($).
    eq = 0.0; peak = 0.0; maxdd = 0.0
    for t in trades:
        eq += t["pnl_usd"]
        peak = max(peak, eq)
        maxdd = min(maxdd, eq - peak)

    def _avg(xs, k="pnl_usd"):
        return round(sum(t[k] for t in xs) / len(xs), 2) if xs else 0.0

    days = sorted({t["day"] for t in trades})
    span = None
    if bars:
        span = f"{ets[0].isoformat()} -> {ets[-1].isoformat()}"

    return {
        "data": {"bars": len(bars), "span_et": span, "trading_days_with_trades": len(days)},
        "coverage": {"window_bars_evaluated": evaluated, "authorized": authorized,
                     "authorization_rate": round(authorized / evaluated, 4) if evaluated else 0.0},
        "sample": {"trades": n, "wins": len(wins), "losses": len(losses),
                   "scratches": len(scratches), "over_cap_scratches": len(over_cap),
                   "ambiguous_bars": len(ambiguous)},
        "performance": {
            "win_rate": round(len(wins) / n, 4) if n else 0.0,
            "total_pnl_usd": total,
            "expectancy_per_trade_usd": round(total / n, 2) if n else 0.0,
            "expectancy_per_trade_R": round(sum(t["R"] for t in trades) / n, 4) if n else 0.0,
            "avg_win_usd": _avg(wins), "avg_loss_usd": _avg(losses),
            "profit_factor": round(gross_win / gross_loss, 3) if gross_loss else None,
            "max_drawdown_usd": round(maxdd, 2),
            "avg_bars_held": round(sum(t["bars_held"] for t in trades) / n, 1) if n else 0.0,
            "avg_contracts": round(sum(t.get("contracts", 0) for t in trades) / n, 1) if n else 0.0,
        },
        "exit_breakdown": {r: sum(1 for t in trades if t["exit_reason"] == r)
                           for r in sorted({t["exit_reason"] for t in trades})},
        "config": {"sizing": "risk-based", "max_risk_usd": MAX_RISK_DOLLARS,
                   "max_contracts": MAX_CONTRACTS, "point_value": POINT_VALUE,
                   "target_pts": TARGET_POINTS, "max_stop_pts": MAX_STOP_POINTS,
                   "max_trades_per_day": MAX_TRADES_PER_DAY, "daily_loss_ceiling": DAILY_LOSS_CEILING,
                   "decision_window_et": DECISION_WINDOW, "slippage_ticks": SLIPPAGE_TICKS,
                   "commission_known": COMMISSION_PER_CONTRACT is not None},
        "trades": trades,
        "honesty": [
            "IN-SAMPLE estimate — plausibility, not proof. Confirm with out-of-sample forward sim.",
            "1m intrabar ambiguity resolved pessimistically (stop-first); see ambiguous_bars.",
            "Fill = next-bar open + 1 tick adverse slippage. Commission UNKNOWN (modeled 0).",
            "Small N -> wide confidence interval. Do not size real risk off a thin sample.",
        ],
    }


def _load_bars(path: str) -> list:
    d = json.load(open(path, encoding="utf-8"))
    raw = d if isinstance(d, list) else (d.get("bars") or d.get("candles") or [])
    out = []
    for b in raw:
        # accept either provider shape or raw bridge shape
        out.append({
            "timestamp": b.get("timestamp") or b.get("t"),
            "open": b.get("open", b.get("o")), "high": b.get("high", b.get("h")),
            "low": b.get("low", b.get("l")), "close": b.get("close", b.get("c")),
            "volume": b.get("volume", b.get("v")),
        })
    return out


def main():
    ap = argparse.ArgumentParser(description="Deterministic MNQ lane expectancy backtest")
    ap.add_argument("--bars", required=True, help="path to 1m bars JSON")
    ap.add_argument("--out", default=None, help="path to write the full report JSON")
    ap.add_argument("--lookback", type=int, default=LOOKBACK)
    ap.add_argument("--progress", action="store_true")
    a = ap.parse_args()

    bars = _load_bars(a.bars)
    print(f"Loaded {len(bars)} bars from {a.bars}")
    rep = run_backtest(bars, lookback=a.lookback, progress=a.progress)

    out = a.out or os.path.join("data", "replay", "reports",
                                f"det_expectancy_{_dt.datetime.now():%Y%m%d_%H%M%S}.json")
    os.makedirs(os.path.dirname(out), exist_ok=True)
    json.dump(rep, open(out, "w", encoding="utf-8"), indent=2)

    p = rep["performance"]; s = rep["sample"]; c = rep["coverage"]
    print("\n================ DETERMINISTIC MNQ EXPECTANCY ================")
    print(f"data span (ET): {rep['data']['span_et']}")
    print(f"window-bars evaluated: {c['window_bars_evaluated']}  authorized: {c['authorized']}  "
          f"(auth rate {c['authorization_rate']})")
    print(f"trades: {s['trades']}  wins: {s['wins']}  losses: {s['losses']}  "
          f"scratches: {s['scratches']}  ambiguous: {s['ambiguous_bars']}")
    print(f"win rate: {p['win_rate']}   profit factor: {p['profit_factor']}")
    print(f"EXPECTANCY/trade: ${p['expectancy_per_trade_usd']}  ({p['expectancy_per_trade_R']} R)")
    print(f"total P&L: ${p['total_pnl_usd']}   max drawdown: ${p['max_drawdown_usd']}")
    print(f"avg win ${p['avg_win_usd']}  avg loss ${p['avg_loss_usd']}  avg bars held {p['avg_bars_held']}")
    print(f"exit breakdown: {rep['exit_breakdown']}")
    print("-------------------------------------------------------------")
    for line in rep["honesty"]:
        print("  * " + line)
    print(f"\nfull report -> {out}")


if __name__ == "__main__":
    main()
