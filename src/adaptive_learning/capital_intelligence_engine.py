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


#: RISK-DOCTRINE-MIGRATION (operator, 2026-08-20): $500 -> $725.
#: Two trades a day at the $350 per-trade ceiling is $700; the extra $25 is
#: headroom for commissions, fees and rounding, so the hard daily stop is not
#: set exactly at the theoretical planned-risk sum.
DEFAULT_DAILY_LOSS_LIMIT_USD = 725.0


def _daily_limit() -> float:
    try:
        return float(os.getenv("DAILY_LOSS_LIMIT_DOLLARS",
                               str(DEFAULT_DAILY_LOSS_LIMIT_USD)))
    except (TypeError, ValueError):
        return DEFAULT_DAILY_LOSS_LIMIT_USD


# ── persistence (scan loop is the only writer) ────────────────────────────────

def _history_path(base_dir: "str | None" = None, create: bool = False) -> str:
    d = os.path.join(performance_root(base_dir), ACCOUNT_KEY)
    if create:                      # writers only — readers never create dirs
        os.makedirs(d, exist_ok=True)
    return os.path.join(d, HISTORY_FILE)


# DECONTAMINATE (2026-08-06): capital history carried NO account binding at all.
# Anchors 20260706..20260805 all read 99990.53 -- an Alpaca paper balance reaching
# this file through the equity leak repaired in 9af35f1. The Topstep Combine is a
# $50k account, so drawdown pressure and Brain aggression were being computed
# against a peak belonging to a different venue and a different account.
CAPITAL_SCHEMA_VERSION = 2
_IDENTITY_FIELDS = ("venue", "account_fingerprint", "account_mode", "currency",
                    "schema_version")


def capital_identity(*, venue: str = "", account_fingerprint: str = "",
                     account_mode: str = "", currency: str = "USD") -> dict:
    """The identity a capital record must carry to be trusted."""
    return {"venue": (venue or "").upper(), "account_fingerprint": account_fingerprint or "",
            "account_mode": (account_mode or "").upper(), "currency": (currency or "USD").upper(),
            "schema_version": CAPITAL_SCHEMA_VERSION}


def identity_matches(hist: dict, identity: dict) -> tuple:
    """(ok, reason). Absent identity is REJECTED, never assumed compatible."""
    if not identity or not identity.get("account_fingerprint"):
        return False, "no_session_identity"
    stored = {k: (hist or {}).get(k) for k in _IDENTITY_FIELDS}
    if not any(stored.values()):
        return False, "history_has_no_identity"
    for field in ("venue", "account_fingerprint", "account_mode", "currency"):
        if stored.get(field) != identity.get(field):
            return False, f"identity_mismatch:{field}"
    if int(stored.get("schema_version") or 0) != CAPITAL_SCHEMA_VERSION:
        return False, "schema_version_mismatch"
    return True, "same_account"


def _load_history(base_dir=None, identity: dict = None) -> dict:
    """Load history, but only history proven to belong to THIS account.

    A foreign or identity-less record is returned as a quarantined shell: its
    equity never becomes a peak, and the contamination is reported rather than
    silently dropped.
    """
    try:
        with open(_history_path(base_dir), encoding="utf-8") as fh:
            data = json.load(fh)
        data = data if isinstance(data, dict) else {}
    except (FileNotFoundError, ValueError, OSError):
        data = {}
    if identity is None:
        return data                      # legacy/diagnostic read, unchanged
    ok, reason = identity_matches(data, identity)
    if ok:
        return data
    return {"_quarantined_history": {k: data.get(k) for k in
                                     ("peak_equity", "last_equity", "updated_at")},
            "_quarantine_reason": reason,
            "_quarantined_anchor_count": len(data.get("daily_anchors") or {}),
            **identity}


def _save_history(hist: dict, base_dir=None) -> None:
    path = _history_path(base_dir, create=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(hist, fh, indent=2, sort_keys=True)
    os.replace(tmp, path)


# ── journal / ledger metrics (read-only) ──────────────────────────────────────

def _journal_dir() -> str:
    return os.getenv("PAPER_TRADES_DIR") or os.path.join("data", "paper_trades")


def _closed_trades_by_date() -> dict:
    """{date: [closed trade dicts]} from the day journals — CURRENT ORGANISM
    ONLY. Pre-epoch trades (pre-AI-Brain / manual-close era) are historical
    evidence and never reach capital interpretation. Read-only."""
    from adaptive_learning.performance_tables import organism_epoch
    epoch = organism_epoch()
    out = {}
    for path in sorted(glob.glob(os.path.join(_journal_dir(),
                                              "*_paper_trades.json"))):
        try:
            with open(path, encoding="utf-8") as fh:
                day = json.load(fh)
        except (OSError, ValueError):
            continue
        date = str(day.get("date") or os.path.basename(path)[:8])
        if date.replace("-", "")[:8] < epoch:
            continue
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
                          base_dir=None, identity: dict = None) -> dict:
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

    hist = _load_history(base_dir, identity=identity)
    equity = _num((account or {}).get("equity"))
    # A quarantined history contributes NO peak. The peak then initializes from
    # this account's own verified equity, which is the only same-account
    # evidence that exists.
    peak = None if hist.get("_quarantine_reason") else _num(hist.get("peak_equity"))
    peak_source = "same_account_history"
    if peak is None:
        peak_source = ("initialized_from_verified_balance"
                       if equity is not None else "unavailable")
    if equity is not None:
        peak = max(peak or equity, equity)

    limit = _daily_limit()
    quarantine = hist.get("_quarantine_reason")
    return {
        "equity": equity,
        "peak_equity": peak,
        "peak_equity_source": peak_source,
        "capital_identity": identity,
        "foreign_history_quarantined": quarantine,
        "quarantined_peak": (hist.get("_quarantined_history") or {}).get("peak_equity")
                            if quarantine else None,
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
    limit = _num(m.get("daily_loss_limit"), _daily_limit()) or DEFAULT_DAILY_LOSS_LIMIT_USD
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
                  persist: bool = True, identity: dict = None) -> dict:
    """One live-scan capital cycle: fetch equity (unless provided), gather
    metrics, evaluate state, persist peak-equity history. Never raises."""
    try:
        if account is None:
            # DECON-3 (2026-08-05): this fell back to `paper_broker.get_account()`,
            # which reads the ALPACA paper account. On a TopstepX MNQ session that
            # computed drawdown pressure and aggression tier from an unrelated
            # equities balance and fed it into the snapshot the Brain reads.
            # The caller now supplies the real account, or capital contributes
            # nothing — an unknown balance is reported, never substituted.
            account = {}
        metrics = build_capital_metrics(symbol, account, today, base_dir,
                                        identity=identity)
        report = evaluate_capital_state(metrics)

        if persist and metrics.get("equity") is not None:
            hist = _load_history(base_dir, identity=identity)
            if hist.get("_quarantine_reason"):
                # Start a clean same-account history. The rejected record is
                # preserved beside it as evidence, never merged, never relabelled.
                hist = {**(identity or {}),
                        "rejected_foreign_history": hist.get("_quarantined_history"),
                        "rejected_reason": hist.get("_quarantine_reason"),
                        "rejected_anchor_count": hist.get("_quarantined_anchor_count"),
                        "initialized_from": "verified_same_account_balance"}
            elif identity:
                hist.update(identity)
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
