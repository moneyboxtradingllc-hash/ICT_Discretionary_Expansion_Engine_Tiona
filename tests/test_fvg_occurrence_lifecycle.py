"""STEP 4B.12 §6 UNIT 6 — A KILLED FVG STAYS KILLED, AND MECHANICS DOES NOT CHOOSE.

The plain-FVG zone was built from `gaps[0]`: the newest three-candle imbalance,
whatever had happened to it since. The engine already owned a zone-death test --
`_is_invalidated` -- but it reads only where price sits RIGHT NOW, so an
occurrence that had been conclusively closed through came back to life the moment
price returned to the other side of it.

Measured over 2000 production-shaped evaluations on the 2026-08-12 tape:

    newest occurrence dead under BOTH notions           991   49.5%
    newest occurrence live under BOTH notions           798   39.9%
    HISTORICALLY RETIRED BUT CURRENTLY "LIVE"           211   10.6%   <-- the defect
    instantaneously dead only                             0    0.0%

    unique FVG occurrences in the corpus                 507
    occurrence DELIVERIES (re-found each scan)       118416   (deliveries, not objects)

THE RETIREMENT THEOREM IS THIS PROJECT'S OWN, recovered rather than imported:
`tool_readiness` already tells Terra "FVG filled ... imbalance resolved, setup
gone"; `entry_trigger_prep` already says "gap fully filled AGAINST INTENDED
DIRECTION" and "no opposing displacement candle CLOSING THROUGH zone"; and
`_is_invalidated` already treats the far boundary as decisive. An authoritative
settled CLOSE through the far boundary retires the occurrence, permanently.

WHAT UNIT 6 DOES NOT DO. It does not substitute. `build_price_level` already
states the law -- "an ineligible zone is returned as itself, marked ineligible.
It is never swapped for an older gap" -- so a retired newest occurrence is
reported as retired, NOT quietly replaced by an older one. Choosing among lawful
occurrences belongs to the selector. It also does not touch `ifvg` or
`opening_fvg`: retirement is a plain-FVG predicate, and a later inversion
theorem may need precisely the occurrences plain-FVG doctrine has retired.
"""
import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))

from toolbox.price_levels import (  # noqa: E402
    LIFECYCLE_NOT_LOCATABLE, LIFECYCLE_NO_SETTLED_AUTHORITY,
    LIFECYCLE_SLOT_COVERAGE_UNPROVEN,
    RETIREMENT_CLOSE_THROUGH, _build_zone_for_family, _find_fvg,
    _is_invalidated, fvg_lifecycle, fvg_occurrence_id, fvg_occurrences,
    lawful_fvg_candidates)

CONTRACT = "CON.F.US.MNQ.U26"


def c(hhmm, o, h, l, cl, temporal_status="settled"):
    """A PRODUCTION-SHAPED bar. Normalized candles carry `temporal_status` (2G)
    and `contract`, and Unit 6 needs both: settlement to authorise a retirement,
    contract to mint the canonical occurrence id."""
    return {"timestamp": f"2026-08-12T{hhmm}:00+00:00", "open": o, "high": h,
            "low": l, "close": cl, "volume": 10, "contract": CONTRACT,
            "temporal_status": temporal_status,
            "direction": "bullish" if cl > o else "bearish" if cl < o else "neutral"}


def bull_gap():
    """A bullish FVG: c1.high=101 < c3.low=103 -> gap [101, 103]."""
    return [c("18:00", 100, 101, 99, 100.5),
            c("18:03", 102, 106, 102, 105),
            c("18:06", 106, 108, 103, 107)]


def bear_gap():
    """A bearish FVG: c1.low=99 > c3.high=96 -> gap [96, 99]."""
    return [c("18:00", 100, 101, 99, 99.5),
            c("18:03", 96, 96, 92, 93),
            c("18:06", 95, 96, 90, 91)]


BULL_LO, BULL_HI = 101.0, 103.0
BEAR_LO, BEAR_HI = 96.0, 99.0


def zone(series, direction="bullish", current=104.0, fam="fvg"):
    return _build_zone_for_family(fam, direction, {}, {}, series, "3m", current)


