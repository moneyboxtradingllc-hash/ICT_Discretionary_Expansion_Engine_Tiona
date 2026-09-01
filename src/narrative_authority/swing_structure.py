"""CANONICAL ORDINAL SWING STRUCTURE — what the confirmed registry actually did.

LUNA-SWING-SEQUENCE-TRUTH-1 (2026-09-01).

WHY THIS EXISTS. On the first live practice session the protected-swing registry
moved highs 29157.75 -> 29163.25 -> 29173 -> 29179 and lows
29040 -> 29085 -> 29116 -> 29135.75: seven consecutive rising confirmed swings.
The Brain was told `swing_sequence: unknown`, because the only sequence the
organism computed came from 15m candle pivots, that window produced ZERO pivots,
and the fallback tested whether 15m candles EXISTED rather than whether they had
produced anything. So the organism held the structural facts and withheld them,
and Luna reasoned about each swing in isolation as a rejected raid.

THE FIX IS INFORMATION, NOT PERMISSION. This module states what the confirmed
swings did. It does not decide what that means, does not rank timeframes into a
trade, and never says buy or sell. A BULLISH_SEQUENCE is a fact about ordering,
not an instruction; Luna weighs it against PO3, delivery, liquidity and location
exactly as she weighs everything else.

AUTHORITY. The confirmed/protected registry is canonical for ordinal structure,
because those are the durable swings the rest of the organism already trusts for
invalidation. The candle-pivot feature in `regime_classification` remains a
WINDOWED WITNESS for regime work; where the two disagree, the disagreement is
published as evidence rather than silently resolved. They are not peers.

BOTH DIMENSIONS SURVIVE. Every entry keeps its causal `basis`
(`buy_side_raid_rejected`) and carries its `ordinal` (`higher_high`) beside it.
A level can be a protected high AND a higher high; collapsing those into one
prose label is the defect this unit repairs.
"""
from __future__ import annotations

SCHEMA = "swing_structure.v1"

BULLISH = "BULLISH_SEQUENCE"
BEARISH = "BEARISH_SEQUENCE"
MIXED = "MIXED"
INSUFFICIENT = "INSUFFICIENT"
UNKNOWN = "UNKNOWN"

SEQUENCES = (BULLISH, BEARISH, MIXED, INSUFFICIENT, UNKNOWN)

#: Sufficiency is the SAME principle the existing pivot engine already applies:
#: a sequence needs at least two swings a side to have a relationship at all.
#: It is not a new tuned threshold.
MIN_SWINGS_PER_SIDE = 2

_RISING_HIGH, _FALLING_HIGH = "higher_high", "lower_high"
_RISING_LOW, _FALLING_LOW = "higher_low", "lower_low"


def _levels(entries) -> list:
    out = []
    for e in entries or []:
        if not isinstance(e, dict):
            continue
        try:
            out.append(float(e["level"]))
        except (KeyError, TypeError, ValueError):
            continue
    return out


def _ordinals(levels, side: str) -> list:
    """Ordinal labels BETWEEN consecutive confirmed swings.

    Derived here rather than trusted from the record so a lineage assembled by
    any route -- live registration, restart, forensic rebuild -- yields the same
    answer from the same levels.
    """
    rising = _RISING_HIGH if side == "high" else _RISING_LOW
    falling = _FALLING_HIGH if side == "high" else _FALLING_LOW
    equal = "equal_high" if side == "high" else "equal_low"
    out = []
    for prev, cur in zip(levels, levels[1:]):
        out.append(rising if cur > prev else falling if cur < prev else equal)
    return out


def _direction(ordinals, rising, falling) -> str:
    up = sum(1 for o in ordinals if o == rising)
    down = sum(1 for o in ordinals if o == falling)
    if up and not down:
        return "rising"
    if down and not up:
        return "falling"
    if up and down:
        return "mixed"
    return "flat"


def _pick(lineage: dict, key: str) -> tuple:
    """The timeframe whose confirmed lineage is longest, and its entries.

    Longest rather than fastest: the sequence should be read from whichever
    slot has actually accumulated the most confirmed lives, and a tie prefers
    the finer timeframe because that is where confirmations arrive first.
    """
    book = (lineage or {}).get(key) or {}
    if not isinstance(book, dict) or not book:
        return None, []
    order = {"1m": 0, "3m": 1, "5m": 2, "15m": 3}
    best_tf, best = None, []
    for tf, entries in book.items():
        entries = entries or []
        if len(entries) > len(best) or (
                len(entries) == len(best)
                and order.get(tf, 99) < order.get(best_tf, 99)):
            best_tf, best = tf, list(entries)
    return best_tf, best


