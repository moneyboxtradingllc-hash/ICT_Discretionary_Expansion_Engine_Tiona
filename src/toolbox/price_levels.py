"""
Price Level Detector — Phase 1L.
Identifies the price zone connected to each tool candidate using available candle data.
No execution, no order routing, no indicator recalculation.
All inputs are pre-computed snapshot dicts (timeframes, structure, liquidity).
"""
import os
from datetime import datetime

_TFS = ["15m", "5m", "3m", "1m"]

# Preferred source timeframe per tool family (first TF with usable candles wins)
#: How far back this detector looks for zone geometry. Five bars is the horizon
#: every committed zone measurement and the current brain-contract fingerprint
#: were taken against; it is pinned here so a change to canonical retention can
#: never move execution geometry as a side effect.
_ZONE_LOOKBACK_BARS = 5

_FAMILY_TF_PRIORITY: dict[str, list] = {
    "fvg":                 ["5m",  "15m", "3m",  "1m"],
    "ifvg":                ["3m",  "1m",  "5m",  "15m"],
    "order_block":         ["15m", "5m",  "3m",  "1m"],
    "breaker":             ["5m",  "15m", "3m",  "1m"],
    "rejection_block":     ["15m", "5m",  "3m",  "1m"],
    "ote_retracement":     ["15m", "5m",  "3m",  "1m"],
    "mss_retest":          ["5m",  "3m",  "1m",  "15m"],
    "ote_after_reclaim":   ["3m",  "1m",  "5m",  "15m"],
    "opening_fvg":         ["1m",  "3m",  "5m",  "15m"],
    "opening_order_block": ["1m",  "3m",  "5m",  "15m"],
    "range_break_retest":  ["15m", "5m",  "3m",  "1m"],
}

# ── Zone SOURCE-TIMEFRAME policy (2026-07-23) ────────────────────────────────
# The stop is anchored to the zone-defining candle's WICK (see _build_zone_for_
# family: inv = candle low/high), so STOP WIDTH SCALES WITH THE SOURCE CANDLE'S
# SIZE — i.e. with its timeframe. Measured on MNQ, 1m zones produce stops far
# below the survivability floor (~2pt median against a 15pt minimum): they can
# never size, and any that squeak through are tighter than the instrument's
# noise — the profile behind the 2026-07-21 stop-out (18pt stop nicked at the
# low, price then ran to target).
#
# 1m is dropped as a zone source. Per-family PRIORITY ORDERING is deliberately
# UNTOUCHED — ordering encodes tool semantics (an ifvg sourced from 3m is a
# different setup from one sourced from 15m), and reordering would change WHICH
# setups the bot detects. Only the allowed SET is constrained, so this can not
# silently change strategy beyond removing structurally unusable candidates.
_DEFAULT_SOURCE_TFS = ("15m", "5m", "3m")

# Per-symbol narrowing. Intentionally EMPTY: set each symbol from its OWN
# measured stop-width-by-timeframe distribution, never borrowed numbers.
_SYMBOL_SOURCE_TFS: dict[str, tuple] = {}


def _symbol_root(symbol: str) -> str:
    """'MNQ SEP26' / 'MNQU6' -> 'MNQ'. Tolerant of a missing symbol."""
    s = (symbol or "").strip().upper()
    return s.split()[0][:3] if s else ""


def _allowed_source_tfs(symbol: str = "") -> tuple:
    """Allowed zone SOURCE timeframes.

    Precedence: per-symbol env > global env > per-symbol table > default.
    A malformed or empty override falls back to the default, so a misconfigured
    env can never blank the toolbox. Instant rollback to pre-fix behaviour:
        ZONE_SOURCE_TFS="15m,5m,3m,1m"
    """
    root = _symbol_root(symbol)
    for key in ((f"ZONE_SOURCE_TFS_{root}" if root else None), "ZONE_SOURCE_TFS"):
        if not key:
            continue
        raw = os.getenv(key, "")
        if raw:
            parsed = tuple(t.strip() for t in raw.split(",") if t.strip() in _TFS)
            if parsed:
                return parsed
    if root in _SYMBOL_SOURCE_TFS:
        return _SYMBOL_SOURCE_TFS[root]
    return _DEFAULT_SOURCE_TFS




# Fibonacci OTE pocket bounds
_OTE_LOW_PCT  = 0.62
_OTE_HIGH_PCT = 0.79

# Tolerance for matching a structure swing to the candle extreme that formed it (MNQ tick).
_OB_ANCHOR_TOL = 0.25

# RELATION-TRUTH (2026-07-06) — the old absolute constant is RETIRED.
# `_TOUCH_TOLERANCE = 1.5` dated from the Phase-1L mock era (NQ-scale ~19,500
# prices) and classified QQQ prices up to 1.5 points beyond a 0.06-0.66 pt
# zone as "touching_zone". Every downstream authority trusted that field
# (FC-0B's in-zone guard, trigger prep, intent builder, the Brain payload),
# so all four fully-authorized trades on 2026-07-06 entered the
# guaranteed-kill band: relation guard passed on false adjacency, chase cap
# (the honest backstop) refused 4/4. "Touching" now means genuinely adjacent
# at the instrument's LIVE volatility — see _touch_tolerance(). Do not
# reintroduce an absolute here.
_TOUCH_TOLERANCE_FRACTION = 0.35   # of average recent candle range — the
                                   # file's established adjacency fraction
                                   # (same 0.35 used by range_break_retest)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _family(tool: str) -> str:
    for p in ("bullish_", "bearish_"):
        if tool.startswith(p):
            return tool[len(p):]
    return tool


def _current_price(snapshot: dict) -> float | None:
    """Most granular available last SETTLED close.

    TOOLBOX-EXECUTION-PRICE-1 (2026-08-20): this is STRUCTURAL. It locates zone
    geometry and it feeds CONTINUITY-2F's dual-arm comparison, both of which are
    questions about what the market has DONE. It is no longer used to answer
    where price is NOW -- see `_reanchor_location`.
    """
    tfs = snapshot.get("timeframes", {})
    for tf in ["1m", "3m", "5m", "15m"]:
        lc = tfs.get(tf, {}).get("last_candle")
        if lc and lc.get("close") is not None:
            return round(float(lc["close"]), 2)
    return None


#: Location fields answer "where is price NOW". Deliberately DISJOINT from
#: `EXECUTION_GEOMETRY_FIELDS`, which is what CONTINUITY-2F compares -- so
#: re-anchoring these can never move a stop, a zone or a temporal verdict.
LOCATION_FIELDS = ("current_price", "distance_to_zone", "price_relation",
                   "entered_zone", "invalidated")

LOCATION_BASIS_EXECUTION = "execution_price"
LOCATION_BASIS_ABSENT = "execution_price_absent"


def _execution_location(snapshot: dict, direction: str) -> tuple:
    """The FRESH SIDED price a current-location claim must be measured from.

    Ask to buy, bid to sell, and only while the quote is fresh. Returns
    (price, basis); price is None when no lawful executable price exists, and
    the settled close is NEVER substituted -- that substitution is the defect
    this exists to end.
    """
    block = (snapshot or {}).get("execution_price") or {}
    if not isinstance(block, dict) or not block.get("schema"):
        return None, LOCATION_BASIS_ABSENT
    from broker.topstepx_execution_price import executable_price, refusal
    px = executable_price(block, direction)
    if px is None:
        return None, f"execution_price_unusable:{refusal(block, direction)}"
    return round(float(px), 2), LOCATION_BASIS_EXECUTION


def _reanchor_location(zone: dict, snapshot: dict, direction: str) -> dict:
    """Re-answer the LOCATION fields from the fresh quote. Geometry untouched.

    TOOLBOX-EXECUTION-PRICE-1. `_make_zone` computed relation, distance and
    entered_zone from the newest SETTLED close. On 2026-08-20 at 11:02:10 that
    made `bearish_ote_after_reclaim` report `price_relation: inside_zone,
    distance_to_zone: 0.0` against 29394.72-29412.74 -- while the market was
    trading 29440.75, twenty-eight points ABOVE the zone. Mechanics believed
    price was standing in an entry it had already left behind.

    Called AFTER `_execution_geometry` has been compared, and it writes only
    `LOCATION_FIELDS`, which share no member with `EXECUTION_GEOMETRY_FIELDS`.
    CONTINUITY-2F's verdict is therefore untouchable from here.

    Fail-closed and LOUD: with no lawful executable price the location is
    `unknown`, not a settled-close guess, and `location_basis` names why. The
    settled close is preserved beside it as structural context.
    """
    if not isinstance(zone, dict):
        return zone
    zone["settled_price"] = zone.get("current_price")
    px, basis = _execution_location(snapshot, direction)
    zone["location_basis"] = basis
    if px is None:
        zone.update({"current_price": None, "distance_to_zone": None,
                     "price_relation": "unknown", "entered_zone": False,
                     "invalidated": False})
        zone.pop("_touch_tol", None)
        return zone
    zl, zh = zone.get("zone_low"), zone.get("zone_high")
    if zl is None or zh is None:
        zone["current_price"] = px
        zone.pop("_touch_tol", None)
        return zone
    relation = _price_relation(px, zl, zh, zone.pop("_touch_tol", None) or 0.0)
    zone.update({
        "current_price": px,
        "distance_to_zone": _distance(px, zl, zh),
        "price_relation": relation,
        "entered_zone": relation in ("inside_zone", "touching_zone"),
        "invalidated": _is_invalidated(direction, px, zone.get("invalidation_level")),
    })
    return zone


def _avg_range(candles: list) -> float:
    """Average candle range over recent candles — used as a zone tolerance proxy."""
    vals = [c.get("range", 0) for c in candles[-5:] if c.get("range", 0) > 0]
    return round(sum(vals) / len(vals), 4) if vals else 2.0


def _touch_tolerance(candles: list) -> float:
    """RELATION-TRUTH — adaptive touch tolerance: a fraction of the average
    recent candle range, so "touching_zone" means genuinely adjacent at the
    instrument's live volatility (QQQ 1m ≈ a few cents; mock-era NQ-scale
    candles stay proportionally sane). With NO real range data the tolerance
    is 0.0 — unknown volatility must never manufacture adjacency."""
    has_range = any(c.get("range", 0) > 0 for c in (candles or [])[-5:])
    if not has_range:
        return 0.0
    return round(_avg_range(candles) * _TOUCH_TOLERANCE_FRACTION, 4)


