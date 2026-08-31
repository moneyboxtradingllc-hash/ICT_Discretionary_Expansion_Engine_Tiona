"""
REGIME-AUTHORITY-MODE — execution-blocking authority switch for the mechanical
regime (REGIME-DEMOTE, 2026-07-09).

Live scans (e.g. 20260709_094951) showed the mechanical regime still owning
FINAL execution authority: a range_rotation label imposed `required_trigger=
confirmed` + `min_setup_age=2` at the execution gate and hard-blocked an ELITE
LIQUIDITY_SWEEP_REVERSAL SHORT — while Market Commander (the environment
authority) was DIRECTIONAL / MATURE_EXPANSION and itself only OBSERVE.

This module owns ONE decision: may the mechanical regime HARD-BLOCK execution?
  - "enforce"      (default): legacy — regime permission / trigger / age gate the
                   execution gate exactly as before. Bit-for-bit unchanged.
  - "observe_only": regime still calculates, warns, records would_have_blocked
                   and veto_reason, and feeds Market Commander — but it may NOT
                   hard-block execution. Market Commander owns final environment
                   authority; while Commander is observe-only the enforcement
                   source is none.

It changes NOTHING about FC-0B, risk, sizing, stops, broker, council, narrative,
or the real trigger execution-ready check — only whether the mechanical regime's
own permission overlay is allowed to veto. Never raises.
"""
import os


def regime_authority_mode() -> str:
    """Return 'enforce' (default) or 'observe_only'."""
    # PROD-20260807 AUDIT: this variable was ABSENT from the production
    # environment and defaulted to "enforce", while the TopstepX production path
    # imports no regime veto at all. Latent ambiguity -- doctrine said context
    # only, configuration said enforce, and only an accident of imports made
    # them agree. The production default is now explicit.
    #
    # A BLANK value is "unset", not "enforce". `REGIME_AUTHORITY_MODE=` left
    # empty in .env previously fell through to enforcement and silently re-armed
    # a veto the doctrine says does not exist. Only an explicit word decides.
    mode = (os.getenv("REGIME_AUTHORITY_MODE") or "").lower().strip()
    if not mode:
        mode = "observe_only"
    return "observe_only" if mode == "observe_only" else "enforce"


def regime_enforces() -> bool:
    """True when the mechanical regime may hard-block execution."""
    return regime_authority_mode() == "enforce"
