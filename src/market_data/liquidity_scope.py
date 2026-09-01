"""LIQUIDITY SCOPE — what a sweep took, relative to a NAMED authority, at the
instant it happened.

LUNA-LIQUIDITY-SCOPE-TRUTH-1 (2026-09-01).

THE DEFECT. `manipulation_detector` already distinguished an external sweep from
an internal raid, and weighted them differently (30 vs 20) -- but recomputed
both every scan against a ROLLING pivot context (`candles[-40:]`), so the scope
of a past event changed as the market moved. Proven mechanically:

    pivots [100, 110]        -> external_sweep TRUE,  internal_raid FALSE
    pivots [100, 110, 120]   -> external_sweep FALSE, internal_raid TRUE

Same candle. Same price. Same event. A later, higher swing rewrote what an
earlier event WAS. Reconstructed on the 2026-09-01 tape, the 09:39-09:40 ET
sell-side event pierced and reclaimed the then-outermost low 29062.75 and read
EXTERNAL at 13:40Z; by 13:45Z the extreme had moved to 29040 and the same event
read as no external sweep at all.

CONTEXT MAY EVOLVE. HISTORY MAY NOT. Scope is therefore stamped ONCE, when the
occurrence is minted, together with the reference it was judged against. Later
scans produce new facts about new events; they never rewrite an old one.

TWO AUTHORITIES, NAMED SEPARATELY. "External" is meaningless without "external
to WHAT", and the two references that matter here genuinely differ:

    detector_scope  relative to MANIPULATION_PIVOT_CONTEXT -- the rolling swing
                    pivots the manipulation detector already reasons over
    po3_scope       relative to SESSION_PO3_ACCUMULATION_RANGE -- the session
                    range that actually authorises entry

They can legitimately disagree: a level can sit inside a wide pivot context and
outside a tighter established accumulation range. Publishing one ambiguous
`scope` would have destroyed that distinction, so both travel with their own
provenance.

SCOPE IS NOT DIRECTION. `external` + `sell_side` + `reclaimed` does not mean
long, bullish, or permission. It means those three facts are true. What they
imply is Luna's judgement, combined with PO3 phase, delivery, structure and
location -- none of which this module knows or may assert.
"""
from __future__ import annotations

import hashlib

SCHEMA = "liquidity_scope.v1"

INTERNAL = "internal"
EXTERNAL = "external"
UNKNOWN = "unknown"
SCOPES = (INTERNAL, EXTERNAL, UNKNOWN)

MANIPULATION_PIVOT_CONTEXT = "MANIPULATION_PIVOT_CONTEXT"
SESSION_PO3_ACCUMULATION_RANGE = "SESSION_PO3_ACCUMULATION_RANGE"

BUY_SIDE, SELL_SIDE = "buy_side", "sell_side"


def _num(v):
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return f if f == f else None


def _rid(kind: str, *parts) -> str:
    """A deterministic id for one reference, from its own facts.

    Stable across processes and rebuilds: the same boundaries and birth produce
    the same id, so a reconstructed occurrence points at the same reference it
    pointed at live.
    """
    raw = "|".join(str(p) for p in parts)
    return "%s:%s" % (kind, hashlib.sha256(raw.encode()).hexdigest()[:12])


def detector_reference(highs, lows, *, context_start=None, context_end=None) -> dict:
    """The pivot context a sweep was judged against, captured as a fact.

    NO STABLE `range_id`, DELIBERATELY. A rolling pivot window has no causal
    identity that survives its own movement -- it is a different set of pivots
    every bar, not one structure that persists and extends. Claiming a stable id
    for it would assert a continuity the mechanism does not have. Only the
    SNAPSHOT is identifiable, and that is exactly what a frozen event needs.
    """
    hs = [h for h in (_num(x) for x in (highs or [])) if h is not None]
    ls = [l for l in (_num(x) for x in (lows or [])) if l is not None]
    outer_high = max(hs) if hs else None
    outer_low = min(ls) if ls else None
    return {
        "type": MANIPULATION_PIVOT_CONTEXT,
        "range_id": None,
        "reference_snapshot_id": _rid("mpc", context_start, context_end,
                                      outer_high, outer_low, len(hs), len(ls)),
        "outer_high": outer_high,
        "outer_low": outer_low,
        "pivot_highs": len(hs),
        "pivot_lows": len(ls),
        "context_start": context_start,
        "context_end": context_end,
        "identity_note": "a rolling pivot window has no identity across scans; "
                         "only this snapshot is identifiable",
    }


