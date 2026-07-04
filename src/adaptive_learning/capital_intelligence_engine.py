"""
CAPITAL-1 — Capital Intelligence Engine (equity awareness).

The organism understands scars. Now it understands money.

Computes the account's capital condition every scan and feeds it into the
adaptive policy as another DEFENSIVE evidence source. Capital modifies
behavior; it does not replace intelligence.

CAPITAL STATES (first matching rule wins — exact transition model):

    critical      daily_pnl <= -80% of DAILY_LOSS_LIMIT, or drawdown >= 10%
                  -> probation lock (trade_block via existing actuator)
    preservation  drawdown >= 6%, or weekly_pnl <= -2x DAILY_LOSS_LIMIT
                  -> reduce size hard (risk_reduction + confidence_penalty)
    defensive     drawdown >= 3%, or daily_pnl <= -50% of DAILY_LOSS_LIMIT
                  -> reduce aggression (confidence_penalty)
    probation     closed sample < 10 trades (fresh start / weak sample)
                  -> no contraction, no pressing (tier "probation")
    expansion     expectancy >= +0.5R and profit_factor >= 1.5 and
                  drawdown <= 0.5% and weekly_pnl > 0 -> tier "press_plus"
    growth        expectancy > 0 and drawdown <= 1% and weekly_pnl > 0
                  -> tier "press"
    stable        everything else -> tier "normal"

AGGRESSION DOCTRINE (constitutional): capital may CONTRACT, LOCK, or PERMIT —
never exceed. "Controlled aggression increase" (growth/expansion) means
permission to operate at the FULL risk-governor ceiling (multiplier 1.0) with
the pressing tier reported; pushing size or confidence ABOVE the ceiling is
deferred until forward validation produces truth. All influence flows through
the EXISTING DEFENSIVE_ONLY actuators (confidence_penalty / risk_reduction /
trade_block) — the mutation engine, risk math, stop math, and broker
contracts are untouched.

PERSIST CONTRACT (as MEM-DECAY-1/SUPPRESS-1): only the live scan loop writes
capital history (peak equity / daily anchors) at
data/performance/ACCOUNT/capital_history.json (inherits PERFORMANCE_TABLES_DIR
isolation). Everything else is a pure read. Never raises into the loop; on
missing equity data the engine contributes NOTHING equity-based (it will not
contract on unknown data) while journal-based daily/weekly checks still run.
"""
from __future__ import annotations

import glob
import json
import os
from datetime import datetime, timezone

from adaptive_learning.performance_tables import performance_root, LEDGER_FILE

ACCOUNT_KEY  = "ACCOUNT"
HISTORY_FILE = "capital_history.json"

STATE_PROBATION    = "probation"
STATE_STABLE       = "stable"
STATE_GROWTH       = "growth"
STATE_EXPANSION    = "expansion"
STATE_DEFENSIVE    = "defensive"
STATE_PRESERVATION = "preservation"
STATE_CRITICAL     = "critical"

TIER = {
    STATE_PROBATION:    "probation",
    STATE_STABLE:       "normal",
    STATE_GROWTH:       "press",
    STATE_EXPANSION:    "press_plus",
    STATE_DEFENSIVE:    "contract",
    STATE_PRESERVATION: "contract_hard",
    STATE_CRITICAL:     "lock",
}

# behavior -> existing DEFENSIVE actuator flags (PHASE 5)
_FLAGS = {
    STATE_DEFENSIVE:    {"confidence_penalty": True},
    STATE_PRESERVATION: {"confidence_penalty": True, "risk_reduction": True},
    STATE_CRITICAL:     {"confidence_penalty": True, "risk_reduction": True,
                         "trade_block": True},
}

MIN_SAMPLE_TRADES   = 10
DD_DEFENSIVE        = 0.03
DD_PRESERVATION     = 0.06
DD_CRITICAL         = 0.10
DAILY_DEFENSIVE_PCT = 0.50
DAILY_CRITICAL_PCT  = 0.80
WEEKLY_PRESERVE_X   = 2.0
EXP_GROWTH          = 0.0
EXP_EXPANSION       = 0.5
PF_EXPANSION        = 1.5
DD_GROWTH_MAX       = 0.01
DD_EXPANSION_MAX    = 0.005

