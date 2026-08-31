"""FVG-LOCATION-AND-PATH-EVIDENCE-1 — publish the geometry Luna never had.

2026-08-24 forensic. Measured across 308 live production scans:

    plain-FVG catalog rows carrying ANY location fact      0 of 12,629
    non-FVG catalog rows carrying location facts         749 of  1,032

FVG was 92% of everything the Brain was shown, and the only trade taken all
session was an FVG. At 10:52 she sold a 1m bearish gap 29092.00-29112.00 at
29092.25 -- 1.25% into a 20-point zone, with 19.75 points of it still above --
and the payload could not tell her that. `_tool_location_facts` reads a
`price_level` dict; the FVG branch publishes occurrence-exact instances straight
from `tool_instances`, which carry geometry and lifecycle but never location.

    `execution_eligible: true` IS NOT A LOCATION -- for gaps either.

Second defect, same specimen. `enumerate_objectives` publishes every level flat.
From 29092.25 it offered BOTH the intact protected low 28979.50 and the external
pool 28947.75 beyond it, with nothing recording that reaching the second means
trading through the first. That choice lifted nominal R:R 6.264 -> 8.028.

THIS UNIT PUBLISHES TRUTH AND NOTHING ELSE. No FVG entry threshold is defined,
no objective is clipped, reordered or preferred, no reward-to-risk law moves,
and nothing branches on penetration. The tests below pin that restraint as hard
as they pin the new facts.

No network. No model. No order.
"""
from __future__ import annotations

import copy
import json
import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))

from broker.luna_candidate_producer import (                       # noqa: E402
    FVG_LOCATION_FIELDS, authorized_objective_catalog,
    authorized_tool_catalog, zone_penetration)

SPECIMEN = os.path.join(ROOT, "data", "ai_brain", "20260824_105200_MNQ.json")
TRADED = "FVG:CON.F.US.MNQ.U26:1m:2026-08-24T13:39:00+00:00"
DESTINATION = "FVG:CON.F.US.MNQ.U26:15m:2026-08-24T13:45:00+00:00"


def artifact():
    if not os.path.exists(SPECIMEN):
        pytest.skip("archived 10:52 specimen absent")
    with open(SPECIMEN, encoding="utf-8") as fh:
        return copy.deepcopy(json.load(fh))


def row(catalog, oid):
    for t in catalog:
        if t.get("occurrence_id") == oid:
            return t
    return None


@pytest.fixture(scope="module")
def art():
    return artifact()


@pytest.fixture(scope="module")
def catalog(art):
    return authorized_tool_catalog(art["raw_snapshot"])


