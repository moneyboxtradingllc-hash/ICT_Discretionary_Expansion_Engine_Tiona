"""Canonical 1m history: one identity per minute, and gaps that cannot hide.

THE LAW THIS ENFORCES

    ABSENCE MAY NEVER MASQUERADE AS CONTINUITY.

WHAT WENT WRONG (2026-08-11). `fetch_1m_candles` served an in-process aggregator
built from the live tick stream, with no REST warm-up. Two operator restarts
punched holes in the day's history -- 10:11-10:19 and 10:41-11:01 ET -- and
nothing detected, reported or repaired them. The 11:03 payload handed the Brain
five 1m bars that LOOKED contiguous:

    14:39Z  14:40Z  14:41Z   <<20 MINUTES MISSING>>   15:01Z  15:02Z

`degraded[]` said nothing. The entire buy-side manipulation through 29,800 lived
inside that hole, so the Brain reasoned about a market it could not see.

WHY THIS IS WORSE THAN MISSING CONTEXT. `structure_engine.find_swings` confirms a
pivot by comparing a candle against its N neighbours ON BOTH SIDES. Across a hole
those "neighbours" are twenty real minutes away, so a gap does not merely hide
structure -- it can FABRICATE it: invent a pivot that never existed, or preserve
one the missing bars would have invalidated. Corrupted topology, not thin data.
And `timeframe_builder._aggregate` buckets by floored timestamp, so a 15m bar
built from two 1m bars is shape-identical to one built from fifteen. Nothing
downstream can tell them apart.

This module is PURE: no I/O, no clock, no network. It answers three questions --
what does the minute grid require, what is missing from it, and how do two
overlapping series become one canonical record -- so that every caller enforces
the same definition of "continuous".
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

#: One canonical identity per bar: the instrument's minute, as an aware UTC
#: instant. Two sources describing the same minute are the SAME bar, never two.
MINUTE = timedelta(minutes=1)


def parse_ts(value) -> "datetime | None":
    """ISO-8601 (with `Z` or offset) or datetime -> aware UTC datetime."""
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    text = str(value or "").strip()
    if not text:
        return None
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def canonical_key(candle: dict) -> "datetime | None":
    """The bar's identity. Same minute == same bar, whatever produced it."""
    stamp = parse_ts((candle or {}).get("timestamp"))
    return stamp.replace(second=0, microsecond=0) if stamp else None


def normalize(candles) -> list:
    """Oldest-first, one bar per minute, unparseable rows dropped.

    Chronology is normalised HERE, once. Some venue endpoints return newest
    first; letting that assumption leak downstream is how a "latest" bar becomes
    the oldest one in a window.

    On duplicate minutes the LAST occurrence wins, because callers merge in
    order of increasing authority (persisted -> REST -> live).
    """
    seen = {}
    for candle in candles or []:
        key = canonical_key(candle)
        if key is None:
            continue
        seen[key] = candle
    return [seen[k] for k in sorted(seen)]


def merge(*series) -> list:
    """Fold several sources into ONE canonical record.

    Argument order IS the authority order: later sources overwrite earlier ones
    for the same minute. There is deliberately no "reconcile disagreements"
    step -- two owners of one bar is the defect, not a situation to arbitrate.
    """
    combined = []
    for source in series:
        combined.extend(source or [])
    return normalize(combined)


def find_gaps(candles, *, expected_step: timedelta = MINUTE) -> list:
    """Every missing stretch inside the series' own span.

    Reports only INTERIOR gaps: a series that simply starts late is short, not
    holed, and calling that a gap would flag every cold start forever.

    Each gap names the last bar before it and the first bar after it, plus the
    minutes actually missing between them, so a repair can request exactly the
    window it needs and prove afterwards that it arrived.
    """
    ordered = normalize(candles)
    gaps = []
    for previous, following in zip(ordered, ordered[1:]):
        before, after = canonical_key(previous), canonical_key(following)
        delta = after - before
        if delta <= expected_step:
            continue
        missing = []
        cursor = before + expected_step
        while cursor < after:
            missing.append(cursor)
            cursor += expected_step
        gaps.append({
            "after": before.isoformat(),
            "before": after.isoformat(),
            "missing_minutes": len(missing),
            "first_missing": missing[0].isoformat() if missing else None,
            "last_missing": missing[-1].isoformat() if missing else None,
            "missing": [m.isoformat() for m in missing],
        })
    return gaps