AUTHORITY_LEVEL = "observe_defensive"   # contract/lock/permit — never exceed
POSTURE         = "DEFENSIVE_ONLY"


def _num(v, default=None):
    return float(v) if isinstance(v, (int, float)) and not isinstance(v, bool) else default


def _daily_limit() -> float:
    try:
        return float(os.getenv("DAILY_LOSS_LIMIT_DOLLARS", "500"))
    except (TypeError, ValueError):
        return 500.0


# ── persistence (scan loop is the only writer) ────────────────────────────────

def _history_path(base_dir: "str | None" = None) -> str:
    d = os.path.join(performance_root(base_dir), ACCOUNT_KEY)
    os.makedirs(d, exist_ok=True)
    return os.path.join(d, HISTORY_FILE)


def _load_history(base_dir=None) -> dict:
    try:
        with open(_history_path(base_dir), encoding="utf-8") as fh:
            data = json.load(fh)
        return data if isinstance(data, dict) else {}
    except (FileNotFoundError, ValueError, OSError):
        return {}


def _save_history(hist: dict, base_dir=None) -> None:
    path = _history_path(base_dir)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(hist, fh, indent=2, sort_keys=True)
    os.replace(tmp, path)


# ── journal / ledger metrics (read-only) ──────────────────────────────────────

def _journal_dir() -> str:
    return os.getenv("PAPER_TRADES_DIR") or os.path.join("data", "paper_trades")


def _closed_trades_by_date() -> dict:
    """{date: [closed trade dicts]} from the day journals. Read-only."""
    out = {}
    for path in sorted(glob.glob(os.path.join(_journal_dir(),
                                              "*_paper_trades.json"))):
        try:
            with open(path, encoding="utf-8") as fh:
                day = json.load(fh)
        except (OSError, ValueError):
            continue
        date = str(day.get("date") or os.path.basename(path)[:8])
        closed = [t for t in day.get("trades", [])
                  if (t.get("order_status") or "") == "closed"]
        if closed:
            out[date] = closed
    return out


def _ledger_stats(symbol: str, base_dir=None) -> dict:
    """closed count / expectancy / win rate / profit factor from the DECON-2
    idempotency ledger (real reconciled trades only)."""
    path = os.path.join(performance_root(base_dir), str(symbol).upper(),
                        LEDGER_FILE)
    try:
        with open(path, encoding="utf-8") as fh:
            ledger = json.load(fh)
    except (OSError, ValueError):
        ledger = {}
    rs = [_num(v.get("realized_r")) for v in ledger.values()]
    rs = [r for r in rs if r is not None]
    n = len(rs)
    wins = [r for r in rs if r > 0.05]
    losses = [r for r in rs if r < -0.05]
    gross_w = sum(wins)
    gross_l = abs(sum(losses))
    return {
        "closed_trades": n,
        "expectancy": round(sum(rs) / n, 4) if n else None,
        "win_rate": round(len(wins) / n, 4) if n else None,
        "profit_factor": round(gross_w / gross_l, 4) if gross_l > 0 else None,
    }


def compute_risk_efficiency(daily: "dict | None" = None) -> "float | None":
    """Realized pnl per dollar of risk deployed, all-time (journal truth)."""
    daily = daily if daily is not None else _closed_trades_by_date()
    pnl = risk = 0.0
    for trades in daily.values():
        for t in trades:
            p = _num(t.get("realized_pnl"))
            r = _num(t.get("risk_dollars"))
            if p is not None and r is not None and r > 0:
                pnl += p
                risk += r
    return round(pnl / risk, 4) if risk > 0 else None


