MIN_CANDLES = 4


#: STEP 4B.12 §4 UNIT 1 — A PIVOT'S NEIGHBOURS ARE MARKET NEIGHBOURS.
#:
#: `candles[i-j]` / `candles[i+j]` are ARRAY neighbours of whatever sequence this
#: function is handed, and `snapshot_builder` hands it `all_settled` -- forming
#: and historical-incomplete buckets already removed. So
#:
#:     good bucket -> [incomplete bucket dropped] -> good bucket
#:
#: became `good, good` and the pivot rule called them neighbours. Measured on the
#: real tape, unique production pivots whose confirming neighbourhood omitted a
#: required canonical slot:
#:
#:     1m 17/313    3m 12/102    5m 13/55    15m 11/19
#:
#: Two currently published levels stood on that: 5m last_swing_low 29889.75 and
#: 15m last_swing_high 29928.75, both descending from ONE absent source minute at
#: 18:11. Neither is proven FALSE -- the absent minute could have printed a lower
#: low or a higher high, or not. They are pivots the engine had no right to
#: certify.
#:
#: FIELD CONTRACT, and it is the INVERSE of liquidity's. The pivot predicate
#: consumes HIGH (for a high) or LOW (for a low) and never CLOSE. A bucket
#: missing an interior minute has a PROVABLE close and UNPROVABLE extrema, so the
#: bucket liquidity may legitimately use is the same bucket this may not.
#:
#: The caller resolves the evidence, exactly as it resolves the previous slot's
#: close for the raid family -- only `snapshot_builder` holds the raw series,
#: the source-member provenance and the venue cadence.
#:
#:     evidence = {
#:         "tf_minutes":            int,
#:         "canonically_adjacent":  [bool] * (n-1)   pair j -> j+1
#:         "high_authoritative":    [bool] * n
#:         "low_authoritative":     [bool] * n
#:     }
#:
#: `evidence=None` preserves today's behaviour exactly, for archives, replays and
#: hand-built fixtures that carry no cadence. Such a call cannot prove market
#: adjacency and does not claim to.
SWING_EVALUABLE = "EVALUABLE"
SWING_NEIGHBOUR_OMITTED = "UNEVALUABLE_REQUIRED_NEIGHBOUR_OMITTED"
SWING_EXTREMA_UNPROVEN = "UNEVALUABLE_EXTREMA_UNPROVEN"
SWING_CADENCE_UNKNOWN = "UNEVALUABLE_CADENCE_UNKNOWN"


SWING_NO_CADENCE = "UNEVALUABLE_NO_CADENCE_SUPPLIED"


def _neighbourhood_verdict(evidence, lo: int, hi: int, side: str,
                           allow_uncadenced: bool = False) -> str:
    """Can the pivot spanning array indices lo..hi be certified?

    ABSENCE OF EVIDENCE MAY NOT CERTIFY. The first version returned EVALUABLE
    when `evidence` was None while its own docstring said such a caller "cannot
    prove market adjacency" -- i.e. "I lack the evidence to establish adjacency,
    therefore adjacency passed". That is the liquidity bridge again.

    `allow_uncadenced=True` is the explicit legacy opt-in, mirroring
    `find_fvgs` and `analyze_liquidity`. No caller inherits it by omission.
    """
    if not evidence:
        return SWING_EVALUABLE if allow_uncadenced else SWING_NO_CADENCE
    # CADENCE UNKNOWN DOMINATES. Without schedule authority we cannot even say
    # a neighbour was omitted -- claiming omission would assert knowledge of what
    # the venue expected. The forensic cause is preserved rather than collapsed
    # into one broad "unevaluable"; a consumer may map several to one Brain
    # capability later, but the producer may not erase why.
    adj = evidence.get("adjacency") or []
    span = [adj[j] for j in range(lo, hi) if j < len(adj)]
    if any(v == "CADENCE_UNKNOWN" for v in span):
        return SWING_CADENCE_UNKNOWN
    if any(v != "ADJACENT_PROVEN" for v in span):
        return SWING_NEIGHBOUR_OMITTED
    field = evidence.get("high_authoritative" if side == "high"
                         else "low_authoritative") or []
    for j in range(lo, hi + 1):
        if j < len(field) and not field[j]:
            return SWING_EXTREMA_UNPROVEN
    return SWING_EVALUABLE