def verify_continuous(candles) -> tuple:
    """(ok, gaps). The check a repair must PASS, not merely attempt.

    A REST call returning 200 is not proof that history healed. This is the
    second gate the operator asked for: without it we would only replace "we
    never noticed the gap" with "we assumed the fix worked", which is the same
    disease wearing a repair's clothes.
    """
    gaps = find_gaps(candles)
    return (not gaps), gaps


def summarize(candles, *, timeframe: str = "1m") -> dict:
    """A continuity report fit to travel in evidence and into `degraded[]`."""
    ordered = normalize(candles)
    ok, gaps = verify_continuous(ordered)
    return {
        "timeframe": timeframe,
        "continuous": ok,
        "bar_count": len(ordered),
        "first": canonical_key(ordered[0]).isoformat() if ordered else None,
        "last": canonical_key(ordered[-1]).isoformat() if ordered else None,
        "gap_count": len(gaps),
        "missing_minutes": sum(g["missing_minutes"] for g in gaps),
        "gaps": gaps,
    }


def degraded_markers(report: dict) -> list:
    """`degraded[]` entries. Absence has to be SAYABLE, not merely true."""
    if not report or report.get("continuous"):
        return []
    timeframe = report.get("timeframe", "1m")
    return [
        f"candle_gap:{timeframe}:{gap['first_missing']}-{gap['last_missing']}"
        f":missing={gap['missing_minutes']}:recovered=false"
        for gap in report.get("gaps") or []
    ]


def material_gap(report: dict, *, within_last: int = None,
                 minimum_minutes: int = 1) -> bool:
    """Does an unrepaired gap sit close enough to poison the current read?

    `within_last` bounds the concern to the recent window a decision actually
    depends on; None means the whole record. A hole in yesterday's tape is a
    fact about the archive, while a hole ten minutes ago is a fact about the
    trade being considered right now.
    """
    if not report or report.get("continuous"):
        return False
    gaps = report.get("gaps") or []
    if within_last is None:
        return any(g["missing_minutes"] >= minimum_minutes for g in gaps)
    last = parse_ts(report.get("last"))
    if last is None:
        return True                      # cannot locate the window: fail closed
    horizon = last - timedelta(minutes=int(within_last))
    for gap in gaps:
        if gap["missing_minutes"] < minimum_minutes:
            continue
        edge = parse_ts(gap["before"])
        if edge is not None and edge >= horizon:
            return True
    return False


def repair_window(gaps, *, pad_minutes: int = 5) -> "tuple | None":
    """(start, end) covering every gap, padded so pivot detectors re-confirm.

    Padded on both sides on purpose: a swing needs candles either side of it to
    exist at all, so refetching only the literal missing minutes would leave the
    pivots at each seam decided by the very neighbours the outage removed.
    """
    if not gaps:
        return None
    firsts = [parse_ts(g["first_missing"]) for g in gaps if g.get("first_missing")]
    lasts = [parse_ts(g["last_missing"]) for g in gaps if g.get("last_missing")]
    firsts = [f for f in firsts if f]
    lasts = [l for l in lasts if l]
    if not firsts or not lasts:
        return None
    pad = timedelta(minutes=max(0, int(pad_minutes)))
    return (min(firsts) - pad, max(lasts) + pad)


# ── history revision: normal growth vs retroactive change ────────────────────
#
# A boolean `rebuild_required` is too weak. It says a rebuild is OWED; it cannot
# say whether the rebuild that happened corresponds to the history that exists
# now. After a repair the candles are healthy while the trackers still hold
# pre-repair facts, and a scan that merely asks `continuous == True?` would
# recreate the same lie under a different flag.
#
# THE DISTINCTION THAT MATTERS: appending a freshly closed minute at the tip is
# ordinary forward progress and invalidates nothing. Inserting a minute at or
# BEFORE the previous tip rewrites the past every derived fact was computed
# from. Only the second is a revision.