def build_capital_metrics(symbol: str, account: "dict | None",
                          today: "str | None" = None,
                          base_dir=None) -> dict:
    """Gather the full capital metric set (read-only)."""
    day = today or datetime.now(timezone.utc).strftime("%Y%m%d")
    day = day.replace("-", "")[:8]
    daily_trades = _closed_trades_by_date()
    daily_pnl = sum(_num(t.get("realized_pnl"), 0.0)
                    for t in daily_trades.get(day, []))
    # weekly = true trailing 7 CALENDAR days ending today — never stale
    # journal files from weeks ago (a three-week-old loss must not put a fresh
    # Monday into preservation).
    try:
        from datetime import timedelta
        week_floor = (datetime.strptime(day, "%Y%m%d")
                      - timedelta(days=7)).strftime("%Y%m%d")
    except ValueError:
        week_floor = day
    weekly_pnl = sum(_num(t.get("realized_pnl"), 0.0)
                     for d, trades in daily_trades.items()
                     if week_floor < d.replace("-", "")[:8] <= day
                     for t in trades)

    hist = _load_history(base_dir)
    equity = _num((account or {}).get("equity"))
    peak = _num(hist.get("peak_equity"))
    if equity is not None:
        peak = max(peak or equity, equity)

    limit = _daily_limit()
    return {
        "equity": equity,
        "peak_equity": peak,
        "drawdown_pct": (round((peak - equity) / peak, 6)
                         if equity is not None and peak else None),
        "daily_pnl": round(daily_pnl, 2),
        "weekly_pnl": round(weekly_pnl, 2),
        "daily_loss_limit": limit,
        "risk_remaining": round(max(0.0, limit + min(0.0, daily_pnl)), 2),
        "risk_efficiency": compute_risk_efficiency(daily_trades),
        **_ledger_stats(symbol, base_dir),
    }


# ── PHASE 3 — pure evaluators ─────────────────────────────────────────────────

def compute_drawdown_pressure(metrics: dict) -> int:
    dd = _num((metrics or {}).get("drawdown_pct"), 0.0) or 0.0
    return int(min(100, round(100 * dd / DD_CRITICAL)))


def compute_equity_health(metrics: dict) -> int:
    m = metrics or {}
    score = 100 - compute_drawdown_pressure(m)
    if _num(m.get("daily_pnl"), 0.0) < 0:
        score -= 10
    if _num(m.get("weekly_pnl"), 0.0) < 0:
        score -= 10
    return int(max(0, min(100, score)))


def compute_growth_strength(metrics: dict) -> int:
    m = metrics or {}
    exp = _num(m.get("expectancy"))
    score = 50
    if exp is not None:
        score += max(-40, min(40, round(exp * 40)))
    w = _num(m.get("weekly_pnl"), 0.0)
    score += 10 if w > 0 else (-10 if w < 0 else 0)
    return int(max(0, min(100, score)))


def compute_risk_efficiency_score(metrics: dict) -> "float | None":
    return (metrics or {}).get("risk_efficiency")


