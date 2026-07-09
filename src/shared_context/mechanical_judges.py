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
