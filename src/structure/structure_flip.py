"""Broken structure that now sits on the other side of price.

STRUCTURE-FLIP (2026-08-11), from the 2026-08-10 live forensic.

The Expansion Bot was bearish at 29783 and could only be offered one bearish
invalidation: a 15m protected high at 29900 -- a 117-point stop, correctly
refused by the 40-point ceiling. Meanwhile its own 5m structure block already
said `last_swing_low 29801.25, bos True`: known support, broken by the close.
Eighteen points overhead, and structurally invisible.

Measured across all 116 scans of that session:

    protected_high (the ONLY short invalidation)   53 present   1 inside 40pt
    protected_low  (long invalidation)             42 present  33 inside 40pt

The short side could not express local invalidation at all. That is a missing
WORD, not a missing trade -- so the repair adds vocabulary and changes no
threshold.

    PROTECTED_HIGH        a raided high that was rejected
    PROTECTED_LOW         a raided low that was rejected
    BROKEN_SUPPORT_FLIP   support broken bearishly; now overhead resistance
    BROKEN_RESISTANCE_FLIP  resistance broken bullishly; now support beneath

THE ONTOLOGY IS NOT MERGED. A broken swing low is NOT re-registered as a
protected high; they are different structural facts with different bases, and
collapsing them would destroy the ability to tell them apart later.

THREE THINGS THIS MODULE DELIBERATELY DOES NOT DO:

  it does not rank by distance      the nearest level is not the right level;
                                    Terra selects, risk vetoes
  it does not filter by the ceiling a legitimate 55-point flip is still a real
                                    structural fact, and saying otherwise would
                                    hide truth to manufacture a trade
  it does not infer direction       a break is minted from a directionally
                                    typed BOS, never from "price is below an
                                    old swing"
"""
from __future__ import annotations

import datetime as _dt
from dataclasses import dataclass, field

BROKEN_SUPPORT_FLIP = "BROKEN_SUPPORT_FLIP"
BROKEN_RESISTANCE_FLIP = "BROKEN_RESISTANCE_FLIP"
FLIP_TYPES = frozenset({BROKEN_SUPPORT_FLIP, BROKEN_RESISTANCE_FLIP})

# ── lifecycle ─────────────────────────────────────────────────────────────────
ACTIVE = "ACTIVE"
SUPERSEDED = "SUPERSEDED"
INVALIDATED = "INVALIDATED"
EXPIRED = "EXPIRED"

#: Higher timeframes win when the same price is broken on several. A level is
#: one structural fact even when four charts can see it.
TIMEFRAME_PRECEDENCE = ("15m", "5m", "3m", "1m")

#: Deterministic bound per side. Not "take the nearest N" -- the survivors are
#: chosen by structural precedence and recency, then this caps what remains so
#: a long session cannot accumulate an unbounded menu of old broken swings.
MAX_ACTIVE_FLIPS_PER_SIDE = 2


def _now() -> str:
    return _dt.datetime.now(_dt.timezone.utc).isoformat()


def _tf_rank(tf: str) -> int:
    try:
        return TIMEFRAME_PRECEDENCE.index(str(tf))
    except ValueError:
        return len(TIMEFRAME_PRECEDENCE)


@dataclass
class StructureFlip:
    """One broken structural level, with the lineage that created it."""
    flip_type: str
    level: float
    source_timeframe: str
    original_swing_type: str          # "swing_low" | "swing_high"
    break_direction: str              # "bearish" | "bullish"
    broken_at: str
    break_close: float = None
    lifecycle_state: str = ACTIVE
    swing_id: str = ""
    also_seen_on: list = field(default_factory=list)
    superseded_by: str = None
    invalidated_at: str = None
    invalidation_reason: str = None
    last_seen_at: str = ""

    @property
    def side(self) -> str:
        """Which thesis this level can invalidate."""
        return "bearish" if self.flip_type == BROKEN_SUPPORT_FLIP else "bullish"

    def identity(self) -> str:
        return f"{self.flip_type}:{self.level:g}"

    def as_candidate(self, index: int) -> dict:
        """The typed fact handed to the Brain. Never a bare price."""
        prefix = "BSF" if self.flip_type == BROKEN_SUPPORT_FLIP else "BRF"
        return {
            "invalidation_id": f"INV_{prefix}_{index}",
            "type": self.flip_type,
            "price": float(self.level),
            "source": f"structure.{self.source_timeframe}.{self.original_swing_type}",
            "timeframe": self.source_timeframe,
            "original_swing_type": self.original_swing_type,
            "break_direction": self.break_direction,
            "broken_at": self.broken_at,
            "break_close": self.break_close,
            "lifecycle_state": self.lifecycle_state,
            "swing_id": self.swing_id,
            "also_seen_on": list(self.also_seen_on),
            "basis": ("support broken by a bearish close; now overhead"
                      if self.flip_type == BROKEN_SUPPORT_FLIP
                      else "resistance broken by a bullish close; now beneath"),
        }


