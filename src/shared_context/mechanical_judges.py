"""
MECHANICAL-JUDGES mode (JUDGE-FREEZE, 2026-07-09).

The mechanical layer historically carried its own JUDGMENTS — a confidence tier,
a regime opinion, council votes — in parallel with the AI Brain / Market Commander.
Mission by mission those were demoted at the execution gate (REGIME-DEMOTE,
MC-ENFORCE, AI-AUTH-2), but the mechanical confidence_tier still influenced
decisions off the gate: it could disqualify in qualification, hard-block in risk,
and boost playbook scores — a second opinion competing with the Brain.

MECHANICAL_JUDGES_MODE=telemetry_only freezes those judges to observation:
  MAY   — measure, warn, log, record would_have_blocked / would_have_vetoed,
          feed post-trade analysis / calibration / learning.
  MAY NOT — block execution, alter qualification / decision / trigger / trade
          intent / broker intent, or override the Brain / Market Commander.

This governs ONLY judgment influence. SAFETY systems are untouched: risk ceilings,
sizing, daily-loss, max-trades, stops, FC-0B, broker, and the regime risk-multiplier
CAP (which can only REDUCE size, never force or enlarge a trade) all remain live.

Default "active" = bit-for-bit legacy. The FC launcher sets "telemetry_only".
Never raises.
"""
import os


def mechanical_judges_mode() -> str:
    mode = os.getenv("MECHANICAL_JUDGES_MODE", "active").lower().strip()
    return "telemetry_only" if mode == "telemetry_only" else "active"


def judges_telemetry_only() -> bool:
    """True when mechanical judges may observe but not influence decisions."""
    return mechanical_judges_mode() == "telemetry_only"


def mechanical_context_witness(snapshot: dict) -> bool:
    """AI_CONTEXT-AUTHORITY (2026-07-09) — True when the MECHANICALLY-authored
    ai_context fields (market_narrative / market_state / directional_bias) must be
    demoted to witness-only. That is the case only when the judges are frozen AND
    the AI Brain holds a SOVEREIGN directional conversion — so a degraded/absent
    Brain still keeps the mechanical narrative as a live safety net. Never raises."""
    if not judges_telemetry_only():
        return False
    try:
        from ai_brain.ecu import sovereign_conversion
        return bool(sovereign_conversion(snapshot or {})[0])
    except Exception:  # noqa: BLE001
        return False
