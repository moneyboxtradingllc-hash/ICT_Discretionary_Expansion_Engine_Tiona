"""TopstepX adapter — the contract, exercised against a scripted venue.

No network and no paid API subscription: `transport` is injected, so every path
including auth failure and token expiry runs offline.

What these pin down are the things that would cost real money on a prop account:
a forming bar reaching the engine, an order leaving without a stop, a stop
rounded wider than the risk model approved, the wrong account being addressed,
and a real-money account being traded because nobody checked.
"""
import os
import sys
from datetime import datetime, timedelta, timezone

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from broker.base import NotConnectedError
from broker.topstepx_adapter import (
    TopstepXBrokerAdapter, TopstepXConfigError, load_topstepx_config,
)
from broker.topstepx_client import (
    ORDER_SIDE, ORDER_TYPE, TopstepXAuthError, TopstepXClient, TopstepXContract,
    TopstepXError,
)

MNQ = {"id": "CON.F.US.MNQ.U26", "name": "MNQU26", "description": "Micro E-mini Nasdaq",
       "tickSize": 0.25, "tickValue": 0.5, "activeContract": True}
ACCT = {"id": 4242, "name": "PRAC-150K", "balance": 150_000.0,
        "canTrade": True, "simulated": True}


class FakeVenue:
    """A scripted TopstepX. Records every call so the payloads can be asserted."""

    def __init__(self, *, accounts=None, contracts=None, bars=None,
                 login_ok=True, login_error=0, fail_first_with=None):
        self.accounts = accounts if accounts is not None else [dict(ACCT)]
        self.contracts = contracts if contracts is not None else [dict(MNQ)]
        self._bars = bars or []
        self.login_ok = login_ok
        self.login_error = login_error
        self.calls: list[tuple[str, dict]] = []
        self.logins = 0
        self._fail_first_with = fail_first_with

    def __call__(self, url, payload, headers, timeout):
        path = url.split("api.topstepx.com")[-1] if "api.topstepx.com" in url else url
        path = "/" + path.split("/", 3)[-1] if path.startswith("http") else path
        path = url[url.index("/api/"):]
        self.calls.append((path, payload))

        if path == "/api/Auth/loginKey":
            self.logins += 1
            if not self.login_ok:
                return {"success": False, "errorCode": self.login_error,
                        "errorMessage": "nope", "token": None}
            return {"success": True, "errorCode": 0, "token": f"jwt-{self.logins}"}

        if self._fail_first_with:
            err, self._fail_first_with = self._fail_first_with, None
            raise TopstepXError(err)

        if path == "/api/Account/search":
            return {"success": True, "errorCode": 0, "accounts": self.accounts}
        if path == "/api/Contract/search":
            return {"success": True, "errorCode": 0, "contracts": self.contracts}
        if path == "/api/History/retrieveBars":
            return {"success": True, "errorCode": 0, "bars": self._bars}
        if path == "/api/Position/searchOpen":
            return {"success": True, "errorCode": 0, "positions": []}
        if path == "/api/Order/place":
            return {"success": True, "errorCode": 0, "orderId": 9056}
        if path in ("/api/Order/cancel", "/api/Position/closeContract"):
            return {"success": True, "errorCode": 0}
        raise AssertionError(f"unscripted path {path}")

    def payload_for(self, path):
        return next(p for sent, p in self.calls if sent == path)


@pytest.fixture
def env(monkeypatch):
    monkeypatch.setenv("TOPSTEPX_USERNAME", "tiona")
    monkeypatch.setenv("TOPSTEPX_API_KEY", "key-abc")
    monkeypatch.setenv("TOPSTEPX_ACCOUNT_NAME", "PRAC-150K")
    monkeypatch.setenv("TOPSTEPX_CONTRACT", "MNQ")
    monkeypatch.delenv("TOPSTEPX_ALLOW_LIVE", raising=False)


def _adapter(venue, **over):
    client = TopstepXClient("tiona", "key-abc", transport=venue, **over)
    return TopstepXBrokerAdapter(client=client)


