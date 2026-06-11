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
from paper_execution.trade_journal import update_trade_management

_VALID_PROFILES = ("defensive", "range", "trend")

# profile -> policy params. None = env default (pre-5T behavior).
#   breakeven_trigger_r:   R at which stop moves to entry
#   take_profit_r:         R at which profit is taken
#   take_profit_fraction:  1.0 = full exit; <1.0 = partial (5T.3, TREND)
#   trail_after_breakeven: structure trail gating
#   thesis_exit:           "off" | "shadow"  (live thesis exits require
#                          promoted evidence — Phase 5T.2+ governance)
POLICY_TABLE = {
    "defensive": {
        "breakeven_trigger_r":   None,
        "take_profit_r":         None,
        "take_profit_fraction":  None,
        "trail_after_breakeven": None,
        "thesis_exit":           "shadow",
    },
    "range": {
        "breakeven_trigger_r":   None,   # 5T.3: 0.75 (study 5T.0)
        "take_profit_r":         None,   # 5T.3: 1.25
        "take_profit_fraction":  None,
        "trail_after_breakeven": None,
        "thesis_exit":           "shadow",
    },
    "trend": {
        "breakeven_trigger_r":   None,   # 5T.3: 1.5
        "take_profit_r":         None,   # 5T.3: 2.0 with fraction 0.5
        "take_profit_fraction":  None,
        "trail_after_breakeven": None,
        "thesis_exit":           "shadow",
    },
}


def get_policy(profile: str) -> dict:
    """Policy params for a profile. Unknown profiles get defensive. Never raises."""
    p = (profile or "defensive").lower().strip()
    if p not in _VALID_PROFILES:
        p = "defensive"
    policy = dict(POLICY_TABLE[p])
    policy["profile"] = p
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
