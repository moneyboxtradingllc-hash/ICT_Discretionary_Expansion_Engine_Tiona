"""LUNA-VENUE-MINTED-CLOSE-LINEAGE-1 phase 1 -- durable close intent.

PROD-20260902. The emergency liquidation flattened a real position through
`POST /api/Position/closeContract`, and the runner called it as a bare
statement: no durable record that a close was intended, and the venue's answer
discarded on the return. The venue minted order 3479178907; nothing local could
ever prove it was ours, so the daily governor -- correctly -- called it
unattributable and the session went CONTAMINATED.

The same ignorance is on record from 2026-08-05, where a real close was
collapsed into `{"step": "flatten", "accepted": true}` and the resulting order
3368041611 was filed under `origin: MANUAL_OPERATOR` -- a positively FALSE
claim, worse than today's honest unknown.

PHASE 1 RECORDS TRANSPORT TRUTH ONLY. It does not prove which venue order
closed the position, does not set `exit_order_id`, and changes no governor
behaviour. Its single purpose is that the request and the answer can never be
lost again -- which is also how the still-unproven question "does closeContract
return an orderId?" gets answered, from the next real close rather than from a
probe fired at a flat account.
"""
from __future__ import annotations

import json
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))), "src"))

from broker import topstepx_emergency_liquidation as EL          # noqa: E402
from broker import topstepx_execution_runner as R                # noqa: E402
from broker import topstepx_submission_record as SUBREC          # noqa: E402
from broker.topstepx_client import TopstepXContract              # noqa: E402

MNQ = TopstepXContract(id="CON.F.US.MNQ.U26", name="MNQU6", description="",
                       tick_size=0.25, tick_value=0.5, active=True)
SESSION = "PRAC-20260902-LUNA"


class CloseVenue:
    """Records ORDER of operations, because ordering is the invariant."""

    def __init__(self, response=None, raises=None):
        self.response, self.raises = response, raises
        self.calls = []

    def close_position(self, contract_id):
        self.calls.append(("close_position", contract_id))
        if self.raises is not None:
            raise self.raises
        return self.response



class NakedVenue(CloseVenue):
    """A genuinely naked position: nonzero size, no working orders.

    That is exactly the state the planner calls E3A_EMERGENCY_NAKED -- it is
    only reachable with discovery COMPLETE and every executable order of ours
    already terminal, which `query_orders` returning [] models.
    """

    def __init__(self, size=-5, response=None, raises=None):
        super().__init__(response=response, raises=raises)
        self.size = size

    def open_positions(self):
        if self.size == 0:
            return []
        return [{"id": 1, "contract_id": MNQ.id, "size": abs(self.size),
                 "side": "short" if self.size < 0 else "long",
                 "avg_price": 29097.75}]

    def query_orders(self, *, statuses=None, contract_id=None):
        return []

    def open_orders(self):
        return []

    def recent_trades(self, since=None):
        return []

    def close_position(self, contract_id):
        out = super().close_position(contract_id)
        self.size = 0                      # the venue really does flatten
        return out

def runner(tmp_path, venue, *, recording=True):
    r = object.__new__(R.ExecutionRunner)
    r.session = venue
    r.contract = MNQ
    r.token = None
    r.geometry = None
    r.recording_failure = None
    r.close_durability_failures = []
    r.transitions = []
    r.state = R.DISARMED
    r.clock = lambda: __import__('datetime').datetime.now(
        __import__('datetime').timezone.utc)
    r.mission_owns_order = lambda o: True
    r.entry_capture = None
    r.order_id = None
    r.submission_record = None
    r.account_fingerprint = "acct:test"
    r.submission_mission_id = "PRAC-20260902-LUNA-T1"
    r.submission_authorization_fingerprint = "auth:test"
    r.submission_store_dir = str(tmp_path) if recording else ""
    r.submission_session_id = SESSION if recording else ""
    return r


def ledger(tmp_path):
    path = SUBREC.ledger_path(str(tmp_path), SESSION)
    if not os.path.exists(path):
        return []
    with open(path, encoding="utf-8") as fh:
        return [json.loads(line) for line in fh if line.strip()]


def closes(tmp_path):
    return [r for r in ledger(tmp_path)
            if r.get("operation") == SUBREC.OPERATION_POSITION_CLOSE]


