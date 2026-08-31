from datetime import datetime

from market_data.object_identity import (
    MarketObjectIdentityError, canonical_instant, row_contract)


#: STEP 3G — CONTRACT IS INTRINSIC TO A BAR, NOT CONFIGURATION ABOUT IT.
#:
#: `_aggregate` rebuilt each bucket from OHLCV alone and dropped `contract`, so
#: every 3m/5m/15m bar arrived anonymous and a downstream caller had to reassert
#: the instrument. That is strictly worse than an ugly id: a bucket whose real
#: members were U26 could be handed a caller's "Z26" and emerge as
#:
#:     FVG:CON.F.US.MNQ.Z26:5m:...
#:
#: -- a perfect-looking identifier attached to falsely scoped evidence. A
#: derived bar belongs to the contract its members belong to, by derivation, and
#: transformation may not erase that.
#: STEP 3H §7-§10 — THREE CASES, NOT TWO.
#:
#: The 3G version collected non-empty values and returned the single survivor,
#: which silently folded PARTIAL silence into full evidence:
#:
#:     U26, U26, <silent>, U26   ->  "U26, EVIDENCE_DERIVED"
#:
#: But 14 members proving U26 is not the same claim as 15 members proving U26,
#: and calling it EVIDENCE_DERIVED overstates what the bucket knows.
#:
#: MEASURED POLICY, not assumed: every one of the 1730 rows in the canonical
#: store carries `contract` (0 missing). The field is therefore REQUIRED in
#: canonical data, which makes a silent member inside an otherwise identified
#: bucket schema damage rather than meaningful uncertainty -- so it fails closed
#: rather than being quietly completed from its neighbours.
ALL_MEMBERS_EVIDENCE_DERIVED = "ALL_MEMBERS_EVIDENCE_DERIVED"
NO_MEMBER_EVIDENCE = "NO_MEMBER_EVIDENCE"


def _bucket_contract(bars: list, key: str) -> tuple:
    """(contract, provenance) for one bucket. Partial and mixed both fail.

    MIXED FAILS CLOSED. Two futures contracts cannot be averaged into one
    candle: choosing first, last, or the caller's parameter would each produce a
    normal-looking bar resting on two markets.

    PARTIAL FAILS CLOSED. One identified member does not identify its anonymous
    neighbours; that a bar sits in the same time bucket is not evidence of which
    market it came from.
    """
    named, silent = set(), 0
    for b in bars:
        v = row_contract(b, where=f"bucket {key} member")
        if v:
            named.add(v)
        else:
            silent += 1
    if len(named) > 1:
        raise MarketObjectIdentityError(
            f"bucket {key} spans contracts {sorted(named)}; a derived candle "
            f"cannot rest on two markets, and neither member may be chosen "
            f"over the other to make it look ordinary")
    if named and silent:
        raise MarketObjectIdentityError(
            f"bucket {key}: {len(bars) - silent}/{len(bars)} members prove "
            f"{next(iter(named))!r} and {silent} carry no instrument. Canonical "
            f"rows are contract-bearing (0 of 1730 stored bars lack one), so "
            f"this is schema damage, not uncertainty -- an identified member "
            f"may not lend its identity to an anonymous one.")
    if named:
        return named.pop(), ALL_MEMBERS_EVIDENCE_DERIVED
    return None, NO_MEMBER_EVIDENCE


