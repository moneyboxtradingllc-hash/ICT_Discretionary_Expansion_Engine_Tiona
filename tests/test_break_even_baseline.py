"""BREAK-EVEN-2A — what 1R meant must survive the process that learned it.

`break_even.evaluate` is correct while the process lives; its inputs were
RAM-only. A restart mid-position therefore had two silent ways to be wrong:

  ADOPT THE CURRENT VENUE STOP. Protection is designed to move. Once it has,
  R recomputed from the working stop shrinks every time the trade improves.
  On the 2026-08-24 position, a restart after break-even had been applied
  would compute R as 29090.25 -> 29088.50 = -1.75 points: not merely wrong,
  inverted.

  FALL BACK TO THE REQUESTED ENTRY. Requested 29092.25, filled 29090.25.
  Against the same 29110.25 stop that is 18.00 points of requested risk and
  20.00 of real risk -- a restart using the request protects at 0.9R.

And one trap found while auditing the durable evidence: the submission ledger
records `stop_points: 18.0`, because that is the requested-entry distance the
sizing lane approved. Reading that stored number as R would be wrong by 10% on
this exact trade, and wrong quietly.

No broker. No provider. No network.
"""
from __future__ import annotations

import json
import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))

from broker import break_even as BE                                  # noqa: E402
from broker import break_even_baseline as BB                         # noqa: E402
from broker.topstepx_client import TopstepXContract                  # noqa: E402

MNQ = TopstepXContract(id="CON.F.US.MNQ.U26", name="MNQ", description="",
                       tick_size=0.25, tick_value=0.50, active=True)
LIVE_DIR = os.path.join(ROOT, "data", "integration", "topstepx")
LIVE_MISSION = os.path.join(LIVE_DIR, "trade_mission_PRAC-20260824_1.json")
LIVE_SUBS = os.path.join(LIVE_DIR, "submissions_PRAC-20260824.jsonl")

FILL, REQUESTED, STOP = 29090.25, 29092.25, 29110.25


def write_pair(tmp, *, mission=None, submission=None, mission_id="M1"):
    mp = tmp / "mission.json"
    sp = tmp / "subs.jsonl"
    m = {"mission_id": mission_id, "contract_id": "CON.F.US.MNQ.U26",
         "account_fingerprint": "acct:test", "order_id": 1, "token_id": "t1",
         "filled_quantity": 8, "fill_price": FILL}
    m.update(mission or {})
    g = {"direction": "bearish", "entry_price": REQUESTED, "stop_price": STOP,
         "target_price": 28947.75, "stop_points": 18.0, "size": 8}
    g.update((submission or {}).pop("geometry", {}) if submission else {})
    row = {"mission_id": mission_id, "submission_id": "s1", "token_id": "t1",
           "state": "SUBMISSION_STARTED", "geometry": g}
    row.update(submission or {})
    mp.write_text(json.dumps(m), encoding="utf-8")
    sp.write_text(json.dumps(row) + "\n", encoding="utf-8")
    return str(mp), str(sp)


# ══════════════════════════════════════════════════════════════════════════════
class TestTheRealPositionRecovers:

    @pytest.fixture(scope="class")
    def b(self):
        if not (os.path.exists(LIVE_MISSION) and os.path.exists(LIVE_SUBS)):
            pytest.skip("live 2026-08-24 artifacts absent")
        return BB.recover(mission_path=LIVE_MISSION, submissions_path=LIVE_SUBS)

    def test_it_recovers(self, b):
        assert b["status"] == BB.RECOVERED
        assert b["mission_id"] == "PRAC-20260824-T1"

    def test_the_actual_fill_survives_not_the_request(self, b):
        assert b["entry_fill_price"] == FILL
        assert b["recorded_requested_entry"] == REQUESTED
        assert b["entry_fill_price"] != b["recorded_requested_entry"]

    def test_r_is_recomputed_from_the_fill_not_the_stored_distance(self, b):
        """The ledger says 18.0. Real risk is 20.0. Trusting the stored number
        would be wrong by 10% on this exact trade."""
        assert b["initial_risk_points"] == 20.0
        assert b["recorded_stop_points_not_used"] == 18.0

    def test_position_identity_travels_with_the_baseline(self, b):
        assert b["direction"] == "short"
        assert b["quantity"] == 8
        assert b["contract_id"] == "CON.F.US.MNQ.U26"
        assert b["entry_order_id"] == 3440832308

    def test_a_restarted_process_reaches_the_same_decision(self, b):
        d = BE.evaluate(direction=b["direction"], entry_fill_price=b["entry_fill_price"],
                        initial_stop_price=b["original_initial_stop"],
                        active_protective_stop=b["original_initial_stop"],
                        current_price=29070.25, armed=True, contract=MNQ)
        assert d["outcome"] == BE.PROPOSE
        assert d["initial_risk_points"] == 20.0
        assert d["break_even_price"] == 29088.50