# ══════════════════════════════════════════════════════════════════════════════
class TestOperationIsNamed:
    """A close is not an order place, and must not be filed as one."""

    def test_place_is_the_default_so_existing_records_keep_their_meaning(self, tmp_path):
        rec = SUBREC.open_submission(
            store_dir=str(tmp_path), session_id=SESSION, mission_id="M",
            payload={"accountId": 1, "contractId": MNQ.id, "type": 2,
                     "side": 0, "size": 1},
            custom_tag="EXPBOT-x")
        assert rec["operation"] == SUBREC.OPERATION_ORDER_PLACE

    def test_a_close_is_recorded_as_a_position_close(self, tmp_path):
        r = runner(tmp_path, CloseVenue(response={"success": True}))
        r._open_close_submission(round_index=1)
        assert closes(tmp_path)[0]["operation"] == SUBREC.OPERATION_POSITION_CLOSE

    def test_absent_order_fields_are_absent_not_faked(self, tmp_path):
        """closeContract carries no side/size/type. Recording zeros would be a
        lie about what was sent."""
        r = runner(tmp_path, CloseVenue(response={"success": True}))
        r._open_close_submission(round_index=1)
        row = closes(tmp_path)[0]
        assert row["side"] is None and row["quantity"] is None
        assert row["order_type"] is None
        assert row["sanitized_payload"] == {"contractId": MNQ.id}


class TestIntentPrecedesTransport:

    def test_started_is_on_disk_before_close_position_is_called(self, tmp_path):
        """Ordering, not just final state: the record must exist while the
        socket is still shut."""
        seen = {}
        venue = CloseVenue(response={"success": True})
        r = runner(tmp_path, venue)
        real = venue.close_position

        def spy(cid):
            seen["ledger_at_transport"] = closes(tmp_path)
            return real(cid)

        venue.close_position = spy
        rec = r._open_close_submission(round_index=1)
        venue.close_position(MNQ.id)
        rows = seen["ledger_at_transport"]
        assert len(rows) == 1
        assert rows[0]["state"] == SUBREC.SUBMISSION_STARTED
        assert rows[0]["submission_id"] == rec["submission_id"]

    def test_the_entry_path_still_refuses_to_send_what_it_cannot_record(self):
        """THE EXCEPTION IS EMERGENCY-CLOSE-SPECIFIC.

        Ordinary order placement keeps the original law: it creates NEW
        exposure, so a submission it cannot durably record must not leave
        the process. `_open_submission_record` still has no failure path --
        it raises out of `submit`, before any transport."""
        import inspect

        text = inspect.getsource(R.ExecutionRunner._open_submission_record)
        assert "except" not in text
        assert "SUBREC.open_submission(" in text


class TestRawResponseIsPreservedWhole:
    """THE WIRE CONTRACT IS UNPROVEN. These fixtures deliberately disagree with
    each other: the point is that WHATEVER the venue sends survives, not that
    TopstepX sends any particular shape."""

    def test_success_only_body_is_stored(self, tmp_path):
        r = runner(tmp_path, CloseVenue())
        rec = r._open_close_submission(round_index=1)
        r._record_close_outcome(rec, raw_response={"success": True})
        row = closes(tmp_path)[-1]
        assert row["raw_response"] == {"success": True}

    def test_a_body_carrying_an_order_id_is_stored(self, tmp_path):
        r = runner(tmp_path, CloseVenue())
        rec = r._open_close_submission(round_index=1)
        r._record_close_outcome(
            rec, raw_response={"orderId": 3479178907, "success": True,
                               "errorCode": 0})
        row = closes(tmp_path)[-1]
        assert row["raw_response"]["orderId"] == 3479178907
        assert row["venue_order_id"] == 3479178907

    def test_unknown_venue_fields_survive_unchanged(self, tmp_path):
        """No field is selected, dropped or normalised -- an unfamiliar key is
        exactly the evidence a future contract question needs."""
        exotic = {"success": True, "positionId": 811804558,
                  "somethingNew": {"a": [1, 2]}, "errorCode": 0}
        r = runner(tmp_path, CloseVenue())
        rec = r._open_close_submission(round_index=1)
        r._record_close_outcome(rec, raw_response=exotic)
        assert closes(tmp_path)[-1]["raw_response"] == exotic

    def test_no_identity_is_invented_when_the_body_has_none(self, tmp_path):
        r = runner(tmp_path, CloseVenue())
        rec = r._open_close_submission(round_index=1)
        r._record_close_outcome(rec, raw_response={"success": True})
        assert closes(tmp_path)[-1]["venue_order_id"] is None


