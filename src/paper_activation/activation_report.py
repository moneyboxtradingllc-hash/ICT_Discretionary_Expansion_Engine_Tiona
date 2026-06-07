"""
Phase 2D — Activation Report.

Provides a human-readable summary of the activation state and persists
activation events to data/activation_reports/ for audit purposes.

Written on every status-change scan so the user has a full log of when
the system armed, blocked, or completed its day — without cluttering the
snapshot store.
"""
import os
import json
from datetime import datetime

import pytz

_EASTERN      = pytz.timezone("America/New_York")
_PROJECT_ROOT = os.path.dirname(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
)
_REPORTS_DIR  = os.path.join(_PROJECT_ROOT, "data", "activation_reports")


def format_report_line(plan: dict, runner: dict) -> str:
    """
    Return a compact one-line activation summary for console / formatter use.

    Examples:
      "DISABLED | PAPER_ACTIVATION_MODE=false"
      "ARMED | QQQ | max_trades=1 | risk=$100"
      "BLOCKED | outside market hours"
      "NOT_READY | EXECUTION_ENABLED=false"
      "COMPLETED_FOR_DAY | max trades reached (1)"
    """
    status = (runner.get("status") or "disabled").upper()
    reason = runner.get("reason", "")
    symbol = plan.get("symbol", "?")
    max_t  = plan.get("max_trades", 1)
    risk_d = plan.get("risk_dollars", 100)

    if status == "ARMED":
        return f"ARMED | {symbol} | max_trades={max_t} | risk=${risk_d:.0f}"
    if status == "DISABLED":
        return "DISABLED | PAPER_ACTIVATION_MODE=false"
    if reason:
        return f"{status} | {reason}"
    return status


def log_activation_event(plan: dict, runner: dict, symbol: str) -> None:
    """
    Persist the current activation state to data/activation_reports/.
    Only writes when status is noteworthy (not plain 'disabled').
    Silently swallows all I/O errors — never crashes the scan loop.
    """
    status = runner.get("status", "disabled")
    if status == "disabled":
        return   # no log entry for routine disabled state

    try:
        os.makedirs(_REPORTS_DIR, exist_ok=True)
        now_et   = datetime.now(_EASTERN)
        date_str = now_et.strftime("%Y%m%d")
        filename = f"{date_str}_{symbol}_activation.json"
        filepath = os.path.join(_REPORTS_DIR, filename)

        # Load existing log or start fresh
        if os.path.exists(filepath):
            try:
                with open(filepath, "r", encoding="utf-8") as fh:
                    log = json.load(fh)
            except Exception:
                log = {"date": date_str, "symbol": symbol, "events": []}
        else:
            log = {"date": date_str, "symbol": symbol, "events": []}

        event = {
            "timestamp":    now_et.strftime("%Y%m%dT%H%M%S"),
            "status":       status,
            "reason":       runner.get("reason", ""),
            "armed":        runner.get("paper_trading_armed", False),
            "blocking":     plan.get("blocking_issues", []),
            "warnings":     runner.get("warnings", []),
        }

        log["events"].append(event)

        with open(filepath, "w", encoding="utf-8") as fh:
            json.dump(log, fh, indent=2, default=str)

    except Exception:
        pass   # never crash the scan loop