class TestInitialRiskIsImmutable:
    """The whole point: nothing that happens after the fill may rewrite R."""

    def test_the_current_venue_stop_can_never_become_the_baseline(self):
        """If a restart adopted the working stop after break-even had been
        applied, R on this position inverts to -1.75 points."""
        bad = BE.evaluate(direction="short", entry_fill_price=FILL,
                          initial_stop_price=29088.50,      # the ADVANCED stop
                          active_protective_stop=29088.50,
                          current_price=29070.25, armed=True, contract=MNQ)
        assert bad["outcome"] == BE.REFUSED
        assert bad["reason"] == BE.DEGENERATE_R

    def test_recovery_returns_the_original_stop_not_a_current_one(self, tmp_path):
        mp, sp = write_pair(tmp_path)
        b = BB.recover(mission_path=mp, submissions_path=sp)
        assert b["original_initial_stop"] == STOP

    def test_recovery_is_stable_across_repeated_reads(self, tmp_path):
        mp, sp = write_pair(tmp_path)
        a = BB.recover(mission_path=mp, submissions_path=sp)
        c = BB.recover(mission_path=mp, submissions_path=sp)
        assert a == c

    def test_a_long_mirror_recovers(self, tmp_path):
        mp, sp = write_pair(tmp_path, mission={"fill_price": 100.0},
                            submission={"geometry": {"direction": "bullish",
                                                     "stop_price": 90.0,
                                                     "entry_price": 100.5}})
        b = BB.recover(mission_path=mp, submissions_path=sp)
        assert b["direction"] == "long" and b["initial_risk_points"] == 10.0


class TestRefusesRatherThanGuessing:
    """A trigger computed from half-known risk is worse than no management,
    because it looks like management."""

    def test_a_missing_mission_is_unavailable(self, tmp_path):
        b = BB.recover(mission_path=str(tmp_path / "nope.json"),
                       submissions_path=str(tmp_path / "nope.jsonl"))
        assert b["status"] == BB.UNAVAILABLE and b["reason"] == BB.NO_MISSION

    def test_a_mission_with_no_fill_is_unavailable(self, tmp_path):
        mp, sp = write_pair(tmp_path, mission={"fill_price": None})
        assert BB.recover(mission_path=mp, submissions_path=sp)["reason"] == BB.NO_FILL

    def test_an_unfilled_mission_is_unavailable(self, tmp_path):
        mp, sp = write_pair(tmp_path, mission={"filled_quantity": 0})
        assert BB.recover(mission_path=mp, submissions_path=sp)["reason"] == BB.NOT_FILLED

    def test_a_missing_submission_is_unavailable(self, tmp_path):
        mp, sp = write_pair(tmp_path)
        (tmp_path / "subs.jsonl").write_text("", encoding="utf-8")
        assert BB.recover(mission_path=mp,
                          submissions_path=sp)["reason"] == BB.NO_SUBMISSION

    def test_a_submission_for_another_mission_is_not_borrowed(self, tmp_path):
        """One position's stop is not another's."""
        mp, sp = write_pair(tmp_path, mission={"mission_id": "MINE"})
        rows = json.loads((tmp_path / "subs.jsonl").read_text(encoding="utf-8"))
        rows["mission_id"] = "SOMEONE_ELSE"
        (tmp_path / "subs.jsonl").write_text(json.dumps(rows) + "\n", encoding="utf-8")
        assert BB.recover(mission_path=mp,
                          submissions_path=sp)["reason"] == BB.NO_SUBMISSION

    def test_a_contract_mismatch_refuses(self, tmp_path):
        mp, sp = write_pair(tmp_path,
                            submission={"geometry": {"contract_id": "CON.OTHER"}})
        r = BB.recover(mission_path=mp, submissions_path=sp)
        assert r["reason"] == BB.IDENTITY_MISMATCH

    def test_a_stop_on_the_wrong_side_refuses(self, tmp_path):
        mp, sp = write_pair(tmp_path,
                            submission={"geometry": {"stop_price": FILL - 5}})
        assert BB.recover(mission_path=mp,
                          submissions_path=sp)["reason"] == BB.DEGENERATE

    def test_corrupt_files_never_raise(self, tmp_path):
        bad = tmp_path / "bad.json"
        bad.write_text("{not json", encoding="utf-8")
        r = BB.recover(mission_path=str(bad), submissions_path=str(bad))
        assert r["status"] == BB.UNAVAILABLE

    def test_a_corrupt_ledger_line_is_skipped_not_fatal(self, tmp_path):
        mp, sp = write_pair(tmp_path)
        good = (tmp_path / "subs.jsonl").read_text(encoding="utf-8")
        (tmp_path / "subs.jsonl").write_text("{broken\n" + good, encoding="utf-8")
        assert BB.recover(mission_path=mp,
                          submissions_path=sp)["status"] == BB.RECOVERED


class TestNoSecondSourceOfTruth:

    def test_it_reads_existing_artifacts_and_writes_nothing(self):
        import inspect
        src = inspect.getsource(BB)
        for forbidden in ('"w"', "'w'", "json.dump(", "makedirs", "mkdir",
                          "requests", "openai", "modify_order"):
            assert forbidden not in src, forbidden

    def test_it_does_not_reimplement_the_trigger_or_the_cost_model(self):
        import inspect
        src = inspect.getsource(BB)
        assert "TRIGGER_R" not in src
        assert "friction" not in src.lower().replace("friction_per_contract", "")
