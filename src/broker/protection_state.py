"""PROTECTION-STATE-AUTHORITY-1 — two stops that were always one number.

Until now `ExecutionContext.structural_stop_price` carried two incompatible
meanings in a single field:

    the price at which the THESIS IS WRONG          — an audit fact, forever
    the price the venue WILL ACTUALLY EXECUTE       — a live, moving thing

Collapsing them is why "the stop is never adjustable" and "protect the bag"
read as contradictory doctrine. They are not in conflict. They were competing
for one variable.

    original_thesis_invalidation   frozen at baseline arming. Never rewritten.
                                   The trade's originating truth, kept for audit
                                   even after protection has moved far past it.

    active_protective_stop         what is working at the venue right now.
                                   May only ever move toward LESS risk.

THE LIFECYCLE BOUNDARY IS THE WHOLE POINT OF THIS MODULE.

    FILL
      -> PROVISIONAL BROKER PROTECTION      emergency execution safety
      -> POST-FILL STRUCTURAL RE-ANCHOR     may legitimately move EITHER way
      -> PROVEN STRUCTURAL PROTECTION       <-- the baseline arms HERE
      -> ONGOING POSITION MANAGEMENT        monotonic from here on

The naive invariant -- "the stop may never move farther from the fill" -- would
have been a defect. The certified re-anchor exists precisely to replace a
fill-relative provisional bracket with the authorized structural one, and the
structural stop is frequently WIDER. Arming the monotonic law at fill would
block the re-anchor and flatten live positions. So the law does not exist until
the structural protection has been venue-PROVEN, and `armed` is a real gate
with its own distinct refusal reason -- never silently treated as "no change".

MONOTONIC LAW, once armed:

    LONG    new >= active           SHORT   new <= active
    equality is a NO-OP, not a failure and not a modify
    anything restoring removed risk FAILS CLOSED -- refused, never clamped

WHY REFUSED AND NEVER CLAMPED. Silently clamping a bad proposal to the current
stop would report success for a request the system did not honour, and the
caller would go on believing protection had advanced. A refusal is auditable.
A clamp is a lie with a 2xx on it.

THE VENUE IS TRUTH, AND ADOPTION IS NOT SUBJECT TO THE MONOTONIC LAW.

The most dangerous state this system can hold is believing it is better
protected than the venue will honour. So on restart and on reconciliation the
working venue stop is adopted unconditionally -- INCLUDING when it is wider
than local state believed. That is not a monotonic violation, because
monotonicity governs proposals WE author, not observations of a reality that
does not answer to us. Local state never writes back over working protection.

WHAT THIS UNIT DELIBERATELY DOES NOT DO. No Luna management vocabulary, no
authorized-level catalog, no partials, no native trailing, no break-even, no R
or P&L thresholds, and no resurrection of `_get_structure_trail_stop`. This unit
only makes the state truthful enough for that work to be possible.
"""
from __future__ import annotations

import math

SCHEMA = "protection_state.v1"

LONG = "long"
SHORT = "short"

# ── outcomes ─────────────────────────────────────────────────────────────────
ADVANCE = "advance"          # lawful reduction of risk
NO_OP = "no_op"              # already there; do not touch the venue
REFUSED = "refused"          # never proceed

# ── refusal reasons ──────────────────────────────────────────────────────────
BASELINE_NOT_ARMED = "protection_baseline_not_armed"
BASELINE_ALREADY_ARMED = "protection_baseline_already_armed"
NO_ACTIVE_STOP = "no_active_protective_stop"
UNKNOWN_DIRECTION = "unknown_direction"
NOT_A_PRICE = "proposed_stop_not_a_price"
RISK_RESTORATION = "risk_restoration_refused"

# ── venue reconciliation outcomes ────────────────────────────────────────────
ADOPTED = "adopted_from_venue"
IDENTICAL = "identical_to_venue"
NO_VENUE_STOP = "no_working_venue_stop"


def price(value):
    """A real, finite, non-boolean number, or None. Booleans are not prices."""
    if value is None or isinstance(value, bool):
        return None
    try:
        out = float(value)
    except (TypeError, ValueError):
        return None
    return None if (math.isnan(out) or math.isinf(out)) else out


def normalized_direction(value):
    """`long`/`short` only. Nothing is guessed from a sign or a size."""
    text = str(value or "").strip().lower()
    if text in ("long", "buy", "bullish"):
        return LONG
    if text in ("short", "sell", "bearish"):
        return SHORT
    return None


def reduces_risk(direction: str, active, proposed) -> "bool | None":
    """Strictly less risk than `active`. None when the question is unanswerable."""
    side = normalized_direction(direction)
    now, want = price(active), price(proposed)
    if side is None or now is None or want is None:
        return None
    return want > now if side == LONG else want < now


