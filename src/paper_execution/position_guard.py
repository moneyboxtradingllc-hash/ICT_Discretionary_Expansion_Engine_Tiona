"""
Phase 2A — Position Guard.

Pre-execution safety gate that runs immediately before any paper order.
All checks must pass before an order is allowed to proceed.

Checks:
  1. paper_mode_enabled    — PAPER_TRADING_ONLY=true
  2. paper_orders_allowed  — ALLOW_PAPER_ORDERS=true
  3. paper_endpoint_safe   — ALPACA_BASE_URL is the paper endpoint
  4. one_position_guard    — no open positions (if ONE_POSITION_AT_A_TIME=true)
  5. max_trades_guard      — trades_today < MAX_TRADES_PER_DAY
  6. daily_loss_guard      — risk_used_today < DAILY_LOSS_LIMIT_DOLLARS
  7. no_duplicate_intent   — this intent_id not already journaled as submitted

Returns:
  {
    "allowed": bool,
    "reason": str,
    "checks": { check_name: bool, ... },
    "warnings": [...],
    "trades_today": int,
    "risk_used_today": float,
  }
"""
import os

from paper_execution.paper_broker  import is_paper_account_safe, get_open_positions
from paper_execution.trade_journal import (
    count_submitted_today, total_risk_today, intent_already_journaled,
)


def check_all(snapshot: dict, symbol: str, intent_id: str | None) -> dict:
    """
    Run all pre-execution guards.  Fail-safe: any exception blocks execution.
    """
    checks   = {}
    warnings = []

    try:
        # 1. Paper-only mode flag
        paper_only = os.getenv("PAPER_TRADING_ONLY", "false").lower().strip()
        checks["paper_mode_enabled"] = paper_only == "true"

        # 2. Paper orders explicitly allowed
        allow_orders = os.getenv("ALLOW_PAPER_ORDERS", "false").lower().strip()
        checks["paper_orders_allowed"] = allow_orders == "true"

        # 3. Endpoint safety (config check only — no network call)
        ep_safe, ep_reason = is_paper_account_safe()
        checks["paper_endpoint_safe"] = ep_safe
        if not ep_safe:
            warnings.append(f"Endpoint check: {ep_reason}")

        # 4. One-position guard
        one_position = os.getenv("ONE_POSITION_AT_A_TIME", "true").lower().strip()
        if one_position == "true":
            open_pos = get_open_positions()
            # Any entry with an "error" key means API failed → conservative block
            has_error    = any("error" in p for p in open_pos)
            has_position = len(open_pos) > 0
            if has_error:
                checks["one_position_guard"] = False
                warnings.append("Could not verify open positions — blocking as safe default")
            else:
                checks["one_position_guard"] = not has_position
                if has_position:
                    symbols = [p.get("symbol", "?") for p in open_pos]
                    warnings.append(f"Open position(s) exist: {symbols}")
        else:
            checks["one_position_guard"] = True

        # 5. Max trades per day
        max_trades   = int(os.getenv("MAX_TRADES_PER_DAY", "2"))
        trades_today = count_submitted_today(symbol)
        checks["max_trades_guard"] = trades_today < max_trades
        if trades_today >= max_trades:
            warnings.append(f"Max trades reached ({trades_today}/{max_trades})")

        # 6. Daily loss limit (conservative: sum of risk_dollars from submitted trades)
        daily_limit    = float(os.getenv("DAILY_LOSS_LIMIT_DOLLARS", "1000"))
        risk_used_today = total_risk_today(symbol)
        checks["daily_loss_guard"] = risk_used_today < daily_limit
        if risk_used_today >= daily_limit:
            warnings.append(
                f"Daily risk limit reached: ${risk_used_today:.2f} >= ${daily_limit:.2f}"
            )

        # 7. No duplicate intent
        if intent_id:
            already = intent_already_journaled(intent_id, symbol)
            checks["no_duplicate_intent"] = not already
            if already:
                warnings.append(f"Intent {intent_id} already submitted today")
        else:
            checks["no_duplicate_intent"] = True  # No ID → can't deduplicate, allow

    except Exception as exc:
        # Any unexpected exception → block and report
        checks["unexpected_error"] = False
        warnings.append(f"Position guard error: {exc}")

    allowed = all(checks.values())

    # Build reason from first failed check
    first_fail = next((k for k, v in checks.items() if not v), None)
    if allowed:
        reason = "all position guards passed"
    else:
        reason = _reason_for(first_fail, warnings)

    return {
        "allowed":         allowed,
        "reason":          reason,
        "checks":          checks,
        "warnings":        warnings[:5],
        "trades_today":    trades_today if "trades_today" in dir() else 0,
        "risk_used_today": risk_used_today if "risk_used_today" in dir() else 0.0,
    }


def _reason_for(check_name: str | None, warnings: list) -> str:
    _messages = {
        "paper_mode_enabled":   "PAPER_TRADING_ONLY is not 'true'",
        "paper_orders_allowed": "ALLOW_PAPER_ORDERS is not 'true'",
        "paper_endpoint_safe":  "Alpaca endpoint is not the paper endpoint",
        "one_position_guard":   "open position exists (ONE_POSITION_AT_A_TIME=true)",
        "max_trades_guard":     "max trades per day exceeded",
        "daily_loss_guard":     "daily risk limit reached",
        "no_duplicate_intent":  "intent already submitted today",
        "unexpected_error":     "unexpected error in position guard",
    }
    if check_name and check_name in _messages:
        return _messages[check_name]
    return warnings[0] if warnings else "position guard check failed"
