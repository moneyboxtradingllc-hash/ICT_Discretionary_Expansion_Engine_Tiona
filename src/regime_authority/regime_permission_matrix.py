"""
Phase 5F.2 — Regime Permission Matrix.

Regime graduates from observe-only to CONSTRAINT authority.
It controls PERMISSIONS — never confidence scores:
  - allowed / forbidden playbooks for the current regime
  - risk multiplier cap        (applied in order_builder — Phase 5F.1)
  - required trigger status    (enforced in execution_gate — Phase 5F.3)
  - minimum setup age in scans (enforced in execution_gate — Phase 5F.5)
  - management profile         (trend / range / defensive)

INVARIANTS:
  - NEVER modifies confidence, qualification scores, or AI output.
  - NEVER raises — returns a safe restricted default on any error.
  - Reads snapshot["market_regime"] + snapshot["playbook"] only.
"""
import os

_CONTINUATION_PLAYBOOKS = frozenset({
    "trend_continuation",
    "opening_drive",
    "range_expansion",
    "manipulation_to_distribution",
})

_REVERSAL_PLAYBOOKS = frozenset({
    "liquidity_sweep_reversal",
    "failed_breakout_reversal",
})

_TREND_REGIMES = frozenset({
    "trend_up", "trend_down", "expansion_up", "expansion_down",
})

# Base profile per regime label:
#   (risk_multiplier_cap, required_trigger_status, min_setup_age_scans, management_profile)
_BASE_PROFILE = {
    "trend_up":         (1.00, "confirmation_needed", 1, "trend"),
    "trend_down":       (1.00, "confirmation_needed", 1, "trend"),
    "expansion_up":     (1.00, "confirmation_needed", 1, "trend"),
    "expansion_down":   (1.00, "confirmation_needed", 1, "trend"),
    "reversal_attempt": (0.50, "confirmed",           2, "defensive"),
    "range_rotation":   (0.50, "confirmed",           2, "range"),
    "chop":             (0.25, "confirmed",           3, "defensive"),
    "high_volatility":  (0.25, "confirmed",           2, "defensive"),
    "low_volatility":   (0.50, "confirmed",           2, "range"),
    "unknown":          (0.50, "confirmed",           2, "defensive"),
}

# Regimes where only reversal-family playbooks may trade at all
_REVERSAL_ONLY_REGIMES = frozenset({"range_rotation", "chop"})

# Volatility states that demand caution
_UNSTABLE_VOL = frozenset({"unstable"})
_SEVERE_VOL   = frozenset({"toxic", "explosive", "extreme", "high"})


def _enabled() -> bool:
    return os.getenv("REGIME_AUTHORITY_ENABLED", "true").lower().strip() == "true"


def _disabled_result(regime_label: str, vol_state: str, exp_state: str) -> dict:
    """Authority explicitly disabled by env — legacy (pre-5F) behavior."""
    return {
        "enabled":                 False,
        "regime_label":            regime_label,
        "volatility_state":        vol_state,
        "expansion_state":         exp_state,
        "allowed":                 True,
        "permission_status":       "allowed",
        "risk_multiplier_cap":     1.0,
        "required_trigger_status": "confirmation_needed",
        "management_profile":      "trend",
        "min_setup_age_scans":     0,
        "forbidden_playbooks":     [],
        "reasons":                 ["regime authority disabled by REGIME_AUTHORITY_ENABLED=false"],
        "blocking_reasons":        [],
    }


def _safe_default(error_reason: str) -> dict:
    """Error fallback — most restrictive non-blocking posture."""
    return {
        "enabled":                 True,
        "regime_label":            "unknown",
        "volatility_state":        "unknown",
        "expansion_state":         "unknown",
        "allowed":                 True,
        "permission_status":       "restricted",
        "risk_multiplier_cap":     0.5,
        "required_trigger_status": "confirmed",
        "management_profile":      "defensive",
        "min_setup_age_scans":     2,
        "forbidden_playbooks":     [],
        "reasons":                 [f"regime permission error — safe default applied: {error_reason}"],
        "blocking_reasons":        [],
    }


