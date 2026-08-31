"""PROD-20260810 — restoring a trade spent by an internal abort.

The allowance is two BOT TRADES. Scan 2 spent one on a stale token binding that
never reached Topstep. These tests pin the only safe way to give it back: an
additive ledger, re-verified on every load, that never touches the record of
what actually happened.
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
from broker.topstepx_session_authorization import (         # noqa: E402
    AuthorizationRefused, ProductionSessionMission, SessionAuthorization)

SESSION = "PROD-TEST"
FINGERPRINT = "acct:test"
CONTRACT = "CON.F.US.MNQ.U26"
FLAT = {"open_positions": 0, "working_orders": 0, "fills_today": 0}
OPEN_ARGS = dict(positions=0, working_orders=0, unknown_external=False,
                 in_window=True)


@pytest.fixture
def store(tmp_path):
    return str(tmp_path)


def session_mission(store):
    auth = SessionAuthorization(
        session_id=SESSION, account_fingerprint=FINGERPRINT,
        contract_id=CONTRACT, session_date="2026-08-10",
        decision_window="09:30-14:00 America/New_York",
        # LUNA-DAILY-LOSS-BUDGET-GOVERNOR-1: signed so recovery still
        # exercises a valid authorization.
        daily_loss_budget_usd=SessionAuthorization.__dataclass_fields__[
            "daily_loss_budget_usd"].default or 725.00)
    auth.authorization_fingerprint = "auth:test"
    sm = ProductionSessionMission(authorization=auth, store_dir=store)
    sm.load_existing()
    return sm


def aborted_mission(store, index=1):
    """A mission in exactly the shape scan 2 left behind."""
    sm = session_mission(store)
    mission = sm.open_trade_mission(**OPEN_ARGS)
    mission.consume_attempt(candidate_fingerprint="cand:abc", token_id="tok:abc")
    assert mission.state == MS.ATTEMPT_CONSUMED
    assert mission.order_id is None and mission.token_spent is False
    return sm, mission


def void(store, sm, index=1, mission=None, **over):
    kwargs = dict(store_dir=store, session_id=SESSION, mission_index=index,
                  mission=mission or sm.trade_missions[index - 1],
                  phrase=RECOVERY.VOID_PHRASE,
                  reason="stale smoke stop ceiling; zero orders placed",
                  venue_evidence=dict(FLAT))
    kwargs.update(over)
    return RECOVERY.record_void(**kwargs)


# ══════════════════════════════════════════════════════════════════════════════
class TestTheAbortIsVoidable:

    def test_the_live_shape_proves_it_never_reached_the_venue(self, store):
        """CONTRACT CHANGED 2026-08-11 (V13). This asserted that an empty
        mission-id-only search PROVES non-delivery. That is the defect: on
        PROD-20260811-V13 the mission was `...-V13-T1`, the ledger row said
        `...-V13`, and the file was named for a retired session, so the search
        returned zero rows for a trade that had really filled -- and every
        other check passes for a stopped-out position. Proof now requires the
        token id, which `open_submission` stamps BEFORE the socket opens.
        """
        _, mission = aborted_mission(store)
        weak = RECOVERY.submission_evidence_for(store, SESSION, mission.mission_id)
        ok, reasons = RECOVERY.never_reached_venue(mission, submission_evidence=weak)
        assert not ok, "an empty weak-key search must never prove non-delivery"
        assert any("too weak" in r for r in reasons)

        strong = RECOVERY.submission_evidence_for(
            store, SESSION, mission.mission_id, token_id=mission.token_id)
        ok, reasons = RECOVERY.never_reached_venue(mission, submission_evidence=strong)
        assert ok and reasons == []

    def test_without_consulting_the_ledger_the_answer_is_always_no(self, store):
        """PROD-20260810: the mission record alone can never prove non-delivery."""
        _, mission = aborted_mission(store)
        ok, reasons = RECOVERY.never_reached_venue(mission)
        assert ok is False
        assert any("ledger was not consulted" in r for r in reasons)

    def test_voiding_restores_the_second_trade(self, store):
        sm, _ = aborted_mission(store)
        assert sm.trades_used() == 1
        assert sm.may_open_trade_mission(**OPEN_ARGS)[0] is False

        void(store, sm)
        sm.load_existing()

        assert sm.trades_used() == 0
        assert len(sm.voided_missions) == 1
        assert sm.may_open_trade_mission(**OPEN_ARGS)[0] is True
        # capacity is 2 again, not 1: the abort was never a trade
        assert sm.authorization.maximum_trades - sm.trades_used() == 2

    def test_the_attempt_history_is_still_counted_honestly(self, store):
        sm, _ = aborted_mission(store)
        void(store, sm)
        sm.load_existing()
        assert sm.entry_attempt_count == 1, "the attempt happened; only the " \
                                            "allowance was restored"
        assert sm.counters()["trade_missions_voided"] == 1
        assert sm.counters()["void_classes"] == [RECOVERY.INFRASTRUCTURE_ABORT]


class TestTheEvidenceSurvives:

    def test_the_mission_file_is_byte_for_byte_unchanged(self, store):
        sm, _ = aborted_mission(store)
        path = sm.mission_path(1)
        before = open(path, "rb").read()
        void(store, sm)
        sm.load_existing()
        sm.open_trade_mission(**OPEN_ARGS)
        assert open(path, "rb").read() == before, "history was rewritten"

    def test_the_replacement_opens_beside_it_not_on_top_of_it(self, store):
        sm, _ = aborted_mission(store)
        void(store, sm)
        sm.load_existing()
        assert sm.next_mission_index() == 2
        replacement = sm.open_trade_mission(**OPEN_ARGS)
        assert os.path.exists(sm.mission_path(1))
        assert os.path.exists(sm.mission_path(2))
        assert replacement.mission_id.endswith("-T2")
        assert MS.load(sm.mission_path(1)).state == MS.ATTEMPT_CONSUMED

    def test_the_ledger_names_what_it_excused(self, store):
        sm, mission = aborted_mission(store)
        void(store, sm)
        entry = json.load(open(RECOVERY.void_ledger_path(store, SESSION),
                               encoding="utf-8"))["voids"][0]
        assert entry["mission_id"] == mission.mission_id
        assert entry["void_class"] == RECOVERY.INFRASTRUCTURE_ABORT
        assert entry["mission_order_id"] is None
        assert entry["mission_token_spent"] is False
        assert entry["venue_evidence"]["open_positions"] == 0
        assert entry["reason"]


class TestItRefusesFarMoreOftenThanItAccepts:

    @pytest.mark.parametrize("field,value", [
        ("order_id", "ORD-123"),          # the venue saw it
        ("token_spent", True),            # the token was burned
        ("position_state", "long"),       # something is open
        ("completion_state", "FILLED"),   # it finished as a real trade
    ])
    def test_anything_that_may_have_traded_is_unvoidable(self, store, field, value):
        sm, mission = aborted_mission(store)
        setattr(mission, field, value)
        assert RECOVERY.never_reached_venue(mission)[0] is False
        with pytest.raises(RECOVERY.VoidRefused, match="MAY_HAVE_REACHED_VENUE"):
            void(store, sm, mission=mission)

    @pytest.mark.parametrize("state", [MS.SUBMIT_UNKNOWN, MS.POSITION_OPEN,
                                       MS.COMPLETE, MS.STATE_UNCERTAIN,
                                       MS.EXIT_PENDING_RECONCILIATION])
    def test_only_a_pre_submission_abort_qualifies(self, store, state):
        sm, mission = aborted_mission(store)
        mission.state = state
        with pytest.raises(RECOVERY.VoidRefused):
            void(store, sm, mission=mission)

    def test_the_operator_phrase_is_required(self, store):
        sm, _ = aborted_mission(store)
        for bad in ("", "yes", RECOVERY.VOID_PHRASE.lower()):
            with pytest.raises(RECOVERY.VoidRefused, match="VOID_PHRASE_MISMATCH"):
                void(store, sm, phrase=bad)

    def test_a_reason_is_required(self, store):
        sm, _ = aborted_mission(store)
        with pytest.raises(RECOVERY.VoidRefused, match="VOID_REASON_REQUIRED"):
            void(store, sm, reason="   ")

    @pytest.mark.parametrize("evidence,match", [
        ({"open_positions": 1, "working_orders": 0}, "VENUE_NOT_FLAT"),
        ({"open_positions": 0, "working_orders": 3}, "VENUE_NOT_FLAT"),
        ({"open_positions": 0, "working_orders": 0, "fills_today": 1},
         "VENUE_SHOWS_FILLS"),
        ({}, "VENUE_NOT_FLAT"),           # absence is not proof of flatness
    ])
    def test_the_venue_must_prove_itself_flat(self, store, evidence, match):
        sm, _ = aborted_mission(store)
        with pytest.raises(RECOVERY.VoidRefused, match=match):
            void(store, sm, venue_evidence=evidence)

    def test_the_same_mission_cannot_be_voided_twice(self, store):
        sm, _ = aborted_mission(store)
        void(store, sm)
        with pytest.raises(RECOVERY.VoidRefused, match="ALREADY_VOIDED"):
            void(store, sm)

    def test_capacity_restoration_is_bounded(self, store):
        """Two voids per session. A repeated abort must run out of session,
        not grind through the account."""
        sm = session_mission(store)
        for _ in range(RECOVERY.MAX_VOIDED_MISSIONS_PER_SESSION):
            sm.load_existing()
            m = sm.open_trade_mission(**OPEN_ARGS)
            m.consume_attempt(candidate_fingerprint="c", token_id="t")
            void(store, sm, index=sm.next_mission_index() - 1, mission=m)
        sm.load_existing()
        m = sm.open_trade_mission(**OPEN_ARGS)
        m.consume_attempt(candidate_fingerprint="c", token_id="t")
        with pytest.raises(RECOVERY.VoidRefused, match="VOID_ALLOWANCE_EXHAUSTED"):
            void(store, sm, index=sm.next_mission_index() - 1, mission=m)
        sm.load_existing()
        assert sm.trades_used() >= 1
        assert sm.may_open_trade_mission(**OPEN_ARGS)[0] is False


class TestTheLedgerIsNeverTrusted:
    """The ledger is a claim. The mission is the evidence. Every load re-checks."""

    def test_a_void_whose_mission_no_longer_verifies_takes_the_trade_back(self, store):
        sm, mission = aborted_mission(store)
        void(store, sm)
        sm.load_existing()
        assert sm.trades_used() == 0            # restored

        # the same mission later turns out to have reached the venue
        mission.order_id = "ORD-999"
        mission.save()

        sm.load_existing()
        assert sm.trades_used() == 1, "the ledger overrode the evidence"
        assert sm.voided_missions == []
        assert sm.may_open_trade_mission(**OPEN_ARGS)[0] is False

    @pytest.mark.parametrize("payload", [
        "{ not json",
        json.dumps({"voids": [{"mission_index": 1,
                               "void_class": "INFRASTRUCTURE_ABORT"}]}),
        json.dumps({"schema_version": "mission_void.v0",
                    "voids": [{"mission_index": 1,
                               "void_class": "INFRASTRUCTURE_ABORT"}]}),
        json.dumps({"schema_version": RECOVERY.VOID_SCHEMA,
                    "voids": [{"mission_index": 1, "void_class": "BECAUSE"}]}),
    ])
    def test_an_unusable_ledger_restores_nothing(self, store, payload):
        sm, _ = aborted_mission(store)
        open(RECOVERY.void_ledger_path(store, SESSION), "w",
             encoding="utf-8").write(payload)
        sm.load_existing()
        assert sm.trades_used() == 1
        assert sm.may_open_trade_mission(**OPEN_ARGS)[0] is False

    def test_a_ledger_naming_a_mission_that_does_not_exist_grants_nothing(self, store):
        sm, _ = aborted_mission(store)
        void(store, sm, index=4, mission=sm.trade_missions[0])
        sm.load_existing()
        assert sm.trades_used() == 1

    def test_more_ledger_rows_than_the_cap_are_truncated_not_honoured(self, store):
        sm, _ = aborted_mission(store)
        rows = [{"mission_index": i, "void_class": RECOVERY.INFRASTRUCTURE_ABORT}
                for i in range(90, 99)] + \
               [{"mission_index": 1, "void_class": RECOVERY.INFRASTRUCTURE_ABORT}]
        json.dump({"schema_version": RECOVERY.VOID_SCHEMA, "session_id": SESSION,
                   "voids": rows},
                  open(RECOVERY.void_ledger_path(store, SESSION), "w",
                       encoding="utf-8"))
        sm.load_existing()
        assert sm.trades_used() == 1, "a padded ledger bought a void past the cap"


class TestTheDoctrineCeilingStillHolds:

    def test_a_void_cannot_raise_the_session_maximum(self, store):
        """Restored capacity is capacity BACK, never capacity ADDED."""
        sm, _ = aborted_mission(store)
        void(store, sm)
        sm.load_existing()
        opened = []
        for _ in range(5):
            try:
                m = sm.open_trade_mission(**OPEN_ARGS)
            except AuthorizationRefused:
                break
            m.consume_attempt(candidate_fingerprint="c", token_id="t")
            m.transition(MS.COMPLETE, "done")
            opened.append(m)
            sm.load_existing()
        assert len(opened) == 2 == sm.authorization.maximum_trades
        assert sm.may_open_trade_mission(**OPEN_ARGS)[0] is False

    def test_the_void_tool_never_writes_to_the_broker(self):
        import ast
        src = open(os.path.join(ROOT, "tools", "topstepx_void_mission.py"),
                   encoding="utf-8").read()
        called = {getattr(n.func, "attr", "") or getattr(n.func, "id", "")
                  for n in ast.walk(ast.parse(src)) if isinstance(n, ast.Call)}
        for forbidden in ("gated_submit", "place_bracket_market_order",
                          "place_order_raw", "submit", "modify_order",
                          "cancel_order", "close_position"):
            assert forbidden not in called, forbidden
