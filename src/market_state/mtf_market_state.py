"""MTF_MARKET_STATE — how four timeframes relate, assembled from atomic facts.

DELIBERATELY NOT CALLED `structure`, and deliberately not an extension of the
legacy `STRUCTURE_WITNESS` contract. That subsystem stays exactly where it is:
witness-only, non-directional, no execution authority, no invalidation
authority, no objective authority. Nothing here reads it, aliases it, or
rehabilitates it.

WHY A NEW LANE INSTEAD OF CURING THE OLD ONE

The legacy structure subsystem earned its demotion: it lagged, it leaked
authority through hidden dependencies, and it took a week to fence off. The
lag has a mechanical cause worth stating, because it shapes this design --
a confirmed swing pivot cannot exist until N candles have formed on BOTH
sides of it, so on a 15m chart a turn at 10:15 may not be "known" until
10:45 or later. That is fine for CONTEXT and poison for EXECUTION.

So this module never asks "what does structure say". It asks four narrower
questions of facts that are each already useful on their own:

    swing detector          knows swings
    BOS/MSS detector        knows breaks and transitions
    liquidity detector      knows sweeps and reclaims
    protected-level registry knows active protected levels
    structure-flip registry knows broken levels now on the other side
    MTF_MARKET_STATE        knows only how those relate ACROSS timeframes

WHAT IT DOES NOT DO

It does not emit `direction`. There is no `MTF says BEARISH`. It emits a
per-timeframe state, the role that timeframe plays, and the CONFLICTS between
them -- then Terra reasons. Producing a single directional verdict here would
be rebuilding the god-object under a new name, which is the one outcome this
file exists to prevent.

    15m  context      the range being traded inside, external draws
    5m   active_leg   the structural leg currently in force
    3m   transition   shifts, retests, intermediate structure
    1m   execution    immediate evidence, trigger proximity

Alignment is reported, never required. A bearish 5m leg inside a neutral 15m
range with a bullish 1m rotation is an ordinary nested auction, not an error --
and forcing four-way agreement would delete exactly those setups.
"""
from __future__ import annotations

#: Role per timeframe. Registering all four is not the same as weighting them
#: alike; the role is what stops a 1m fact reading as context.
ROLES = {"15m": "context", "5m": "active_leg", "3m": "transition",
         "1m": "execution"}
ORDER = ("15m", "5m", "3m", "1m")

#: Facts that need candles on both sides of a pivot before they exist. They
#: describe what HAS happened and are honest context; they are never treated
#: as evidence of what price is doing right now.
CONFIRMED = "confirmed"
#: Facts available on the closing bar: a close through a level, a sweep and
#: reclaim, displacement. These describe the present.
REALTIME = "realtime"

BEARISH_BOS = "BEARISH_BOS"
BULLISH_BOS = "BULLISH_BOS"

ALIGNED = "ALIGNED"
NESTED = "NESTED"
CONFLICTED = "CONFLICTED"
UNDETERMINED = "UNDETERMINED"

SCHEMA = "mtf_market_state.v1"


def _f(value):
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def timeframe_facts(tf: str, *, structure: dict, liquidity: dict,
                    protected_highs: dict, protected_lows: dict,
                    flips: list, price) -> dict:
    """Every atomic fact for ONE timeframe, tagged by how timely it is."""
    st = structure or {}
    liq = liquidity or {}
    price = _f(price)

    swing_high, swing_low = _f(st.get("last_swing_high")), _f(st.get("last_swing_low"))
    direction = st.get("bos_direction")
    broken = _f(st.get("broken_level"))
    bos_event = None
    if st.get("bos") and direction == "bearish":
        bos_event = BEARISH_BOS
    elif st.get("bos") and direction == "bullish":
        bos_event = BULLISH_BOS

    swept = bool(liq.get("sweep_detected"))
    reclaimed = bool(liq.get("reclaim_detected"))

    return {
        "timeframe": tf,
        "role": ROLES.get(tf, "unknown"),
        # ── confirmed (lagging by construction) ──────────────────────────────
        #
        # `bias` and `state` from the legacy structure engine are DELIBERATELY
        # NOT carried here. They are that engine's directional verdicts
        # ("bullish"/"bearish", "bearish_continuation"), and this module's whole
        # contract is that it reports roles and conflicts while emitting no
        # direction of its own. Passing them through would rebuild the
        # god-object under a new key.
        #
        # It is also what broke PROD-20260811: `scan_payload_taint` flags any
        # unlabeled `"bias"` key outside the exempt STRUCTURE_WITNESS block, so
        # every scan came back `BRAIN_DEGRADED - taint:['unlabeled_bias_key']`
        # and Terra was never called -- 43 scans, zero external cognition. The
        # contamination guard was right; this payload was wrong.
        CONFIRMED: {
            "last_swing_high": swing_high,
            "last_swing_low": swing_low,
            "mss_event": bool(st.get("mss")),
            "note": "pivot-derived; requires candles on both sides to exist",
        },
        # ── realtime (available on the closing bar) ──────────────────────────
        REALTIME: {
            "bos_event": bos_event,
            "broken_level": broken,
            "break_close": _f(st.get("break_close")),
            "sweep_detected": swept,
            "reclaim_detected": reclaimed,
            "sweep_direction": liq.get("sweep_direction"),
            "sweep_reclaim_complete": bool(swept and reclaimed),
        },
        # ── active levels owned by THIS timeframe ────────────────────────────
        "protected_high": (protected_highs or {}).get(tf),
        "protected_low": (protected_lows or {}).get(tf),
        "structure_flips": [f for f in (flips or [])
                            if str(f.get("timeframe")) == tf],
        "price_vs_swing_low": (None if (price is None or swing_low is None)
                               else ("below" if price < swing_low else "above")),
        "price_vs_swing_high": (None if (price is None or swing_high is None)
                                else ("above" if price > swing_high else "below")),
    }


