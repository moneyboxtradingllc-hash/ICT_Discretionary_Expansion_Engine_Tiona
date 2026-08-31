"""Displacement confluence — did institutions actually commit?

"When institutions commit, price should not simply drift away. It should expand
with conviction. If price merely teeters around after leaving consolidation, that
is weak evidence. If price rapidly accelerates away with large directional
candles and leaves inefficiencies behind, that is strong evidence."

The existing signal cannot express that. `displacement_detected` is a bare bool —
true when ANY candle in the last five has a body over an ATR-derived threshold.
It carries no magnitude, no direction, and no imbalance evidence, so a 1.4x
nudge and a 2.1x drive that tears three gaps in the tape are the same value.

Observed on 2026-07-24: the candles immediately after the order block ran 1.4x
and 0.6x average body, while the real expansion (2.1x, 1.6x) and every FVG landed
from 12:25 onward. A bool cannot separate those; a score with components can.

Six sources, scored by confluence and reported per-component:

  displacement_magnitude   largest body in the window, in ATR
  imbalance_created        FVGs left behind by the leg
  structure_break          BOS / MSS
  directional_efficiency   net travel vs total travel (leg-scoped upstream)
  follow_through           consecutive candles in one direction
  no_hesitation            share of the window opposing the move

Weights are starting values, NOT tuned. Telemetry lands before tuning.

WHAT THIS PRODUCES — STEP 3B (2026-08-13)
-----------------------------------------
A MECHANICAL WINDOW ASSESSMENT. Not a market-event detector.

It scores a FIXED TRAILING `LOOKBACK` window. It has no leg detection and no
start-of-move anchoring, so one conviction candle keeps the score elevated for
up to ten subsequent bars. Measured over 250 bars of the real Aug-12 tape:

    660 rolling readings   ->   10 magnitude-anchored objects
    588 / 660 (89%)             no magnitude witness at all
     55                         `displacement_confirmed` with NO candle
                                clearing MAGNITUDE_ATR_MULT
      0                         15m readings with any anchor, ever

`displacement_possible` / `displacement_confirmed` are therefore THIS
CLASSIFIER'S OPINION about accumulated weighted evidence. They are NOT
epistemic synonyms for "possible market event" / "confirmed market event", and
the word "confirmed" here must never elevate mechanical opinion into atomic
market fact. The Brain contract files this under DERIVED_ASSESSMENTS.

DELIBERATELY NOT CHANGED
------------------------
Magnitude is NOT mandatory for `displacement_confirmed`. Making it mandatory
would convert a weighted detector into a new mandatory-gate detector -- a
change to trading doctrine, made to fit an event ontology rather than because
evidence demanded it. No threshold, weight or lookback is tuned here. The
composite was demoted to its true jurisdiction instead.

Truth before tuning.
"""
from structure.direction_vote import resolve_direction_vote
from toolbox.price_levels import find_fvgs

# Component weights — unvalidated starting values.
W_MAGNITUDE   = 30
W_IMBALANCE   = 25
W_STRUCTURE   = 15
W_EFFICIENCY  = 15
W_FOLLOW      = 10
W_NO_HESITATE = 5

CONFIRMED_AT = 50
POSSIBLE_AT  = 25

# A displacement candle must clear this multiple of ATR to count as conviction.
MAGNITUDE_ATR_MULT = 1.5
EFFICIENCY_AT      = 0.30
FOLLOW_THROUGH_AT  = 3
HESITATION_MAX     = 0.40

LOOKBACK = 10
_MIN_CANDLES = 5


def _body(c):
    b = c.get("body_size")
    return b if b is not None else abs(c["close"] - c["open"])


def _dir_of(c):
    d = c.get("direction")
    if d in ("bullish", "bearish"):
        return d
    return "bullish" if c["close"] > c["open"] else ("bearish" if c["close"] < c["open"]
                                                    else "neutral")