def find_swings_detailed(candles: list, source_tf: str = None, *,
                         evidence: dict = None,
                         allow_uncadenced: bool = False) -> tuple:
    """Swings as OBJECTS: (highs, lows), each carrying its own evidence.

    STEP 2C (2026-08-12). `find_swings` computed the pivot index, the bars that
    confirmed it and the confirming bar's timestamp -- then returned bare prices
    and threw all of it away. A BOS could therefore say "close broke 29877.5"
    without being able to say when 29877.5 became a level, what confirmed it, or
    whether that evidence was settled. The break was temporally classified; the
    thing it claimed to break was not.

    A pivot needs `lookback` bars AFTER it to be confirmed, so it has a real
    lifecycle: it forms at `pivot_time` and becomes usable at `confirmed_at`.
    That is confirmation, not lookahead -- every bar used is at or before the
    confirming bar, and before that bar exists the pivot simply is not yet a
    swing.

    `lookback` adapts to `n`, so a pivot confirmed in a short window may not
    qualify in a longer one. That is the producer's existing behaviour and is
    preserved exactly: this function only records what the rule already decided.
    """
    n = len(candles)
    lookback = 3 if n >= 10 else 2 if n >= 6 else 1

    highs, lows = [], []
    for i in range(lookback, n - lookback):
        h = candles[i]["high"]
        l = candles[i]["low"]
        confirm_idx = i + lookback

        if all(candles[i - j]["high"] < h for j in range(1, lookback + 1)) and \
           all(candles[i + j]["high"] < h for j in range(1, lookback + 1)):
            verdict = _neighbourhood_verdict(evidence, i - lookback,
                                             i + lookback, "high",
                                             allow_uncadenced)
            if verdict == SWING_EVALUABLE:
                highs.append(_swing_object(candles, i, confirm_idx, lookback, h,
                                           "high", source_tf))

        if all(candles[i - j]["low"] > l for j in range(1, lookback + 1)) and \
           all(candles[i + j]["low"] > l for j in range(1, lookback + 1)):
            verdict = _neighbourhood_verdict(evidence, i - lookback,
                                             i + lookback, "low",
                                             allow_uncadenced)
            if verdict == SWING_EVALUABLE:
                lows.append(_swing_object(candles, i, confirm_idx, lookback, l,
                                          "low", source_tf))

    return highs, lows


def find_swings_withheld(candles: list, source_tf: str = None, *,
                         evidence: dict = None,
                         allow_uncadenced: bool = False) -> list:
    """Pivot candidates the geometry accepts but the EVIDENCE cannot certify.

    Deliberately a separate call rather than a third return value: a swing in
    `find_swings_detailed` is a swing the engine may certify, and every existing
    consumer keeps that guarantee unchanged. This channel exists so the Brain
    contract can later say UNEVALUABLE instead of falling silent -- withholding
    a level and never mentioning it would replace one lie with another.
    """
    n = len(candles)
    lookback = 3 if n >= 10 else 2 if n >= 6 else 1
    out = []
    for i in range(lookback, n - lookback):
        h, l = candles[i]["high"], candles[i]["low"]
        for side, hit in (
                ("high", all(candles[i - j]["high"] < h for j in range(1, lookback + 1))
                 and all(candles[i + j]["high"] < h for j in range(1, lookback + 1))),
                ("low", all(candles[i - j]["low"] > l for j in range(1, lookback + 1))
                 and all(candles[i + j]["low"] > l for j in range(1, lookback + 1)))):
            if not hit:
                continue
            verdict = _neighbourhood_verdict(evidence, i - lookback,
                                             i + lookback, side,
                                             allow_uncadenced)
            if verdict != SWING_EVALUABLE:
                out.append({"side": side, "source_tf": source_tf,
                            "level": h if side == "high" else l,
                            "pivot_index": i,
                            "pivot_time": str(candles[i].get("timestamp") or ""),
                            "evaluability": verdict})
    return out


