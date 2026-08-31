"""The runner's flight recorder, at the exact seam where PROD-20260810 lost it.

`place_order` raised. The reason was formatted into the exception string, the
structured body was discarded, and `self.order_id` was never assigned because
the assignment lives AFTER the call that raised. Two facts died together:

    what Topstep said        (errorCode / errorMessage)
    that Topstep had an order at all   (orderId)

These tests drive the real `ExecutionRunner.submit` against a stub venue and
assert both survive to disk. No network anywhere.
"""
from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))

from broker import topstepx_execution_runner as R          # noqa: E402
from broker import topstepx_submission_record as SUB       # noqa: E402
from broker import topstepx_smoke_auth as smoke_auth       # noqa: E402
from broker.topstepx_client import (ORDER_SIDE, ORDER_TYPE,  # noqa: E402
                                    TopstepXContract, TopstepXError)
from broker.topstepx_combine_risk import BracketGeometry   # noqa: E402

SESSION = "PROD-REC-TEST"
MISSION = "PROD-REC-TEST-T1"
FINGERPRINT = "acct:rec"
NOW = datetime(2026, 8, 11, 14, 0, tzinfo=timezone.utc)
MNQ = TopstepXContract(id="CON.F.US.MNQ.U26", name="MNQ", description="",
                       tick_size=0.25, tick_value=0.5, active=True)

REJECTION = {"success": False, "orderId": 3385801549, "errorCode": 2,
             "errorMessage": "Invalid stop loss ticks (40). Ticks should be "
                             "less than zero when longing.", "fillVolume": 0}


class StubVenue:
    """Answers exactly like the live client, including how it raises."""

    def __init__(self, *, raise_with=None, result=None, orders=None,
                 positions=None):
        self.raise_with = raise_with
        self.result = result
        self._orders = orders or []
        self._positions = positions or []
        self.calls = []

    def place_order(self, payload):
        self.calls.append(payload)
        if self.raise_with is not None:
            raise self.raise_with
        return self.result

    def open_orders(self):
        return list(self._orders)

    def open_positions(self):
        return list(self._positions)


def geometry():
    return BracketGeometry(
        direction="bullish", side="buy", side_code=ORDER_SIDE["buy"],
        entry_price=29800.0, stop_price=29762.5, target_price=29865.0,
        stop_points=37.5, target_points=65.0, stop_ticks=150, target_ticks=260,
        size=3, risk_usd=225.0, reward_usd=390.0)


def runner(venue, store, *, recording=True):
    r = R.ExecutionRunner(session=venue, account_fingerprint=FINGERPRINT,
                          contract=MNQ, clock=lambda: NOW)
    r.geometry = geometry()
    r.token = smoke_auth.issue(
        phrase=smoke_auth.AUTHORIZATION_PHRASE, account_fingerprint=FINGERPRINT,
        contract_id=MNQ.id, max_risk_usd=250.0, max_contracts=15,
        max_stop_points=40.0, now=NOW)
    if recording:
        r.submission_store_dir = store
        r.submission_session_id = SESSION
        r.submission_mission_id = MISSION
    return r


def rows(store, mission_id=MISSION):
    return SUB.load_submissions(store, SESSION, mission_id)


@pytest.fixture
def store(tmp_path):
    return str(tmp_path)


# ══════════════════════════════════════════════════════════════════════════════
class TestTheRejectionSurvivesTheRaise:

    def test_all_four_fields_survive(self, store):
        """success / orderId / errorCode / errorMessage, after the raise."""
        venue = StubVenue(raise_with=TopstepXError("order rejected: boom",
                                                   venue_body=REJECTION))
        r = runner(venue, store)
        with pytest.raises(R.RunnerHalt):
            r.submit(account_id=90000042, custom_tag="EXPBOT-PROD-x")

        last = rows(store)[-1]
        assert last["success"] is False
        assert last["venue_order_id"] == 3385801549
        assert last["error_code"] == 2
        assert last["error_message"] == REJECTION["errorMessage"]
        assert last["raw_response"] == REJECTION
        assert last["state"] == SUB.VENUE_REJECTED

    def test_the_venue_order_id_survives_although_the_runner_never_assigned_it(
            self, store):
        """THE defect: `self.order_id` is set after the call that raised."""
        venue = StubVenue(raise_with=TopstepXError("order rejected",
                                                   venue_body=REJECTION))
        r = runner(venue, store)
        with pytest.raises(R.RunnerHalt):
            r.submit(account_id=90000042, custom_tag="EXPBOT-PROD-x")
        assert r.order_id is None, "the live shape is reproduced"
        assert rows(store)[-1]["venue_order_id"] == 3385801549

    def test_the_payload_is_on_disk_before_transport(self, store):
        """The pre-write must exist even when transport never returns."""
        class Exploding(StubVenue):
            def place_order(self, payload):
                super().place_order(payload)
                raise RuntimeError("socket died mid-flight")

        r = runner(Exploding(), store)
        with pytest.raises(R.RunnerHalt):
            r.submit(account_id=90000042, custom_tag="EXPBOT-PROD-x")
        first = rows(store)[0]
        assert first["state"] == SUB.SUBMISSION_STARTED
        assert first["signed_stop_loss_ticks"] == -150
        assert first["signed_take_profit_ticks"] == 260
        assert first["quantity"] == 3
        assert first["payload_sha256"]

    def test_a_transport_death_is_unknown_not_rejected(self, store):
        r = runner(StubVenue(raise_with=RuntimeError("timeout")), store)
        with pytest.raises(R.RunnerHalt):
            r.submit(account_id=90000042, custom_tag="EXPBOT-PROD-x")
        assert rows(store)[-1]["state"] == SUB.SUBMISSION_UNKNOWN

    def test_an_accepted_order_records_acknowledged(self, store):
        venue = StubVenue(result={"order_id": 42, "accepted": True,
                                  "raw": {"success": True, "orderId": 42}})
        r = runner(venue, store)
        out = r.submit(account_id=90000042, custom_tag="EXPBOT-PROD-x")
        assert out["order_id"] == 42
        last = rows(store)[-1]
        assert last["state"] == SUB.VENUE_ACKNOWLEDGED
        assert last["venue_order_id"] == 42


