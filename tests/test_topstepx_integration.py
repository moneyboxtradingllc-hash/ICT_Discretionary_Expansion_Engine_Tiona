"""TOPSTEPX-INTEGRATION — locks for the native adapter, pinning, realtime and
the structurally read-only preflight.

Every test runs against injected transports. Nothing here reaches the network,
needs a paid API subscription, or can place an order.
"""
from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timedelta, timezone

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src"))

from broker.topstepx_client import (                     # noqa: E402
    TopstepXAuthError, TopstepXClient, TopstepXError, TopstepXPinError,
    TopstepXRateLimited,
)
from broker.topstepx_readonly import (                   # noqa: E402
    KNOWN_WRITE_PATHS, ReadOnlyViolation, TopstepXReadOnlySession,
)
from broker.topstepx_realtime import (                   # noqa: E402
    RealtimeError, SignalRHub, Subscription, market_hub_subscriptions,
    user_hub_subscriptions,
)
from broker.topstepx_redaction import (                  # noqa: E402
    MASK, account_fingerprint, assert_clean, redact, redact_mapping,
    redacted_account_label,
)

TOKEN = "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxIn0.c2lnbmF0dXJlX2hlcmU"
LOGIN_OK = {"token": TOKEN, "success": True, "errorCode": 0, "errorMessage": None}

ACCT_MAIN = {"id": 7788, "name": "50KCOMBINE98765", "balance": 50000.0,
             "canTrade": True, "isVisible": True, "simulated": True}
ACCT_OTHER = {"id": 9911, "name": "PRACTICEJUL2612345", "balance": 150000.0,
              "canTrade": True, "isVisible": True, "simulated": True}

MNQ = {"id": "CON.F.US.MNQ.U25", "name": "MNQU5",
       "description": "Micro E-mini Nasdaq-100: September 2025",
       "tickSize": 0.25, "tickValue": 0.5, "activeContract": True,
       "symbolId": "F.US.MNQ"}


def make_transport(routes, log=None):
    """Route by endpoint path. Unrouted paths raise, so no test passes by accident."""
    def transport(url, payload, headers, timeout):
        path = url.split("topstepx.com", 1)[-1]
        if log is not None:
            log.append(path)
        if path not in routes:
            raise TopstepXError(f"unrouted path in test: {path}")
        r = routes[path]
        return r(payload) if callable(r) else r
    return transport


def base_routes(accounts=(ACCT_MAIN,), contracts=(MNQ,), positions=(), orders=()):
    return {
        "/api/Auth/loginKey": LOGIN_OK,
        "/api/Account/search": {"accounts": list(accounts), "success": True, "errorCode": 0},
        "/api/Contract/search": {"contracts": list(contracts), "success": True, "errorCode": 0},
        "/api/Contract/available": {"contracts": list(contracts), "success": True, "errorCode": 0},
        "/api/Position/searchOpen": {"positions": list(positions), "success": True, "errorCode": 0},
        "/api/Order/searchOpen": {"orders": list(orders), "success": True, "errorCode": 0},
        # `/api/Order/v2/query` is the COMPLETE discovery surface. `searchOpen`
        # omits Suspended bracket children by official Gateway contract, so a
        # route table without this entry models a venue that cannot be asked
        # the question production now asks.
        "/api/Order/v2/query": {"orders": list(orders), "success": True, "errorCode": 0},
    }


def client(routes=None, **kw):
    return TopstepXClient("user", "key", transport=make_transport(routes or base_routes()),
                          sleep=lambda s: None, **kw)


