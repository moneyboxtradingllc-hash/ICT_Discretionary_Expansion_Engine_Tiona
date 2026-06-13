"""
Phase AB-1 — Narrative Brain output schema.

The old wrapper consumed 2 of 11 fields. This schema is machine-consumable by
design: every field has a defined type and a defined consumer (wired in later
phases). Validation rejects malformed model output so the brain falls back to
its deterministic synthesis rather than poisoning downstream state.

NONE of these fields are print-only. The console/journal/gate consumers are
defined in the AB phase plan; until a consumer is wired, a field is persisted
(audit) — not discarded.
"""

_DIRECTIONS = {"bullish", "bearish", "conflicted", "neutral"}
_PHASES = {"accumulation", "manipulation", "distribution", "reversal",
           "continuation", "exhaustion", "transition"}

_REQUIRED = {
    "market_story":              str,
    "narrative_direction":       str,   # in _DIRECTIONS
    "narrative_phase":           str,   # in _PHASES
    "phase_confidence":          int,   # 0-100
    "delivery_interpretation":   str,
    "liquidity_interpretation":  str,
    "protected_high_interpretation": str,
    "protected_low_interpretation":  str,
    "active_draw":               str,
    "allowed_direction":         str,   # in _DIRECTIONS ∪ {"any","none"}
    "forbidden_direction":       (str, type(None)),
    "preferred_trade_family":    str,
    "preferred_playbooks":       list,
    "preferred_tools":           list,
    "invalidation_level":        (int, float, type(None)),
    "thesis_health":             str,
    "contradiction_flags":       list,
    "warnings":                  list,
    "confidence_by_component":   dict,
    "memory_matches":            list,
    "current_action":            str,
    "reason":                    str,
    "must_not_do":               list,
}


def empty_brain_output() -> dict:
    """A safe, fully-typed default — used as the witness/degraded baseline."""
    return {
        "market_story":              "",
        "narrative_direction":       "neutral",
        "narrative_phase":           "transition",
        "phase_confidence":          0,
        "delivery_interpretation":   "",
        "liquidity_interpretation":  "",
        "protected_high_interpretation": "",
        "protected_low_interpretation":  "",
        "active_draw":               "",
        "allowed_direction":         "any",
        "forbidden_direction":       None,
        "preferred_trade_family":    "",
        "preferred_playbooks":       [],
        "preferred_tools":           [],
        "invalidation_level":        None,
        "thesis_health":             "n/a",
        "contradiction_flags":       [],
        "warnings":                  [],
        "confidence_by_component":   {},
        "memory_matches":            [],
        "current_action":            "stand_down",
        "reason":                    "",
        "must_not_do":               [],
    }


def validate_brain_output(resp: dict) -> tuple:
    """(is_valid, reason). Never raises."""
    try:
        if not isinstance(resp, dict):
            return False, "response is not a dict"
        for field, typ in _REQUIRED.items():
            if field not in resp:
                return False, f"missing field: {field}"
            if not isinstance(resp[field], typ):
                return False, f"{field} wrong type: {type(resp[field]).__name__}"
        if resp["narrative_direction"] not in _DIRECTIONS:
            return False, f"narrative_direction '{resp['narrative_direction']}' invalid"
        if resp["narrative_phase"] not in _PHASES:
            return False, f"narrative_phase '{resp['narrative_phase']}' invalid"
        if not (0 <= resp["phase_confidence"] <= 100):
            return False, "phase_confidence out of range"
        if resp["allowed_direction"] not in (_DIRECTIONS | {"any", "none"}):
            return False, f"allowed_direction '{resp['allowed_direction']}' invalid"
        return True, None
    except Exception as exc:  # noqa: BLE001
        return False, f"validation error: {exc}"
