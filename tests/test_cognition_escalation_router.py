"""COGNITION-ESCALATION-ROUTER-1 -- the ruled predicate, and what must NOT fire.

No provider. No network. No broker. The router is a pure function; the sink is
the only I/O and it is pointed at tmp_path.

Most of this file is negative: the rule was ruled the way it was BECAUSE the
obvious standalone versions were measured and rejected. A suite that only proved
the escalations fire would pass just as happily on a router that always says
Terra.
"""
from __future__ import annotations

import glob
import json
import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))

from cognition import escalation_router as R                        # noqa: E402

ARCHIVE = os.path.join(ROOT, "data", "ai_brain")


# -- builders ---------------------------------------------------------------
def path(owner="bullish", status="active", transfer=None, available=True):
    if not available:
        return {"state_available": False,
                "unavailable_reason": "path_state_unavailable",
                "owner": None, "status": None, "forming_direction": None}
    te = {"opposing_structure_break": False, "load_bearing_failure": False,
          "load_bearing_replaced_against_path": False,
          "opposing_raid_rejected": False,
          "opposing_market_structure_shift": None, "opposing_displacement": None}
    te.update(transfer or {})
    return {"state_available": True, "owner": owner, "status": status,
            "forming_direction": None, "transfer_evidence": te}


def tool(direction, relation="inside_zone"):
    return {"direction": direction, "price_relation": relation, "tool": "fvg"}


def objective(intervening=False):
    return {"objective_id": "OBJ_1",
            "protected_level_between_entry_and_target": intervening}


# == THE FOUR ESCALATIONS ====================================================
class TestTerraEscalates:

    def test_contested_path_escalates_alone(self):
        v = R.route(active_path_state=path(status="contested"))
        assert v["tier"] == R.TERRA_SHADOW
        assert R.REASON_CONTESTED in v["reasons"]

    def test_counter_path_plus_transfer_evidence_escalates(self):
        v = R.route(active_path_state=path(
                        owner="bullish",
                        transfer={"opposing_structure_break": True}),
                    tool_catalog=[tool("bearish")])
        assert v["tier"] == R.TERRA_SHADOW
        assert R.REASON_COUNTER_AND_TRANSFER in v["reasons"]


# == WHAT THE DOCTRINE SAYS MUST NOT ESCALATE ================================
class TestNothingElseEscalates:

    def test_intervening_structure_alone_does_not_escalate(self):
        """83.2 percent prevalent corpus-wide. Alone it would mean always-Terra."""
        v = R.route(active_path_state=path(owner="bullish"),
                    tool_catalog=[tool("bullish")],
                    objective_catalog=[objective(intervening=True)])
        assert v["tier"] == R.LUNA_SHADOW
        assert v["predicates"]["intervening_protected_structure"] is True

    def test_counter_path_at_location_alone_does_not_escalate(self):
        v = R.route(active_path_state=path(owner="bullish"),
                    tool_catalog=[tool("bearish")],
                    objective_catalog=[objective(intervening=False)])
        assert v["tier"] == R.LUNA_SHADOW
        assert v["predicates"]["counter_path_at_location"] is True

    def test_transfer_evidence_alone_does_not_escalate(self):
        v = R.route(active_path_state=path(
                        owner="bullish",
                        transfer={"opposing_raid_rejected": True}),
                    tool_catalog=[tool("bullish")])
        assert v["tier"] == R.LUNA_SHADOW
        assert v["predicates"]["transfer_evidence_present"] is True

    def test_forming_direction_alone_does_not_escalate(self):
        """A rejected raid opens a hypothesis. Routing on it would buy the
        expensive tier for ordinary retracement behaviour."""
        aps = path(owner="none", status="forming")
        aps["forming_direction"] = "bullish"
        v = R.route(active_path_state=aps, tool_catalog=[tool("bearish")],
                    objective_catalog=[objective(intervening=True)])
        assert v["tier"] == R.LUNA_SHADOW
        assert v["predicates"]["counter_path_at_location"] is False


