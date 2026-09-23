"""ACK-DISPLAY-1 — one acknowledgement is one ACK row; the rest are evidence.

PROD-20260922 filled one entry and the flight recorder held six rows for it:
one SUBMISSION_STARTED and five reading VENUE_ACKNOWLEDGED, all carrying the
same venue order id. That was escalated to the owner as a suspected duplicate
write.

It was not a duplicate. `record_establishment` deliberately PRESERVES the
submission state -- post-fill evidence describes what happened AFTER the venue
answered and must never invent a new answer to whether the venue saw the entry
-- so a successful entry writes:

    VENUE_ACKNOWLEDGED                                    (the submit path)
    VENUE_ACKNOWLEDGED + POST_FILL_AUTHORIZED             (establishment)
    VENUE_ACKNOWLEDGED + STRUCTURAL_STOP_PROVEN           (establishment)
    VENUE_ACKNOWLEDGED + STRUCTURAL_PROTECTION_VERIFIED   (establishment)
    VENUE_ACKNOWLEDGED + STRUCTURAL_BASELINE_ARMED        (establishment)

Five rows, five different facts, one acknowledgement.

The ledger was always truthful. The session outcome report's projection of it
was not: it dropped `post_fill_establishment`, which is the only field that
tells the rows apart, so five facts printed as one fact written five times.
These tests exercise the REAL writers, then assert the report can distinguish
what they wrote.

NOTHING HERE TOUCHES EXECUTION. The finding is observability and so is the
repair.
"""
from __future__ import annotations

import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "src"))

from broker import topstepx_submission_record as SUB                # noqa: E402

sys.path.insert(0, os.path.join(ROOT, "tools"))
from topstepx_session_outcome_report import submissions             # noqa: E402

SESSION = "PROD-TESTACK"
ACK_BODY = {"orderId": 3555166672, "success": True, "errorCode": 0,
            "errorMessage": None}

SUCCESS_PATH_STAGES = (
    SUB.ESTABLISHMENT_AUTHORIZED,
    SUB.ESTABLISHMENT_STOP_PROVEN,
    SUB.ESTABLISHMENT_PROTECTION_VERIFIED,
    SUB.ESTABLISHMENT_COMPLETE,
)


@pytest.fixture()
def ledger(tmp_path):
    """One filled entry, written by the production writers themselves."""
    store = str(tmp_path)
    opened = SUB.open_submission(
        store_dir=store, session_id=SESSION, mission_id="PROD-TESTACK-T1",
        payload={"accountId": 1, "size": 6}, custom_tag="EXPBOT-test",
        contract_id="CON.F.US.MNQ.Z26", symbol="MNQZ6")
    acked = SUB.record_response(store_dir=store, session_id=SESSION,
                                submission=opened, raw_response=ACK_BODY)
    assert acked["state"] == SUB.VENUE_ACKNOWLEDGED
    for index, stage in enumerate(SUCCESS_PATH_STAGES):
        SUB.record_establishment(store_dir=store, session_id=SESSION,
                                 submission=acked, stage=stage,
                                 evidence={"step": index})
    return store


class TestWhatTheWritersActuallyProduce:

    def test_one_entry_produces_six_rows(self, ledger):
        assert submissions(ledger, SESSION)["count"] == 6

    def test_five_of_them_read_venue_acknowledged(self, ledger):
        states = submissions(ledger, SESSION)["states"]
        assert states[SUB.VENUE_ACKNOWLEDGED] == 5
        assert states[SUB.SUBMISSION_STARTED] == 1

    def test_they_all_carry_the_same_single_order_id(self, ledger):
        ids = {r["venue_order_id"] for r in submissions(ledger, SESSION)["rows"]
               if r["venue_order_id"] is not None}
        assert ids == {3555166672}, "one acknowledgement, one order id"


class TestOneAcknowledgementIsOneAcknowledgement:
    """The proof the owner asked for."""

    def _acks(self, store):
        return [r for r in submissions(store, SESSION)["rows"]
                if r["state"] == SUB.VENUE_ACKNOWLEDGED]

    def test_exactly_one_ack_row_is_the_acknowledgement_itself(self, ledger):
        bare = [r for r in self._acks(ledger) if not r.get("establishment")]
        assert len(bare) == 1, (
            "more than one row claims to BE the venue's acknowledgement")

    def test_every_other_ack_row_names_its_establishment_stage(self, ledger):
        staged = [r["establishment"] for r in self._acks(ledger)
                  if r.get("establishment")]
        assert len(staged) == 4
        assert staged == list(SUCCESS_PATH_STAGES)

    def test_no_two_rows_are_actually_identical(self, ledger):
        """THE REGRESSION. They only looked identical because the projection
        dropped the field that distinguishes them."""
        fingerprints = [(r["state"], r.get("establishment"))
                        for r in self._acks(ledger)]
        assert len(set(fingerprints)) == len(fingerprints)


class TestTheReportCanNowTellThemApart:

    def test_the_establishment_stage_survives_into_the_projection(self, ledger):
        rows = submissions(ledger, SESSION)["rows"]
        assert any(r.get("establishment") for r in rows), (
            "post_fill_establishment is dropped again; the rows are "
            "indistinguishable and a false duplicate-write alarm is back")

    def test_a_plain_acknowledgement_reports_no_stage(self, tmp_path):
        """A submission that never fills must not grow a phantom stage."""
        store = str(tmp_path)
        opened = SUB.open_submission(
            store_dir=store, session_id=SESSION, mission_id="M",
            payload={"accountId": 1}, custom_tag="t")
        SUB.record_response(store_dir=store, session_id=SESSION,
                            submission=opened, raw_response=ACK_BODY)
        rows = submissions(store, SESSION)["rows"]
        assert [r.get("establishment") for r in rows] == [None, None]


class TestIdempotenceIsNotWeakened:
    """Repairing the DISPLAY may not change what the recorder keeps."""

    def test_repeating_an_identical_stage_appends_nothing(self, ledger):
        before = submissions(ledger, SESSION)["count"]
        sid = submissions(ledger, SESSION)["rows"][0]["submission_id"]
        acked = SUB.find_submission(ledger, SESSION, sid)
        SUB.record_establishment(store_dir=ledger, session_id=SESSION,
                                 submission=acked,
                                 stage=SUB.ESTABLISHMENT_COMPLETE,
                                 evidence={"step": 3})
        assert submissions(ledger, SESSION)["count"] == before

    def test_a_new_stage_still_appends(self, ledger):
        before = submissions(ledger, SESSION)["count"]
        sid = submissions(ledger, SESSION)["rows"][0]["submission_id"]
        acked = SUB.find_submission(ledger, SESSION, sid)
        SUB.record_establishment(store_dir=ledger, session_id=SESSION,
                                 submission=acked,
                                 stage=SUB.ESTABLISHMENT_COMPLETE,
                                 evidence={"step": "different"})
        assert submissions(ledger, SESSION)["count"] == before + 1