# ── A · the occurrence exists, is named, and is lawful ───────────────────────
def test_A_a_fresh_fvg_is_lawful():
    occ = fvg_occurrences(bull_gap(), "bullish", 3)
    assert len(occ) == 1
    o = occ[0]
    assert (o["low"], o["high"]) == (BULL_LO, BULL_HI)
    assert o["execution_eligible"] is True
    assert o["retired"] is False
    assert o["identity_evaluable"] is True
    assert o["lifecycle_evaluable"] is True
    assert o["c1_time"] and o["c2_time"] and o["c3_time"]


def test_A2_identity_comes_from_the_canonical_owner():
    """ONE identity theorem, not two. `market_events` publishes FVG identity as
    contract + timeframe + completion bucket via `object_identity`; Unit 6 calls
    the same constructor instead of formatting a second near-identical string."""
    from market_data.object_identity import market_object_id
    o = fvg_occurrences(bull_gap(), "bullish", 3)[0]
    assert o["occurrence_id"] == market_object_id(
        "FVG", contract=CONTRACT, timeframe="3m", instant=o["c3_time"])


def test_A3_geometry_never_enters_identity():
    """Geometry is RECONSTRUCTED from OHLC. History repair would mint a twin on
    every revision instead of revising one object."""
    o = fvg_occurrences(bull_gap(), "bullish", 3)[0]
    twin = dict(o, low=o["low"] - 7, high=o["high"] + 7, size=999)
    assert fvg_occurrence_id(3, "bullish", twin, contract=CONTRACT) == o["occurrence_id"]
    other = dict(o, c3_time="2026-08-12T18:09:00+00:00")
    assert fvg_occurrence_id(3, "bullish", other, contract=CONTRACT) != o["occurrence_id"]


# ── B · entry is an observation, not a retirement ────────────────────────────
def test_B_entering_the_gap_does_not_retire_it():
    series = bull_gap() + [c("18:09", 104, 105, 102, 104)]      # dips inside
    o = fvg_occurrences(series, "bullish", 3)[0]
    assert o["entered"] is True
    assert o["retired"] is False
    assert o["execution_eligible"] is True


# ── C · full traversal is an observation, not a retirement ───────────────────
def test_C_intrabar_full_traversal_does_not_retire():
    """Price sweeps the whole gap and closes back ABOVE it. This project has no
    theorem making an intrabar traversal permanent, so it retires nothing."""
    series = bull_gap() + [c("18:09", 104, 105, 100.5, 104)]
    o = fvg_occurrences(series, "bullish", 3)[0]
    assert o["fully_traversed"] is True
    assert o["close_through_far_boundary"] is False
    assert o["retired"] is False
    assert o["execution_eligible"] is True


# ── D · the authoritative settled close is the retirement event ──────────────
def test_D_a_close_through_the_far_boundary_retires_it():
    series = bull_gap() + [c("18:09", 104, 105, 100, 100.5)]    # CLOSES below 101
    o = fvg_occurrences(series, "bullish", 3)[0]
    assert o["close_through_far_boundary"] is True
    assert o["retired"] is True
    assert o["retirement_reason"] == RETIREMENT_CLOSE_THROUGH
    assert o["retirement_bar"] == "2026-08-12T18:09:00+00:00"
    assert o["execution_eligible"] is False
    assert lawful_fvg_candidates(series, "bullish", 3) == []


def test_D2_bearish_uses_the_upper_boundary():
    """Orientation is PROVEN from the producer: a bearish gap is [c3.high,
    c1.low] and acts as resistance, so its far side is the HIGH."""
    series = bear_gap() + [c("18:09", 95, 100, 94, 99.5)]       # CLOSES above 99
    assert fvg_occurrences(series, "bearish", 3)[0]["retired"] is True


# ── E · THE DEFECT · retirement is sticky ────────────────────────────────────
def test_E_price_returning_cannot_resurrect_a_retired_occurrence():
    """The measured 211/2000 case. Price closes through, then comes back, so
    `_is_invalidated` reports the zone live again. It is still dead."""
    series = bull_gap() + [c("18:09", 104, 105, 100, 100.5),    # retires it
                           c("18:12", 100.5, 106, 100.5, 105)]  # price returns above
    o = fvg_occurrences(series, "bullish", 3)[0]
    assert o["retired"] is True, "the killing close does not un-happen"
    assert o["execution_eligible"] is False
    assert _is_invalidated("bullish", 105, BULL_LO) is False, \
        "the instantaneous predicate still says live -- that is the whole point"
    z = zone(series, current=105)
    assert z["occurrence_execution_eligible"] is False
    assert z["invalidated"] is False, "the two questions stay separate"


