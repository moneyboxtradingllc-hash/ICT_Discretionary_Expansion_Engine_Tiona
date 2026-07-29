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
def _live_bars(n=10):
    """Bars ending ~now.

    Fixed-date fixtures would be permanently stale, and the transport now REFUSES
    a stale window — correctly, since stale bars are indistinguishable from a
    quiet market downstream. A fixture standing in for a live feed has to age
    like one.
    """
    from datetime import datetime, timedelta, timezone
    end = datetime.now(timezone.utc).replace(second=0, microsecond=0)
    out = []
    for i in range(n, 0, -1):
        t = end - timedelta(minutes=i - 1)
        out.append({"t": t.strftime("%Y-%m-%dT%H:%M:00Z"),
                    "o": 100 + i, "h": 101 + i, "l": 99 + i,
                    "c": 100.5 + i, "v": 10})
    return out


BARS = _live_bars()


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


class TestTheBarWindowIsUnambiguous:
    """The lane asks for 2000 bars over a 10-day window. MNQ prints ~1380 a day,
    so a naive translation requests ~13,800 and caps at 2000 — and nothing
    documents which 2000 come back. Warming up on ten-day-old bars would have the
    lane trading a market that no longer exists."""

    def test_the_window_is_sized_to_the_bars_wanted(self, env):
        venue = Venue()
        c = _client(venue)
        c.historical_1m("MNQ", 2000, days_back=10, max_bars=2500)
        sent = venue.sent("/api/History/retrieveBars")
        from datetime import datetime
        start = datetime.fromisoformat(sent["startTime"].replace("Z", "+00:00"))
        end = datetime.fromisoformat(sent["endTime"].replace("Z", "+00:00"))
        minutes = (end - start).total_seconds() / 60.0
        assert minutes < 10 * 24 * 60          # NOT the naive 10-day window
        assert sent["limit"] >= 2500           # cap matches what was asked for

    def test_the_partial_bar_is_still_refused(self, env):
        venue = Venue()
        _client(venue).historical_1m("MNQ", 2000, days_back=10)
        assert venue.sent("/api/History/retrieveBars")["includePartialBar"] is False

    def test_a_stale_window_is_refused_rather_than_traded(self, env, monkeypatch):
        """Stale bars are indistinguishable from a quiet market downstream."""
        import integrations.ninjatrader.deterministic.topstepx_lane_client as mod
        monkeypatch.setattr(mod.TopstepXLaneClient, "_bar_age_minutes",
                            staticmethod(lambda _s: 240.0))
        assert _client(Venue()).historical_1m("MNQ", 100) == []

    def test_fresh_bars_pass(self, env, monkeypatch):
        import integrations.ninjatrader.deterministic.topstepx_lane_client as mod
        monkeypatch.setattr(mod.TopstepXLaneClient, "_bar_age_minutes",
                            staticmethod(lambda _s: 1.0))
        assert len(_client(Venue()).historical_1m("MNQ", 100)) == len(BARS)

    def test_an_unreadable_timestamp_does_not_halt_trading(self, env):
        """Unparseable must read as a parsing problem, not as staleness."""
        from integrations.ninjatrader.deterministic.topstepx_lane_client import (
            TopstepXLaneClient)
        assert TopstepXLaneClient._bar_age_minutes("not-a-date") is None
        assert TopstepXLaneClient._bar_age_minutes(None) is None


class TestTheVenueOwnsTheIdentity:
    """The guard demanded NT_ACCOUNT unconditionally, which broke TopstepX at
    import — and invited a far worse workaround than the crash.

    On TopstepX, acct["account"] is the TopstepX account NAME. loop.py computes
    account_known = (acct["account"] == ACCOUNT). With a placeholder in
    NT_ACCOUNT that is False on every scan, and the 20-check fail-closed author
    refuses every trade in silence: a lane that looks like it simply never finds
    a setup. The crash was loud; the workaround would not have been.
    """

    def _reload(self, monkeypatch, venue, **env):
        # load_dotenv() runs again on reload and would re-populate NT_ACCOUNT
        # from the developer's own .env, so "unset" could never be simulated on
        # a configured machine. Neutralised here so the test sees exactly the
        # environment it declares.
        # Patched on `dotenv` itself, not on the lane module: reload re-executes
        # `from dotenv import load_dotenv`, which would rebind the real function
        # and quietly undo a module-level patch.
        import dotenv
        monkeypatch.setattr(dotenv, "load_dotenv", lambda *a, **k: False)
        import integrations.ninjatrader.deterministic as d
        for k in ("NT_ACCOUNT", "NT_INSTRUMENT", "TOPSTEPX_ACCOUNT_NAME",
                  "TOPSTEPX_CONTRACT"):
            monkeypatch.delenv(k, raising=False)
        monkeypatch.setenv("DETERMINISTIC_VENUE", venue)
        for k, v in env.items():
            monkeypatch.setenv(k, v)
        import importlib
        return importlib.reload(d)

    def test_topstepx_needs_no_ninjatrader_config_at_all(self, monkeypatch):
        d = self._reload(monkeypatch, "topstepx",
                         TOPSTEPX_ACCOUNT_NAME="PRAC-V2-562817-71602583",
                         TOPSTEPX_CONTRACT="MNQ")
        assert d.ACCOUNT == "PRAC-V2-562817-71602583"
        assert d.INSTRUMENT == "MNQ"

    def test_account_known_is_true_on_the_topstepx_path(self, env, monkeypatch):
        """The whole point: the comparison must be like-for-like.

        Without this the lane connects, reads bars, decides — and refuses
        everything, with no error anywhere to explain why.
        """
        d = self._reload(monkeypatch, "topstepx",
                         TOPSTEPX_ACCOUNT_NAME="PRAC-50K",
                         TOPSTEPX_CONTRACT="MNQ")
        monkeypatch.setenv("TOPSTEPX_USERNAME", "tiona")
        monkeypatch.setenv("TOPSTEPX_API_KEY", "k")
        reported = _client(Venue()).account_state()["account"]
        assert reported == d.ACCOUNT          # exactly what loop.py compares

    def test_missing_topstepx_config_names_topstepx_variables(self, monkeypatch):
        with pytest.raises(RuntimeError) as exc:
            self._reload(monkeypatch, "topstepx")
        msg = str(exc.value)
        assert "TOPSTEPX_ACCOUNT_NAME" in msg
        assert "Do NOT set NT_ACCOUNT" in msg      # kills the placeholder idea

    def test_ninjatrader_still_demands_its_own_config(self, monkeypatch):
        with pytest.raises(RuntimeError) as exc:
            self._reload(monkeypatch, "ninjatrader")
        assert "NT_ACCOUNT" in str(exc.value)

    def test_ninjatrader_identity_is_unchanged(self, monkeypatch):
        d = self._reload(monkeypatch, "ninjatrader",
                         NT_ACCOUNT="DEMO8458533", NT_INSTRUMENT="MNQ SEP26")
        assert d.ACCOUNT == "DEMO8458533"
        assert d.INSTRUMENT == "MNQ SEP26"
