from structure.structure_engine import find_swings

MIN_CANDLES = 4


#: STEP 4B.12 §4 — THE PRIOR BAR MUST BE THE PREVIOUS EXPECTED MARKET SLOT.
#:
#: `prior = candles[-2]["close"]` asked for "where price sat immediately before
#: this bar", but `candles` arrives already filtered: `snapshot_builder` drops
#: FORMING and HISTORICAL_INCOMPLETE buckets before calling. When the dropped
#: bucket sat at position -2, `candles[-2]` was the bar BEFORE the previous
#: market slot, and the raid predicate compared against a stale price.
#:
#: Measured on 2026-08-12, all four traceable to ONE absent 1m observation at
#: 18:11:
#:
#:     15m 17:45 -> [18:00] -> 18:15   15 exposures,  0 output impact
#:      5m 18:05 -> [18:10] -> 18:15    5 exposures,  5 PROVEN FALSE POSITIVES
#:      3m 18:06 -> [18:09] -> 18:12    3 exposures,  3 unsupported (close UNPROVEN)
#:      1m 18:10 -> [18:11] -> 18:12    1 exposure,   1 unsupported (no observation)
#:
#: The 5m witness: bridged close 29899.50 vs authoritative 29907.50, which made
#: 29900.0 look like it was resting ABOVE price when the previous expected bar
#: had already closed above it.
#:
#: A DEGRADED CANDLE IS NOT A DEGRADED FIELD. The 5m and 15m buckets missing
#: 18:11 have unprovable HIGH and LOW -- the absent minute could hold either
#: extremum -- yet their CLOSE is fully authoritative because `_aggregate` takes
#: `bars[-1]["close"]` and their terminal constituent (18:14) is present. The 3m
#: bucket's terminal constituent IS 18:11, so its close is unprovable.
#:
#: So the rule is field-scoped, not candle-scoped:
#:
#:     previous expected slot absent      -> withhold; never bridge backward
#:     present, CLOSE unprovable          -> withhold; never substitute
#:     present, CLOSE authoritative       -> use it, even if high/low are not
PRIOR_ADJACENT = "ADJACENT_SETTLED"
PRIOR_AUTHORITATIVE = "PREVIOUS_SLOT_CLOSE_PROVEN"
PRIOR_CLOSE_UNPROVEN = "PREVIOUS_SLOT_CLOSE_UNPROVEN"
PRIOR_NO_OBSERVATION = "PREVIOUS_SLOT_NOT_OBSERVED"
PRIOR_UNCADENCED = "UNCADENCED_LEGACY"
#: §9 RESIDUE + §10. The previous EXPECTED market slot cannot be identified at
#: all, because venue cadence authority is unknown or unavailable. Deliberately
#: NOT folded into the two neighbours it superficially resembles:
#:
#:   PRIOR_NO_OBSERVATION  claims a slot was expected and was not observed.
#:                         Absence was PROVEN there. Here nothing is proven.
#:   PRIOR_CLOSE_UNPROVEN  presupposes a previous bucket was identified and
#:                         asks about its CLOSE. Here we never got that far.
#:
#: An unverified schedule is not a data gap. The unknown belongs to cadence.
PRIOR_CADENCE_UNKNOWN = "PREVIOUS_SLOT_CADENCE_UNKNOWN"