# ══════════════════════════════════════════════════════════════════════════════
class TestAuthentication:

    def test_a_missing_username_is_refused_not_defaulted(self):
        with pytest.raises(TopstepXAuthError):
            TopstepXClient("", "key")

    def test_a_missing_api_key_is_refused(self):
        with pytest.raises(TopstepXAuthError):
            TopstepXClient("user", "")

    def test_an_http_failure_fails_closed(self):
        def boom(url, payload, headers, timeout):
            raise TopstepXError("HTTP 503 from /api/Auth/loginKey: gateway down")
        c = TopstepXClient("user", "key", transport=boom, sleep=lambda s: None)
        with pytest.raises(TopstepXError):
            c.accounts()

    def test_success_false_fails_closed(self):
        routes = dict(base_routes(), **{"/api/Auth/loginKey": {
            "token": TOKEN, "success": False, "errorCode": 3, "errorMessage": "nope"}})
        with pytest.raises(TopstepXAuthError):
            client(routes).accounts()

    def test_an_empty_token_fails_closed(self):
        routes = dict(base_routes(), **{"/api/Auth/loginKey": {
            "token": "", "success": True, "errorCode": 0}})
        with pytest.raises(TopstepXAuthError):
            client(routes).accounts()

    def test_a_missing_api_subscription_names_itself(self):
        routes = dict(base_routes(), **{"/api/Auth/loginKey": {
            "success": False, "errorCode": 9, "errorMessage": "ApiSubscriptionNotFound"}})
        with pytest.raises(TopstepXAuthError) as exc:
            client(routes).accounts()
        assert "paid add-on" in str(exc.value)

    def test_one_login_is_reused_across_calls(self):
        log = []
        c = TopstepXClient("user", "key", transport=make_transport(base_routes(), log),
                           sleep=lambda s: None)
        c.accounts()
        c.accounts()
        assert log.count("/api/Auth/loginKey") == 1


class TestRateLimiting:

    def test_a_429_is_retried_within_the_bound_then_succeeds(self):
        calls = {"n": 0}

        def flaky(url, payload, headers, timeout):
            if url.endswith("/api/Auth/loginKey"):
                return LOGIN_OK
            calls["n"] += 1
            if calls["n"] < 3:
                raise TopstepXRateLimited("HTTP 429", retry_after=0.01)
            return {"accounts": [ACCT_MAIN], "success": True, "errorCode": 0}

        waits = []
        c = TopstepXClient("user", "key", transport=flaky, sleep=waits.append, max_retries=3)
        assert c.accounts()[0].id == 7788
        assert len(waits) == 2                      # two throttles, two waits

    def test_the_retry_limit_is_enforced_rather_than_looping(self):
        def always429(url, payload, headers, timeout):
            if url.endswith("/api/Auth/loginKey"):
                return LOGIN_OK
            raise TopstepXRateLimited("HTTP 429", retry_after=0.01)

        waits = []
        c = TopstepXClient("user", "key", transport=always429, sleep=waits.append, max_retries=2)
        with pytest.raises(TopstepXError) as exc:
            c.accounts()
        assert "gave up after 3 attempts" in str(exc.value)
        assert len(waits) == 2

    def test_backoff_doubles_when_the_venue_gives_no_retry_after(self):
        def always429(url, payload, headers, timeout):
            if url.endswith("/api/Auth/loginKey"):
                return LOGIN_OK
            raise TopstepXRateLimited("HTTP 429", retry_after=None)

        waits = []
        c = TopstepXClient("user", "key", transport=always429, sleep=waits.append,
                           max_retries=3, backoff_base=1.0)
        with pytest.raises(TopstepXError):
            c.accounts()
        assert waits == [1.0, 2.0, 4.0]

    def test_a_refusal_is_never_retried(self):
        """A 403 is the venue saying no. Repeating it changes nothing."""
        calls = {"n": 0}

        def refuse(url, payload, headers, timeout):
            if url.endswith("/api/Auth/loginKey"):
                return LOGIN_OK
            calls["n"] += 1
            raise TopstepXError("HTTP 403 forbidden")

        c = TopstepXClient("user", "key", transport=refuse, sleep=lambda s: None)
        with pytest.raises(TopstepXError):
            c.accounts()
        assert calls["n"] == 1


