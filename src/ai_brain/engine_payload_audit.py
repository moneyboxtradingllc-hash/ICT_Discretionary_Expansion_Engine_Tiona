"""Engine payload audit — which intelligence engines actually reach the Brain.

The failure this exists to prevent: reporting an engine as "active" because its
module imports. A module can be present, tested and completely unwired from the
live payload — the HTF wiring audit of 2026-07-30 found exactly that, with HTF
memory computed and fed to nothing.

So every engine here is judged ONLY by whether its data is present in the
`brain_input` that was actually built for a live scan, and whether that data
carries anything. Four verdicts, no softer ones available:

    PRESENT_AND_POPULATED   key exists and carries real content
    PRESENT_BUT_EMPTY       key exists and is null / {} / [] / all-null
    ABSENT_FROM_LIVE_PAYLOAD  key is not in the payload at all
    BLOCKED                 a gate is switched off, so it cannot attach

This module reads a payload. It never builds, fixes or fills one.
"""
from __future__ import annotations

import os

PRESENT_AND_POPULATED = "PRESENT_AND_POPULATED"
PRESENT_BUT_EMPTY = "PRESENT_BUT_EMPTY"
ABSENT = "ABSENT_FROM_LIVE_PAYLOAD"
BLOCKED = "BLOCKED"


def _populated(value) -> bool:
    """Content, not merely existence. A dict of all-None is empty."""
    if value is None:
        return False
    if isinstance(value, bool):
        return True
    if isinstance(value, (int, float)):
        return True
    if isinstance(value, str):
        return bool(value.strip())
    if isinstance(value, (list, tuple, set)):
        return any(_populated(v) for v in value)
    if isinstance(value, dict):
        return any(_populated(v) for v in value.values())
    return True


def _dig(payload: dict, path: str):
    """Fetch a dotted path. Returns (found, value)."""
    cur = payload
    for part in path.split("."):
        if not isinstance(cur, dict) or part not in cur:
            return False, None
        cur = cur[part]
    return True, cur


def _flag_on(name: str, default: str = "off") -> bool:
    return (os.getenv(name, default) or "").strip().lower() in ("1", "true", "yes", "on")


# engine -> (payload path, gate flag or None, gate default)
ENGINE_MAP = {
    "market_structure":        ("STRUCTURE_WITNESS", None, None),
    "liquidity":               ("liquidity", None, None),
    "po3":                     ("delivery.po3_15m", None, None),
    "volatility":              ("market.volatility_state", None, None),
    "session_state":           ("session", None, None),
    "volume_witness":          ("volume_witness", "VOLUME_WITNESS", "off"),
    "htf_memory":              ("htf_memory", None, None),
    "adaptive_context":        ("adaptive_learning_context", None, None),
    "adaptive_friction":       ("adaptive_friction_report", None, None),
    "vector_retrieval_analogs": ("memory_retrieval", None, None),
    "playbook_families":       ("playbook_toolbox", None, None),
    "tool_families":           ("playbook_toolbox", None, None),
    "thesis_lifecycle":        ("stance_history", None, None),
    "protected_levels":        ("protected_swings", None, None),
    "delivery_state":          ("delivery.state", None, None),
    "news_context":            ("news_context", "NEWS_LAYER_ENABLED", "off"),
}


def audit_payload(brain_input: dict, engine_map: dict = None) -> dict:
    """Classify every engine against one real live payload."""
    engine_map = engine_map or ENGINE_MAP
    results = {}
    for engine, (path, flag, flag_default) in engine_map.items():
        found, value = _dig(brain_input or {}, path)
        if not found:
            # A gate that is off explains the absence; say so rather than
            # reporting a wiring defect that is really a configuration choice.
            if flag and not _flag_on(flag, flag_default):
                results[engine] = {"status": BLOCKED, "path": path,
                                   "reason": f"{flag} is off"}
            else:
                results[engine] = {"status": ABSENT, "path": path}
            continue
        results[engine] = {
            "status": PRESENT_AND_POPULATED if _populated(value) else PRESENT_BUT_EMPTY,
            "path": path,
        }
    return results


def summarize(results: dict) -> dict:
    counts = {}
    for r in results.values():
        counts[r["status"]] = counts.get(r["status"], 0) + 1
    return {
        "counts": counts,
        "populated": sorted(k for k, v in results.items() if v["status"] == PRESENT_AND_POPULATED),
        "empty": sorted(k for k, v in results.items() if v["status"] == PRESENT_BUT_EMPTY),
        "absent": sorted(k for k, v in results.items() if v["status"] == ABSENT),
        "blocked": sorted(k for k, v in results.items() if v["status"] == BLOCKED),
    }


def thesis_provenance(brain_result: dict) -> dict:
    """Where the returned thesis actually came from.

    A deterministic fallback can look like a healthy thesis. This reports the
    source explicitly so a fallback can never be counted as sovereign.
    """
    r = brain_result or {}
    fallback = r.get("fallback_reason")
    return {"model": r.get("model"),
            "ok": bool(r.get("ok")),
            "fallback_reason": str(fallback)[:200] if fallback else None,
            "is_live_llm": bool(r.get("ok")) and not fallback,
            "is_sovereign": bool(r.get("ok")) and not fallback}
