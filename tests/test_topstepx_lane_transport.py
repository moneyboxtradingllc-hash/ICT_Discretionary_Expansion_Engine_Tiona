"""The deterministic lane, running on TopstepX with no NinjaTrader involved.

The lane calls ten methods on its client and reads specific fields off the
results — account_known, position_known, orders_known and armed all come straight
off them and feed the fail-closed author. A transport that answered a slightly
different shape would not raise; it would quietly degrade those gates to
"unknown", which reads as a bot that never finds a setup.

So these assert the SHAPE the lane consumes, not merely that calls succeed.
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from broker.topstepx_adapter import TopstepXBrokerAdapter
from broker.topstepx_client import TopstepXClient

MNQ = {"id": "CON.F.US.MNQ.U26", "name": "MNQU26", "description": "Micro Nasdaq",
       "tickSize": 0.25, "tickValue": 0.5, "activeContract": True}
ACCT = {"id": 77, "name": "PRAC-50K", "balance": 50_000.0,
        "canTrade": True, "simulated": True}
BARS = [{"t": f"2026-07-28T13:{m:02d}:00Z", "o": 100 + m, "h": 101 + m,
         "l": 99 + m, "c": 100.5 + m, "v": 10} for m in range(30, 40)]


class Venue:
    def __init__(self, *, positions=None, orders=None):
        self.positions = positions or []
        self.orders = orders or []
        self.calls = []

    def __call__(self, url, payload, headers, timeout):
        path = url[url.index("/api/"):]
        self.calls.append((path, payload))
        if path == "/api/Auth/loginKey":
            return {"success": True, "errorCode": 0, "token": "jwt"}
        if path == "/api/Account/search":
            return {"success": True, "accounts": [dict(ACCT)]}
        if path == "/api/Contract/search":
            return {"success": True, "contracts": [dict(MNQ)]}
        if path == "/api/History/retrieveBars":
            return {"success": True, "bars": BARS}
        if path == "/api/Position/searchOpen":
            return {"success": True, "positions": self.positions}
        if path == "/api/Order/searchOpen":
            return {"success": True, "orders": self.orders}
        if path == "/api/Order/place":
            return {"success": True, "orderId": 5150}
        if path == "/api/Position/closeContract":
            return {"success": True}
        raise AssertionError(f"unscripted {path}")

    def sent(self, path):
        return next(p for s, p in self.calls if s == path)

    def called(self, path):
        return any(s == path for s, _ in self.calls)


@pytest.fixture
def env(monkeypatch):
    monkeypatch.setenv("TOPSTEPX_USERNAME", "tiona")
    monkeypatch.setenv("TOPSTEPX_API_KEY", "k")
    monkeypatch.setenv("TOPSTEPX_ACCOUNT_NAME", "PRAC-50K")
    monkeypatch.setenv("TOPSTEPX_CONTRACT", "MNQ")
    monkeypatch.delenv("TOPSTEPX_ARM_ORDERS", raising=False)
    monkeypatch.delenv("TOPSTEP_ACCOUNT_SIZE", raising=False)


def _client(venue):
    from integrations.ninjatrader.deterministic.topstepx_lane_client import (
        TopstepXLaneClient)
    adapter = TopstepXBrokerAdapter(
        client=TopstepXClient("tiona", "k", transport=venue))
    c = TopstepXLaneClient(adapter)
    assert c.connect() is True
    return c


class TestNoNinjaTraderAnywhere:
    def test_the_transport_never_imports_the_bridge(self):
        """Checked on the IMPORT GRAPH, not on the text.

        A substring search would flag the docstring, which mentions the bridge
        deliberately — the module exists to replace it and says so. What must be
        true is that no NinjaTrader code is reachable from here.
        """
        import ast
        import inspect

        from integrations.ninjatrader.deterministic import topstepx_lane_client
        tree = ast.parse(inspect.getsource(topstepx_lane_client))
        imported = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported += [a.name for a in node.names]
            elif isinstance(node, ast.ImportFrom):
                imported.append(node.module or "")
        assert not [m for m in imported if "bridge" in m or "ninjatrader.execution" in m], \
            f"transport reaches NinjaTrader code: {imported}"

    def test_the_lane_selects_topstepx_by_env(self, env, monkeypatch):
        monkeypatch.setenv("DETERMINISTIC_VENUE", "topstepx")
        import importlib

        from integrations.ninjatrader.deterministic import loop
        importlib.reload(loop)
        assert loop.VENUE == "topstepx"
        assert type(loop._venue_client()).__name__ == "TopstepXLaneClient"
        monkeypatch.setenv("DETERMINISTIC_VENUE", "ninjatrader")
        importlib.reload(loop)

    def test_an_unknown_venue_is_refused_not_defaulted(self, env, monkeypatch):
        monkeypatch.setenv("DETERMINISTIC_VENUE", "tradovate")
        import importlib

        from integrations.ninjatrader.deterministic import loop
        importlib.reload(loop)
        with pytest.raises(RuntimeError, match="not a venue"):
            loop._venue_client()
        monkeypatch.setenv("DETERMINISTIC_VENUE", "ninjatrader")
        importlib.reload(loop)


class TestTheShapeTheLaneReads:
    def test_account_state_carries_what_the_author_gates_on(self, env):
        c = _client(Venue())
        a = c.account_state()
        assert a["known"] is True
        assert a["account"] == "PRAC-50K"          # compared against ACCOUNT
        assert a["cash_value"] == 50_000.0          # drives compounding + sizing

    def test_realized_pnl_absence_is_declared_not_faked(self, env):
        """Without a prior close, 'flat on the day' would be a fabrication."""
        c = _client(Venue())
        assert c.account_state()["realized_pnl_known"] is False

    def test_a_flat_position_is_known_and_zero(self, env):
        p = _client(Venue()).position("MNQ")
        assert p["known"] is True and p["qty"] == 0

    def test_a_short_position_reports_negative_quantity(self, env):
        """The lane does abs(qty) and compares signs; unsigned would break it."""
        venue = Venue(positions=[{"id": 1, "contractId": MNQ["id"], "type": 2,
                                  "size": 6, "averagePrice": 20_000.0}])
        p = _client(venue).position("MNQ")
        assert p["qty"] == -6 and p["known"] is True

    def test_a_long_position_reports_positive_quantity(self, env):
        venue = Venue(positions=[{"id": 1, "contractId": MNQ["id"], "type": 1,
                                  "size": 4, "averagePrice": 20_000.0}])
        assert _client(venue).position("MNQ")["qty"] == 4

    def test_working_order_count_is_how_protection_is_proven(self, env):
        """The lane requires exactly 2 — a bracket's stop and target."""
        venue = Venue(orders=[
            {"id": 1, "contractId": MNQ["id"], "status": 1, "type": 4, "side": 1, "size": 6},
            {"id": 2, "contractId": MNQ["id"], "status": 1, "type": 1, "side": 1, "size": 6},
        ])
        s = _client(venue).order_summary()
        assert s["known"] is True and s["working_order_count"] == 2

    def test_bars_arrive_in_the_providers_shape(self, env):
        rows = _client(Venue()).historical_1m("MNQ", 5)
        assert len(rows) == 5
        assert set(rows[0]) >= {"timestamp", "open", "high", "low", "close",
                                "volume", "instrument"}

    def test_quote_is_the_last_closed_bar_and_says_so(self, env):
        q = _client(Venue()).quote("MNQ")
        assert q["known"] is True
        assert q["last"] == BARS[-1]["c"]
        assert q["derived_from"] == "last_closed_bar"