# == DATA QUALITY IS NOT AN ESCALATION =======================================
class TestUnavailableStateIsDataQuality:

    def test_unavailable_path_never_escalates(self):
        v = R.route(active_path_state=path(available=False),
                    tool_catalog=[tool("bearish")],
                    objective_catalog=[objective(intervening=True)])
        assert v["tier"] == R.LUNA_SHADOW
        assert v["predicates"]["path_state_unavailable"] is True

    def test_unavailable_is_recorded_not_hidden(self):
        v = R.route(active_path_state=path(available=False))
        assert v["path_owner"] is None and v["path_status"] is None

    def test_no_escalation_survives_an_unavailable_path(self):
        """With R2 retired, EVERY remaining clause needs an established owner or
        a status, so unavailable path state can no longer escalate by any route."""
        v = R.route(active_path_state=path(available=False),
                    tool_catalog=[tool("bullish"), tool("bearish")],
                    objective_catalog=[objective(intervening=True)])
        assert v["tier"] == R.LUNA_SHADOW
        assert v["reasons"] == []


# == TRUTHFUL NULLS ==========================================================
class TestTruthfulNulls:

    def test_none_valued_evidence_is_not_presence(self):
        """A null means the producer cannot say. Counting it as evidence would
        escalate on the ABSENCE of knowledge."""
        aps = path(owner="bullish",
                   transfer={"opposing_displacement": None,
                             "opposing_market_structure_shift": None})
        assert R.transfer_evidence_present(aps) is False

    def test_truthy_non_true_is_not_presence(self):
        aps = path(owner="bullish")
        aps["transfer_evidence"]["opposing_structure_break"] = "yes"
        assert R.transfer_evidence_present(aps) is False


# == LOCATION VOCABULARY =====================================================
class TestAtLocationMeansWhatExecutionMeans:

    def test_relations_match_the_order_builder(self):
        from paper_execution.order_builder import _IN_ZONE_RELATIONS
        assert R.AT_LOCATION_RELATIONS == _IN_ZONE_RELATIONS

    def test_distant_zones_are_not_locations(self):
        v = R.route(active_path_state=path(owner="bullish"),
                    tool_catalog=[tool("bearish", "below_zone"),
                                  tool("bullish", "above_zone")])
        assert v["at_location_count"] == 0
        assert v["tier"] == R.LUNA_SHADOW


# == PURITY AND STRUCTURAL ZERO-DIFF =========================================
class TestPurityAndIsolation:

    def test_route_mutates_nothing(self):
        aps, cat, obj = path(), [tool("bullish")], [objective(True)]
        before = json.dumps([aps, cat, obj], sort_keys=True)
        R.route(active_path_state=aps, tool_catalog=cat, objective_catalog=obj)
        assert json.dumps([aps, cat, obj], sort_keys=True) == before

    def test_no_weighted_score_is_published(self):
        v = R.route(active_path_state=path(status="contested"))
        assert not any("score" in k or "weight" in k for k in v)

    def test_observe_never_raises_on_garbage(self):
        assert R.observe(snapshot="not a dict", brain_input=7) is None

    def test_observe_does_not_touch_the_brain_payload(self, tmp_path, monkeypatch):
        monkeypatch.setenv(R.SINK_DIR_ENV, str(tmp_path))
        bi = {"authorized_tool_catalog": [tool("bullish"), tool("bearish")],
              "authorized_objectives": [objective(True)]}
        snap = {"active_path_state": path(), "timestamp": "2026-08-24T10:52:00"}
        before = json.dumps(bi, sort_keys=True)
        R.observe(snapshot=snap, brain_input=bi, symbol="MNQ")
        assert json.dumps(bi, sort_keys=True) == before
        assert "escalation" not in before and "shadow" not in before

    def test_the_sink_is_a_separate_file(self, tmp_path, monkeypatch):
        monkeypatch.setenv(R.SINK_DIR_ENV, str(tmp_path))
        snap = {"active_path_state": path(status="contested"),
                "timestamp": "2026-08-24T10:52:00"}
        R.observe(snapshot=snap, brain_input={}, symbol="MNQ")
        with open(R.sink_path("2026-08-24T10:52:00"), encoding="utf-8") as fh:
            rows = [json.loads(line) for line in fh if line.strip()]
        assert len(rows) == 1 and rows[0]["tier"] == R.TERRA_SHADOW
        assert rows[0]["timestamp"] == "2026-08-24T10:52:00"