class TestAccountPinning:

    def test_zero_matches_fails_closed(self):
        with pytest.raises(TopstepXPinError) as exc:
            client().pin_account(account_id=12345)
        assert "Refusing to fall back" in str(exc.value)

    def test_multiple_matches_fail_closed(self):
        dupe = dict(ACCT_OTHER, name=ACCT_MAIN["name"])
        c = client(base_routes(accounts=(ACCT_MAIN, dupe)))
        with pytest.raises(TopstepXPinError) as exc:
            c.pin_account(account_name="50KCOMBINE98765")
        assert "matched 2 accounts" in str(exc.value)

    def test_the_exact_configured_match_succeeds(self):
        c = client(base_routes(accounts=(ACCT_OTHER, ACCT_MAIN)))
        assert c.pin_account(account_id=7788).id == 7788

    def test_first_account_selection_is_impossible(self):
        """Nothing configured means nothing chosen — never 'the first one'."""
        c = client(base_routes(accounts=(ACCT_OTHER, ACCT_MAIN)))
        with pytest.raises(TopstepXPinError) as exc:
            c.pin_account()
        assert "will not choose an account" in str(exc.value)

    def test_an_invisible_account_fails_closed(self):
        hidden = dict(ACCT_MAIN, isVisible=False)
        with pytest.raises(TopstepXPinError) as exc:
            client(base_routes(accounts=(hidden,))).pin_account(account_id=7788)
        assert "isVisible=false" in str(exc.value)

    def test_a_non_trade_enabled_account_fails_closed(self):
        locked = dict(ACCT_MAIN, canTrade=False)
        with pytest.raises(TopstepXPinError) as exc:
            client(base_routes(accounts=(locked,))).pin_account(account_id=7788)
        assert "canTrade=false" in str(exc.value)

    def test_a_changed_account_identity_fails_closed(self):
        c = client()
        with pytest.raises(TopstepXPinError) as exc:
            c.pin_account(account_id=7788, expected_fingerprint="acct:deadbeefcafe")
        assert "IDENTITY CHANGED" in str(exc.value)

    def test_a_stable_identity_is_accepted(self):
        fp = account_fingerprint(ACCT_MAIN["id"], ACCT_MAIN["name"])
        assert client().pin_account(account_id=7788, expected_fingerprint=fp).id == 7788

    def test_the_pin_error_never_prints_the_account_name(self):
        c = client(base_routes(accounts=(ACCT_OTHER,)))
        with pytest.raises(TopstepXPinError) as exc:
            c.pin_account(account_name="50KCOMBINE98765")
        assert "50KCOMBINE98765" not in str(exc.value)

    def test_the_pin_error_never_prints_the_configured_account_number(self):
        """REGRESSION — live preflight 2026-08-04.

        A no-match pin failure embedded the configured TOPSTEPX_ACCOUNT_ID in
        its message, and the preflight wrote that message into the evidence
        artifact. A pin failure is precisely the message an operator copies
        into a screenshot or a bug report, so the account number must not ride
        along with it.
        """
        c = client(base_routes(accounts=(ACCT_OTHER,)))
        with pytest.raises(TopstepXPinError) as exc:
            c.pin_account(account_id=5745492)
        msg = str(exc.value)
        assert "5745492" not in msg
        assert "TOPSTEPX_ACCOUNT_ID" in msg          # still actionable
        assert "Refusing to fall back" in msg

    def test_a_pin_failure_never_lists_the_other_available_accounts(self):
        c = client(base_routes(accounts=(ACCT_OTHER, dict(ACCT_MAIN, id=4321))))
        with pytest.raises(TopstepXPinError) as exc:
            c.pin_account(account_id=999999)
        msg = str(exc.value)
        assert ACCT_OTHER["name"] not in msg and str(ACCT_OTHER["id"]) not in msg
        assert "4321" not in msg

    def test_a_configured_account_id_is_redacted_from_free_text(self, monkeypatch):
        """Defence in depth: even if some path prints it, the layer masks it."""
        monkeypatch.setenv("TOPSTEPX_ACCOUNT_ID", "5745492")
        assert "5745492" not in redact("pinned account id=5745492 not found")


