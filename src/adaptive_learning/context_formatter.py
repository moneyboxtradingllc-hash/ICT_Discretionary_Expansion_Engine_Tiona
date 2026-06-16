"""
Adaptive Learning — Phase 1C: Context formatter + telemetry (OBSERVE_ONLY).

Turns a LearningSignal into a Brain-payload context block and a scan-telemetry
block. The authority is HARD-LOCKED here:

  * the formatted context always reports  authority_level = "observe_only"
  * telemetry always reports               adaptive_confidence_adjustment = 0
  * final_confidence ALWAYS equals base_confidence

The underlying signal is computed at an ADVISORY authority so the RECOMMENDATION
(`confidence_adjustment_recommendation`) is the genuine value the system would
suggest at a higher authority — but it is NEVER applied this phase. This lets the
Brain SEE the scar without the scar touching the steering wheel.

Never raises.
"""
from adaptive_learning.learning_signal import build_learning_signal, LearningSignal

# The signal is COMPUTED at advisory so the recommendation is non-trivial; the
# authority that is EXPOSED / APPLIED downstream is hard-locked to observe_only.
RECOMMENDATION_AUTHORITY = "advisory"
APPLIED_AUTHORITY = "observe_only"


def format_adaptive_learning_context(signal: LearningSignal) -> dict:
    """Brain-payload context block. authority_level hard-locked to observe_only."""
    try:
        return {
            "sample_size": signal.sample_size,
            "win_rate": float(f"{signal.win_rate * 100:.1f}"),
            "avg_r": float(f"{signal.avg_r:.2f}"),
            "mae_risk": None if signal.mae_risk is None else float(f"{signal.mae_risk:.2f}"),
            "warning_tags": list(signal.warning_tags),
            "supporting_evidence": list(signal.supporting_evidence),
            "conflicting_evidence": list(signal.conflicting_evidence),
            "confidence_adjustment_recommendation": signal.confidence_adjustment,
            "authority_level": APPLIED_AUTHORITY,          # HARD-LOCK
            "explanation": signal.reason,
        }
    except Exception as exc:  # noqa: BLE001
        return neutral_adaptive_context(reason=f"format_error:{type(exc).__name__}")


def neutral_adaptive_context(reason: str = "no adaptive learning signal") -> dict:
    """Safe neutral context when no analogs / no signal exist."""
    return {
        "sample_size": 0,
        "win_rate": 0.0,
        "avg_r": 0.0,
        "mae_risk": None,
        "warning_tags": ["no_adaptive_learning_signal"],
        "supporting_evidence": [],
        "conflicting_evidence": [],
        "confidence_adjustment_recommendation": 0,
        "authority_level": APPLIED_AUTHORITY,              # HARD-LOCK
        "explanation": reason,
    }


def build_adaptive_telemetry(base_confidence, signal: "LearningSignal | None",
                             friction=None, interpretation=None, output=None) -> dict:
    """Scan-telemetry block separating the RECOMMENDED adjustment from the APPLIED
    (always 0). final_confidence ALWAYS equals base_confidence. ADAPTIVE-2A/2B:
    also records friction + interpretation + rebuttal status (observe-only)."""
    base = _to_int(base_confidence)
    recommended = signal.confidence_adjustment if signal is not None else 0
    tel = {
        "base_confidence": base,
        "adaptive_recommended_adjustment": recommended,
        "adaptive_confidence_adjustment": 0,               # HARD-LOCK — never applied
        "final_confidence": base,                          # unchanged, by construction
        "adaptive_authority_level": APPLIED_AUTHORITY,
        "similar_sample_size": signal.sample_size if signal is not None else 0,
        "adaptive_warnings": (list(signal.warning_tags) if signal is not None
                              else ["no_adaptive_learning_signal"]),
        "adaptive_reason": signal.reason if signal is not None else "no adaptive learning signal",
    }
    tel.update(_friction_telemetry(friction, interpretation, output))
    return tel


def _friction_telemetry(friction, interpretation, output) -> dict:
    """ADAPTIVE-2A/2B telemetry: objection + interpretation + rebuttal presence."""
    interp = interpretation or {}
    required = bool(getattr(friction, "required_rebuttal", False)) if friction else False
    present, resolution = _rebuttal_status(required, output or {})
    return {
        "friction_level": getattr(friction, "friction_level", 0) if friction else 0,
        "friction_label": getattr(friction, "friction_label", "none") if friction else "none",
        "historical_objection": getattr(friction, "historical_objection", "") if friction else "",
        "required_rebuttal": required,
        "brain_rebuttal_present": present,
        "disagreement_resolution": resolution,
        "interpretation_bias": interp.get("interpretation_bias", "insufficient_history"),
        "confidence_posture": interp.get("confidence_posture", "stable"),
        "fragility_flags": interp.get("fragility_flags", []),
    }


_REBUTTAL_KEYWORDS = ("history", "historical", "objection", "analog", "scar",
                      "prior", "previously", "failed before", "friction")


def _rebuttal_status(required: bool, output: dict):
    """Heuristic (observe-only): did the Brain answer the objection? Detects whether
    the narrative reasoning references history/objection when a rebuttal was
    required. Never affects behavior."""
    if not required:
        return False, "n/a"
    text = " ".join(str(output.get(k, "")) for k in
                    ("dominant_reasoning", "market_story", "reason")).lower()
    present = any(k in text for k in _REBUTTAL_KEYWORDS)
    return present, ("rebuttal_present" if present else "rebuttal_missing")


def inject_friction_and_interpretation(brain_input: dict, signal, snapshot: dict = None):
    """Build the friction report + interpretation context from the (advisory)
    LearningSignal and attach BOTH to the Brain payload. Visibility only — sets
    brain_input["adaptive_friction_report"] and ["adaptive_interpretation_context"].
    Returns (friction_report, interpretation_dict). Never raises."""
    try:
        from adaptive_learning.friction_engine import build_friction_report, friction_to_dict
        from adaptive_learning.interpretation_engine import build_adaptive_interpretation
        friction = build_friction_report(signal, snapshot or {})
        interp = build_adaptive_interpretation(signal, friction, snapshot or {})
        brain_input["adaptive_friction_report"] = friction_to_dict(friction)
        brain_input["adaptive_interpretation_context"] = interp
        return friction, interp
    except Exception:  # noqa: BLE001
        return None, {}


def inject_adaptive_context(brain_input: dict, analogs, snapshot: dict = None):
    """
    Build the (advisory) LearningSignal from analogs, attach its OBSERVE_ONLY
    context to the Brain payload, and return the signal (or None when no analogs).

    Visibility only — sets brain_input["adaptive_learning_context"]. Never raises
    and never mutates anything else.
    """
    try:
        if not analogs:
            brain_input["adaptive_learning_context"] = neutral_adaptive_context()
            return None
        signal = build_learning_signal(
            analogs, snapshot or {}, authority_level=RECOMMENDATION_AUTHORITY)
        brain_input["adaptive_learning_context"] = format_adaptive_learning_context(signal)
        return signal
    except Exception:  # noqa: BLE001
        brain_input["adaptive_learning_context"] = neutral_adaptive_context(
            reason="inject_error")
        return None


def _to_int(v):
    try:
        return int(v) if v is not None else 0
    except (TypeError, ValueError):
        return 0
