"""SESSION-CONTAMINATION-1 adversarial proof.

No broker, provider, or network. These tests join the durable bot close intent
to venue trade/reconciliation evidence and prove terminal contamination stops
paid cognition while per-tick safety work continues.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
import os
import sys
from types import SimpleNamespace

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))

from broker import daily_loss_budget as DLB
from broker import topstepx_close_attribution as CLOSEATTR
from broker import topstepx_execution_runner as RUNNER
from broker import topstepx_mission_reconciler as RECON
from broker import topstepx_mission_state as MS
from broker import topstepx_production_loop as PL
from broker import topstepx_session_cognition_lock as COGNITION_LOCK
from broker import topstepx_submission_record as SUBREC
from broker.topstepx_client import TopstepXContract


CID = "CON.F.US.MNQ.U26"
FP = "acct:session-contamination-test"
SESSION = "PRAC-20261002-CLOSE"
MISSION_ID = f"{SESSION}-T2"
ENTRY_ID = 81001
CLOSE_ID = 81002


def _mission(tmp_path, *, session_id=SESSION):
    m = MS.open_mission(
        path=str(tmp_path / f"{MISSION_ID}.json"), mission_id=MISSION_ID,
        account_fingerprint=FP, contract_id=CID,
        authorization_fingerprint="auth:test")
    m.consume_attempt(candidate_fingerprint="candidate:test",
                      token_id="token:test")
    m.record_venue_acknowledgement(
        venue_order_id=ENTRY_ID, session_id=session_id)
    m.observe_position_open(filled_quantity=2, fill_price=100.0,
                            protective_order_ids=[], evidence="fixture position")
    return m


def _close_record(tmp_path, mission, *, close_id=None, success=True,
                  intent_overrides=None):
    intent = {
        "schema": "emergency_close_intent.v1",
        "entry_order_id": ENTRY_ID,
        "pre_close_signed_position": -2,
        "requested_quantity": 2,
        "requested_side": "buy",
        "reason": "post-fill authorization refused",
    }
    intent.update(intent_overrides or {})
    row = SUBREC.open_submission(
        store_dir=str(tmp_path), session_id=mission.session_id,
        mission_id=mission.mission_id,
        payload={"contractId": CID}, custom_tag="", token_id="token:test",
        authorization_fingerprint="auth:test", account_fingerprint=FP,
        contract_id=CID,
        geometry={"emergency_close_round": 1, "emergency_close": intent},
        operation=SUBREC.OPERATION_POSITION_CLOSE)
    raw = {"success": success}
    if close_id is not None:
        raw["orderId"] = close_id
    return SUBREC.record_response(
        store_dir=str(tmp_path), session_id=mission.session_id,
        submission=row, raw_response=raw)


def _record_flat_confirmation(tmp_path, mission, row, *, flat=True,
                              foreign_same_contract=None):
    response_at = datetime.fromisoformat(row["response_at_utc"])
    observed_at = response_at + timedelta(seconds=2)
    SUBREC.record_reconciliation(
        store_dir=str(tmp_path), session_id=mission.session_id,
        submission=row, state=row["state"], reconciliation={
            "close_flat_confirmation": {
                "schema": CLOSEATTR.SCHEMA,
                "close_submission_id": row["submission_id"],
                "session_id": mission.session_id,
                "mission_id": mission.mission_id,
                "account_fingerprint": FP,
                "contract_id": CID,
                "flat_confirmed": flat,
                "safe_terminal": True,
                "orders_complete": True,
                "all_positions_flat": flat,
                "contract_position_size": 0 if flat else -1,
                "mission_working_orders": [],
                "unaccounted_same_contract": list(foreign_same_contract or []),
                "observed_at_utc": observed_at.isoformat(),
            }
        })
    return observed_at


def _trade(order_id, created, *, side, size=2, price=101.25,
           contract=CID, pnl=None):
    return {"orderId": order_id, "contractId": contract,
            "creationTimestamp": created.isoformat(), "side": side,
            "size": size, "price": price, "profitAndLoss": pnl,
            "fees": 0.72, "commissions": 0.50, "voided": False}


class _Venue:
    def __init__(self, *, trades, all_orders=()):
        self.trades = list(trades)
        self.all_orders = list(all_orders)

    def open_positions(self):
        return []

    def open_orders(self):
        return []

    def query_orders(self, *, statuses=None, contract_id=None):
        return [row for row in self.all_orders
                if contract_id is None or row.get("contract_id") == contract_id]

    def recent_trades(self, since=None):
        return list(self.trades)


def _close_order(order_id=CLOSE_ID, *, side=0, size=2):
    return {"id": order_id, "contract_id": CID, "status": 2,
            "type": 2, "side": side, "size": size}


def _entry_trade():
    # It predates the close request and is already owned by mission entry id.
    return {"orderId": ENTRY_ID, "contractId": CID,
            "creationTimestamp": "2026-10-02T13:00:00+00:00",
            "side": 1, "size": 2, "price": 100.0,
            "profitAndLoss": None, "fees": 0.72, "commissions": 0.50}


def _close_trade_after(row, observed_at, *, order_id=CLOSE_ID, side=0,
                       size=2, price=101.25):
    response_at = datetime.fromisoformat(row["response_at_utc"])
    created = response_at + timedelta(seconds=1)
    assert created < observed_at
    return _trade(order_id, created, side=side, size=size, price=price, pnl=2.5)


@pytest.mark.parametrize("response_order_id", [None, CLOSE_ID])
def test_bot_close_is_attributed_from_exact_intent_fill_and_flat_proof(
        tmp_path, response_order_id):
    m = _mission(tmp_path)
    row = _close_record(tmp_path, m, close_id=response_order_id)
    observed_at = _record_flat_confirmation(tmp_path, m, row)
    venue = _Venue(trades=[_entry_trade(),
                           _close_trade_after(row, observed_at)],
                   all_orders=[_close_order()])

    result = RECON.MissionReconciler(venue=venue, contract_id=CID).reconcile(m)

    assert result["state"] == MS.COMPLETE
    assert m.exit_order_id == CLOSE_ID
    assert m.exit_price == pytest.approx(101.25)
    assert m.exit_type == RECON.EXIT_UNCLASSIFIED
    latest = SUBREC.find_submission(str(tmp_path), SESSION, row["submission_id"])
    assert latest["reconciliation"]["close_attribution"]["status"] == CLOSEATTR.PROVEN
    # The recovered close ID joins the existing governor's owned-order set.
    budget = DLB.compute(
        budget_usd=725, orders=[{"id": ENTRY_ID, "contract_id": CID},
                                _close_order()],
        trades=[_entry_trade(), _close_trade_after(row, observed_at)],
        missions=[m], contract_id=CID,
        session_start="2000-01-01T00:00:00+00:00", max_risk_usd=350)
    assert budget["state"] == DLB.OK
    assert budget["attributed_trades"] == 2
    assert budget["owned_order_ids"] == [str(ENTRY_ID), str(CLOSE_ID)]


def test_prod_shape_emergency_flatten_response_without_id_reconciles_cleanly(
        tmp_path):
    """Drive closeContract through the real emergency-flatten executor, then
    prove the resulting venue fill prevents a false governor contamination."""
    contract = TopstepXContract(id=CID, name="MNQU6", description="",
                                tick_size=0.25, tick_value=0.5, active=True)

    class FlattenVenue(_Venue):
        def __init__(self):
            super().__init__(trades=[_entry_trade()])
            self.position_size = -2
            self.close_calls = 0

        def open_positions(self):
            if self.position_size == 0:
                return []
            return [{"id": 1, "contract_id": CID, "type": 2,
                     "size": abs(self.position_size), "avg_price": 100.0}]

        def query_orders(self, *, statuses=None, contract_id=None):
            return [row for row in self.all_orders
                    if contract_id is None or row.get("contract_id") == contract_id]

        def close_position(self, contract_id):
            assert contract_id == CID
            assert self.position_size == -2
            self.close_calls += 1
            self.position_size = 0
            created = datetime.now(timezone.utc)
            self.trades.append(_trade(CLOSE_ID, created, side=0, size=2,
                                      price=101.25, pnl=2.5))
            self.all_orders.append(_close_order())
            return {"success": True}  # production incident: no order id

    venue = FlattenVenue()
    m = _mission(tmp_path)
    runner = object.__new__(RUNNER.ExecutionRunner)
    runner.session = venue
    runner.contract = contract
    runner.token = None
    runner.geometry = None
    runner.recording_failure = None
    runner.close_durability_failures = []
    runner.transitions = []
    runner.state = RUNNER.DISARMED
    runner.clock = lambda: datetime.now(timezone.utc)
    runner.mission_owns_order = lambda _order: True
    runner.entry_capture = None
    runner.order_id = ENTRY_ID
    runner.submission_record = None
    runner.account_fingerprint = FP
    runner.submission_mission_id = MISSION_ID
    runner.submission_authorization_fingerprint = "auth:test"
    runner.submission_store_dir = str(tmp_path)
    runner.submission_session_id = SESSION

    flattened = runner.emergency_flatten("post-fill economics refused")

    assert venue.close_calls == 1
    assert flattened["flattened"] is True
    close_rows = [row for row in SUBREC.latest_by_submission(
        str(tmp_path), SESSION, MISSION_ID).values()
        if row.get("operation") == SUBREC.OPERATION_POSITION_CLOSE]
    assert len(close_rows) == 1
    row = close_rows[0]
    intent = row["geometry"]["emergency_close"]
    assert row["raw_response"] == {"success": True}
    assert row["venue_order_id"] is None
    assert intent["entry_order_id"] == ENTRY_ID
    assert intent["pre_close_signed_position"] == -2
    assert intent["requested_quantity"] == 2
    assert intent["requested_side"] in ("0", "buy")
    assert row["reconciliation"]["close_flat_confirmation"]["flat_confirmed"] is True

    reconciled = RECON.MissionReconciler(venue=venue, contract_id=CID).reconcile(m)
    assert reconciled["state"] == MS.COMPLETE
    assert m.exit_order_id == CLOSE_ID
    assert m.exit_price == pytest.approx(101.25)
    budget = DLB.compute(
        budget_usd=725,
        orders=[{"id": ENTRY_ID, "contract_id": CID}, _close_order()],
        trades=venue.trades, missions=[m], contract_id=CID,
        session_start="2000-01-01T00:00:00+00:00", max_risk_usd=350)
    assert budget["state"] == DLB.OK
    assert budget["attributed_trades"] == 2


@pytest.mark.parametrize("evidence_case", [
    "flat_only", "wrong_side", "wrong_quantity", "conflicting_same_contract_order",
])
def test_ambiguous_or_conflicting_close_evidence_remains_fail_closed(
        tmp_path, evidence_case):
    m = _mission(tmp_path)
    row = _close_record(tmp_path, m)
    observed_at = _record_flat_confirmation(
        tmp_path, m, row,
        foreign_same_contract=[99999] if evidence_case == "conflicting_same_contract_order" else [])
    trades = [_entry_trade()]
    orders = [_close_order()]
    if evidence_case != "flat_only":
        trades.append(_close_trade_after(
            row, observed_at,
            side=1 if evidence_case == "wrong_side" else 0,
            size=1 if evidence_case == "wrong_quantity" else 2))
    venue = _Venue(trades=trades, all_orders=orders)

    result = RECON.MissionReconciler(venue=venue, contract_id=CID).reconcile(m)

    assert result["state"] == MS.EXIT_PENDING_RECONCILIATION
    assert m.exit_order_id is None
    assert m.exit_type == RECON.EXIT_UNATTRIBUTED
    assert CLOSEATTR.has_unresolved_bot_close(
        submissions=CLOSEATTR.mission_close_submissions(m), mission=m,
        contract_id=CID)


def test_external_trade_without_bot_close_provenance_still_contaminates():
    class MinimalMission:
        mission_id = "M"
        order_id = ENTRY_ID
        exit_order_id = ENTRY_ID
        protective_order_ids = []
        token_id = "token:test"
        custom_tag = ""

    result = DLB.compute(
        budget_usd=725, orders=[{"id": ENTRY_ID, "contract_id": CID}],
        trades=[{"order_id": ENTRY_ID, "created": "2026-10-02T13:01:00+00:00",
                  "pnl": None},
                {"order_id": 99999, "created": "2026-10-02T13:02:00+00:00",
                 "pnl": -1}],
        missions=[MinimalMission()], contract_id=CID,
        session_start="2000-01-01T00:00:00+00:00", max_risk_usd=350)
    assert result["state"] == DLB.CONTAMINATED
    assert result["reason"] == DLB.UNOWNED_TRADE


def test_wrong_response_order_id_cannot_be_replaced_by_another_trade(tmp_path):
    m = _mission(tmp_path)
    row = _close_record(tmp_path, m, close_id=88008)
    observed_at = _record_flat_confirmation(tmp_path, m, row)
    result = CLOSEATTR.prove_emergency_close_attribution(
        submissions=CLOSEATTR.mission_close_submissions(m),
        trades=[_close_trade_after(row, observed_at, order_id=CLOSE_ID)],
        mission=m, contract_id=CID, orders=[_close_order()])
    assert result["status"] == CLOSEATTR.UNKNOWN
    assert result["reason"] == "response_and_trade_order_identity_mismatch"


def test_restart_reconciliation_can_prove_flat_from_current_complete_venue_reads(
        tmp_path):
    """The append-only flat record is useful, but a restart may reconstruct
    the same fact from today's complete venue position/order answers."""
    m = _mission(tmp_path)
    row = _close_record(tmp_path, m)
    response_at = datetime.fromisoformat(row["response_at_utc"])
    observed_at = response_at + timedelta(seconds=2)
    venue = _Venue(trades=[_entry_trade(),
                           _close_trade_after(row, observed_at)],
                   all_orders=[_close_order()])

    result = RECON.MissionReconciler(
        venue=venue, contract_id=CID,
        clock=lambda: observed_at).reconcile(m)

    assert result["state"] == MS.COMPLETE
    assert m.exit_order_id == CLOSE_ID
    latest = SUBREC.find_submission(str(tmp_path), SESSION, row["submission_id"])
    assert latest["reconciliation"]["close_attribution"]["status"] == CLOSEATTR.PROVEN


