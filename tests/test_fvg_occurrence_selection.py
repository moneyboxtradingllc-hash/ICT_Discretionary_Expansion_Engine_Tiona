"""STEP 4B.12 §6 UNIT 6 — CARDINALITY BEFORE EXTRACTION.

Terra's contract returns EXACTLY ONE TOOL-FAMILY TOKEN, and the resolver
narrowed family -> direction -> execution-eligible and then did:

    match = eligible[0]

Three lines above it, the same function already stated the doctrine:

    "the contract is exactly one tool family token. Mechanics will not choose
     among, discard from, or repair Terra's selection."

and then a list index chose among them anyway. That was survivable only while
each family produced at most one entry. With plain FVG restored as exact
occurrences (F-7), one family token can now cover several real market objects.

OPTION 2 — the release-safe theorem, chosen over breaking the Brain contract:

    |eligible| == 0   ->  existing no-executable-candidate refusal
    |eligible| == 1   ->  resolve to that occurrence  (EXTRACTION, not choice)
    |eligible|  > 1   ->  TOOL_OCCURRENCE_AMBIGUOUS, refuse

Mechanics never ranks, sorts, prefers the newest, or takes the first.
"""
import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))

from broker.luna_candidate_producer import (  # noqa: E402
    NoCandidate, authorized_tool_catalog)

CONTRACT = "CON.F.US.MNQ.U26"


def occ_instance(oid, *, tf="5m", direction="bullish", eligible=True,
                 low=100.0, high=103.0, reason=None):
    return {"tool": f"{direction}_fvg", "family": "fvg", "direction": direction,
            "source_tf": tf, "tool_id": f"{direction}_fvg@{tf}#{oid}",
            "occurrence_id": f"FVG:{CONTRACT}:{tf}:{oid}",
            "zone_low": low, "zone_high": high,
            "identity_evaluable": True,
            "temporal_class": "settled" if eligible else "provisional",
            "temporal_execution_eligible": eligible,
            "execution_eligible": eligible,
            "execution_ineligible_reason": reason,
            "score": 60}


def snap(instances):
    return {"toolbox": {"tool_instances": instances, "tool_candidates": []}}


def resolve(instances, family="fvg", want="bullish"):
    """Drive the real resolver the way `produce` does."""
    from broker import luna_candidate_producer as LP
    catalog = authorized_tool_catalog(snap(instances))
    producer = LP.CandidateProducer.__new__(LP.CandidateProducer)
    return producer._assert_tool_detected([family], want, snap(instances), None)


class TestTheCatalogCarriesExactOccurrences:

    def test_each_occurrence_is_its_own_catalog_entry(self):
        cat = authorized_tool_catalog(snap([occ_instance("A"), occ_instance("B")]))
        assert len(cat) == 2
        assert len({e["occurrence_id"] for e in cat}) == 2
        assert all(e["tool_family"] == "fvg" for e in cat)

    def test_a_retired_occurrence_is_published_but_not_eligible(self):
        cat = authorized_tool_catalog(snap([
            occ_instance("A", eligible=False,
                         reason="historical_close_through_far_boundary")]))
        assert len(cat) == 1, "existence is still published"
        assert cat[0]["execution_eligible"] is False
        assert cat[0]["execution_ineligible_reason"] == \
            "historical_close_through_far_boundary"


class TestOptionTwoCardinality:

    def test_CASE_1_two_eligible_occurrences_refuse(self):
        with pytest.raises(NoCandidate) as e:
            resolve([occ_instance("A"), occ_instance("B")])
        assert e.value.reason == "tool_occurrence_ambiguous"
        assert "2 execution-eligible occurrences" in str(e.value)

    def test_CASE_2_a_retired_sibling_leaves_a_unique_resolution(self):
        b = occ_instance("B", low=110.0, high=113.0)
        match = resolve([occ_instance("A", eligible=False,
                                      reason="historical_close_through_far_boundary"),
                         b])
        assert match["occurrence_id"] == b["occurrence_id"]
        assert (match["zone_low"], match["zone_high"]) == (110.0, 113.0)

    def test_CASE_3_a_provisional_sibling_leaves_a_unique_resolution(self):
        a = occ_instance("A", low=100.0, high=103.0)
        match = resolve([a, occ_instance("B", eligible=False,
                                         reason="TOOL_NOT_SETTLED: zone geometry "
                                                "depends on a forming bucket")])
        assert match["occurrence_id"] == a["occurrence_id"]

    def test_CASE_4_zero_eligible_uses_the_existing_refusal(self):
        with pytest.raises(NoCandidate) as e:
            resolve([occ_instance("A", eligible=False, reason="retired"),
                     occ_instance("B", eligible=False, reason="retired")])
        assert e.value.reason == "tool_not_execution_eligible"

    def test_three_eligible_occurrences_still_refuse(self):
        with pytest.raises(NoCandidate) as e:
            resolve([occ_instance("A"), occ_instance("B"), occ_instance("C")])
        assert e.value.reason == "tool_occurrence_ambiguous"
        assert "3 execution-eligible" in str(e.value)

    def test_occurrences_on_different_timeframes_are_still_ambiguous(self):
        """A family token names no timeframe either."""
        with pytest.raises(NoCandidate) as e:
            resolve([occ_instance("A", tf="5m"), occ_instance("B", tf="15m")])
        assert e.value.reason == "tool_occurrence_ambiguous"

    def test_the_opposite_side_does_not_create_ambiguity(self):
        """Direction narrows before cardinality is counted."""
        match = resolve([occ_instance("A", direction="bullish"),
                         occ_instance("B", direction="bearish")])
        assert match["direction"] == "bullish"


class TestOrderCannotBecomeDoctrine:

    @pytest.mark.parametrize("reverse", [False, True])
    def test_ambiguity_is_order_independent(self, reverse):
        inst = [occ_instance("A"), occ_instance("B")]
        if reverse:
            inst.reverse()
        with pytest.raises(NoCandidate) as e:
            resolve(inst)
        assert e.value.reason == "tool_occurrence_ambiguous"

    @pytest.mark.parametrize("reverse", [False, True])
    def test_unique_resolution_is_order_independent(self, reverse):
        b = occ_instance("B", low=110.0, high=113.0)
        inst = [occ_instance("A", eligible=False, reason="retired"), b]
        if reverse:
            inst.reverse()
        assert resolve(inst)["occurrence_id"] == b["occurrence_id"]


class TestOtherFamiliesAreNotTouched:

    def test_ifvg_is_matched_by_exact_family_never_by_substring(self):
        """`ifvg` contains "fvg". Exact family equality is what scopes this."""
        from broker.luna_candidate_producer import _family_of
        assert _family_of("bullish_ifvg") == "ifvg"
        assert _family_of("bearish_opening_fvg") == "opening_fvg"
        assert _family_of("bullish_fvg") == "fvg"

    def test_a_legacy_snapshot_without_instances_still_publishes_fvg(self):
        """An archive predating Unit 6 carries `tool_candidates` and no
        `tool_instances`. It stays readable rather than silently losing its
        FVG entry."""
        legacy = {"toolbox": {"tool_candidates": [
            {"tool": "bullish_fvg",
             "price_level": {"direction": "bullish", "source_tf": "5m",
                             "level_type": "fvg_zone",
                             "execution_eligible": True}}]}}
        cat = authorized_tool_catalog(legacy)
        assert [e["tool_family"] for e in cat] == ["fvg"]