class TestOrdersAreDisarmedByDefault:
    def test_nothing_can_be_sent_without_an_explicit_arm(self, env):
        venue = Venue()
        c = _client(venue)
        ack = c.deterministic_order({"direction": "long", "quantity": 3,
                                     "structural_stop_price": 120.0,
                                     "target_points": 35.0})
        assert ack["accepted"] is False
        assert "disarmed" in ack["reason"]
        assert not venue.called("/api/Order/place")

    def test_an_armed_order_converts_the_stop_price_to_a_distance(self, env, monkeypatch):
        monkeypatch.setenv("TOPSTEPX_ARM_ORDERS", "true")
        venue = Venue()
        c = _client(venue)
        ref = BARS[-1]["c"]                       # 139.5
        ack = c.deterministic_order({"direction": "long", "quantity": 3,
                                     "structural_stop_price": ref - 20.0,
                                     "target_points": 35.0})
        assert ack["accepted"] is True and ack["order_id"] == 5150
        sent = venue.sent("/api/Order/place")
        assert sent["size"] == 3
        assert sent["stopLossBracket"]["ticks"] == 80      # 20 pts / 0.25
        assert sent["takeProfitBracket"]["ticks"] == 140   # 35 pts / 0.25

    def test_a_stop_equal_to_the_reference_is_refused(self, env, monkeypatch):
        monkeypatch.setenv("TOPSTEPX_ARM_ORDERS", "true")
        venue = Venue()
        ack = _client(venue).deterministic_order({
            "direction": "long", "quantity": 1,
            "structural_stop_price": BARS[-1]["c"], "target_points": 35.0})
        assert ack["accepted"] is False
        assert not venue.called("/api/Order/place")

    def test_environment_proof_reports_the_arm_state(self, env, monkeypatch):
        assert _client(Venue()).environment_proof()["arm_orders"] is False
        monkeypatch.setenv("TOPSTEPX_ARM_ORDERS", "true")
        assert _client(Venue()).environment_proof()["arm_orders"] is True

    def test_a_separate_oco_is_never_submitted(self, env):
        """Brackets attach to the entry; a second leg would double the exit."""
        r = _client(Venue()).submit_oco({}, {})
        assert r["accepted"] is False


class TestDisconnectedIsSafe:
    def test_every_read_reports_unknown_before_connect(self, env):
        from integrations.ninjatrader.deterministic.topstepx_lane_client import (
            TopstepXLaneClient)
        c = TopstepXLaneClient(TopstepXBrokerAdapter(
            client=TopstepXClient("tiona", "k", transport=Venue())))
        assert c.account_state()["known"] is False
        assert c.position("MNQ")["known"] is False
        assert c.order_summary()["known"] is False
        assert c.historical_1m("MNQ", 10) == []

    def test_orders_are_refused_before_connect(self, env, monkeypatch):
        monkeypatch.setenv("TOPSTEPX_ARM_ORDERS", "true")
        from integrations.ninjatrader.deterministic.topstepx_lane_client import (
            TopstepXLaneClient)
        venue = Venue()
        c = TopstepXLaneClient(TopstepXBrokerAdapter(
            client=TopstepXClient("tiona", "k", transport=venue)))
        ack = c.deterministic_order({"direction": "long", "quantity": 1,
                                     "structural_stop_price": 100.0,
                                     "target_points": 35.0})
        assert ack["accepted"] is False
        assert not venue.called("/api/Order/place")
