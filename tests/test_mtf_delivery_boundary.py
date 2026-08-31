"""The hop nothing tested: tracker registry -> brain_input -> catalog.

v10 built the per-timeframe protected-swing registry. v11 pinned that
`authorized_invalidation_catalog` honours a registry when it is given one.
Neither pinned that the payload DELIVERS one, and the defect lived exactly
there: `brain_input._protected` REBUILT the block from the two legacy summary
fields and silently dropped `by_timeframe`, so the catalog fell through to the
legacy branch and published a single INV_PH_1 / INV_PL_1 pair.

PROD-20260811, 10:32:07, price 29746.00. The tracker held protected highs on
1m (29773.75, 27.75pt), 3m and 5m (29793.00, 47.00pt). Terra was handed ONE
side-valid bearish invalidation -- the 47-point one -- and the candidate died
correctly on the 40-point ceiling while a 27.75-point execution-timeframe
structure sat unused in the same snapshot. The tracker was right. The catalog
was right. The bridge between them was wrong.

The v11 test could not have caught this: it constructed the registry itself and
handed it straight to the catalog, so it proved the catalog's behaviour and
nothing about the payload. These tests start from the verbatim production
`protected_swings` block and run the PUBLIC builder, so a future reconstruction
of the payload fails here instead of live.

WHAT THIS FILE DELIBERATELY DOES NOT ASSERT: that Terra selects the 1m level,
or any level. Delivery is the contract; selection is Terra's. Pinning the
choice would hard-code execution-timeframe preference -- the same collapse as
2026-08-10, only pointing the other way. The whole value of the fix is that
10:32 becomes a real question: here are three side-valid bearish structural
invalidations, which one actually falsifies the thesis?
"""
from __future__ import annotations

import json
import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))

from ai_brain.brain_input import build_brain_input                 # noqa: E402
from ai_brain.brain_validation import scan_payload_taint           # noqa: E402
from broker.luna_candidate_producer import (                       # noqa: E402
    authorized_invalidation_catalog)
from narrative_authority import protected_swings as PS             # noqa: E402

FIXTURE = os.path.join(ROOT, "tests", "fixtures",
                       "prod20260811_103207_protected_swings.json")
#: The untrimmed live artifact, when this machine still has it. Never required.
LIVE_ARCHIVE = os.path.join(ROOT, "data", "ai_brain", "20260811_103207_MNQ.json")

PROVENANCE = ("timeframe", "role", "swing_id", "registered_at", "basis")


def fixture() -> dict:
    with open(FIXTURE, encoding="utf-8") as fh:
        return json.load(fh)


def snapshot() -> dict:
    """The production block, inside a snapshot the real builder accepts."""
    fx = fixture()
    bar = {"open": 29750.0, "high": 29752.0, "low": 29744.0, "close": fx["price"]}
    return {"timestamp": "2026-08-11T14:32:07+00:00",
            "session": "PROD-20260811",
            "protected_swings": fx["protected_swings"],
            "timeframes": {"1m": {"recent_candles": [dict(bar) for _ in range(5)]}}}


def registry_less_snapshot() -> dict:
    """The same scan as the payload actually shaped it live."""
    snap = snapshot()
    snap["protected_swings"] = {k: v for k, v in snap["protected_swings"].items()
                                if k not in ("by_timeframe", "roles")}
    return snap


def built() -> dict:
    return build_brain_input(snapshot(), {})


def catalog() -> list:
    return authorized_invalidation_catalog(built())


def bearish_stops(entries, price) -> list:
    """Side-valid invalidations for a short: protected highs ABOVE price."""
    return [c for c in entries if c["type"] == "protected_high" and c["price"] > price]


class TestTheRegistryReachesThePayload:

    def test_build_brain_input_delivers_by_timeframe(self):
        block = built()["protected_swings"]
        assert block.get("by_timeframe"), "registry stripped between tracker and Terra"
        assert set(block["by_timeframe"]["highs"]) == {"1m", "3m", "5m"}
        assert set(block["by_timeframe"]["lows"]) == {"15m", "1m", "3m"}

    def test_the_timeframe_roles_travel_with_it(self):
        assert built()["protected_swings"].get("roles") == dict(PS.TIMEFRAME_ROLES)

    def test_the_builder_reads_the_real_price(self):
        assert built()["market"]["current_price"] == fixture()["price"]

    def test_the_legacy_summary_fields_are_unchanged(self):
        block = built()["protected_swings"]
        assert block["protected_high"]["level"] == 29793.0
        assert block["protected_low"]["level"] == 29636.0
        assert block["protected_high_status"] and block["protected_low_status"]