#: STEP 4B.12 §10 — A VALUE IS NOT AN AUTHORISATION.
#:
#: The resolver asked `prior_close is not None`. A float is not evidence that
#: the float may author this proposition, and under a calendar failure the
#: bridged array-neighbour close is a perfectly good float. Measured on the real
#: engine: a forced calendar failure published `sweep_detected` computed from
#: `candles[-2]` while the honest signal sat in a different field.
#:
#: Repairing only the Brain-facing LABEL would have been worse than useless. The
#: consumer audit showed scoring, routing and positive-trigger consumers read the
#: BOOLEANS and never read capability -- so a capability-only fix produces two
#: different realities inside one engine: Terra told UNEVALUABLE while a scorer
#: is handed True. The refusal therefore lives at the AUTHORING boundary; the
#: capability label is derived from the same decision rather than asserted beside
#: it.
#:
#: One table, exhaustive over the states the resolver can actually return, so the
#: next authority value cannot become "good enough" by carrying a number.
PRIOR_MAY_AUTHOR = {
    PRIOR_ADJACENT:        True,   # cadence KNOWN and no slot sits between
    PRIOR_AUTHORITATIVE:   True,   # terminal constituent observed
    PRIOR_CLOSE_UNPROVEN:  False,
    PRIOR_NO_OBSERVATION:  False,
    PRIOR_CADENCE_UNKNOWN: False,
    PRIOR_UNCADENCED:      False,  # caller supplied no cadence at all
}

#: Why, in the vocabulary of the ACTUAL missing prerequisite. A calendar-authority
#: failure must not be reported in words that imply better price data would fix
#: it -- nothing about the candles is wrong in that case.
PRIOR_UNEVALUABLE_REASON = {
    PRIOR_CLOSE_UNPROVEN:  "PREVIOUS_SLOT_CLOSE_UNPROVEN",
    PRIOR_NO_OBSERVATION:  "PREVIOUS_SLOT_NOT_OBSERVED",
    PRIOR_CADENCE_UNKNOWN: "EXPECTED_SLOT_AUTHORITY_UNAVAILABLE",
    PRIOR_UNCADENCED:      "NO_CADENCE_SUPPLIED",
}


#: STEP 4B.12 §5 — A NEGATIVE IS A CLAIM, AND IT NEEDS A CAPABILITY BEHIND IT.
#:
#: `False` asserts that a capable detector looked and did not find the pattern.
#: Three situations were all being published as that single word:
#:
#:     EVALUATED             detector able, evidence present, pattern absent
#:     UNEVALUABLE_EVIDENCE  detector able, required evidence unavailable
#:     UNAVAILABLE_SENSOR    detector itself cannot evaluate the proposition
#:
#: The third is not hypothetical here. See FAILED_BREAKOUT_UNREACHABLE below.
CAPABILITY_EVALUATED = "EVALUATED"
CAPABILITY_UNEVALUABLE_EVIDENCE = "UNEVALUABLE_EVIDENCE"
CAPABILITY_UNAVAILABLE_SENSOR = "UNAVAILABLE_SENSOR"

#: `failed_breakout` below is DEAD BY CONSTRUCTION — proven, not suspected, by
#: two INDEPENDENT contradictions. Measured: 1000 evaluations of the real MNQ
#: tape, sweep_detected TRUE 412, failed_breakout TRUE 0.
#:
#:   1. CONTROL FLOW. The high branch is reached only when
#:      `last_close >= ref_high`, and its body requires `last_close < ref_high`.
#:      Symmetric on the low side.
#:
#:   2. CANDIDATE UNIVERSE. `ref_high = max(pierced_highs)`, and membership of
#:      that pool already guarantees `prior <= ref_high`, while the predicate
#:      requires `prior > ref_high`. Symmetric on the low side.
#:
#: (2) is the deeper one: the proposition cannot live under `if pierced_highs:`
#: at ALL. Pool membership asserts the prior close sat INSIDE the level; a
#: failed breakout asserts it sat BEYOND it. Deleting the `elif` would have
#: looked like a repair and left the branch just as dead.
#:
#: NOT REPAIRED HERE, deliberately. A reachable sibling exists —
#: `manipulation_detector._failed_breakout`, which fires 202 times over those
#: same 1000 evaluations and carries the only docstring in the repo for the
#: concept — but it draws its reference from `max(highs)` rather than a pierced
#: pool and scans the whole lookback rather than the last bar. Which of the two
#: expresses this bot's market doctrine is an open question, and the +40 that
#: `_score_failed_breakout_reversal` awards for this field is a scoring contract
#: that must not be re-plumbed as a side effect of an epistemics repair.
#:
#: Until that doctrine is settled, the honest published value is not `False`.
FAILED_BREAKOUT_UNREACHABLE = "PREDICATE_UNREACHABLE_DOCTRINE_UNRESOLVED"