def _swing_object(candles: list, i: int, confirm_idx: int, lookback: int,
                  level: float, side: str, source_tf: str = None) -> dict:
    """One swing with the evidence that made it a swing.

    IDENTITY IS TIMEFRAME-QUALIFIED. A 1m swing low and a 5m swing low can share
    a pivot minute and a price and still be different structural objects. Once
    BOS/MSS started publishing `broken_swing_id`, an un-qualified id would alias
    two different levels across the Brain's multi-timeframe world.
    """
    window = candles[max(0, i - lookback):confirm_idx + 1]
    pivot_time = str(candles[i].get("timestamp") or "")
    tf = source_tf or "unspecified_tf"
    return {
        "swing_id": f"swing_{side}:{tf}:{pivot_time}:{round(level, 2)}",
        "source_tf": source_tf,
        "side": side,
        "level": level,
        "pivot_index": i,
        "pivot_time": pivot_time,
        "confirmed_at": str(candles[confirm_idx].get("timestamp") or ""),
        "source_bars": [str(c.get("timestamp") or "") for c in window],
        "source_temporal_states": [str(c.get("temporal_status") or "unknown")
                                   for c in window],
    }


def find_swings(candles: list, *, evidence: dict = None,
                allow_uncadenced: bool = False) -> tuple:
    """
    Returns (swing_highs, swing_lows) as ordered lists of price values.
    Lookback adapts to dataset size for short timeframes.

    Unchanged contract, now a projection of `find_swings_detailed` so the pivot
    rule has exactly ONE owner and the price-only view cannot drift from the
    object view.
    """
    highs, lows = find_swings_detailed(candles, evidence=evidence,
                                       allow_uncadenced=allow_uncadenced)
    return [s["level"] for s in highs], [s["level"] for s in lows]


def _bias(highs: list, lows: list) -> str:
    if len(highs) >= 2 and len(lows) >= 2:
        if highs[-1] > highs[-2] and lows[-1] > lows[-2]:
            return "bullish"
        if highs[-1] < highs[-2] and lows[-1] < lows[-2]:
            return "bearish"
    return "neutral"