class TestProvenanceSurvivesTheHop:
    """Preserved, not reinterpreted. A level without its swing id, its
    timeframe and when it registered is a number, not a structural fact."""

    def test_every_record_arrives_byte_identical(self):
        src = fixture()["protected_swings"]["by_timeframe"]
        got = built()["protected_swings"]["by_timeframe"]
        for bucket in ("highs", "lows"):
            for tf, record in src[bucket].items():
                assert got[bucket][tf] == record, f"{bucket}.{tf} was reinterpreted"

    def test_every_record_carries_full_provenance(self):
        got = built()["protected_swings"]["by_timeframe"]
        for bucket in ("highs", "lows"):
            for tf, record in got[bucket].items():
                for field in PROVENANCE:
                    assert record.get(field) is not None, f"{bucket}.{tf}.{field}"

    def test_provenance_reaches_the_catalog_entries(self):
        for entry in catalog():
            if entry["invalidation_id"] in ("INV_PH_1", "INV_PL_1"):
                continue
            for field in PROVENANCE:
                assert entry.get(field) is not None, (entry["invalidation_id"], field)
            assert entry["source"].startswith("protected_swings.by_timeframe.")


class TestPerTimeframeIdsNotTheLegacyPair:

    def test_the_catalog_publishes_every_registered_level(self):
        ids = [c["invalidation_id"] for c in catalog()]
        assert "INV_PH_1" not in ids and "INV_PL_1" not in ids, \
            "legacy summary branch fired despite a registry being present"
        assert len(ids) == 6, ids
        assert sorted(ids) == ["INV_PH_1m_1", "INV_PH_3m_2", "INV_PH_5m_3",
                              "INV_PL_15m_1", "INV_PL_1m_2", "INV_PL_3m_3"]

    def test_legacy_summary_still_serves_snapshots_without_a_registry(self):
        """Backward compatibility only -- older archives and replays."""
        cat = authorized_invalidation_catalog(
            build_brain_input(registry_less_snapshot(), {}))
        assert [c["invalidation_id"] for c in cat] == ["INV_PH_1", "INV_PL_1"]


class TestTheHistoricalFixture:

    def test_three_bearish_invalidations_are_offered(self):
        price = fixture()["price"]
        stops = bearish_stops(catalog(), price)
        assert {c["timeframe"] for c in stops} == {"1m", "3m", "5m"}
        by_tf = {c["timeframe"]: c["price"] for c in stops}
        assert by_tf["1m"] == 29773.75 and abs(by_tf["1m"] - price) == 27.75
        assert by_tf["3m"] == by_tf["5m"] == 29793.0

    def test_at_least_one_of_them_is_inside_the_ceiling(self):
        price = fixture()["price"]
        inside = [c for c in bearish_stops(catalog(), price)
                  if abs(c["price"] - price) <= 40.0]
        assert inside, "no bearish stop inside the ceiling despite one existing"

    def test_live_delivered_exactly_one(self):
        """What the collapsed payload actually handed Terra at 10:32:07."""
        price = fixture()["price"]
        cat = authorized_invalidation_catalog(
            build_brain_input(registry_less_snapshot(), {}))
        stops = bearish_stops(cat, price)
        assert len(stops) == 1 and abs(stops[0]["price"] - price) == 47.00


class TestDeliveryNeverBecomesSelection:
    """Every one of these is a way of secretly choosing FOR Terra."""

    def test_the_ceiling_does_not_filter_delivery(self):
        price = fixture()["price"]
        outside = [c for c in catalog() if c["type"] == "protected_high"
                   and abs(c["price"] - price) > 40.0]
        assert len(outside) == 2, "40-point permission leaked into delivery"

    def test_wrong_side_levels_are_still_published(self):
        assert [c for c in catalog() if c["type"] == "protected_low"]

    def test_entries_are_ordered_by_registry_key_not_distance(self):
        """The fixture's own low ordering is ascending by distance BY
        COINCIDENCE (15m 6.50 < 1m 9.25 < 3m 110.00 happens to match
        alphabetical), so it cannot tell the two rules apart. This constructs
        a registry where the orders disagree and pins which one wins."""
        price = 29746.0
        snap = snapshot()
        snap["protected_swings"] = {
            "by_timeframe": {"highs": {}, "lows": {
                tf: {"level": lvl, "timeframe": tf, "role": PS.TIMEFRAME_ROLES[tf],
                     "registered_at": "2026-08-11T14:30:00+00:00",
                     "swing_id": f"{tf}:swing_low:{lvl}", "basis": "sell_side_raid_rejected"}
                for tf, lvl in (("15m", 29646.0), ("1m", 29676.0),
                                ("3m", 29706.0), ("5m", 29736.0))}},
            "roles": dict(PS.TIMEFRAME_ROLES)}
        cat = authorized_invalidation_catalog(build_brain_input(snap, {}))
        assert [c["timeframe"] for c in cat] == ["15m", "1m", "3m", "5m"], \
            "order is registry order; nearest-first would be a ranking"
        distances = [abs(c["price"] - price) for c in cat]
        assert distances == [100.0, 70.0, 40.0, 10.0]
        assert distances != sorted(distances), "delivery sorted by proximity"

    def test_no_entry_claims_to_be_the_chosen_one(self):
        for entry in catalog():
            for key in ("selected", "preferred", "rank", "best", "weight",
                        "priority", "recommended"):
                assert key not in entry, f"{key} in {entry['invalidation_id']}"

    def test_the_execution_timeframe_gets_a_label_not_a_privilege(self):
        for entry in catalog():
            if entry.get("timeframe") == "1m":
                assert entry["role"] == "execution"
        roles = {c["timeframe"]: c["role"] for c in catalog() if c.get("role")}
        assert roles == {"1m": "execution", "3m": "transition",
                         "5m": "active_leg", "15m": "context"}

    def test_no_deduplication_beyond_the_catalogs_own_price_guard(self):
        """3m and 5m share 29793.0 and BOTH survive -- they are different
        structural facts that happen to sit at the same price."""
        same = [c for c in catalog() if c["price"] == 29793.0]
        assert {c["timeframe"] for c in same} == {"3m", "5m"}