def evaluate_regime_permissions(snapshot: dict) -> dict:
    """
    Phase 5F.2 — evaluate regime constraint permissions for the current scan.
    Never raises.
    """
    try:
        return _evaluate(snapshot or {})
    except Exception as exc:  # noqa: BLE001
        return _safe_default(str(exc))


def _evaluate(snapshot: dict) -> dict:
    regime    = snapshot.get("market_regime", {}) or {}
    playbook  = snapshot.get("playbook", {}) or {}

    regime_label = (regime.get("regime_label")     or "unknown").lower()
    vol_state    = (regime.get("volatility_state") or "unknown").lower()
    exp_state    = (regime.get("expansion_state")  or "unknown").lower()

    if not _enabled():
        return _disabled_result(regime_label, vol_state, exp_state)

    selected_pb = (playbook.get("selected_playbook") or "no_playbook").lower()

    cap, required_trigger, min_age, profile = _BASE_PROFILE.get(
        regime_label, _BASE_PROFILE["unknown"]
    )

    reasons:  list[str] = []
    blocking: list[str] = []
    forbidden: set[str] = set()

    reasons.append(f"regime={regime_label} base: cap={cap} trigger>={required_trigger} min_age={min_age}")

    # ── Regime-family playbook rules ──────────────────────────────────────────
    if regime_label in _REVERSAL_ONLY_REGIMES:
        forbidden |= _CONTINUATION_PLAYBOOKS
        reasons.append(
            f"{regime_label}: continuation playbooks forbidden — "
            "only reversal entries with confirmed trigger"
        )

    # ── Overlay: expansion exhaustion risk ────────────────────────────────────
    if exp_state == "exhaustion_risk":
        forbidden |= _CONTINUATION_PLAYBOOKS
        required_trigger = "confirmed"
        cap     = min(cap, 0.5)
        min_age = max(min_age, 2)
        reasons.append(
            "expansion exhaustion_risk: late continuation blocked, "
            "confirmed trigger required, risk cap <= 0.5"
        )

    # ── Overlay: volatility state ─────────────────────────────────────────────
    if vol_state in _SEVERE_VOL:
        cap = min(cap, 0.25)
        if regime_label not in _TREND_REGIMES:
            required_trigger = "confirmed"
        reasons.append(f"volatility {vol_state}: risk cap <= 0.25")
    elif vol_state in _UNSTABLE_VOL:
        cap = min(cap, 0.5)
        if regime_label not in _TREND_REGIMES:
            required_trigger = "confirmed"
        reasons.append(f"volatility {vol_state}: risk cap <= 0.5, confirmed trigger outside strong trend")

    # ── Playbook permission decision ──────────────────────────────────────────
    allowed = True
    if selected_pb not in ("no_playbook", ""):
        if selected_pb in forbidden:
            allowed = False
            blocking.append(
                f"playbook '{selected_pb}' forbidden in regime '{regime_label}'"
                + (" with exhaustion_risk" if exp_state == "exhaustion_risk" else "")
            )
        elif regime_label in _REVERSAL_ONLY_REGIMES and selected_pb not in _REVERSAL_PLAYBOOKS:
            allowed = False
            blocking.append(
                f"playbook '{selected_pb}' not in permitted reversal set for regime '{regime_label}'"
            )
    else:
        reasons.append("no active playbook — permissions evaluated for environment only")

    # ── Status ────────────────────────────────────────────────────────────────
    if not allowed:
        permission_status = "blocked"
    elif cap < 1.0 or required_trigger == "confirmed" or min_age > 1:
        permission_status = "restricted"
    else:
        permission_status = "allowed"

    return {
        "enabled":                 True,
        "regime_label":            regime_label,
        "volatility_state":        vol_state,
        "expansion_state":         exp_state,
        "allowed":                 allowed,
        "permission_status":       permission_status,
        "risk_multiplier_cap":     cap,
        "required_trigger_status": required_trigger,
        "management_profile":      profile,
        "min_setup_age_scans":     min_age,
        "forbidden_playbooks":     sorted(forbidden),
        "reasons":                 reasons[:6],
        "blocking_reasons":        blocking[:4],
    }
