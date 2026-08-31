"""
Phase AB-1 — Brain stance memory (ends the amnesia).

The old wrapper had zero memory of its own prior output: the 10:15 bearish
read on June 11 had vanished by 10:28. This is a cross-scan ring buffer of
the brain's own stances, supplied back into the next scan's input so the
brain can answer "what did I say last scan / when the thesis began / what
changed". AB-4: persisted across restart/replay/session to data/ai_brain/stance_memory.json,
so the brain answers "what was my prior stance?" without relying on the current
process. Never raises.
"""
import json
import os


def _stance_path() -> str:
    d = os.getenv("AI_BRAIN_DIR", os.path.join("data", "ai_brain"))
    return os.path.join(d, "stance_memory.json")


class StanceMemory:
    def __init__(self, max_len: int = 30, persist: bool = True):
        self._buf: list = []
        self._max = max_len
        self._thesis_anchor = None   # stance at the start of the current direction run
        self._persist = persist
        if persist:
            self._load()

    # ── AB-4 persistence ────────────────────────────────────────────────────
    def _load(self) -> None:
        try:
            path = _stance_path()
            if os.path.exists(path):
                data = json.load(open(path, encoding="utf-8"))
                self._buf = data.get("buf", [])[-self._max:]
                self._thesis_anchor = data.get("thesis_anchor")
        except Exception:  # noqa: BLE001
            self._buf, self._thesis_anchor = [], None

    def _save(self) -> None:
        if not self._persist:
            return
        try:
            path = _stance_path()
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "w", encoding="utf-8") as fh:
                json.dump({"buf": self._buf, "thesis_anchor": self._thesis_anchor},
                          fh, default=str)
        except Exception:  # noqa: BLE001
            pass

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
            self._save()
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
                # CONTINUITY-2B: prior stances may have been reasoned from a
                # tape that was later repaired. Terra is told, not steered.
                "history_revision":   self.superseded_summary(),
            }
        except Exception:  # noqa: BLE001
            return {"available": False, "last": None, "prior_5": [],
                    "thesis_anchor": None, "changed_since_last": None}

    # ── history revision (CONTINUITY-2B, 2026-08-11) ─────────────────────────
    #
    # A stance is a BELIEF Terra formed about a market it was shown. When the
    # canonical tape is retroactively repaired, every stance recorded before
    # that repair was reasoned from a world that no longer exists -- and this
    # buffer feeds straight back into the next prompt via `history_summary`.
    # Mechanical state can be re-derived; a belief cannot, so it is RE-ANCHORED
    # rather than replayed.
    #
    # The entries are NOT deleted. They are evidence of what Terra actually
    # thought, and destroying them would be the same error as erasing a
    # rejection. What is removed is their AUTHORITY: they are marked as formed
    # before a revision, and the summary says so, so Terra is told rather than
    # quietly steered by a superseded conviction.
    def supersede(self, revision: int, note: str = "") -> dict:
        """Mark every stance recorded so far as predating `revision`."""
        try:
            marked = 0
            for entry in self._buf:
                if entry.get("superseded_by_history_revision") is None:
                    entry["superseded_by_history_revision"] = int(revision)
                    marked += 1
            if self._thesis_anchor is not None:
                self._thesis_anchor["superseded_by_history_revision"] = int(revision)
            self._history_revision = int(revision)
            self._supersede_note = str(note or "")
            self._save()
            return {"marked": marked, "revision": int(revision)}
        except Exception:  # noqa: BLE001 — memory may never cost a scan
            return {"marked": 0, "revision": revision, "error": True}

    def superseded_summary(self) -> dict:
        """What the next prompt should be told about its own history."""
        revision = getattr(self, "_history_revision", None)
        stale = [e for e in self._buf
                 if e.get("superseded_by_history_revision") is not None]
        return {
            "history_revision": revision,
            "stances_formed_before_a_repair": len(stale),
            "note": (getattr(self, "_supersede_note", "")
                     or ("market history was repaired after these stances were "
                         "formed; they described a tape that has since changed"
                         if stale else "")),
        }