def _leg_state(facts: dict):
    """What this timeframe is DOING, from realtime evidence only.

    Returns None rather than guessing. A timeframe with no break and no
    sweep/reclaim has nothing to say this scan, and saying nothing is a
    legitimate answer that a directional verdict would paper over.
    """
    rt = facts[REALTIME]
    if rt["bos_event"] == BEARISH_BOS:
        return "bearish_break"
    if rt["bos_event"] == BULLISH_BOS:
        return "bullish_break"
    if rt["sweep_reclaim_complete"]:
        if rt["sweep_direction"] == "above_high":
            return "buyside_swept_rejected"
        if rt["sweep_direction"] == "below_low":
            return "sellside_swept_reclaimed"
    return None


#: Which leg states point which way, for CONFLICT DETECTION ONLY. This never
#: becomes an output direction -- it exists so the synthesis can say "these two
#: timeframes disagree", which is the whole point.
_LEAN = {"bearish_break": "bearish", "buyside_swept_rejected": "bearish",
         "bullish_break": "bullish", "sellside_swept_reclaimed": "bullish"}


def build(*, structure: dict, liquidity: dict, protected_swings: dict,
          structure_flips: list = None, price=None,
          timestamp: str = "") -> dict:
    """Assemble MTF_MARKET_STATE. Deterministic. Never raises.

    `protected_swings` is the tracker's `state()`, whose `by_timeframe` block
    carries the per-timeframe registry. The legacy summary fields are ignored
    here on purpose: collapsing to one extreme level is the behaviour this
    module exists to stop relying on.
    """
    try:
        by_tf = (protected_swings or {}).get("by_timeframe") or {}
        highs, lows = by_tf.get("highs") or {}, by_tf.get("lows") or {}
        per_tf = {}
        for tf in ORDER:
            per_tf[tf] = timeframe_facts(
                tf, structure=(structure or {}).get(tf),
                liquidity=(liquidity or {}).get(tf),
                protected_highs=highs, protected_lows=lows,
                flips=structure_flips, price=price)

        legs = {tf: _leg_state(per_tf[tf]) for tf in ORDER}
        leans = {tf: _LEAN.get(legs[tf]) for tf in ORDER}
        stated = [tf for tf in ORDER if leans[tf]]

        conflicts = []
        for i, a in enumerate(stated):
            for b in stated[i + 1:]:
                if leans[a] != leans[b]:
                    conflicts.append({
                        "between": [a, b],
                        "roles": [ROLES.get(a), ROLES.get(b)],
                        "detail": (f"{ROLES.get(a)} {a} is {legs[a]} while "
                                   f"{ROLES.get(b)} {b} is {legs[b]}"),
                    })

        distinct = {leans[tf] for tf in stated}
        if not stated:
            alignment = UNDETERMINED
        elif len(distinct) == 1:
            alignment = ALIGNED if len(stated) > 1 else NESTED
        else:
            alignment = CONFLICTED

        return {
            "schema_version": SCHEMA,
            "timestamp": timestamp,
            "price": _f(price),
            "roles": dict(ROLES),
            "timeframes": per_tf,
            "synthesis": {
                "context_state": legs["15m"],
                "active_leg_state": legs["5m"],
                "transition_state": legs["3m"],
                "execution_state": legs["1m"],
                "timeframes_stating_something": stated,
                "alignment_state": alignment,
                "conflicts": conflicts,
                "note": ("Roles and conflicts only. This object states NO "
                         "overall direction: Terra owns the narrative."),
            },
        }
    except Exception as exc:  # noqa: BLE001 — synthesis may never cost a scan
        return {"schema_version": SCHEMA, "error": f"{type(exc).__name__}: {exc}",
                "timeframes": {}, "synthesis": {"alignment_state": UNDETERMINED,
                                                "conflicts": []}}


def opposing_execution_evidence(state: dict, direction: str) -> list:
    """Which timeframes are actively doing the OPPOSITE of a thesis.

    The 2026-08-10 12:34 question in one call: a bullish thesis was authorized
    while 1m and 3m were both in bearish breaks, and nothing in the payload
    could say so. This does not veto anything -- it makes the disagreement
    visible so a thesis has to be held against it.
    """
    want = "bullish" if str(direction) == "bearish" else "bearish"
    out = []
    for tf in ORDER:
        facts = ((state or {}).get("timeframes") or {}).get(tf) or {}
        lean = _LEAN.get(_leg_state(facts)) if facts.get(REALTIME) else None
        if lean == want:
            out.append({"timeframe": tf, "role": ROLES.get(tf),
                        "state": _leg_state(facts),
                        "broken_level": facts[REALTIME].get("broken_level")})
    return out
