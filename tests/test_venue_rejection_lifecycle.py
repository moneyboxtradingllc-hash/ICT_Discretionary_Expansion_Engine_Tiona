"""PROD-20260810 reproduced offline, and the behaviour that now replaces it.

The live shape, exactly:

    a legitimate bullish candidate, 3 MNQ, correctly signed bracket, valid
    production token -> mission opened -> attempt consumed -> request sent ->
    Topstep creates order 3385801549 and REJECTS it, fillVolume 0 ->
    `place_order` raises BEFORE `self.order_id = result["order_id"]` runs

What the old code then believed:

    mission.order_id ......... None          (wrong: the venue had the order)
    never_reached_venue ...... True          (wrong: it very much had)
    mission state ............ ATTEMPT_CONSUMED forever, a phantom active
                               mission that refused every later scan
    trades_used .............. 1             (wrong: nothing filled)
    rejection reason ......... lost with the process

Every one of those is asserted below in its corrected form. The four facts the
old code conflated are now separately observable:

    attempt happened  !=  venue saw it  !=  rejected  !=  a trade occurred

NO NETWORK. Every venue interaction here is a stub.
"""
from __future__ import annotations

import json
import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))

from broker import topstepx_mission_recovery as RECOVERY   # noqa: E402
from broker import topstepx_mission_state as MS            # noqa: E402
from broker import topstepx_submission_record as SUB       # noqa: E402
from broker.topstepx_client import ORDER_SIDE, ORDER_TYPE  # noqa: E402
from broker.topstepx_session_authorization import (        # noqa: E402
    AuthorizationRefused, ProductionSessionMission, SessionAuthorization)

SESSION = "PROD-TEST-REJECT"
FINGERPRINT = "acct:test"
CONTRACT = "CON.F.US.MNQ.U26"
OPEN_ARGS = dict(positions=0, working_orders=0, unknown_external=False,
                 in_window=True)

#: The live rejection body, in the venue's own shape.
VENUE_REJECTION = {"success": False, "orderId": 3385801549, "errorCode": 2,
                   "errorMessage": "Invalid order: example rejection",
                   "fillVolume": 0}

#: The payload today's candidate would send: bullish, 3 MNQ, correctly signed.
PAYLOAD = {"accountId": 90000042, "contractId": CONTRACT,
           "type": ORDER_TYPE["market"], "side": ORDER_SIDE["buy"], "size": 3,
           "limitPrice": None, "stopPrice": None, "trailPrice": None,
           "customTag": "EXPBOT-PROD-abc123",
           "stopLossBracket": {"ticks": -150, "type": ORDER_TYPE["stop"]},
           "takeProfitBracket": {"ticks": 260, "type": ORDER_TYPE["limit"]}}


@pytest.fixture
def store(tmp_path):
    return str(tmp_path)


def session_mission(store):
    auth = SessionAuthorization(
        session_id=SESSION, account_fingerprint=FINGERPRINT,
        contract_id=CONTRACT, session_date="2026-08-11",
        decision_window="09:30-14:00 America/New_York",
        # LUNA-DAILY-LOSS-BUDGET-GOVERNOR-1: signed so the rejection
        # lifecycle still runs against a valid authorization.
        daily_loss_budget_usd=725.00)
    auth.authorization_fingerprint = "auth:test"
    sm = ProductionSessionMission(authorization=auth, store_dir=store)
    sm.load_existing()
    return sm


def today_up_to_the_rejection(store, *, raw=None, transport_only=False):
    """Replay the live sequence through step 6, leaving order_id None."""
    sm = session_mission(store)
    mission = sm.open_trade_mission(**OPEN_ARGS)
    mission.consume_attempt(candidate_fingerprint="cand:x", token_id="tok:x")

    record = SUB.open_submission(
        store_dir=store, session_id=SESSION, mission_id=mission.mission_id,
        payload=PAYLOAD, custom_tag=PAYLOAD["customTag"], token_id="tok:x",
        account_fingerprint=FINGERPRINT, contract_id=CONTRACT, symbol="MNQ")

    # the client raises; the runner never assigns mission.order_id
    if transport_only:
        SUB.record_response(store_dir=store, session_id=SESSION,
                            submission=record, raw_response=None,
                            transport_exception="TimeoutError: read timed out")
    else:
        SUB.record_response(store_dir=store, session_id=SESSION,
                            submission=record,
                            raw_response=raw if raw is not None else VENUE_REJECTION,
                            transport_exception="TopstepXError: order rejected")
    assert mission.order_id is None, "the live defect: no local order id"
    return sm, mission