# ══════════════════════════════════════════════════════════════════════════════
class TestFvgLocationParity:

    def test_the_archive_really_shipped_without_location(self, art):
        """Guard against a vacuous unit: if the live rows had carried location
        all along, everything below would be proving nothing."""
        shipped = art["input_payload"]["authorized_tool_catalog"]
        fvg = [t for t in shipped if t.get("tool_family") == "fvg"]
        assert fvg, "specimen carries no FVG rows"
        assert all(t.get("current_price") is None for t in fvg)
        assert all(t.get("price_relation") is None for t in fvg)

    def test_every_fvg_row_now_carries_location(self, catalog):
        fvg = [t for t in catalog if t.get("tool_family") == "fvg"]
        assert fvg
        for t in fvg:
            for f in ("current_price", "price_relation", "entered_zone",
                      "distance_to_zone", "location_basis"):
                assert f in t, (t.get("occurrence_id"), f)

    def test_the_traded_gap_reports_its_true_geometry(self, catalog):
        t = row(catalog, TRADED)
        assert t is not None
        assert (t["zone_low"], t["zone_high"]) == (29092.0, 29112.0)
        assert t["current_price"] == 29092.25          # bearish_executable
        assert t["price_relation"] == "inside_zone"
        assert t["entered_zone"] is True
        assert t["location_basis"] == "execution_price"

    def test_the_traded_gap_reports_how_little_of_it_was_left(self, catalog):
        """THE FACT SHE NEVER HAD. Inside the zone, 1.25% in, 19.75 points of
        gap still above the entry."""
        t = row(catalog, TRADED)
        assert t["zone_width"] == 20.0
        assert t["zone_penetration_pct"] == 1.25
        assert t["distance_to_far_boundary"] == 19.75

    def test_the_destination_zone_penetration_matches_the_forensic(self, catalog):
        """The 15m bearish rebalance area: entered, but only a third of the way,
        with 103.75 points of zone remaining. Entered != worked through."""
        t = row(catalog, DESTINATION)
        assert (t["zone_low"], t["zone_high"]) == (29038.0, 29196.0)
        assert t["entered_zone"] is True
        assert t["zone_penetration_pct"] == pytest.approx(34.34, abs=0.01)
        assert t["distance_to_far_boundary"] == 103.75

    def test_location_comes_from_the_governed_sided_quote(self, art, catalog):
        """Not the settled close. The bearish rows must price from the BID."""
        ep = art["raw_snapshot"]["execution_price"]
        assert ep["bearish_executable"] == 29092.25
        assert ep["bullish_executable"] == 29092.75
        for t in catalog:
            if t.get("tool_family") != "fvg" or t.get("current_price") is None:
                continue
            expect = (ep["bearish_executable"] if t["direction"] == "bearish"
                      else ep["bullish_executable"])
            assert t["current_price"] == expect, t["occurrence_id"]

    def test_no_executable_price_fails_closed_to_unknown(self, art):
        """A stale or absent quote must NOT fall back to a settled close --
        that substitution is the defect `_reanchor_location` exists to end."""
        s = copy.deepcopy(art["raw_snapshot"])
        s["execution_price"] = {"schema": "execution_price.v1", "available": False,
                                "best_bid": None, "best_ask": None}
        fvg = [t for t in authorized_tool_catalog(s) if t.get("tool_family") == "fvg"]
        assert fvg
        for t in fvg:
            assert t["current_price"] is None
            assert t["price_relation"] == "unknown"
            assert t["entered_zone"] is False
            assert t["zone_penetration_pct"] is None

    def test_a_missing_execution_price_block_does_not_break_the_catalog(self, art):
        s = copy.deepcopy(art["raw_snapshot"])
        s.pop("execution_price", None)
        cat = authorized_tool_catalog(s)
        assert [t for t in cat if t.get("tool_family") == "fvg"]

    def test_no_invalidation_claim_is_manufactured_for_a_gap(self, catalog):
        """A plain FVG carries no structural stop. `invalidated: False` from a
        level that does not exist would be an unbacked claim in a real field's
        name -- the occurrence's own eligibility already answers that."""
        assert "invalidated" not in FVG_LOCATION_FIELDS
        assert "invalidation_level" not in FVG_LOCATION_FIELDS
        for t in catalog:
            if t.get("tool_family") == "fvg":
                assert "invalidated" not in t
                assert t.get("execution_eligible") is not None


class TestNoSecondGeometrySystem:

    def test_location_is_delegated_to_the_canonical_owner(self):
        import inspect
        from broker import luna_candidate_producer as M
        src = inspect.getsource(M._fvg_location_facts)
        assert "_reanchor_location" in src
        for reinvented in ("_price_relation(", "def _distance", "zl <= current"):
            assert reinvented not in src, reinvented

    def test_the_same_adjacency_rule_is_used(self):
        import inspect
        from broker import luna_candidate_producer as M
        assert "_touch_tolerance" in inspect.getsource(M._fvg_location_facts)


