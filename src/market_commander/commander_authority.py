"""
MARKET-COMMANDER AUTHORITY (MC-ENFORCE, 2026-07-09).

Turns Market Commander from an OBSERVE_ONLY witness into the FINAL environment /
regime / opportunity authority during paper validation — WITHOUT touching any
safety authority (FC-0B, risk, sizing, stops, broker, max-trades, daily-loss).

The Market Commander matrix (market_commander.py) stays internally observe_only
and deterministic — this is a thin AUTHORITY ADAPTER on top of it. It:

  1. Derives the commander_* authority fields from the L1/L2 verdict.
  2. Splits the council into SAFETY-class (may still veto) and ADVISORY-class
     (demoted to would_have_vetoed when Commander enforces). This closes the
     indirect channel by which mechanical REGIME / OPPORTUNITY / TOOLBOX / etc.
     council votes could still veto the gate after the mechanical regime itself
     was demoted (REGIME-DEMOTE).

Authority classes (mission doctrine):
  Class A — SAFETY (always enforce): FC-0B, risk, sizing, stops, broker,
            max-trades, daily-loss, reconciliation, position monitor. On the
            council, only RISK is a safety voice.
  Class B — ADVISORY (observe unless Commander delegates): mechanical regime,
            volatility, council REGIME/OPPORTUNITY/DELIVERY/QUALIFICATION/TOOLBOX
            environment votes, narrative environment warnings, memory/meta/etc.

Default MARKET_COMMANDER_AUTHORITY_MODE=observe_only → bit-for-bit legacy.
Launcher opts into enforce. Never raises.
"""
import os

from market_commander.market_commander import build_market_commander_matrix

# Council voices that may STILL veto after Commander approves (safety-class).
SAFETY_COUNCIL_MEMBERS = frozenset({"RISK"})
# Council voices demoted to would_have_vetoed when Commander enforces (advisory).
ADVISORY_COUNCIL_MEMBERS = frozenset(
    {"REGIME", "DELIVERY", "OPPORTUNITY", "QUALIFICATION", "TOOLBOX"}
)

_PERMISSION = {
    "PARTICIPATE": "PARTICIPATE",
    "OBSERVE":     "ALLOW_ADVISORY",
    "STAND_DOWN":  "BLOCK",
}


def commander_authority_mode() -> str:
    """Return 'enforce' or 'observe_only' (default)."""
    mode = os.getenv("MARKET_COMMANDER_AUTHORITY_MODE", "observe_only").lower().strip()
    return "enforce" if mode == "enforce" else "observe_only"


def commander_enforces() -> bool:
    """True when Market Commander owns final environment authority."""
    return commander_authority_mode() == "enforce"


def _mc_matrix(snapshot: dict) -> dict:
    mc = (snapshot or {}).get("market_commander")
    if isinstance(mc, dict) and mc.get("environment"):
        return mc
    try:
        return build_market_commander_matrix(snapshot or {})
    except Exception:  # noqa: BLE001
        return {}


def build_commander_authority(snapshot: dict) -> dict:
    """Derive the commander_* authority fields from the MC matrix. Never raises.

    commander_blocks_trade is True ONLY for a STAND_DOWN participation verdict —
    i.e. a HOSTILE (news chaos / liquidity vacuum) or INERT (confirmed dead
    market) guardian environment. DIRECTIONAL/ROTATIONAL/etc. never hard-block:
    Commander allows the pipeline to proceed to the real trigger/risk authorities
    (paper-validation doctrine — let valid theses through for outcome evidence)."""
    try:
        mode = commander_authority_mode()
        mc = _mc_matrix(snapshot)
        env = mc.get("environment") or {}
        part = mc.get("participation") or {}
        decision = str(part.get("decision") or "OBSERVE").upper()
        fam = env.get("family") or "UNKNOWN"
        typ = env.get("type") or "UNKNOWN"
        conf = int(env.get("confidence") or 0)
        conflict = int(env.get("conflict_index") or 0)
        override_status = env.get("commander_vs_regime_status") or ""
        override_active = (override_status == "COGNITIVE_OVERRIDE_ACTIVE")
        blocks = (decision == "STAND_DOWN")
        return {
            "commander_authority_mode":       mode,
            "commander_final_environment":    f"{fam}/{typ}",
            "commander_final_bias":           str(fam).lower(),
            "commander_final_permission":     _PERMISSION.get(decision, "ALLOW_ADVISORY"),
            "commander_confidence":           conf,
            "commander_conflict_score":       conflict,
            "commander_override_active":      bool(override_active),
            "commander_override_reason":      env.get("disagreement_reason") or override_status or None,
            "commander_blocks_trade":         bool(blocks),
            "commander_allows_trade":         (not blocks),
            "commander_participation_decision": decision,
            "commander_final_state":          mc.get("final_state"),
            "commander_source":               mc.get("source"),
        }
    except Exception as exc:  # noqa: BLE001
        # Fail-open to advisory: never let the adapter block a trade.
        return {
            "commander_authority_mode":  commander_authority_mode(),
            "commander_final_environment": "UNKNOWN/UNKNOWN",
            "commander_final_bias":      "unknown",
            "commander_final_permission": "ALLOW_ADVISORY",
            "commander_confidence":      0,
            "commander_conflict_score":  0,
            "commander_override_active": False,
            "commander_override_reason": f"commander_authority_error:{type(exc).__name__}",
            "commander_blocks_trade":    False,
            "commander_allows_trade":    True,
            "commander_participation_decision": "OBSERVE",
            "commander_final_state":     None,
            "commander_source":          None,
        }


def review_council_authority(council: dict, enforce: bool) -> dict:
    """Split the council veto into safety-class vs advisory-class.

    When enforce=True, ONLY safety-class (RISK) members may contribute to a
    blocking veto; advisory-class NO votes are recorded as would_have_vetoed but
    do not block. When enforce=False, legacy: the full veto stands. Never raises.
    """
    try:
        veto = (council or {}).get("veto") or {}
        full_triggered = bool(veto.get("veto_triggered"))
        strong_no = list(veto.get("strong_no_votes") or [])
        min_no = int(veto.get("min_no_votes", 2) or 2)

        advisory_no = [m for m in strong_no
                       if str(m.get("member", "")).upper() in ADVISORY_COUNCIL_MEMBERS]
        safety_no = [m for m in strong_no
                     if str(m.get("member", "")).upper() in SAFETY_COUNCIL_MEMBERS]

        if not enforce:
            effective = full_triggered
            demoted = False
        else:
            # Only safety-class members may block; advisory dissent is demoted.
            effective = len(safety_no) >= min_no
            demoted = full_triggered and not effective

        return {
            "council_authority_mode":    "enforce" if enforce else "observe_only",
            "council_veto_effective":    effective,
            "council_would_have_vetoed": full_triggered,
            "council_veto_reason":       veto.get("veto_reason") or None,
            "advisory_dissent":          advisory_no,
            "safety_dissent":            safety_no,
            "advisory_veto_demoted":     demoted,
            "council_role": ("safety_veto_only" if enforce else "enforce_full"),
        }
    except Exception as exc:  # noqa: BLE001
        return {
            "council_authority_mode":    "observe_only",
            "council_veto_effective":    False,
            "council_would_have_vetoed": False,
            "council_veto_reason":       f"council_review_error:{type(exc).__name__}",
            "advisory_dissent":          [],
            "safety_dissent":            [],
            "advisory_veto_demoted":     False,
            "council_role":              "enforce_full",
        }