# == THE ARCHIVE =============================================================
class TestAgainstRealTape:

    @pytest.fixture(scope="class")
    def catalog(self):
        f = os.path.join(ARCHIVE, "20260824_105200_MNQ.json")
        if not os.path.exists(f):
            pytest.skip("archived 10:52 specimen absent")
        from broker.luna_candidate_producer import authorized_tool_catalog
        with open(f, encoding="utf-8") as fh:
            snap = json.load(fh)["raw_snapshot"]
        return authorized_tool_catalog(snap)

    def test_real_catalog_produces_a_verdict(self, catalog):
        v = R.route(active_path_state=path(), tool_catalog=catalog)
        assert v["tier"] in (R.LUNA_SHADOW, R.TERRA_SHADOW)
        assert v["at_location_count"] >= 1, "10:52 had rows at location"

    def test_every_archived_scan_routes_without_raising(self):
        files = sorted(glob.glob(os.path.join(ARCHIVE, "20260824_*_MNQ.json")))
        if not files:
            pytest.skip("archive absent")
        from broker.luna_candidate_producer import authorized_tool_catalog
        for f in files[:40]:
            try:
                with open(f, encoding="utf-8") as fh:
                    snap = json.load(fh)["raw_snapshot"]
            except Exception:  # noqa: BLE001
                continue
            v = R.route(active_path_state=snap.get("active_path_state"),
                        tool_catalog=authorized_tool_catalog(snap))
            assert v["tier"] in (R.LUNA_SHADOW, R.TERRA_SHADOW)


# == ZERO BEHAVIOUR DIFFERENCE, AGAINST REAL PAYLOADS ========================
class TestZeroBehaviourDiffOnRealPayloads:
    """The synthetic payload test above proves `observe` does not mutate a dict.

    This proves the stronger thing the shadow claim actually rests on: run
    against the REAL production payload object graph, the router leaves both the
    Brain input and the snapshot byte-identical. Bound to the real object graph
    on purpose -- MARKET-REALITY's lesson was that a regression bound to a
    hand-built stand-in certifies the stand-in.
    """

    SCANS = ("20260824_105200_MNQ.json", "20260824_104257_MNQ.json",
             "20260824_112011_MNQ.json")

    def _payloads(self):
        from ai_brain.brain_input import build_brain_input
        out = []
        for name in self.SCANS:
            f = os.path.join(ARCHIVE, name)
            if not os.path.exists(f):
                continue
            with open(f, encoding="utf-8") as fh:
                snap = json.load(fh)["raw_snapshot"]
            out.append((snap, build_brain_input(snap, {"available": False})))
        return out

    def test_payload_and_snapshot_survive_untouched(self, tmp_path, monkeypatch):
        monkeypatch.setenv(R.SINK_DIR_ENV, str(tmp_path))
        pairs = self._payloads()
        if not pairs:
            pytest.skip("archived specimens absent")
        for snap, bi in pairs:
            before_bi = json.dumps(bi, sort_keys=True, default=str)
            before_snap = json.dumps(snap, sort_keys=True, default=str)
            R.observe(snapshot=snap, brain_input=bi, symbol="MNQ")
            assert json.dumps(bi, sort_keys=True, default=str) == before_bi
            assert json.dumps(snap, sort_keys=True, default=str) == before_snap

    def test_nothing_the_brain_can_read_names_the_router(self, tmp_path, monkeypatch):
        """Shadow must be STRUCTURAL. If the verdict appeared anywhere in the
        payload, 'the model ignored it' would be an assumption, not a property."""
        monkeypatch.setenv(R.SINK_DIR_ENV, str(tmp_path))
        pairs = self._payloads()
        if not pairs:
            pytest.skip("archived specimens absent")
        for snap, bi in pairs:
            R.observe(snapshot=snap, brain_input=bi, symbol="MNQ")
            blob = json.dumps(bi, sort_keys=True, default=str).lower()
            for token in ("terra_shadow", "luna_shadow", "escalation_router",
                          "bidirectional_at_location"):
                assert token not in blob

    def test_the_verdict_did_reach_the_separate_sink(self, tmp_path, monkeypatch):
        """The mirror of the test above: proving nothing leaked into the payload
        is only meaningful if the record demonstrably went somewhere."""
        monkeypatch.setenv(R.SINK_DIR_ENV, str(tmp_path))
        pairs = self._payloads()
        if not pairs:
            pytest.skip("archived specimens absent")
        for snap, bi in pairs:
            R.observe(snapshot=snap, brain_input=bi, symbol="MNQ")
        written = [p for p in os.listdir(str(tmp_path)) if p.endswith(".jsonl")]
        assert written, "the shadow sink recorded nothing"
        rows = []
        for p in written:
            with open(os.path.join(str(tmp_path), p), encoding="utf-8") as fh:
                rows += [json.loads(line) for line in fh if line.strip()]
        assert len(rows) == len(pairs)
        assert all(r["tier"] in (R.LUNA_SHADOW, R.TERRA_SHADOW) for r in rows)


