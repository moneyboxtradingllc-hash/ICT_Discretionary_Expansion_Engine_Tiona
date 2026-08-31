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


# ── CONTINUITY-2E.3 — asymmetric authority composition ────────────────────────
#
# AUDIT_2E3_realtime_volatility_authority.md proved realtime volatility is not a
# purely conservative signal. With settled history held byte-identical and only
# the forming bucket varying, it RAISED the risk multiplier 170 times, REMOVED a
# volatility veto 68 times, and GRANTED extended stop authority 22 times.
#
# The composition rule, and the reason it is not a ratchet:
#
#     SETTLED volatility establishes the MAXIMUM authority available.
#     REALTIME volatility may only REDUCE it.
#
# A ratchet would need memory across scans, which is hysteresis under another
# name -- and the audit found the volatility lane deliberately has no state
# machine. This composition is STATELESS: each scan re-derives both views and
# takes the more restrictive. A live bar that turns violent tightens instantly;
# a live bar that calms down simply stops tightening. Neither can manufacture
# permission the settled evidence never earned.
#
# CAUTION_RANK is derived from how the CONSUMERS actually treat each state, not
# from intuition about the words:
#   * `stable` / `expanding` are the safe-harbor set (confidence-cap bypass,
#     hard-block escape).
#   * `expanding` additionally GRANTS -- it is in extended_volatility_supported's
#     permit set -- so it is the single most permissive state, below `stable`.
#   * `unstable` caps risk at 0.5 in the permission matrix; `toxic`/`explosive`
#     cap at 0.25 and are the multi-timeframe hard-block states.
#   * `liquidity_vacuum` and `unknown` are neither safe harbor nor severe.
CAUTION_RANK = {
    "expanding": 0,          # most permissive: safe harbor AND grants stop width
    "stable": 1,             # safe harbor, grants nothing
    "unknown": 2,
    "liquidity_vacuum": 3,
    "unstable": 4,           # permission cap 0.5
    "toxic": 5,              # severe: cap 0.25, hard-block state
    "explosive": 5,
}
_UNRANKED = 2   # an unrecognised label is treated as neither safe nor severe


def _rank(state) -> int:
    return CAUTION_RANK.get(str(state or "unknown").lower(), _UNRANKED)


def compose_authority(settled: dict, realtime: dict) -> dict:
    """The volatility ONE authority consumer should read.

    Settled is the baseline; realtime may only make it more cautious. Returns a
    settled-shaped block whose `state` is the MORE RESTRICTIVE of the two, plus
    provenance so the composition is auditable rather than silent.

    Numeric fields follow the state that won, so `range_acceleration` and
    `volatility_score` describe the same evidence as the label beside them --
    a merged block must not be a chimera of two different reads.

    Consequence worth stating: `extended_volatility_supported` grants on
    `expanding`, which is rank 0, so a grant now requires BOTH views to be
    expanding. That is STRICTER than "settled only" and deliberately so -- the
    operator's rule was that realtime may never grant, and this also prevents a
    settled grant surviving a realtime deterioration.
    """
    s, r = settled or {}, realtime or {}
    if not s:
        # CONTINUITY-2E.3A — FAIL CLOSED. An earlier version returned the
        # realtime block here as `temporal_class="realtime_only"`, which would
        # have let realtime volatility hold authority precisely when the settled
        # baseline that bounds it did not exist. That contradicts the rule this
        # function exists to enforce: if settled establishes the MAXIMUM
        # authority available, then no settled view means no maximum was
        # established, and realtime cannot supply one.
        #
        # PROVEN UNREACHABLE from the production snapshot path -- classify_volatility
        # always returns a populated `state: "unknown"` block rather than {},
        # and the only skip (`if not candles: continue`) omits the timeframe
        # entirely instead of composing it. This is defence in depth against a
        # future caller, not a correction of live behaviour.
        return {"state": "unknown", "atr": None, "atr_trend": "unknown",
                "volatility_score": 0, "range_acceleration": 1.0,
                "temporal_class": "unknown_no_settled_baseline",
                "settled_state": None,
                "realtime_state": r.get("state"),
                "realtime_tightened": False,
                "volatility_authority_note":
                    "no settled baseline — realtime may not hold authority alone"}
    winner = r if _rank(r.get("state")) > _rank(s.get("state")) else s
    return dict(
        winner,
        temporal_class="authority",
        settled_state=s.get("state"),
        realtime_state=r.get("state"),
        realtime_tightened=bool(_rank(r.get("state")) > _rank(s.get("state"))),
    )


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