def _price_relation(current: float | None, zl: float, zh: float,
                    touch_tol: float = 0.0) -> str:
    if current is None:
        return "unknown"
    if zl <= current <= zh:
        return "inside_zone"
    if zl - touch_tol <= current < zl:
        return "touching_zone"
    if zh < current <= zh + touch_tol:
        return "touching_zone"
    return "below_zone" if current < zl else "above_zone"


def _distance(current: float | None, zl: float, zh: float) -> float | None:
    if current is None:
        return None
    if zl <= current <= zh:
        return 0.0
    return round(zl - current if current < zl else current - zh, 2)


def _is_invalidated(direction: str, current: float | None, inv_level: float | None) -> bool:
    if current is None or inv_level is None:
        return False
    return current < inv_level if direction == "bullish" else current > inv_level


def _make_zone(level_type: str, direction: str, zl: float, zh: float,
               inv_level: float | None, current: float | None, source_tf: str,
               touch_tol: float = 0.0, occurrence: dict = None) -> dict:
    zl = round(zl, 2)
    zh = round(zh, 2)
    if zl > zh:
        zl, zh = zh, zl  # guard inverted zone

    relation  = _price_relation(current, zl, zh, touch_tol)
    dist      = _distance(current, zl, zh)
    entered   = relation in ("inside_zone", "touching_zone")
    inval     = _is_invalidated(direction, current, inv_level)

    zone = {
        "level_type":         level_type,
        "direction":          direction,
        "zone_low":           zl,
        "zone_high":          zh,
        "midpoint":           round((zl + zh) / 2, 3),
        "current_price":      current,
        "distance_to_zone":   dist,
        "price_relation":     relation,
        # CURRENT geometric relation. STEP 4B.12 §6 UNIT 6 keeps this exactly as
        # it was and adds `retired` beside it: they answer different questions.
        # `invalidated` is where price sits NOW; `retired` is whether an
        # authoritative close already killed this occurrence for good.
        "entered_zone":       entered,
        "invalidated":        inval,
        "invalidation_level": round(inv_level, 2) if inv_level is not None else None,
        "source_tf":          source_tf,
        # Carried so `_reanchor_location` applies the SAME adjacency rule this
        # zone was built with rather than recomputing it. Stripped before the
        # zone is published.
        "_touch_tol":         touch_tol,
    }
    if occurrence:
        # STEP 4B.12 §6 UNIT 6 — WHICH OCCURRENCE THIS RECTANGLE IS.
        #
        # The zone used to be geometry with no name, so a consumer could not
        # tell one gap from another, could not tell whether the gap it was
        # looking at had already been worked, and could not check that the gap
        # it chose was the gap it got. The producer had the source stamps all
        # along -- `_find_fvg` threw them away at the boundary.
        zone.update({
            "occurrence_id":       occurrence.get("occurrence_id"),
            "formation_c1_time":   occurrence.get("c1_time"),
            "formation_c2_time":   occurrence.get("c2_time"),
            "formation_c3_time":   occurrence.get("c3_time"),
            "original_low":        occurrence.get("low"),
            "original_high":       occurrence.get("high"),
            "lifecycle": {k: occurrence.get(k) for k in (
                "entered", "fully_traversed", "close_through_far_boundary",
                "retired", "retirement_reason", "retirement_bar",
                "bars_since_formation")},
            "retired":             bool(occurrence.get("retired")),
        })
    return zone


def _no_zone(direction: str, current: float | None) -> dict:
    return {
        "level_type":         "no_zone",
        "direction":          direction,
        "zone_low":           None,
        "zone_high":          None,
        "midpoint":           None,
        "current_price":      current,
        "distance_to_zone":   None,
        "price_relation":     "unknown",
        "entered_zone":       False,
        "invalidated":        False,
        "invalidation_level": None,
        "source_tf":          None,
    }


# ── Zone finders ──────────────────────────────────────────────────────────────

def _minutes_between(c_a, c_b):
    """Minutes between two candles, or None when timestamps are unusable."""
    ta, tb = c_a.get("timestamp"), c_b.get("timestamp")
    if not ta or not tb:
        return None
    try:
        return abs((datetime.fromisoformat(str(tb))
                    - datetime.fromisoformat(str(ta))).total_seconds()) / 60.0
    except (ValueError, TypeError):
        return None