class TestContractDiscovery:

    def _session(self, contracts):
        return TopstepXReadOnlySession(
            "user", "key", transport=make_transport(base_routes(contracts=contracts)))

    def test_the_exact_active_mnq_contract_resolves(self):
        s = self._session((MNQ,))
        assert s.resolve_contract("MNQ").id == "CON.F.US.MNQ.U25"

    def test_an_inactive_contract_fails_closed(self):
        stale = dict(MNQ, activeContract=False)
        with pytest.raises(TopstepXError) as exc:
            self._session((stale,)).resolve_contract("MNQ")
        assert "no ACTIVE contract" in str(exc.value)

    def test_ambiguity_during_a_roll_fails_closed(self):
        dec = dict(MNQ, id="CON.F.US.MNQ.Z25", name="MNQZ5")
        with pytest.raises(TopstepXError) as exc:
            self._session((MNQ, dec)).resolve_contract("MNQ")
        assert "Ambiguous during a roll" in str(exc.value)

    def test_invalid_tick_metadata_fails_closed(self):
        bad = dict(MNQ, tickSize=0)
        with pytest.raises(TopstepXError) as exc:
            self._session((bad,)).resolve_contract("MNQ")
        assert "invalid metadata" in str(exc.value)

    def test_resolution_comes_from_the_api_not_a_constant(self):
        """Change what the venue returns; resolution must follow it."""
        rolled = dict(MNQ, id="CON.F.US.MNQ.Z25", name="MNQZ5")
        assert self._session((rolled,)).resolve_contract("MNQ").id == "CON.F.US.MNQ.Z25"


# ══════════════════════════════════════════════════════════════════════════════
class FakeSocket:
    """Scripted SignalR socket. Records what was sent; replays canned frames."""

    def __init__(self, inbound=None, fail_on_connect=False):
        self.sent, self.closed = [], False
        self._inbound = list(inbound or [])
        self.fail_on_connect = fail_on_connect

    def send(self, data):
        self.sent.append(data)

    def recv(self):
        if self._inbound:
            return self._inbound.pop(0)
        return "{}\x1e"                       # handshake ack / idle

    def close(self):
        self.closed = True

    def invoked(self):
        out = []
        for raw in self.sent:
            for chunk in raw.split("\x1e"):
                if not chunk.strip():
                    continue
                m = json.loads(chunk)
                if m.get("type") == 1:
                    out.append(m["target"])
        return out


def hub(inbound=None, url="https://rtc.topstepx.com/hubs/user", sockets=None):
    made = []

    def factory(u):
        s = (sockets.pop(0) if sockets else FakeSocket(inbound))
        s.url = u
        made.append(s)
        return s

    h = SignalRHub(url, lambda: TOKEN, connect_factory=factory, sleep=lambda s: None)
    h._made = made
    return h