def _floor_timestamp(ts_str: str, n_minutes: int) -> str:
    """Return the ISO 8601 bucket start for ts_str rounded down to n_minutes."""
    if ts_str.endswith("Z"):
        ts_str = ts_str[:-1] + "+00:00"
    dt = datetime.fromisoformat(ts_str)
    total = dt.hour * 60 + dt.minute
    floored = (total // n_minutes) * n_minutes
    bucket = dt.replace(
        hour=floored // 60,
        minute=floored % 60,
        second=0,
        microsecond=0,
    )
    return bucket.isoformat()


def _aggregate(candles_1m: list, n_minutes: int) -> list:
    """
    Aggregate sorted 1m candles into n_minutes candles using floor bucketing.
    Incomplete trailing buckets are included — live scanning benefits from
    seeing the current in-progress bar rather than waiting for its close. Each
    bucket carries `members`/`complete` so a consumer that needs SETTLED
    evidence can tell the forming bar apart from a finished one.
    """
    if not candles_1m:
        return []

    buckets: dict = {}
    order: list   = []

    for c in candles_1m:
        key = _floor_timestamp(c["timestamp"], n_minutes)
        if key not in buckets:
            buckets[key] = []
            order.append(key)
        buckets[key].append(c)

    result = []
    for key in order:
        bars = buckets[key]
        contract, contract_provenance = _bucket_contract(bars, key)
        row = {
            "timestamp": key,
            "open":      bars[0]["open"],
            "high":      max(b["high"]   for b in bars),
            "low":       min(b["low"]    for b in bars),
            "close":     bars[-1]["close"],
            "volume":    sum(b["volume"] for b in bars),
            # CONTINUITY-2D (2026-08-11). How many 1m constituents this bucket
            # actually has. Without it a 15m bar built from 6 minutes is
            # shape-identical to one built from 15, and `find_swings` will
            # happily use the forming bar as RIGHT-SIDE confirmation for a
            # pivot. Measured on the live tape: at 15:05Z a 15m swing high of
            # 29,805.0 was "confirmed" by a 6/15 bucket -- and vanished once
            # that bucket closed higher. A confirmed pivot must not rest on a
            # bar that is still changing.
            "members":   len(bars),
            "complete":  len(bars) == n_minutes,
            # CONTINUITY-2G (2026-08-11). How many constituents a FULL bucket of
            # this timeframe has. Without it `members: 6` is uninterpretable --
            # 6 of what? The Brain is told 6/15, not 6.
            "expected_members": n_minutes,
            # STEP 4B.12 — OBSERVED SOURCE MEMBERSHIP (identity, not count).
            #
            # `members`/`expected_members` answer HOW MANY constituents were
            # seen. They can never answer WHICH. A 5m bucket reading 4/5 because
            # its INTERIOR minute is absent and one reading 4/5 because its
            # TERMINAL minute is absent are indistinguishable by count -- yet
            # their CLOSE authority is opposite, since `close` is taken from
            # `bars[-1]`.
            #
            # A consumer must not reconstruct this by searching the current raw
            # tape: the aggregate was formed under one evidence universe and a
            # later lookup could answer from another. The transformation that
            # consumed these observations publishes what it consumed.
            #
            # SCOPE: retrospective source-member provenance for the current
            # evidence basis. These are 1m bucket starts, NOT a claim to solve
            # perception-faithful version identity.
            "source_tf": "1m",
            # STEP 4B.12 §8 — ONE INSTANT, ONE IDENTITY.
            #
            # This published `str(timestamp)`, and every consumer compared those
            # raw strings. So
            #
            #     2026-08-12T18:14:00+00:00
            #     2026-08-12T14:14:00-04:00
            #
            # -- the same minute of the same session -- were two different
            # source-member identities, and a terminal-constituent lookup across
            # that boundary would report the close UNPROVEN for a bucket whose
            # terminal minute was sitting right there. Identity answered by
            # identity is only true if the identity is canonical.
            #
            # `strict=False` deliberately: a naive or unparseable stamp keeps its
            # raw form and stays VISIBLE rather than raising here. The builder
            # accepts archives, replays and hand-built fixtures, and refusing to
            # aggregate them would be a far larger claim than this repair makes.
            # Such a value simply cannot match a canonical one -- an honest
            # inability, identical to today's behaviour.
            #
            # ORDER IS PRESERVED: this is a sequence, and `bars[-1]` is the
            # terminal constituent that authorises `close`.
            "source_member_times": tuple(
                canonical_instant(b.get("timestamp"), strict=False) for b in bars),
        }
        # STEP 3G: preserved by DERIVATION from the members, never reinjected by
        # a later caller. Absent only when the members themselves said nothing.
        if contract:
            row["contract"] = contract
            # §10: the VALUE and its PROVENANCE QUALITY travel together, so a
            # downstream FVG inherits not just "U26" but how well that is known.
            row["contract_provenance"] = contract_provenance
        result.append(row)

    return result


def build_timeframes(candles_1m: list) -> dict:
    """
    Return a raw_data dict compatible with build_snapshot().
    Input: list of normalized 1m candle dicts (oldest first).
    Output: {"1m": [...], "3m": [...], "5m": [...], "15m": [...]}

    CONTINUITY-2G: the 1m series is STAMPED settled rather than left unlabelled.
    It is not an assumption -- it relays a provider contract:
    `MinuteCandleAggregator.roll()` closes only buckets strictly older than the
    current minute, and `developing()` is diagnostics-only and "never a completed
    candle". Before this, 1m reached the Brain with no completeness information
    and was indistinguishable from an archive whose status is genuinely unknown.
    Publishing what is known is the whole point of 2G; inferring it downstream
    is what 2G exists to stop.

    A new dict per bar -- the caller's candles are never mutated.
    """
    return {
        "1m":  [{**c, "members": 1, "complete": True, "expected_members": 1}
                for c in candles_1m],
        "3m":  _aggregate(candles_1m, 3),
        "5m":  _aggregate(candles_1m, 5),
        "15m": _aggregate(candles_1m, 15),
    }
