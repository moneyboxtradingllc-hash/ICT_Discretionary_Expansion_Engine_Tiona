"""Deterministic stair-step profit protection for an already-open position.

This is a proposal layer only.  It has no venue, model, or mutation authority;
the established protection actuator owns every live stop amendment.
"""
from __future__ import annotations

import math

from broker import break_even as BE

SCHEMA = "trailing_protection.v1"
TRIGGER_R = 2.0
PROPOSE = "propose_trailing"
HOLD = "hold"
REFUSED = "refused"


def evaluate(*, direction, entry_fill_price, initial_stop_price,
             current_price, armed: bool, tick_size=None) -> dict:
    """Return the one lawful stair-step destination, or no proposal.

    R is permanently measured from actual fill to the original structural
    baseline.  The current stop is intentionally not an input: moving a stop
    must never move the ruler used to decide the next step.
    """
    def out(outcome, reason=None, detail="", **extra):
        return dict({"schema": SCHEMA, "outcome": outcome, "reason": reason,
                     "detail": detail, "direction": BE._side(direction)}, **extra)

    side = BE._side(direction)
    if side is None:
        return out(REFUSED, "unknown_direction")
    if not armed:
        return out(REFUSED, "protection_baseline_not_armed")
    fill = BE._num(entry_fill_price)
    now = BE._num(current_price)
    risk = BE.initial_risk_points(direction=direction, entry_fill_price=fill,
                                  initial_stop_price=initial_stop_price)
    if fill is None or risk is None or risk <= 0:
        return out(REFUSED, "initial_risk_is_not_positive")
    if now is None:
        return out(REFUSED, "no_fresh_executable_quote",
                   initial_risk_points=round(risk, 4))
    open_r = BE.open_r_multiple(direction=direction, entry_fill_price=fill,
                                initial_stop_price=initial_stop_price,
                                current_price=now)
    common = {"initial_risk_points": round(risk, 4),
              "open_r": None if open_r is None else round(open_r, 4)}
    if open_r is None or open_r < TRIGGER_R:
        return out(HOLD, "below_trailing_trigger", **common)
    locked_r = math.floor(open_r) - 1
    raw = fill + (locked_r * risk) if side == "long" else fill - (locked_r * risk)
    desired = BE.normalize_to_tick(direction=direction, raw_price=raw,
                                   tick_size=tick_size)
    if desired is None:
        return out(REFUSED, "invalid_tick_geometry", **common)
    # A stop must still be executable as protection against the same governed
    # quote used to measure open R.  Never clamp a pathological value.
    invalid = desired >= now if side == "long" else desired <= now
    if invalid:
        return out(REFUSED, "trailing_stop_not_protective_against_quote",
                   desired_stop=desired, locked_r=locked_r, **common)
    return out(PROPOSE, None,
               f"open {open_r:.4f}R locks {locked_r}R at {desired}",
               trailing_price=desired, desired_stop=desired,
               locked_r=locked_r, raw_trailing_price=round(raw, 10), **common)
