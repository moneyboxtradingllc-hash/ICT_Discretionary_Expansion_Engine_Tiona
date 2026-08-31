"""STEP 4B.12 §4 UNIT 1 — canonical swing evidence, and its projection.

ONE OWNER. `structure_engine`, `liquidity_engine`, `manipulation_detector` and
`structure_hierarchy` must never learn about venue calendars, expected buckets or
source-member reconstruction. They ask a pivot question; this module answers what
the evidence permits. Detector modules import only this, never `snapshot_builder`
internals.

TWO LAWS the projection exists to protect:

    TRUTHFUL AUTHORITY MAY NOT BROADEN A CONSUMER'S MARKET HORIZON.

        `manipulation_detector` sees `candles[-40:]`; `structure_hierarchy` sees
        its sequence window. Handing either a swing list computed over the whole
        history would "repair" authority by secretly granting pivots the consumer
        could never have confirmed. Same eyes, same field of view -- better proof
        about what those eyes actually saw.

    EVIDENCE IS ALIGNED BY IDENTITY, NEVER BY POSITION.

        Aligning by array length would be the very defect this unit exists to
        remove, one layer up. Every projected position is matched on canonical
        bucket identity, and a mismatch fails CLOSED (unevaluable) rather than
        falling back to array-neighbour semantics.
"""
from datetime import datetime, timedelta

from market_data.object_identity import canonical_instant

#: Per-pair adjacency verdicts. Three propositions, never a boolean: "no slot
#: sits between them" and "I may not answer that question" are different facts.
ADJ_PROVEN = "ADJACENT_PROVEN"
ADJ_NEIGHBOUR_OMITTED = "REQUIRED_NEIGHBOUR_OMITTED"
ADJ_CADENCE_UNKNOWN = "CADENCE_UNKNOWN"