class TestRecordingIsOptionalButNeverSilentlyPartial:

    def test_with_no_store_configured_nothing_is_written(self, store):
        """Smoke tools and older tests keep working untouched."""
        venue = StubVenue(raise_with=TopstepXError("x", venue_body=REJECTION))
        r = runner(venue, store, recording=False)
        with pytest.raises(R.RunnerHalt):
            r.submit(account_id=1, custom_tag="SMOKE")
        assert not os.path.exists(SUB.ledger_path(store, SESSION))

    def test_production_always_configures_the_recorder(self):
        """`build_runner` must wire it -- asserted at the call site."""
        src = open(os.path.join(ROOT, "src", "broker",
                                "topstepx_production_session.py"),
                   encoding="utf-8").read()
        block = src[src.index("def build_runner("):src.index("def submit(")]
        for field in ("submission_store_dir", "submission_session_id",
                      "submission_mission_id"):
            assert f"runner.{field}" in block, field

    def test_the_pre_write_happens_before_place_order(self):
        """Ordering asserted in the source: a lost rejection is a lost cause."""
        src = open(os.path.join(ROOT, "src", "broker",
                                "topstepx_execution_runner.py"),
                   encoding="utf-8").read()
        body = src[src.index("def submit(self, *, account_id"):
                   src.index("def _recording(")]
        assert body.index("_open_submission_record(") < body.index(
            "self.session.place_order("), "the payload must be durable first"


class TestSanitization:

    def test_the_raw_account_id_never_reaches_the_ledger(self, store):
        venue = StubVenue(result={"order_id": 7, "raw": {"success": True,
                                                         "orderId": 7}})
        runner(venue, store).submit(account_id=90000042, custom_tag="EXPBOT-PROD-x")
        text = open(SUB.ledger_path(store, SESSION), encoding="utf-8").read()
        assert "90000042" not in text

    def test_the_bracket_is_kept_verbatim(self, store):
        """Redacting geometry would defeat the purpose of the record."""
        venue = StubVenue(result={"order_id": 7, "raw": {"success": True,
                                                         "orderId": 7}})
        runner(venue, store).submit(account_id=90000042, custom_tag="EXPBOT-PROD-x")
        sent = rows(store)[0]["sanitized_payload"]
        assert sent["stopLossBracket"] == {"ticks": -150, "type": ORDER_TYPE["stop"]}
        assert sent["takeProfitBracket"] == {"ticks": 260, "type": ORDER_TYPE["limit"]}


class TestVenueBodyExtraction:

    @pytest.mark.parametrize("obj,expected", [
        (TopstepXError("x", venue_body={"success": False, "errorCode": 2}),
         {"success": False, "errorCode": 2}),
        ({"raw": {"success": True, "orderId": 5}}, {"success": True, "orderId": 5}),
        ({"success": True, "orderId": 6}, {"success": True, "orderId": 6}),
        (RuntimeError("no body"), {}),
        (None, {}),
    ])
    def test_the_body_is_found_or_honestly_absent(self, obj, expected):
        assert R.ExecutionRunner._venue_body(obj) == expected

    def test_the_client_attaches_the_body_to_its_error(self):
        """`_post` must not stringify-and-drop the venue's answer."""
        src = open(os.path.join(ROOT, "src", "broker", "topstepx_client.py"),
                   encoding="utf-8").read()
        block = src[src.index("def _post("):src.index("def _request_with_backoff(")]
        assert "venue_body=out" in block


