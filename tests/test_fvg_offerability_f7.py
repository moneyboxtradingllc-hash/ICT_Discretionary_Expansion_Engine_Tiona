"""STEP 4B.12 §6 UNIT 6 (F-7) — A GAP PROVES ITS OWN SIDE.

Plain FVG was withdrawn from offerability on 2026-08-14 by the DIRECTIONAL
TRUTH repair, which classified it direction-blind:

    "These have no directional evidence in the snapshot at all ... Until their
     own detectors witness a side, they are not offerable in either direction."

The LAW was right -- never borrow an FVG's side from BOS, bias, liquidity or a
caller's request. The CLASSIFICATION was wrong. `find_fvgs` has proven FVG
direction from the exact source triple since the initial commit (4139c77), over
two months earlier, and the very commit that declared FVG direction-blind also
wrote in `market_events`: "an FVG proves its own side or it is not an FVG."

Consequence, measured on the venue tape over 250 scans:

    producer knew a lawful BULLISH occurrence on   250 / 250 scans
    producer knew a lawful BEARISH occurrence on   206 / 250 scans
    unique lawful occurrence identities                 92
    bullish occurrence DELIVERIES                     2488
    bearish occurrence DELIVERIES                      913

    plain-FVG tool_instances                             0
    plain-FVG tool_candidates                            0
    plain-FVG catalog entries                            0

A canonical tool family -- one of the 22, and the FIRST listed tool in two
playbooks -- was completely dark to Terra.
"""
import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))

from toolbox import toolbox_engine as TE  # noqa: E402
from toolbox.toolbox_engine import fvg_occurrence_instances, tool_instances  # noqa: E402

CONTRACT = "CON.F.US.MNQ.U26"


def c(hhmm, o, h, l, cl, temporal_status="settled"):
    return {"timestamp": f"2026-08-12T{hhmm}:00+00:00", "open": o, "high": h,
            "low": l, "close": cl, "volume": 10, "contract": CONTRACT,
            "temporal_status": temporal_status,
            "direction": "bullish" if cl > o else "bearish" if cl < o else "neutral"}


BULL = [c("18:00", 100, 101, 99, 100.5),
        c("18:03", 102, 106, 102, 105),
        c("18:06", 106, 108, 103, 107)]          # bullish gap [101, 103]


def snap(candles, tf="3m"):
    return {"timeframes": {tf: {"recent_candles": candles,
                                "last_candle": candles[-1]}},
            "expansion": {}, "liquidity": {}, "structure": {}, "po3": {},
            "playbook": {}, "session": "ny_open"}


class TestTheGuardPremiseIsGone:

    def test_fvg_is_no_longer_direction_blind(self):
        assert "fvg" not in TE._DIRECTION_BLIND_FAMILIES

    def test_the_law_still_governs_the_genuinely_blind_families(self):
        """The doctrine is untouched -- only FVG's classification changed."""
        assert TE._DIRECTION_BLIND_FAMILIES == ("opening_fvg", "mss_retest")

    def test_fvg_never_borrows_reversal_or_continuation_authority(self):
        """Adding fvg to either family would replace one authority inversion
        with another: a sweep does not give a gap its side, and neither does a
        break."""
        assert "fvg" not in TE._REVERSAL_FAMILIES
        assert "fvg" not in TE._CONTINUATION_FAMILIES


class TestDirectionComesFromTheOccurrence:

    def test_a_bullish_instance_requires_a_bullish_triple(self):
        inst = fvg_occurrence_instances("bullish_fvg", snap(BULL))
        assert inst, "a genuine bullish gap must be offerable"
        assert all(i["direction"] == "bullish" for i in inst)
        assert all(i["directional_witness"] == "fvg_occurrence_geometry"
                   for i in inst)

    def test_a_bullish_request_cannot_relabel_a_bearish_occurrence(self):
        """THE CENTRAL SAFETY PROPERTY. `direction` selects which predicate is
        tested; it never labels. A bearish triple under a bullish request must
        produce NOTHING, not a mislabelled instance."""
        bear = [c("18:00", 100, 101, 99, 99.5),
                c("18:03", 96, 96, 92, 93),
                c("18:06", 95, 96, 90, 91)]      # bearish gap [96, 99]
        assert fvg_occurrence_instances("bullish_fvg", snap(bear)) == []
        assert fvg_occurrence_instances("bearish_fvg", snap(bear)) != []

    def test_no_structural_or_liquidity_fact_can_create_an_fvg_instance(self):
        """A snapshot screaming bullish BOS and a bullish sweep, with no gap,
        yields no FVG. Direction is not the only thing that must come from the
        occurrence -- existence must too."""
        flat = [c("18:00", 100, 101, 99, 100),
                c("18:03", 100, 101, 99, 100),
                c("18:06", 100, 101, 99, 100)]
        s = snap(flat)
        s["structure"] = {"3m": {"bos": True, "bos_direction": "bullish",
                                 "state": "bullish_expansion"}}
        s["liquidity"] = {"3m": {"sweep_detected": True,
                                 "sweep_direction": "below_low"}}
        assert fvg_occurrence_instances("bullish_fvg", s) == []


