"""
REPLAY-3 — session scoreboard (2026-07-09).

Fixed metric definitions (REPLAY-0 design §7) so every report is comparable:
win = R > 0 at exit; profit factor = gross positive R / |gross negative R|;
expectancy = mean R (reported WITH N — no expectancy claims under N=5);
max drawdown = max peak-to-trough on the cumulative-R curve.

Safety invariants are graded here too: any violation FAILS the run outright.
Pure functions; no state, no I/O.
"""

_MIN_EXPECTANCY_N = 5


def score_trades(trades: list) -> dict:
    """Aggregate simulate_trade() records into the canonical scoreboard."""
    trades = [t for t in (trades or []) if t]
    n = len(trades)
    rs = [float(t["r"]) for t in trades]
    wins = [r for r in rs if r > 0]
    losses = [r for r in rs if r <= 0]

    gross_win = sum(wins)
    gross_loss = abs(sum(losses))
    profit_factor = (round(gross_win / gross_loss, 2) if gross_loss > 0
                     else (None if not wins else float("inf")))

    # max drawdown on the cumulative R curve
    peak = cum = 0.0
    max_dd = 0.0
    for r in rs:
        cum += r
        peak = max(peak, cum)
        max_dd = max(max_dd, peak - cum)

    return {
        "trades": n,
        "wins": len(wins),
        "losses": len(losses),
        "win_rate": round(len(wins) / n, 3) if n else None,
        "total_r": round(sum(rs), 3),
        "avg_r": round(sum(rs) / n, 3) if n else None,
        "profit_factor": profit_factor,
        "expectancy_r": round(sum(rs) / n, 3) if n >= _MIN_EXPECTANCY_N else None,
        "expectancy_note": (None if n >= _MIN_EXPECTANCY_N
                            else f"n={n} < {_MIN_EXPECTANCY_N}: no expectancy claim"),
        "avg_mfe_r": round(sum(t["mfe_r"] for t in trades) / n, 3) if n else None,
        "avg_mae_r": round(sum(t["mae_r"] for t in trades) / n, 3) if n else None,
        "max_drawdown_r": round(max_dd, 3),
        "exit_reasons": _count(trades, "exit_reason"),
    }


def _count(trades, key):
    out = {}
    for t in trades:
        v = t.get(key)
        out[v] = out.get(v, 0) + 1
    return out


def safety_invariants(trades: list, max_trades_per_day: int = 2,
                      risk_dollars: float = 500.0,
                      daily_loss_limit: float = 500.0) -> dict:
    """Grade the protected limits. ANY violation fails the run outright.
    Trades carry 'r' (risk-multiples); dollar loss = r * risk_dollars."""
    trades = [t for t in (trades or []) if t]
    by_day = {}
    for t in trades:
        day = str(t.get("entry_time", ""))[:10]
        by_day.setdefault(day, []).append(t)
    violations = []
    for day, day_trades in by_day.items():
        if len(day_trades) > max_trades_per_day:
            violations.append(f"{day}: {len(day_trades)} trades > max {max_trades_per_day}")
        day_loss = -sum(min(0.0, float(t["r"])) for t in day_trades) * risk_dollars
        if day_loss > daily_loss_limit:
            violations.append(f"{day}: loss ${day_loss:.0f} > limit ${daily_loss_limit:.0f}")
    return {"violations": violations, "passed": not violations}