def tip(candles):
    """The newest canonical minute in a record, or None."""
    ordered = normalize(candles)
    return canonical_key(ordered[-1]) if ordered else None


def minute_keys(candles) -> set:
    return {canonical_key(c) for c in candles or [] if canonical_key(c)}


def retroactive_change(previous_keys, current_keys, previous_tip) -> list:
    """Minutes that appeared at or before the previous tip. The past changed.

    Returns the inserted minutes so a caller can say exactly what was rewritten
    rather than only that something was.
    """
    if previous_tip is None:
        return []
    return sorted(k for k in (current_keys or set())
                  if k <= previous_tip and k not in (previous_keys or set()))


class HistoryRevision:
    """Monotonic identity of the canonical record's PAST.

    Bumps only when history is rewritten, never when it grows. Derived state may
    declare which revision it was built from, and authoritative cognition is
    permitted only while those two agree:

        canonical_history_revision == derived_state_revision   -> eligible
        canonical_history_revision >  derived_state_revision   -> REFUSE

    Self-contained on purpose: it is computed from the candles a consumer
    already holds, so no caller can bypass it by forgetting to pass a flag.
    """

    def __init__(self) -> None:
        self.revision = 0
        self._keys: set = set()
        self._tip = None
        self.last_inserted: list = []

    def observe(self, candles) -> int:
        """Fold in the current record. Returns the revision after observing."""
        keys = minute_keys(candles)
        inserted = retroactive_change(self._keys, keys, self._tip)
        if inserted:
            self.revision += 1
            self.last_inserted = [k.isoformat() for k in inserted]
        new_tip = tip(candles)
        # The tip never moves backward: a shorter record is a partial view, not
        # a rewrite, and treating it as one would bump the revision on every
        # trimmed window.
        if new_tip is not None and (self._tip is None or new_tip >= self._tip):
            self._tip = new_tip
        self._keys |= keys
        return self.revision

    def state(self) -> dict:
        return {"revision": self.revision,
                "tip": self._tip.isoformat() if self._tip else None,
                "known_minutes": len(self._keys),
                "last_inserted": list(self.last_inserted)}


# ── a market-history WINDOW, not a pile of observations ──────────────────────
#
# THE SECOND LAW (2026-08-11):
#
#     OBSERVATION COUNT MAY NEVER MASQUERADE AS ELAPSED MARKET TIME.
#
# `fetch_1m_candles(lookback_bars=300)` means "the last 300 records I happen to
# possess". Against a sparse store that walks backwards through time until it
# has counted 300 of them. The window V13 actually reasoned over spanned
# 2026-08-07 to 2026-08-11 -- three calendar days, six gaps, 5,414 missing
# minutes -- and `find_swings` dutifully confirmed pivots against "neighbours"
# that were days apart. 29,752.50 became a 5m/15m swing low that way, and from
# there the nearest-sell-side draw Terra was handed.
#
# `find_swings` was mechanically correct for its input. Its input contract
# simply never required the records to be adjacent in TIME. This closes that
# contract: a window is a bounded, continuous interval, and a bar count can
# never be satisfied by reaching across a discontinuity.
#
# BUCKET ALIGNMENT. Even a perfectly continuous window produces a LEADING
# partial higher-timeframe bucket when it starts mid-bucket -- measured: a 15m
# bar built from 10 one-minute bars, shape-identical to one built from 15.
# `_aggregate` cannot tell them apart, so a pivot can be confirmed against a bar
# that never existed. Snapping the window start UP to a bucket boundary removes
# the class entirely, without touching the aggregator. The TRAILING partial
# bucket is left alone: that is the forming bar, and live scanning wants it.

#: The coarsest timeframe derived from 1m. A window must start on one of these
#: boundaries or every derived series inherits a fabricated first bar.
COARSEST_TIMEFRAME_MINUTES = 15