#: Which published fact depends on what. `nearest_*` rest on `find_swings` and
#: the CURRENT close only; the raid family additionally needs an authoritative
#: previous-slot close. `failed_breakout` needs a sensor that does not exist.
_PRIOR_CLOSE_DEPENDENT = ("sweep_detected", "sweep_direction", "reclaim_detected")
_PRIOR_CLOSE_INDEPENDENT = ("nearest_buy_side_liquidity", "nearest_sell_side_liquidity")


def _capability(*, evidence_available: bool, prior_close_provable: bool) -> dict:
    """Capability class per published proposition.

    Sensor unavailability DOMINATES evidence unavailability: `failed_breakout`
    would be unevaluable even with perfect evidence, so it never degrades to
    UNEVALUABLE_EVIDENCE when the prior close is missing. Reporting it as an
    evidence problem would imply that better evidence could fix it.
    """
    def ev(dependent_on_prior_close: bool) -> str:
        if not evidence_available:
            return CAPABILITY_UNEVALUABLE_EVIDENCE
        if dependent_on_prior_close and not prior_close_provable:
            return CAPABILITY_UNEVALUABLE_EVIDENCE
        return CAPABILITY_EVALUATED

    caps = {name: ev(True) for name in _PRIOR_CLOSE_DEPENDENT}
    caps.update({name: ev(False) for name in _PRIOR_CLOSE_INDEPENDENT})
    caps["failed_breakout"] = CAPABILITY_UNAVAILABLE_SENSOR
    return caps


def _capability_reason(*, evidence_available: bool, prior_close_provable: bool,
                       prior_authority: str = None) -> dict:
    """Why, for every proposition that is not plainly EVALUATED. Present-only:
    an EVALUATED fact needs no excuse, and listing one invites a consumer to
    treat every negative as suspect.

    §10: the reason names the ACTUAL missing prerequisite. A calendar-authority
    failure reported as a close/observation problem would tell a reader that
    better price data could repair it. Nothing is wrong with the candles there.
    """
    reasons = {"failed_breakout": FAILED_BREAKOUT_UNREACHABLE}
    if not evidence_available:
        for name in _PRIOR_CLOSE_DEPENDENT + _PRIOR_CLOSE_INDEPENDENT:
            reasons[name] = "INSUFFICIENT_OBSERVATIONS"
    elif not prior_close_provable:
        why = PRIOR_UNEVALUABLE_REASON.get(prior_authority,
                                           "PREVIOUS_SLOT_CLOSE_UNAVAILABLE")
        for name in _PRIOR_CLOSE_DEPENDENT:
            reasons[name] = why
    return reasons


