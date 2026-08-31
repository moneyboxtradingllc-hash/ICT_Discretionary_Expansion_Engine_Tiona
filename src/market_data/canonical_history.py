"""RAW JOURNAL vs CANONICAL HISTORY — one loader, one meaning.

STEP 4 PREFLIGHT (2026-08-13).

The `.jsonl` under `data/market_data/topstepx/` is written by
`TopstepXDataProvider._persist`, which opens the file `"a"` and appends. It is
an APPEND-ONLY JOURNAL, and it was measured to contain:

    1730 rows      1691 distinct timestamps
    38 duplicate timestamp groups   (19 identical, 19 with CONFLICTING OHLC)
    2 out-of-order positions

Every measurement in the Step 3 series read that file directly with
`json.loads` and treated it as canonical history. Most conclusions survived, but
one did not: an FVG cardinality audit reported 5 completion-slot collisions on
1m, which vanished entirely on canonical input. Two array positions carrying the
same market bucket had let two triples claim one slot.

    RAW JOURNAL              append-only persistence evidence. Duplicates and
                             non-chronological order are LEGAL here.
    CANONICAL HISTORY        one bar per bucket, authoritative revision chosen,
                             chronological. The only legal input to
                             reconstruction.

The two words are not interchangeable, and this module exists so a measurement
cannot quietly pick the wrong one again.

WHY NOT NORMALISE INSIDE `reconstruct_*`?
-----------------------------------------
That would hide an upstream contract violation. Canonicalisation belongs at the
boundary that owns it (`candle_continuity.normalize` / `merge`); below that
boundary a duplicate bucket is a defect to surface, not a mess to silently
tidy. Reconstruction therefore ASSERTS canonical input rather than producing it.
"""
from __future__ import annotations

import json

from data_feed.candle_continuity import normalize
from market_data.object_identity import MarketObjectIdentityError


def load_normalized_last_wins_history(path: str) -> list:
    """The journal at `path`, deduplicated and ordered by LAST-OCCURRENCE-WINS.

    DELIBERATELY NOT NAMED `canonical`. STEP 4A proved append order is not
    authority order for this journal: of 19 conflicting duplicate groups, the
    later row carries MORE volume 10 times and LESS 9 times. A function that
    knowingly picks an unproven revision may not wear the word "canonical" --
    that is precisely the conflation this module exists to stop.

    It delivers: one row per bucket, chronological, well-formed-checkable.
    It does NOT deliver: a justified choice between conflicting revisions.

    `candle_continuity.normalize` is CALLED, never reimplemented: it is where
    "one bar per minute, last occurrence wins, oldest first" lives, and a second
    copy of that rule is exactly how two subsystems drift apart.
    """
    with open(path, encoding="utf-8") as fh:
        raw = [json.loads(line) for line in fh if line.strip()]
    return normalize(raw)


def load_raw_journal(path: str) -> list:
    """The journal verbatim. For AUDITING the journal itself -- never for
    reconstruction, and named so that intent is unmistakable at the call site."""
    with open(path, encoding="utf-8") as fh:
        return [json.loads(line) for line in fh if line.strip()]


def assert_canonical(candles: list, *, where: str = "reconstruction") -> list:
    """Refuse history that is not canonical. Returns the series unchanged.

    Duplicate or out-of-order buckets are the same species of defect as partial
    contract provenance: one market object occupying two slots with conflicting
    state. Silently repairing it here would let the violation keep happening
    upstream where it is actually caused.
    """
    stamps = [str((c or {}).get("timestamp") or "") for c in candles or []]
    if not stamps:
        return candles
    seen, dupes = set(), set()
    for s in stamps:
        (dupes if s in seen else seen).add(s)
    if dupes:
        raise MarketObjectIdentityError(
            f"{where}: {len(dupes)} timestamp(s) occupy more than one array "
            f"position (e.g. {sorted(dupes)[:3]}). This is an append-only "
            f"journal, not canonical history -- normalise it at the boundary "
            f"that owns canonicalisation.")
    if stamps != sorted(stamps):
        bad = next(i for i in range(len(stamps) - 1) if stamps[i] > stamps[i + 1])
        raise MarketObjectIdentityError(
            f"{where}: history is not chronological at position {bad} "
            f"({stamps[bad]} precedes {stamps[bad + 1]}).")
    return candles


#: STEP 4 §8 — WELL-FORMEDNESS, because the FVG proof depends on it.
#:
#: `find_fvgs`'s bullish and bearish predicates are mutually exclusive on one
#: triple ONLY while every candle satisfies `low <= high`. Measured over an
#: exhaustive grid: 0 of 100 well-formed combinations satisfy both, and 36
#: malformed ones DO -- so corrupt geometry could mint two contradictory FVGs in
#: a slot proven to hold at most one.
MALFORMED_CANDLE = "malformed_candle"