class TestZonePenetrationIsTelemetryOnly:

    def test_bearish_zone_is_measured_from_its_low(self):
        p = zone_penetration("bearish", 29092.25, 29092.0, 29112.0)
        assert p["penetration_near_boundary"] == 29092.0
        assert p["penetration_far_boundary"] == 29112.0
        assert p["zone_penetration_pct"] == 1.25

    def test_bullish_zone_is_measured_from_its_high(self):
        """The mirror: a bullish zone is approached from ABOVE."""
        p = zone_penetration("bullish", 29110.0, 29092.0, 29112.0)
        assert p["penetration_near_boundary"] == 29112.0
        assert p["penetration_far_boundary"] == 29092.0
        assert p["zone_penetration_pct"] == 10.0

    def test_edges_and_midpoint(self):
        assert zone_penetration("bearish", 100.0, 100.0, 200.0)["zone_penetration_pct"] == 0.0
        assert zone_penetration("bearish", 150.0, 100.0, 200.0)["zone_penetration_pct"] == 50.0
        assert zone_penetration("bearish", 200.0, 100.0, 200.0)["zone_penetration_pct"] == 100.0
        assert zone_penetration("bullish", 200.0, 100.0, 200.0)["zone_penetration_pct"] == 0.0
        assert zone_penetration("bullish", 100.0, 100.0, 200.0)["zone_penetration_pct"] == 100.0

    def test_outside_the_zone_has_no_penetration(self):
        """0.0 would claim first contact. Outside is not contact."""
        for px in (99.0, 201.0):
            p = zone_penetration("bearish", px, 100.0, 200.0)
            assert p["zone_penetration_pct"] is None
            assert p["distance_to_far_boundary"] is None
            assert p["zone_width"] == 100.0

    def test_no_side_means_no_near_or_far(self):
        p = zone_penetration(None, 150.0, 100.0, 200.0)
        assert p["zone_penetration_pct"] is None
        assert p["penetration_near_boundary"] is None

    def test_degenerate_and_malformed_input_never_raises(self):
        assert zone_penetration("bearish", 100.0, 100.0, 100.0)["zone_penetration_pct"] is None
        assert zone_penetration("bearish", None, 1, 2)["zone_penetration_pct"] is None
        assert zone_penetration("bearish", "x", 1, 2)["zone_width"] is None
        # inverted bounds are normalised, not rejected
        assert zone_penetration("bearish", 150.0, 200.0, 100.0)["zone_penetration_pct"] == 50.0

    def test_no_threshold_semantics_were_introduced(self):
        """Penetration must not acquire a verdict. If any of these words appear
        beside it, this unit has stopped being telemetry."""
        import inspect
        from broker import luna_candidate_producer as M
        src = inspect.getsource(M.zone_penetration)
        for verdict in ("complete", "rejected", "reversed", "shallow", "deep",
                        "sufficient", "threshold", "if pct", "> 50", ">= 50"):
            assert verdict not in src.lower(), verdict

    def test_nothing_in_the_tree_branches_on_penetration(self):
        """Grep the production source: penetration may be READ by no one. The
        moment something gates on it, it is a signal and needs its own unit."""
        import pathlib
        hits = []
        for p in pathlib.Path(os.path.join(ROOT, "src")).rglob("*.py"):
            txt = p.read_text(encoding="utf-8", errors="ignore")
            if "zone_penetration_pct" in txt and p.name != "luna_candidate_producer.py":
                hits.append(str(p))
        assert not hits, hits