# ── F · AS-OF-T · retirement may not leak backward ───────────────────────────
def test_F_a_scan_before_the_killing_close_still_sees_it_lawful():
    early = bull_gap()
    late = bull_gap() + [c("18:09", 104, 105, 100, 100.5)]
    assert fvg_occurrences(early, "bullish", 3)[0]["retired"] is False
    assert fvg_occurrences(late, "bullish", 3)[0]["retired"] is True
    assert fvg_occurrences(early, "bullish", 3)[0]["occurrence_id"] == \
        fvg_occurrences(late, "bullish", 3)[0]["occurrence_id"], \
        "lifecycle advances; occurrence identity never changes"


# ── G · NO SUBSTITUTION, but the alternatives are disclosed ──────────────────
def test_G_a_retired_newest_is_reported_not_swapped():
    """93 of the measured 211 had an older lawful occurrence available. Unit 6
    makes it VISIBLE. It does not trade it on the selector's behalf --
    `build_price_level`'s own law is that a zone is never swapped for an older
    gap."""
    series = [c("18:00", 100, 101, 99, 100.5),
              c("18:03", 102, 106, 102, 105),
              c("18:06", 106, 108, 103, 107),       # gap [101,103]
              c("18:09", 107, 112, 107, 111),       # gap [106,107]
              c("18:12", 112, 116, 109, 115),       # gap [108,109] — newest
              c("18:15", 115, 117, 107.9, 107.9)]   # CLOSES below 108 only
    occ = fvg_occurrences(series, "bullish", 3)
    newest, lawful = occ[0], lawful_fvg_candidates(series, "bullish", 3)
    assert newest["retired"] is True
    assert lawful, "older occurrences survive that close"
    z = zone(series, current=107.9)
    # the NEWEST still authors the geometry — nothing was swapped
    assert (z["zone_low"], z["zone_high"]) == (newest["low"], newest["high"])
    assert z["occurrence_id"] == newest["occurrence_id"]
    assert z["occurrence_execution_eligible"] is False
    # and the alternatives are disclosed rather than chosen
    ids = {o["occurrence_id"] for o in z["lawful_fvg_candidates"]}
    assert ids == {o["occurrence_id"] for o in lawful}
    assert newest["occurrence_id"] not in ids


def test_G2_mechanics_publishes_no_selection_rule():
    """`selection_rule = newest_execution_eligible_occurrence` was mechanics
    naming its own hidden choice. There is no such choice to name."""
    z = zone(bull_gap())
    assert "selection_rule" not in z


# ── H · an empty lawful set is a real answer ─────────────────────────────────
def test_H_all_retired_leaves_no_lawful_candidate_and_no_fallback():
    series = bull_gap() + [c("18:09", 104, 105, 100, 100.4)]
    assert lawful_fvg_candidates(series, "bullish", 3) == []
    z = zone(series, current=100.4)
    assert z["lawful_candidate_count"] == 0
    assert z["observed_occurrence_count"] == 1
    assert z["occurrence_execution_eligible"] is False
    assert z["zone_low"] == BULL_LO, "reported as itself, not deleted or swapped"


