"""
Phase NA-1 — Protected Swing Intelligence.

June 11 gap: the 10:00 buy-side raid created a protected high and the
~11:00 sell-side raid created a protected low, and no subsystem modeled
either. The structure engine counted the raid wick as a higher high
(bullish strength); the liquidity engine detected the sweep but forgot it
one scan later. Protected levels are the system's first persistent
liquidity memory.

Definitions (ICT semantics, same primitives as liquidity_engine):
  PROTECTED HIGH — a swing high swept from below (above_high) whose raid
    was rejected (reclaim: close back below). Buy stops there are spent;
    the high is defended until price CLOSES back above it.
  PROTECTED LOW — mirror image (below_low sweep + reclaim), defended until
    price closes back below it.

The tracker is stateful across scans (like SetupTracker): a protected
level persists until violated, not until the next scan forgets the sweep.

Never raises. State degrades safely on missing data.
"""
import os

_REGISTER_TFS = ("15m", "5m")   # raids on these timeframes create protected levels


def _violation_buffer_pct() -> float:
    try:
        return float(os.getenv("NARRATIVE_PROTECTED_BUFFER_PCT", "0.05")) / 100.0
    except (TypeError, ValueError):
        return 0.0005


def _current_price(snapshot: dict) -> "float | None":
    tfs = snapshot.get("timeframes", {}) or {}
    for tf in ("1m", "3m", "5m", "15m"):
        lc = (tfs.get(tf) or {}).get("last_candle")
        if lc and lc.get("close") is not None:
            try:
                return float(lc["close"])
            except (TypeError, ValueError):
                pass
    ez = (snapshot.get("trade_intent", {}) or {}).get("entry_zone") or {}
    cp = ez.get("current_price")
    try:
        return float(cp) if cp is not None else None
    except (TypeError, ValueError):
        return None


class ProtectedSwingTracker:
    """Tracks the active protected high/low across scans."""

    def __init__(self):
        self.protected_high = None   # {"level", "timeframe", "registered_at", "basis"}
        self.protected_low  = None

    def update(self, snapshot: dict) -> dict:
        """
        Register new protected levels from this scan's sweep evidence and
        clear violated ones. Returns the current state dict. Never raises.
        """
        try:
            return self._update(snapshot or {})
        except Exception as exc:  # noqa: BLE001
            return self.state(warnings=[f"protected swing tracker error: {exc}"])

    def _update(self, snapshot: dict) -> dict:
        liquidity = snapshot.get("liquidity", {}) or {}
        structure = snapshot.get("structure", {}) or {}
        ts        = snapshot.get("timestamp", "")
        price     = _current_price(snapshot)

        # ── Registration: sweep + reclaim on a registering timeframe ─────────
        for tf in _REGISTER_TFS:
            liq = liquidity.get(tf, {}) or {}
            if not (liq.get("sweep_detected") and liq.get("reclaim_detected")):
                continue
            st    = structure.get(tf, {}) or {}
            sweep = liq.get("sweep_direction", "")
            if sweep == "above_high" and st.get("last_swing_high") is not None:
                level = float(st["last_swing_high"])
                if (self.protected_high is None
                        or level >= self.protected_high["level"]):
                    self.protected_high = {
                        "level":         round(level, 4),
                        "timeframe":     tf,
                        "registered_at": ts,
                        "basis":         "buy_side_raid_rejected",
                    }
            elif sweep == "below_low" and st.get("last_swing_low") is not None:
                level = float(st["last_swing_low"])
                if (self.protected_low is None
                        or level <= self.protected_low["level"]):
                    self.protected_low = {
                        "level":         round(level, 4),
                        "timeframe":     tf,
                        "registered_at": ts,
                        "basis":         "sell_side_raid_rejected",
                    }

        # ── Violation: close beyond the level (with buffer) clears it ────────
        if price is not None:
            buf = price * _violation_buffer_pct()
            if (self.protected_high is not None
                    and price > self.protected_high["level"] + buf):
                self.protected_high = None
            if (self.protected_low is not None
                    and price < self.protected_low["level"] - buf):
                self.protected_low = None

        return self.state()

    def state(self, warnings: "list | None" = None) -> dict:
        return {
            "protected_high": dict(self.protected_high) if self.protected_high else None,
            "protected_low":  dict(self.protected_low) if self.protected_low else None,
            "warnings":       warnings or [],
        }
