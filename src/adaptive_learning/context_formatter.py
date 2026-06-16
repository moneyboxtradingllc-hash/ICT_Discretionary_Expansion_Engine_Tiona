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


def build_adaptive_telemetry(base_confidence, signal: "LearningSignal | None") -> dict:
    """Scan-telemetry block separating the RECOMMENDED adjustment from the APPLIED
    (always 0). final_confidence ALWAYS equals base_confidence."""
    base = _to_int(base_confidence)
    recommended = signal.confidence_adjustment if signal is not None else 0
    return {
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