def canonical_sequence(lineage: dict) -> dict:
    """Ordinal structure from the ordered confirmed swing registry.

    Never raises. A registry that cannot be read is UNKNOWN -- genuinely
    unavailable truth -- and is never quietly reported as balance or range.
    """
    base = {"schema": SCHEMA, "sequence": UNKNOWN, "authority": "confirmed_swing_registry",
            "high_timeframe": None, "low_timeframe": None,
            "highs": [], "lows": [], "high_ordinals": [], "low_ordinals": [],
            "high_direction": None, "low_direction": None,
            "confirmed_highs": 0, "confirmed_lows": 0,
            "detail": "no confirmed swing lineage available"}
    try:
        if not isinstance(lineage, dict):
            return base
        # ABSENT REGISTRY vs EMPTY REGISTRY. These are different claims and must
        # not collapse. A lineage that was never supplied is UNAVAILABLE TRUTH
        # -- UNKNOWN. A lineage that was supplied and holds no swings yet is
        # readable and simply early -- INSUFFICIENT. Reporting the second as
        # UNKNOWN would tell the Brain the mechanism failed when it is merely
        # waiting; reporting the first as INSUFFICIENT would claim we looked.
        if "highs" not in lineage and "lows" not in lineage:
            return base
        hi_tf, hi = _pick(lineage, "highs")
        lo_tf, lo = _pick(lineage, "lows")
        hl, ll = _levels(hi), _levels(lo)
        base.update(high_timeframe=hi_tf, low_timeframe=lo_tf,
                    highs=hl, lows=ll,
                    confirmed_highs=len(hl), confirmed_lows=len(ll))
        if len(hl) < MIN_SWINGS_PER_SIDE or len(ll) < MIN_SWINGS_PER_SIDE:
            base["sequence"] = INSUFFICIENT
            base["detail"] = (
                "%d confirmed high(s) / %d confirmed low(s); a relationship "
                "needs at least %d a side" % (len(hl), len(ll), MIN_SWINGS_PER_SIDE))
            base["high_ordinals"] = _ordinals(hl, "high")
            base["low_ordinals"] = _ordinals(ll, "low")
            return base
        ho, lo_ord = _ordinals(hl, "high"), _ordinals(ll, "low")
        hdir = _direction(ho, _RISING_HIGH, _FALLING_HIGH)
        ldir = _direction(lo_ord, _RISING_LOW, _FALLING_LOW)
        if hdir == "rising" and ldir == "rising":
            seq = BULLISH
        elif hdir == "falling" and ldir == "falling":
            seq = BEARISH
        else:
            # CONFLICT IS REPORTED, NOT RESOLVED. Higher highs with lower lows is
            # a widening auction and a real market state; inventing a lean for it
            # would be the organism authoring direction it cannot prove.
            seq = MIXED
        base.update(sequence=seq, high_ordinals=ho, low_ordinals=lo_ord,
                    high_direction=hdir, low_direction=ldir,
                    detail="highs %s (%s), lows %s (%s) over %d/%d confirmed swings"
                           % (hdir, hi_tf, ldir, lo_tf, len(hl), len(ll)))
        return base
    except Exception as exc:  # noqa: BLE001 -- unreadable truth is UNKNOWN
        base["sequence"] = UNKNOWN
        base["detail"] = "swing lineage unreadable: %s" % (exc,)
        return base


def witness_agreement(canonical: dict, windowed_sequence) -> dict:
    """Whether the windowed pivot witness agrees with the canonical registry.

    DISAGREEMENT IS PUBLISHED, NOT ARBITRATED. The registry is canonical, so a
    conflicting window never overrides it -- but hiding the conflict would throw
    away the fact that two mechanisms are looking at the same market and seeing
    different things, which is exactly the kind of uncertainty Luna should weigh.
    """
    canon = (canonical or {}).get("sequence", UNKNOWN)
    win = str(windowed_sequence or "unknown")
    lean = {"higher_highs_higher_lows": BULLISH,
            "lower_highs_lower_lows": BEARISH,
            "mixed_bullish_lean": MIXED, "mixed_bearish_lean": MIXED,
            "balanced": MIXED}.get(win)
    if canon in (UNKNOWN, INSUFFICIENT) or lean is None:
        agreement = "not_comparable"
    elif lean == canon:
        agreement = "agree"
    else:
        agreement = "disagree"
    # NOT NAMED `state`, DELIBERATELY. `bias` and `state` inside the structural
    # blocks are the legacy structure engine's directional verdicts, and
    # carrying them killed 43 scans on 2026-08-11; a boundary guard bans those
    # key names there. This value is an agreement between two mechanisms, not a
    # direction, but the guard cannot know that from a key name and should not
    # have to -- so the field is named for what it holds.
    return {"agreement": agreement, "canonical": canon, "windowed": win,
            "note": "the confirmed registry is authoritative; the windowed "
                    "pivot feature is a regime witness and does not override it"}