class TestOneOccurrenceIsOneInstance:

    def _two_on_one_tf(self):
        return [c("18:00", 100, 101, 99, 100.5),
                c("18:03", 102, 106, 102, 105),
                c("18:06", 106, 108, 103, 107),   # gap A [101,103]
                c("18:09", 107, 112, 107, 111),
                c("18:12", 112, 116, 109, 115)]   # gap B [108,109]

    def test_two_gaps_on_one_timeframe_are_two_instances(self):
        """`_anchor_tfs` would have reduced these to the single string "3m".
        They are different market objects."""
        inst = fvg_occurrence_instances("bullish_fvg", snap(self._two_on_one_tf()))
        assert len(inst) >= 2
        assert len({i["occurrence_id"] for i in inst}) == len(inst)
        assert len({i["tool_id"] for i in inst}) == len(inst)
        assert {i["source_tf"] for i in inst} == {"3m"}

    def test_identical_scores_never_collapse_occurrences(self):
        """The restored scoring terms are market CONTEXT, so occurrences on one
        timeframe legitimately tie. A tie is not a licence to drop one."""
        inst = fvg_occurrence_instances("bullish_fvg", snap(self._two_on_one_tf()))
        assert len({i["score"] for i in inst}) == 1, "fixture should tie"
        assert len(inst) >= 2, "and both must survive the tie"

    def test_each_instance_carries_its_own_geometry_and_provenance(self):
        inst = fvg_occurrence_instances("bullish_fvg", snap(self._two_on_one_tf()))
        for i in inst:
            assert i["formation_c1_time"] and i["formation_c3_time"]
            assert i["zone_low"] is not None and i["zone_high"] is not None
        geoms = {(i["zone_low"], i["zone_high"]) for i in inst}
        assert len(geoms) == len(inst), "distinct occurrences, distinct geometry"


class TestFourPropositionsStaySeparate:

    def test_a_retired_occurrence_is_published_but_not_eligible(self):
        """Observable != lawful. Existence is not authority, and a retired gap
        stays visible with its reason rather than vanishing."""
        series = BULL + [c("18:09", 104, 105, 100, 100.5)]   # closes below 101
        inst = fvg_occurrence_instances("bullish_fvg", snap(series))
        assert inst, "the occurrence still EXISTS"
        i = inst[0]
        assert i["occurrence_execution_eligible"] is False
        assert i["occurrence_ineligible_reason"] == \
            "historical_close_through_far_boundary"
        assert i["occurrence_lifecycle"]["retired"] is True

    def test_the_instance_carries_its_OWN_2f_verdict(self):
        """CONTINUITY-2F is run PER OCCURRENCE, not once for the family.

        Applying one zone's temporal verdict to every occurrence would let one
        gap's forming-bucket defect condemn a perfectly settled neighbour -- or
        let a clean verdict launder a provisional one. The dual-arm comparison
        is matched BY occurrence_id, never by position or price.
        """
        i = fvg_occurrence_instances("bullish_fvg", snap(BULL))[0]
        assert i["temporal_class"] in ("settled", "provisional")
        assert isinstance(i["temporal_execution_eligible"], bool)

    def test_the_four_authorities_stay_separately_visible(self):
        """A composite of False must still name its author."""
        i = fvg_occurrence_instances("bullish_fvg", snap(BULL))[0]
        for witness in ("identity_evaluable", "lifecycle_evaluable",
                        "retired", "temporal_execution_eligible"):
            assert witness in i or witness in i["occurrence_lifecycle"], witness
        assert "execution_ineligible_reason" in i

    def test_an_occurrence_without_identity_is_not_a_tool(self):
        stripped = [dict(b) for b in BULL]
        for b in stripped:
            b.pop("contract")
        assert fvg_occurrence_instances("bullish_fvg", snap(stripped)) == []


class TestOtherFamiliesAreUntouched:

    def test_non_fvg_families_keep_the_anchor_path(self):
        """Only plain FVG gets the occurrence path. Every other family still
        resolves through `_anchor_tfs`."""
        import inspect
        src = inspect.getsource(TE.tool_instances)
        assert 'if fam == "fvg"' in src
        assert "_anchor_tfs(fam, direction, snapshot)" in src

    def test_ifvg_and_opening_fvg_get_no_occurrence_instances(self):
        for tool in ("bullish_ifvg", "bearish_ifvg",
                     "bullish_opening_fvg", "bearish_opening_fvg"):
            assert fvg_occurrence_instances(tool, snap(BULL)) == []

    def test_opening_fvg_remains_direction_blind(self):
        s = snap(BULL)
        assert TE._anchor_tfs("opening_fvg", "bullish", s) == []
        assert TE._anchor_tfs("mss_retest", "bullish", s) == []


class TestScoringDoctrineWasRestoredNotInvented:

    def test_the_terms_are_the_original_score_fvg_terms(self):
        """`_local_fvg` is `_score_fvg` from 4139c77: +25 displacement,
        +15 expansion state, +5 no-sweep, base 20."""
        s = snap(BULL)
        assert TE._local_fvg(s, "3m") == 25          # base 20 + no-sweep 5
        s["expansion"] = {"15m": {"displacement_detected": True}}
        assert TE._local_fvg(s, "3m") == 50
        s["expansion"]["5m"] = {"state": "healthy_expansion"}
        assert TE._local_fvg(s, "3m") == 65
        s["liquidity"] = {"1m": {"sweep_detected": True}}
        assert TE._local_fvg(s, "3m") == 60