def _bar_span_tolerance(candles: list) -> float | None:
    """Max minutes a genuine 3-candle window may span.

    Derived from the series' own median bar interval, so it works on any
    timeframe without being told which one. None when timestamps are unusable —
    callers then fall back to the timestamp-free rule.
    """
    deltas = []
    for a, b in zip(candles, candles[1:]):
        d = _minutes_between(a, b)
        if d and d > 0:
            deltas.append(d)
    if len(deltas) < 3:
        return None
    deltas.sort()
    median = deltas[len(deltas) // 2]
    return median * 3.0          # two bar-widths plus slack


#: Minutes per timeframe, so a caller holding `source_tf` can supply cadence
#: authority without inventing a second table.
TF_MINUTES = {"1m": 1, "3m": 3, "5m": 5, "15m": 15, "30m": 30, "1h": 60}


#: STEP 4B.5 — CANONICAL TIMEFRAME ADJACENCY.
#:
#: FILTERING MAY REMOVE EVIDENTIARY AUTHORITY. IT MAY NEVER REMOVE A MARKET SLOT
#: FROM HISTORY AND MAKE ITS NEIGHBOURS CONSECUTIVE.
#:
#: Measured on 2026-08-12: the 1m bar at 18:11 is absent, so the 3m bucket at
#: 18:09 holds 2/3 members and `snapshot_builder` withholds it from the
#: displacement detector as unsettled. In that filtered list 18:06 and 18:12
#: became array-neighbours, and this function returned
#:
#:     18:03 / 18:06 / 18:12
#:
#: as a three-candle pattern -- a triple spanning nine minutes on a three-minute
#: timeframe. The chronology path, reading the unfiltered series, produced
#:
#:     18:06 / 18:09 / 18:12
#:
#: for the SAME completion slot. Two consumers, two source triples, one market.
#:
#: `_bar_span_tolerance` could not catch it: the filtered window's median delta
#: is still 3m, so the tolerance is 9m and the span is exactly 9m -- `9 > 9` is
#: False. That guard was built for session breaks, not a single missing bucket.
#:
#: The rule is now EXACT: no bucket the venue was expected to print may lie
#: strictly between consecutive members of the triple. Scheduled halts and the
#: daily close produce no expected buckets, so they remain legitimately
#: adjacent -- the venue calendar owns that question, not a second calendar
#: here.
def _crosses_forbidden_boundary(c1: dict, c3: dict) -> bool:
    """Does this triple span a venue closure? STEP 4B.7 §4.

    A generic FVG may not be manufactured out of the clock. Asked of the venue
    calendar directly rather than inferred from a span statistic, so the verdict
    does not depend on how many unrelated bars accompany the triple.
    """
    from market_data.venue_calendar import (
        classify, SCHEDULED_DAILY_MAINTENANCE, SCHEDULED_INTRADAY_TRADING_HALT,
        WEEKLY_MARKET_CLOSED)
    # ONLY a KNOWN closure forbids. `SPECIAL_SCHEDULE_UNKNOWN` means the date
    # lies outside the calendar's verified authority -- that is ignorance, not a
    # closure, and treating it as one would refuse every FVG outside the
    # verified range (measured: it killed a legitimate same-session July triple).
    # For those dates `_bar_span_tolerance` remains the guard it always was.
    _CLOSED = (SCHEDULED_DAILY_MAINTENANCE, SCHEDULED_INTRADAY_TRADING_HALT,
               WEEKLY_MARKET_CLOSED)
    ta, tb = (c1 or {}).get("timestamp"), (c3 or {}).get("timestamp")
    if not ta or not tb:
        return False
    try:
        from datetime import datetime, timedelta
        a = datetime.fromisoformat(str(ta).replace("Z", "+00:00"))
        b = datetime.fromisoformat(str(tb).replace("Z", "+00:00"))
    except (ValueError, TypeError):
        return False
    if b <= a:
        return False
    # Probe the interior. Any non-trading stretch between c1 and c3 means the
    # gap is at least partly an artefact of the venue being shut.
    span = (b - a).total_seconds() / 60.0
    steps = max(1, min(60, int(span)))
    for i in range(1, steps):
        probe = a + timedelta(minutes=span * i / steps)
        if classify(probe)["class"] in _CLOSED:
            return True
    return False


def _canonically_adjacent(a: dict, b: dict, tf_minutes: int) -> bool:
    """Are these two bars MARKET neighbours? Unknown is never yes.

    THE FAIL-OPEN THIS CLOSES (VENUE-CALENDAR-AUTHORITY-HORIZON-1, 2026-08-30).
    This asked `expected_buckets` alone and returned `not <result>`. On a date
    outside the verified ordinary ranges `is_expected` is False for every
    minute, so `expected_buckets` returns [] -- and `not []` is True. The
    calendar saying "I have no jurisdiction here" was read as "no market slot
    sits between them, therefore they are adjacent", and the triple was admitted
    as an FVG.

    Measured on 2026-08-30: ordinary authority ended 2026-08-31, so from
    2026-09-01 EVERY pair would have been declared adjacent and this guard --
    the one standing between the detector and the 2026-07-26 phantom -- would
    have stopped skipping anything at all.

    `swing_evidence` had already fixed this exact shape in three places by
    asking cadence authority FIRST. Same law, same order, here.
    """
    from market_data.venue_calendar import (CADENCE_KNOWN, cadence_authority_over,
                                            expected_buckets)
    ta, tb = (a or {}).get("timestamp"), (b or {}).get("timestamp")
    if not ta or not tb:
        return True                      # timestamp-free callers keep old behaviour
    try:
        # AUTHORITY BEFORE ADJACENCY. UNKNOWN SCHEDULE IS NOT AN EMPTY SCHEDULE.
        if cadence_authority_over(ta, tb)["authority"] != CADENCE_KNOWN:
            return False
        return not expected_buckets(ta, tb, int(tf_minutes))
    except Exception:                    # noqa: BLE001 — a calendar that cannot
        return False                     # answer proves no adjacency either


class UncadencedFvgRequest(ValueError):
    """A canonical FVG was requested without valid cadence authority."""


def tf_minutes_strict(source_tf, *, where: str = "canonical FVG") -> int:
    """Minutes for `source_tf`, or REFUSE. STEP 4B.7 §1.

    `TF_MINUTES.get(source_tf)` returns None for an unknown, renamed or
    malformed timeframe -- and None disabled the adjacency invariant. That is
    the bypass wearing a nicer shirt: unknown cadence became permission to trust
    array adjacency. Unknown cadence is a schema defect.
    """
    try:
        return TF_MINUTES[source_tf]
    except (KeyError, TypeError):
        raise UncadencedFvgRequest(
            f"{where}: {source_tf!r} has no known bar cadence; canonical FVG "
            f"construction requires cadence authority and may not fall back to "
            f"array adjacency")


def find_fvgs(candles: list, direction: str, tf_minutes: int = None, *,
              allow_uncadenced: bool = False) -> list:
    """Every 3-candle imbalance gap in `candles`, newest first.

    Bullish FVG: candle[i].high < candle[i+2].low
    Bearish FVG: candle[i].low  > candle[i+2].high

    SESSION BOUNDARIES ARE EXCLUDED. The three candles must be contiguous in
    time. Without that check the rule treats the last bar before a session close
    and the first bar after the reopen as adjacent, manufacturing a phantom gap
    out of the break itself — on MNQ that is ~33 points across the nightly
    17:00-18:00 close and ~195 points across a weekend. Those phantoms became the
    preferred toolbox zone, their edge became the structural invalidation, and
    the risk engine then rejected a 300-point stop. The bot looked fearful; it
    was being handed a level manufactured by a clock.

    Returns [{"index", "low", "high", "size", "c1_time", "c2_time", "c3_time"}].
    Public because the displacement detector scores imbalance as evidence of
    institutional commitment and must not re-implement the rule.

    The three source stamps let a consumer resolve a gap to its canonical FVG
    object EXACTLY. `index` is relative to the list the caller passed and is
    diagnostic only.
    """
    # STEP 4B.7 §3 — ONE SEMANTIC, NOT TWO.
    #
    # This is the canonical FVG producer, so cadence is REQUIRED. A caller that
    # genuinely wants raw three-array-element geometry must say so out loud;
    # silence can no longer weaken a market-object invariant.
    if tf_minutes is None and not allow_uncadenced:
        raise UncadencedFvgRequest(
            "find_fvgs: no bar cadence supplied. Pass tf_minutes for canonical "
            "FVGs, or allow_uncadenced=True to request raw array geometry with "
            "no market-adjacency guarantee")
    out = []
    if len(candles) < 3:
        return out
    tol = _bar_span_tolerance(candles)
    for i in range(len(candles) - 3, -1, -1):
        c1, c3 = candles[i], candles[i + 2]
        if tol is not None:
            span = _minutes_between(c1, c3)
            if span is None or span > tol:
                continue          # spans a session break — not an imbalance
        # STEP 4B.2 §7 — EXACT SOURCE PROVENANCE, PROMOTED NOT RECONSTRUCTED.
        #
        # `index` is a position in whatever list this caller happened to pass --
        # the displacement detector's trailing 10-bar window is not the
        # timeframe series, so an index cannot resolve a gap to a canonical
        # object. Consumers were reduced to matching on price, which is not
        # identity. The three source stamps are already in hand here; they were
        # simply thrown away.
        #
        # ADDITIVE ONLY. No geometry, no direction, no ordering, no count and no
        # size changes -- `index`/`low`/`high`/`size` keep their exact previous
        # values and meanings.
        c2 = candles[i + 1]
        # STEP 4B.5: three ARRAY neighbours are not three MARKET neighbours.
        if tf_minutes and not (_canonically_adjacent(c1, c2, tf_minutes)
                               and _canonically_adjacent(c2, c3, tf_minutes)):
            continue
        # STEP 4B.7 §4/§6 — SESSION BOUNDARY, INTRINSIC TO THE TRIPLE.
        #
        # The cross-close prohibition (proven doctrine from the 2026-07-26
        # incident: a 296-point phantom became the preferred toolbox zone) rested
        # on `_bar_span_tolerance`, a MEDIAN over the surrounding series. With
        # only three bars there are two deltas, the median cannot be computed,
        # and the guard silently switches off -- so the same triple was legal or
        # illegal depending on how much unrelated padding it arrived with.
        #
        # Legality of a three-candle object must be intrinsic to those three
        # candles plus venue authority. The venue calendar owns the question; no
        # second session calendar is built here.
        if tf_minutes and _crosses_forbidden_boundary(c1, c3):
            continue
        if direction == "bullish" and c1["high"] < c3["low"]:
            out.append({"index": i, "low": c1["high"], "high": c3["low"],
                        "size": round(c3["low"] - c1["high"], 2),
                        "c1_time": c1.get("timestamp"), "c2_time": c2.get("timestamp"),
                        "c3_time": c3.get("timestamp")})
        elif direction == "bearish" and c1["low"] > c3["high"]:
            out.append({"index": i, "low": c3["high"], "high": c1["low"],
                        "size": round(c1["low"] - c3["high"], 2),
                        "c1_time": c1.get("timestamp"), "c2_time": c2.get("timestamp"),
                        "c3_time": c3.get("timestamp")})
    return out


#: STEP 4B.12 §6 UNIT 6 — PLAIN-FVG LIFECYCLE.
#:
#: RETIREMENT_CLOSE_THROUGH is the ONE persistent retirement event, recovered
#: from this project's own language rather than imported from outside doctrine:
#:
#:   tool_readiness    "FVG filled before price returns to test -- imbalance
#:                      resolved, setup gone"
#:   entry_trigger_prep "gap fully filled AGAINST INTENDED DIRECTION"
#:                      "no opposing displacement candle CLOSING THROUGH zone"
#:   _is_invalidated    already treats the far boundary as decisive -- but only
#:                      for where price sits RIGHT NOW.
#:
#: The far boundary is PROVEN from `find_fvgs`, not assumed: a bullish gap is
#: [c1.high, c3.low] and sits above its formation, so it acts as support and its
#: far side is the LOW; a bearish gap is [c3.high, c1.low] and acts as
#: resistance, far side HIGH. `_build_zone_for_family` (`inv = zl if bullish
#: else zh`) and `_is_invalidated` independently agree.
RETIREMENT_CLOSE_THROUGH = "historical_close_through_far_boundary"

#: Observations that are TRUE FACTS but are NOT retirement events. Entering a
#: gap, or even traversing it intrabar, does not permanently kill it: this
#: project has no theorem that says so, and inventing one here would be exactly
#: the borrowed-doctrine error Unit 6 exists to avoid. They are published so a
#: consumer can see the whole life, never folded into authority.
FVG_LIFECYCLE_OBSERVATIONS = ("entered", "fully_traversed",
                              "close_through_far_boundary")


#: Timeframe label for the canonical id, from the cadence this producer was
#: given. `market_events` keys FVG identity on the timeframe LABEL, so the
#: minutes this layer works in are mapped back rather than a second convention
#: being invented.
_TF_LABEL_FOR_MINUTES = {1: "1m", 3: "3m", 5: "5m", 15: "15m", 30: "30m", 60: "1h"}


def fvg_occurrence_id(tf_minutes, direction: str, gap: dict,
                      contract=None) -> "str | None":
    """Stable identity for ONE plain-FVG occurrence, via the CANONICAL owner.

    ONE IDENTITY THEOREM, NOT TWO. `market_events._fvgs_at` already publishes
    FVG identity as `contract + timeframe + completion bucket`, minted through
    `object_identity.market_object_id`. The first version of this function
    formatted its own `fvg:{tf}m:{c3}` string, which is a SECOND
    almost-identical identity system for the same market object -- exactly the
    duplication that lets two layers disagree about which gap they mean. The
    canonical constructor is called directly instead.

    `direction`, `low`, `high` and `size` are RECONSTRUCTED from c1/c3 OHLC.
    History repair can change them, so putting them in the id would mint a twin
    on every revision instead of revising one object -- `market_events` records
    the same reasoning, and its proof that the bullish/bearish predicates are
    mutually exclusive on one triple is what lets direction stay out too.

    FAILS CLOSED. Returns None when the completion slot, the cadence or the
    contract cannot be established. An occurrence with no provable identity is
    not an occurrence that may author execution.
    """
    from market_data.object_identity import market_object_id, row_contract

    when = gap.get("c3_time")
    tf_label = _TF_LABEL_FOR_MINUTES.get(tf_minutes)
    if not when or not tf_label:
        return None
    if contract is None:
        src = gap.get("c3_row") or {}
        try:
            contract = row_contract(src, where="fvg occurrence") if src else None
        except Exception:            # noqa: BLE001 — contradictory row proves nothing
            return None
    if not contract:
        return None
    try:
        return market_object_id("FVG", contract=contract, timeframe=tf_label,
                                instant=when)
    except Exception:                # noqa: BLE001 — uncanonical instant/contract
        return None


def _bars_after_formation(candles: list, gap: dict) -> list:
    """Bars strictly after this gap's completion bar.

    AS-OF-T BY CONSTRUCTION. `candles` is the series the caller already holds at
    scan T, so a bar that has not happened yet cannot appear here and a later
    session's evidence can never leak backward into an earlier scan.

    LOCATED BY INDEX, NOT BY STAMP. `find_fvgs` walks `i` over the list the
    caller passed and this function receives that same list, so `i + 2` IS the
    completion bar -- exact, and independent of whether the series carries
    timestamps at all. The first version matched `c["timestamp"] ==
    gap["c3_time"]`, which on an unstamped series compared None to None, matched
    the FIRST bar, and handed back nearly the whole series as "after formation"
    -- absence masquerading as identity, and it manufactured retirement facts
    for gaps that had none.

    If the index is missing or does not address this list, NO bars are returned:
    a lifecycle that cannot be located is not a lifecycle that did not happen,
    and the caller must not be told otherwise.
    """
    idx = gap.get("index")
    if not isinstance(idx, int) or isinstance(idx, bool):
        return []
    start = idx + 3
    if start < 0 or start > len(candles or []):
        return []
    return list(candles[start:])


#: Why a lifecycle could not be established. NO EVIDENCE OF RETIREMENT is not
#: the same proposition as UNABLE TO EVALUATE RETIREMENT, and the first version
#: of this module collapsed both into `after == []` -> `retired = False` ->
#: `execution_eligible = True`. That is a fail-OPEN on unknown evidence.
LIFECYCLE_NOT_LOCATABLE = "formation_not_locatable_in_source_series"
LIFECYCLE_NO_SETTLED_AUTHORITY = "no_settled_evidence_authority_after_formation"
#: An expected market slot between formation and now was never observed, so the
#: retirement evidence may have lived in the bar that is missing. Temporal
#: LABELS on the bars that ARE present prove nothing about the one that is not.
LIFECYCLE_SLOT_COVERAGE_UNPROVEN = "expected_slot_absent_after_formation"


def _lifecycle_slot_coverage(bars: list, tf_minutes) -> "str | None":
    """Can the slots between formation and now account for themselves?

    STEP 4B.12 §6 UNIT 6 — ARRAY ADJACENCY IS NOT MARKET ADJACENCY, AGAIN.

    Reading a temporal label off the bars that are PRESENT says nothing about a
    bar that is ABSENT. A 5m occurrence completing at 14:50 whose 14:55 slot was
    never observed, followed by a forming 15:00, would otherwise be judged
    "nothing settled has happened yet" -- when the settled close that killed it
    could have been exactly the 14:55 print nobody has.

    THE CANONICAL OWNER ANSWERS THIS. `evidence_continuity` is the same
    authority Unit 5 used for follow-through: it already knows the venue
    calendar, already distinguishes a scheduled closure from a real hole, and
    already fails closed on unknown cadence. No second detector is built here.

    Returns None when coverage is proven, otherwise the reason it is not.
    """
    if len(bars or []) < 2:
        return None                      # nothing to bridge
    from market_data.evidence_continuity import (CONTIGUOUS,
                                                 EXPECTED_MARKET_BREAK, evaluate)
    tf_label = _TF_LABEL_FOR_MINUTES.get(tf_minutes)
    try:
        verdict = evaluate(bars, tf_label)
    except Exception:                    # noqa: BLE001 — cadence unavailable
        return LIFECYCLE_SLOT_COVERAGE_UNPROVEN
    klass = verdict.get("continuity_class")
    if klass in (CONTIGUOUS, EXPECTED_MARKET_BREAK):
        # every expected slot is accounted for, or the venue was closed and
        # none was expected -- both are complete coverage.
        return None
    return LIFECYCLE_SLOT_COVERAGE_UNPROVEN


def fvg_lifecycle(candles: list, direction: str, gap: dict,
                  tf_minutes=None) -> dict:
    """AS-OF-T life of ONE plain-FVG occurrence, derived from candles alone.

    DERIVED, NOT CARRIED. Nothing is stored across scans, so this is
    deterministic, replayable, and immune to a missed scan -- the architectural
    pattern `order_block_extractor.track_mitigation` already proves for a
    DIFFERENT object. Its states and thresholds are deliberately NOT imported:
    an order block is a body, an FVG is unvisited space, and Unit 6 does not
    transplant one object's doctrine onto another.

    ORTHOGONAL FACTS, NOT A STATE MACHINE. An occurrence may truthfully be
    entered AND fully_traversed AND NOT retired. Collapsing these into one
    mutually-exclusive enum would erase history.
    """
    lo, hi = gap.get("low"), gap.get("high")
    out = {
        "entered": False,
        "fully_traversed": False,
        "close_through_far_boundary": False,
        "retired": False,
        "retirement_reason": None,
        "retirement_bar": None,
        "bars_since_formation": 0,
        "lifecycle_evaluable": True,
        "lifecycle_reason": None,
    }
    idx = gap.get("index")
    if lo is None or hi is None or not isinstance(idx, int) or isinstance(idx, bool) \
            or idx + 3 > len(candles or []):
        out["lifecycle_evaluable"] = False
        out["lifecycle_reason"] = LIFECYCLE_NOT_LOCATABLE
        return out

    after = _bars_after_formation(candles, gap)
    out["bars_since_formation"] = len(after)
    if not after:
        # NEWLY FORMED. The occurrence IS locatable and simply has no later
        # bars yet: a fully evaluable lifecycle whose answer is "nothing has
        # happened to it". Distinct from "we could not look".
        return out

    # RETIREMENT EVIDENCE MUST BE AUTHORITATIVE.
    #
    # `build_price_level` locates zones from `recent_candles` with the FORMING
    # bucket included (CONTINUITY-2F, deliberately, so a realtime opportunity
    # stays visible). A forming bar's close is still moving and may not
    # permanently kill an occurrence, so retirement is judged on SETTLED bars
    # only -- through `_settled_only`, the 2G metadata already on the candles.
    # There is no second completeness detector here and there must not be one.
    # EXPECTED-SLOT COVERAGE, from the completion bar forward. Asked BEFORE any
    # label is trusted: a missing slot invalidates what the surviving labels
    # appear to say.
    coverage = _lifecycle_slot_coverage(candles[idx + 2:], tf_minutes)
    if coverage:
        out["lifecycle_evaluable"] = False
        out["lifecycle_reason"] = coverage
        return out

    settled_after = _settled_only(after)
    if not settled_after and not any(c.get("temporal_status") for c in after):
        # WE COULD NOT LOOK. No bar after formation carries a temporal label at
        # all, so we cannot tell settled evidence from forming evidence. Unknown
        # authority is not clean authority.
        out["lifecycle_evaluable"] = False
        out["lifecycle_reason"] = LIFECYCLE_NO_SETTLED_AUTHORITY
        return out
    # WE LOOKED AND NOTHING SETTLED HAS HAPPENED YET. A run of labelled bars
    # that are all forming is KNOWLEDGE, not ignorance: the venue has not closed
    # one of them, so no settled close can have gone through the gap. Treating
    # that as unevaluable conflated "we know nothing settled occurred" with "we
    # do not know what occurred", and refused every occurrence whose only later
    # bucket was the live one -- caught by the CONTINUITY-2F real-tape cases,
    # where a 14:50 occurrence was denied because 14:55 was still forming.

    # OBSERVATIONS may use every bar the engine held -- they are facts about
    # what was seen, and they carry no execution authority of their own.
    out["entered"] = any(c["low"] <= hi and c["high"] >= lo for c in after)
    out["fully_traversed"] = (min(c["low"] for c in after) <= lo
                              and max(c["high"] for c in after) >= hi)

    # THE FAR BOUNDARY, AGAINST THE INTENDED DIRECTION, on settled evidence.
    for c in settled_after:
        close = c.get("close")
        if close is None:
            continue
        if (direction == "bullish" and close < lo) or \
           (direction == "bearish" and close > hi):
            out["close_through_far_boundary"] = True
            # STICKY, AND ATTRIBUTABLE. The FIRST such close is the retirement
            # event; a later return by price changes the geometric relation and
            # may never resurrect the occurrence.
            out["retired"] = True
            out["retirement_reason"] = RETIREMENT_CLOSE_THROUGH
            out["retirement_bar"] = c.get("timestamp")
            break
    return out


def fvg_occurrences(candles: list, direction: str, tf_minutes: int = None,
                    *, contract=None) -> list:
    """EVERY observed plain-FVG occurrence, newest first, with identity and life.

    OCCURRENCE EXISTED != OCCURRENCE CURRENTLY LAWFUL. This is the observed
    inventory, retired members included and marked. Erasing them would destroy
    history a consumer is entitled to see, and a later theorem (what inversion
    is, which occurrence an IFVG binds to) may need precisely the occurrences
    plain-FVG doctrine has retired.

    `execution_eligible` is stated PER OCCURRENCE and fails closed on three
    separate grounds: no provable identity, no evaluable lifecycle, or a
    completed retirement.
    """
    out = []
    for g in find_fvgs(candles, direction, tf_minutes):
        idx = g.get("index")
        c3_row = None
        if isinstance(idx, int) and not isinstance(idx, bool) \
                and 0 <= idx + 2 < len(candles or []):
            c3_row = candles[idx + 2]
        # PLAIN-FVG-EXECUTABLE-REPRESENTATION-1. `c3_row` is built above and
        # carries no contract: canonical candle rows do not record one, so
        # `row_contract` could never derive identity and EVERY plain FVG on
        # EVERY timeframe came back anonymous -- 45 occurrences, 0 identities,
        # measured on the 2026-08-21 tape. The contract is threaded from the
        # caller that legitimately knows it. When it is absent, identity stays
        # None and the occurrence stays execution-ineligible: a contract is
        # never manufactured here, because inventing provenance would relabel
        # foreign evidence as production evidence.
        occ_id = fvg_occurrence_id(tf_minutes, direction, dict(g, c3_row=c3_row),
                                   contract=contract)
        life = fvg_lifecycle(candles, direction, g, tf_minutes)
        if occ_id is None:
            reason = "occurrence_identity_unprovable"
        elif not life["lifecycle_evaluable"]:
            reason = life["lifecycle_reason"]
        elif life["retired"]:
            reason = life["retirement_reason"]
        else:
            reason = None
        out.append({
            **g,
            "occurrence_id": occ_id,
            "identity_evaluable": occ_id is not None,
            "direction": direction,
            "source_tf_minutes": tf_minutes,
            **life,
            "execution_eligible": reason is None,
            "execution_ineligible_reason": reason,
        })
    return out


def fvg_execution_instances(candles: list, direction: str,
                            tf_minutes: int = None, *, contract=None) -> list:
    """Every occurrence, each carrying its OWN temporal authority and composite.

    STEP 4B.12 §6 UNIT 6 — CONTINUITY-2F, EVALUATED PER OCCURRENCE.

    `build_price_level` runs 2F once for the FAMILY zone: locate twice, compare
    execution geometry, refuse if the forming bucket authored it. That verdict
    belongs to whichever occurrence the family view happened to present, and
    applying it to every occurrence would let one gap's temporal defect condemn
    another gap that is perfectly settled -- or, worse, let one gap's clean
    verdict launder another's.

    So the same theorem is run occurrence-exactly: build the inventory from the
    realtime series and again from settled bars only, then match BY
    `occurrence_id`. An occurrence whose geometry is identical in both arms did
    not depend on the forming bucket. One that is absent from the settled arm,
    or whose bounds move, did.

    Matching is by identity, never by position or price -- re-searching for
    "the newest" or "the nearest" in the settled arm would compare two
    different market objects and call the result a temporal verdict.

    FOUR INDEPENDENT AUTHORITIES compose here, and every witness is preserved
    beside the composite so a refusal can always name its author.
    """
    realtime = fvg_occurrences(candles, direction, tf_minutes, contract=contract)
    settled_by_id = {o["occurrence_id"]: o
                     for o in fvg_occurrences(_settled_only(candles), direction,
                                              tf_minutes, contract=contract)
                     if o.get("occurrence_id")}
    out = []
    for occ in realtime:
        oid = occ.get("occurrence_id")
        twin = settled_by_id.get(oid)
        temporal_ok = bool(twin) and (twin["low"], twin["high"]) == (occ["low"],
                                                                    occ["high"])
        reason = occ.get("execution_ineligible_reason")
        if occ.get("execution_eligible") and not temporal_ok:
            reason = ("TOOL_NOT_SETTLED: zone geometry depends on a forming "
                      "bucket")
        out.append({
            **occ,
            "temporal_class": "settled" if temporal_ok else "provisional",
            "temporal_execution_eligible": temporal_ok,
            # COMPOSITE: identity AND lifecycle AND not-retired AND temporal.
            # The first three already live in `execution_eligible` on `occ`.
            "execution_eligible": bool(occ.get("execution_eligible")) and temporal_ok,
            "execution_ineligible_reason": reason,
        })
    return out


def lawful_fvg_candidates(candles: list, direction: str,
                          tf_minutes: int = None) -> list:
    """Only the occurrences that may currently author execution.

    An empty set is a legitimate market result and is never filled in.
    """
    return [o for o in fvg_occurrences(candles, direction, tf_minutes)
            if o["execution_eligible"]]


def _find_fvg(candles: list, direction: str, tf_minutes: int = None) -> tuple | None:
    """Most recent 3-candle imbalance gap as (zone_low, zone_high), or None.

    STEP 4B.6 §1: `tf_minutes` is threaded from `source_tf`, which the caller
    already had in scope. Without it this path -- the one that builds the
    TOOLBOX ZONE Terra will eventually select -- was the last place where a
    filtered list could still manufacture market adjacency.

    STEP 4B.12 §6 UNIT 6 SCOPE: this function is now the IFVG / opening_fvg
    path ONLY, and its behaviour is deliberately unchanged. Unit 6 governs
    PLAIN FVG. A plain-FVG occurrence being retired means it is no longer lawful
    AS A PLAIN FVG SETUP -- it does not mean the occurrence stopped existing,
    and a future inversion theorem may need exactly such an occurrence. Applying
    plain-FVG retirement here would delete the evidence Unit 7 has to reason
    about, so it is not applied.
    """
    gaps = find_fvgs(candles, direction, tf_minutes)
    if not gaps:
        return None
    g = gaps[0]
    return g["low"], g["high"]


def _find_ob(candles: list, direction: str) -> tuple | None:
    """
    Most recent opposite-direction candle body as order block.
    Returns (zone_low, zone_high, invalidation_level) or None.
    Invalidation = the whole candle's extreme (low for bullish OB, high for bearish OB).
    """
    if len(candles) < 2:
        return None
    opp = "bearish" if direction == "bullish" else "bullish"
    for c in reversed(candles[:-1]):
        if c["direction"] == opp:
            body_lo = round(min(c["open"], c["close"]), 2)
            body_hi = round(max(c["open"], c["close"]), 2)
            if body_hi <= body_lo:
                continue  # skip neutral/doji candles
            inv = c["low"] if direction == "bullish" else c["high"]
            return body_lo, body_hi, inv
    return None


def _find_ote(struct: dict, direction: str) -> tuple | None:
    """
    OTE retracement zone from structure swing high/low.
    Bullish: 62–79% pullback from swing high.
    Bearish: 62–79% bounce from swing low.
    Returns (zone_low, zone_high, invalidation_level) or None.
    """
    sh = struct.get("last_swing_high")
    sl = struct.get("last_swing_low")
    if sh is None or sl is None:
        return None
    rng = sh - sl
    if rng <= 0:
        return None
    if direction == "bullish":
        return sh - rng * _OTE_HIGH_PCT, sh - rng * _OTE_LOW_PCT, sl
    return sl + rng * _OTE_LOW_PCT, sl + rng * _OTE_HIGH_PCT, sh


def _find_swing_zone(struct: dict, candles: list, direction: str) -> tuple | None:
    """
    Small zone around the swept swing level.
    Used as fallback for breaker and primary for range_break_retest.
    Bullish → zone around last_swing_LOW (the swept low).
    Bearish → zone around last_swing_HIGH (the swept high).
    Returns (zone_low, zone_high, invalidation_level) or None.
    """
    sh  = struct.get("last_swing_high")
    sl  = struct.get("last_swing_low")
    tol = _avg_range(candles) * 0.35

    if direction == "bullish" and sl is not None:
        return sl - tol, sl + tol, sl - tol * 2.5
    if direction == "bearish" and sh is not None:
        return sh - tol, sh + tol, sh + tol * 2.5
    return None


def _ob_block_run(candles: list, struct: dict, direction: str,
                  max_run: int = 12) -> list:
    """The unbroken run of opposite-direction candles immediately preceding the
    structure swing price rejected from. Returns the run oldest-first, or [].

    Anchoring to the swing is the whole point. `_find_ob` walks back from the NEWEST
    candle and takes the first opposite body it meets, which during a retracement
    lands inside the retracement itself — producing an "order block" price has
    already traded through, with an invalidation on the wrong side of entry.

    Bearish setup -> run of bullish candles before the last swing HIGH.
    Bullish setup -> run of bearish candles before the last swing LOW.
    """
    anchor = (struct.get("last_swing_high") if direction == "bearish"
              else struct.get("last_swing_low"))
    if anchor is None or not candles:
        return []
    key = "high" if direction == "bearish" else "low"
    # The swing must correspond to a real candle extreme; one tick of tolerance.
    idx = next((i for i in range(len(candles) - 1, -1, -1)
                if abs(float(candles[i][key]) - float(anchor)) <= _OB_ANCHOR_TOL), None)
    if idx is None:
        return []   # swing not found among these candles -> fail closed
    opp = "bullish" if direction == "bearish" else "bearish"
    run = []
    for c in reversed(candles[:idx]):
        if c.get("direction") != opp or len(run) >= max_run:
            break
        run.append(c)
    return list(reversed(run))


def _find_ob_block(candles: list, struct: dict, direction: str) -> tuple | None:
    """Multi-candle order block spanning the displacement-origin run.

    Returns (zone_low, zone_high, invalidation_level) where the zone spans the run's
    BODIES and invalidation is the run's extreme. The mean threshold (50% of the
    block) falls out of _make_zone's midpoint.
    """
    run = _ob_block_run(candles, struct, direction)
    if not run:
        return None
    body_lo = round(min(min(c["open"], c["close"]) for c in run), 2)
    body_hi = round(max(max(c["open"], c["close"]) for c in run), 2)
    if body_hi <= body_lo:
        return None
    inv = (max(c["high"] for c in run) if direction == "bearish"
           else min(c["low"] for c in run))
    return body_lo, body_hi, inv


def _find_breaker_zone(candles: list, struct: dict, direction: str) -> tuple | None:
    """
    Breaker zone: body of the reversal/failure candle (same direction as intended trade).
    For bullish breaker: most recent bullish candle body (the reversal after the sweep).
    For bearish breaker: most recent bearish candle body.
    Falls back to swept swing level zone if no same-direction candle found.
    Returns (zone_low, zone_high, invalidation_level) or None.
    """
    # Primary: same-direction reversal candle body (the failure/reclaim candle)
    for c in reversed(candles[:-1]):
        if c["direction"] == direction:
            body_lo = round(min(c["open"], c["close"]), 2)
            body_hi = round(max(c["open"], c["close"]), 2)
            if body_hi <= body_lo:
                continue
            inv = c["low"] if direction == "bullish" else c["high"]
            return body_lo, body_hi, inv
    # Fallback: swept swing level zone
    return _find_swing_zone(struct, candles, direction)


def _find_mss_level_zone(struct: dict, candles: list, direction: str) -> tuple | None:
    """
    MSS Retest zone: built around the BROKEN structure level.
    Bullish: price broke ABOVE last_swing_HIGH → retest that broken high from above.
    Bearish: price broke BELOW last_swing_LOW  → retest that broken low from below.
    Distinct from breaker: uses structural breakout level, not a candle body.
    Returns (zone_low, zone_high, invalidation_level) or None.
    """
    sh  = struct.get("last_swing_high")
    sl  = struct.get("last_swing_low")
    tol = _avg_range(candles) * 0.35

    if direction == "bullish" and sh is not None:
        # Bullish BOS broke above swing_high — retest that level as new support
        return sh - tol, sh + tol, sh - tol * 2.5
    if direction == "bearish" and sl is not None:
        # Bearish BOS broke below swing_low — retest that level as new resistance
        return sl - tol, sl + tol, sl + tol * 2.5
    return None


def _find_rejection_zone(struct: dict, candles: list, direction: str) -> tuple | None:
    """
    Rejection block zone built from the largest-wick candle in recent data.
    Zone = body of that candle; invalidation = wick extreme + small buffer.
    Returns (zone_low, zone_high, invalidation_level) or None.
    """
    recent = candles[-5:] if candles else []
    if not recent:
        return None

    if direction == "bullish":
        rej    = max(recent, key=lambda c: c.get("lower_wick", 0))
        body_lo = round(min(rej["open"], rej["close"]), 2)
        body_hi = round(max(rej["open"], rej["close"]), 2)
        inv     = round(rej["low"] - _avg_range(recent) * 0.1, 2)
    else:
        rej    = max(recent, key=lambda c: c.get("upper_wick", 0))
        body_lo = round(min(rej["open"], rej["close"]), 2)
        body_hi = round(max(rej["open"], rej["close"]), 2)
        inv     = round(rej["high"] + _avg_range(recent) * 0.1, 2)

    if body_hi <= body_lo:
        return None
    return body_lo, body_hi, inv


# ── Zone dispatcher ───────────────────────────────────────────────────────────

def _build_zone_for_family(
    fam: str, direction: str,
    struct: dict, liq: dict, candles: list,
    source_tf: str, current: float | None
) -> dict:
    # RELATION-TRUTH: one adaptive touch tolerance per evaluation, derived
    # from the same candles the zones themselves are built from.
    touch_tol = _touch_tolerance(candles)

    if fam == "fvg":
        # STEP 4B.12 §6 UNIT 6 — DISCLOSE THE INVENTORY; SUBSTITUTE NOTHING.
        #
        # NO SUBSTITUTION is not a new rule -- `build_price_level` already
        # states it: "an ineligible zone is returned as itself, marked
        # ineligible. It is never swapped for an older gap, a nearer level, a
        # tighter invalidation or another timeframe's zone." An earlier version
        # of this branch walked the eligible occurrences and returned the first,
        # which is precisely the swap that doctrine forbids, dressed as a repair.
        #
        # So the NEWEST occurrence still authors the geometry, exactly as
        # before. What changes is that it now says WHICH occurrence it is,
        # whether that occurrence is still lawful, and what else exists.
        # Choosing among lawful occurrences belongs to the selector, not here.
        _tfm = tf_minutes_strict(source_tf, where="fvg zone")
        occurrences = fvg_occurrences(candles, direction, _tfm)
        if not occurrences:
            return _no_zone(direction, current)
        newest = occurrences[0]
        lawful = [o for o in occurrences if o["execution_eligible"]]
        zl, zh = newest["low"], newest["high"]
        inv = zl if direction == "bullish" else zh
        zone = _make_zone("fvg_zone", direction, zl, zh, inv, current,
                          source_tf, touch_tol, occurrence=newest)
        # OBSERVED INVENTORY vs LAWFUL SET — named apart, because "this gap
        # existed" and "this gap may author a trade" are different claims.
        zone["fvg_occurrences"] = [
            {k: o.get(k) for k in ("occurrence_id", "low", "high", "size",
                                   "c1_time", "c3_time", "entered",
                                   "fully_traversed", "retired",
                                   "execution_eligible",
                                   "execution_ineligible_reason")}
            for o in occurrences]
        zone["lawful_fvg_candidates"] = [
            {k: o.get(k) for k in ("occurrence_id", "low", "high", "size",
                                   "c1_time", "c3_time")}
            for o in lawful]
        zone["lawful_candidate_count"] = len(lawful)
        zone["observed_occurrence_count"] = len(occurrences)
        zone["occurrence_execution_eligible"] = bool(newest["execution_eligible"])
        zone["occurrence_ineligible_reason"] = newest["execution_ineligible_reason"]
        # >1 lawful occurrence means the trade object is genuinely ambiguous and
        # mechanics has no doctrine that resolves it. The zone stays VISIBLE and
        # is marked selection-required; it may not author execution until a
        # selector names the exact occurrence it means.
        zone["occurrence_selection_required"] = len(lawful) > 1
        return zone

    if fam in ("ifvg", "opening_fvg"):
        # UNIT 6 DELIBERATELY DOES NOT TOUCH THESE. Retirement is a PLAIN-FVG
        # predicate; what inversion is, what makes a gap an opening gap, and
        # which occurrence each binds to are unwritten theorems. Filtering here
        # with plain-FVG eligibility could delete exactly the occurrence a later
        # unit must reason about. Behaviour is byte-identical to a1f2046.
        result = _find_fvg(candles, direction,
                           tf_minutes_strict(source_tf, where=f"{fam} zone"))
        if result:
            zl, zh = result
            inv = zl if direction == "bullish" else zh
            return _make_zone(f"{fam}_zone", direction, zl, zh, inv, current,
                              source_tf, touch_tol)

    if fam in ("order_block", "opening_order_block"):
        result = _find_ob(candles, direction)
        if result:
            zl, zh, inv = result
            return _make_zone(f"{fam}_zone", direction, zl, zh, inv, current, source_tf, touch_tol)

    if fam == "breaker":
        result = _find_breaker_zone(candles, struct, direction)
        if result:
            zl, zh, inv = result
            return _make_zone("breaker_zone", direction, zl, zh, inv, current, source_tf, touch_tol)

    if fam == "rejection_block":
        result = _find_rejection_zone(struct, candles, direction)
        if result:
            zl, zh, inv = result
            return _make_zone("rejection_block_zone", direction, zl, zh, inv, current, source_tf, touch_tol)

    if fam in ("ote_retracement", "ote_after_reclaim"):
        result = _find_ote(struct, direction)
        if result:
            zl, zh, inv = result
            return _make_zone("ote_zone", direction, zl, zh, inv, current, source_tf, touch_tol)

    if fam == "mss_retest":
        result = _find_mss_level_zone(struct, candles, direction)
        if result:
            zl, zh, inv = result
            return _make_zone("mss_retest_zone", direction, zl, zh, inv, current, source_tf, touch_tol)

    if fam == "range_break_retest":
        buy_side  = liq.get("nearest_buy_side_liquidity")
        sell_side = liq.get("nearest_sell_side_liquidity")
        ref       = buy_side if direction == "bullish" else sell_side
        if ref is not None:
            tol = _avg_range(candles) * 0.35
            zl  = ref - tol
            zh  = ref + tol
            inv = (ref - tol * 2.5) if direction == "bullish" else (ref + tol * 2.5)
            return _make_zone("range_break_retest_zone", direction, zl, zh, inv, current, source_tf, touch_tol)
        # Fallback to swing zone if no liquidity level available
        result = _find_swing_zone(struct, candles, direction)
        if result:
            zl, zh, inv = result
            return _make_zone("range_break_retest_zone", direction, zl, zh, inv, current, source_tf, touch_tol)

    return _no_zone(direction, current)


# ── Public entry point ────────────────────────────────────────────────────────

#: The fields that can become an ORDER: the zone the entry sits in, the level
#: the stop is derived from, and which series produced them. Provenance and
#: display fields are deliberately excluded -- they may differ without the
#: geometry differing.
EXECUTION_GEOMETRY_FIELDS = ("level_type", "zone_low", "zone_high",
                             "invalidation_level", "source_tf")


def _execution_geometry(zone: dict) -> tuple:
    return tuple((zone or {}).get(k) for k in EXECUTION_GEOMETRY_FIELDS)


def _settled_only(candles: list) -> list:
    """CONTINUITY-2F. Uses the 2G temporal metadata already on the candles --
    there is no second completeness detector and there must not be one.
    `unknown` is NOT treated as settled here: this decides whether geometry may
    author a STOP, and a bar whose settlement was never recorded cannot support
    that claim. (2D's opposite policy governs whether structure is DELETED,
    which is a different question.)"""
    return [c for c in candles or [] if c.get("temporal_status") == "settled"]


def _locate_zone(fam, direction, snapshot, current, settled_only: bool) -> dict:
    tfs        = snapshot.get("timeframes", {})
    struct_all = snapshot.get("structure",  {})
    liq_all    = snapshot.get("liquidity",  {})
    allowed_tfs = _allowed_source_tfs(snapshot.get("symbol", ""))

    for tf in _FAMILY_TF_PRIORITY.get(fam, ["15m", "5m", "3m", "1m"]):
        if tf not in allowed_tfs:      # source-timeframe policy (set only, not order)
            continue
        # PHASE 4A (2026-08-12) — THIS CONSUMER'S OWN WINDOW, STATED EXPLICITLY.
        # The canonical snapshot used to retain exactly 5 bars per timeframe, so
        # every consumer silently inherited the Brain's old presentation policy.
        # The store now retains a wider canonical history; zone geometry must not
        # move because of that, so the five-bar horizon this detector was
        # measured and fingerprinted against is declared HERE rather than
        # depending on how much the store happens to keep.
        retained = tfs.get(tf, {}).get("recent_candles") or []
        # STEP 4B.12 §6 UNIT 6 — F-5: DISCOVERY HORIZON IS NOT A PRESENTATION
        # HORIZON.
        #
        # Every family read `retained[-5:]`. That five-bar slice has no market
        # theorem behind it: the constant is documented as the horizon "the
        # current brain-contract fingerprint was taken against", pinned so a
        # change to canonical retention could not move execution geometry. A
        # fingerprint proves behavioural stability, not market correctness --
        # and PHASE 4A in `snapshot_builder` had already diagnosed this same
        # five-bar retention as blindness when it governed the store ("Terra was
        # asked to find a discretionary entry through a four-minute window"),
        # widened it everywhere else, and left it in force on the one path that
        # authors a stop.
        #
        # Measured on the venue tape: 399 plain-FVG occurrences that were still
        # lawful under the certified retirement theorem were invisible to
        # execution SOLELY because their formation fell outside the slice --
        # some by a single bar. A 15m gap at five bars exists; at six it does
        # not, having filled, expired or violated nothing.
        #
        # PLAIN FVG ONLY. `ifvg`, `opening_fvg`, order blocks and every other
        # family keep the five-bar window byte-for-byte: their occurrence
        # theorems are unwritten, and widening a horizon for a family whose
        # candidate semantics nobody has proven would be inventing doctrine.
        if fam == "fvg":
            candles = retained
        else:
            candles = retained[-_ZONE_LOOKBACK_BARS:]
        if settled_only:
            candles = _settled_only(candles)
        if not candles:
            continue
        struct = struct_all.get(tf, {})
        liq    = liq_all.get(tf, {})
        result = _build_zone_for_family(fam, direction, struct, liq, candles, tf, current)
        if result.get("level_type") != "no_zone":
            return result
    return _no_zone(direction, current)


def build_price_level(tool: str, snapshot: dict) -> dict:
    """
    Phase 1L — Price Level Detector.
    Returns the price zone and current-price relationship for the given tool.

    CONTINUITY-2F (2026-08-12) — WITNESS / AUTHORITY SPLIT.

    The zone is still located from `recent_candles`, forming bucket included, so
    a realtime opportunity stays VISIBLE to the Toolbox and to Terra. What is new
    is that the zone now declares whether its geometry could author a stop.

    Measured on the committed Aug-11 venue tape, forming bucket present vs
    excluded, geometry moved on EIGHT tool families and `invalidation_level`
    moved by as much as 20.5 points against a 40-point ceiling:

        14:42Z bearish_order_block   invalidation 29757.50 -> 29778.00
        14:42Z bullish_breaker       invalidation 29740.25 -> 29752.00
        14:40Z bullish_order_block   invalidation 29742.50 -> 29733.00

    Eligibility is decided by COMPARISON, not by reasoning about each detector's
    internals: locate the zone twice -- once from the realtime series, once from
    settled candles only -- and if the execution geometry is identical, the
    forming bucket contributed nothing and the zone may author a stop. This is
    family-agnostic by construction, so a new tool family cannot silently opt
    out of the contract, and it needs no per-detector theory of which candle
    index matters.

    NOTE ON ORDER BLOCKS: an earlier audit called `_find_ob`'s `candles[:-1]`
    slice "safe by coincidence" because it excludes the newest bar. That was
    WRONG and this tape disproves it -- order blocks were the MOST affected
    family (23 + 18 scans). Excluding the last bar does not exclude the forming
    bar's influence; appending it shifts WHICH candle is excluded, so the block
    moves. Coincidence was never protection.

    NO SUBSTITUTION: an ineligible zone is returned as itself, marked
    ineligible. It is never swapped for an older gap, a nearer level, a tighter
    invalidation or another timeframe's zone. A veto is a veto; the Toolbox
    validates, it does not quietly trade a different setup.
    """
    fam       = _family(tool)
    direction = "bullish" if tool.startswith("bullish_") else "bearish"
    current   = _current_price(snapshot)
    session   = snapshot.get("session", "")

    # Opening tools are session-gated — no zone outside ny_open
    if fam in ("opening_fvg", "opening_order_block") and session != "ny_open":
        return _no_zone(direction, current)

    realtime = _locate_zone(fam, direction, snapshot, current, settled_only=False)
    settled  = _locate_zone(fam, direction, snapshot, current, settled_only=True)

    eligible = _execution_geometry(realtime) == _execution_geometry(settled)
    realtime["temporal_class"] = "settled" if eligible else "provisional"
    # CONTINUITY-2F's OWN VERDICT, published separately and never overwritten.
    #
    # STEP 4B.12 §6 UNIT 6 gives `execution_eligible` a SECOND author: whether
    # the occurrence behind the geometry is a lawful plain-FVG setup. Once two
    # independent authorities can veto one field, that field can no longer
    # answer "what did 2F decide" -- and a zone whose geometry is fully settled
    # can read `execution_eligible: False` for a reason that has nothing to do
    # with temporal authority. Keeping 2F's answer addressable is what lets both
    # theorems stay separately provable.
    realtime["temporal_execution_eligible"] = bool(eligible)
    # TOOLBOX-EXECUTION-PRICE-1 — the location fields are re-answered from
    # the fresh sided quote HERE, after `_execution_geometry` has already
    # been compared on both arms. Geometry and 2F are settled facts by this
    # point and share no field with LOCATION_FIELDS.
    _reanchor_location(realtime, snapshot, direction)
    realtime["execution_eligible"] = bool(eligible)
    realtime["settled_geometry"] = dict(zip(EXECUTION_GEOMETRY_FIELDS,
                                            _execution_geometry(settled)))
    if not eligible:
        realtime["execution_ineligible_reason"] = (
            "TOOL_NOT_SETTLED: zone geometry depends on a forming bucket")

    # STEP 4B.12 §6 UNIT 6 — OCCURRENCE AUTHORITY, FOR PLAIN FVG ONLY.
    #
    # A SECOND, INDEPENDENT veto alongside 2F's temporal one. 2F asks whether
    # the geometry rests on a forming bucket; this asks whether the OCCURRENCE
    # that geometry belongs to is still a lawful plain-FVG setup at all. Both
    # must pass, and neither substitutes a different zone -- an ineligible zone
    # is returned as itself with its reason.
    if fam == "fvg" and realtime.get("level_type") == "fvg_zone":
        if realtime.get("occurrence_selection_required"):
            realtime["execution_eligible"] = False
            realtime.setdefault(
                "execution_ineligible_reason",
                "FVG_OCCURRENCE_SELECTION_REQUIRED: more than one lawful "
                "occurrence exists and mechanics does not choose between them")
        elif realtime.get("occurrence_execution_eligible") is False:
            realtime["execution_eligible"] = False
            realtime.setdefault(
                "execution_ineligible_reason",
                f"FVG_OCCURRENCE_NOT_LAWFUL: "
                f"{realtime.get('occurrence_ineligible_reason')}")
    return realtime


# ── PROTECTED-LEVEL-REJECTION-AGGRESSIVE-1 (2026-08-20) ───────────────────────
#
# `_find_rejection_zone` takes `max(recent, key=upper_wick)` over five bars and
# calls that candle's BODY the zone. It is anchored to nothing. On 2026-08-20 it
# published a 15m "bearish rejection block" at 29350.25-29367.75 while the level
# it was nominally rejecting from sat at 29470.25 -- a hundred points away, and
# on the wrong side of the market.
#
# Two defects in one function:
#
#   NO ANCHOR    a big wick is not a rejection. A rejection is a failure AT
#                something. Without a structural referent, every candle in a
#                two-sided range qualifies: 13 candidates in two hours on the
#                Aug-20 tape, against 1 once an anchor is required.
#   WRONG ZONE   an ICT bearish rejection block is the WICK region -- body top
#                to wick extreme -- not the body. The body is the part price
#                did NOT reject from.
#
# This is the anchored variant. It does not replace the generic detector; it
# answers a different question: given a protected level that already has
# authority, which settled candle created the rejection, and what is its zone?
#
# FRACTAL-TIMEFRAME LAW (operator ruling, 2026-08-20). One market extreme
# appears on several timeframes. Those are RESOLUTIONS of one event, not
# competing setups. The protected swing owns the LEVEL; the finest allowed
# settled candle that prints that extreme AND independently expresses the
# rejection owns the GEOMETRY. Both provenances travel together, and coarser
# candles containing the same extreme are witnesses, never duplicate blocks.
#
# Selection is by RESOLUTION, never by which timeframe yields a tighter stop.
# On the Aug-20 tape the two criteria happen to agree and the answer is
# over-determined: of the allowed source timeframes only 3m expresses the
# rejection at all -- the 5m and 15m bars containing 29470.25 closed BULLISH
# with bodies larger than their wicks.

#: Only a swing with real structural standing may anchor a rejection block.
#: `transition` and `execution` swings are interior chop: on the Aug-20 tape the
#: 5m active_leg high held ONE level for the whole session (29470.25) while the
#: 3m/1m registers churned through four or more apiece.
REJECTION_ANCHOR_ROLES = ("context", "active_leg")

#: How near a creating wick must come to the protected level to be ITS
#: rejection. Frozen at 15.00 points by operator ruling 2026-08-20, measured on
#: the APPROACH side. This associates a creating candle with a level; it is NOT
#: how a later retest is judged -- once the block exists, location is measured
#: against the block and its mean threshold, not against the level.
PROTECTED_LEVEL_PROXIMITY_POINTS = 15.00

NO_ANCHOR = "NO_QUALIFYING_STRUCTURAL_LOCATION"
NO_CREATING_CANDLE = "NO_SETTLED_CANDLE_EXPRESSES_THE_REJECTION"


def _expresses_rejection(candle: dict, direction: str) -> bool:
    """Does this candle EXPRESS a rejection, or merely contain one?

    The wick must dominate the body. A bar that ran to the extreme and closed
    near it did not reject anything -- it accepted. This is what disqualifies
    the Aug-20 5m and 15m bars: both contain 29470.25, both closed bullish with
    bodies larger than their wicks.
    """
    body = abs(float(candle.get("body_size") or 0.0))
    wick = float(candle.get("upper_wick" if direction == "bearish"
                            else "lower_wick") or 0.0)
    return wick > body


def _rejection_zone_from(candle: dict, direction: str) -> tuple:
    """The WICK region. `(zone_low, zone_high, mean_threshold)`."""
    o, c = float(candle["open"]), float(candle["close"])
    if direction == "bearish":
        lo, hi = round(max(o, c), 2), round(float(candle["high"]), 2)
    else:
        lo, hi = round(float(candle["low"]), 2), round(min(o, c), 2)
    return lo, hi, round((lo + hi) / 2, 3)


def anchored_rejection_block(snapshot: dict, direction: str, *,
                             proximity_points: float = PROTECTED_LEVEL_PROXIMITY_POINTS
                             ) -> dict:
    """The rejection block that OWNS a canonical protected level. Never raises.

    Returns a block with both provenances, or a refusal naming what was absent.
    Mechanics supplies the object; whether it is the trade remains Luna's.
    """
    side = "highs" if direction == "bearish" else "lows"
    swings = (((snapshot or {}).get("protected_swings") or {})
              .get("by_timeframe") or {}).get(side) or {}
    if not isinstance(swings, dict):
        # A malformed registry is an ABSENT anchor, never a crash: this runs
        # inside the scan path and evidence must not break the organism.
        swings = {}
    # PRESENCE IS LIVENESS. `ProtectedSwingTracker` POPS a swing the moment a
    # close accepts through it, so a swing that is still registered has not been
    # violated. No `retired` flag is needed or exists.
    anchors = [(tf, rec) for tf, rec in swings.items()
               if isinstance(rec, dict) and rec.get("role") in REJECTION_ANCHOR_ROLES
               and rec.get("level") is not None]
    if not anchors:
        return {"available": False, "reason": NO_ANCHOR, "direction": direction}

    tfs = (snapshot or {}).get("timeframes") or {}
    allowed = _allowed_source_tfs((snapshot or {}).get("symbol", ""))
    # FINEST FIRST. The generic detector's coarse-first `_FAMILY_TF_PRIORITY`
    # answers "find me some rejection block"; once the level is known the
    # question is "which candle created THIS one", and the highest-resolution
    # canonical occurrence is the truthful answer.
    order = [tf for tf in ("1m", "3m", "5m", "15m") if tf in allowed]

    # PRECEDENCE. A candle that PRINTS the extreme is its rejection; the
    # proximity band is a fallback for a wick that came close without printing
    # it. Searching the band and resolution together let a 3m candle 14.75
    # points away outrank a 5m candle sitting exactly on the level -- which
    # inverts the law, since "actually prints the protected extreme" is the
    # primary criterion and resolution only breaks ties among equals.
    for max_gap in (0.0, float(proximity_points)):
      for anchor_tf, rec in sorted(anchors,
                                   key=lambda a: a[1].get("role") != "active_leg"):
        level = float(rec["level"])
        for tf in order:
            for candle in _settled_only((tfs.get(tf) or {}).get("recent_candles") or []):
                try:
                    extreme = float(candle["high"] if direction == "bearish"
                                    else candle["low"])
                except (KeyError, TypeError, ValueError):
                    continue
                gap = (level - extreme) if direction == "bearish" else (extreme - level)
                if not (0 <= gap <= max_gap):
                    continue
                if not _expresses_rejection(candle, direction):
                    continue          # contains the extreme, does not express it
                lo, hi, mt = _rejection_zone_from(candle, direction)
                if hi <= lo:
                    continue
                return {
                    "available": True, "reason": None, "direction": direction,
                    "anchor_swing_id": rec.get("swing_id"),
                    "anchor_tf": anchor_tf,
                    "anchor_role": rec.get("role"),
                    "anchor_level": level,
                    "anchor_basis": rec.get("basis"),
                    "rejection_block_tf": tf,
                    "creating_candle_timestamp": candle.get("timestamp"),
                    "zone_low": lo, "zone_high": hi, "mean_threshold": mt,
                    "wick_extreme": round(extreme, 2),
                    "distance_to_anchor": round(gap, 2),
                    # The stop is the LEVEL, not the wick: the thesis is wrong
                    # when price accepts through the structure, not when it
                    # ticks past the candle that rejected from it.
                    "invalidation_level": level,
                }
    return {"available": False, "reason": NO_CREATING_CANDLE, "direction": direction}


# ── PO3-REVERSAL-ORDER-BLOCK-1 (2026-08-20) ──────────────────────────────────
#
# The operator's primary expansion-entry model, and NOT a generic order block.
#
#   ACCUMULATION -> SELL-SIDE MANIPULATION -> BULLISH EXPANSION (change in state
#   of delivery) -> the prior manipulation run is RECLASSIFIED as the reversal
#   order block -> retracement into it -> distribution.
#
# THE CAUSALITY IS THE OBJECT. A terminal bearish run is NOT a bullish order
# block because it is bearish, or near a low, or because sell-side was taken. It
# becomes one only once opposite-direction expansion VIOLATES it and proves the
# state of delivery changed. Before that violation this function publishes
# nothing: an unvalidated candidate must never reach the Brain as an execution
# object.
#
# WHY A DISTINCT FAMILY. Adding generic `order_block` to the reversal playbooks
# would let ANY continuation block ride the reversal doctrine, and the causal
# requirement would become unenforceable -- exactly the universalisation the
# operator ruled against. `order_block` keeps `trend_continuation` untouched.
#
# GEOMETRY reuses `_ob_block_run` / `_find_ob_block`, which were already written
# and tested against real MNQ bars and never wired to production. Their run
# convention (unbroken opposing run before the structure swing, body envelope,
# run extreme) is preserved rather than reinvented.
#
# TWO EXTREMES, DELIBERATELY SEPARATE. The run's wick extreme is a GEOMETRY fact.
# The protected manipulation swing is the INVALIDATION AUTHORITY. They often
# nearly coincide; they are not the same claim, and both are published.

PO3_REVERSAL_OB_LEVEL_TYPE = "po3_reversal_order_block_zone"

NO_MANIPULATION = "NO_QUALIFYING_LIQUIDITY_MANIPULATION"
NO_TERMINAL_RUN = "NO_TERMINAL_OPPOSING_DELIVERY_RUN"
NOT_YET_VALIDATED = "AWAITING_EXPANSION_VIOLATION"

#: Which sweep proves the manipulation for each reversal direction.
_MANIPULATION_SIDE = {"bullish": "below_low", "bearish": "above_high"}


def _expansion_validates(snapshot: dict, tf: str) -> bool:
    """Did delivery actually change state, or did one candle merely close green?

    Reuses the canonical expansion authority rather than re-deriving it. Colour
    alone is never sufficient.
    """
    exp = ((snapshot or {}).get("expansion") or {}).get(tf) or {}
    return bool(exp.get("displacement_detected")) or \
        exp.get("state") in ("healthy_expansion", "mature_expansion")


def _violating_close(candles: list, run: list, direction: str,
                     body_lo: float, body_hi: float):
    """The first SETTLED candle after the run that CLOSES through its envelope.

    A close, not a wick: a wick through the run is a probe, not a change in the
    state of delivery. This is the event that reclassifies the run.
    """
    if not run:
        return None
    last_ts = run[-1].get("timestamp") or run[-1].get("t")
    seen_run_end = False
    for c in candles:
        ts = c.get("timestamp") or c.get("t")
        if not seen_run_end:
            seen_run_end = (ts == last_ts)
            continue
        if c.get("temporal_status") not in (None, "settled"):
            continue
        try:
            close = float(c["close"])
        except (KeyError, TypeError, ValueError):
            continue
        if (direction == "bullish" and close > body_hi) or \
           (direction == "bearish" and close < body_lo):
            return c
    return None


def _reversal_leg(candles: list, violator: dict, direction: str,
                  protected_level: float) -> dict:
    """The leg THIS reversal actually created, with both ends attributed.

    Bullish: protected manipulation LOW -> the high the validating expansion
    reached. Bearish mirrors. The 0.50 of that leg is the operator's third
    equilibrium reference; it is NOT OTE, which remains 0.62-0.79.

    The expansion extreme is measured from the validating candle forward, so the
    leg cannot borrow a high the reversal never produced.
    """
    try:
        vts = (violator or {}).get("timestamp") or (violator or {}).get("t")
        after, seen = [], False
        for c in candles or []:
            ts = c.get("timestamp") or c.get("t")
            if not seen:
                seen = (ts == vts)
            if seen:
                after.append(c)
        if not after:
            return {"retracement_leg": None,
                    "retracement_leg_reason": "no_expansion_bars"}
        if direction == "bullish":
            lo = round(float(protected_level), 2)
            hi = round(max(float(c["high"]) for c in after), 2)
        else:
            hi = round(float(protected_level), 2)
            lo = round(min(float(c["low"]) for c in after), 2)
        if hi <= lo:
            return {"retracement_leg": None,
                    "retracement_leg_reason": "degenerate_leg"}
        return {"retracement_leg": {
            "direction": direction,
            "low": lo, "high": hi,
            "equilibrium_50": round(lo + (hi - lo) * 0.5, 2),
            "low_source": ("protected_manipulation_swing" if direction == "bullish"
                           else "validated_expansion_extreme"),
            "high_source": ("validated_expansion_extreme" if direction == "bullish"
                            else "protected_manipulation_swing"),
            "expansion_from": vts,
            # OTE is a DIFFERENT structure and is restated here only so nobody
            # mistakes this 0.50 for it.
            "ote_low_pct": _OTE_LOW_PCT, "ote_high_pct": _OTE_HIGH_PCT},
            "retracement_leg_reason": None}
    except Exception:  # noqa: BLE001
        return {"retracement_leg": None, "retracement_leg_reason": "leg_unmeasurable"}


def po3_reversal_order_block(snapshot: dict, direction: str) -> dict:
    """The reversal order block, with its causal birth certificate. Never raises.

    Returns an established object, or a refusal naming exactly which part of the
    causal sequence is absent.
    """
    want_sweep = _MANIPULATION_SIDE.get(direction)
    if want_sweep is None:
        return {"available": False, "reason": NO_MANIPULATION, "direction": direction}
    tfs = (snapshot or {}).get("timeframes") or {}
    liq_all = (snapshot or {}).get("liquidity") or {}
    struct_all = (snapshot or {}).get("structure") or {}
    # A malformed block is an ABSENT fact, never a crash: this runs inside the
    # scan path and evidence must not break the organism.
    if not isinstance(tfs, dict):
        tfs = {}
    if not isinstance(liq_all, dict):
        liq_all = {}
    if not isinstance(struct_all, dict):
        struct_all = {}
    allowed = _allowed_source_tfs((snapshot or {}).get("symbol", ""))

    worst = {"available": False, "reason": NO_MANIPULATION, "direction": direction}
    for tf in [t for t in ("1m", "3m", "5m", "15m") if t in allowed]:
        liq = liq_all.get(tf) or {}
        if not (liq.get("sweep_detected") and liq.get("sweep_direction") == want_sweep):
            continue
        worst = {"available": False, "reason": NO_TERMINAL_RUN, "direction": direction}
        settled = _settled_only((tfs.get(tf) or {}).get("recent_candles") or [])
        run = _ob_block_run(settled, struct_all.get(tf, {}), direction)
        if not run:
            continue
        geometry = _find_ob_block(settled, struct_all.get(tf, {}), direction)
        if not geometry:
            continue
        body_lo, body_hi, run_extreme = geometry
        worst = {"available": False, "reason": NOT_YET_VALIDATED, "direction": direction}
        if not _expansion_validates(snapshot, tf):
            continue
        violator = _violating_close(settled, run, direction, body_lo, body_hi)
        if violator is None:
            continue

        prot = (((snapshot or {}).get("protected_swings") or {})
                .get("by_timeframe") or {}).get(
                    "lows" if direction == "bullish" else "highs") or {}
        swing = prot.get(tf) or next(iter(prot.values()), None) or {}
        # THE CAUSAL LEG. The 0.50 must belong to THIS reversal, not to whatever
        # swing pair the structure engine happens to be holding. Its anchors are
        # the two facts this object already owns: the protected manipulation
        # extreme, and the extreme the validating expansion reached.
        #
        # Selecting a different recent swing because its midpoint clusters more
        # prettily with the FVG or the block would be manufacturing confluence.
        # Confluence is OBSERVED, not manufactured.
        leg = _reversal_leg(settled, violator, direction,
                            swing.get("level", run_extreme))
        return {
            "available": True, "reason": None, "direction": direction,
            "level_type": PO3_REVERSAL_OB_LEVEL_TYPE,
            "source_tf": tf,
            # ── the causal birth certificate ──────────────────────────────
            "liquidity_side_taken": ("sell_side" if direction == "bullish"
                                     else "buy_side"),
            "manipulation_sweep_tf": tf,
            "manipulation_sweep_direction": liq.get("sweep_direction"),
            "manipulation_reclaimed": bool(liq.get("reclaim_detected")),
            "creating_run_start": run[0].get("timestamp") or run[0].get("t"),
            "creating_run_end": run[-1].get("timestamp") or run[-1].get("t"),
            "creating_run_length": len(run),
            "validation_timestamp": violator.get("timestamp") or violator.get("t"),
            "validation_basis": direction + "_expansion_close_through_run_envelope",
            "validation_close": round(float(violator["close"]), 2),
            # ── geometry ──────────────────────────────────────────────────
            "zone_low": body_lo, "zone_high": body_hi,
            "mean_threshold": round((body_lo + body_hi) / 2, 3),
            # GEOMETRY fact, distinct from the invalidation authority below.
            "run_extreme": round(float(run_extreme), 2),
            # ── invalidation authority ────────────────────────────────────
            "protected_swing_id": swing.get("swing_id"),
            "protected_swing_role": swing.get("role"),
            "invalidation_level": swing.get("level", run_extreme),
            # ── the causal retracement leg, and WHERE ITS ENDS CAME FROM ──
            **leg,
        }
    return worst