def build_swing_evidence(settled: list, raw_series: list, tf_minutes: int) -> dict:
    """The canonical evidence a pivot neighbourhood needs, for one timeframe.

    Resolved here because this is the only layer holding all three inputs: the
    raw aggregates (which carry `source_member_times`), the venue cadence, and
    the timeframe.

    Two independent facts per position:

        adjacency[j]              relationship between settled[j] and [j+1]
        high/low_authoritative[j] EVERY expected source constituent of settled[j]
                                  was observed, so its extrema cannot be wrong

    The extrema test is deliberately stricter than the CLOSE test used for the
    raid family: a close is authored by ONE constituent (`bars[-1]`), an extremum
    by ALL of them. One absent minute could have held either extreme.
    """
    n = len(settled or [])
    if not n or not tf_minutes:
        return None                      # no cadence supplied; claim nothing
    if any(not c.get("timestamp") for c in settled):
        # A series without instants cannot be placed on a calendar at all, so no
        # evidence exists to build. Returning None (rather than raising) is the
        # honest answer: "no cadence supplied", which every consumer already
        # treats as fail-closed unless it explicitly opts into geometry.
        #
        # Raising here was a real defect: `extract_regime_features` wraps its
        # body in a blanket try/except that converts ANY exception into
        # `_zero_features()`, so a KeyError on `c["timestamp"]` silently zeroed
        # every regime feature -- including ones that have nothing to do with
        # swings. An evidence resolver must not be able to blank a consumer.
        return None
    from market_data.venue_calendar import (CADENCE_KNOWN,
                                            cadence_authority_over,
                                            expected_buckets, is_expected)

    raw_by_ts = {canonical_instant(c.get("timestamp"), strict=False): c
                 for c in (raw_series or [])}

    # CADENCE AUTHORITY MUST PRECEDE THE ADJACENCY QUESTION. Asking
    # `expected_buckets` first returns [] on a date outside the verified ranges
    # -- `is_expected` is False for every minute there -- and `not []` is True.
    # UNKNOWN SCHEDULE would masquerade as CLEAN ADJACENCY, the §9 residue.
    adjacency = []
    for j in range(n - 1):
        a_ts, b_ts = settled[j]["timestamp"], settled[j + 1]["timestamp"]
        cadence = cadence_authority_over(a_ts, b_ts)
        if cadence["authority"] != CADENCE_KNOWN:
            adjacency.append(ADJ_CADENCE_UNKNOWN)
            continue
        try:
            gap = expected_buckets(a_ts, b_ts, int(tf_minutes))
        except Exception:                # noqa: BLE001 — cadence unavailable
            adjacency.append(ADJ_CADENCE_UNKNOWN)
            continue
        adjacency.append(ADJ_NEIGHBOUR_OMITTED if gap else ADJ_PROVEN)

    # COUNT IS NOT CONSTITUENT IDENTITY. Authorising extrema with
    # `len(members) == expected_members` revives the fallacy §8 outlawed:
    #
    #     expected  18:10 18:11 18:12 18:13 18:14
    #     observed  18:10 18:12 18:13 18:14 18:15
    #     count     5 == 5      identity  WRONG
    #
    # `expected subset-of observed`, not equality: an observation the venue did
    # not schedule is a real print that ADDS information and cannot undermine an
    # extremum, while a missing expected one could have held either extreme.
    extrema, bucket_times = [], []
    for c in settled:
        ts = canonical_instant(c.get("timestamp"), strict=False)
        bucket_times.append(ts)
        raw = raw_by_ts.get(ts)
        if raw is None:
            extrema.append(False)
            continue
        if int(tf_minutes) == 1:
            # A 1m object IS the source observation. Its HIGH/LOW are directly
            # observed on the object itself -- there is no aggregation to
            # reconstruct and no constituent set to prove, so this holds even
            # when cadence authority is unknown. Object existence and field
            # authority survive; adjacency and the pivot proposition do not.
            extrema.append(True)
            continue
        members = raw.get("source_member_times")
        if members is None:
            extrema.append(False)        # no provenance: cannot prove
            continue
        observed = {canonical_instant(m, strict=False) for m in members}
        t0 = datetime.fromisoformat(ts)
        span_end = (t0 + timedelta(minutes=int(tf_minutes) - 1)).isoformat()
        if cadence_authority_over(ts, span_end)["authority"] != CADENCE_KNOWN:
            # The expected constituent SET cannot be derived without schedule
            # authority, so the extrema cannot be proven either.
            extrema.append(False)
            continue
        wanted = {canonical_instant((t0 + timedelta(minutes=k)).isoformat(),
                                    strict=False)
                  for k in range(int(tf_minutes))
                  if is_expected(t0 + timedelta(minutes=k))}
        extrema.append(bool(wanted) and wanted.issubset(observed))

    return {"tf_minutes": int(tf_minutes),
            "bucket_times": bucket_times,
            "adjacency": adjacency,
            "high_authoritative": list(extrema),
            "low_authoritative": list(extrema)}


def project_swing_evidence(evidence: dict, candles: list) -> dict:
    """Project full-series evidence onto a consumer's own bounded window.

    Matching is by canonical bucket IDENTITY. Adjacency edges are rebuilt from
    the child window only -- an edge from outside it describes a relationship the
    consumer cannot see, and importing it would widen the horizon by the back
    door.

    Returns None when the child window cannot be aligned, and None means "no
    evidence" -- which every consumer treats as UNEVALUABLE unless it explicitly
    opts into legacy semantics. Failing closed is the point: a silent fallback to
    array adjacency is exactly the defect being repaired.
    """
    if not evidence or not candles:
        return None
    parent = evidence.get("bucket_times") or []
    index = {ts: i for i, ts in enumerate(parent)}
    positions = []
    for c in candles:
        ts = canonical_instant(c.get("timestamp"), strict=False)
        if ts not in index:
            return None                  # identity mismatch -> fail closed
        positions.append(index[ts])

    hi = evidence.get("high_authoritative") or []
    lo = evidence.get("low_authoritative") or []
    par_adj = evidence.get("adjacency") or []
    child_hi = [hi[p] if p < len(hi) else False for p in positions]
    child_lo = [lo[p] if p < len(lo) else False for p in positions]

    child_adj = []
    for k in range(len(positions) - 1):
        a, b = positions[k], positions[k + 1]
        if b == a + 1 and a < len(par_adj):
            child_adj.append(par_adj[a])
        else:
            # The child's neighbours are not the parent's neighbours: the
            # consumer window skips a position the parent held. That is exactly
            # a required-neighbour omission from this window's point of view.
            child_adj.append(ADJ_NEIGHBOUR_OMITTED)

    assert len(child_hi) == len(candles)
    assert len(child_lo) == len(candles)
    assert len(child_adj) == max(len(candles) - 1, 0)
    return {"tf_minutes": evidence.get("tf_minutes"),
            "bucket_times": [parent[p] for p in positions],
            "adjacency": child_adj,
            "high_authoritative": child_hi,
            "low_authoritative": child_lo}