class TestRealtime:

    def test_connection_and_handshake_succeed(self):
        h = hub()
        h.connect()
        assert h.health.connected and h.health.handshake_ok
        assert json.loads(h._made[0].sent[0].rstrip("\x1e")) == {"protocol": "json", "version": 1}

    def test_a_refused_handshake_fails_closed(self):
        h = hub(inbound=['{"error":"unauthorized"}\x1e'])
        with pytest.raises(RealtimeError) as exc:
            h.connect()
        assert "handshake refused" in str(exc.value)

    def test_the_four_user_subscriptions_are_registered(self):
        h = hub()
        h.connect()
        for s in user_hub_subscriptions(7788):
            h.subscribe(s)
        assert h._made[0].invoked() == ["SubscribeAccounts", "SubscribeOrders",
                                        "SubscribePositions", "SubscribeTrades"]

    def test_market_subscriptions_cover_quotes_and_trades(self):
        h = hub(url="https://rtc.topstepx.com/hubs/market")
        h.connect()
        for s in market_hub_subscriptions("CON.F.US.MNQ.U25"):
            h.subscribe(s)
        assert h._made[0].invoked() == ["SubscribeContractQuotes", "SubscribeContractTrades"]

    def test_a_duplicate_subscription_is_not_sent_twice(self):
        """Two identical subscriptions would double every fill event."""
        h = hub()
        h.connect()
        sub = Subscription("SubscribeOrders", (7788,), "GatewayUserOrder")
        h.subscribe(sub)
        h.subscribe(sub)
        assert h._made[0].invoked() == ["SubscribeOrders"]

    def test_reconnect_resubscribes_in_the_original_order(self):
        first, second = FakeSocket(), FakeSocket()
        h = hub(sockets=[first, second])
        h.connect()
        for s in user_hub_subscriptions(7788):
            h.subscribe(s)
        replayed = h.reconnect()
        assert replayed == ["SubscribeAccounts", "SubscribeOrders",
                            "SubscribePositions", "SubscribeTrades"]
        assert second.invoked() == replayed
        assert h.health.resubscribed_in_order and first.closed

    def test_stale_market_data_is_detected(self):
        h = hub()
        h.connect()
        assert h.health.is_stale(max_age=60)          # nothing seen yet
        h.health.last_event_at = datetime.now(timezone.utc) - timedelta(seconds=300)
        assert h.health.is_stale(max_age=60)
        h.health.last_event_at = datetime.now(timezone.utc)
        assert not h.health.is_stale(max_age=60)

    def test_a_malformed_event_does_not_kill_the_stream(self):
        h = hub(inbound=["{}\x1e", 'not json at all\x1e{"type":1,"target":"GatewayQuote","arguments":[]}\x1e'])
        h.connect()
        assert h.pump(max_messages=1) == 1
        assert h.health.events_seen["GatewayQuote"] == 1

    def test_a_handler_exception_is_recorded_not_raised(self):
        h = hub(inbound=["{}\x1e", '{"type":1,"target":"GatewayUserOrder","arguments":[]}\x1e'])
        h.connect()
        h.on("GatewayUserOrder", lambda args: (_ for _ in ()).throw(ValueError("bad")))
        h.pump(max_messages=1)
        assert any("handler_error" in e for e in h.health.errors)

    def test_keepalive_frames_are_not_counted_as_events(self):
        h = hub(inbound=["{}\x1e", '{"type":6}\x1e'])
        h.connect()
        assert h.pump(max_messages=1) == 0
        assert h.health.last_event_at is None

    def test_the_health_snapshot_carries_no_token(self):
        h = hub()
        h.connect()
        assert TOKEN not in json.dumps(h.describe())

    def test_the_socket_url_uses_the_websocket_scheme(self):
        """REGRESSION — live preflight 2026-08-04.

        The whole REST path passed and both hubs then failed with InvalidURI:
        the documented hub address is https://, and a raw WebSocket client
        refuses that scheme. The official SignalR client hides the rewrite
        behind skipNegotiation + WebSockets transport; we must do it ourselves.
        """
        seen = {}

        def factory(u):
            seen["url"] = u
            return FakeSocket()

        h = SignalRHub("https://rtc.topstepx.com/hubs/user", lambda: TOKEN,
                       connect_factory=factory, sleep=lambda s: None)
        h.connect()
        assert seen["url"].startswith("wss://rtc.topstepx.com/hubs/user?")
        assert "https://" not in seen["url"]

    def test_the_token_rides_the_query_string(self):
        seen = {}
        h = SignalRHub("https://rtc.topstepx.com/hubs/market", lambda: TOKEN,
                       connect_factory=lambda u: (seen.update(url=u), FakeSocket())[1],
                       sleep=lambda s: None)
        h.connect()
        assert "access_token=" in seen["url"]

    def test_the_documented_https_constant_is_what_evidence_reports(self):
        """Evidence should name the hub the docs name, not the rewritten socket."""
        h = hub()
        h.connect()
        assert h.describe()["hub"] == "https://rtc.topstepx.com/hubs/user"

    @pytest.mark.parametrize("given,expected", [
        ("https://rtc.topstepx.com/hubs/user", "wss://rtc.topstepx.com/hubs/user"),
        ("http://localhost:5000/hubs/user", "ws://localhost:5000/hubs/user"),
        ("wss://already.correct/hub", "wss://already.correct/hub"),
    ])
    def test_scheme_rewrite_is_total_and_idempotent(self, given, expected):
        from broker.topstepx_realtime import _ws_scheme
        assert _ws_scheme(given) == expected