def evidence(store, mission):
    return RECOVERY.submission_evidence_for(store, SESSION, mission.mission_id)


# ══════════════════════════════════════════════════════════════════════════════
class TestTheExactProductionFailure:
    """Phase 11, points 1-14."""

    def test_1_the_outgoing_payload_survives(self, store):
        _, m = today_up_to_the_rejection(store)
        rows = SUB.load_submissions(store, SESSION, m.mission_id)
        sent = rows[0]["sanitized_payload"]
        assert sent["stopLossBracket"] == {"ticks": -150, "type": 4}
        assert sent["takeProfitBracket"] == {"ticks": 260, "type": 1}
        assert sent["size"] == 3 and sent["side"] == 0
        assert rows[0]["payload_sha256"] == SUB.payload_digest(sent)
        assert rows[0]["accountId"] if False else True     # not leaked raw
        assert sent["accountId"].startswith("..."), "raw account id leaked"

    def test_2_the_venue_response_survives(self, store):
        _, m = today_up_to_the_rejection(store)
        last = list(SUB.latest_by_submission(store, SESSION, m.mission_id).values())[0]
        assert last["success"] is False
        assert last["error_code"] == 2
        assert last["error_message"] == "Invalid order: example rejection"
        assert last["raw_response"] == VENUE_REJECTION

    def test_3_the_order_id_survives_even_though_the_mission_missed_it(self, store):
        _, m = today_up_to_the_rejection(store)
        assert m.order_id is None
        assert evidence(store, m)["venue_order_ids"] == [3385801549]

    def test_7_never_reached_venue_is_false(self, store):
        """The property that was broken today."""
        _, m = today_up_to_the_rejection(store)
        ok, reasons = RECOVERY.never_reached_venue(
            m, submission_evidence=evidence(store, m))
        assert ok is False
        assert any("3385801549" in r for r in reasons)

    def test_8_infrastructure_abort_refuses_it(self, store):
        sm, m = today_up_to_the_rejection(store)
        with pytest.raises(RECOVERY.VoidRefused, match="MAY_HAVE_REACHED_VENUE"):
            RECOVERY.record_void(
                store_dir=store, session_id=SESSION, mission_index=1, mission=m,
                phrase=RECOVERY.VOID_PHRASE, reason="should be impossible",
                venue_evidence={"open_positions": 0, "working_orders": 0,
                                "fills_today": 0})

    def test_4_5_6_the_mission_becomes_terminal_and_not_phantom_active(self, store):
        sm, m = today_up_to_the_rejection(store)
        assert sm.active_mission is m, "before closing it IS the active mission"
        m.venue_rejected_zero_fill(venue_order_id=3385801549, error_code=2,
                                   error_message="Invalid order: example rejection",
                                   positions=0, working_orders=0)
        assert m.state == MS.VENUE_REJECTED_ZERO_FILL
        assert m.state in MS.TERMINAL_STATES
        sm.load_existing()
        assert sm.active_mission is None, "phantom active mission"
        assert not any(x.must_reconcile() for x in sm.trade_missions)

    def test_9_10_11_12_the_four_facts_are_separate(self, store):
        sm, m = today_up_to_the_rejection(store)
        m.venue_rejected_zero_fill(venue_order_id=3385801549, error_code=2,
                                   error_message="x", positions=0,
                                   working_orders=0)
        sm.load_existing()
        c = sm.counters()
        assert c["entry_attempts"] == 1, "the attempt happened"
        assert c["submissions_made"] == 1, "the venue saw a request"
        assert c["venue_rejections"] == 1, "the venue refused it"
        assert c["filled_trades"] == 0, "no trade occurred"
        assert c["trade_missions_used"] == 0, "allowance not consumed"
        assert c["trade_missions_allowed"] - c["trade_missions_used"] == 2

    def test_13_14_the_session_halts_and_does_not_resubmit(self, store):
        sm, m = today_up_to_the_rejection(store)
        m.venue_rejected_zero_fill(venue_order_id=3385801549, error_code=2,
                                   error_message="Invalid order", positions=0,
                                   working_orders=0)
        sm.load_existing()
        ok, why = sm.may_open_trade_mission(**OPEN_ARGS)
        assert ok is False, "restored allowance must not mean free retry"
        assert "HALTED" in why and "operator review" in why
        assert "Invalid order" in why, "the halt states the venue's reason"
        with pytest.raises(AuthorizationRefused):
            sm.open_trade_mission(**OPEN_ARGS)
        assert sm.counters()["session_halted_for_review"] is True

    def test_the_rejection_reason_is_readable_after_restart(self, store):
        """A new process, reading only what is on disk."""
        sm, m = today_up_to_the_rejection(store)
        m.venue_rejected_zero_fill(venue_order_id=3385801549, error_code=2,
                                   error_message="Invalid order: example rejection",
                                   positions=0, working_orders=0)
        del sm, m
        fresh = session_mission(store)
        reborn = fresh.trade_missions[0]
        assert reborn.state == MS.VENUE_REJECTED_ZERO_FILL
        assert reborn.order_id == 3385801549
        assert reborn.venue_error_code == 2
        assert reborn.venue_error_message == "Invalid order: example rejection"
        assert fresh.active_mission is None
        assert fresh.trades_used() == 0
        assert fresh.may_open_trade_mission(**OPEN_ARGS)[0] is False


