"""PROPOSED CISD fact validator. SHADOW ONLY: no production module imports it.

Change in State of Delivery (CISD), as a pure fact over SETTLED buckets:

    bearish   the maximal run of consecutive bullish-delivery buckets
              (close > open) that ends at or before the bucket printing the
              selected extreme high; the FIRST later settled bucket whose close
              is strictly below that run's first open.
    bullish   the mirror (bearish-delivery run, close strictly above its open).

This module answers only "did that settled event occur, when did it become
knowable, and which exact event is it". It never grants direction, ownership,
transfer, campaign scope or entry authority: `AUTHORITY` is constant and
DISABLED/UNPROVEN. Which extreme is selected, timeframe precedence, boundary,
doji handling, revocation and the relationship to existing transfer and D3
gates are owner decisions (CISD_CONTRACT_PROPOSAL.md, appendix O1-O9); the
parameters below expose them without choosing them.

Determinism: the result is a function of (bars, timeframe, direction,
extreme_at, settled_through, policy) only. Bars at or after `settled_through`
are ignored, so prefix replay and a cold restart reproduce the same identity.
"""
from __future__ import annotations

import math
from datetime import datetime, timedelta, timezone

SCHEMA = "cisd_shadow/v1"
FAMILY = "cisd_body_open_break"
AUTHORITY = {"enabled": False, "status": "UNPROVEN",
             "reason": "owner_route_unratified"}
DIRECTIONS = ("bullish", "bearish")
DEFAULT_POLICY = {"boundary": "STRICT", "doji": "ENDS_RUN"}


def _instant(value):
    if isinstance(value, datetime):
        stamp = value
    elif isinstance(value, str):
        try:
            stamp = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
    else:
        return None
    if stamp.tzinfo is None:
        return None
    return stamp.astimezone(timezone.utc)


def _price(value):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    value = float(value)
    return value if math.isfinite(value) else None


def _iso(stamp):
    return stamp.isoformat()


def settled_buckets(bars_1m, minutes, settled_through):
    """Aggregate 1m bars into `minutes` buckets that are COMPLETE and SETTLED.

    A bucket is returned only when every constituent minute is present and its
    closing edge (open + minutes) is at or before `settled_through`. Malformed,
    duplicate, naive-time or non-finite input refuses the whole tape (None):
    a CISD is never computed from a tape the validator cannot read exactly.
    """
    edge = _instant(settled_through)
    if edge is None or not isinstance(minutes, int) or minutes < 1 or 60 % minutes:
        return None
    rows = {}
    for bar in bars_1m or ():
        if not isinstance(bar, dict):
            return None
        stamp = _instant(bar.get("timestamp"))
        prices = [_price(bar.get(k)) for k in ("open", "high", "low", "close")]
        if stamp is None or None in prices or stamp.second or stamp.microsecond:
            return None
        if stamp in rows:
            return None
        o, h, l, c = prices
        if not (l <= min(o, c) and h >= max(o, c)):
            return None
        rows[stamp] = (o, h, l, c)
    out = []
    starts = sorted({s - timedelta(minutes=s.minute % minutes) for s in rows})
    for start in starts:
        if start + timedelta(minutes=minutes) > edge:
            continue
        parts = [rows.get(start + timedelta(minutes=i)) for i in range(minutes)]
        if None in parts:
            continue
        out.append({"open_time": _iso(start), "open": parts[0][0],
                    "high": max(p[1] for p in parts), "low": min(p[2] for p in parts),
                    "close": parts[-1][3],
                    "available_at": _iso(start + timedelta(minutes=minutes))})
    return out


def _delivery(bucket):
    if bucket["close"] > bucket["open"]:
        return "bullish"
    if bucket["close"] < bucket["open"]:
        return "bearish"
    return "doji"