# ══════════════════════════════════════════════════════════════════════════════
class TestReadOnlyEnforcement:

    def session(self, log=None, **kw):
        return TopstepXReadOnlySession(
            "user", "key", transport=make_transport(base_routes(**kw), log))

    def test_no_write_methods_exist_on_the_session(self):
        s = self.session()
        for name in ("place_order", "submit_order", "cancel_order", "modify_order",
                     "close_position", "flatten", "emergency_flatten"):
            assert not hasattr(s, name), f"{name} must not exist on a read-only session"
        assert s.assert_no_write_surface()

    @pytest.mark.parametrize("path", sorted(KNOWN_WRITE_PATHS))
    def test_every_known_write_endpoint_is_refused_at_the_transport(self, path):
        s = self.session()
        with pytest.raises(ReadOnlyViolation) as exc:
            s._guarded_transport(f"https://api.topstepx.com{path}", {}, {}, 5)
        assert "No request was sent" in str(exc.value)
        assert s.write_attempts == [path]

    def test_an_unknown_endpoint_is_denied_by_default(self):
        """A write endpoint TopstepX adds tomorrow must fail closed today."""
        s = self.session()
        with pytest.raises(ReadOnlyViolation):
            s._guarded_transport("https://api.topstepx.com/api/Order/futureThing", {}, {}, 5)

    def test_the_read_path_still_works_through_the_guard(self):
        log = []
        s = self.session(log)
        s.authenticate()
        s.pin(account_id=7788)
        s.resolve_contract("MNQ")
        assert s.open_positions() == []
        assert s.open_orders() == []
        assert "/api/Order/searchOpen" in log
        assert s.write_attempts == []

    def test_the_zero_write_proof_reports_no_writes(self):
        s = self.session()
        s.authenticate()
        s.pin(account_id=7788)
        proof = s.zero_write_proof()
        assert proof["write_calls_made"] == 0
        assert proof["write_attempts"] == []
        assert "/api/Account/search" in proof["endpoints_called"]

    def test_positions_and_orders_reflect_real_state(self):
        pos = [{"id": 1, "contractId": MNQ["id"], "type": 1, "size": 2,
                "averagePrice": 20000.0, "creationTimestamp": "2026-08-04T13:00:00+00:00"}]
        orders = [{"id": 5, "contractId": MNQ["id"], "status": 1, "type": 4,
                   "side": 1, "size": 2, "limitPrice": None, "stopPrice": 19950.0}]
        s = self.session(positions=pos, orders=orders)
        s.authenticate()
        s.pin(account_id=7788)
        assert len(s.open_positions()) == 1
        assert len(s.open_orders()) == 1


