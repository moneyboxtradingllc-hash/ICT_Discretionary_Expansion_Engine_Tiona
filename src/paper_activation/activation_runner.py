"""
Phase 2D — Activation Runner.

Derives the final paper trading activation status from the plan built by
activation_plan.py.  Does NOT submit orders.  Does NOT modify execution
engine logic.  Solely determines whether allow_order_attempts should be True.

Statuses:
  disabled          — PAPER_ACTIVATION_MODE=false
  not_ready         — config/infrastructure requirements missing
  blocked           — operational conditions unmet (market hours, open position)
  completed_for_day — daily trade limit reached
  armed             — all requirements pass; order attempts are allowed
"""

from paper_activation.activation_plan import _BLOCKED_REQUIREMENTS, _COMPLETED_REQUIREMENT


def run_activation(plan: dict, symbol: str) -> dict:
    """
    Phase 2D — derive paper trading activation status from the plan.
    Never raises.
    """
    try:
        return _evaluate(plan, symbol)
    except Exception as exc:
        return {
            "status":               "not_ready",
            "paper_trading_armed":  False,
            "allow_order_attempts": False,
            "reason":               f"activation runner error: {exc}",
            "warnings":             [str(exc)],
        }


def _evaluate(plan: dict, symbol: str) -> dict:

    # ── Activation mode is off ────────────────────────────────────────────────
    if not plan.get("activation_mode", False):
        return {
            "status":               "disabled",
            "paper_trading_armed":  False,
            "allow_order_attempts": False,
            "reason":               "activation mode disabled",
            "warnings":             [],
        }

    # ── All requirements passed → armed ───────────────────────────────────────
    if plan.get("requirements_passed", False):
        return {
            "status":               "armed",
            "paper_trading_armed":  True,
            "allow_order_attempts": True,
            "reason":               plan.get("reason", "all requirements passed"),
            "warnings":             plan.get("warnings", []),
        }

    # ── Requirements failed — categorise ─────────────────────────────────────
    blocking  = plan.get("blocking_issues", [])
    reason    = plan.get("reason", "requirements not met")
    warnings  = plan.get("warnings", [])

    # completed_for_day: only the trade-limit key is failing
    if blocking == [_COMPLETED_REQUIREMENT] or set(blocking) == {_COMPLETED_REQUIREMENT}:
        return {
            "status":               "completed_for_day",
            "paper_trading_armed":  False,
            "allow_order_attempts": False,
            "reason":               reason,
            "warnings":             warnings,
        }

    # blocked: at least one blocked-condition fails (may mix with others)
    has_blocked = any(k in _BLOCKED_REQUIREMENTS for k in blocking)
    if has_blocked:
        # Find the first blocked condition for the reason string
        first_blocked = next(k for k in blocking if k in _BLOCKED_REQUIREMENTS)
        blocked_reasons = {
            "within_market_hours": "outside market hours",
            "no_open_position":    "open position exists — cannot arm",
        }
        return {
            "status":               "blocked",
            "paper_trading_armed":  False,
            "allow_order_attempts": False,
            "reason":               blocked_reasons.get(first_blocked, reason),
            "warnings":             warnings,
        }

    # not_ready: config / infrastructure gap
    return {
        "status":               "not_ready",
        "paper_trading_armed":  False,
        "allow_order_attempts": False,
        "reason":               reason,
        "warnings":             warnings,
    }