def evaluate_advance(*, direction, active_protective_stop, proposed_stop,
                     armed: bool) -> dict:
    """The monotonic verifier. Pure -- it touches no state and no broker.

    Returns an `outcome` of ADVANCE / NO_OP / REFUSED. Callers must branch on
    all three: NO_OP is a success that must not produce a venue modify, and
    REFUSED must never be coerced into one.
    """
    def out(outcome, reason=None, detail=""):
        return {"schema": SCHEMA, "outcome": outcome, "reason": reason,
                "detail": detail, "direction": normalized_direction(direction),
                "active_protective_stop": price(active_protective_stop),
                "proposed_stop": price(proposed_stop)}

    if not armed:
        return out(REFUSED, BASELINE_NOT_ARMED,
                   "structural protection has not been venue-proven; the "
                   "provisional bracket is not a management baseline")
    side = normalized_direction(direction)
    if side is None:
        return out(REFUSED, UNKNOWN_DIRECTION, f"direction {direction!r}")
    now = price(active_protective_stop)
    if now is None:
        return out(REFUSED, NO_ACTIVE_STOP,
                   "armed without an active protective stop is an impossible state")
    want = price(proposed_stop)
    if want is None:
        return out(REFUSED, NOT_A_PRICE, f"proposed {proposed_stop!r}")
    if want == now:
        return out(NO_OP, None, f"already protecting at {now}")
    if reduces_risk(side, now, want):
        return out(ADVANCE, None, f"{now} -> {want}")
    return out(REFUSED, RISK_RESTORATION,
               f"{side} protection may not move from {now} to {want}; that "
               f"restores risk this position has already given up")


def arm_baseline(*, direction, thesis_invalidation, proven_stop_price,
                 already_armed: bool) -> dict:
    """Freeze the originating truth and seed the live stop, exactly once.

    TWO AUTHORITIES, NOT ONE. This is the whole reason the split exists, so the
    two inputs are taken separately and never derived from each other:

        thesis_invalidation   the CANONICAL AUTHORED structural invalidation.
                              Thesis truth. What made the trade wrong. Comes
                              from structure, and structure alone.
        proven_stop_price     the VENUE-PROVEN ALIGNED working stop. Execution
                              truth. What will actually exit the position.

    They routinely differ by a tick, because the venue rounds to its own grid.
    That tick is not noise to be collapsed -- it is the proof that these are
    different concepts. Seeding both from the aligned price would let broker
    alignment quietly rewrite recorded thesis history, which is precisely the
    "one number means everything" assumption this unit exists to end.

    Called on the ONE path where `reanchor_protection_to_structure` returned
    `reanchored: True` -- stop modified, readback proven, target proven, whole
    protection verified. Not on any earlier return.

    Re-arming is refused. A second arming would rewrite
    `original_thesis_invalidation`, and that field's entire value is that it
    cannot be rewritten -- including by a restart that re-runs the fill path.
    """
    def out(ok, reason=None, detail="", **extra):
        return dict({"schema": SCHEMA, "armed": ok, "reason": reason,
                     "detail": detail}, **extra)

    if already_armed:
        return out(False, BASELINE_ALREADY_ARMED,
                   "the originating thesis invalidation is immutable; it may "
                   "not be re-frozen against a later price")
    side = normalized_direction(direction)
    if side is None:
        return out(False, UNKNOWN_DIRECTION, f"direction {direction!r}")
    authored = price(thesis_invalidation)
    if authored is None:
        return out(False, NOT_A_PRICE,
                   f"authored invalidation {thesis_invalidation!r}")
    proven = price(proven_stop_price)
    if proven is None:
        return out(False, NOT_A_PRICE, f"proven stop {proven_stop_price!r}")
    return out(True, None,
               f"baseline armed: thesis {authored}, working {proven}",
               original_thesis_invalidation=authored,
               active_protective_stop=proven,
               alignment_delta=round(proven - authored, 6))


def reconcile_with_venue(*, direction, active_protective_stop,
                         venue_stop_price) -> dict:
    """The venue is truth. Local belief is overwritten, never written back.

    Adoption is UNCONDITIONAL and deliberately exempt from the monotonic law.
    Monotonicity governs proposals WE author; it does not govern observations of
    a reality that does not answer to us. A venue stop adopted at a wider price
    is not a risk restoration -- it is the discovery that the risk was always
    there.

    The two divergences are not equally serious, so they are reported
    separately rather than as one boolean:

        local_believed_tighter   DANGEROUS. The process thought it was better
                                 protected than the venue will honour. This is
                                 the state that loses money quietly.
        local_believed_wider     The venue protects better than local state
                                 believed. Still a divergence worth an alarm.
    """
    side = normalized_direction(direction)
    local, venue = price(active_protective_stop), price(venue_stop_price)
    base = {"schema": SCHEMA, "direction": side,
            "active_protective_stop": local, "venue_stop_price": venue,
            "divergence": False, "local_believed_tighter": False,
            "local_believed_wider": False}
    if venue is None:
        return dict(base, outcome=NO_VENUE_STOP, adopted=local,
                    detail="no working protective stop found at the venue")
    if local == venue:
        return dict(base, outcome=IDENTICAL, adopted=venue,
                    detail=f"local state agrees with the venue at {venue}")
    # NAMED FOR WHAT IT ASKS. `reduces_risk(side, active, proposed)` answers
    # "is `proposed` less risk than `active`", so passing (venue, local) asks
    # "is LOCAL tighter than the venue" -- not "is the venue tighter". Under the
    # bare name `tighter` that argument order reads backwards to a reviewer, and
    # a rename is cheaper than re-deriving the polarity every time.
    local_is_tighter = reduces_risk(side, venue, local)
    return dict(base, outcome=ADOPTED, adopted=venue, divergence=True,
                local_believed_tighter=bool(local_is_tighter),
                local_believed_wider=(local_is_tighter is False),
                detail=f"venue is truth: {local} -> {venue}")