def terminal_constituent_observed(bucket: dict, terminal: str) -> bool:
    """Did the bucket's LAST EXPECTED constituent get observed?

    STEP 4B.12. The first version answered this with `members ==
    expected_members` -- three lines under a docstring saying counts cannot
    identify WHICH constituent was seen. That guard called the 5m bucket at
    18:10 unproven (4/5) even though its terminal minute 18:14 was present and
    its close was fully authoritative, so it over-withheld.
    
    The aggregator now publishes `source_member_times`, the exact observations
    it consumed. Identity is answered by identity.
    """
    observed = bucket.get("source_member_times")
    if observed is None:
        return False          # no provenance -> cannot prove; never assume
    # STEP 4B.12 §8 — compare INSTANTS, not spellings. The producer canonicalises
    # what it publishes, and this canonicalises again rather than trusting that,
    # because archived buckets were written before the producer did so.
    want = canonical_instant(terminal, strict=False)
    return want in {canonical_instant(t, strict=False) for t in observed}


def previous_slot_close(settled: list, raw_series: list, tf_minutes) -> dict:
    """The previous EXPECTED market slot's close, and the authority behind it.

    STEP 4B.12 §4/§5. Three outcomes, never a fourth:

        the previous expected slot IS the previous settled bar   -> adjacent
        the slot exists but its CLOSE cannot be proven           -> withhold
        the slot was never observed                              -> withhold

    CLOSE authority is field-scoped: `_aggregate` takes `bars[-1]["close"]`, so
    the close is proven exactly when the bucket's TERMINAL expected constituent
    is present -- even if an interior member is missing and the bucket's high
    and low are therefore unprovable.
    """
    from datetime import timezone
    from structure.liquidity_engine import (
        PRIOR_ADJACENT, PRIOR_AUTHORITATIVE, PRIOR_CADENCE_UNKNOWN,
        PRIOR_CLOSE_UNPROVEN, PRIOR_NO_OBSERVATION, PRIOR_UNCADENCED)
    if not tf_minutes or len(settled or []) < 2:
        return {"authority": PRIOR_UNCADENCED}
    from market_data.venue_calendar import (
        CADENCE_KNOWN, cadence_authority_over, expected_buckets)
    a, b = settled[-2], settled[-1]
    # §9 RESIDUE + §10 — TWO FAILURES, ONE LAW.
    #
    #   A. unverified schedule: `is_expected` is False for every minute of an
    #      unverified date, so `expected_buckets` returns [] and the old code
    #      read that as "no slot sits between them" -- when the calendar had in
    #      fact said "I have no jurisdiction here".
    #   B. calendar failure: the exception path returned PRIOR_UNCADENCED, whose
    #      consumer bridged to the array neighbour.
    #
    # Neither holds the authority to establish the immediately previous EXPECTED
    # market slot, so neither may author a prior-close-dependent proposition.
    # They converge on one non-authoritative state instead of two different
    # silences. UNKNOWN SCHEDULE IS NOT AN EMPTY SCHEDULE.
    cadence = cadence_authority_over(a["timestamp"], b["timestamp"])
    if cadence["authority"] != CADENCE_KNOWN:
        return {"authority": PRIOR_CADENCE_UNKNOWN, "cadence_rule": cadence["rule"]}
    try:
        missing = expected_buckets(a["timestamp"], b["timestamp"], int(tf_minutes))
    except Exception as exc:                 # noqa: BLE001 — calendar unavailable
        return {"authority": PRIOR_CADENCE_UNKNOWN,
                "cadence_rule": f"expected-slot authority unavailable: {exc}"}
    if not missing:
        # Cadence IS known here, so an empty result is a real answer: the array
        # neighbour genuinely is the previous market slot.
        return {"authority": PRIOR_ADJACENT, "close": a.get("close")}
    # An expected slot sits between them: the array neighbour is NOT the prior bar.
    prev_start = missing[-1].astimezone(timezone.utc).isoformat()
    # §8 — the SAME defect as the terminal lookup, one line earlier and easy to
    # miss: a raw-string match against a series carrying a different UTC offset
    # finds nothing and reports PREVIOUS_SLOT_NOT_OBSERVED for a slot that was
    # observed. Absence must be real absence, not a spelling mismatch.
    from market_data.object_identity import canonical_instant
    _want = canonical_instant(prev_start, strict=False)
    bucket = next((c for c in raw_series or []
                   if canonical_instant(c.get("timestamp"), strict=False) == _want),
                  None)
    if bucket is None:
        return {"authority": PRIOR_NO_OBSERVATION}
    # Is that bucket's CLOSE authoritative? Only if its terminal constituent
    # was observed. Membership counts alone cannot answer this.
    #
    # §9 — WHICH minute is the terminal constituent is a CADENCE question, not
    # an arithmetic one. This computed `bucket_start + N - 1`, which asserts the
    # venue was scheduled to print at that minute; only the calendar can say so.
    # A bucket whose nominal last minute falls inside a scheduled closure is
    # COMPLETE, and the old arithmetic would have called its close unprovable --
    # a scheduled closure masquerading as a missing observation.
    from market_data.venue_calendar import (
        NO_EXPECTED_CONSTITUENT, expected_terminal_constituent)
    spec = expected_terminal_constituent(prev_start, int(tf_minutes))
    if spec["basis"] == NO_EXPECTED_CONSTITUENT:
        # The calendar expected nothing in this bucket, yet a bucket exists.
        # Those two authorities disagree, and no observation can be named as the
        # author of the close, so it is not provable here.
        return {"authority": PRIOR_CLOSE_UNPROVEN,
                "terminal_basis": spec["basis"]}
    proven = terminal_constituent_observed(bucket, spec["terminal"])
    if not proven:
        return {"authority": PRIOR_CLOSE_UNPROVEN,
                "terminal_basis": spec["basis"]}
    # The basis travels with the verdict: PROVEN under a KNOWN schedule and
    # PROVEN under nominal arithmetic are not the same strength of claim, and a
    # consumer that cannot tell them apart cannot audit this later.
    return {"authority": PRIOR_AUTHORITATIVE, "close": bucket.get("close"),
            "terminal_basis": spec["basis"]}