def analyze_structure(candles: list, evidence: dict = None, *,
                      transition: dict = None,
                      allow_uncadenced: bool = False) -> dict:
    if len(candles) < MIN_CANDLES:
        return {
            "bias": "neutral",
            "state": "insufficient_data",
            "last_swing_high": None,
            "last_swing_low": None,
            # UNIT 4: stated as None rather than omitted. A missing key would
            # send a consumer back to guessing identity from price, which is
            # the defect this unit removes.
            "last_swing_high_pivot_index": None,
            "last_swing_low_pivot_index": None,
            "bos": False,
            "mss": False,
            # UNIT 2: the early return predates the transition contract and was
            # publishing a structure block with no evaluability at all, so a
            # consumer could not tell "insufficient data" from "evaluated, no
            # event". Same distinction the rest of this unit exists to protect.
            "bos_evaluability": "UNEVALUABLE_INSUFFICIENT_CANDLES",
            "mss_evaluability": "UNEVALUABLE_INSUFFICIENT_CANDLES",
            "position_beyond_swing_high": False,
            "position_beyond_swing_low": False,
        }

    # STEP 4B.12 §4 UNIT 4 — IDENTITY IS NOT RECONSTRUCTABLE FROM PRICE.
    #
    # This called `find_swings`, the PRICE-ONLY projection, and published two
    # bare rounded floats. `expansion_detector._leg_start_index` then had to
    # find the leg origin by searching backwards for a candle whose extreme
    # equalled that price -- which matches EVERY candle that ever touched the
    # level, and the reversed scan deliberately takes the most recent one.
    #
    # Measured over 1000 leg lookups on the 2026-08-12 tape:
    #
    #     exact identity                                     952
    #     wrong occurrence                                     48
    #       cause "a later candle revisited a level"       48/48
    #       changed a leg metric                              30
    #       hidden by the [8,60] clamp                        18
    #
    # Every wrong selection was too RECENT -- a revisit read as an origin. On 1m
    # at 15:55 the high 29843.00 was made at 15:43 and touched again at 15:51,
    # and that touch outranked the swing LOW made at 15:45, so the leg began at a
    # candle that was not a pivot on either side.
    #
    # The detailed objects already carry `pivot_index`, in the SAME list index
    # space the consumer receives, so the correct answer was computed here and
    # discarded. Publishing it needs no resolver and no new lookup.
    #
    # The index and the price are read from the SAME selected object. Choosing
    # a price from one occurrence and an index from another would rebuild the
    # defect with extra steps.
    highs_d, lows_d = find_swings_detailed(candles, evidence=evidence,
                                           allow_uncadenced=allow_uncadenced)
    highs = [s["level"] for s in highs_d]
    lows = [s["level"] for s in lows_d]

    src_high = highs_d[-1] if highs_d else None
    src_low = lows_d[-1] if lows_d else None
    last_swing_high = round(src_high["level"], 2) if src_high else None
    last_swing_low = round(src_low["level"], 2) if src_low else None
    last_swing_high_pivot_index = src_high["pivot_index"] if src_high else None
    last_swing_low_pivot_index = src_low["pivot_index"] if src_low else None
    bias = _bias(highs, lows)
    last_close = candles[-1]["close"]

    # STEP 4B.12 §4 UNIT 2 — A BREAK IS AN EVENT, NOT A POSITION.
    #
    # This asked "is the close beyond the most recent swing?" and published the
    # answer as `bos` / `bos_event`. That is a STATE. Once price sat beyond a
    # level it stayed beyond it, so the same break was re-announced as a fresh
    # event on every subsequent scan. Measured over 1000 scan x timeframe
    # opportunities on the Unit-1 tree:
    #
    #     OLD BOS positive deliveries   366
    #     genuine fresh transitions      88   (38 unique market events)
    #     persistent already-beyond     278   published as fresh events
    #     transitions OLD missed          0
    #
    # An EVENT requires evidence of a TRANSITION: the previous EXPECTED market
    # bucket on the unbroken side, this one beyond it. Nothing further is added
    # here -- no displacement requirement, no body ratio, no excursion minimum,
    # no close-quality rule. None of those is authorised by the evidence, and
    # inventing them would be doctrine rather than repair.
    position_above = last_swing_high is not None and last_close > last_swing_high
    position_below = last_swing_low is not None and last_close < last_swing_low

    prev_close = (transition or {}).get("previous_close")
    transition_state = (transition or {}).get("state")
    can_evaluate = transition_state == "EVALUABLE" and prev_close is not None

    if not can_evaluate:
        # Unevaluable is NOT an evaluated negative. The cause is preserved for
        # Unit 3 to carry across the Brain boundary; it is never collapsed into
        # a bare False here.
        bos_bullish = bos_bearish = False
        bos_evaluability = transition_state or "UNEVALUABLE_NO_TRANSITION_EVIDENCE"
    else:
        bos_bullish = position_above and prev_close <= last_swing_high
        bos_bearish = position_below and prev_close >= last_swing_low
        bos_evaluability = "EVALUATED"

    bos = bos_bullish or bos_bearish
    bos_dir = "bullish" if bos_bullish else "bearish" if bos_bearish else None

    # Market Structure Shift: a break AGAINST the prevailing structural bias.
    # The bias relation is preserved verbatim -- Unit 2 changes only WHICH breaks
    # qualify, never what makes a break a shift. A persistent already-beyond
    # state can no longer regenerate an MSS event every scan; measured, that was
    # 54 of OLD's 90 MSS deliveries, set-identical to its false positives.
    mss = (bos and bias == "bearish" and bos_dir == "bullish") or           (bos and bias == "bullish" and bos_dir == "bearish")

    if mss:
        state = f"{bos_dir}_reversal"
    elif bos and bias == "bullish":
        state = "bullish_continuation"
    elif bos and bias == "bearish":
        state = "bearish_continuation"
    elif last_swing_high and last_swing_low and last_swing_low < last_close < last_swing_high:
        state = "range_bound"
    else:
        state = "neutral"

    return {
        "bias": bias,
        "state": state,
        "last_swing_high": last_swing_high,
        "last_swing_low": last_swing_low,
        # UNIT 4 — the EXACT occurrence each published level came from, in this
        # candle list's index space. INTERNAL deterministic plumbing: it exists
        # so a consumer never has to guess identity back from a price. It is
        # deliberately NOT a Terra fact -- Unit 3 owns that boundary and swing
        # occurrence identity remains deferred there.
        "last_swing_high_pivot_index": last_swing_high_pivot_index,
        "last_swing_low_pivot_index": last_swing_low_pivot_index,
        "bos": bos,
        # UNIT 2: the evaluability of the EVENT, so an unevaluable transition is
        # never indistinguishable from an evaluated no-event. Unit 3 carries this
        # across the Brain boundary; it is preserved here so the truth exists to
        # be carried.
        "bos_evaluability": bos_evaluability,
        # The honest STATE proposition, named for what it actually is. `state`
        # below legitimately describes standing structure rather than an event,
        # and a consumer that genuinely needs "price is beyond the level" must
        # ask for that rather than reading an event field.
        "position_beyond_swing_high": position_above,
        "position_beyond_swing_low": position_below,
        "mss": mss,
        # UNIT 2: MSS inherits the transition's evaluability. When the transition
        # cannot be evaluated the public boolean is False for compatibility, but
        # the CAUSE survives -- a boolean fallback must never be able to
        # manufacture an MSS, and an unevaluable transition must never look like
        # an evaluated no-event.
        "mss_evaluability": ("EVALUATED" if can_evaluate
                             else "UNEVALUABLE_TRANSITION"),
        # STRUCTURE-FLIP (2026-08-11). `bos_dir` and the level it broke were
        # already computed here and then discarded, so every consumer saw only
        # `bos: True` -- a fact with no direction and no subject.
        #
        # On 2026-08-10 that cost a session. The 5m block reported
        # `last_swing_low 29801.25, bos True` while price traded 29783: a
        # bearish break through known support. Nothing downstream could say so,
        # so the only bearish invalidation the Brain was ever offered was a 15m
        # protected high 117 points away.
        #
        # Direction is asserted from the CLOSE that broke the level, never from
        # "price happens to be below an old swing". `broken_level` names the
        # subject so a consumer never has to guess which swing was broken.
        "bos_direction": bos_dir,
        "broken_level": (last_swing_low if bos_bearish
                         else last_swing_high if bos_bullish else None),
        "break_close": last_close if bos else None,
    }


def compute_alignment(tf_results: dict) -> str:
    """Scores cross-timeframe bias agreement. Ignores neutral/insufficient timeframes."""
    biases = [
        v.get("bias") for v in tf_results.values()
        if isinstance(v, dict) and v.get("bias") not in (None, "neutral")
        and v.get("state") != "insufficient_data"
    ]
    if not biases:
        return "neutral"
    dominant = max(set(biases), key=biases.count)
    ratio = biases.count(dominant) / len(biases)
    if ratio == 1.0:
        return "full"
    if ratio >= 0.75:
        return "strong"
    if ratio >= 0.5:
        return "partial"
    return "mixed"