# == R2 RETIRED FROM AUTHORITY (measured, not tuned) =========================
class TestBidirectionalIsTelemetryOnly:
    """R2 was ruled as an escalation and disqualified by its own measurement.

    Across 975 archived scans its activation is monotonic in catalog row count
    at price -- 0% at one row, 100% at seven or more, the same curve with the
    design day excluded. It measures how many objects piled up at price, not
    whether two executable narratives genuinely compete. These tests exist so
    the flag cannot quietly regain authority.
    """

    def test_bidirectional_alone_does_not_escalate(self):
        v = R.route(active_path_state=path(),
                    tool_catalog=[tool("bullish"), tool("bearish")])
        assert v["tier"] == R.LUNA_SHADOW
        assert v["reasons"] == []

    def test_it_is_still_measured_and_published(self):
        """Retired from AUTHORITY, not from the record -- the evidence has to
        keep accruing for any future stronger representation."""
        v = R.route(active_path_state=path(),
                    tool_catalog=[tool("bullish"), tool("bearish")])
        assert v["predicates"]["bidirectional_at_location"] is True
        assert v["telemetry_only"]["bidirectional_at_location"] is True

    def test_it_never_appears_as_a_reason(self):
        v = R.route(active_path_state=path(status="contested"),
                    tool_catalog=[tool("bullish"), tool("bearish")],
                    objective_catalog=[objective(intervening=True)])
        assert R.RETIRED_REASON_BIDIRECTIONAL not in v["reasons"]
        assert set(v["reasons"]) <= set(R.AUTHORITATIVE_REASONS)

    def test_density_alone_cannot_route(self):
        """Nine rows at price, both directions, no owner -- the exact shape of
        the 2026-08-24 11:2x continuation scans that R2 escalated."""
        cat = [tool("bullish") for _ in range(5)] + [tool("bearish") for _ in range(4)]
        aps = path(owner="none", status="forming")
        v = R.route(active_path_state=aps, tool_catalog=cat,
                    objective_catalog=[objective(intervening=True)])
        assert v["at_location_count"] == 9
        assert v["tier"] == R.LUNA_SHADOW


# == R3 RETIRED FROM AUTHORITY (the conjunction withheld nothing) ===========
class TestCounterPlusInterveningIsTelemetryOnly:
    """R3 fired on 224 corpus scans -- the SAME 224 that `counter_path_at_location`
    fired on. The conjunction withheld zero cases, so R3 was counter-path wearing
    a second term, and escalating on counter-path alone is what the doctrine
    forbids. The cause is aggregation: `intervening_protected_structure` asks
    whether ANY objective on EITHER side sits behind structure, which at an 83.2%
    base rate is nearly always true once price stands at a zone.
    """

    def test_counter_plus_intervening_does_not_escalate(self):
        v = R.route(active_path_state=path(owner="bullish"),
                    tool_catalog=[tool("bearish")],
                    objective_catalog=[objective(intervening=True)])
        assert v["tier"] == R.LUNA_SHADOW
        assert v["reasons"] == []

    def test_it_is_still_measured_and_published(self):
        v = R.route(active_path_state=path(owner="bullish"),
                    tool_catalog=[tool("bearish")],
                    objective_catalog=[objective(intervening=True)])
        assert v["telemetry_only"][R.RETIRED_REASON_COUNTER_AND_INTERVENING] is True

    def test_surviving_authority_is_exactly_r1_r4_r5(self):
        assert R.AUTHORITATIVE_REASONS == (R.REASON_CONTESTED,
                                           R.REASON_COUNTER_AND_TRANSFER,
                                           R.REASON_HORIZON_CONFLICT)


