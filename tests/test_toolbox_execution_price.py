"""TOOLBOX-EXECUTION-PRICE-1 — the toolbox knew where price was. It was wrong.

2026-08-20, 11:02:10 ET. `bearish_ote_after_reclaim` published:

    zone 29394.72 - 29412.74
    current_price     29404.25
    price_relation    inside_zone
    distance_to_zone  0.0
    entered_zone      True

The market was trading 29440.75 — TWENTY-EIGHT POINTS ABOVE THE ZONE. Mechanics
believed price was standing inside an entry it had already left behind, because
`_current_price()` returned the newest SETTLED candle close and every
location field was measured from it.

This is the same defect as EXEC-PRICE-FRESHNESS-1 in its third costume. That
unit stopped the PRODUCER pricing exposure from a settled close and FRESHNESS-2
stopped the BRAIN reasoning from one. Neither reached the toolbox, which is
where the location facts are actually manufactured.

    A SETTLED CLOSE ESTABLISHES WHERE A ZONE IS.
    IT CANNOT SAY WHERE PRICE IS.

THE AUTHORITY SPLIT THIS UNIT DRAWS, and deliberately does not cross:

  settled close  -> locates zone geometry, and feeds CONTINUITY-2F's dual-arm
                    comparison. Both ask what the market has DONE. UNCHANGED.
  fresh quote    -> re-answers the five LOCATION_FIELDS, and nothing else.

Re-anchoring runs AFTER `_execution_geometry` has been compared on both arms,
and `LOCATION_FIELDS` shares no member with `EXECUTION_GEOMETRY_FIELDS`, so 2F's
verdict is unreachable from here. Fresh price does NOT choose which zone is
selected — that would blur execution state into structural truth.

ON `invalidated`, WHICH LOOKS LIKE STRUCTURE AND IS NOT. It is re-anchored, and
that is deliberate. The repository already settled its meaning: "`invalidated`
is where price sits NOW; `retired` is whether an authoritative close already
killed this occurrence for good." Its consumers agree — `_raw_trigger_status`
is documented as "Score/price-based trigger status" and reads it beside
`price_relation`. `retired` carries the settled authority, lives outside
LOCATION_FIELDS, and this unit does not touch it.
"""
from __future__ import annotations

import os
import sys
from datetime import datetime, timezone

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))

from broker import topstepx_execution_price as EP                  # noqa: E402
from broker.topstepx_slippage import capture_quote                 # noqa: E402
from toolbox.price_levels import (EXECUTION_GEOMETRY_FIELDS,       # noqa: E402
                                  LOCATION_BASIS_ABSENT,
                                  LOCATION_BASIS_EXECUTION,
                                  LOCATION_FIELDS, _execution_location,
                                  _reanchor_location)

NOW = datetime(2026, 8, 20, 15, 2, 10, tzinfo=timezone.utc)
CID = "CON.F.US.MNQ.U26"

# ── the archived 11:02:10 zone, verbatim ─────────────────────────────────────
SETTLED_CLOSE = 29404.25
FRESH_BID = 29440.75
FRESH_ASK = 29441.00
ZONE_LOW = 29394.72
ZONE_HIGH = 29412.74


def zone(**over):
    z = {"level_type": "ote_zone", "direction": "bearish",
         "zone_low": ZONE_LOW, "zone_high": ZONE_HIGH, "midpoint": 29403.73,
         "current_price": SETTLED_CLOSE, "distance_to_zone": 0.0,
         "price_relation": "inside_zone", "entered_zone": True,
         "invalidated": False, "invalidation_level": 29435.0,
         "source_tf": "3m", "_touch_tol": 0.0}
    z.update(over)
    return z


def snap(bid=FRESH_BID, ask=FRESH_ASK, *, age=0.4, present=True):
    if not present:
        return {}
    q = capture_quote(market_hub_quote={"bestBid": bid, "bestAsk": ask,
                                        "lastPrice": bid},
                      contract_id=CID, market_data_age_seconds=age, now=NOW)
    return {"execution_price": EP.from_capture(q)}