# ── configuration ─────────────────────────────────────────────────────────────
class TestConfiguration:
    def test_missing_settings_name_themselves(self, monkeypatch):
        for k in ("TOPSTEPX_USERNAME", "TOPSTEPX_API_KEY",
                  "TOPSTEPX_ACCOUNT_NAME", "TOPSTEPX_CONTRACT"):
            monkeypatch.delenv(k, raising=False)
        with pytest.raises(TopstepXConfigError) as exc:
            load_topstepx_config()
        for k in ("TOPSTEPX_USERNAME", "TOPSTEPX_API_KEY", "TOPSTEPX_ACCOUNT_NAME"):
            assert k in str(exc.value)

    def test_no_credentials_is_refused_not_defaulted(self):
        with pytest.raises(TopstepXAuthError):
            TopstepXClient("", "", transport=FakeVenue())


# ── the money gate ────────────────────────────────────────────────────────────
class TestRealMoneyIsRefusedByDefault:
    def test_a_non_simulated_account_will_not_connect(self, env):
        live = dict(ACCT, simulated=False, name="PRAC-150K")
        adapter = _adapter(FakeVenue(accounts=[live]))
        with pytest.raises(NotConnectedError) as exc:
            adapter.connect()
        assert "NOT simulated" in str(exc.value)
        assert "TOPSTEPX_ALLOW_LIVE" in str(exc.value)

    def test_real_money_requires_a_deliberate_opt_in(self, env, monkeypatch):
        monkeypatch.setenv("TOPSTEPX_ALLOW_LIVE", "true")
        live = dict(ACCT, simulated=False)
        adapter = _adapter(FakeVenue(accounts=[live]))
        assert adapter.connect().simulated is False
        assert adapter.capability().paper_only is False

    def test_an_account_topstep_has_disabled_is_refused(self, env):
        dead = dict(ACCT, canTrade=False)
        with pytest.raises(NotConnectedError) as exc:
            _adapter(FakeVenue(accounts=[dead])).connect()
        assert "canTrade=false" in str(exc.value)


# ── addressing the right account ──────────────────────────────────────────────
class TestAccountResolution:
    def test_the_account_is_matched_by_exact_name(self, env):
        venue = FakeVenue(accounts=[dict(ACCT, id=1, name="EVAL-50K"), dict(ACCT)])
        adapter = _adapter(venue)
        assert adapter.connect().id == 4242

    def test_an_unknown_name_lists_what_is_available(self, env):
        venue = FakeVenue(accounts=[dict(ACCT, name="SOMETHING-ELSE")])
        with pytest.raises(TopstepXError) as exc:
            _adapter(venue).connect()
        assert "SOMETHING-ELSE" in str(exc.value)

    def test_duplicate_names_are_refused_rather_than_guessed(self, env):
        venue = FakeVenue(accounts=[dict(ACCT), dict(ACCT, id=99)])
        with pytest.raises(TopstepXError) as exc:
            _adapter(venue).connect()
        assert "matched 2 accounts" in str(exc.value)

    def test_an_ambiguous_contract_is_refused(self, env):
        venue = FakeVenue(contracts=[dict(MNQ), dict(MNQ, id="CON.F.US.MNQ.Z26")])
        with pytest.raises(TopstepXError) as exc:
            _adapter(venue).connect()
        assert "TOPSTEPX_CONTRACT" in str(exc.value)


# ── market data ───────────────────────────────────────────────────────────────
class TestBars:
    def test_the_forming_bar_is_never_requested(self, env):
        """The defect class this project has paid for most often."""
        venue = FakeVenue(bars=[{"t": "2026-07-28T13:30:00Z", "o": 1, "h": 2,
                                 "l": 0.5, "c": 1.5, "v": 10}])
        adapter = _adapter(venue)
        adapter.connect()
        adapter.bars_1m()
        assert venue.payload_for("/api/History/retrieveBars")["includePartialBar"] is False

    def test_bars_come_back_oldest_first_in_the_core_shape(self, env):
        venue = FakeVenue(bars=[
            {"t": "2026-07-28T13:32:00Z", "o": 3, "h": 4, "l": 2, "c": 3.5, "v": 7},
            {"t": "2026-07-28T13:30:00Z", "o": 1, "h": 2, "l": 0.5, "c": 1.5, "v": 10},
        ])
        adapter = _adapter(venue)
        adapter.connect()
        rows = adapter.bars_1m()
        assert [r["timestamp"] for r in rows] == ["2026-07-28T13:30:00Z",
                                                  "2026-07-28T13:32:00Z"]
        assert set(rows[0]) == {"timestamp", "open", "high", "low", "close", "volume"}