# ── §6 · lifecycle evaluability must fail CLOSED ─────────────────────────────
class TestUnknownIsNotClean:

    def test_a_newly_formed_occurrence_is_evaluable_with_nothing_yet(self):
        o = fvg_occurrences(bull_gap(), "bullish", 3)[0]
        assert o["lifecycle_evaluable"] is True
        assert o["bars_since_formation"] == 0
        assert o["retired"] is False
        assert o["execution_eligible"] is True

    def test_an_unlocatable_occurrence_is_not_eligible(self):
        life = fvg_lifecycle(bull_gap(), "bullish",
                             {"low": 101, "high": 103, "index": None})
        assert life["lifecycle_evaluable"] is False
        assert life["lifecycle_reason"] == LIFECYCLE_NOT_LOCATABLE
        assert life["retired"] is False, "we did not prove retirement either"

    def test_unlabelled_later_bars_cannot_prove_settlement(self):
        """WE COULD NOT LOOK. No bar after formation carries a temporal label,
        so settled evidence cannot be told from forming evidence."""
        series = bull_gap() + [c("18:09", 104, 105, 102, 104)]
        for b in series:
            b.pop("temporal_status")
        o = fvg_occurrences(series, "bullish", 3)[0]
        assert o["lifecycle_evaluable"] is False
        assert o["lifecycle_reason"] == LIFECYCLE_NO_SETTLED_AUTHORITY
        assert o["execution_eligible"] is False
        assert o["execution_ineligible_reason"] == LIFECYCLE_NO_SETTLED_AUTHORITY

    def test_a_labelled_forming_bar_is_knowledge_not_ignorance(self):
        """WE LOOKED AND NOTHING SETTLED HAS HAPPENED YET.

        An earlier version of this module treated "no settled bar after
        formation" as unevaluable even when every later bar was LABELLED
        forming. That conflated "we know nothing settled occurred" with "we do
        not know what occurred", and refused every occurrence whose only later
        bucket was the live one. Caught by the CONTINUITY-2F real-tape cases.
        """
        series = bull_gap() + [c("18:09", 104, 105, 102, 104,
                                 temporal_status="forming")]
        o = fvg_occurrences(series, "bullish", 3)[0]
        assert o["lifecycle_evaluable"] is True
        assert o["retired"] is False
        assert o["execution_eligible"] is True

    def test_a_missing_expected_slot_makes_the_lifecycle_unprovable(self):
        """ARRAY ADJACENCY IS NOT MARKET ADJACENCY, AGAIN.

        Formation completes 18:06; the expected 18:09 bucket was never
        observed; 18:12 is present and labelled forming. Reading 18:12's label
        and concluding "nothing settled has happened" would be reading the bar
        we HAVE to make a claim about the bar we DON'T -- and the settled close
        that killed this gap could have been exactly the missing 18:09 print.
        """
        series = bull_gap() + [c("18:12", 104, 105, 102, 104,
                                 temporal_status="forming")]
        o = fvg_occurrences(series, "bullish", 3)[0]
        assert o["lifecycle_evaluable"] is False
        assert o["lifecycle_reason"] == LIFECYCLE_SLOT_COVERAGE_UNPROVEN
        assert o["execution_eligible"] is False
        assert o["retired"] is False, "we did not prove retirement either"

    def test_a_scheduled_closure_is_not_a_missing_slot(self):
        """The venue calendar owns this. A wall-clock gap across a scheduled
        break is complete coverage, not absent evidence."""
        series = [c("20:00", 100, 101, 99, 100.5),
                  c("20:05", 102, 106, 102, 105),
                  c("20:10", 106, 108, 103, 107),      # gap completes 20:10
                  c("20:30", 107, 109, 104, 108)]      # 20:15/20:20/20:25 closed
        o = fvg_occurrences(series, "bullish", 5)[0]
        assert o["lifecycle_evaluable"] is True, o["lifecycle_reason"]
        assert o["retired"] is False

    def test_unknown_cadence_fails_closed_at_the_producer(self):
        """Stronger than a lifecycle veto: STEP 4B.7 §3 already makes the
        canonical producer REFUSE an uncadenced request outright, so no
        occurrence is minted at all and there is nothing to judge."""
        from toolbox.price_levels import UncadencedFvgRequest
        series = bull_gap() + [c("18:09", 104, 105, 102, 104)]
        with pytest.raises(UncadencedFvgRequest):
            fvg_occurrences(series, "bullish", None)

    def test_a_complete_settled_sequence_still_retires_exactly_as_before(self):
        """The retirement predicate is untouched by slot-coverage work."""
        series = bull_gap() + [c("18:09", 104, 105, 100, 100.5)]
        o = fvg_occurrences(series, "bullish", 3)[0]
        assert o["lifecycle_evaluable"] is True
        assert o["retired"] is True
        assert o["retirement_reason"] == RETIREMENT_CLOSE_THROUGH

    def test_a_forming_close_through_still_cannot_retire(self):
        """The other half of the same law: knowing the bar is forming means we
        know it may not KILL the occurrence either."""
        series = bull_gap() + [c("18:09", 104, 105, 100, 100.5,
                                 temporal_status="forming")]
        o = fvg_occurrences(series, "bullish", 3)[0]
        assert o["lifecycle_evaluable"] is True
        assert o["close_through_far_boundary"] is False
        assert o["retired"] is False