# ══════════════════════════════════════════════════════════════════════════════
class TestTheElevenOhTwoDefect:
    def test_the_settled_close_reported_price_inside_the_zone(self):
        """What shipped: a zone price had already left, reported as standing in it."""
        z = zone()
        assert z["price_relation"] == "inside_zone"
        assert z["distance_to_zone"] == 0.0
        assert ZONE_LOW <= SETTLED_CLOSE <= ZONE_HIGH      # true of the STALE price

    def test_the_market_was_twenty_eight_points_above_it(self):
        assert FRESH_BID > ZONE_HIGH
        assert round(FRESH_BID - ZONE_HIGH, 2) == 28.01

    def test_re_anchoring_corrects_the_relation(self):
        z = _reanchor_location(zone(), snap(), "bearish")
        assert z["price_relation"] == "above_zone"
        assert z["distance_to_zone"] == 28.01
        assert z["entered_zone"] is False

    def test_the_corrected_price_is_the_executable_one(self):
        z = _reanchor_location(zone(), snap(), "bearish")
        assert z["current_price"] == FRESH_BID

    def test_the_settled_close_is_preserved_as_structural_context(self):
        """Not deleted — demoted. It still answers what the market has DONE."""
        z = _reanchor_location(zone(), snap(), "bearish")
        assert z["settled_price"] == SETTLED_CLOSE

    def test_the_basis_is_stated(self):
        assert _reanchor_location(zone(), snap(), "bearish")["location_basis"] \
            == LOCATION_BASIS_EXECUTION


class TestStructuralGeometryIsUntouched:
    """The zone exists because of settled structure. A quote may not move it."""

    @pytest.mark.parametrize("field", EXECUTION_GEOMETRY_FIELDS)
    def test_every_geometry_field_survives_re_anchoring(self, field):
        before = zone()
        after = _reanchor_location(zone(), snap(), "bearish")
        assert after[field] == before[field], field

    def test_the_midpoint_is_untouched(self):
        assert _reanchor_location(zone(), snap(), "bearish")["midpoint"] == 29403.73

    def test_the_temporal_verdict_is_untouched(self):
        z = _reanchor_location(zone(temporal_class="settled",
                                    temporal_execution_eligible=True),
                               snap(), "bearish")
        assert z["temporal_class"] == "settled"
        assert z["temporal_execution_eligible"] is True

    def test_occurrence_identity_is_untouched(self):
        z = _reanchor_location(zone(occurrence_id="3m:ote:29394.72"),
                               snap(), "bearish")
        assert z["occurrence_id"] == "3m:ote:29394.72"

    def test_a_wildly_different_quote_still_moves_no_geometry(self):
        z = _reanchor_location(zone(), snap(bid=31000.0, ask=31000.25), "bearish")
        assert (z["zone_low"], z["zone_high"]) == (ZONE_LOW, ZONE_HIGH)
        assert z["invalidation_level"] == 29435.0
        assert z["price_relation"] == "above_zone"      # only location moved


class TestTheTwoFieldSetsAreDisjoint:
    """The structural proof that CONTINUITY-2F is unreachable from here."""

    def test_no_field_belongs_to_both(self):
        assert not (set(LOCATION_FIELDS) & set(EXECUTION_GEOMETRY_FIELDS))

    def test_re_anchoring_writes_only_location_fields(self):
        before, after = zone(), _reanchor_location(zone(), snap(), "bearish")
        changed = {k for k in before
                   if k in after and before[k] != after[k]}
        assert changed <= set(LOCATION_FIELDS), changed

    def test_retired_is_not_a_location_field(self):
        """`retired` is the SETTLED kill. `invalidated` is where price sits now."""
        assert "retired" not in LOCATION_FIELDS

    def test_a_retired_occurrence_stays_retired(self):
        z = _reanchor_location(zone(retired=True, retirement_reason="closed through"),
                               snap(), "bearish")
        assert z["retired"] is True
        assert z["retirement_reason"] == "closed through"

    def test_re_anchoring_happens_after_the_2f_comparison(self):
        """AST: the call must follow `_execution_geometry`, or a fresh quote
        could change which arm 2F compares."""
        import ast
        import inspect
        import textwrap
        from toolbox import price_levels as PL
        src = textwrap.dedent(inspect.getsource(PL.build_price_level))
        body = ast.unparse(ast.parse(src))
        assert "_reanchor_location" in body
        assert body.index("_execution_geometry") < body.index("_reanchor_location")


