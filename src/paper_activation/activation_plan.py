"""
Phase 2D — Activation Plan Builder.

Evaluates all 14 controlled-activation requirements for this scan iteration.
Pure assessment — no orders, no execution changes, no broker state mutation.

NOTE: This runs BEFORE operational_readiness / activation_controller are
computed in the scan pipeline, so requirements 1-2 are checked via direct
env/broker calls rather than from the snapshot.
"""
import os

from data_feed.market_clock import is_within_scan_window
from paper_execution.paper_broker  import is_paper_account_safe
from paper_execution.trade_journal import count_submitted_today

_PAPER_MARKER = "paper-api.alpaca.markets"

# Requirements that indicate a transient operational block (not a config gap).
# Runner will use "blocked" status for these rather than "not_ready".
_BLOCKED_REQUIREMENTS = frozenset({
    "within_market_hours",
    "no_open_position",
})

# When only this requirement fails, runner uses "completed_for_day".
_COMPLETED_REQUIREMENT = "trades_below_max"


def build_activation_plan(snapshot: dict, symbol: str) -> dict:
    """
    Phase 2D — evaluate all 14 activation requirements for this scan.
    Never raises — errors return a safe blocked plan.
    """
    try:
        return _build(snapshot, symbol)
    except Exception as exc:
        return {
            "activation_mode":    False,
            "armed":              False,
            "symbol":             symbol,
            "max_trades":         int(os.getenv("PAPER_ACTIVATION_MAX_TRADES", "1")),
            "risk_dollars":       float(os.getenv("PAPER_ACTIVATION_RISK_DOLLARS", "100")),
            "requirements_passed": False,
            "requirements":       {},
            "blocking_issues":    [f"plan build error: {exc}"],
            "warnings":           [],
            "reason":             f"plan error: {exc}",
        }