def po3_reference(po3_range: dict, *, session_date=None) -> "dict | None":
    """The session accumulation range a sweep was judged against.

    TWO IDENTITIES, AND THE DISTINCTION IS CAUSAL.

        range_id               the SAME accumulation range across its life.
                               Derived from session + birth, which do not move
                               when the range legitimately extends.
        reference_snapshot_id  the EXACT version used for this event, including
                               the boundaries as they stood.

    Keying identity on high/low would have made one causal range look like
    several unrelated ranges every time it extended -- A17 becoming A18 becoming
    A19 for the same structure. Now A17 extends from A17:v4 to A17:v5, and an
    event classified against v4 stays classified against v4 forever.

    None when no authoritative range existed -- a real state, never filled in
    later from a range that formed afterwards.
    """
    if not isinstance(po3_range, dict):
        return None
    high, low = _num(po3_range.get("high")), _num(po3_range.get("low"))
    if high is None or low is None:
        return None
    if not po3_range.get("established"):
        # A forming range has not yet earned the authority to say what is
        # outside it. Treating it as one would let a boundary that is still
        # moving decide that an event was external.
        return None
    birth = po3_range.get("birth")
    last_ext = po3_range.get("last_extension")
    range_id = _rid("po3", session_date, birth)
    return {
        "type": SESSION_PO3_ACCUMULATION_RANGE,
        "range_id": range_id,
        "reference_snapshot_id": _rid("po3v", range_id, last_ext, high, low),
        "session_date": session_date,
        "birth": birth,
        "last_extension": last_ext,
        "high": high,
        "low": low,
        "age_bars_at_event": po3_range.get("age_bars"),
    }


def _classify(level, side: str, outer_high, outer_low) -> str:
    """Where a swept level sits relative to one pair of boundaries.

    A buy-side sweep is judged against the upper boundary and a sell-side sweep
    against the lower one: taking liquidity above the outermost high is an
    external event on the buy side and says nothing about the low.
    """
    lv = _num(level)
    if lv is None or side not in (BUY_SIDE, SELL_SIDE):
        return UNKNOWN
    bound = outer_high if side == BUY_SIDE else outer_low
    if bound is None:
        return UNKNOWN
    if side == BUY_SIDE:
        return EXTERNAL if lv >= bound else INTERNAL
    return EXTERNAL if lv <= bound else INTERNAL


def stamp(sweep_fact: dict, *, highs=None, lows=None, po3_range=None,
          context_start=None, context_end=None, session_date=None) -> dict:
    """Freeze both scopes onto a sweep, at mint time. Never raises.

    Returns the fields to carry on the occurrence. An input this cannot judge
    yields `unknown` with a stated reason -- never a guessed side.
    """
    out = {
        "scope_schema": SCHEMA,
        "detector_scope": UNKNOWN,
        "detector_scope_reference": None,
        "po3_scope": UNKNOWN,
        "po3_scope_reference": None,
        "scope_reason": None,
    }
    try:
        if not isinstance(sweep_fact, dict):
            out["scope_reason"] = "no sweep fact"
            return out
        side = sweep_fact.get("liquidity_side_taken")
        level = sweep_fact.get("swept_level")
        ref = detector_reference(highs, lows, context_start=context_start,
                                 context_end=context_end)
        out["detector_scope_reference"] = ref
        out["detector_scope"] = _classify(level, side, ref["outer_high"],
                                          ref["outer_low"])
        p = po3_reference(po3_range, session_date=session_date)
        if p is None:
            out["po3_scope_reference"] = None
            out["po3_scope"] = UNKNOWN
            out["scope_reason"] = ("no established session accumulation range at "
                                   "event time; po3 scope is unavailable, not "
                                   "internal")
        else:
            out["po3_scope_reference"] = p
            out["po3_scope"] = _classify(level, side, p["high"], p["low"])
        return out
    except Exception as exc:  # noqa: BLE001 -- scope must never break a scan
        out["scope_reason"] = "scope unavailable: %s" % (exc,)
        return out