# == THE 10:52 SPECIMEN STILL ESCALATES, NOW ON R4 ==========================
class TestTheLayeredSpecimenStillEscalates:
    """2026-08-24 10:52 is the scan the unit exists for: a real bearish reaction
    taken INSIDE an established bullish path. It carried affirmative transfer
    evidence, so it survives both retirements and escalates on R4 -- without
    density (R2) and without the vacuous conjunction (R3).
    """

    def test_layered_counter_path_escalates_on_r4_without_density(self):
        v = R.route(
            active_path_state=path(owner="bullish", status="active",
                                   transfer={"opposing_structure_break": True}),
            tool_catalog=[tool("bearish")],          # ONE row: no bidirectionality
            objective_catalog=[objective(intervening=True)])
        assert v["tier"] == R.TERRA_SHADOW
        assert v["reasons"] == [R.REASON_COUNTER_AND_TRANSFER]
        assert v["predicates"]["bidirectional_at_location"] is False

    def test_escalating_does_not_mean_forbidding_the_trade(self):
        """The router picks a TIER. It publishes no veto, no permission, no
        direction -- a bullish path never forbids a short, and that short ran
        roughly 55 points in its favour."""
        v = R.route(active_path_state=path(
                        owner="bullish",
                        transfer={"opposing_structure_break": True}),
                    tool_catalog=[tool("bearish")])
        for banned in ("veto", "block", "allow", "permitted", "direction",
                       "qualified", "confidence"):
            assert banned not in v


# == R5 OBJECTIVE-HORIZON CONFLICT (HORIZON-B) ==============================
def obj(price, *, valid_for, blocked=False, blocker=None,
        kind="protected_swing", oid="OBJ"):
    return {"objective_id": oid, "kind": kind, "price": price,
            "valid_for": valid_for,
            "protected_level_between_entry_and_target": blocked,
            "nearest_intervening_protected_level": blocker}


BEAR = dict(owner="bullish", status="active")     # counter side = bearish
BULL = dict(owner="bearish", status="active")     # counter side = bullish