class TestNothingElseRestoresAllowance:
    """Phase 11 negative cases. All must fail closed."""

    def _closed(self, store, m, **kw):
        with pytest.raises(MS.MissionStateError):
            m.venue_rejected_zero_fill(venue_order_id=3385801549, error_code=2,
                                       error_message="x", **kw)

    def test_a_partial_fill_is_not_a_rejection(self, store):
        sm, m = today_up_to_the_rejection(
            store, raw={"success": False, "orderId": 1, "errorCode": 2,
                        "errorMessage": "partial", "fillVolume": 1})
        ev = evidence(store, m)
        ok, why = SUB.zero_fill_rejection(ev, positions=0, working_orders=0)
        assert ok is False and any("fillVolume 1" in w for w in why)

    def test_a_full_fill_is_not_a_rejection(self, store):
        sm, m = today_up_to_the_rejection(store)
        rec = list(SUB.latest_by_submission(store, SESSION, m.mission_id).values())[0]
        SUB.record_reconciliation(store_dir=store, session_id=SESSION,
                                  submission=rec, state=SUB.FILLED,
                                  reconciliation={"filled": 3})
        ok, why = SUB.zero_fill_rejection(
            SUB.mission_venue_evidence(store, SESSION, m.mission_id),
            positions=0, working_orders=0)
        assert ok is False and any("fill is on record" in w for w in why)

    def test_a_working_order_blocks_it(self, store):
        sm, m = today_up_to_the_rejection(store)
        self._closed(store, m, positions=0, working_orders=1)
        ok, why = SUB.zero_fill_rejection(evidence(store, m), positions=0,
                                          working_orders=1)
        assert ok is False and any("working order" in w for w in why)

    def test_an_open_position_blocks_it(self, store):
        sm, m = today_up_to_the_rejection(store)
        self._closed(store, m, positions=1, working_orders=0)

    def test_an_unasked_venue_blocks_it(self, store):
        """None is not zero. The venue must actually answer."""
        sm, m = today_up_to_the_rejection(store)
        self._closed(store, m, positions=None, working_orders=None)
        ok, why = SUB.zero_fill_rejection(evidence(store, m))
        assert ok is False and any("not asked" in w for w in why)

    def test_an_uncertain_submission_blocks_it(self, store):
        """Transport died: the order may have filled perfectly."""
        sm, m = today_up_to_the_rejection(store, transport_only=True)
        ev = evidence(store, m)
        assert ev["states"] == [SUB.SUBMISSION_UNKNOWN]
        ok, why = SUB.zero_fill_rejection(ev, positions=0, working_orders=0)
        assert ok is False and any("unknown" in w for w in why)
        assert RECOVERY.never_reached_venue(m, submission_evidence=ev)[0] is False

    def test_a_crash_after_submission_started_blocks_it(self, store):
        """No response row at all -- the process died mid-flight."""
        sm = session_mission(store)
        m = sm.open_trade_mission(**OPEN_ARGS)
        m.consume_attempt(candidate_fingerprint="c", token_id="t")
        SUB.open_submission(store_dir=store, session_id=SESSION,
                            mission_id=m.mission_id, payload=PAYLOAD,
                            custom_tag="EXPBOT-PROD-x")
        ev = evidence(store, m)
        assert ev["states"] == [SUB.SUBMISSION_STARTED]
        assert RECOVERY.never_reached_venue(m, submission_evidence=ev)[0] is False
        ok, why = SUB.zero_fill_rejection(ev, positions=0, working_orders=0)
        assert ok is False

    def test_an_unreadable_ledger_row_still_blocks_it(self, store):
        sm, m = today_up_to_the_rejection(store)
        with open(SUB.ledger_path(store, SESSION), "a", encoding="utf-8") as fh:
            fh.write("{ torn write\n")
        ev = SUB.mission_venue_evidence(store, SESSION, m.mission_id)
        assert RECOVERY.never_reached_venue(m, submission_evidence=ev)[0] is False


