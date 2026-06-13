"""
Phase AB-1 — Brain stance memory (ends the amnesia).

The old wrapper had zero memory of its own prior output: the 10:15 bearish
read on June 11 had vanished by 10:28. This is a cross-scan ring buffer of
the brain's own stances, supplied back into the next scan's input so the
brain can answer "what did I say last scan / when the thesis began / what
changed". RAM-resident (like SetupTracker / ProtectedSwingTracker); a later
AB phase persists it across restarts.
"""


class StanceMemory:
    def __init__(self, max_len: int = 30):
        self._buf: list = []
        self._max = max_len
        self._thesis_anchor = None   # stance at the start of the current direction run

    def record(self, ts: str, stance: dict) -> None:
        try:
            entry = {
                "timestamp":  ts,
                "direction":  stance.get("narrative_direction", "neutral"),
                "phase":      stance.get("narrative_phase", "transition"),
                "confidence": stance.get("phase_confidence", 0),
                "action":     stance.get("current_action", "stand_down"),
            }
            prev_dir = self._buf[-1]["direction"] if self._buf else None
            if entry["direction"] != prev_dir:
                self._thesis_anchor = dict(entry)   # new directional thesis began
            self._buf.append(entry)
            if len(self._buf) > self._max:
                self._buf.pop(0)
        except Exception:  # noqa: BLE001
            pass

    def recent(self, n: int = 5) -> list:
        return list(self._buf[-n:])

    def history_summary(self) -> dict:
        """The block injected into the next brain input. Never raises."""
        try:
            if not self._buf:
                return {"available": False, "last": None, "prior_5": [],
                        "thesis_anchor": None, "changed_since_last": None}
            last = self._buf[-1]
            prev = self._buf[-2] if len(self._buf) >= 2 else None
            changed = None
            if prev:
                changed = {
                    "direction": prev["direction"] != last["direction"],
                    "phase":     prev["phase"] != last["phase"],
                    "from": {"direction": prev["direction"], "phase": prev["phase"]},
                    "to":   {"direction": last["direction"], "phase": last["phase"]},
                }
            return {
                "available":          True,
                "last":               last,
                "prior_5":            self.recent(5),
                "thesis_anchor":      self._thesis_anchor,
                "changed_since_last": changed,
            }
        except Exception:  # noqa: BLE001
            return {"available": False, "last": None, "prior_5": [],
                    "thesis_anchor": None, "changed_since_last": None}