def _align_up(moment, minutes: int):
    """The first bucket boundary at or after `moment`."""
    floor = moment.replace(second=0, microsecond=0)
    floor = floor.replace(minute=(floor.minute // minutes) * minutes)
    return floor if floor == moment else floor + timedelta(minutes=minutes)


def contiguous_tail(candles, *, horizon_minutes: int = None) -> list:
    """The unbroken run of minutes ending at the tip.

    Walks back from the newest bar and STOPS at the first discontinuity. It
    does not step over the gap to collect more bars, which is precisely the
    behaviour that produced a three-day "recent window".
    """
    ordered = normalize(candles)
    if not ordered:
        return []
    keys = [canonical_key(c) for c in ordered]
    last = keys[-1]
    start_index = 0
    for i in range(len(keys) - 1, 0, -1):
        if keys[i] - keys[i - 1] != MINUTE:
            start_index = i
            break
    if horizon_minutes:
        earliest = last - timedelta(minutes=int(horizon_minutes))
        while start_index < len(keys) and keys[start_index] < earliest:
            start_index += 1
    return ordered[start_index:]


def coherent_window(candles, *, horizon_minutes: int = 300,
                    minimum_bars: int = 60,
                    align_minutes: int = COARSEST_TIMEFRAME_MINUTES) -> dict:
    """A temporally bounded, continuous, bucket-aligned recent window.

    Returns the window plus an explicit verdict. Insufficient valid history is
    DEGRADATION, never permission to stitch older observations: if the coherent
    interval is too short for a detector's warm-up, the honest answer is "not
    enough history", not "here are some bars from Tuesday".
    """
    tail = contiguous_tail(candles, horizon_minutes=horizon_minutes)
    aligned = tail
    if tail and align_minutes:
        boundary = _align_up(canonical_key(tail[0]), int(align_minutes))
        aligned = [c for c in tail if canonical_key(c) >= boundary]
    ok, gaps = verify_continuous(aligned)
    span = 0
    if aligned:
        span = int((canonical_key(aligned[-1]) - canonical_key(aligned[0])
                    ).total_seconds() // 60) + 1
    sufficient = bool(aligned) and len(aligned) >= int(minimum_bars) and ok
    reason = ""
    if not aligned:
        # Distinguish the two ways a window can end up empty. "Nothing at all"
        # and "two bars that did not survive bucket alignment" are different
        # facts about the feed, and evidence that blurs them sends a reader
        # looking in the wrong place.
        reason = ("no contiguous history"
                  if not tail else
                  f"the contiguous tail is only {len(tail)} bar(s) and none "
                  f"survive alignment to a {align_minutes}-minute boundary")
    elif not ok:
        reason = "the aligned window is not continuous"
    elif len(aligned) < int(minimum_bars):
        reason = (f"only {len(aligned)} contiguous bars inside a "
                  f"{horizon_minutes}-minute horizon; {minimum_bars} required")
    return {
        "window": aligned,
        "sufficient": sufficient,
        "reason": reason,
        "bars": len(aligned),
        "span_minutes": span,
        "horizon_minutes": int(horizon_minutes),
        "minimum_bars": int(minimum_bars),
        "aligned_to_minutes": int(align_minutes or 0),
        "offered": len(normalize(candles)),
        "discarded_as_incoherent": len(normalize(candles)) - len(aligned),
        "continuous": ok,
        "gaps": gaps,
    }


def bucket_membership(candles, minutes: int) -> list:
    """How many 1m constituents each derived bucket actually has.

    A 15m bar built from two 1m bars is shape-identical to one built from
    fifteen. This makes the difference statable so a caller can prove the
    aggregation it is reasoning over is whole.
    """
    counts = {}
    for candle in normalize(candles):
        key = canonical_key(candle)
        bucket = key.replace(minute=(key.minute // minutes) * minutes)
        counts[bucket] = counts.get(bucket, 0) + 1
    return [{"timestamp": b.isoformat(), "members": n, "expected": minutes,
             "complete": n == minutes} for b, n in sorted(counts.items())]
