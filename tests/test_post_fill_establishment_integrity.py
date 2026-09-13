"""Post-fill economics and crash-safe structural establishment."""
import json
import os
import socket
import sys
from pathlib import Path

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from broker import topstepx_submission_record as SUB
from broker.topstepx_production_session import ProductionLaneRefused, ProductionSession
from broker.topstepx_session_authorization import (
    ProductionSessionMission, SessionAuthorization,
)
from test_break_even_lifecycle_binding import fresh
from test_exec_price_anchor import _fill, _runner


@pytest.fixture(autouse=True)
def no_external_calls(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("external call reached post-fill integrity test")
    monkeypatch.setattr(socket.socket, "connect", forbidden)
    monkeypatch.setattr(socket.socket, "connect_ex", forbidden)
    import ai_brain.narrative_brain as brain
    monkeypatch.setattr(brain, "run_narrative_brain", forbidden)


class TestAllInActualFillAuthorization:
    def test_gross_pass_all_in_fail_is_refused(self):
        # 12 * 10 * $2 = $240 gross <= $250; canonical friction makes
        # all-in $278.64 and must close the already-filled position.
        runner, venue = _runner(
            "bullish", 30000.0, 29990.0, 30030.0, 30000.0, size=12)
        out = runner.reanchor_protection_to_structure(
            fill_event=_fill(30000.0, 12), working_orders=venue.open_orders())
        auth = out["authorization"]
        assert auth["gross_risk_usd"] == 240.0
        assert auth["all_in_risk_usd"] == 278.64
        assert auth["reason"] == "risk_above_cap"
        assert venue.modifies == []
        assert venue.closed

    def test_exact_all_in_ceiling_preserves_inclusive_boundary(self):
        runner, _ = _runner(
            "bullish", 30000.0, 29990.0, 30030.0, 30000.0, size=10)
        runner.max_risk_usd = 232.20
        auth = runner.authorize_actual_fill(_fill(30000.0, 10))
        assert auth["all_in_risk_usd"] == 232.20
        assert auth["authorized"] is True

    def test_lower_effective_ceiling_survives_to_actual_fill(self):
        runner, _ = _runner(
            "bullish", 30000.0, 29990.0, 30030.0, 30000.0, size=10)
        runner.max_risk_usd = 220.0
        auth = runner.authorize_actual_fill(_fill(30000.0, 10))
        assert auth["gross_risk_usd"] == 200.0
        assert auth["all_in_risk_usd"] == 232.20
        assert auth["max_risk_usd"] == 220.0
        assert auth["authorized"] is False

    def test_favorable_and_lawful_adverse_fills_keep_structure(self):
        favorable, _ = _runner(
            "bullish", 30000.0, 29980.0, 30060.0, 29998.0, size=2)
        adverse, _ = _runner(
            "bullish", 30000.0, 29980.0, 30060.0, 30002.0, size=2)
        fa = favorable.authorize_actual_fill(_fill(29998.0, 2))
        aa = adverse.authorize_actual_fill(_fill(30002.0, 2))
        assert fa["authorized"] is True and aa["authorized"] is True
        assert fa["authorized_stop_price"] == 29980.0
        assert aa["authorized_stop_price"] == 29980.0
        assert fa["all_in_risk_usd"] < aa["all_in_risk_usd"]


def _strip_post_fill_rows(store_dir, session_id):
    path = SUB.ledger_path(store_dir, session_id)
    rows = [json.loads(line) for line in open(path, encoding="utf-8") if line.strip()]
    rows = [row for row in rows if "post_fill_establishment" not in row]
    path_obj = Path(path)
    path_obj.write_text("".join(json.dumps(row) + "\n" for row in rows),
                        encoding="utf-8")


def _cold_crash_fixture(tmp_path):
    loop, ps, venue, owner, result = fresh(tmp_path)
    assert result["outcome"] == "SUBMITTED"
    mission = owner.active_mission
    geometry = ps.runner.geometry
    os.remove(ps.context_path)
    _strip_post_fill_rows(ps.store_dir, ps.session_id)
    venue.modifies.clear()
    cold = ProductionSession(
        session=venue, account_fingerprint=ps.account_fingerprint,
        contract=ps.contract, mission_id=ps.mission_id, store_dir=ps.store_dir,
        session_id=ps.session_id, quote_provider=ps.quote_provider,
        clock=ps.clock, fill_deadline_seconds=0.2)
    restored_owner = ProductionSessionMission(
        SessionAuthorization.load(owner.authorization.path), owner.store_dir)
    restored_owner.load_existing()
    loop.ps, loop.mission = cold, restored_owner
    return loop, cold, venue, restored_owner.active_mission, geometry


class TestColdRestartEstablishment:
    def test_fresh_path_persists_authorization_before_completion(self, tmp_path):
        _, ps, _, owner, result = fresh(tmp_path)
        assert result["outcome"] == "SUBMITTED"
        mission = owner.active_mission
        stages = [
            row["post_fill_establishment"]
            for row in SUB.load_submissions(ps.store_dir, ps.session_id,
                                            mission.mission_id)
            if "post_fill_establishment" in row]
        assert [block["stage"] for block in stages] == [
            SUB.ESTABLISHMENT_AUTHORIZED,
            SUB.ESTABLISHMENT_STOP_PROVEN,
            SUB.ESTABLISHMENT_PROTECTION_VERIFIED,
            SUB.ESTABLISHMENT_COMPLETE,
        ]
        authorization = stages[0]["evidence"]
        assert authorization["actual_full_fill_vwap"] == mission.fill_price
        assert authorization["actual_attributed_quantity"] == mission.filled_quantity
        assert authorization["gross_risk_usd"] < authorization["all_in_risk_usd"]
        assert authorization["max_risk_usd"] == ps.runner.max_risk_usd
        assert authorization["authorized_stop_price"] == ps.runner.geometry.stop_price
        assert authorization["structural_invalidation"]
        assert (
            authorization["structural_invalidation"]
            == ps.runner.submission_structural_invalidation
        )

    def test_provisional_stop_is_reanchored_without_second_entry(self, tmp_path):
        loop, cold, venue, mission, geometry = _cold_crash_fixture(tmp_path)
        fill = mission.fill_price
        venue._o[0]["stop_price"] = fill - geometry.stop_points
        venue._o[1]["limit_price"] = fill + geometry.target_points
        place_calls = venue.place_calls
        assert cold.open_lane()["lane"] == "RECOVERY"
        out = loop.manage_open_position()
        assert out["status"] == "establishment_recovered", out
        assert venue.place_calls == place_calls
        assert venue._o[0]["stop_price"] == geometry.stop_price
        assert cold.runner.execution_context.protection_baseline_armed is True

    def test_already_correct_venue_truth_causes_zero_writes(self, tmp_path):
        loop, cold, venue, _, geometry = _cold_crash_fixture(tmp_path)
        venue._o[0]["stop_price"] = geometry.stop_price
        venue._o[1]["limit_price"] = geometry.target_price
        assert cold.open_lane()["lane"] == "RECOVERY"
        out = loop.manage_open_position()
        assert out["status"] == "establishment_recovered", out
        assert venue.modifies == []

    def test_stop_landed_before_crash_is_not_repeated(self, tmp_path):
        loop, cold, venue, mission, geometry = _cold_crash_fixture(tmp_path)
        venue._o[0]["stop_price"] = geometry.stop_price
        venue._o[1]["limit_price"] = geometry.target_price - 1.0
        out = loop.manage_open_position()
        assert out["status"] == "establishment_recovered", out
        assert [order_id for order_id, _ in venue.modifies] == [venue._o[1]["id"]]

    def test_durable_authorization_and_completion_reload(self, tmp_path):
        loop, _, venue, mission, _ = _cold_crash_fixture(tmp_path)
        out = loop.manage_open_position()
        assert out["status"] == "establishment_recovered", out
        rows = SUB.latest_by_submission(
            loop.ps.store_dir, loop.ps.session_id, mission.mission_id)
        assert len(rows) == 1
        block = next(iter(rows.values()))["post_fill_establishment"]
        assert block["stage"] == SUB.ESTABLISHMENT_COMPLETE
        assert block["evidence"]["mission_id"] == mission.mission_id
        assert block["evidence"]["actual_fill_price"] == mission.fill_price
        assert venue.place_calls == 1

    def test_ambiguous_durable_submission_refuses_lane(self, tmp_path):
        _, cold, venue, mission, _ = _cold_crash_fixture(tmp_path)
        row = next(iter(SUB.latest_by_submission(
            cold.store_dir, cold.session_id, mission.mission_id).values()))
        duplicate = dict(row)
        duplicate["submission_id"] = "ambiguous-second-entry"
        SUB._append(SUB.ledger_path(cold.store_dir, cold.session_id), duplicate)
        with pytest.raises(ProductionLaneRefused,
                           match="ambiguous establishment recovery"):
            cold.open_lane()
        assert venue.modifies == []

    def test_incomplete_order_discovery_cannot_mutate(self, tmp_path):
        loop, cold, venue, _, _ = _cold_crash_fixture(tmp_path)

        def unavailable_query(*args, **kwargs):
            raise RuntimeError("complete query unavailable")

        venue.query_orders = unavailable_query
        assert cold.open_lane()["lane"] == "RECOVERY"
        out = loop.manage_open_position()
        assert out["status"] == "identity_unavailable", out
        assert out["recovery"]["status"] == "establishment_unavailable"
        assert "complete protection discovery" in out["recovery"]["reason"]
        assert venue.modifies == []

    def test_complete_view_missing_stop_uses_existing_emergency_flat(self, tmp_path):
        loop, cold, venue, _, _ = _cold_crash_fixture(tmp_path)
        venue._o = [row for row in venue._o if row.get("type") != 4]
        place_calls = venue.place_calls
        cancelled = []
        closed = []

        def cancel_order(order_id):
            cancelled.append(order_id)
            venue._o = [row for row in venue._o if row.get("id") != order_id]
            return {"success": True}

        def close_position(contract_id):
            closed.append(contract_id)
            venue._p = []
            return {"success": True}

        venue.cancel_order = cancel_order
        venue.close_position = close_position
        assert cold.open_lane()["lane"] == "RECOVERY"
        out = loop.manage_open_position()
        assert out["status"] == "identity_unavailable", out
        anchor = out["recovery"]["anchor"]
        assert anchor["reason"] == "child_ownership_ambiguous"
        assert anchor["flattened"]["flattened"] is True
        assert cancelled and closed == [cold.contract.id]
        assert venue._p == []
        assert venue.place_calls == place_calls
        assert venue.modifies == []

    def test_restart_reconciles_multi_fill_vwap_before_authorization(self, tmp_path):
        loop, cold, venue, mission, geometry = _cold_crash_fixture(tmp_path)
        quantity = geometry.size
        first = max(1, quantity // 3)
        second = quantity - first
        venue._trades = [
            {"id": 901, "orderId": mission.order_id, "size": first,
             "price": mission.fill_price, "contractId": cold.contract.id},
            {"id": 902, "orderId": mission.order_id, "size": second,
             "price": mission.fill_price + 1.0, "contractId": cold.contract.id},
        ]
        expected = ((mission.fill_price * first
                     + (mission.fill_price + 1.0) * second) / quantity)
        venue._p[0]["avg_price"] = expected
        data = json.loads(open(mission.path, encoding="utf-8").read())
        data["state"] = "VENUE_ACKNOWLEDGED"
        data["fill_price"] = None
        data["filled_quantity"] = None
        Path(mission.path).write_text(
            json.dumps(data), encoding="utf-8")
        loop.mission.load_existing()
        report = loop.reconcile_missions()
        assert report.get("error") is None, report
        live = loop.mission.active_mission
        assert live.fill_price == expected
        out = loop.manage_open_position()
        assert out["status"] == "establishment_recovered", out
        assert out["recovery"]["fill"]["fill_price"] == expected
