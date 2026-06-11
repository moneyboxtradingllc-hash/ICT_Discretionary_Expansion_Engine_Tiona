"""
Phase 5T.1 — Management Policy Engine.

Trade management becomes profile-driven. The regime permission matrix has
published management_profile (trend/range/defensive) since 5F.2; this module
finally consumes it.

POLICY CONTRACT:
  - The profile is LOCKED at first management touch of a trade and persisted
    to the journal (no mid-trade profile flapping).
  - A policy value of None means "use the env-configured default" — the
    exact pre-5T behavior.
  - DEFENSIVE is all-None by constitution: it must reproduce current
    behavior bit-for-bit.
  - 5T.1 ships ALL profiles as all-None (zero behavior change at ship).
    5T.3 populates RANGE/TREND from the 5T.0 study, under counterfactual
    measurement. Parameters are governed objects (registry records P-001..3).

No execution coupling beyond trade_manager. Never raises.
"""
import os

from paper_execution.trade_journal import update_trade_management

_VALID_PROFILES = ("defensive", "range", "trend")

# profile -> policy params. None = env default (pre-5T behavior).
#   breakeven_trigger_r:   R at which stop moves to entry
#   take_profit_r:         R at which profit is taken
#   take_profit_fraction:  1.0/None = full exit; <1.0 = partial (TREND)
#   trail_after_breakeven: structure trail gating
#   thesis_exit:           "off" | "shadow"  (live thesis exits require
#                          promoted evidence — Phase 5T.2+ governance)
#
# RANGE/TREND values are from the 5T.0 MFE/MAE study (floor-estimate caveat
# applies; see data/rule_governance/reports/5T0_mfe_mae_study.md). They are
# governed objects (P-002/P-003) measured by the management action ledger.
POLICY_TABLE = {
    "defensive": {                       # P-001 — the grandfathered baseline
        "breakeven_trigger_r":   None,
        "take_profit_r":         None,
        "take_profit_fraction":  None,
        "trail_after_breakeven": None,
        "thesis_exit":           "shadow",
    },
    "range": {                           # P-002 — 5T.0 study
        "breakeven_trigger_r":   0.75,
        "take_profit_r":         1.25,
        "take_profit_fraction":  1.0,    # full exit at target
        "trail_after_breakeven": True,
        "thesis_exit":           "shadow",
    },
    "trend": {                           # P-003 — 5T.0 study
        "breakeven_trigger_r":   1.5,
        "take_profit_r":         2.0,
        "take_profit_fraction":  0.5,    # partial; remainder trails uncapped
        "trail_after_breakeven": True,
        "thesis_exit":           "shadow",
    },
}


def _adaptive_enabled() -> bool:
    return os.getenv("ADAPTIVE_MANAGEMENT_ENABLED", "true").lower().strip() == "true"


def get_policy(profile: str) -> dict:
    """
    Policy params for a profile. Unknown profiles get defensive.
    ADAPTIVE_MANAGEMENT_ENABLED=false forces defensive (kill switch back to
    exact pre-5T behavior). Never raises.
    """
    p = (profile or "defensive").lower().strip()
    if p not in _VALID_PROFILES or not _adaptive_enabled():
        p = "defensive"
    policy = dict(POLICY_TABLE[p])
    policy["profile"] = p
    policy["adaptive_enabled"] = _adaptive_enabled()
    return policy


def resolve_trade_profile(snapshot: dict, trade_record: dict, symbol: str) -> str:
    """
    Profile for this trade, locked at first management touch.

    1. If the journal record already carries management_profile -> use it.
    2. Otherwise read regime_permissions.management_profile from the CURRENT
       snapshot, persist it to the journal, and use it from then on.
    3. Anything missing/invalid -> defensive.

    Never raises.
    """
    try:
        existing = (trade_record.get("management_profile") or "").lower().strip()
        if existing in _VALID_PROFILES:
            return existing

        rp      = snapshot.get("regime_permissions", {}) or {}
        profile = (rp.get("management_profile") or "defensive").lower().strip()
        if profile not in _VALID_PROFILES:
            profile = "defensive"

        trade_id = trade_record.get("trade_id")
        if trade_id:
            update_trade_management(
                trade_id, {"management_profile": profile}, symbol,
            )
        return profile
    except Exception:  # noqa: BLE001
        return "defensive"