# ══════════════════════════════════════════════════════════════════════════════
class TestRecordingFailureIsNeverSilent:
    """V5 AUDIT ISSUE 1.

    `_record_submission_outcome` used to `except Exception: pass`, which
    reintroduced the PROD-20260810 failure one layer down: the venue answers,
    the write fails, the answer dies in memory anyway. Persistence failure
    after transport must now be loud, must reconcile against the venue, and
    must halt -- while never MASKING what the broker actually did.
    """

    @staticmethod
    def _break_writes(monkeypatch):
        def explode(**kwargs):
            raise OSError("disk full")
        monkeypatch.setattr(SUB, "record_response", explode)

    def test_A_a_rejection_whose_record_fails_cannot_pass_silently(
            self, store, monkeypatch):
        venue = StubVenue(raise_with=TopstepXError("order rejected",
                                                   venue_body=REJECTION))
        r = runner(venue, store)
        self._break_writes(monkeypatch)
        with pytest.raises(R.RunnerHalt) as exc:
            r.submit(account_id=90000042, custom_tag="EXPBOT-PROD-x")

        # the failure is a first-class state, not a swallowed exception
        states = [t.state for t in r.transitions]
        assert R.SUBMISSION_RECORD_WRITE_FAILED in states
        # the venue's answer is preserved in memory rather than lost
        assert r.recording_failure["error_code"] == 2
        assert r.recording_failure["venue_order_id"] == 3385801549
        assert r.recording_failure["error_message"] == REJECTION["errorMessage"]
        assert "disk full" in r.recording_failure["error"]
        # and it still reconciles + halts rather than resubmitting
        assert exc.value.state in (R.SUBMIT_REJECTED, R.SUBMISSION_RECORD_WRITE_FAILED)
        assert len(venue.calls) == 1, "never auto-resubmit"

    def test_A_the_failure_leaves_a_durable_marker_when_it_can(self, store,
                                                               monkeypatch):
        venue = StubVenue(raise_with=TopstepXError("rejected",
                                                   venue_body=REJECTION))
        r = runner(venue, store)
        self._break_writes(monkeypatch)
        with pytest.raises(R.RunnerHalt):
            r.submit(account_id=90000042, custom_tag="EXPBOT-PROD-x")
        marker = os.path.join(store, f"RECORDING_FAILURE_{SESSION}.jsonl")
        assert os.path.exists(marker), "no second chance at durability"
        row = json.loads(open(marker, encoding="utf-8").read().splitlines()[0])
        assert row["error_code"] == 2 and row["venue_order_id"] == 3385801549

    def test_B_an_accepted_order_is_reconciled_not_hidden(self, store,
                                                          monkeypatch):
        """Broker reality has priority: the live position must surface."""
        position = {"id": 1, "contract_id": MNQ.id, "side": "long", "size": 3}
        venue = StubVenue(result={"order_id": 42, "accepted": True,
                                  "raw": {"success": True, "orderId": 42}},
                          positions=[position],
                          orders=[{"id": 43, "contract_id": MNQ.id,
                                   "parentOrderId": 42}])
        r = runner(venue, store)
        self._break_writes(monkeypatch)
        with pytest.raises(R.RunnerHalt) as exc:
            r.submit(account_id=90000042, custom_tag="EXPBOT-PROD-x")

        assert exc.value.state == R.SUBMISSION_RECORD_WRITE_FAILED
        # the venue was asked, and what it said is in the halt
        assert "1 position(s)" in exc.value.detail
        assert "1 working order(s)" in exc.value.detail
        assert R.SUBMIT_UNKNOWN in [t.state for t in r.transitions]
        assert r.recording_failure["venue_order_id"] == 42
        assert len(venue.calls) == 1, "never auto-resubmit"

    def test_B_an_unreachable_venue_after_a_recording_failure_still_halts(
            self, store, monkeypatch):
        class Blind(StubVenue):
            def open_positions(self):
                raise TopstepXError("position search unavailable")

        venue = Blind(result={"order_id": 42, "raw": {"success": True,
                                                      "orderId": 42}})
        r = runner(venue, store)
        self._break_writes(monkeypatch)
        with pytest.raises(R.RunnerHalt) as exc:
            r.submit(account_id=90000042, custom_tag="EXPBOT-PROD-x")
        assert exc.value.state == R.SUBMISSION_RECORD_WRITE_FAILED
        assert "could not be re-queried" in exc.value.detail

    def test_C_a_normal_response_records_and_does_not_halt(self, store):
        venue = StubVenue(result={"order_id": 42, "accepted": True,
                                  "raw": {"success": True, "orderId": 42}})
        r = runner(venue, store)
        out = r.submit(account_id=90000042, custom_tag="EXPBOT-PROD-x")
        assert out["order_id"] == 42
        assert r.recording_failure is None
        assert R.SUBMISSION_RECORD_WRITE_FAILED not in [t.state for t in r.transitions]
        assert rows(store)[-1]["state"] == SUB.VENUE_ACKNOWLEDGED

    def test_the_recorder_no_longer_swallows_exceptions(self):
        """The literal defect: `except Exception: pass` in the outcome path."""
        src = open(os.path.join(ROOT, "src", "broker",
                                "topstepx_execution_runner.py"),
                   encoding="utf-8").read()
        body = src[src.index("def _record_submission_outcome("):
                   src.index("def _emergency_recording_marker(")]
        assert "pass" not in body.split("except Exception as exc:")[-1][:200]
        assert "self.recording_failure = {" in body
        assert "SUBMISSION_RECORD_WRITE_FAILED" in body