def _build(snapshot: dict, symbol: str) -> dict:

    activation_mode = os.getenv("PAPER_ACTIVATION_MODE", "false").lower().strip() == "true"
    max_trades      = int(os.getenv("PAPER_ACTIVATION_MAX_TRADES",          "1"))
    risk_dollars    = float(os.getenv("PAPER_ACTIVATION_RISK_DOLLARS",     "100"))
    req_mkt_hours   = os.getenv("PAPER_ACTIVATION_REQUIRE_MARKET_HOURS", "true").lower().strip() == "true"
    act_symbol      = os.getenv("PAPER_ACTIVATION_SYMBOL", "QQQ").upper().strip()
    scan_start      = os.getenv("SCAN_START_TIME", "08:30")
    scan_end        = os.getenv("SCAN_END_TIME",   "15:00")

    # ── Short-circuit when activation mode is off ─────────────────────────────
    if not activation_mode:
        return {
            "activation_mode":    False,
            "armed":              False,
            "symbol":             symbol,
            "max_trades":         max_trades,
            "risk_dollars":       risk_dollars,
            "requirements_passed": False,
            "requirements":       {},
            "blocking_issues":    [],
            "warnings":           [],
            "reason":             "PAPER_ACTIVATION_MODE=false",
        }

    req: dict[str, bool] = {}
    warnings: list[str]  = []

    # ── 1. Infrastructure / paper safety ──────────────────────────────────────
    ep_safe, _  = is_paper_account_safe()
    req["operational_ready"] = ep_safe   # PAPER_TRADING_ONLY + endpoint check

    # ── 2. All activation controller conditions (direct env check) ────────────
    req["activation_controller_ok"] = (
        os.getenv("EXECUTION_ENABLED",    "false").lower().strip() == "true"
        and os.getenv("ALLOW_PAPER_ORDERS", "false").lower().strip() == "true"
        and _PAPER_MARKER in os.getenv("ALPACA_BASE_URL", "")
        and os.getenv("PAPER_TRADING_ONLY",  "false").lower().strip() == "true"
    )

    # ── 3. EXECUTION_ENABLED ──────────────────────────────────────────────────
    req["execution_enabled"] = (
        os.getenv("EXECUTION_ENABLED", "false").lower().strip() == "true"
    )

    # ── 4. ALLOW_PAPER_ORDERS ─────────────────────────────────────────────────
    req["paper_orders_allowed"] = (
        os.getenv("ALLOW_PAPER_ORDERS", "false").lower().strip() == "true"
    )

    # ── 5. PAPER_TRADING_ONLY ─────────────────────────────────────────────────
    req["paper_only_mode"] = (
        os.getenv("PAPER_TRADING_ONLY", "false").lower().strip() == "true"
    )

    # ── 6. PAPER_EXIT_ON_STOP ─────────────────────────────────────────────────
    req["exit_on_stop_enabled"] = (
        os.getenv("PAPER_EXIT_ON_STOP", "false").lower().strip() == "true"
    )

    # ── 7. MAX_TRADES_PER_DAY must not exceed activation limit ────────────────
    try:
        sys_max_trades = int(os.getenv("MAX_TRADES_PER_DAY", "2"))
        req["max_trades_safe"] = sys_max_trades <= max_trades
    except ValueError:
        req["max_trades_safe"] = False
        warnings.append("MAX_TRADES_PER_DAY is not a valid integer")

    # ── 8. RISK_PER_TRADE_DOLLARS must not exceed activation limit ────────────
    try:
        sys_risk = float(os.getenv("RISK_PER_TRADE_DOLLARS", "500"))
        req["risk_dollars_safe"] = sys_risk <= risk_dollars
    except ValueError:
        req["risk_dollars_safe"] = False
        warnings.append("RISK_PER_TRADE_DOLLARS is not a valid number")

    # ── 9. DAILY_LOSS_LIMIT_DOLLARS must not exceed activation limit ──────────
    try:
        sys_daily_loss = float(os.getenv("DAILY_LOSS_LIMIT_DOLLARS", "1000"))
        req["daily_loss_safe"] = sys_daily_loss <= risk_dollars
    except ValueError:
        req["daily_loss_safe"] = False
        warnings.append("DAILY_LOSS_LIMIT_DOLLARS is not a valid number")

    # ── 10. ONE_POSITION_AT_A_TIME ────────────────────────────────────────────
    req["one_position_only"] = (
        os.getenv("ONE_POSITION_AT_A_TIME", "false").lower().strip() == "true"
    )

    # ── 11. No open position (from position_monitor in snapshot) ──────────────
    pm = snapshot.get("position_monitor", {})
    req["no_open_position"] = not pm.get("has_open_position", False)

    # ── 12. Trade count below daily max ───────────────────────────────────────
    try:
        trades_today       = count_submitted_today(symbol)
        req["trades_below_max"] = trades_today < max_trades
    except Exception as exc:
        req["trades_below_max"] = False
        warnings.append(f"trade count check failed: {exc}")

    # ── 13. Within market hours (if required) ─────────────────────────────────
    if req_mkt_hours:
        req["within_market_hours"] = is_within_scan_window(scan_start, scan_end)
    else:
        req["within_market_hours"] = True

    # ── 14. Symbol match ──────────────────────────────────────────────────────
    req["correct_symbol"] = symbol.upper().strip() == act_symbol

    # ── Collect blocking issues ───────────────────────────────────────────────
    blocking: list[str] = [k for k, passed in req.items() if not passed]

    all_passed = len(blocking) == 0

    # Derive concise reason for display
    reason = _derive_reason(blocking, req, max_trades, risk_dollars)

    return {
        "activation_mode":     True,
        "armed":               all_passed,
        "symbol":              symbol,
        "max_trades":          max_trades,
        "risk_dollars":        risk_dollars,
        "requirements_passed": all_passed,
        "requirements":        req,
        "blocking_issues":     blocking,
        "warnings":            warnings,
        "reason":              reason,
    }


def _derive_reason(
    blocking: list[str],
    req: dict[str, bool],
    max_trades: int,
    risk_dollars: float,
) -> str:
    if not blocking:
        return "all requirements passed"
    first = blocking[0]
    messages = {
        "operational_ready":       "paper endpoint or PAPER_TRADING_ONLY not configured",
        "activation_controller_ok": "EXECUTION_ENABLED or ALLOW_PAPER_ORDERS not set",
        "execution_enabled":        "EXECUTION_ENABLED=false",
        "paper_orders_allowed":     "ALLOW_PAPER_ORDERS=false",
        "paper_only_mode":          "PAPER_TRADING_ONLY=false",
        "exit_on_stop_enabled":     "PAPER_EXIT_ON_STOP=false",
        "max_trades_safe":          f"MAX_TRADES_PER_DAY exceeds activation limit ({max_trades})",
        "risk_dollars_safe":        f"RISK_PER_TRADE_DOLLARS exceeds activation limit (${risk_dollars:.0f})",
        "daily_loss_safe":          f"DAILY_LOSS_LIMIT_DOLLARS exceeds activation limit (${risk_dollars:.0f})",
        "one_position_only":        "ONE_POSITION_AT_A_TIME=false",
        "no_open_position":         "open position exists — wait for close",
        "trades_below_max":         f"max trades for day reached ({max_trades})",
        "within_market_hours":      "outside market hours",
        "correct_symbol":           f"symbol mismatch (expected {os.getenv('PAPER_ACTIVATION_SYMBOL','QQQ')})",
    }
    return messages.get(first, first)
