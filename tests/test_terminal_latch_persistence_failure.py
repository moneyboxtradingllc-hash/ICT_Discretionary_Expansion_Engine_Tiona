"""Terminal cognition-contamination latch when its durable write fails.

test_session_contamination_repair covers the persisted latch and the restart
that reads it. This covers the remaining branch of
`ProductionLoop._latch_terminal_contamination`: the governor proves
contamination but `session_cognition_lock.record_contaminated` raises. The
in-memory latch must still stop cognition in this process (no second governor
or Brain consultation), clear the live candidate and conditional plan, and
report the persistence error rather than hide it. A clean governor is the
healthy control. No venue, provider or model is reached.
"""
from __future__ import annotations

from datetime import datetime, timezone
import os
import sys
from types import SimpleNamespace

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))

from broker import daily_loss_budget as DLB  # noqa: E402
from broker import topstepx_production_loop as PL  # noqa: E402
from broker import topstepx_session_cognition_lock as COGNITION_LOCK  # noqa: E402

CID = "CON.F.US.MNQ.U26"
FP = "acct:latch-persistence-test"
SESSION = "PRAC-20261022-LATCH"


def _loop(tmp_path, cleared):
    loop = PL.ProductionLoop.__new__(PL.ProductionLoop)
    auth = SimpleNamespace(session_id=SESSION, maximum_trades=10)
    loop.mission = SimpleNamespace(store_dir=str(tmp_path), authorization=auth, trade_missions=[],
                                   active_mission=None)
    loop.ps = SimpleNamespace(account_fingerprint=FP, contract=SimpleNamespace(id=CID), session=object())
    loop.clock = lambda: datetime(2026, 10, 22, 14, 0, tzinfo=timezone.utc)
    loop.candles = SimpleNamespace(wake_registry=SimpleNamespace(
        clear_conditional_watch=lambda **kwargs: cleared.append(kwargs.get("plan_id"))))
    loop.active_conditional_plan = {"plan_id": "plan:latch"}
    loop.active_candidate = object()
    loop._terminal_cognition = None
    return loop


def _governor(state, calls):
    def resolve(**kwargs):
        calls.append(state)
        return {"state": state, "entry_permitted": state != DLB.CONTAMINATED, "reason": DLB.UNOWNED_TRADE}
    return resolve


def test_clean_governor_leaves_cognition_on(tmp_path, monkeypatch):
    calls, cleared = [], []
    clean = DLB.OK
    monkeypatch.setattr(PL.DLB, "resolve", _governor(clean, calls))
    loop = _loop(tmp_path, cleared)
    assert loop._terminal_contamination_before_cognition() is None
    assert loop._terminal_cognition is None and loop.active_conditional_plan == {"plan_id": "plan:latch"}
    assert COGNITION_LOCK.load(store_dir=str(tmp_path), session_id=SESSION, account_fingerprint=FP,
                               contract_id=CID) is None
    assert calls == [clean] and cleared == []


def test_failed_lock_write_still_latches_this_process_and_reports_the_error(tmp_path, monkeypatch):
    calls, cleared = [], []
    monkeypatch.setattr(PL.DLB, "resolve", _governor(DLB.CONTAMINATED, calls))

    def unwritable(**kwargs):
        raise OSError("store is read-only")

    monkeypatch.setattr(PL.COGNITION_LOCK, "record_contaminated", unwritable)
    loop = _loop(tmp_path, cleared)
    out = loop._terminal_contamination_before_cognition()
    assert out["outcome"] == PL.TRADING_COGNITION_OFF and out["reason"] == DLB.UNOWNED_TRADE
    assert out["terminal_lock_persistence_error"] == "OSError: store is read-only"
    assert out["provider_call_suppressed"] and out["candidate_production_suppressed"]
    assert out["conditional_plan_publication_suppressed"] and out["safety_reconciliation_continues"]
    assert out["session_cognition"]["state"] == COGNITION_LOCK.CONTAMINATED
    assert out["session_cognition"]["terminal"] is True
    assert loop.active_candidate is None and loop.active_conditional_plan is None and cleared == ["plan:latch"]
    # Nothing durable was written, so the honest record is the reported error, not a lock file.
    assert COGNITION_LOCK.load(store_dir=str(tmp_path), session_id=SESSION, account_fingerprint=FP,
                               contract_id=CID) is None
    # Same process: the memory latch answers; the governor is not consulted again.
    again = loop._terminal_contamination_before_cognition()
    assert again["outcome"] == PL.TRADING_COGNITION_OFF and calls == [DLB.CONTAMINATED]


def test_after_a_failed_write_a_restart_reconsults_the_governor_and_latches_durably(tmp_path, monkeypatch):
    calls, cleared = [], []
    monkeypatch.setattr(PL.DLB, "resolve", _governor(DLB.CONTAMINATED, calls))
    original = PL.COGNITION_LOCK.record_contaminated
    monkeypatch.setattr(PL.COGNITION_LOCK, "record_contaminated",
                        lambda **kwargs: (_ for _ in ()).throw(OSError("store is read-only")))
    _loop(tmp_path, cleared)._terminal_contamination_before_cognition()
    monkeypatch.setattr(PL.COGNITION_LOCK, "record_contaminated", original)
    restarted = _loop(tmp_path, cleared)
    out = restarted._terminal_contamination_before_cognition()
    assert out["outcome"] == PL.TRADING_COGNITION_OFF and out["terminal_lock_persistence_error"] is None
    assert calls == [DLB.CONTAMINATED, DLB.CONTAMINATED]
    assert COGNITION_LOCK.load(store_dir=str(tmp_path), session_id=SESSION, account_fingerprint=FP,
                               contract_id=CID)["terminal"] is True
