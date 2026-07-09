"""
EXPANSION-STABILITY — per-timeframe expansion-state hysteresis (PERCEPTION-1).

The 2026-07-08 perception assassination proved the 5m expansion classifier is
the primary oscillation source feeding the narrative engine: its `state`
(early/mature/exhaustion_risk) transitioned 29× with 11 one-scan reversals, and
the exhaustion LEVEL flipped 51× with 21 one-scan reversals (avg persistence 3.1
scans) — while the 15m expansion was stable (2 transitions). `_exhaustion_risk`
reads a 3-candle rolling window against HARD thresholds with no hysteresis, so
the state flips as the window rolls across the boundary; 38 of 48 exhaustion_risk
narratives were driven by this flickering 5m signal overriding the stable 15m.

This is the VECTOR-3 analogue for expansion (mirrors Po3StabilityManager): a
symmetric debounce so a raw expansion `state` change must PERSIST for a
confirmation window before it is accepted — killing one-scan flicker without
changing the underlying detector. It only stabilizes the `state` field (the one
rule 2 consumes); scores and all other fields pass through untouched.

Gated by EXPANSION_STABILITY_MODE (default "off" = bit-for-bit legacy; the FC
launcher sets "on"). Rollback = set it to "off". Never raises.
"""
import os

_DEFAULT_CONFIRM = 2   # a new state must appear this many consecutive scans


def stability_enabled() -> bool:
    return os.getenv("EXPANSION_STABILITY_MODE", "off").lower().strip() == "on"


def _confirm_window() -> int:
    try:
        return max(1, int(os.getenv("EXPANSION_STABILITY_CONFIRM", str(_DEFAULT_CONFIRM))))
    except ValueError:
        return _DEFAULT_CONFIRM


class ExpansionStabilityManager:
    """Debounces the per-TF expansion `state` across consecutive scans.
    Instantiate once before the scan loop; call update() each iteration."""

    def __init__(self):
        # per-tf: {"confirmed": str, "pending": str, "pending_count": int}
        self._state: dict = {}

    def update(self, expansion: dict) -> dict:
        """Return the expansion dict with a hysteresis-stabilized `state` per TF.
        When disabled, returns the input unchanged. Never raises."""
        if not stability_enabled() or not isinstance(expansion, dict):
            return expansion
        win = _confirm_window()
        out = {}
        for tf, block in expansion.items():
            if not isinstance(block, dict) or "state" not in block or tf == "alignment":
                out[tf] = block
                continue
            try:
                out[tf] = self._debounce(tf, block, win)
            except Exception:  # noqa: BLE001 — never let stabilization break the pipeline
                out[tf] = block
        return out

    def _debounce(self, tf: str, block: dict, win: int) -> dict:
        raw = block.get("state")
        st = self._state.get(tf)
        if st is None or raw in (None, "unknown"):
            # first sighting (or no data) — accept immediately, no confirmation
            self._state[tf] = {"confirmed": raw, "pending": raw, "pending_count": 0}
            return block

        confirmed = st["confirmed"]
        if raw == confirmed:
            st["pending"], st["pending_count"] = raw, 0
            return block   # unchanged; already the stable state

        # raw differs from the confirmed state → require persistence
        if raw == st["pending"]:
            st["pending_count"] += 1
        else:
            st["pending"], st["pending_count"] = raw, 1

        if st["pending_count"] >= win:
            st["confirmed"] = raw          # change confirmed; accept it
            st["pending_count"] = 0
            return block

        # not yet confirmed — hold the previous stable state (kill the flicker)
        held = dict(block)
        held["state"] = confirmed
        held["expansion_stability"] = {
            "raw_state": raw, "held_state": confirmed,
            "pending_count": st["pending_count"], "confirm_window": win,
        }
        return held