class TestHorizonConflict:
    """R5 is the question Terra is paid for: how far may a valid counter-path
    reaction carry its thesis before traversing structure that still belongs to
    the active path? HORIZON-B: the blocking level must BE the near objective.
    """

    def test_bearish_geometry_fires(self):
        """reference > near > far, mirroring 2026-08-24 10:52."""
        v = R.route(active_path_state=path(**BEAR), tool_catalog=[tool("bearish")],
                    reference_price=29094.0,
                    objective_catalog=[obj(28979.5, valid_for="bearish"),
                                       obj(28947.75, valid_for="bearish",
                                           blocked=True, blocker=28979.5)])
        assert v["tier"] == R.TERRA_SHADOW
        assert R.REASON_HORIZON_CONFLICT in v["reasons"]

    def test_bullish_geometry_fires_identically(self):
        """reference < near < far. Same law, inverted -- no direction special case."""
        v = R.route(active_path_state=path(**BULL), tool_catalog=[tool("bullish")],
                    reference_price=29906.75,
                    objective_catalog=[obj(29915.5, valid_for="bullish"),
                                       obj(29924.5, valid_for="bullish",
                                           blocked=True, blocker=29915.5)])
        assert v["tier"] == R.TERRA_SHADOW
        assert R.REASON_HORIZON_CONFLICT in v["reasons"]

    def test_far_blocked_by_a_DIFFERENT_level_does_not_fire(self):
        """The chosen law is HORIZON-B. A third level blocking the far objective
        is a different shape: the near destination is not the structure that
        owns the path, so banking there is not the choice being described.
        Measured: this rejects 5 corpus scans, all with a liquidity-pool near.
        """
        v = R.route(active_path_state=path(**BEAR), tool_catalog=[tool("bearish")],
                    reference_price=29186.0,
                    objective_catalog=[obj(29171.5, valid_for="bearish",
                                           kind="opposing_external_liquidity"),
                                       obj(29034.25, valid_for="bearish",
                                           blocked=True, blocker=29165.75)])
        assert v["tier"] == R.LUNA_SHADOW

    def test_only_a_near_objective_is_not_a_choice(self):
        v = R.route(active_path_state=path(**BEAR), tool_catalog=[tool("bearish")],
                    reference_price=29094.0,
                    objective_catalog=[obj(28979.5, valid_for="bearish")])
        assert v["tier"] == R.LUNA_SHADOW

    def test_only_a_blocked_far_objective_is_not_a_choice(self):
        """No defensible near destination exists, so there is nothing to choose
        BETWEEN -- this is the shape retired R3 wrongly escalated."""
        v = R.route(active_path_state=path(**BEAR), tool_catalog=[tool("bearish")],
                    reference_price=29094.0,
                    objective_catalog=[obj(28947.75, valid_for="bearish",
                                           blocked=True, blocker=28979.5)])
        assert v["tier"] == R.LUNA_SHADOW

    def test_nearest_objective_itself_blocked_does_not_fire(self):
        v = R.route(active_path_state=path(**BEAR), tool_catalog=[tool("bearish")],
                    reference_price=29094.0,
                    objective_catalog=[obj(28979.5, valid_for="bearish",
                                           blocked=True, blocker=29000.0),
                                       obj(28947.75, valid_for="bearish",
                                           blocked=True, blocker=28979.5)])
        assert v["tier"] == R.LUNA_SHADOW

    def test_no_counter_path_at_location_does_not_fire(self):
        """The horizon only matters for a trade actually available right now."""
        v = R.route(active_path_state=path(**BEAR), tool_catalog=[],
                    reference_price=29094.0,
                    objective_catalog=[obj(28979.5, valid_for="bearish"),
                                       obj(28947.75, valid_for="bearish",
                                           blocked=True, blocker=28979.5)])
        assert v["tier"] == R.LUNA_SHADOW

    def test_same_path_opportunity_does_not_fire(self):
        """A bullish tool inside a bullish path is not counter-path."""
        v = R.route(active_path_state=path(**BEAR), tool_catalog=[tool("bullish")],
                    reference_price=29094.0,
                    objective_catalog=[obj(28979.5, valid_for="bearish"),
                                       obj(28947.75, valid_for="bearish",
                                           blocked=True, blocker=28979.5)])
        assert v["tier"] == R.LUNA_SHADOW

    def test_cross_side_objectives_are_ignored(self):
        """Objectives valid for the OTHER direction may never form the pair."""
        v = R.route(active_path_state=path(**BEAR), tool_catalog=[tool("bearish")],
                    reference_price=29094.0,
                    objective_catalog=[obj(28979.5, valid_for="bearish"),
                                       obj(29243.75, valid_for="bullish",
                                           blocked=True, blocker=28979.5)])
        assert v["tier"] == R.LUNA_SHADOW

    def test_objective_behind_the_entry_is_not_a_horizon(self):
        """Ordering law: SIGNED distance, never absolute. An objective on the
        wrong side of price is behind the trade, not ahead of it."""
        v = R.route(active_path_state=path(**BEAR), tool_catalog=[tool("bearish")],
                    reference_price=29094.0,
                    objective_catalog=[obj(28979.5, valid_for="bearish"),
                                       obj(29200.0, valid_for="bearish",
                                           blocked=True, blocker=28979.5)])
        assert v["tier"] == R.LUNA_SHADOW

    def test_invalid_objectives_are_ignored_not_fatal(self):
        v = R.route(active_path_state=path(**BEAR), tool_catalog=[tool("bearish")],
                    reference_price=29094.0,
                    objective_catalog=[{"price": None, "valid_for": "bearish"},
                                       "not a dict",
                                       obj("abc", valid_for="bearish"),
                                       obj(28979.5, valid_for="bearish"),
                                       obj(28947.75, valid_for="bearish",
                                           blocked=True, blocker=28979.5)])
        assert v["tier"] == R.TERRA_SHADOW

    def test_duplicate_objectives_cannot_manufacture_a_pair(self):
        """One structural level published twice is one destination, not a
        near/far choice."""
        v = R.route(active_path_state=path(**BEAR), tool_catalog=[tool("bearish")],
                    reference_price=29094.0,
                    objective_catalog=[obj(28979.5, valid_for="bearish", oid="A"),
                                       obj(28979.5, valid_for="bearish", oid="B")])
        assert v["tier"] == R.LUNA_SHADOW

    def test_tick_tolerance_boundary(self):
        """Within half a tick is one level; beyond it is another."""
        assert R.same_level(28979.5, 28979.6, 0.25) is True     # 0.10 <= 0.125
        assert R.same_level(28979.5, 28979.75, 0.25) is False   # 0.25 >  0.125
        assert R.same_level(28979.5, 28979.5) is True
        assert R.same_level(None, 28979.5, 0.25) is False

    def test_tick_tolerance_is_used_by_the_predicate(self):
        v = R.route(active_path_state=path(**BEAR), tool_catalog=[tool("bearish")],
                    reference_price=29094.0, tick_size=0.25,
                    objective_catalog=[obj(28979.5, valid_for="bearish"),
                                       obj(28947.75, valid_for="bearish",
                                           blocked=True, blocker=28979.56)])
        assert v["tier"] == R.TERRA_SHADOW

    def test_no_reference_price_cannot_fire(self):
        """Fail closed: without a lawful reference there is no ordering."""
        v = R.route(active_path_state=path(**BEAR), tool_catalog=[tool("bearish")],
                    objective_catalog=[obj(28979.5, valid_for="bearish"),
                                       obj(28947.75, valid_for="bearish",
                                           blocked=True, blocker=28979.5)])
        assert v["tier"] == R.LUNA_SHADOW