def analyze_liquidity(candles: list, prior: dict = None, *,
                      swing_evidence: dict = None,
                      allow_uncadenced: bool = False) -> dict:
    """Liquidity raids. `prior` carries the previous EXPECTED slot's close and
    the AUTHORITY behind it. Prior-close-dependent facts are authored only from
    an authorising state (see `PRIOR_MAY_AUTHOR`); otherwise they are withheld,
    never bridged to the array neighbour.

    `allow_uncadenced` is the explicit legacy opt-in, mirroring
    `price_levels.find_fvgs`. A caller with no cadence must now say so out loud
    instead of inheriting a bridge by omission.
    """
    empty = {
        "sweep_detected": False,
        "sweep_direction": None,
        "reclaim_detected": False,
        "failed_breakout": False,
        "nearest_buy_side_liquidity": None,
        "nearest_sell_side_liquidity": None,
        # LIQUIDITY-SWEEP-EPISODE-IDENTITY-1 — the birth evidence of a sweep,
        # or None when no sweep was observed. Absent is absent; never {}.
        "sweep_fact": None,
    }

    if len(candles) < MIN_CANDLES:
        # Nothing here was evaluated -- there were not enough observations to
        # evaluate anything. Publishing bare `False` claimed otherwise.
        empty["proposition_capability"] = _capability(
            evidence_available=False, prior_close_provable=False)
        empty["capability_reason"] = _capability_reason(
            evidence_available=False, prior_close_provable=False)
        return empty

    # STEP 4B.12 §4 UNIT 1 — the LEVELS themselves need canonical authority.
    # Measured: 53 swing occurrences withheld and 203 output exposures changed
    # across 250 scans when this call used survivor-array neighbourhoods. The
    # caller supplies evidence resolved by the market-data owner; without it the
    # pivot neighbourhood is unproven and the swings are withheld rather than
    # bridged. (The prior-close authority unit is CLOSED and untouched -- this
    # is the level SOURCE, a dependency that unit explicitly deferred.)
    highs, lows = find_swings(candles, evidence=swing_evidence,
                              allow_uncadenced=allow_uncadenced)

    last = candles[-1]
    last_close = last["close"]
    last_high = last["high"]
    last_low = last["low"]

    sweep_detected = False
    sweep_direction = None
    reclaim_detected = False
    failed_breakout = False
    # LIQUIDITY-SWEEP-EPISODE-IDENTITY-1. `ref_high`/`ref_low` below IS the
    # level the tape actually took. It was computed, compared against, and then
    # dropped on the floor -- so every downstream consumer could learn THAT a
    # sweep happened and never WHICH level it took or WHEN. `nearest_*` below is
    # "nearest pool right now" and is NOT a retrospective substitute for it.
    swept_level = None

    # Which swing is price actually raiding?
    #
    # This used to reference highs[-1] / lows[-1] — the chronologically most
    # recent swing, regardless of where it sits relative to price. That tests a
    # different level than this same function publishes as liquidity below
    # (nearest_buy_side_liquidity correctly filters to swings ABOVE price).
    #
    # The consequence was silent and total on higher timeframes: once the newest
    # swing high sat below price, `last_high > ref_high` was trivially true and
    # `last_close < ref_high` could never be true, so no sweep was reportable —
    # while the pool price was genuinely raiding went untested. Measured on
    # 2026-07-24 RTH: price breached a published 15m level on 23 of 133 scans
    # and sweep_detected was False on all 133, which starved PO3's three
    # direction fields to fallback_none and left directional authority #2 mute
    # for the entire session.
    #
    # A sweep is a pool that was pierced and rejected, so the reference is the
    # highest swing high the bar actually reached above (or the lowest swing low
    # it reached below) — not whichever swing happened to form last.
    # A raid has three parts: the pool was RESTING beyond price, this bar
    # REACHED it, and the close came back. All three are required — filtering on
    # "pierced" alone would mark every close below any nearby lower swing high as
    # a sweep (measured: 105 of 133 scans on 1m, which is noise, not raids).
    # STEP 4B.12: the caller resolves the previous EXPECTED slot. Absent that,
    # the array neighbour is NOT assumed to be the previous market bar.
    # §10 — AUTHORITY DECIDES, NOT VALUE PRESENCE. `PRIOR_MAY_AUTHOR` is the one
    # place that answers "may this state supply the previous close to the raid
    # predicates". A state absent from the table is treated as NOT authorised:
    # an unrecognised authority is an unknown one, and unknown never authorises.
    prior_authority = (prior or {}).get("authority", PRIOR_UNCADENCED)
    # Captured HERE, not at the return: `prior` is rebound to the float
    # `prior_close` below, so reading it later gets a number and an
    # AttributeError. The integrated regression caught that immediately.
    prior_cadence_rule = (prior or {}).get("cadence_rule")
    may_author = PRIOR_MAY_AUTHOR.get(prior_authority, False)
    if allow_uncadenced and prior_authority == PRIOR_UNCADENCED:
        # Explicit legacy opt-in for the uncadenced callers (test/diagnostic
        # only; no production importer). Bridging is a decision a caller now has
        # to make out loud rather than inherit by omission.
        may_author = True
        prior_close = (candles[-2]["close"] if len(candles) >= 2
                       else last["open"])
    elif may_author:
        prior_close = (prior or {}).get("close")
        if prior_close is None:
            # ADJACENT with no close recorded: the array neighbour IS the
            # previous market slot here (cadence known), so this is not a bridge.
            prior_close = candles[-2]["close"] if len(candles) >= 2 else last["open"]
    else:
        prior_close = None            # withhold: no bridging, no substitution
    # STEP 4B.12 — AUTHORITY IS PROPOSITION-SCOPED.
    #
    # The first repair returned an EMPTY liquidity object whenever prior-close
    # authority failed, which also nulled `nearest_buy_side_liquidity` and
    # `nearest_sell_side_liquidity`. Traced dependencies:
    #
    #   nearest_*        highs/lows + CURRENT close        -> independent
    #   sweep_detected   pierced pools -> prior            -> dependent
    #   sweep_direction  the sweep branch                  -> dependent
    #   reclaim_detected the sweep branch                  -> dependent
    #   failed_breakout  pierced pools AND a second direct
    #                    read of candles[-2] as prev_close -> dependent, twice
    #
    # One evidence defect may not erase an independent fact. When prior close is
    # unproven the pierced pools are simply empty, so every dependent
    # proposition falls out naturally -- the nearest-liquidity facts below are
    # computed regardless and survive on their own evidence.
    #
    # NOTE: `nearest_*` being PRIOR-CLOSE-INDEPENDENT is not a claim that they
    # are unconditionally authoritative; they still rest on `find_swings`, whose
    # own adjacency semantics remain under audit.
    prior_close_dependent_provable = prior_close is not None
    prior = prior_close
    pierced_highs = ([h for h in highs if prior <= h < last_high]
                     if prior_close_dependent_provable else [])
    pierced_lows = ([l for l in lows if last_low < l <= prior]
                    if prior_close_dependent_provable else [])

    # Sweep above swing high: wick pierced it but close is back below
    if pierced_highs:
        ref_high = max(pierced_highs)
        if last_close < ref_high:
            sweep_detected = True
            sweep_direction = "above_high"
            reclaim_detected = True
            swept_level = ref_high
        elif prior_close_dependent_provable:
            # STEP 4B.12: consumes the SAME resolved prior-close fact. It used
            # to re-read `candles[-2]["close"]`, a second synthetic-adjacency
            # path under a different name that would have survived repairing
            # the pierced pools alone.
            if prior > ref_high and last_close < ref_high:
                failed_breakout = True

    # Sweep below swing low: wick pierced it but close is back above
    if not sweep_detected and pierced_lows:
        ref_low = min(pierced_lows)
        if last_close > ref_low:
            sweep_detected = True
            sweep_direction = "below_low"
            reclaim_detected = True
            swept_level = ref_low
        elif not failed_breakout and prior_close_dependent_provable:
            if prior < ref_low and last_close > ref_low:
                failed_breakout = True

    # ── THE BIRTH EVIDENCE OF ONE SWEEP ─────────────────────────────────────
    # EVIDENCE, NOT IDENTITY. No `occurrence_id` is minted here: this engine
    # owns DETECTION truth, and `market_events` owns what canonical object that
    # fact is. Two authorities, one question each -- minting an id here would be
    # the second identity theorem the repository already forbids.
    #
    # `reclaimed` is an ATTRIBUTE of the sweep, never its own event: this
    # detector only ever declares a sweep when ONE settled candle both pierced
    # the level and closed back through it. A multi-bar reclaim would need its
    # own detector before it earned its own event, so no SWEPT->RECLAIMED
    # lifecycle is invented from a predicate that cannot observe one.
    sweep_fact = None
    if sweep_detected and swept_level is not None:
        when = last.get("timestamp") or last.get("time") or last.get("t")
        sweep_fact = {
            "source_tf": None,          # the caller owns cadence, not this engine
            "event_time": when,
            "sweep_direction": sweep_direction,
            "liquidity_side_taken": ("buy_side" if sweep_direction == "above_high"
                                     else "sell_side"),
            "swept_level": round(float(swept_level), 2),
            # No canonical swing identity exists upstream; `find_swings` returns
            # bare prices. Say so rather than manufacturing an id downstream.
            "swept_level_id": None,
            "reclaimed": bool(reclaim_detected),
            "reclaimed_at": when if reclaim_detected else None,
            "reclaim_basis": ("same_bar_close_back_through_level"
                              if reclaim_detected else None),
            "source_bars": [c.get("timestamp") or c.get("time")
                            for c in candles[-2:]],
        }
        # LUNA-LIQUIDITY-SCOPE-TRUTH-1 (2026-09-01). SCOPE IS STAMPED HERE,
        # ONCE, because this is the only moment the pivot set that judged the
        # event is still the pivot set that existed. `manipulation_detector`
        # re-derived internal/external every scan from a rolling
        # `candles[-40:]`, so a later higher swing rewrote what an earlier
        # sweep WAS -- proven: pivots [100,110] gave EXTERNAL, and
        # [100,110,120] gave INTERNAL for the identical candle.
        #
        # NO PO3 DEPENDENCY HERE, DELIBERATELY. `session_po3` already consumes
        # this engine; reaching the other way would close a cycle. The session
        # scope is stamped by the scan cycle, which owns both facts.
        from market_data.liquidity_scope import stamp as _scope_stamp
        sweep_fact.update(_scope_stamp(
            sweep_fact, highs=highs, lows=lows, po3_range=None,
            context_start=(candles[0].get("timestamp") if candles else None),
            context_end=when))

    # Buy-side liquidity: resting stops above price (at swing highs above current close)
    above = [h for h in highs if h > last_close]
    buy_side = round(min(above), 2) if above else None

    # Sell-side liquidity: resting stops below price (at swing lows below current close)
    below = [l for l in lows if l < last_close]
    sell_side = round(max(below), 2) if below else None

    return {
        "prior_close_authority": prior_authority,
        # §11 — SAME CONSEQUENCE, DIFFERENT CAUSE. An unverified schedule and a
        # calendar machinery failure both yield PRIOR_CADENCE_UNKNOWN and both
        # tell Terra EXPECTED_SLOT_AUTHORITY_UNAVAILABLE, which is right: the
        # proposition-level consequence really is identical, and Terra has no
        # use for implementation detail. But they are operationally different
        # incidents, and the integrated regression caught that the two produced
        # BYTE-IDENTICAL output everywhere downstream -- so a forensic reader
        # could never tell "we have no calendar for this date" from "the
        # calendar raised". Diagnostics keep the cause; the Brain does not.
        **({"prior_cadence_rule": prior_cadence_rule}
           if prior_cadence_rule else {}),
        "sweep_detected": sweep_detected,
        "sweep_direction": sweep_direction,
        "reclaim_detected": reclaim_detected,
        "failed_breakout": failed_breakout,
        # The three booleans above are UNCHANGED for all twenty existing
        # consumers. `sweep_fact` is additive: the facts this engine already
        # knew at the instant of detection and used to discard.
        "sweep_fact": sweep_fact,
        "nearest_buy_side_liquidity": buy_side,
        "nearest_sell_side_liquidity": sell_side,
        # The boolean above is retained unchanged for every existing consumer;
        # what is NEW is that the consumer can now tell a looked-and-found-none
        # from a could-not-look and from a cannot-look-at-all.
        "proposition_capability": _capability(
            evidence_available=True,
            prior_close_provable=prior_close_dependent_provable),
        "capability_reason": _capability_reason(
            evidence_available=True,
            prior_close_provable=prior_close_dependent_provable,
            prior_authority=prior_authority),
    }