# ══════════════════════════════════════════════════════════════════════════════
class TestRedaction:

    def test_a_configured_secret_never_survives(self, monkeypatch):
        monkeypatch.setenv("TOPSTEPX_API_KEY", "sk-super-secret-value")
        assert "sk-super-secret-value" not in redact("key=sk-super-secret-value tail")
        assert MASK in redact("key=sk-super-secret-value tail")

    def test_a_jwt_is_caught_by_shape_even_when_unconfigured(self):
        assert TOKEN not in redact(f"Authorization: Bearer {TOKEN}")

    def test_a_bearer_header_is_masked(self):
        assert "Bearer [REDACTED]" in redact("Authorization: Bearer abc.def.ghi")

    def test_secret_named_keys_are_masked_whatever_the_value(self):
        out = redact_mapping({"userName": "maurice", "apiKey": "k", "nested": {"token": TOKEN}})
        assert out["userName"] == MASK and out["apiKey"] == MASK
        assert out["nested"]["token"] == MASK

    def test_there_is_no_partial_reveal_mode(self):
        """A tail-of-the-key display is still a reveal; the mask is total."""
        monkeypatch_val = "abcdefghijklmnop"
        os.environ["TOPSTEPX_API_KEY"] = monkeypatch_val
        try:
            out = redact(f"key={monkeypatch_val}")
            assert "mnop" not in out and "abcd" not in out
        finally:
            os.environ.pop("TOPSTEPX_API_KEY", None)

    def test_assert_clean_passes_clean_text_through(self):
        assert assert_clean("nothing sensitive") == "nothing sensitive"

    def test_assert_clean_is_a_real_guard_not_just_a_redact_call(self, monkeypatch):
        """If redaction ever regressed to a no-op, the write must still fail.

        Neutering `redact` inside the module simulates that regression: the
        post-check has to catch the secret on its own, otherwise `assert_clean`
        is decorative and an artifact could ship a live credential.
        """
        import broker.topstepx_redaction as red
        monkeypatch.setenv("TOPSTEPX_API_KEY", "sk-live-key-value")
        monkeypatch.setattr(red, "redact", lambda t: str(t))
        with pytest.raises(RuntimeError) as exc:
            red.assert_clean("key=sk-live-key-value", where="artifact")
        assert "redaction failed" in str(exc.value)

    def test_a_surviving_jwt_shape_is_caught_by_the_guard(self, monkeypatch):
        import broker.topstepx_redaction as red
        monkeypatch.setattr(red, "redact", lambda t: str(t))
        with pytest.raises(RuntimeError):
            red.assert_clean(f"token={TOKEN}")

    def test_the_account_label_hides_the_account_number(self):
        assert redacted_account_label("50KCOMBINE98765") == f"KCOMBINE{MASK}" or \
               redacted_account_label("PRACTICEJUL2612345") == f"PRACTICEJUL{MASK}"
        assert "98765" not in redacted_account_label("50KCOMBINE98765")

    def test_the_fingerprint_is_stable_and_non_reversible(self):
        a = account_fingerprint(7788, "50KCOMBINE98765")
        assert a == account_fingerprint(7788, "50KCOMBINE98765")
        assert a != account_fingerprint(9911, "50KCOMBINE98765")
        assert "98765" not in a and "7788" not in a


# ══════════════════════════════════════════════════════════════════════════════
class TestPreflight:
    """End-to-end locks on the Phase 2 preflight, against a fake venue."""

    def _preflight(self, tmp_path, monkeypatch, **route_kw):
        from broker import topstepx_readonly_preflight as pf

        # The preflight module calls load_dotenv() at import, so a real .env on
        # the operator's machine leaks into these tests. Every variable in the
        # contract is therefore set or cleared explicitly — a suite whose result
        # depends on whether the developer has credentials configured is a suite
        # that passes for the wrong reason.
        monkeypatch.setenv("TOPSTEPX_USERNAME", "maurice-login")
        monkeypatch.setenv("TOPSTEPX_API_KEY", "sk-live-key-value")
        monkeypatch.setenv("TOPSTEPX_ACCOUNT_ID", "7788")
        monkeypatch.delenv("TOPSTEPX_ACCOUNT_NAME", raising=False)
        monkeypatch.delenv("TOPSTEPX_ACCOUNT_FINGERPRINT", raising=False)
        monkeypatch.setenv("TOPSTEPX_CONTRACT", "MNQ")
        monkeypatch.setattr(pf, "EVIDENCE_PATH", str(tmp_path / "evidence.json"))

        def factory():
            return TopstepXReadOnlySession(
                "maurice-login", "sk-live-key-value",
                transport=make_transport(base_routes(**route_kw)),
                connect_factory=lambda url: FakeSocket(),
                sleep=lambda s: None)

        return pf, pf.Preflight(session_factory=factory)

    def test_a_clean_venue_produces_a_pass_verdict(self, tmp_path, monkeypatch):
        pf, flight = self._preflight(tmp_path, monkeypatch)
        assert flight.run() == 0
        assert flight.artifact["verdict"] == "PASS"

    def test_the_artifact_records_zero_write_calls(self, tmp_path, monkeypatch):
        pf, flight = self._preflight(tmp_path, monkeypatch)
        flight.run()
        proof = flight.artifact["zero_write_proof"]
        assert proof["write_calls_made"] == 0
        assert proof["write_attempts"] == []
        assert not (set(proof["endpoints_called"]) & set(KNOWN_WRITE_PATHS))

    def test_no_secret_reaches_the_evidence_file(self, tmp_path, monkeypatch):
        pf, flight = self._preflight(tmp_path, monkeypatch)
        flight.run()
        body = open(pf.EVIDENCE_PATH, encoding="utf-8").read()
        for secret in ("maurice-login", "sk-live-key-value", TOKEN):
            assert secret not in body
        assert "98765" not in body           # the account number never lands either

    def test_the_artifact_carries_both_timestamps_and_stream_health(self, tmp_path, monkeypatch):
        pf, flight = self._preflight(tmp_path, monkeypatch)
        flight.run()
        a = flight.artifact
        assert a["generated_at_utc"] and a["generated_at_eastern"]
        assert a["stream_health"]["user_hub"]["handshake_ok"] is True
        assert a["stream_health"]["market_hub"]["subscriptions"] == ["GatewayQuote", "GatewayTrade"]
        assert a["stream_health"]["user_hub"]["resubscribed_in_order"] is True

    def test_an_unpinned_account_blocks_before_any_network_call(self, tmp_path, monkeypatch):
        pf, flight = self._preflight(tmp_path, monkeypatch)
        monkeypatch.delenv("TOPSTEPX_ACCOUNT_ID", raising=False)
        assert flight.run() == 1
        assert flight.artifact["blocker"] == "configuration"

    def test_a_non_flat_account_is_reported_as_such(self, tmp_path, monkeypatch):
        pos = [{"id": 1, "contractId": MNQ["id"], "type": 1, "size": 1,
                "averagePrice": 20000.0, "creationTimestamp": "2026-08-04T13:00:00+00:00"}]
        pf, flight = self._preflight(tmp_path, monkeypatch, positions=pos)
        flight.run()
        states = {c["check"]: c["detail"] for c in flight.artifact["checks"]}
        assert states["flat"] == "NOT FLAT"


