"""TOOL-CATALOG-LOCATION-SEMANTICS-1 — `execution_eligible` is not a location.

2026-08-20, 11:02:10 ET. The Brain was handed this, and nothing more:

    {"tool": "bearish_ote_after_reclaim", "execution_eligible": true,
     "source_tf": "3m", "level_type": "ote_zone", "temporal_class": "settled"}

The snapshot behind that row already held the zone bounds 29394.72-29412.74,
the price relation, the distance, the invalidation level, the readiness reasons
("Sweep and reclaim confirmed") and `prerequisites_missing`. `authorized_tool_
catalog` read `price_level` for `source_tf` and `level_type` and published no
price from it. Every family except FVG lost its geometry at that boundary.

So Luna chose an execution expression while being told a tool was eligible and
NOT WHERE IT WAS. Her refusal that scan -- "no qualified bearish entry geometry
is currently established" -- was made with the map withheld: at the real price
both eligible bearish zones sat 28.01 and 64.75 points BELOW the market, and
nothing in her payload could have told her.

    WE ASKED FOR A DISCRETIONARY DECISION AND HID THE MAP.

This unit publishes facts mechanics already owns. It computes nothing, ranks
nothing, and adds no judgement -- the catalog serialises upstream truth or it
states that the truth is absent.
"""
from __future__ import annotations

import json
import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))

from broker.luna_candidate_producer import (TOOL_LOCATION_FIELDS,   # noqa: E402
                                            _tool_location_facts,
                                            authorized_tool_catalog)

ARCHIVE = os.path.join(ROOT, "data", "ai_brain", "20260820_110210_MNQ.json")


def archived_snapshot():
    with open(ARCHIVE, encoding="utf-8") as fh:
        return (json.load(fh).get("raw_snapshot") or {})


def entry(tool):
    for row in authorized_tool_catalog(archived_snapshot()):
        if row.get("tool") == tool:
            return row
    raise AssertionError(f"{tool} absent from the catalog")


def candidate(**over):
    c = {"tool": "bearish_breaker", "tool_id": "bearish_breaker@1m",
         "reasons": ["Sweep and reclaim confirmed"],
         "readiness": {"next_status": "actionable",
                       "prerequisites_missing": ["Failed breakout not confirmed"]},
         "price_level": {"zone_low": 29360.0, "zone_high": 29376.0,
                         "midpoint": 29368.0, "price_relation": "above_zone",
                         "distance_to_zone": 64.75, "entered_zone": False,
                         "current_price": 29440.75, "settled_price": 29404.25,
                         "location_basis": "execution_price",
                         "invalidation_level": 29398.5, "invalidated": True}}
    c.update(over)
    return c


# ══════════════════════════════════════════════════════════════════════════════
class TestTheArchivedRowNowNamesItsLocation:
    def test_the_eligible_tool_publishes_its_zone(self):
        e = entry("bearish_ote_after_reclaim")
        assert e["execution_eligible"] is True
        assert (e["zone_low"], e["zone_high"]) == (29394.72, 29412.74)

    def test_it_publishes_where_price_stands(self):
        e = entry("bearish_ote_after_reclaim")
        for f in ("price_relation", "distance_to_zone", "entered_zone"):
            assert f in e, f

    def test_it_publishes_its_own_invalidation(self):
        assert entry("bearish_ote_after_reclaim")["invalidation_level"] == 29435.0

    def test_it_publishes_why_mechanics_calls_it_ready(self):
        e = entry("bearish_ote_after_reclaim")
        assert "Sweep and reclaim confirmed" in e["readiness_reasons"]

    def test_it_publishes_what_is_still_missing(self):
        assert entry("bearish_ote_after_reclaim")["prerequisites_missing"] == []

    def test_the_provisional_rejection_block_says_where_it_is_AND_why_it_cannot_execute(self):
        """A provisional tool is a witness. It must still be locatable.

        PROTECTED-LEVEL-REJECTION-AGGRESSIVE-1 later supersedes this row with an
        anchored block, so the generic geometry now rides in
        `superseded_generic` — the proposition is unchanged: a row that cannot
        execute must still say where it was and why."""
        e = entry("bearish_rejection_block")
        prior = e["superseded_generic"]
        assert prior["execution_eligible"] is False
        assert "TOOL_NOT_SETTLED" in prior["execution_ineligible_reason"]
        assert (prior["zone_low"], prior["zone_high"]) == (29350.25, 29367.75)

    def test_before_this_unit_none_of_that_reached_the_brain(self):
        """The archived payload is the control: it carries no zone at all."""
        with open(ARCHIVE, encoding="utf-8") as fh:
            shipped = json.load(fh)["input_payload"]["authorized_tool_catalog"]
        row = [r for r in shipped if r["tool"] == "bearish_ote_after_reclaim"][0]
        for absent in ("zone_low", "zone_high", "price_relation",
                       "distance_to_zone", "invalidation_level"):
            assert absent not in row, absent