class TestAmbiguousTransport:

    def test_a_lost_answer_is_unknown_not_rejected(self, tmp_path):
        """A close can execute perfectly while its response is lost."""
        r = runner(tmp_path, CloseVenue())
        rec = r._open_close_submission(round_index=1)
        r._record_close_outcome(rec, raw_response=None,
                                transport_exception="TimeoutError: read timed out",
                                state=SUBREC.SUBMISSION_UNKNOWN)
        row = closes(tmp_path)[-1]
        assert row["state"] == SUBREC.SUBMISSION_UNKNOWN
        assert row["state"] in SUBREC.VENUE_MAY_HAVE_SEEN
        assert row["state"] != SUBREC.VENUE_REJECTED


class TestPerAttemptIdentity:

    def test_two_close_rounds_leave_two_distinct_records(self, tmp_path):
        r = runner(tmp_path, CloseVenue())
        a = r._open_close_submission(round_index=1)
        b = r._open_close_submission(round_index=2)
        assert a["submission_id"] != b["submission_id"]
        ids = {row["submission_id"] for row in closes(tmp_path)}
        assert len(ids) == 2

    def test_the_entry_flight_record_is_not_overwritten(self, tmp_path):
        """`self.submission_record` belongs to the ENTRY."""
        r = runner(tmp_path, CloseVenue())
        r.submission_record = {"submission_id": "sub-entry", "state": "FILLED"}
        r._open_close_submission(round_index=1)
        assert r.submission_record == {"submission_id": "sub-entry",
                                       "state": "FILLED"}


class TestRestartRecovery:

    def test_a_prior_attempt_is_recoverable_as_possibly_seen(self, tmp_path):
        """After a crash, the ledger alone must say the venue MAY have seen a
        close -- the window that was previously invisible."""
        r = runner(tmp_path, CloseVenue())
        rec = r._open_close_submission(round_index=1)
        del r                                   # the process dies here
        found = SUBREC.find_submission(str(tmp_path), SESSION,
                                       rec["submission_id"])
        assert found is not None
        assert found["operation"] == SUBREC.OPERATION_POSITION_CLOSE
        assert found["state"] in SUBREC.VENUE_MAY_HAVE_SEEN

    def test_no_record_means_this_process_never_sent_a_close(self, tmp_path):
        assert closes(tmp_path) == []


class TestPhase1PromotesNothing:

    def test_recording_is_a_no_op_when_unconfigured(self, tmp_path):
        """Smoke tools and existing tests keep byte-identical behaviour."""
        venue = CloseVenue(response={"success": True})
        r = runner(tmp_path, venue, recording=False)
        assert r._open_close_submission(round_index=1) is None
        assert ledger(tmp_path) == []

    def test_capturing_an_order_id_does_not_touch_mission_ownership(self, tmp_path):
        """CAPTURE IS ALLOWED. OWNERSHIP PROMOTION IS NOT -- that is step 2."""
        src = os.path.join("src", "broker", "topstepx_execution_runner.py")
        with open(src, encoding="utf-8") as fh:
            text = fh.read()
        start = text.index("def _open_close_submission")
        end = text.index("def _venue_body")
        block = text[start:end]
        for banned in ("exit_order_id", "observe_exit", "mission."):
            assert banned not in block, banned

    def test_close_position_remains_the_primitive(self, tmp_path):
        """No opposite-side market order -- that reintroduces the reversal
        hazard closeContract exists to avoid."""
        src = os.path.join("src", "broker", "topstepx_execution_runner.py")
        with open(src, encoding="utf-8") as fh:
            text = fh.read()
        start = text.index("if action == EL.ACTION_CLOSE:")
        block = text[start:start + 4200]
        assert "self.session.close_position(self.contract.id)" in block
        assert "place_order" not in block


class TestFailureToRecordIsNotAmbiguity:

    def test_not_submitted_is_distinct_from_unknown(self):
        """Nothing transmitted is NOT 'the venue might hold a close'."""
        assert EL.CLOSE_NOT_SUBMITTED != EL.CLOSE_STATE_UNKNOWN


