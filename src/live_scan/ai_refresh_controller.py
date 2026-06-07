"""
AI Refresh Controller — Phase 1P.
Decides when to call the external AI provider vs reuse the last cached result.

Decision uses the PREVIOUS scan's snapshot state so no lookahead is needed.
The very first scan always calls external AI.

Signal-based triggers (checked against previous scan):
  - qualification.status in candidate / qualified / elite
  - risk_governor.trade_allowed is True
  - toolbox.best_available_raw_status is actionable

Time-based trigger: AI_REFRESH_SECONDS elapsed since last successful call.
"""

from datetime import datetime, timezone


class AIRefreshController:

    def __init__(self, refresh_seconds: int = 60):
        self._refresh_seconds    = refresh_seconds
        self._last_refresh_time  = None
        self._cached_result      = None   # last successful external ai_discretionary dict
        self._last_state         = None   # key fields captured after each completed scan

    # ── Public API ────────────────────────────────────────────────────────────

    def should_refresh(self) -> bool:
        """Return True if the external AI provider should be called this scan."""
        if self._cached_result is None:
            return True  # first scan — no prior result

        now     = datetime.now(timezone.utc)
        elapsed = (now - self._last_refresh_time).total_seconds()
        if elapsed >= self._refresh_seconds:
            return True

        # Signal-based: check last scan's resolved state
        if self._last_state:
            s = self._last_state
            if s.get("qual_status") in ("candidate", "qualified", "elite"):
                return True
            if s.get("trade_allowed"):
                return True
            if s.get("best_tool_status") == "actionable":
                return True

        return False

    def record_refresh(self, ai_disc: dict):
        """Cache a successful external AI result and stamp the refresh time."""
        self._cached_result                  = {k: v for k, v in ai_disc.items()}
        self._cached_result["ai_reused"]     = False   # mark as a fresh result
        self._last_refresh_time              = datetime.now(timezone.utc)

    def update_state(self, snapshot: dict):
        """Capture key fields from the just-completed scan for next iteration's decision."""
        self._last_state = {
            "qual_status":      snapshot.get("qualification", {}).get("status"),
            "trade_allowed":    snapshot.get("risk",          {}).get("trade_allowed", False),
            "best_tool_status": snapshot.get("toolbox",       {}).get("best_available_raw_status"),
        }

    def get_reused(self) -> dict:
        """Return the cached external result tagged with reuse metadata."""
        result  = dict(self._cached_result)
        elapsed = int((datetime.now(timezone.utc) - self._last_refresh_time).total_seconds())
        result["ai_reused"]                   = True
        result["ai_last_refresh_age_seconds"] = elapsed
        return result

    @property
    def has_cached_result(self) -> bool:
        return self._cached_result is not None