def _magnitude(window, atr):
    """(present, detail, direction, magnitude_atr, anchor_candle).

    STEP 3A: `anchor_candle` is the largest-BODY bar -- the conviction candle the
    whole component is about. It was computed and thrown away, exactly as
    `analyze_liquidity` once discarded the swept level. It is returned (never
    scored) because it is the ONLY market object this rolling detector is
    anchored to, and therefore the only thing that can give a displacement a
    stable occurrence identity across a sliding window.
    """
    if not atr or atr <= 0:
        return False, "no atr", None, 0.0, None
    best, best_c = 0.0, None
    for c in window:
        m = _body(c) / atr
        if m > best:
            best, best_c = m, c
    if best_c is None:
        return False, "no candles", None, 0.0, None
    ok = best >= MAGNITUDE_ATR_MULT
    detail = (f"largest body {_body(best_c):.2f} = {best:.2f}x atr {atr:.2f} "
              f"({'>=' if ok else '<'} {MAGNITUDE_ATR_MULT}x)")
    # The anchor is published only when the component is PRESENT. A largest body
    # that never cleared the ATR threshold is not a conviction candle, and
    # letting it anchor an occurrence would manufacture identity out of a
    # component that voted for nothing.
    return (ok, detail, (_dir_of(best_c) if ok else None), round(best, 2),
            (best_c if ok else None))


#: STEP 4B §13 — WHAT THIS COMPONENT ACTUALLY PROVES.
#:
#: The score key is `imbalance_created` and the detail string says "imbalance
#: left behind", both of which claim the displacement leg CREATED these gaps.
#: The code does not establish that: `find_fvgs(window, direction)` scans the
#: ENTIRE trailing LOOKBACK window, so a gap that formed nine bars ago -- before
#: any displacement -- scores identically to one torn open by the conviction
#: candle. There is no leg-scoping, no anchor-relative filter, nothing tying a
#: returned gap to the move being assessed.
#:
#: The legacy key and weights are UNCHANGED (no tuning). What is published
#: alongside them is the proposition the producer can actually defend.
IMBALANCE_SEMANTIC_BASIS = "WINDOW_CONTAINS_DIRECTIONAL_FVG"
IMBALANCE_SEMANTIC_NOTE = (
    "the scored window contains directional FVG(s); the producer does NOT "
    "establish that this displacement leg created them")

#: STEP 4B.4 §1 — the precise name for what this component does.
#:
#: It is not an independent directional detector: it never asks what side the
#: FVG evidence supports, only whether a gap agreeing with the already-handed
#: leg exists. Nor is it literally the handed fact counted twice -- real
#: same-side geometry must be present for it to fire. Both descriptions were
#: reached and both were too strong.
IMBALANCE_DIRECTION_ROLE = "CONDITIONED_SAME_SIDE_FVG_CORROBORATION"


def _imbalance(window, direction, tf_minutes=None):
    if direction not in ("bullish", "bearish"):
        return False, "no leg direction to scan for imbalance", None, 0, []
    # STEP 4B.7 — NO CADENCE, NO IMBALANCE CLAIM.
    #
    # `find_fvgs` now REFUSES uncadenced canonical requests, because unknown
    # cadence was permission to trust array adjacency. A caller with no
    # timeframe (order_block_extractor scores a leg, not a series) therefore
    # cannot assert imbalance at all -- it cannot know whether its bars are
    # market-adjacent. The component reports ABSENT with the reason, rather
    # than scoring on geometry it cannot vouch for.
    if tf_minutes is None:
        return False, "no bar cadence: market adjacency unprovable", None, 0, []
    gaps = find_fvgs(window, direction, tf_minutes)
    if not gaps:
        return False, f"no {direction} imbalance left behind", None, 0, []
    total = sum(g["size"] for g in gaps)
    # STEP 3B §4B: the gaps themselves, not just a count. They are already
    # atomic FVG facts elsewhere in the chronology; a reader must be able to
    # see WHICH ones this assessment leaned on.
    return (True, (f"{len(gaps)} {direction} FVG(s), {total:.2f} pts total, "
                   f"largest {max(g['size'] for g in gaps):.2f}"),
            direction, len(gaps), list(gaps))


def _structure_break(struct):
    bos = bool((struct or {}).get("bos"))
    mss = bool((struct or {}).get("mss"))
    if bos or mss:
        parts = [n for n, v in (("BOS", bos), ("MSS", mss)) if v]
        return True, " + ".join(parts) + " on this timeframe", None
    return False, "no BOS or MSS", None