# ── §8 · identity must fail closed ───────────────────────────────────────────
class TestIdentityFailsClosed:

    def test_no_contract_yields_no_identity_and_no_eligibility(self):
        series = [dict(b) for b in bull_gap()]
        for b in series:
            b.pop("contract")
        o = fvg_occurrences(series, "bullish", 3)[0]
        assert o["occurrence_id"] is None
        assert o["identity_evaluable"] is False
        assert o["execution_eligible"] is False
        assert o["execution_ineligible_reason"] == "occurrence_identity_unprovable"

    def test_no_cadence_yields_no_identity(self):
        assert fvg_occurrence_id(None, "bullish",
                                 {"c3_time": "2026-08-12T18:06:00+00:00"},
                                 contract=CONTRACT) is None

    def test_index_is_never_used_as_cross_scan_identity(self):
        """Index locates an occurrence inside the series it came from. It is not
        a stable market identity.

        STRUCTURAL, not a substring scan: index 0 is a substring of the "00" in
        the timestamp, so containment reports a collision that is not one.
        The proposition is that identity does not VARY with index.
        """
        o = fvg_occurrences(bull_gap(), "bullish", 3)[0]
        moved = dict(o, index=o["index"] + 41)
        assert fvg_occurrence_id(3, "bullish", moved, contract=CONTRACT) == \
            o["occurrence_id"]


# ── §9 · retirement evidence must be authoritative ───────────────────────────
class TestRetirementEvidenceIsAuthoritative:

    def test_a_forming_close_beyond_the_boundary_does_not_retire(self):
        """A forming bar's close is still moving. It may not permanently kill an
        occurrence -- CONTINUITY-2F deliberately keeps the forming bucket
        VISIBLE, so it reaches this code and must not be given authority."""
        series = bull_gap() + [
            c("18:09", 104, 105, 100, 100.5, temporal_status="settled"),
        ]
        settled_o = fvg_occurrences(series, "bullish", 3)[0]
        assert settled_o["retired"] is True

        forming = bull_gap() + [
            c("18:09", 104, 105, 102, 104, temporal_status="settled"),
            c("18:12", 104, 105, 100, 100.5, temporal_status="forming"),
        ]
        o = fvg_occurrences(forming, "bullish", 3)[0]
        assert o["close_through_far_boundary"] is False, \
            "a forming close is not authoritative evidence"
        assert o["retired"] is False

    def test_the_same_close_retires_once_settled(self):
        forming = bull_gap() + [
            c("18:09", 104, 105, 102, 104),
            c("18:12", 104, 105, 100, 100.5, temporal_status="forming")]
        settled = bull_gap() + [
            c("18:09", 104, 105, 102, 104),
            c("18:12", 104, 105, 100, 100.5, temporal_status="settled")]
        assert fvg_occurrences(forming, "bullish", 3)[0]["retired"] is False
        assert fvg_occurrences(settled, "bullish", 3)[0]["retired"] is True

    def test_observations_may_still_use_every_bar_the_engine_held(self):
        """`entered` is a fact about what was SEEN and carries no execution
        authority, so it is not restricted to settled bars."""
        series = bull_gap() + [c("18:09", 104, 105, 102, 104),
                               c("18:12", 104, 105, 102, 104, temporal_status="forming")]
        o = fvg_occurrences(series, "bullish", 3)[0]
        assert o["entered"] is True


