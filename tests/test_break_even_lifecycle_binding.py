"""Real production scan/submit/fill/reanchor/arm, with only a synthetic venue.

No test supplies an armed context to the fresh lifecycle. No network or model
provider is allowed; the scan fixture supplies an already-produced narrative.
"""
import json
import os
import socket
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import pytest

from broker import break_even_actuator as ACT
from broker import break_even_journal as J
from broker.topstepx_production_session import ProductionSession
from broker.topstepx_session_authorization import ProductionSessionMission, SessionAuthorization
from test_production_scan_loop import build, Session, Cycle, parsed, brain_input, CID, NOW
from test_break_even_mission_identity_audit import owner_for, open_filled, loop_for, SESSION


@pytest.fixture(autouse=True)
def isolated(monkeypatch):
    def forbidden(*a, **kw):
        raise AssertionError("no network or model during BE regression")
    monkeypatch.setattr(socket.socket, "connect", forbidden)
    monkeypatch.setattr(socket.socket, "connect_ex", forbidden)
    import ai_brain.narrative_brain as NB
    monkeypatch.setattr(NB, "run_narrative_brain", forbidden)


class FilledVenue(Session):
    def __init__(self, *, short=False):
        super().__init__(place=self.fill)
        self.short = short
        self.modifies = []
        self.before_write = None

    def fill(self, payload):
        assert payload["side"] == int(self.short)
        qty, px = payload["size"], 29880.0
        self._p = [dict(id=101, contract_id=CID, side="short" if self.short else "long",
                        size=qty, avg_price=px)]
        self._trades = [dict(id=201, orderId=100, size=qty, price=px, contractId=CID)]
        self._o = [dict(id=102, contract_id=CID, status=1, type=4, size=qty,
                        side=0 if self.short else 1, parent_order_id=100,
                        stop_price=px + (7 if self.short else -7), limit_price=None),
                   dict(id=103, contract_id=CID, status=1, type=1, size=qty,
                        side=0 if self.short else 1, parent_order_id=100,
                        stop_price=None, limit_price=px + (-45 if self.short else 45))]
        return {"success": True, "order_id": 100}

    def modify_order(self, order_id, **kw):
        if self.before_write:
            self.before_write()
        self.modifies.append((order_id, kw))
        for order in self._o:
            if order["id"] == order_id:
                for k, value in kw.items():
                    if value is not None:
                        order[k] = value
        return {"success": True}


def fresh(tmp_path, short=False):
    venue = FilledVenue(short=short)
    cycle = Cycle()
    if short:
        cycle = Cycle(output=parsed(narrative_direction="bearish", invalidation_level=29885.0,
                                    active_draw="sell side liquidity below"),
                      bi=brain_input(high=29885.0))
    loop, ps, _, owner = build(tmp_path, armed=True, session=venue, cycle=cycle)
    # Same configuration performed by the checked-in production launcher.
    ps.session_id = owner.authorization.session_id
    ps.authorization_fingerprint = owner.authorization.fingerprint()
    owner.authorization.save()
    venue.before_write = lambda: assert_unarmed(ps)
    assert ps.runner is None
    result = loop.scan_once()
    venue.before_write = None
    return loop, ps, venue, owner, result


def assert_unarmed(ps):
    assert ps.runner.execution_context is None


@pytest.mark.parametrize("short", [False, True])
def test_full_production_fill_arms_then_manages_and_cold_restores(tmp_path, short):
    loop, ps, venue, owner, result = fresh(tmp_path, short)
    assert result["outcome"] == "SUBMITTED", result
    assert result["break_even_management"]["status"] == "armed", result
    ctx = ps.runner.execution_context
    mission = owner.active_mission
    assert ctx.mission_id == mission.mission_id
    assert ctx.session_id == owner.authorization.session_id
    assert ctx.position_id == 101 and ctx.entry_order_id == 100
    assert ctx.protection_baseline_armed is True
    original = ctx.original_thesis_invalidation
    risk = abs(ctx.entry_fill_price - original)
    initial_writes = len(venue.modifies)
    assert initial_writes == 2  # both structural legs, with no armed context
    px = ctx.entry_fill_price + (-risk if short else risk)
    venue.market_hub.emit("GatewayQuote", [CID, {"bestBid": px, "bestAsk": px}])
    out = loop.manage_open_position()
    assert out["status"] == ACT.APPLIED, out
    assert out["baseline"]["initial_risk_points"] == risk
    assert venue.modifies[-1][0] == 102
    assert set(venue.modifies[-1][1]) == {"stop_price"}
    assert len(venue.modifies) == initial_writes + 1
    target = venue._o[1].copy()
    cold = ProductionSession(session=venue, account_fingerprint=ps.account_fingerprint,
        contract=ps.contract, mission_id=ps.mission_id, store_dir=ps.store_dir,
        session_id=ps.session_id, quote_provider=ps.quote_provider, clock=lambda: NOW)
    assert cold.open_lane()["lane"] == "RECOVERY"
    assert cold.runner is None  # deserialization alone is not authority
    owner = ProductionSessionMission(SessionAuthorization.load(owner.authorization.path), ps.store_dir)
    owner.load_existing()
    owner.filled_trade_count, owner.completed_round_trip_count = 999, 0
    loop.ps, loop.mission = cold, owner
    for _ in range(3):
        after = loop.manage_open_position()
        assert after["status"] in (ACT.HELD, "decision_declines"), after
    assert cold.runner.execution_context.original_thesis_invalidation == original
    assert after["baseline"]["initial_risk_points"] == risk
    assert venue._o[1] == target
    assert len(venue.modifies) == initial_writes + 1


@pytest.mark.parametrize("artifact,field,value", [
    ("mission", "mission_id", "foreign"), ("mission", "order_id", 9090),
    ("mission", "session_id", "foreign"), ("mission", "token_id", "foreign"),
    ("mission", "account_fingerprint", "foreign"), ("mission", "contract_id", "foreign"),
    ("submission", "session_id", "foreign"), ("submission", "token_id", "foreign"),
    ("submission", "account_fingerprint", "foreign"), ("submission", "contract_id", "foreign"),
    ("submission", "authorization_fingerprint", "foreign"), ("submission", "venue_order_id", 9090),
    ("submission", "mission_id", "foreign"), ("submission", "token_id", None),
])
def test_corrupt_durable_binding_stops_before_proposal_or_emergency(tmp_path, artifact, field, value):
    owner = owner_for(tmp_path)
    mission = open_filled(owner, fill=30000, stop=29990)
    loop, venue = loop_for(owner, mission, stop=29990)
    venue._o = []  # must not flatten using a foreign baseline
    if artifact == "mission":
        path = tmp_path / os.path.basename(mission.path)
        data = json.loads(path.read_text())
        data[field] = value
        path.write_text(json.dumps(data))
    else:
        path = tmp_path / f"submissions_{SESSION}.jsonl"
        rows = [json.loads(line) for line in path.read_text().splitlines()]
        for row in rows:
            row[field] = value
        path.write_text("\n".join(json.dumps(row) for row in rows))
    result = loop.manage_open_position()
    assert result["status"] == "identity_unavailable", result
    assert "decision" not in result
    assert venue.modifies == [] and J.load(owner.store_dir, SESSION) == []