class TestTheSideIsCorrect:
    def test_a_short_measures_from_the_bid(self):
        px, basis = _execution_location(snap(), "bearish")
        assert px == FRESH_BID and basis == LOCATION_BASIS_EXECUTION

    def test_a_long_measures_from_the_ask(self):
        px, _ = _execution_location(snap(), "bullish")
        assert px == FRESH_ASK

    def test_the_zone_direction_drives_the_side(self):
        short = _reanchor_location(zone(direction="bearish"), snap(), "bearish")
        long_ = _reanchor_location(zone(direction="bullish"), snap(), "bullish")
        assert short["current_price"] == FRESH_BID
        assert long_["current_price"] == FRESH_ASK

    def test_an_unresolved_direction_fails_closed(self):
        px, basis = _execution_location(snap(), "conflicted")
        assert px is None
        assert basis.startswith("execution_price_unusable")


class TestFailClosed:
    def test_an_absent_block_yields_unknown_location(self):
        z = _reanchor_location(zone(), snap(present=False), "bearish")
        assert z["price_relation"] == "unknown"
        assert z["distance_to_zone"] is None
        assert z["entered_zone"] is False
        assert z["location_basis"] == LOCATION_BASIS_ABSENT

    def test_a_stale_quote_yields_unknown_location(self):
        z = _reanchor_location(zone(), snap(age=90.0), "bearish")
        assert z["price_relation"] == "unknown"
        assert EP.STALE_QUOTE in z["location_basis"]

    def test_the_settled_close_is_never_substituted(self):
        """The whole point. No fresh price means no location claim."""
        for s in (snap(present=False), snap(age=90.0)):
            z = _reanchor_location(zone(), s, "bearish")
            assert z["current_price"] is None
            assert z["current_price"] != SETTLED_CLOSE

    def test_no_quote_is_invented(self):
        z = _reanchor_location(zone(), snap(present=False), "bearish")
        assert z["settled_price"] == SETTLED_CLOSE     # stated, not promoted
        assert z["current_price"] is None

    def test_structural_geometry_survives_a_missing_quote(self):
        """Losing the quote must not lose the zone."""
        z = _reanchor_location(zone(), snap(present=False), "bearish")
        for f in EXECUTION_GEOMETRY_FIELDS:
            assert z[f] == zone()[f], f

    def test_invalidated_is_not_asserted_without_a_price(self):
        z = _reanchor_location(zone(invalidated=True), snap(present=False), "bearish")
        assert z["invalidated"] is False      # unknown location asserts nothing


class TestInvalidatedIsAPricePositionFact:
    """Audited before this unit locked it in. It is meaning A, per the
    repository's own comment and its consumers."""

    def test_it_is_re_anchored_with_the_other_location_fields(self):
        assert "invalidated" in LOCATION_FIELDS

    def test_a_short_beyond_its_invalidation_reads_invalidated(self):
        z = _reanchor_location(zone(), snap(bid=29440.0, ask=29440.25), "bearish")
        assert z["invalidation_level"] == 29435.0
        assert z["invalidated"] is True          # 29440.0 > 29435.0

    def test_and_below_it_does_not(self):
        z = _reanchor_location(zone(), snap(bid=29430.0, ask=29430.25), "bearish")
        assert z["invalidated"] is False

    def test_the_stale_close_would_have_answered_differently(self):
        """29404.25 is below 29435.0, so the settled close said 'not
        invalidated' while the market was above the level."""
        assert SETTLED_CLOSE < 29435.0
        assert FRESH_BID > 29435.0

    def test_its_consumer_treats_it_as_price_based(self):
        import inspect
        from toolbox import entry_trigger_prep as ETP
        doc = inspect.getdoc(ETP._raw_trigger_status) or ""
        assert "price-based" in doc.lower()


class TestThePrivateToleranceDoesNotLeak:
    @pytest.mark.parametrize("s", [snap(), snap(present=False), snap(age=90.0)])
    def test_touch_tol_is_stripped_on_every_path(self, s):
        assert "_touch_tol" not in _reanchor_location(zone(), s, "bearish")

    def test_the_zone_built_tolerance_is_the_one_applied(self):
        """A zone built with adjacency tolerance keeps it when re-anchored."""
        z = _reanchor_location(zone(_touch_tol=30.0), snap(), "bearish")
        assert z["price_relation"] == "touching_zone"   # 28.01 away, tol 30
