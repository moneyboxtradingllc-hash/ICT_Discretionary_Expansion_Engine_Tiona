"""CONTINUITY-2E.2 — a tie earns no direction.

`manipulation_detector` and `displacement_detector` both resolved a direction
from component votes with:

    max(set(directions), key=directions.count)

`set` iteration order over strings depends on PYTHONHASHSEED, so on a TIE the
winner depended on which process happened to be running. Measured on the gold
tape, 5m at 15:08Z -- votes `rejection` (bullish) and `rapid_reversal` (bearish),
one each, score 30 both ways:

    seeds 0, 1, 99  ->  direction "bullish"
    seeds 2, 3, 42  ->  direction "bearish"

Identical evidence, identical score, opposite direction.

THE RULE IS NOT A DETERMINISTIC TIE-BREAK. Alphabetical, first-seen, last-seen or
a directional default would all make replay stable while still asserting a
direction the evidence never supported -- a coin flip in a deterministic costume.
A 2-2 vote is uncertainty, and the truthful answer to uncertainty is to say so.

    unique plurality  ->  that direction, conflicted False
    tie               ->  None,           conflicted True
    no usable votes   ->  None,           conflicted False   (absence, not conflict)

The precedent is already in this codebase: `po3_engine._directions` models "no
direction is authorised" as None with an explicit `fallback_none` provenance
rather than inventing one.
"""
from collections import Counter

#: The only labels that can win a vote. Anything else is not a direction and is
#: ignored rather than being allowed to dilute or win a tally.
DIRECTIONS = ("bullish", "bearish")


def resolve_direction_vote(votes) -> tuple:
    """(direction, conflicted) from a list of component direction votes.

    Deterministic and order-independent: the tally is by count, and a tie
    resolves to None rather than to whichever label a set happened to yield
    first. Never raises.
    """
    tally = Counter(v for v in (votes or []) if v in DIRECTIONS)
    if not tally:
        return None, False
    top = max(tally.values())
    winners = [d for d in DIRECTIONS if tally.get(d) == top]
    if len(winners) == 1:
        return winners[0], False
    return None, True