# ══════════════════════════════════════════════════════════════════════════════
class TestObjectiveInterveningStructure:

    @pytest.fixture(scope="class")
    def objectives(self, art):
        return authorized_objective_catalog(
            art["raw_snapshot"], art["input_payload"], 29092.25)

    def by_id(self, objs, oid):
        return next(o for o in objs if o["objective_id"] == oid)

    def test_the_chosen_deep_target_declares_the_intact_level_in_front(self, objectives):
        o = self.by_id(objectives, "OBJ_LIQ_SSL_2")
        assert o["price"] == 28947.75
        assert o["protected_level_between_entry_and_target"] is True
        assert o["nearest_intervening_protected_level"] == 28979.5
        lv = o["intervening_protected_levels"]
        assert [r["level"] for r in lv] == [28979.5]
        assert lv[0]["basis"] == "sell_side_raid_rejected"
        assert lv[0]["status"] == "intact_no_acceptance_through"

    def test_the_nearer_objective_has_nothing_in_front_of_it(self, objectives):
        """A level AT the objective IS that objective, never an obstacle."""
        o = self.by_id(objectives, "OBJ_PS_4")
        assert o["price"] == 28979.5
        assert o["protected_level_between_entry_and_target"] is False
        assert o["intervening_protected_levels"] == []

    def test_the_bullish_side_is_symmetric(self, objectives):
        o = self.by_id(objectives, "OBJ_LIQ_BSL_1")
        assert o["price"] == 29243.75
        assert o["protected_level_between_entry_and_target"] is True
        assert [r["level"] for r in o["intervening_protected_levels"]] == [
            29110.25, 29225.0, 29242.0]

    def test_intervening_levels_are_ordered_nearest_first(self, objectives):
        o = self.by_id(objectives, "OBJ_LIQ_BSL_1")
        d = [abs(r["level"] - 29092.25) for r in o["intervening_protected_levels"]]
        assert d == sorted(d)

    def test_no_objective_was_removed_reordered_or_clipped(self, art, objectives):
        """The whole point: publish truth, change nothing."""
        from broker.luna_candidate_producer import enumerate_objectives
        base = enumerate_objectives(art["raw_snapshot"], art["input_payload"])
        assert [o["price"] for o in objectives] == [o["price"] for o in base]
        assert len(objectives) == len(base)

    def test_reward_to_risk_law_is_untouched(self):
        from broker.luna_candidate_producer import (LEGACY_QUALIFICATION_R,
                                                    MIN_QUALIFICATION_R)
        assert MIN_QUALIFICATION_R == 1.0
        assert LEGACY_QUALIFICATION_R == 1.5

    def test_acceptance_is_not_required_before_publication(self, objectives):
        """A deep objective behind an intact level is still PUBLISHED and still
        selectable. This unit narrates; it does not veto."""
        o = self.by_id(objectives, "OBJ_LIQ_SSL_2")
        assert o["protected_level_between_entry_and_target"] is True
        assert o.get("valid_for") == "bearish"
        assert "objective_id" in o

    def test_no_reference_price_means_no_claim(self, art):
        objs = authorized_objective_catalog(art["raw_snapshot"],
                                            art["input_payload"], None)
        assert objs
        for o in objs:
            assert "protected_level_between_entry_and_target" not in o

    def test_absent_protected_swings_never_raises(self, art):
        bi = copy.deepcopy(art["input_payload"])
        bi["protected_swings"] = {}
        objs = authorized_objective_catalog(art["raw_snapshot"], bi, 29092.25)
        assert all(o["protected_level_between_entry_and_target"] is False
                   for o in objs)


class TestNothingElseMoved:

    def test_non_fvg_rows_keep_every_field_they_had(self, art, catalog):
        """Keyed on the row's own identity rather than `tool_id`: the anchored
        rejection block carries no tool_id, and on this specimen it is the ONLY
        non-FVG row -- an earlier version of this test keyed on tool_id, found
        nothing to compare, and would have passed while proving nothing."""
        def key(t):
            return (t.get("tool"), t.get("level_type"),
                    t.get("zone_low"), t.get("zone_high"))
        shipped = {key(t): t for t in
                   art["input_payload"]["authorized_tool_catalog"]
                   if t.get("tool_family") != "fvg"}
        assert shipped, "specimen carries no non-FVG rows to compare"
        now = {key(t): t for t in catalog if t.get("tool_family") != "fvg"}
        assert set(shipped) == set(now)
        for k, old in shipped.items():
            new = now[k]
            for field, v in old.items():
                assert new.get(field) == v, (k, field)

    def test_the_catalog_gained_only_additive_keys(self, art, catalog):
        old_fvg = next(t for t in art["input_payload"]["authorized_tool_catalog"]
                       if t.get("occurrence_id") == TRADED)
        new_fvg = row(catalog, TRADED)
        assert set(old_fvg) - set(new_fvg) == set()
        added = set(new_fvg) - set(old_fvg)
        assert added <= {"current_price", "price_relation", "entered_zone",
                         "distance_to_zone", "midpoint", "location_basis",
                         "zone_width", "zone_penetration_pct",
                         "distance_to_far_boundary",
                         "penetration_near_boundary", "penetration_far_boundary"}

    def test_execution_eligibility_is_unchanged_for_every_row(self, art, catalog):
        old = {t["occurrence_id"]: t["execution_eligible"]
               for t in art["input_payload"]["authorized_tool_catalog"]
               if t.get("occurrence_id")}
        for t in catalog:
            oid = t.get("occurrence_id")
            if oid in old:
                assert t["execution_eligible"] == old[oid], oid
