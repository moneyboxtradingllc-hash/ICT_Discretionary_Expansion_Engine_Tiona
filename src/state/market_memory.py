"""
Market Memory — persists recent snapshots and tracks state transitions over time.

Responsibilities:
  - Store up to max_snapshots completed snapshots.
  - Apply PO3 phase stability filter to eliminate short-lived flickers.
  - Expose historical modifiers (confidence trend, tier changes, flickering TFs)
    that the narrative and confidence engines consume BEFORE the new snapshot is built.
  - After the snapshot is built, store it and return a full memory context dict
    that goes directly into snapshot["memory"].
"""

TIMEFRAMES          = ["15m", "5m", "3m", "1m"]
STABILITY_THRESHOLD = 65    # min phase_confidence to accept a new stable phase
TREND_THRESHOLD     = 2     # min score delta to call a trend rising/falling
FLICKER_WINDOW      = 5     # how many recent stable phases to inspect
FLICKER_MIN_CHANGES = 3     # changes within FLICKER_WINDOW that constitute flickering
TIER_ORDER          = ["no_trade", "observe", "valid_setup", "elite_setup"]

_NO_MEMORY = {"available": False, "snapshot_count": 0, "global": None, "timeframes": None}


class MarketMemory:
    def __init__(self, max_snapshots: int = 20):
        self._history: list = []
        self._max = max_snapshots
        # Per-TF stability tracking: phase, count, recent phase log
        self._stable: dict = {
            tf: {"phase": None, "count": 0, "log": []} for tf in TIMEFRAMES
        }

    # ── Public API ────────────────────────────────────────────────────────────

    def get_modifiers(self) -> dict:
        """
        Returns historical signals the AI engines use during the BUILD of a new snapshot.
        Called BEFORE push_and_get_context; reflects only completed prior snapshots.
        """
        if not self._history:
            return {
                "confidence_trend": "stable",
                "flickering_tfs":   [],
                "tier_improved":    False,
                "tier_degraded":    False,
                "stable_phases":    {tf: {"phase": None, "count": 0} for tf in TIMEFRAMES},
            }

        tier_improved, tier_degraded = self._tier_change()
        return {
            "confidence_trend": self._conf_trend(),
            "flickering_tfs":   [tf for tf in TIMEFRAMES if self._is_flickering(tf)],
            "tier_improved":    tier_improved,
            "tier_degraded":    tier_degraded,
            "stable_phases": {
                tf: {"phase": self._stable[tf]["phase"], "count": self._stable[tf]["count"]}
                for tf in TIMEFRAMES
            },
        }

    def push_and_get_context(self, snapshot: dict) -> dict:
        """
        Atomically:
          1. Computes the new stable phases for this snapshot's PO3 data.
          2. Builds the memory context dict (delta vs. last stored snapshot).
          3. Commits stable-phase state and appends snapshot to history.
          4. Returns the context dict to embed in snapshot["memory"].
        """
        new_stable = {
            tf: self._resolve_stable(
                tf,
                snapshot.get("po3", {}).get(tf, {}).get("phase", "no_phase"),
                snapshot.get("po3", {}).get(tf, {}).get("phase_confidence", 0),
            )
            for tf in TIMEFRAMES
        }

        context = self._build_context(snapshot, new_stable)

        # Commit
        for tf in TIMEFRAMES:
            phase, count = new_stable[tf]
            self._stable[tf]["phase"] = phase
            self._stable[tf]["count"] = count
            self._stable[tf]["log"].append(phase)
            if len(self._stable[tf]["log"]) > 10:
                self._stable[tf]["log"].pop(0)

        self._history.append(snapshot)
        if len(self._history) > self._max:
            self._history.pop(0)

        return context

    # ── Stable Phase Resolution ───────────────────────────────────────────────

    def _resolve_stable(self, tf: str, new_phase: str, new_conf: int) -> tuple:
        prev  = self._stable[tf]["phase"]
        count = self._stable[tf]["count"]

        if new_conf >= STABILITY_THRESHOLD:
            # High confidence — accept unconditionally
            return new_phase, (count + 1 if new_phase == prev else 1)

        # Low confidence — hold previous stable phase if one exists
        if prev is not None:
            return prev, count + 1

        return new_phase, 1  # no prior history — accept regardless

    # ── Context Building ──────────────────────────────────────────────────────

    def _build_context(self, curr: dict, new_stable: dict) -> dict:
        if not self._history:
            return _NO_MEMORY.copy()

        prev = self._history[-1]
        return {
            "available":      True,
            "snapshot_count": len(self._history),
            "global":         self._global_delta(prev, curr),
            "timeframes":     self._tf_deltas(prev, curr, new_stable),
        }

    def _global_delta(self, prev: dict, curr: dict) -> dict:
        p_ai = prev.get("ai_context", {})
        c_ai = curr.get("ai_context", {})

        p_score = p_ai.get("confidence_score", 0)
        c_score = c_ai.get("confidence_score", 0)
        delta   = c_score - p_score

        if delta > TREND_THRESHOLD:
            trend = "rising"
        elif delta < -TREND_THRESHOLD:
            trend = "falling"
        else:
            trend = "stable"

        return {
            "previous_market_narrative": p_ai.get("market_narrative", "unknown"),
            "current_market_narrative":  c_ai.get("market_narrative",  "unknown"),
            "narrative_changed":         p_ai.get("market_narrative") != c_ai.get("market_narrative"),
            "previous_confidence_score": p_score,
            "current_confidence_score":  c_score,
            "confidence_delta":          delta,
            "confidence_trend":          trend,
            "previous_confidence_tier":  p_ai.get("confidence_tier", "unknown"),
            "current_confidence_tier":   c_ai.get("confidence_tier", "unknown"),
        }

    def _tf_deltas(self, prev: dict, curr: dict, new_stable: dict) -> dict:
        result = {}
        for tf in TIMEFRAMES:
            p_po3 = prev.get("po3",       {}).get(tf, {})
            c_po3 = curr.get("po3",        {}).get(tf, {})
            phase, count = new_stable[tf]

            result[tf] = {
                "previous_po3_phase":   p_po3.get("phase",  "no_phase"),
                "current_po3_phase":    c_po3.get("phase",  "no_phase"),
                "stable_po3_phase":     phase,
                "po3_phase_changed":    p_po3.get("phase") != c_po3.get("phase"),
                "po3_stability_count":  count,
                "structure_changed":    (prev.get("structure",  {}).get(tf, {}).get("state")
                                          != curr.get("structure",  {}).get(tf, {}).get("state")),
                "volatility_changed":   (prev.get("volatility", {}).get(tf, {}).get("state")
                                          != curr.get("volatility", {}).get(tf, {}).get("state")),
                "expansion_changed":    (prev.get("expansion",  {}).get(tf, {}).get("state")
                                          != curr.get("expansion",  {}).get(tf, {}).get("state")),
            }
        return result

    # ── Historical Helpers ────────────────────────────────────────────────────

    def _conf_trend(self) -> str:
        if len(self._history) < 2:
            return "stable"
        s1 = self._history[-2].get("ai_context", {}).get("confidence_score", 0)
        s2 = self._history[-1].get("ai_context", {}).get("confidence_score", 0)
        delta = s2 - s1
        if delta > TREND_THRESHOLD:
            return "rising"
        if delta < -TREND_THRESHOLD:
            return "falling"
        return "stable"

    def _is_flickering(self, tf: str) -> bool:
        log = self._stable[tf]["log"]
        if len(log) < 3:
            return False
        recent  = log[-FLICKER_WINDOW:]
        changes = sum(1 for i in range(1, len(recent)) if recent[i] != recent[i - 1])
        return changes >= FLICKER_MIN_CHANGES

    def _tier_change(self) -> tuple:
        if len(self._history) < 2:
            return False, False
        def idx(t): return TIER_ORDER.index(t) if t in TIER_ORDER else 0
        p_tier = self._history[-2].get("ai_context", {}).get("confidence_tier", "no_trade")
        c_tier = self._history[-1].get("ai_context", {}).get("confidence_tier", "no_trade")
        diff = idx(c_tier) - idx(p_tier)
        return diff > 0, diff < 0