#: STEP 4B.12 §4 UNIT 2 — TRANSITION EVIDENCE.
#:
#: A BREAK is an EVENT. `last_close > last_swing_high` is a POSITION, and the two
#: are not the same proposition. Measured over 1000 scan x timeframe
#: opportunities on the Unit-1 tree:
#:
#:     OLD BOS positive deliveries   366
#:     genuine fresh transitions      88   (38 unique market events)
#:     persistent already-beyond     278   published as fresh events
#:     transitions OLD missed          0
#:
#:     OLD MSS positive deliveries    90
#:     genuine fresh transitions      36   (12 unique market events)
#:     persistent already-in-state    54   (set-identical to OLD's false positives)
#:
#: 76% of every "break event" this bot published was price standing still.
#:
#: The transition question needs the CLOSE of the previous EXPECTED market
#: bucket -- the same fact the raid family already consumes -- so it is answered
#: by the same resolver rather than a second calendar owner. What this adds is
#: CURRENT close authority, which the liquidity lane never had to ask.
#:
#: TRANSITION consumes CLOSE only. It does not consume HIGH/LOW: the extrema
#: belong to the source swing, whose authority is Unit 1's responsibility and is
#: already settled before this is called.
TRANSITION_EVALUABLE = "EVALUABLE"
TRANSITION_UNEVALUABLE_PREVIOUS_SLOT = "UNEVALUABLE_PREVIOUS_SLOT"
TRANSITION_UNEVALUABLE_PREVIOUS_CLOSE = "UNEVALUABLE_PREVIOUS_CLOSE"
TRANSITION_UNEVALUABLE_CURRENT_CLOSE = "UNEVALUABLE_CURRENT_CLOSE"
TRANSITION_UNEVALUABLE_CADENCE = "UNEVALUABLE_CADENCE"