def test_genuine_terminal_contamination_stops_cognition_but_keeps_safety_ticks(
        tmp_path, monkeypatch):
    calls = {"reconcile": 0, "manage": 0, "brain": 0, "cycle": 0,
             "candles": 0, "governor": 0}

    class Cycle:
        def scan(self, *args, **kwargs):
            calls["cycle"] += 1
            calls["brain"] += 1

    class Candles:
        def __init__(self):
            self.cleared_plans = []
            self.wake_registry = SimpleNamespace(
                clear_conditional_watch=lambda **kwargs:
                self.cleared_plans.append(kwargs.get("plan_id")))

        def fetch_1m_candles(self, *args, **kwargs):
            calls["candles"] += 1
            return []

    def build_loop(session_id=SESSION):
        loop = PL.ProductionLoop.__new__(PL.ProductionLoop)
        auth = SimpleNamespace(session_id=session_id, maximum_trades=10)
        owner = SimpleNamespace(store_dir=str(tmp_path), authorization=auth,
                                trade_missions=[], active_mission=None)
        loop.mission = owner
        loop.ps = SimpleNamespace(
            account_fingerprint=FP, contract=SimpleNamespace(id=CID),
            session=object())
        loop.clock = lambda: datetime.now(timezone.utc)
        loop.reconcile_missions = lambda: calls.__setitem__(
            "reconcile", calls["reconcile"] + 1)
        loop.manage_open_position = lambda: calls.__setitem__(
            "manage", calls["manage"] + 1)
        loop.cycle = Cycle()
        loop.candles = Candles()
        loop.active_conditional_plan = {"plan_id": "plan:test"}
        loop.active_candidate = None
        loop._terminal_cognition = None
        return loop

    monkeypatch.setattr(PL.LIFECYCLE, "entry_authority_exhausted",
                        lambda _mission: False)

    def contaminated(**kwargs):
        calls["governor"] += 1
        return {"state": DLB.CONTAMINATED, "entry_permitted": False,
                "reason": DLB.UNOWNED_TRADE}

    monkeypatch.setattr(PL.DLB, "resolve", contaminated)
    first = build_loop()
    out = first._scan_once()
    assert out["outcome"] == PL.TRADING_COGNITION_OFF
    assert out["reason"] == DLB.UNOWNED_TRADE
    assert out["provider_call_suppressed"] is True
    assert out["safety_reconciliation_continues"] is True
    assert first.active_conditional_plan is None
    assert first.active_candidate is None
    assert first.candles.cleared_plans == ["plan:test"]
    assert calls == {"reconcile": 1, "manage": 1, "brain": 0, "cycle": 0,
                     "candles": 0, "governor": 1}

    # New process, venue now flat: the session lock remains terminal and the
    # deterministic safety/reconciliation reads continue without DLB/Brain.
    def unexpected_governor(**kwargs):
        raise AssertionError("persisted contamination must short-circuit cognition")

    monkeypatch.setattr(PL.DLB, "resolve", unexpected_governor)
    restarted = build_loop()
    out = restarted._scan_once()
    assert out["outcome"] == PL.TRADING_COGNITION_OFF
    assert out["reason"] == DLB.UNOWNED_TRADE
    assert restarted.active_conditional_plan is None
    assert restarted.candles.cleared_plans == ["plan:test"]
    assert calls["reconcile"] == calls["manage"] == 2
    assert calls["brain"] == calls["cycle"] == calls["candles"] == 0
    assert calls["governor"] == 1


def test_cognition_lock_is_scoped_to_one_session_not_cleared_by_flat(tmp_path):
    lock = COGNITION_LOCK.record_contaminated(
        store_dir=str(tmp_path), session_id=SESSION,
        account_fingerprint=FP, contract_id=CID,
        reason=DLB.UNOWNED_TRADE)
    assert lock["state"] == DLB.CONTAMINATED
    assert COGNITION_LOCK.load(
        store_dir=str(tmp_path), session_id=SESSION,
        account_fingerprint=FP, contract_id=CID)["terminal"] is True
    # A new authorized session has a distinct namespace and follows the
    # existing reset boundary; flatness itself did not erase the prior lock.
    assert COGNITION_LOCK.load(
        store_dir=str(tmp_path), session_id=f"{SESSION}-NEXT",
        account_fingerprint=FP, contract_id=CID) is None