def candle_defects(candle: dict) -> list:
    """Every way this candle violates the canonical OHLC contract."""
    out = []
    c = candle or {}
    vals = {}
    for field in ("open", "high", "low", "close"):
        v = c.get(field)
        if not isinstance(v, (int, float)) or isinstance(v, bool) or v != v:
            out.append(f"{field}_not_finite_numeric")
        else:
            vals[field] = float(v)
    if len(vals) == 4:
        if vals["low"] > vals["high"]:
            out.append("low_above_high")
        if not vals["low"] <= vals["open"] <= vals["high"]:
            out.append("open_outside_range")
        if not vals["low"] <= vals["close"] <= vals["high"]:
            out.append("close_outside_range")
    return out


def assert_well_formed(candles: list, *, where: str = "canonical") -> list:
    """Refuse malformed candle geometry. Returns the series unchanged."""
    for i, c in enumerate(candles or []):
        defects = candle_defects(c)
        if defects:
            raise MarketObjectIdentityError(
                f"{where}: candle {i} ({(c or {}).get('timestamp')}) violates "
                f"the OHLC contract {defects}; malformed evidence may not mint "
                f"a canonical market object")
    return candles


# ══════════════════════════════════════════════════════════════════════════════
# STEP 4A.2 — BUCKET TIME IS NOT KNOWLEDGE TIME.
#
# Aug-12's duplicates are byte-identical full-state rewrites, so last-wins and
# first-wins produce the same candle. That removes REVISION-CHOICE ambiguity in
# that scope -- and nothing more. It does NOT establish what the engine
# possessed at any past moment, because the journal carries no `persisted_at`
# and seven separate processes wrote it that day, several of them REST-
# backfilling buckets that had already elapsed.
#
#     bucket timestamp 11:30   written by a backfill at 12:21
#     replay cut       11:45
#
# A replay that filters `bar["timestamp"] <= cut` includes that candle, because
# the BUCKET precedes the cut. Whether the running engine had it at 11:45 is a
# different question the final journal cannot answer. Building an as-of timeline
# from bucket timestamps would hand a past decision evidence fetched after it --
# hindsight leakage wearing a chronological costume.
RETROSPECTIVE_NORMALIZED = "RETROSPECTIVE_NORMALIZED"
PERCEPTION_AS_OF = "PERCEPTION_AS_OF"
LIVE_CURRENT = "LIVE_CURRENT"
HISTORY_BASES = (RETROSPECTIVE_NORMALIZED, PERCEPTION_AS_OF, LIVE_CURRENT)

AS_OF_AVAILABILITY_PROVEN = "AS_OF_AVAILABILITY_PROVEN"
AS_OF_AVAILABILITY_UNKNOWN = "AS_OF_AVAILABILITY_UNKNOWN"

UNRESOLVED_REVISION_AUTHORITY = "UNRESOLVED_REVISION_AUTHORITY"

#: The complete canonical candle state. Two revisions equal across ALL of these
#: are the same candle; equal on OHLC alone are NOT -- a differing volume is a
#: conflicting revision even though FVG geometry would never notice.
_CANDLE_STATE = ("timestamp", "contract", "open", "high", "low", "close", "volume")


def _state(row: dict) -> tuple:
    return tuple((row or {}).get(f) for f in _CANDLE_STATE)


def partition_revisions(raw: list) -> dict:
    """Split a raw journal into resolvable buckets and unresolved ones.

    EXACT-DUPLICATE COLLAPSE IS LOSSLESS for retrospective candle state: when
    every revision of a bucket agrees across the whole canonical state, there is
    no choice to get wrong. It says nothing about their write times, which is
    why `availability` stays UNKNOWN either way.

    CONFLICTING revisions are QUARANTINED, never resolved by heuristic. Last
    row, highest volume and closest-to-neighbours are all guesses dressed as
    policy.
    """
    groups = {}
    for row in raw or []:
        groups.setdefault(str((row or {}).get("timestamp") or ""), []).append(row)
    bars, unresolved = [], []
    for stamp, rows in groups.items():
        states = {_state(r) for r in rows}
        if len(states) == 1:
            bars.append(dict(rows[-1], raw_revision_count=len(rows)))
        else:
            unresolved.append({
                "bucket_timestamp": stamp,
                "contract": (rows[0] or {}).get("contract"),
                "candidate_revisions": [dict(r) for r in rows],
                "revision_count": len(rows),
                "reason": UNRESOLVED_REVISION_AUTHORITY})
    bars.sort(key=lambda b: str(b.get("timestamp")))
    unresolved.sort(key=lambda u: u["bucket_timestamp"])
    return {"bars": bars, "unresolved_revision_slots": unresolved,
            "history_basis": RETROSPECTIVE_NORMALIZED,
            "as_of_availability": AS_OF_AVAILABILITY_UNKNOWN}


def unresolved_buckets(partitioned: dict) -> set:
    return {u["bucket_timestamp"] for u
            in (partitioned or {}).get("unresolved_revision_slots") or []}


def depends_on_unresolved(source_timestamps, unresolved: set) -> list:
    """Which of an object's EXACT source bars sit on an unresolved slot.

    AUTHORITY PROPAGATES THROUGH DEPENDENCY, NOT FILE MEMBERSHIP. An unresolved
    bucket on 2026-08-05 does not make an Aug-12 FVG uncertain; it only matters
    if that FVG's own c1/c2/c3 rest on it.
    """
    return sorted({str(t) for t in (source_timestamps or []) if str(t) in (unresolved or set())})