def build_transition_evidence(settled: list, raw_series: list,
                              tf_minutes: int) -> dict:
    """Can a break EVENT be evaluated for the latest settled bucket, and against
    which previous close?

    Returns the current bucket identity and close, the previous EXPECTED bucket
    identity and close, and one mutually exclusive state. Never bridges to the
    array neighbour: an absent expected bucket is UNEVALUABLE, not a licence to
    reach further back.
    """
    from structure.liquidity_engine import (
        PRIOR_ADJACENT, PRIOR_AUTHORITATIVE, PRIOR_CADENCE_UNKNOWN,
        PRIOR_CLOSE_UNPROVEN, PRIOR_NO_OBSERVATION)

    if not settled or not tf_minutes:
        return {"state": TRANSITION_UNEVALUABLE_CADENCE, "reason": "no cadence"}

    cur = settled[-1]
    cur_ts = canonical_instant(cur.get("timestamp"), strict=False)

    # CURRENT close authority. A settled aggregate does not automatically prove
    # every field: `close` is authored by the TERMINAL constituent alone, so it
    # is provable exactly when that constituent was observed.
    raw_by_ts = {canonical_instant(c.get("timestamp"), strict=False): c
                 for c in (raw_series or [])}
    cur_raw = raw_by_ts.get(cur_ts)
    if int(tf_minutes) > 1:
        members = (cur_raw or {}).get("source_member_times")
        if members is None:
            return {"state": TRANSITION_UNEVALUABLE_CURRENT_CLOSE,
                    "current_bucket": cur_ts, "reason": "no source provenance"}
        try:
            t0 = datetime.fromisoformat(cur_ts)
        except (ValueError, TypeError):
            return {"state": TRANSITION_UNEVALUABLE_CADENCE,
                    "current_bucket": cur_ts, "reason": "unusable instant"}
        terminal = canonical_instant(
            (t0 + timedelta(minutes=int(tf_minutes) - 1)).isoformat(), strict=False)
        if terminal not in {canonical_instant(m, strict=False) for m in members}:
            return {"state": TRANSITION_UNEVALUABLE_CURRENT_CLOSE,
                    "current_bucket": cur_ts,
                    "reason": "terminal constituent absent"}

    prior = previous_slot_close(settled, raw_series, tf_minutes)
    authority = (prior or {}).get("authority")
    if authority in (PRIOR_ADJACENT, PRIOR_AUTHORITATIVE):
        return {"state": TRANSITION_EVALUABLE,
                "current_bucket": cur_ts, "current_close": cur.get("close"),
                "previous_close": prior.get("close"),
                "previous_authority": authority}
    return {"state": {PRIOR_NO_OBSERVATION: TRANSITION_UNEVALUABLE_PREVIOUS_SLOT,
                      PRIOR_CLOSE_UNPROVEN: TRANSITION_UNEVALUABLE_PREVIOUS_CLOSE,
                      PRIOR_CADENCE_UNKNOWN: TRANSITION_UNEVALUABLE_CADENCE,
                      }.get(authority, TRANSITION_UNEVALUABLE_CADENCE),
            "current_bucket": cur_ts, "current_close": cur.get("close"),
            "previous_authority": authority,
            "reason": (prior or {}).get("cadence_rule")}