# ── §5 · IFVG / opening_fvg are OUT of scope and must not move ───────────────
class TestUnit6DoesNotTouchTheOtherFamilies:

    def test_ifvg_zone_is_unchanged_by_retirement(self):
        """A retired plain-FVG occurrence is still an occurrence. Filtering it
        here could delete exactly what a future inversion theorem needs."""
        series = bull_gap() + [c("18:09", 104, 105, 100, 100.5)]   # retires it
        assert lawful_fvg_candidates(series, "bullish", 3) == []
        z = zone(series, current=100.5, fam="ifvg")
        assert z["level_type"] == "ifvg_zone"
        assert (z["zone_low"], z["zone_high"]) == (BULL_LO, BULL_HI)

    def test_opening_fvg_zone_is_unchanged_by_retirement(self):
        series = bull_gap() + [c("18:09", 104, 105, 100, 100.5)]
        z = zone(series, current=100.5, fam="opening_fvg")
        assert z["level_type"] == "opening_fvg_zone"
        assert (z["zone_low"], z["zone_high"]) == (BULL_LO, BULL_HI)

    def test_the_other_families_carry_no_occurrence_fields(self):
        series = bull_gap()
        for fam in ("ifvg", "opening_fvg"):
            z = zone(series, fam=fam)
            for k in ("occurrence_id", "fvg_occurrences", "lawful_fvg_candidates",
                      "occurrence_execution_eligible"):
                assert k not in z, f"{fam} leaked {k}"

    def test_find_fvg_keeps_its_pre_unit6_contract(self):
        """`_find_fvg` is the ifvg/opening path now and still returns the newest
        gap regardless of lifecycle."""
        series = bull_gap() + [c("18:09", 104, 105, 100, 100.5)]
        assert _find_fvg(series, "bullish", 3) == (BULL_LO, BULL_HI)


# ── the zone's schema distinguishes existence from authority ─────────────────
class TestZoneSchema:

    def test_zone_names_which_occurrence_it_is(self):
        z = zone(bull_gap())
        assert z["occurrence_id"]
        assert z["formation_c1_time"] and z["formation_c3_time"]
        assert z["original_low"] == BULL_LO and z["original_high"] == BULL_HI

    def test_observed_inventory_and_lawful_set_are_named_apart(self):
        z = zone(bull_gap())
        assert z["observed_occurrence_count"] == 1
        assert z["lawful_candidate_count"] == 1
        assert "fvg_occurrences" in z and "lawful_fvg_candidates" in z

    def test_retired_occurrences_stay_in_the_observed_inventory(self):
        series = bull_gap() + [c("18:09", 104, 105, 100, 100.4)]
        z = zone(series, current=100.4)
        ids = {o["occurrence_id"] for o in z["fvg_occurrences"]}
        assert ids, "existence is not authority -- but it is still existence"
        assert z["lawful_fvg_candidates"] == []


class TestNothingWasInvented:

    def test_no_order_block_doctrine_was_transplanted(self):
        """AST, not substring: the docstring NAMES `track_mitigation` in order
        to say it is deliberately not imported, and a text scan cannot tell a
        citation from a transplant."""
        import ast
        import inspect
        import textwrap
        from toolbox import price_levels as PL
        tree = ast.parse(textwrap.dedent(inspect.getsource(PL.fvg_lifecycle)))
        names = {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)}
        attrs = {n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute)}
        keys = {n.value for n in ast.walk(tree)
                if isinstance(n, ast.Constant) and isinstance(n.value, str)}
        for forbidden in ("mean_threshold", "max_penetration", "touches",
                          "track_mitigation", "mitigation_state", "tradeable"):
            assert forbidden not in (names | attrs | keys), forbidden

    def test_no_fractional_threshold_decides_authority(self):
        """Index arithmetic is allowed; a RATIO is not. An FVG's authority may
        not depend on how deeply price penetrated it."""
        import ast
        import inspect
        import textwrap
        from toolbox import price_levels as PL
        tree = ast.parse(textwrap.dedent(inspect.getsource(PL.fvg_lifecycle)))
        floats = {n.value for n in ast.walk(tree)
                  if isinstance(n, ast.Constant) and isinstance(n.value, float)}
        assert not floats, f"a ratio entered the lifecycle: {floats}"

    def test_only_one_retirement_reason_exists(self):
        from toolbox import price_levels as PL
        assert RETIREMENT_CLOSE_THROUGH == "historical_close_through_far_boundary"
        assert PL.FVG_LIFECYCLE_OBSERVATIONS == (
            "entered", "fully_traversed", "close_through_far_boundary")