def _efficiency(exp):
    eff = (exp or {}).get("directional_efficiency")
    if not isinstance(eff, (int, float)):
        return False, "directional_efficiency unavailable", None
    ok = eff >= EFFICIENCY_AT
    return ok, (f"directional_efficiency {eff:.3f} "
                f"({'>=' if ok else '<'} {EFFICIENCY_AT})"), None


def _follow_through(window, tf: str = None):
    """(present, detail, vote, observed_run_direction, observed_run_length).

    STEP 3A: the OBSERVED run is returned even when it is too short to vote. A
    two-candle bearish run beside a bullish `direction` is a real directional
    disagreement, and it was previously visible only inside a detail string.
    The vote itself is unchanged -- a short run still earns no points and no
    vote.
    """
    if not window:
        return False, "no window", None, None, 0, []
    last = _dir_of(window[-1])
    if last == "neutral":
        return False, "final candle has no direction", None, None, 0, []

    # STEP 4B.12 §4 UNIT 5 — CONSECUTIVE MEANS CONSECUTIVE MARKET BARS.
    #
    # This walked ARRAY neighbours. A venue-open bucket with no observation is
    # never built, so its neighbours are array-adjacent and the walk crossed the
    # hole. Measured over 1000 evaluations: 11 times an observed run reached the
    # >=3 threshold on evidence that supports fewer, each buying W_FOLLOW points
    # AND a component vote -- and follow-through is one of only two independent
    # direction witnesses here. Final direction survived on the net-move fallback
    # in all 11, so this is an unauthorised VOTE rather than invented direction.
    #
    # The threshold and weight are untouched; only the run that reaches them is
    # corrected. `observed_run` is still returned so the observation survives.
    from market_data.evidence_continuity import authoritative_trailing_run
    _v = authoritative_trailing_run(window, tf, _dir_of)
    n = _v["observed_run"]                 # THE PRODUCER'S OWN CLAIM, unchanged
    authorised = _v["authoritative_run"]   # what market continuity supports

    # ONLY THE CREDIT IS GATED. `market_events` publishes this run beside its own
    # continuity verdict, and that contract requires the OBSERVED claim to keep
    # arriving intact -- reporting the truncated number here would delete the
    # very observation the publisher exists to place next to the continuity fact.
    ok = authorised >= FOLLOW_THROUGH_AT
    # STEP 3C §4: the EXACT bars the run is made of. A claim about N candles is
    # a claim about N observations, and publishing only the newest one let the
    # evidence for a multi-bar fact disappear again.
    run_bars = window[-n:] if n else []
    detail = f"{n} consecutive {last} candles ({'>=' if ok else '<'} {FOLLOW_THROUGH_AT})"
    if authorised != n:
        detail += (f"; only {authorised} market-contiguous "
                   f"({_v['continuity']}) -- credit withheld")
    return (ok, detail, (last if ok else None), last, n, list(run_bars))


def _net_travel(window):
    """Signed start-open -> end-close travel across the scored window."""
    try:
        return round(float(window[-1]["close"]) - float(window[0]["open"]), 4)
    except (TypeError, ValueError, KeyError, IndexError):
        return None


def _sign_direction(net):
    if not isinstance(net, (int, float)):
        return None
    return "bullish" if net > 0 else ("bearish" if net < 0 else "flat")


#: STEP 3A — do the intrinsic directional facts agree with each other?
#:
#: `direction` is a vote consensus; `net_travel` is where price actually
#: finished. A future tool must never read "direction == bullish" as a proven
#: bullish market fact while the leg closed lower than it opened. The
#: disagreement is EXPOSED, never resolved and never used to veto: it is
#: evidence for Terra, and a bullish impulse inside a leg that has not yet
#: delivered upward is a real and useful thing to be able to say.
ALIGNED = "aligned"
CONFLICTED = "conflicted"
NET_FLAT = "net_flat"
NO_DIRECTION = "no_direction"
UNMEASURABLE = "unmeasurable"


def _witnesses_conflict(*witnesses) -> bool:
    """Do the intrinsic directional witnesses disagree with each other?

    Reported, never acted on. A bullish conviction candle inside a leg that has
    not yet delivered upward is real and useful information, and collapsing it
    to one headline is how mechanics becomes a narrator.
    """
    seen = {w for w in witnesses if w in DIRECTIONS_OK}
    return len(seen) > 1


