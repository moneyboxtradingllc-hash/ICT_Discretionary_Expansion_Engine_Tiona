"""
REPLAY-2 — RecordedBrain: deterministic LLM replay (2026-07-09).

Every live Brain call is persisted by persist_brain_call (data/ai_brain/
YYYYMMDD_HHMMSS_SYMBOL.json: parsed_output, source, usage, ai_market_commander).
RecordedBrain serves those records back during replay so the pipeline sees the
EXACT narrative the LLM authored that day — deterministic, zero cost, zero
network. It substitutes ai_brain.narrative_brain.run_narrative_brain for the
duration of a run (ecu.produce_thesis resolves the name at call time from the
module namespace, so the ECU path is covered too).

Matching: nearest record by snapshot timestamp within tolerance (default 120s —
live scans ran ~60s apart). A scan with no record in tolerance gets an explicit
source="replay_no_record" empty output (direction neutral) and is COUNTED —
missing history is reported, never silently invented.
"""
import json
import os
from contextlib import contextmanager
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

_ET = ZoneInfo("America/New_York")
_DEFAULT_TOLERANCE_S = 120


def _brain_dir() -> str:
    return os.getenv("REPLAY_BRAIN_RECORDS_DIR") \
        or os.getenv("AI_BRAIN_DIR", os.path.join("data", "ai_brain"))


def _parse_ts(value) -> "datetime | None":
    try:
        ts = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return ts if ts.tzinfo else ts.replace(tzinfo=timezone.utc)
    except (ValueError, TypeError):
        return None


def load_brain_records(date: str, symbol: str = "QQQ",
                       records_dir: str = None) -> list:
    """[(ts_datetime, record)] for the session date, sorted by time."""
    d = records_dir or _brain_dir()
    out = []
    if not os.path.isdir(d):
        return out
    prefix = f"{date}_"
    for name in sorted(os.listdir(d)):
        if not (name.startswith(prefix) and name.endswith(f"_{symbol}.json")):
            continue
        try:
            with open(os.path.join(d, name), encoding="utf-8") as fh:
                rec = json.load(fh)
        except (json.JSONDecodeError, OSError):
            continue
        ts = _parse_ts(rec.get("timestamp"))
        # Guard: keep only records whose TIMESTAMP truly falls on the session's
        # ET date — filename-matching alone admits leaked test fixtures with
        # stale snapshot timestamps (found on 2026-07-08: a "0708" file whose
        # record timestamp was 2026-06-11).
        if ts is not None and ts.astimezone(_ET).strftime("%Y%m%d") == date:
            out.append((ts, rec))
    out.sort(key=lambda p: p[0])
    return out


def _result_from_record(rec: dict) -> dict:
    """Shape a persisted record like run_narrative_brain's public return."""
    return {
        "enabled": True,
        "authority": "observe_only",
        "source": rec.get("source"),
        "llm_enabled": rec.get("llm_enabled"),
        "llm_model": rec.get("llm_model"),
        "llm_usage": rec.get("llm_usage"),
        "fallback_reason": rec.get("fallback_reason"),
        "normalization_notes": rec.get("normalization_notes") or [],
        "repair_attempted": rec.get("repair_attempted", False),
        "family_repair_attempted": rec.get("family_repair_attempted", False),
        "family_repair_fixed": rec.get("family_repair_fixed", False),
        "input_degraded": rec.get("input_degraded") or [],
        "output": rec.get("parsed_output") or {},
        "adaptive_telemetry": rec.get("adaptive_telemetry"),
        "ai_market_commander": rec.get("ai_market_commander"),
        "persisted": None,
        "replayed_from_record": rec.get("timestamp"),
    }


def _empty_result(reason: str) -> dict:
    try:
        from ai_brain.brain_schema import empty_brain_output
        output = empty_brain_output()
    except Exception:  # noqa: BLE001
        output = {}
    output["warnings"] = [f"replay: {reason}"]
    return {"enabled": True, "authority": "observe_only", "source": reason,
            "llm_enabled": False, "llm_model": None, "llm_usage": None,
            "fallback_reason": reason, "normalization_notes": [],
            "repair_attempted": False, "family_repair_attempted": False,
            "family_repair_fixed": False, "input_degraded": [],
            "output": output, "adaptive_telemetry": None,
            "ai_market_commander": None, "persisted": None,
            "replayed_from_record": None}


class RecordedBrain:
    """Callable with run_narrative_brain's signature, serving persisted records.

    SEQUENTIAL consumption: scan ticks ARE the record timestamps, so record i
    belongs to scan i. Nearest-timestamp matching alone is WRONG when two live
    scans share an anchor minute (2026-07-08 14:03: two records, the second
    carrying the sovereign family) — it would serve the first record twice and
    silently drop the second. The cursor consumes each record exactly once, in
    order, within tolerance; nearest-match remains only as the fallback for
    out-of-sequence ticks."""

    def __init__(self, date: str, symbol: str = "QQQ", records_dir: str = None,
                 tolerance_s: int = _DEFAULT_TOLERANCE_S):
        self.records = load_brain_records(date, symbol, records_dir)
        self.tolerance_s = tolerance_s
        self.served = 0
        self.misses = 0
        self._cursor = 0

    def __call__(self, snapshot: dict, symbol: str, stance_memory=None) -> dict:
        ts = _parse_ts((snapshot or {}).get("timestamp"))
        if ts is None or not self.records:
            self.misses += 1
            return _empty_result("replay_no_record")
        # sequential: next unconsumed record whose ts matches within tolerance
        for i in range(self._cursor, len(self.records)):
            rts, rec = self.records[i]
            delta = (rts - ts).total_seconds()
            if abs(delta) <= self.tolerance_s:
                self._cursor = i + 1
                self.served += 1
                return _result_from_record(rec)
            if delta > self.tolerance_s:
                break   # records are sorted; nothing later can match
        # fallback: nearest anywhere (out-of-sequence tick) — cursor unchanged
        best = min(self.records, key=lambda p: abs((p[0] - ts).total_seconds()))
        if abs((best[0] - ts).total_seconds()) > self.tolerance_s:
            self.misses += 1
            return _empty_result("replay_no_record")
        self.served += 1
        return _result_from_record(best[1])


@contextmanager
def brain_replay(brain: "RecordedBrain"):
    """Substitute run_narrative_brain for the duration of a replay run.
    Restores the real function on exit no matter what."""
    import ai_brain.narrative_brain as nb
    original = nb.run_narrative_brain
    nb.run_narrative_brain = brain
    try:
        yield brain
    finally:
        nb.run_narrative_brain = original