class TestTheHopChangesNothingElse:

    def test_the_delivered_payload_is_taint_clean(self):
        ok, hits = scan_payload_taint(built())
        assert ok, hits

    def test_no_legacy_directional_key_in_the_structural_blocks(self):
        """`bias` / `state` are the legacy structure engine's directional
        verdicts, and carrying them is what killed 43 scans on 2026-08-11.

        Scoped to the structural blocks on purpose. The payload's OTHER
        `state` keys are unrelated and predate all of this -- `delivery.state`
        is the expansion delivery state from shared_context, which is not a
        direction and is not sourced from the structure engine. A blanket
        key-name ban would fail on it and prove nothing.
        """
        payload = built()
        scoped = {k: payload.get(k) for k in
                  ("protected_swings", "MTF_MARKET_STATE", "structure_flips")}
        offenders = []

        def walk(node, path=""):
            if isinstance(node, dict):
                for key, value in node.items():
                    here = f"{path}.{key}"
                    if key in ("bias", "state"):
                        offenders.append(here)
                    walk(value, here)
            elif isinstance(node, list):
                for item in node:
                    walk(item, path + "[]")

        walk(scoped)
        assert not offenders, offenders

    def test_risk_doctrine_is_untouched(self):
        from broker import topstepx_combine_risk as R
        assert R.ABSOLUTE_MAX_STOP_POINTS == 50.0
        assert R.PREFERRED_MAX_STOP_POINTS == 35.0
        assert R.PRODUCTION_MAX_RISK_USD == 350.00
        assert R.PRODUCTION_MAX_CONTRACTS == 15
        assert R.MIN_REWARD_TO_RISK == 1.0

    def test_the_delivery_hop_touches_no_architecture_gate(self):
        """No ECU, no shadow, no env read. This hop only moves facts."""
        import ai_brain.brain_input as BI
        with open(BI.__file__, encoding="utf-8") as fh:
            source = fh.read()
        for flag in ("BRAIN_ECU_MODE", "TWO_BRAIN", "SHADOW",
                     "os.getenv", "os.environ"):
            assert flag not in source, f"{flag} appeared in the delivery hop"


class TestAgainstTheUntrimmedLiveArtifact:
    """Belt and braces: the fixture is a trimmed copy, so when the real
    artifact is still on disk, run the same assertions through it."""

    def test_the_full_artifact_yields_the_same_three_stops(self):
        if not os.path.exists(LIVE_ARCHIVE):
            pytest.skip("live 10:32:07 artifact not retained on this machine")
        with open(LIVE_ARCHIVE, encoding="utf-8") as fh:
            raw = json.load(fh)["raw_snapshot"]
        cat = authorized_invalidation_catalog(build_brain_input(raw, {}))
        stops = bearish_stops(cat, fixture()["price"])
        assert {c["timeframe"] for c in stops} == {"1m", "3m", "5m"}
        assert {c["price"] for c in stops} == {29773.75, 29793.0}

    def test_the_fixture_matches_the_artifact_verbatim(self):
        if not os.path.exists(LIVE_ARCHIVE):
            pytest.skip("live 10:32:07 artifact not retained on this machine")
        with open(LIVE_ARCHIVE, encoding="utf-8") as fh:
            raw = json.load(fh)["raw_snapshot"]
        assert fixture()["protected_swings"] == raw["protected_swings"]
