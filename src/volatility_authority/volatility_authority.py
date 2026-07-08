"""
VOLATILITY-AUTHORITY — single owner of volatility veto authority (VOL-AUTH-1).

During the ADAPTIVE-8 forward-validation campaign the organism has not produced
enough post-repair trades to prove whether volatility filtering improves
expectancy. This module lets volatility be DEMOTED from veto authority to
observe-only: it still calculates, still logs toxic/dangerous/explosive states,
still records "would have vetoed" — but in observe_only mode it may NOT zero
qualification, block risk, or prevent execution. Flip the flag back to enforce
to restore full veto authority (no code change).

    VOLATILITY_AUTHORITY_MODE = enforce (default) | observe_only

This is the ONLY definition of "the volatility veto condition" and of the mode.
The three hard-block sites (confidence cap, qualification disqualifier, risk
governor) consult it — one owner, no drift. It NEVER touches FC-0B, stops,
position sizing, max trades, max risk, daily loss, or broker safety.
"""
import os


def volatility_mode() -> str:
    return (os.getenv("VOLATILITY_AUTHORITY_MODE", "enforce").lower().strip())


def observe_only() -> bool:
    """True → volatility is advisory (observe/score/warn/would_have_vetoed) and
    may not hard-block. False (default 'enforce') → full veto authority."""
    return volatility_mode() == "observe_only"


def volatility_veto_reason(ai_context: dict, volatility: dict) -> "str | None":
    """The reason volatility WOULD hard-veto this scan, or None if it would not.

    Mirrors the exact conditions of the three demoted hard-block sites:
      * dangerous market state with no lower-timeframe (5m/3m) safe harbor
      * 15m AND 5m both toxic/explosive
    Read-only; never raises. This is the would_have_vetoed oracle used for
    telemetry in BOTH modes."""
    ai  = ai_context or {}
    vol = volatility or {}
    market_state = ai.get("market_state", "")

    if market_state == "dangerous":
        v5 = (vol.get("5m") or {}).get("state", "")
        v3 = (vol.get("3m") or {}).get("state", "")
        safe_harbor = v5 in ("stable", "expanding") and v3 in ("stable", "expanding")
        if not safe_harbor:
            return "dangerous_market_state_no_lower_tf_safe_harbor"

    toxic = sum(
        1 for tf in ("15m", "5m")
        if (vol.get(tf) or {}).get("state") in ("toxic", "explosive")
    )
    if toxic >= 2:
        return "multi_timeframe_toxic_volatility(15m+5m)"

    return None


def volatility_telemetry(ai_context: dict, volatility: dict) -> dict:
    """The standard VOL-AUTH-1 audit block, identical shape everywhere it is
    surfaced (qualification, risk). Records what volatility WOULD have done and
    what authority it actually holds this session."""
    reason = volatility_veto_reason(ai_context, volatility)
    obs = observe_only()
    return {
        "volatility_authority":            "observe_only" if obs else "enforce",
        "volatility_would_have_vetoed":    reason is not None,
        "volatility_veto_reason":          reason,
        "volatility_effect_on_score":      "advisory_only" if obs else "enforced",
    }
