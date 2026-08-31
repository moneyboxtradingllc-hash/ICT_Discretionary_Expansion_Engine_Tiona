"""PRICE TICKS — one symmetric integer identity for a traded price.

LUNA-VAP-CAPTURE-AND-PERSISTENCE-1 (2026-08-30).

WHY THIS EXISTS. Volume-at-price needs a dictionary KEY, and a float is not one.
`29250.25` and `29250.249999999996` are the same economic price and two
different keys, so a profile built on float keys silently splits one price level
into several and reports a shape the market never traded.

WHY `break_even.normalize_to_tick` IS NOT REUSED. That primitive is
DIRECTIONAL on purpose -- ceil for a long, floor for a short -- because it snaps
PROTECTION and must always err toward more of it. Asked for a bucket key it
would place the same trade in different buckets depending on which side someone
happened to pass, which is exactly the drift this module exists to prevent.
Location must be symmetric. Protection must not be. They are different jobs and
they get different functions.

REFUSAL IS A RESULT. A price that is materially off the tick grid is not
rounded to the nearest bucket: it is refused. Rounding it would invent a trade
at a price the venue cannot quote, and a capture layer that quietly relocates
prints is worse than one that admits it saw something it did not understand.
Float representation noise is a different thing entirely and is tolerated.

Pure. No clock, no IO, no venue. Never raises.
"""
from __future__ import annotations

SCHEMA = "price_ticks.v1"

#: Absolute slack on the tick count, plus a relative term for large prices.
#: The absolute floor follows `break_even.normalize_to_tick`'s existing 1e-9
#: decimal-noise guard; the relative term keeps the same intent at MNQ scale,
#: where a tick index near 1.2e5 carries proportionally larger float error.
_ABS_TOLERANCE = 1e-9
_REL_TOLERANCE = 1e-12


def _num(v):
    """A real, finite float, or None. Booleans are not prices."""
    if isinstance(v, bool):
        return None
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return f if f == f and f not in (float("inf"), float("-inf")) else None


def tick_index(price, tick_size):
    """The integer tick a price sits on, or None if it does not sit on one.

    None means one of three honest things, and the caller must treat them the
    same way -- as evidence it cannot key:

        the price is unusable          (None, NaN, non-numeric)
        the tick size is unusable      (None, zero, negative)
        the price is materially off-grid

    A price that is on-grid to within float representation noise returns the
    tick it belongs to. Nothing is nudged toward a neighbour.
    """
    p, tick = _num(price), _num(tick_size)
    if p is None or tick is None or tick <= 0:
        return None
    n = p / tick
    nearest = round(n)
    if abs(n - nearest) > max(_ABS_TOLERANCE, abs(n) * _REL_TOLERANCE):
        return None
    return int(nearest)


def tick_price(index, tick_size):
    """The display price for a stored tick index. None when unusable.

    Rounded to 10 places to undo the float noise that `index * tick` can
    reintroduce -- the STORED identity is the integer; this only reconstructs
    something human-readable from it.
    """
    tick = _num(tick_size)
    if tick is None or tick <= 0 or isinstance(index, bool):
        return None
    try:
        i = int(index)
    except (TypeError, ValueError):
        return None
    return round(i * tick, 10)


def is_on_grid(price, tick_size) -> bool:
    """Whether a price can be keyed at all. Convenience over `tick_index`."""
    return tick_index(price, tick_size) is not None