def observe(structure_block: dict, *, timestamp: str = None) -> list:
    """Directionally-typed breaks in ONE scan's structure block.

    Reads `bos_direction` and `broken_level`. A generic `bos: True` yields
    nothing -- that is the whole point of the engine change that produced them.
    """
    stamp = timestamp or _now()
    found = []
    for tf in TIMEFRAME_PRECEDENCE:
        block = (structure_block or {}).get(tf)
        if not isinstance(block, dict) or not block.get("bos"):
            continue
        direction = block.get("bos_direction")
        level = block.get("broken_level")
        if direction not in ("bullish", "bearish") or level is None:
            continue          # undirected break: not enough to mint a fact
        if direction == "bearish":
            flip_type, swing_type = BROKEN_SUPPORT_FLIP, "swing_low"
        else:
            flip_type, swing_type = BROKEN_RESISTANCE_FLIP, "swing_high"
        found.append(StructureFlip(
            flip_type=flip_type, level=float(level), source_timeframe=tf,
            original_swing_type=swing_type, break_direction=direction,
            broken_at=stamp, break_close=block.get("break_close"),
            swing_id=f"{tf}:{swing_type}:{float(level):g}", last_seen_at=stamp))
    return found


class FlipRegistry:
    """Lifecycle across the scans of one session.

    Stateful because BIRTH, SUPERSEDED and INVALIDATED are transitions, not
    properties of a single snapshot. A stateless read could only ever say
    ACTIVE, which is the shallow version of this idea.
    """

    def __init__(self) -> None:
        self.flips: dict = {}
        self.history: list = []

    # ── the per-scan update ──────────────────────────────────────────────────
    def update(self, structure_block: dict, *, timestamp: str = None) -> list:
        stamp = timestamp or _now()
        seen = observe(structure_block, timestamp=stamp)
        seen = self._dedupe(seen)
        seen_ids = {f.identity() for f in seen}

        for flip in seen:
            existing = self.flips.get(flip.identity())
            if existing is None:
                self.flips[flip.identity()] = flip
                self.history.append({"at": stamp, "event": "BIRTH",
                                     "id": flip.identity(),
                                     "level": flip.level,
                                     "timeframe": flip.source_timeframe})
            else:
                # still broken on this scan: refresh liveness, keep the lineage
                existing.last_seen_at = stamp
                existing.also_seen_on = flip.also_seen_on
                if existing.lifecycle_state != ACTIVE:
                    existing.lifecycle_state = ACTIVE
                    existing.invalidated_at = None
                    existing.invalidation_reason = None

        # A level no longer reported as broken has been structurally reclaimed.
        for identity, flip in self.flips.items():
            if identity not in seen_ids and flip.lifecycle_state == ACTIVE:
                flip.lifecycle_state = INVALIDATED
                flip.invalidated_at = stamp
                flip.invalidation_reason = (
                    "the source structure is no longer reported as broken; "
                    "the level was reclaimed")
                self.history.append({"at": stamp, "event": INVALIDATED,
                                     "id": identity, "level": flip.level})

        self._supersede(stamp)
        return self.active()

    def _dedupe(self, flips: list) -> list:
        """One price is ONE structural fact, whichever charts can see it."""
        best = {}
        for flip in sorted(flips, key=lambda f: _tf_rank(f.source_timeframe)):
            key = (flip.flip_type, round(flip.level, 4))
            if key in best:
                best[key].also_seen_on.append(flip.source_timeframe)
            else:
                best[key] = flip
        return list(best.values())

    def _supersede(self, stamp: str) -> None:
        """Keep the structurally newest levels per side, demote the rest.

        Precedence is recency of the break first, then timeframe -- NOT
        distance from price. Ranking by distance is how a structural menu turns
        into a nearest-stop machine.
        """
        for side in ("bearish", "bullish"):
            live = [f for f in self.flips.values()
                    if f.side == side and f.lifecycle_state == ACTIVE]
            if len(live) <= MAX_ACTIVE_FLIPS_PER_SIDE:
                continue
            ranked = sorted(live, key=lambda f: (f.broken_at,
                                                 -_tf_rank(f.source_timeframe)),
                            reverse=True)
            keep, demote = ranked[:MAX_ACTIVE_FLIPS_PER_SIDE], \
                ranked[MAX_ACTIVE_FLIPS_PER_SIDE:]
            newest = keep[0].identity() if keep else None
            for flip in demote:
                flip.lifecycle_state = SUPERSEDED
                flip.superseded_by = newest
                self.history.append({"at": stamp, "event": SUPERSEDED,
                                     "id": flip.identity(),
                                     "superseded_by": newest})

    # ── reading ──────────────────────────────────────────────────────────────
    def active(self, side: str = None) -> list:
        out = [f for f in self.flips.values() if f.lifecycle_state == ACTIVE]
        if side:
            out = [f for f in out if f.side == side]
        return sorted(out, key=lambda f: (_tf_rank(f.source_timeframe), f.level))

    def expire_session(self, *, reason: str = "session reset") -> None:
        """Structure does not survive a session boundary."""
        stamp = _now()
        for flip in self.flips.values():
            if flip.lifecycle_state in (ACTIVE, SUPERSEDED):
                flip.lifecycle_state = EXPIRED
                flip.invalidated_at = stamp
                flip.invalidation_reason = reason
                self.history.append({"at": stamp, "event": EXPIRED,
                                     "id": flip.identity()})

    def candidates(self) -> list:
        """Typed invalidation candidates for the authorized catalog."""
        return [f.as_candidate(i + 1) for i, f in enumerate(self.active())]
