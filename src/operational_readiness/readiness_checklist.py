"""
Phase 2C — Operational Readiness Checklist.

Pure assessment — no orders, no execution changes, no broker submissions.
Evaluates 13 infrastructure and configuration checks and returns a
scored readiness report. A score of 100 means all checks pass.

Critical failures set ready=False regardless of score.
"""
import os
import json

_PROJECT_ROOT = os.path.dirname(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
)
_TRADES_DIR  = os.path.join(_PROJECT_ROOT, "data", "paper_trades")
_PAPER_MARKER = "paper-api.alpaca.markets"

# Point weight for each check — must sum to 100.
_WEIGHTS: dict[str, int] = {
    "paper_endpoint_verified":          20,
    "paper_only_mode":                  15,
    "execution_gate_present":           10,
    "position_monitor_present":         10,
    "stop_enforcer_present":            10,
    "alpaca_connected":                  8,
    "journal_writable":                  7,
    "trade_journal_present":             5,
    "market_data_available":             5,
    "daily_limits_present":              4,
    "risk_limits_present":               3,
    "intent_scoring_present":            2,
    "open_position_recovery_available":  1,
}

# Any of these failing sets ready=False.
_CRITICAL: frozenset[str] = frozenset({
    "paper_endpoint_verified",
    "paper_only_mode",
    "alpaca_connected",
    "journal_writable",
    "execution_gate_present",
    "position_monitor_present",
    "stop_enforcer_present",
})


# ── Individual check implementations ─────────────────────────────────────────

def _check_paper_endpoint() -> bool:
    url = os.getenv("ALPACA_BASE_URL", "").strip()
    return bool(url) and _PAPER_MARKER in url


def _check_paper_only_mode() -> bool:
    return os.getenv("PAPER_TRADING_ONLY", "false").lower().strip() == "true"


def _check_alpaca_connected() -> bool:
    """Lightweight broker connectivity check — calls get_account() once."""
    try:
        from paper_execution.paper_broker import get_account
        result = get_account()
        return isinstance(result, dict) and "error" not in result
    except Exception:
        return False


def _check_journal_writable() -> bool:
    """Write and delete a probe file inside data/paper_trades/."""
    try:
        os.makedirs(_TRADES_DIR, exist_ok=True)
        probe = os.path.join(_TRADES_DIR, "__readiness_probe__.tmp")
        with open(probe, "w", encoding="utf-8") as fh:
            json.dump({"probe": True}, fh)
        os.remove(probe)
        return True
    except Exception:
        return False


def _check_trade_journal_present() -> bool:
    """Trade journal module is importable and the data path is resolvable."""
    try:
        from paper_execution.trade_journal import (  # noqa: F401
            load_today_trades, find_active_trade,
        )
        return True
    except ImportError:
        return False


def _check_market_data(snapshot: dict) -> bool:
    """Snapshot contains at least one timeframe with a last_candle."""
    tfs = snapshot.get("timeframes", {})
    if not tfs:
        return False
    return any(
        tfs.get(tf, {}).get("last_candle") is not None
        for tf in ("1m", "3m", "5m", "15m")
    )


def _check_daily_limits() -> bool:
    return bool(
        os.getenv("MAX_TRADES_PER_DAY") and os.getenv("DAILY_LOSS_LIMIT_DOLLARS")
    )


def _check_risk_limits() -> bool:
    return bool(
        os.getenv("RISK_PER_TRADE_DOLLARS") and os.getenv("MIN_INTENT_GATED_SCORE")
    )


def _check_recovery_available() -> bool:
    """Both find_active_trade and monitor_paper_position are importable."""
    try:
        from paper_execution.trade_journal   import find_active_trade       # noqa: F401
        from paper_execution.position_monitor import monitor_paper_position  # noqa: F401
        return True
    except ImportError:
        return False


# ── Public entry point ────────────────────────────────────────────────────────

def run_readiness_check(snapshot: dict) -> dict:
    """
    Phase 2C — run all 13 operational readiness checks.

    Returns a scored dict with ready / score / checks / warnings / blocking_issues.
    Never raises — any internal error is captured and returned as a blocking issue.
    """
    try:
        return _run(snapshot)
    except Exception as exc:
        return {
            "ready":           False,
            "score":           0,
            "checks":          {k: False for k in _WEIGHTS},
            "warnings":        [],
            "blocking_issues": [f"readiness check crashed: {exc}"],
        }


def _run(snapshot: dict) -> dict:
    checks: dict[str, bool] = {}
    warnings:       list[str] = []
    blocking_issues: list[str] = []

    # ── Static / env checks ───────────────────────────────────────────────────
    checks["paper_endpoint_verified"]        = _check_paper_endpoint()
    checks["paper_only_mode"]                = _check_paper_only_mode()
    checks["alpaca_connected"]               = _check_alpaca_connected()
    checks["journal_writable"]               = _check_journal_writable()
    checks["trade_journal_present"]          = _check_trade_journal_present()
    checks["daily_limits_present"]           = _check_daily_limits()
    checks["risk_limits_present"]            = _check_risk_limits()
    checks["open_position_recovery_available"] = _check_recovery_available()

    # ── Snapshot-derived checks ───────────────────────────────────────────────
    checks["execution_gate_present"]   = bool(snapshot.get("execution_gate"))
    checks["position_monitor_present"] = "position_monitor" in snapshot
    checks["stop_enforcer_present"]    = "stop_enforcer"    in snapshot
    checks["intent_scoring_present"]   = bool(snapshot.get("intent_score"))
    checks["market_data_available"]    = _check_market_data(snapshot)

    # ── Score ─────────────────────────────────────────────────────────────────
    deduction = sum(
        _WEIGHTS.get(k, 0) for k, passed in checks.items() if not passed
    )
    score = max(0, 100 - deduction)

    # ── Classify failures ─────────────────────────────────────────────────────
    for k in _CRITICAL:
        if not checks.get(k, False):
            blocking_issues.append(k)

    for k, passed in checks.items():
        if not passed and k not in _CRITICAL:
            warnings.append(f"{k} check failed")

    return {
        "ready":           len(blocking_issues) == 0,
        "score":           score,
        "checks":          checks,
        "warnings":        warnings,
        "blocking_issues": blocking_issues,
    }