class TestClausesRemainIndependent:

    def test_r1_fires_without_r4_or_r5(self):
        v = R.route(active_path_state=path(status="contested"))
        assert v["reasons"] == [R.REASON_CONTESTED]

    def test_r4_fires_without_r5(self):
        v = R.route(active_path_state=path(
                        owner="bullish",
                        transfer={"opposing_structure_break": True}),
                    tool_catalog=[tool("bearish")])
        assert v["reasons"] == [R.REASON_COUNTER_AND_TRANSFER]

    def test_r5_fires_without_r1_or_r4(self):
        v = R.route(active_path_state=path(**BEAR), tool_catalog=[tool("bearish")],
                    reference_price=29094.0,
                    objective_catalog=[obj(28979.5, valid_for="bearish"),
                                       obj(28947.75, valid_for="bearish",
                                           blocked=True, blocker=28979.5)])
        assert v["reasons"] == [R.REASON_HORIZON_CONFLICT]

    def test_retired_clauses_still_hold_no_authority(self):
        v = R.route(active_path_state=path(owner="bullish"),
                    tool_catalog=[tool("bullish"), tool("bearish")],
                    objective_catalog=[objective(intervening=True)])
        assert v["tier"] == R.LUNA_SHADOW
        assert v["telemetry_only"][R.RETIRED_REASON_BIDIRECTIONAL] is True
        assert v["telemetry_only"][R.RETIRED_REASON_COUNTER_AND_INTERVENING] is True
        assert set(v["reasons"]) <= set(R.AUTHORITATIVE_REASONS)


class TestR5AgainstRealTape:
    """Bound to the real object graph, not a hand-built stand-in."""

    def _replay(self, name):
        f = os.path.join(ARCHIVE, name)
        if not os.path.exists(f):
            pytest.skip(f"archived specimen absent: {name}")
        from ai_brain.brain_input import build_brain_input
        from broker.luna_candidate_producer import authorized_objective_catalog
        with open(f, encoding="utf-8") as fh:
            snap = json.load(fh)["raw_snapshot"]
        bi = build_brain_input(snap, {"available": False})
        ref = (bi.get("market") or {}).get("current_price")
        return snap, authorized_objective_catalog(snap, bi, ref), ref

    def test_the_1052_specimen_produces_a_real_horizon_choice(self):
        """A bullish path, a bearish reaction, a defensible protected low and a
        farther liquidity pool behind it. Nothing here is hardcoded: the near
        and far objectives are read out of the produced catalog."""
        _, cat, ref = self._replay("20260824_105200_MNQ.json")
        fired, detail = R.horizon_conflict(cat, "bearish", ref, 0.25)
        assert fired is True
        assert detail["near_kind"] == "protected_swing"
        assert R.same_level(detail["blocking_level"], detail["near_price"], 0.25)
        assert all(f < detail["near_price"] for f in detail["far_prices"])

    def test_the_density_only_specimen_has_no_horizon_choice(self):
        """11:20:52 carried nine rows at location and escalated under the
        retired density clause. It must not come back through R5."""
        _, cat, ref = self._replay("20260824_112052_MNQ.json")
        for direction in ("bearish", "bullish"):
            fired, _ = R.horizon_conflict(cat, direction, ref, 0.25)
            assert fired is False