def _consistency(direction, net, vote_conflicted):
    if vote_conflicted or direction not in DIRECTIONS_OK:
        return NO_DIRECTION
    if not isinstance(net, (int, float)):
        return UNMEASURABLE
    if net == 0:
        return NET_FLAT
    return ALIGNED if _sign_direction(net) == direction else CONFLICTED


DIRECTIONS_OK = ("bullish", "bearish")


def _no_hesitation(window, direction):
    if direction not in ("bullish", "bearish") or not window:
        return False, "no leg direction", None
    opposing = sum(1 for c in window if _dir_of(c) not in (direction, "neutral"))
    share = opposing / len(window)
    ok = share <= HESITATION_MAX
    return ok, (f"{opposing}/{len(window)} candles oppose the {direction} leg "
                f"({share:.0%} {'<=' if ok else '>'} {HESITATION_MAX:.0%})"), None


def detect_displacement(candles: list, struct: dict = None, atr: float = None,
                        expansion: dict = None, authority: dict = None,
                        atr_provenance: dict = None, tf_minutes: int = None) -> dict:
    """Score institutional commitment by confluence over a lookback window."""
    components, votes = [], []

    def add(name, present, weight, detail, direction=None):
        components.append({"name": name, "present": bool(present),
                           "points": weight if present else 0,
                           "weight": weight, "detail": detail})
        if present and direction:
            votes.append(direction)

    if not candles or len(candles) < _MIN_CANDLES:
        return {"score": 0, "classification": "none", "direction": None,
                "direction_conflicted": False, "magnitude_atr": 0.0, "imbalance_count": 0, "components": [],
                "lookback": 0,
                # Same schema as a scored reading: a caller must not have to
                # branch on presence to learn there is no anchor and no
                # direction here.
                "direction_basis": "none", "direction_votes": [],
                "direction_vote": None, "magnitude_direction": None,
                "follow_through_direction": None,
                "follow_through_observed_direction": None, "follow_through_run": 0,
                "follow_through_run_bars": [], "follow_through_run_candles": [],
                "imbalance_vote_echoes_leg": False,
                "leg_direction": None, "leg_provenance": "NONE",
                "net_travel": None, "net_travel_direction": None,
                "direction_consistency": NO_DIRECTION,
                "directional_witnesses": {"magnitude": None,
                                          "follow_through_run": None,
                                          "net_travel": None},
                "witnesses_conflict": False,
                "conviction_candle": None, "imbalance_gaps": [],
                "imbalance_semantic_basis": IMBALANCE_SEMANTIC_BASIS,
                "imbalance_semantic_note": IMBALANCE_SEMANTIC_NOTE,
                "imbalance_conditioned_on_leg": True,
           # Visible, not silent: a caller without cadence gets no imbalance
           # evidence and the reader is told why.
           "imbalance_cadence_known": tf_minutes is not None,
           "imbalance_direction_role": IMBALANCE_DIRECTION_ROLE,
                "fvg_bullish_gaps": [], "fvg_bearish_gaps": [],
                "fvg_bullish_count": 0, "fvg_bearish_count": 0,
                "imbalance_same_side_count": 0, "imbalance_opposite_side_count": 0,
                "imbalance_directionally_permissive": False,
                "structure_evidence": {"bos": False, "mss": False},
                "directional_efficiency": None,
                "magnitude_anchor_time": None, "magnitude_anchor_body": None,
                "window_start_time": None, "window_end_time": None,
                "window_is_trailing_artifact": True,
                "reason": f"insufficient candles ({len(candles) if candles else 0})"}

    window = candles[-LOOKBACK:]

    present, detail, d, magnitude, anchor = _magnitude(window, atr)
    add("displacement_magnitude", present, W_MAGNITUDE, detail, d)
    magnitude_direction = d

    # NET TRAVEL — window[0].open -> window[-1].close. Published (STEP 3A)
    # because it is a DIFFERENT fact from the vote consensus below and the two
    # can legitimately disagree. It was already computed here for the `leg`
    # fallback and then discarded.
    net_travel = _net_travel(window)

    # Leg direction: the displacement candle names it; otherwise the net move.
    leg = d or ("bullish" if window[-1]["close"] > window[0]["open"] else
                "bearish" if window[-1]["close"] < window[0]["open"] else None)
    # STEP 4B.3 §2 — WHAT FACT PRODUCED THE DIRECTION `_imbalance` ECHOES?
    #
    # Published rather than inferred downstream, because the two cases are
    # materially different:
    #
    #   MAGNITUDE_WITNESS  the echo re-votes a fact ALREADY in the tally
    #                      -> a genuine duplicate
    #   NET_MOVE_FALLBACK  the echo votes for start->end travel, which casts no
    #                      vote of its own -> not a duplicate, but the tally's
    #                      only direction comes from non-independent evidence
    leg_provenance = ("MAGNITUDE_WITNESS" if d else
                      "NET_MOVE_FALLBACK" if leg else "NONE")

    present, detail, d, gaps, gap_objects = _imbalance(window, leg, tf_minutes)
    add("imbalance_created", present, W_IMBALANCE, detail, d)
    # STEP 4B.4 §2/§3 — THE TWO-SIDED FACT, computed but never scored.
    #
    # `_imbalance` asks "can I find an FVG agreeing with the direction I was
    # already handed?", never "what direction does the FVG evidence support?".
    # So a window holding three bullish and four bearish gaps returns BULLISH
    # when handed bullish and would have returned BEARISH when handed bearish --
    # from identical geometry.
    #
    # Both sides are published so that permissiveness is visible instead of
    # inferred. Scoring, weights and the component's own answer are untouched.
    _bull_gaps = find_fvgs(window, "bullish", tf_minutes) if tf_minutes else []
    _bear_gaps = find_fvgs(window, "bearish", tf_minutes) if tf_minutes else []
    _same = _bull_gaps if leg == "bullish" else _bear_gaps if leg == "bearish" else []
    _opp = _bear_gaps if leg == "bullish" else _bull_gaps if leg == "bearish" else []
    # NOT AN INDEPENDENT WITNESS. `_imbalance` is HANDED `leg` and returns it
    # back on success, so its vote is whatever magnitude (or the net-move
    # fallback) already said. Two entries in `votes`, one underlying fact.
    imbalance_echoes = bool(present and d and d == leg)

    present, detail, d = _structure_break(struct)
    add("structure_break", present, W_STRUCTURE, detail, d)

    present, detail, d = _efficiency(expansion)
    add("directional_efficiency", present, W_EFFICIENCY, detail, d)

    # UNIT 5: hand the continuity authority the horizon it needs. tf_minutes is
    # what this detector is given, so it is mapped to the label the authority
    # keys on; None simply lets the series infer its own cadence.
    _tf_label = {1: "1m", 3: "3m", 5: "5m", 15: "15m", 30: "30m", 60: "1h"}.get(
        tf_minutes)
    present, detail, d, ft_run_dir, ft_run_len, ft_run_bars = _follow_through(
        window, _tf_label)
    add("follow_through", present, W_FOLLOW, detail, d)
    follow_direction = d

    present, detail, d = _no_hesitation(window, leg)
    add("no_hesitation", present, W_NO_HESITATE, detail, d)

    raw = sum(c["points"] for c in components)
    score = min(100, raw)
    classification = ("displacement_confirmed" if score >= CONFIRMED_AT else
                      "displacement_possible" if score >= POSSIBLE_AT else "none")
    # CONTINUITY-2E.2 — was `max(set(votes), key=votes.count)`, whose tie-winner
    # depended on PYTHONHASHSEED. A tie now earns no direction. The pre-existing
    # `leg` fallback is preserved for the ABSENCE of votes, which is a different
    # state from a conflict -- but a TIE must NOT fall back to `leg`, because
    # that would be exactly the invented directional default 2E.2 forbids.
    direction, direction_conflicted = resolve_direction_vote(votes)
    # DIRECTION BASIS — four different epistemic states wore one field name.
    #
    #   component_vote              an INDEPENDENT witness won the tally
    #   imbalance_echo_of_net_move  the only voter was `_imbalance`, which was
    #                               handed the net-move `leg` and handed it back
    #   net_move_fallback           nothing voted; `leg` is bare start->end travel
    #   none                        a tie, or nothing at all
    #
    # The third row is the one that matters. Measured on the 15m at 19:24: no
    # candle cleared 1.5x ATR, structure was silent, efficiency was 0.094 and
    # the observed run was BEARISH -- yet `direction` read bullish because a
    # 2.00-point bullish FVG echoed a +10.75 net move. A first version of this
    # field called that a `component_vote`, which laundered a fallback into a
    # witness. Only `_magnitude` and `_follow_through` name a side from price
    # without being told one first.
    independent = tuple(v for v in (magnitude_direction, follow_direction) if v)
    vote_winner = direction
    if direction is not None:
        basis = "component_vote" if independent else "imbalance_echo_of_net_move"
    elif direction_conflicted:
        basis = "none"
    else:
        direction = leg
        basis = "net_move_fallback" if leg else "none"

    out = {"score": score, "raw_score": raw, "classification": classification,
           # COMPATIBILITY FIELD. Retained under its historical name so no
           # consumer changes meaning, but it is NOT synonymous with net travel
           # -- see `direction_consistency`.
           "direction": direction, "direction_conflicted": direction_conflicted,
           "direction_basis": basis,
           "direction_votes": list(votes),
           # STEP 3A — WHAT `direction` ACTUALLY MEANS.
           #
           # It is a consensus of body/follow-through witnesses, NOT the leg's
           # net travel. Measured on the real tape: 15m reported bullish with a
           # net move of -1.0, because the largest body was bullish (and
           # `_imbalance` echoed it) while the window finished lower than it
           # started. Both facts are true and both are published; nothing here
           # resolves them, because resolving them is Terra's job.
           "direction_vote": vote_winner,
           "magnitude_direction": magnitude_direction,
           "follow_through_direction": follow_direction,
           # The run as OBSERVED, whether or not it was long enough to vote.
           "follow_through_observed_direction": ft_run_dir,
           "follow_through_run": ft_run_len,
           # STEP 3C §4 — the EXACT bars, not the whole 10-bar window. A
           # three-candle run is a claim about three observations.
           "follow_through_run_bars": [b.get("timestamp") for b in ft_run_bars],
           "follow_through_run_candles": list(ft_run_bars),
           "imbalance_vote_echoes_leg": imbalance_echoes,
           "leg_direction": leg,
           "leg_provenance": leg_provenance,
           "net_travel": net_travel,
           "net_travel_direction": _sign_direction(net_travel),
           "direction_consistency": _consistency(direction, net_travel,
                                                 direction_conflicted),
           # EVERY intrinsic directional witness, named, with nothing resolved.
           # `direction_consistency` compares the headline against net travel;
           # this exposes the rest so a short bearish run under a bullish
           # headline cannot hide inside a detail string.
           "directional_witnesses": {"magnitude": magnitude_direction,
                                     "follow_through_run": ft_run_dir,
                                     "net_travel": _sign_direction(net_travel)},
           "witnesses_conflict": _witnesses_conflict(
               magnitude_direction, ft_run_dir, _sign_direction(net_travel)),
           "magnitude_atr": magnitude,
           # THE CONVICTION CANDLE — a PHYSICAL fact with its own geometry, not
           # a property of this assessment. STEP 3B promotes it to an atomic
           # object in its own right; what is published here is the reference
           # and the geometry needed to build it. Absent when no body cleared
           # the ATR threshold, in which case this assessment has no physical
           # occurrence to point at.
           "magnitude_anchor_time": (anchor or {}).get("timestamp"),
           "magnitude_anchor_body": (round(_body(anchor), 4) if anchor else None),
           "conviction_candle": (None if anchor is None else {
               # ── PHYSICAL, true at the candle's own timestamp ──
               "timestamp": anchor.get("timestamp"),
               "open": anchor.get("open"), "high": anchor.get("high"),
               "low": anchor.get("low"), "close": anchor.get("close"),
               "body": round(_body(anchor), 4),
               "direction": _dir_of(anchor),
               # ── DERIVED, true only when this assessment computed it ──
               #
               # STEP 3C §1/§3. `atr` is the caller's ATR, which
               # `snapshot_builder` computes as `calculate_atr(settled)` -- a
               # trailing 14-period SMA ending at the NEWEST settled bar, i.e.
               # ASSESSMENT time. The anchor candle may sit up to LOOKBACK-1
               # bars in the past, so this ratio can be an old body measured
               # against a newer scale. The denominator's as-of time is
               # published so nobody can read the ratio as an anchor-time fact.
               "atr": atr,
               "atr_multiple": magnitude,
               "atr_as_of": (window[-1] or {}).get("timestamp"),
               "atr_source": "calculate_atr(settled) at assessment time",
               "threshold_atr_multiple": MAGNITUDE_ATR_MULT,
               "qualified_at": (window[-1] or {}).get("timestamp"),
               # STEP 3D — the DENOMINATOR'S OWN EVIDENCE. Supplied by the
               # caller that computed the ATR; this detector receives a float
               # and cannot know its provenance, so it never invents one.
               "atr_period": (atr_provenance or {}).get("period"),
               "atr_source_bars": [b.get("timestamp") for b
                                   in ((atr_provenance or {}).get("source_bars") or [])],
               "atr_source_candles": list((atr_provenance or {}).get("source_bars") or []),
               }),
           # WHY THE SCORE IS WHAT IT IS (§5). Each component's underlying
           # value, not just its detail prose.
           "imbalance_gaps": list(gap_objects),
           # §13: the name may not claim causation the producer never proved.
           "imbalance_semantic_basis": IMBALANCE_SEMANTIC_BASIS,
           "imbalance_semantic_note": IMBALANCE_SEMANTIC_NOTE,
           # §1: the component's direction is CONDITIONED on the handed leg.
           "imbalance_conditioned_on_leg": True,
           # Visible, not silent: a caller without cadence gets no imbalance
           # evidence and the reader is told why.
           "imbalance_cadence_known": tf_minutes is not None,
           "imbalance_direction_role": IMBALANCE_DIRECTION_ROLE,
           # §2/§24: BOTH sides, always. A handed direction may not hide
           # opposite-side physical FVG facts from Terra.
           "fvg_bullish_gaps": list(_bull_gaps),
           "fvg_bearish_gaps": list(_bear_gaps),
           "fvg_bullish_count": len(_bull_gaps),
           "fvg_bearish_count": len(_bear_gaps),
           "imbalance_same_side_count": len(_same),
           "imbalance_opposite_side_count": len(_opp),
           # §3: would the SAME window have fired for the opposite leg?
           "imbalance_directionally_permissive": bool(_same and _opp),
           "structure_evidence": {"bos": bool((struct or {}).get("bos")),
                                  "mss": bool((struct or {}).get("mss"))},
           "directional_efficiency": (expansion or {}).get("directional_efficiency"),
           # The window is a DETECTOR ARTEFACT (`candles[-LOOKBACK:]`), not a
           # measured leg. Named so nobody reads `window_start_time` as the
           # moment the displacement began.
           "window_start_time": (window[0] or {}).get("timestamp"),
           "window_end_time": (window[-1] or {}).get("timestamp"),
           "window_is_trailing_artifact": True,
           "imbalance_count": gaps, "components": components,
           "lookback": len(window)}

    # Coherence with standing authority — reported, never used to rewrite the
    # score. Displacement against authority is real displacement; it is the
    # authority that is then in question, and that call is not made here.
    if authority and authority.get("bias") in ("bullish", "bearish"):
        if direction in ("bullish", "bearish"):
            agrees = direction == authority["bias"]
            out["authority_coherence"] = {
                "coherent": agrees,
                "note": (f"{direction} displacement "
                         f"{'delivers' if agrees else 'opposes'} "
                         f"{authority['bias']} authority")}
        else:
            out["authority_coherence"] = {"coherent": None,
                                          "note": "displacement has no direction"}
    return out


def format_displacement(d: dict) -> str:
    lines = ["Displacement Score:", ""]
    for c in d.get("components", []):
        lines.append(f"  {c['name']:<24} {('+' + str(c['points'])) if c['points'] else '0':>5}"
                     f"   {c['detail']}")
    lines += ["", f"  Total: {d.get('score', 0)}/100",
              f"  Classification: {d.get('classification', 'none')}"]
    if d.get("direction"):
        lines.append(f"  Direction: {d['direction']}")
    if d.get("authority_coherence"):
        lines.append(f"  Authority: {d['authority_coherence']['note']}")
    return "\n".join(lines)
