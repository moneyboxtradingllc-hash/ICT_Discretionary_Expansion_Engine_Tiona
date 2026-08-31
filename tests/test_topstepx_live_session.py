"""Write-capable session locks. No network; the transport is injected."""
from __future__ import annotations

import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src"))

from broker.topstepx_live_session import WRITE_PATHS, TopstepXLiveSession  # noqa: E402

CID = "CON.F.US.MNQ.U26"
TOKEN = "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxIn0.sig"
ACCT = {"id": 7788, "name": "50KTC-V2", "balance": 50000.0, "canTrade": True,
        "isVisible": True, "simulated": True}
MNQ = {"id": CID, "name": "MNQU6", "description": "MNQ", "tickSize": 0.25,
       "tickValue": 0.5, "activeContract": True}


def transport(log):
    def _t(url, payload, headers, timeout):
        path = url.split("topstepx.com", 1)[-1]
        log.append({"path": path, "payload": payload})
        return {
            "/api/Auth/loginKey": {"token": TOKEN, "success": True, "errorCode": 0},
            "/api/Account/search": {"accounts": [ACCT], "success": True, "errorCode": 0},
            "/api/Contract/search": {"contracts": [MNQ], "success": True, "errorCode": 0},
            "/api/Position/searchOpen": {"positions": [], "success": True, "errorCode": 0},
            "/api/Order/searchOpen": {"orders": [], "success": True, "errorCode": 0},
            "/api/Order/place": {"orderId": 9056, "success": True, "errorCode": 0},
            "/api/Order/cancel": {"success": True, "errorCode": 0},
            "/api/Position/closeContract": {"success": True, "errorCode": 0},
        }.get(path, {"success": True, "errorCode": 0})
    return _t


def session(log):
    s = TopstepXLiveSession("u", "k", transport=transport(log))
    s.authenticate()
    s.pin(account_id=7788)
    s.resolve_contract("MNQ")
    return s


class TestLiveSession:

    def test_it_pins_and_resolves_like_the_read_only_session(self):
        s = session([])
        assert s.account.id == 7788 and s.contract.id == CID

    def test_reads_work(self):
        s = session([])
        assert s.open_positions() == [] and s.open_orders() == []

    def test_place_order_sends_the_exact_payload_it_was_given(self):
        """The validated body must reach the venue byte-for-byte."""
        log = []
        s = session(log)
        body = {"accountId": 7788, "contractId": CID, "type": 2, "side": 0, "size": 1,
                "limitPrice": None, "stopPrice": None, "trailPrice": None,
                "customTag": "EXPBOT-smoke-1",
                "stopLossBracket": {"ticks": 20, "type": 4},
                "takeProfitBracket": {"ticks": 60, "type": 1}}
        out = s.place_order(body)
        sent = [e for e in log if e["path"] == "/api/Order/place"][0]
        assert sent["payload"] == body, "the body must not be rebuilt or mutated"
        assert out["order_id"] == 9056

    def test_writes_are_recorded_for_evidence(self):
        s = session([])
        assert s.write_proof()["write_calls_made"] == 0
        s.place_order({"accountId": 7788})
        s.cancel_order(5)
        s.modify_order(5, stop_price=29980.0)
        s.close_position(CID)
        proof = s.write_proof()
        assert proof["write_calls_made"] == 4
        assert {w["endpoint"] for w in proof["writes"]} == set(WRITE_PATHS)

    def test_reads_alone_record_no_writes(self):
        s = session([])
        s.open_positions()
        s.open_orders()
        assert s.write_proof()["write_calls_made"] == 0

    def test_it_refuses_to_act_before_being_pinned(self):
        s = TopstepXLiveSession("u", "k", transport=transport([]))
        s.authenticate()
        for call in (s.open_positions, s.open_orders):
            with pytest.raises(RuntimeError):
                call()
        with pytest.raises(RuntimeError):
            s.place_order({})

    def test_constructing_it_arms_nothing(self):
        log = []
        TopstepXLiveSession("u", "k", transport=transport(log))
        assert log == [], "construction must not touch the venue"

    def test_it_exposes_exactly_four_write_endpoints(self):
        """EXEC-PRICE-ANCHOR-1 (2026-08-18) added `/api/Order/modify`.

        This deliberately widens the write surface, so it is stated here rather
        than absorbed. The venue's attached brackets are TICK OFFSETS applied to
        the actual fill, so after slippage the working stop sits at a price the
        thesis never authorized. Moving it back onto the authorized structural
        invalidation requires a modify, and `TopstepXClient` already owned the
        verified endpoint -- only the session passthrough was missing.
        """
        assert set(WRITE_PATHS) == {"/api/Order/place", "/api/Order/cancel",
                                    "/api/Order/modify",
                                    "/api/Position/closeContract"}

    def test_it_holds_no_decision_logic(self):
        """Bracket building and authorization live elsewhere, by design."""
        import inspect
        import broker.topstepx_live_session as m
        src = inspect.getsource(m)
        for banned in ("build_bracket", "smoke_auth", "authorize_submission",
                       "as_order_payload", "RiskRejection"):
            assert banned not in src