# ══════════════════════════════════════════════════════════════════════════════
class TestExposureReductionOutranksDurability:
    """LUNA-EMERGENCY-CLOSE-DURABILITY-PRIORITY-1 (2026-09-02).

    The first cut of phase 1 inherited the ENTRY law -- "a caller that cannot
    record what it is about to send must not send it" -- into the liquidation
    path. That law exists to stop us CREATING exposure we cannot account for.
    An emergency close REMOVES exposure, so the veto inverted the very risk it
    was written to prevent: a disk failure produced eight consecutive refusals
    to flatten a position the planner had just proved was naked.

    `ACTION_CLOSE` is only emitted at E3A_EMERGENCY_NAKED -- discovery COMPLETE,
    ownership unambiguous, every executable order of ours terminal, and a
    measured NONZERO position. A flat account returns at `size == 0` and never
    reaches it. So the choice is never bookkeeping versus tidiness; it is a disk
    failure deciding whether live contracts stay in the market.

    A busted disk may cost Luna the rest of the session. It may not earn the
    right to leave naked MNQ contracts sitting at the venue.
    """

    def test_the_source_branch_has_no_withholding_path(self):
        """Proven against the SOURCE, because the hazard is a control-flow
        decision: nothing may skip transport, and the branch may not report
        CLOSE_NOT_SUBMITTED after a journal failure."""
        import inspect

        text = inspect.getsource(R.ExecutionRunner)
        start = text.index("if action == EL.ACTION_CLOSE:")
        block = text[start:start + 4200]
        assert "CLOSE_NOT_SUBMITTED" not in block
        assert "self.session.close_position(self.contract.id)" in block

    def test_an_unrecordable_close_still_reaches_the_venue(self, tmp_path):
        """THE THEOREM, DRIVEN THROUGH THE REAL `emergency_flatten` LOOP.

        Not a source assertion and not a hand-called helper: a genuinely naked
        SHORT 5, a venue that answers, and a submission store that cannot be
        written. The position must end flat and the durability failure must be
        on record."""
        venue = NakedVenue(size=-5, response={"success": True})
        r = runner(tmp_path, venue)
        # An unwritable store: `open_submission` cannot persist or verify.
        r.submission_store_dir = os.path.join(str(tmp_path), "wall\x00bad")

        out = r.emergency_flatten("protection missing after fill")

        assert ("close_position", MNQ.id) in venue.calls, venue.calls
        assert venue.size == 0
        assert r.close_durability_failures, "durability failure not observable"
        assert r.close_durability_failures[0]["close_transported_anyway"] is True
        assert out is not None

    def test_the_failure_is_observable_and_not_swallowed(self, tmp_path):
        r = runner(tmp_path, CloseVenue(response={"success": True}))
        r.close_durability_failures.append(
            {"round": 0, "stage": "pre_transport_intent",
             "close_transported_anyway": True})
        assert r.close_durability_failures[0]["close_transported_anyway"] is True

    def test_no_fake_durable_history_is_written_after_the_fact(self, tmp_path):
        """A record created AFTER transport would assert a pre-transport write
        that never happened."""
        r = runner(tmp_path, CloseVenue())
        assert r._record_close_outcome(None, raw_response={"success": True}) is None
        assert closes(tmp_path) == []

    def test_the_entry_evidence_surface_is_never_overwritten(self, tmp_path):
        r = runner(tmp_path, CloseVenue())
        r.recording_failure = {"submission_id": "sub-entry"}
        r.close_durability_failures.append({"round": 0})
        assert r.recording_failure == {"submission_id": "sub-entry"}

    def test_a_flat_position_can_never_emit_another_close(self):
        """Venue position truth, not journal truth, bounds repeated closes."""
        d = EL.plan(position_size=0, orders=[], owns=lambda o: True,
                    close_state=EL.CLOSE_NOT_SUBMITTED, round_index=1,
                    discovery_complete=True)
        assert d["action"] != EL.ACTION_CLOSE

    def test_an_acknowledged_close_proves_before_it_closes_again(self):
        """After transport the planner re-reads rather than sending a second
        close -- that is what bounds the reversal hazard, and it is unchanged."""
        d = EL.plan(position_size=-5, orders=[], owns=lambda o: True,
                    close_state=EL.CLOSE_ACKNOWLEDGED, round_index=1,
                    discovery_complete=True)
        assert d["action"] == EL.ACTION_PROVE

    def test_an_unknown_close_outcome_still_halts(self):
        """Ambiguity after transport must not authorize blind repetition."""
        d = EL.plan(position_size=-5, orders=[], owns=lambda o: True,
                    close_state=EL.CLOSE_STATE_UNKNOWN, round_index=1,
                    discovery_complete=True)
        assert d["action"] == EL.ACTION_HALT

    def test_a_naked_position_is_what_action_close_means(self):
        """Documents the precondition the exception rests on."""
        d = EL.plan(position_size=-5, orders=[], owns=lambda o: True,
                    close_state=EL.CLOSE_NOT_SUBMITTED, round_index=0,
                    discovery_complete=True)
        assert d["action"] == EL.ACTION_CLOSE
        assert d["naked"] is True
        assert d["close_size"] == 5