def evaluate_capital_state(metrics: dict) -> dict:
    """PHASE 2 state machine (pure). Returns the full capital report."""
    m = metrics or {}
    dd = _num(m.get("drawdown_pct"))
    daily = _num(m.get("daily_pnl"), 0.0)
    weekly = _num(m.get("weekly_pnl"), 0.0)
    limit = _num(m.get("daily_loss_limit"), _daily_limit()) or 500.0
    n = int(m.get("closed_trades") or 0)
    exp = _num(m.get("expectancy"))
    pf = _num(m.get("profit_factor"))

    reasons = []
    if daily <= -DAILY_CRITICAL_PCT * limit:
        state = STATE_CRITICAL
        reasons.append(f"daily_pnl {daily} within 20% of hard loss limit -{limit}")
    elif dd is not None and dd >= DD_CRITICAL:
        state = STATE_CRITICAL
        reasons.append(f"drawdown {dd:.1%} >= {DD_CRITICAL:.0%}")
    elif (dd is not None and dd >= DD_PRESERVATION) or weekly <= -WEEKLY_PRESERVE_X * limit:
        state = STATE_PRESERVATION
        reasons.append(f"deep drawdown ({dd if dd is not None else 'n/a'}) "
                       f"or weekly_pnl {weekly} <= -{WEEKLY_PRESERVE_X}x limit")
    elif (dd is not None and dd >= DD_DEFENSIVE) or daily <= -DAILY_DEFENSIVE_PCT * limit:
        state = STATE_DEFENSIVE
        reasons.append(f"drawdown ({dd if dd is not None else 'n/a'}) or "
                       f"daily_pnl {daily} past 50% of limit")
    elif n < MIN_SAMPLE_TRADES:
        state = STATE_PROBATION
        reasons.append(f"weak sample: {n} closed trades < {MIN_SAMPLE_TRADES}")
    elif (exp is not None and exp >= EXP_EXPANSION and pf is not None
          and pf >= PF_EXPANSION and (dd or 0.0) <= DD_EXPANSION_MAX
          and weekly > 0):
        state = STATE_EXPANSION
        reasons.append(f"expectancy {exp} >= {EXP_EXPANSION}, "
                       f"profit_factor {pf} >= {PF_EXPANSION}, equity at peak")
    elif exp is not None and exp > EXP_GROWTH and (dd or 0.0) <= DD_GROWTH_MAX and weekly > 0:
        state = STATE_GROWTH
        reasons.append(f"positive expectancy {exp}, healthy curve")
    else:
        state = STATE_STABLE
        reasons.append("flat normal conditions")

    flags = dict(_FLAGS.get(state, {}))
    actions = []
    if flags.get("trade_block"):
        actions.append("capital(critical): probation lock — entries blocked")
    if flags.get("risk_reduction"):
        actions.append(f"capital({state}): reduce size hard (existing halving rule)")
    if flags.get("confidence_penalty"):
        actions.append(f"capital({state}): reduce aggression (-10% confidence rule)")
    if state in (STATE_GROWTH, STATE_EXPANSION):
        actions.append(f"capital({state}): full risk-governor ceiling permitted "
                       "(no contraction; pressing above ceiling deferred)")

    return {
        "capital_authority":   AUTHORITY_LEVEL,
        "posture":             POSTURE,
        "capital_state":       state,
        "aggression_tier":     TIER[state],
        "equity_health_score": compute_equity_health(m),
        "drawdown_pressure":   compute_drawdown_pressure(m),
        "growth_strength":     compute_growth_strength(m),
        "risk_efficiency":     compute_risk_efficiency_score(m),
        "capital_mutation":    flags,           # existing actuators only
        "capital_pressure": {
            "drawdown_pct":       dd,
            "daily_pnl":          daily,
            "weekly_pnl":         weekly,
            "daily_loss_limit":   limit,
            "risk_remaining":     m.get("risk_remaining"),
            "daily_limit_used_pct": (round(min(1.0, -daily / limit), 4)
                                     if daily < 0 and limit else 0.0),
        },
        "capital_actions":     actions,
        "state_reasons":       reasons,
        "metrics":             {k: m.get(k) for k in (
            "equity", "peak_equity", "closed_trades", "expectancy",
            "win_rate", "profit_factor")},
    }


# ── scan-loop entry point (the ONLY writer) ───────────────────────────────────

def track_capital(symbol: str, account: "dict | None" = None,
                  today: "str | None" = None, base_dir=None,
                  persist: bool = True) -> dict:
    """One live-scan capital cycle: fetch equity (unless provided), gather
    metrics, evaluate state, persist peak-equity history. Never raises."""
    try:
        if account is None:
            try:
                from paper_execution.paper_broker import get_account
                account = get_account()
            except Exception:  # noqa: BLE001
                account = {}
        metrics = build_capital_metrics(symbol, account, today, base_dir)
        report = evaluate_capital_state(metrics)

        if persist and metrics.get("equity") is not None:
            hist = _load_history(base_dir)
            hist["peak_equity"] = metrics["peak_equity"]
            hist["last_equity"] = metrics["equity"]
            hist["updated_at"] = datetime.now(timezone.utc).isoformat()
            anchors = hist.setdefault("daily_anchors", {})
            day = (today or datetime.now(timezone.utc).strftime("%Y%m%d"))
            day = str(day).replace("-", "")[:8]
            anchors.setdefault(day, metrics["equity"])
            if len(anchors) > 30:                      # keep a month of anchors
                for k in sorted(anchors)[:-30]:
                    del anchors[k]
            _save_history(hist, base_dir)
        return report
    except Exception as exc:  # noqa: BLE001
        # fail-safe: unknown capital contributes NOTHING (never contracts on
        # unknown data, never presses either)
        report = evaluate_capital_state({"closed_trades": 0})
        report["capital_state"] = STATE_PROBATION
        report["aggression_tier"] = TIER[STATE_PROBATION]
        report["capital_mutation"] = {}
        report["capital_actions"] = []
        report["state_reasons"] = [f"capital_error:{type(exc).__name__} "
                                   "(neutral fail-safe)"]
        return report