def detect_cisd(bars_1m, *, minutes, direction, extreme_at, settled_through,
                contract, policy=None):
    """Return the CISD fact for one selected extreme, or a typed non-event.

    status: CONFIRMED | PENDING | SUPERSEDED | UNAVAILABLE. `extreme_at` is the
    open time of the bucket that printed the selected extreme; which extreme to
    select is owner choice O2, so it is an explicit input, never inferred.
    """
    policy = {**DEFAULT_POLICY, **(policy or {})}
    base = {"schema": SCHEMA, "family": FAMILY, "contract": contract,
            "timeframe": f"{minutes}m", "direction": direction,
            "authority": dict(AUTHORITY), "policy": dict(policy)}
    if (direction not in DIRECTIONS or not contract
            or policy["boundary"] not in ("STRICT", "INCLUSIVE")
            or policy["doji"] not in ("ENDS_RUN", "CONTINUES_RUN")):
        return {**base, "status": "UNAVAILABLE", "reason": "invalid_request"}
    buckets = settled_buckets(bars_1m, minutes, settled_through)
    target = _instant(extreme_at)
    if buckets is None or target is None:
        return {**base, "status": "UNAVAILABLE", "reason": "tape_unreadable"}
    index = {b["open_time"]: i for i, b in enumerate(buckets)}
    at = index.get(_iso(target))
    if at is None:
        return {**base, "status": "UNAVAILABLE", "reason": "extreme_bucket_not_settled"}
    prior = "bullish" if direction == "bearish" else "bearish"
    extreme_key = "high" if direction == "bearish" else "low"
    extreme = buckets[at][extreme_key]

    def in_run(bucket):
        kind = _delivery(bucket)
        return kind == prior or (kind == "doji" and policy["doji"] == "CONTINUES_RUN")

    last = at
    while last >= 0 and _delivery(buckets[last]) != prior:
        last -= 1
    if last < 0:
        return {**base, "status": "UNAVAILABLE", "reason": "no_prior_delivery_run"}
    first = last
    while first - 1 >= 0 and in_run(buckets[first - 1]) and (
            _instant(buckets[first]["open_time"]) - _instant(buckets[first - 1]["open_time"])
            == timedelta(minutes=minutes)):
        first -= 1
    while _delivery(buckets[first]) != prior:   # a run starts on real delivery
        first += 1
    anchor = buckets[first]["open"]
    side = max if direction == "bearish" else min
    if side(b[extreme_key] for b in buckets[first:at + 1]) != extreme:
        return {**base, "status": "UNAVAILABLE", "reason": "extreme_not_maximal"}
    run = {"first_open_time": buckets[first]["open_time"],
           "last_open_time": buckets[last]["open_time"],
           "buckets": last - first + 1, "anchor_open": anchor,
           "extreme": extreme, "extreme_open_time": buckets[at]["open_time"]}
    step = timedelta(minutes=minutes)
    for previous, bucket in zip(buckets[last:], buckets[last + 1:]):
        if _instant(bucket["open_time"]) - _instant(previous["open_time"]) != step:
            # An unsettled or incomplete bucket could hide the break or a new
            # extreme; the validator never reads across a hole.
            return {**base, "status": "UNAVAILABLE", "run": run, "reason": "tape_gap",
                    "gap_after": previous["open_time"]}
        close = bucket["close"]
        broke = (close < anchor or (policy["boundary"] == "INCLUSIVE" and close == anchor)
                 if direction == "bearish" else
                 close > anchor or (policy["boundary"] == "INCLUSIVE" and close == anchor))
        if broke:
            event = {"break_open_time": bucket["open_time"], "break_close": close,
                     "available_at": bucket["available_at"]}
            ident = ":".join([FAMILY, contract, f"{minutes}m", direction,
                              run["first_open_time"], repr(anchor), bucket["open_time"]])
            return {**base, "status": "CONFIRMED", "run": run, "event": event,
                    "occurrence_id": ident}
        beyond = (bucket["high"] > extreme if direction == "bearish"
                  else bucket["low"] < extreme)
        if beyond and _instant(bucket["open_time"]) > target:
            return {**base, "status": "SUPERSEDED", "run": run,
                    "reason": "new_extreme_before_break",
                    "superseded_at": bucket["available_at"]}
    return {**base, "status": "PENDING", "run": run, "reason": "no_settled_break"}