# ── orders ────────────────────────────────────────────────────────────────────
class TestOrders:
    def test_entry_carries_its_stop_and_target_in_one_request(self, env):
        """A fill that lands while a follow-up stop is in flight is unprotected."""
        venue = FakeVenue()
        adapter = _adapter(venue)
        adapter.connect()
        out = adapter.submit_order({"direction": "long", "quantity": 3,
                                    "stop_points": 20.0, "target_points": 35.0})
        sent = venue.payload_for("/api/Order/place")
        assert sent["type"] == ORDER_TYPE["market"]
        assert sent["side"] == ORDER_SIDE["buy"]
        assert sent["size"] == 3
        assert sent["stopLossBracket"] == {"ticks": 80, "type": ORDER_TYPE["stop"]}
        assert sent["takeProfitBracket"] == {"ticks": 140, "type": ORDER_TYPE["limit"]}
        assert out["order_id"] == 9056

    def test_a_short_is_the_sell_side(self, env):
        venue = FakeVenue()
        adapter = _adapter(venue)
        adapter.connect()
        adapter.submit_order({"direction": "short", "quantity": 1,
                              "stop_points": 10.0, "target_points": 20.0})
        assert venue.payload_for("/api/Order/place")["side"] == ORDER_SIDE["sell"]

    @pytest.mark.parametrize("bad", [
        {"direction": "long", "quantity": 1, "stop_points": 0, "target_points": 35},
        {"direction": "long", "quantity": 0, "stop_points": 20, "target_points": 35},
    ])
    def test_an_order_without_a_stop_or_size_is_never_sent(self, env, bad):
        venue = FakeVenue()
        adapter = _adapter(venue)
        adapter.connect()
        with pytest.raises(TopstepXError):
            adapter.submit_order(bad)
        assert not any(p == "/api/Order/place" for p, _ in venue.calls)

    def test_tick_conversion_never_rounds_a_stop_wider(self):
        c = TopstepXContract(id="x", name="MNQ", description="", tick_size=0.25,
                             tick_value=0.5, active=True)
        assert c.points_to_ticks(20.0) == 80
        assert c.points_to_ticks(20.2) == 80      # 80.8 -> 80, never 81
        assert c.points_to_ticks(0.1) == 1        # never zero

    def test_orders_are_refused_before_connect(self, env):
        adapter = _adapter(FakeVenue())
        with pytest.raises(NotConnectedError):
            adapter.submit_order({"direction": "long", "quantity": 1,
                                  "stop_points": 20, "target_points": 35})


# ── session handling ──────────────────────────────────────────────────────────
class TestSession:
    def test_one_login_is_reused_across_calls(self, env):
        venue = FakeVenue()
        adapter = _adapter(venue)
        adapter.connect()
        adapter.get_account()
        adapter.get_position()
        assert venue.logins == 1

    def test_an_expired_token_is_renewed(self, env):
        venue = FakeVenue()
        now = [datetime(2026, 7, 28, 12, 0, tzinfo=timezone.utc)]
        client = TopstepXClient("tiona", "key-abc", transport=venue,
                                clock=lambda: now[0])
        adapter = TopstepXBrokerAdapter(client=client)
        adapter.connect()
        assert venue.logins == 1
        now[0] += timedelta(hours=21)
        adapter.get_account()
        assert venue.logins == 2

    def test_a_401_triggers_exactly_one_reauth(self, env):
        venue = FakeVenue(fail_first_with="HTTP 401 from /api/Account/search: expired")
        adapter = _adapter(venue)
        adapter.connect()
        assert venue.logins == 2

    def test_a_missing_api_subscription_says_so(self, env):
        venue = FakeVenue(login_ok=False, login_error=9)
        with pytest.raises(TopstepXAuthError) as exc:
            _adapter(venue).connect()
        assert "paid add-on" in str(exc.value)


# ── what the adapter admits it cannot do ──────────────────────────────────────
class TestHonestCapability:
    def test_it_declares_the_trailing_drawdown_gap(self, env):
        adapter = _adapter(FakeVenue())
        adapter.connect()
        assert "trailing" in adapter.capability().notes.lower()