class TestItSerialisesAndNeverComputes:
    def test_every_location_field_is_value_identical_to_its_source(self):
        cand = candidate()
        facts = _tool_location_facts(cand, cand["price_level"])
        for f in TOOL_LOCATION_FIELDS:
            assert facts[f] == cand["price_level"][f], f

    def test_the_catalog_layer_does_no_arithmetic(self):
        """AST: no value may be COMPUTED on the way through.

        Presence checks (`missing is not None`) are legitimate and expected —
        they decide whether a fact exists, never what it equals. What must not
        appear is arithmetic, which would make this layer a second author of
        numbers mechanics already owns.
        """
        import ast
        import inspect
        import textwrap
        from broker import luna_candidate_producer as P
        tree = ast.parse(textwrap.dedent(inspect.getsource(P._tool_location_facts)))
        for node in ast.walk(tree):
            assert not isinstance(node, ast.BinOp), ast.unparse(node)
        # and every comparison is against None or a bare key — never a number
        for node in ast.walk(tree):
            if isinstance(node, ast.Compare):
                rendered = ast.unparse(node)
                assert not any(ch.isdigit() for ch in rendered), rendered

    def test_an_absent_fact_is_omitted_rather_than_invented(self):
        facts = _tool_location_facts({"tool": "x"}, {"zone_low": 1.0})
        assert facts["zone_low"] == 1.0
        for invented in ("zone_high", "price_relation", "distance_to_zone",
                         "current_price", "invalidation_level"):
            assert invented not in facts, invented

    def test_a_none_value_is_published_as_none_not_dropped(self):
        """`distance_to_zone: None` is a real answer — location unknown."""
        facts = _tool_location_facts({}, {"distance_to_zone": None,
                                          "price_relation": "unknown"})
        assert facts["distance_to_zone"] is None
        assert facts["price_relation"] == "unknown"

    def test_empty_prerequisites_is_not_the_same_as_uncomputed(self):
        nothing_missing = _tool_location_facts(
            candidate(readiness={"prerequisites_missing": []}), {})
        never_computed = _tool_location_facts(candidate(readiness={}), {})
        assert nothing_missing["prerequisites_missing"] == []
        assert "prerequisites_missing" not in never_computed

    def test_it_never_raises_on_malformed_input(self):
        for bad in (None, {}, {"readiness": "not a dict"}, {"reasons": 5}):
            assert isinstance(_tool_location_facts(bad, None), dict)


class TestTheFreshnessChainReachesTheCatalog:
    """Commit 1 made location truthful; this carries that truth outward."""

    def test_the_fresh_price_and_its_basis_travel_together(self):
        cand = candidate()
        facts = _tool_location_facts(cand, cand["price_level"])
        assert facts["current_price"] == 29440.75          # the fresh bid
        assert facts["settled_price"] == 29404.25          # structural context
        assert facts["location_basis"] == "execution_price"

    def test_a_failed_closed_location_is_carried_as_such(self):
        pl = {"zone_low": 29360.0, "zone_high": 29376.0, "current_price": None,
              "price_relation": "unknown", "distance_to_zone": None,
              "entered_zone": False, "settled_price": 29404.25,
              "location_basis": "execution_price_absent"}
        facts = _tool_location_facts({}, pl)
        assert facts["price_relation"] == "unknown"
        assert facts["current_price"] is None
        assert facts["location_basis"] == "execution_price_absent"
        assert facts["zone_low"] == 29360.0        # geometry still delivered

    def test_the_settled_close_is_never_promoted_into_current_price(self):
        pl = {"current_price": None, "settled_price": 29404.25}
        facts = _tool_location_facts({}, pl)
        assert facts["current_price"] is None
        assert facts["current_price"] != facts["settled_price"]


class TestNothingElseMoved:
    def test_eligibility_semantics_are_unchanged_for_generic_families(self):
        """The anchored rejection blocks are additionally eligible; no GENERIC
        family's eligibility was altered by publishing location facts."""
        cat = authorized_tool_catalog(archived_snapshot())
        generic = {r["tool"] for r in cat if r["execution_eligible"]
                   and r.get("level_type") != "protected_level_rejection_block"}
        assert generic == {"bearish_breaker", "bearish_ote_after_reclaim",
                           "bullish_ote_retracement"}

    def test_the_catalog_still_publishes_provisional_rows(self):
        cat = authorized_tool_catalog(archived_snapshot())
        assert any(r["execution_eligible"] is False for r in cat)

    def test_no_generic_row_is_added_or_dropped(self):
        """This unit WIDENS rows; it adds none. (The anchored rejection blocks
        arrive in a later unit and SUPERSEDE their generic counterparts rather
        than accumulating beside them, so tool names stay unique.)"""
        import collections
        with open(ARCHIVE, encoding="utf-8") as fh:
            shipped = json.load(fh)["input_payload"]["authorized_tool_catalog"]
        now = authorized_tool_catalog(archived_snapshot())
        before, after = {r["tool"] for r in shipped}, {r["tool"] for r in now}
        # nothing the generic scan found may vanish
        assert not (before - after), before - after
        # and anything NEW must be an anchored block, never a generic row
        added = {r["tool"] for r in now if r["tool"] not in before}
        anchored = {r["tool"] for r in now
                    if r.get("level_type") == "protected_level_rejection_block"}
        assert added <= anchored, added - anchored
        names = collections.Counter(r["tool"] for r in now)
        assert not [t for t, n in names.items() if n > 1]

    def test_the_original_fields_are_untouched(self):
        """Every field a row shipped with still means what it meant.

        Rejection blocks are exempt: they are DELIBERATELY superseded by the
        anchored variant, and their original geometry is asserted intact inside
        `superseded_generic` by the test above."""
        with open(ARCHIVE, encoding="utf-8") as fh:
            shipped = json.load(fh)["input_payload"]["authorized_tool_catalog"]
        now = {r["tool"]: r for r in authorized_tool_catalog(archived_snapshot())}
        for old in shipped:
            if old.get("tool_family") == "rejection_block":
                continue
            for k, v in old.items():
                assert now[old["tool"]][k] == v, (old["tool"], k)

    def test_the_quarantine_scar_still_travels_in_its_own_fields(self):
        e = [r for r in authorized_tool_catalog(archived_snapshot())
             if r["tool"] == "bearish_ifvg"]
        if e:
            assert "execution_quarantined" in e[0]