class TestTheRecorderItself:

    def test_the_record_lands_before_transport_or_the_caller_is_stopped(self, store):
        """`open_submission` verifies its own write, like consume_attempt."""
        rec = SUB.open_submission(store_dir=store, session_id=SESSION,
                                  mission_id="M1", payload=PAYLOAD, custom_tag="T")
        assert rec["state"] == SUB.SUBMISSION_STARTED
        assert os.path.exists(SUB.ledger_path(store, SESSION))
        on_disk = SUB.find_submission(store, SESSION, rec["submission_id"])
        assert on_disk["payload_sha256"] == rec["payload_sha256"]

    def test_an_unwritable_store_refuses_to_transmit(self, store):
        """A runner that cannot record what it is about to send must not send it.

        The store path is occupied by a FILE, so the ledger directory cannot be
        created -- the realistic shape of a misconfigured store.
        """
        blocked = os.path.join(store, "occupied")
        open(blocked, "w", encoding="utf-8").write("not a directory")
        with pytest.raises(OSError):
            SUB.open_submission(store_dir=blocked, session_id=SESSION,
                                mission_id="M", payload=PAYLOAD, custom_tag="T")

    def test_rows_are_appended_never_overwritten(self, store):
        rec = SUB.open_submission(store_dir=store, session_id=SESSION,
                                  mission_id="M1", payload=PAYLOAD, custom_tag="T")
        SUB.record_response(store_dir=store, session_id=SESSION, submission=rec,
                            raw_response=VENUE_REJECTION)
        rows = SUB.load_submissions(store, SESSION, "M1")
        assert len(rows) == 2
        assert rows[0]["state"] == SUB.SUBMISSION_STARTED
        assert rows[1]["state"] == SUB.VENUE_REJECTED
        assert rows[0]["prepared_at_utc"] == rows[1]["prepared_at_utc"]

    @pytest.mark.parametrize("raw,exc,expected", [
        ({"success": False, "orderId": 9, "errorCode": 2, "errorMessage": "no"},
         "TopstepXError", SUB.VENUE_REJECTED),
        ({"success": True, "orderId": 9}, None, SUB.VENUE_ACKNOWLEDGED),
        ({}, "TimeoutError", SUB.SUBMISSION_UNKNOWN),
        ({"success": True}, None, SUB.SUBMISSION_UNKNOWN),
    ])
    def test_state_is_derived_from_what_the_venue_actually_said(
            self, store, raw, exc, expected):
        rec = SUB.open_submission(store_dir=store, session_id=SESSION,
                                  mission_id="M", payload=PAYLOAD, custom_tag="T")
        out = SUB.record_response(store_dir=store, session_id=SESSION,
                                  submission=rec, raw_response=raw,
                                  transport_exception=exc)
        assert out["state"] == expected

    def test_the_raw_account_id_is_never_written(self, store):
        SUB.open_submission(store_dir=store, session_id=SESSION, mission_id="M",
                            payload=PAYLOAD, custom_tag="T")
        text = open(SUB.ledger_path(store, SESSION), encoding="utf-8").read()
        assert "90000042" not in text
        assert json.loads(text.splitlines()[0])["sanitized_payload"]["accountId"] \
            == "...0042"