class TestBarsWindowHygiene:
    """REGRESSION - retrieveBars debug, 2026-08-05.

    bars() built its window from raw now(), so endTime landed mid-minute with
    microsecond precision while includePartialBar=false asked for closed bars
    only. Every request was also unique, defeating any upstream caching.
    """

    def _capture(self, minutes_back=15):
        captured = {}

        def spy(url, payload, headers, timeout):
            captured.update(payload)
            return {"bars": [], "success": True, "errorCode": 0}

        c = TopstepXClient("u", "k", transport=spy, sleep=lambda s: None)
        c._token = TOKEN
        from datetime import datetime, timedelta, timezone
        c._token_expires = datetime.now(timezone.utc) + timedelta(hours=1)
        c.bars("CON.F.US.MNQ.U26", minutes_back=minutes_back)
        return captured

    def test_the_window_ends_on_a_completed_minute(self):
        p = self._capture()
        assert p["endTime"].endswith(":00Z") or p["endTime"].endswith(":00.000000Z"), p["endTime"]
        assert "." not in p["endTime"].split("T")[1].rstrip("Z") or \
               p["endTime"].split("T")[1].rstrip("Z").endswith(":00.000000")

    def test_start_is_strictly_before_end(self):
        p = self._capture()
        assert p["startTime"] < p["endTime"]

    def test_live_false_survives_serialization(self):
        """A falsy-filtering payload builder would silently delete this."""
        import json
        p = self._capture()
        assert p["live"] is False
        assert '"live": false' in json.dumps(p)

    def test_the_contract_id_stays_a_string(self):
        p = self._capture()
        assert isinstance(p["contractId"], str)
        assert p["contractId"] == "CON.F.US.MNQ.U26"

    def test_partial_bars_are_never_requested_by_default(self):
        assert self._capture()["includePartialBar"] is False

    def test_timestamps_are_utc_zulu(self):
        p = self._capture()
        assert p["startTime"].endswith("Z") and p["endTime"].endswith("Z")
        assert "+00:00" not in p["startTime"]
