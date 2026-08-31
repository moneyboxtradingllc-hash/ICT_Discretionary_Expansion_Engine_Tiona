"""EVIDENCE-SUBSTRATE-PHASE0 (2026-08-08). The flight recorder.

Two properties matter and they pull against each other.

It must CAPTURE ENOUGH that a trade taken today is fully explicable months from
now -- which decision, which brain, which doctrine, which order, which fill,
which exit. PROD-20260807 lost its qualification evidence and cost a day of
archaeology; a lost trade would cost far more.

And it must NEVER COST A TRADE. A recorder that can raise, block, or be
consulted by a gate is not a recorder. Every write swallows its failure and
every function returns evidence, never permission.
"""
from __future__ import annotations

import json
import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))

from broker import trade_lineage as TL                               # noqa: E402


@pytest.fixture
def session(tmp_path, monkeypatch):
    """An isolated session root. Never the operator's real evidence."""
    monkeypatch.setattr(TL, "_root", lambda sid: str(tmp_path / (sid or "UNSCOPED")))
    return "PROD-TEST"


class Ctx:
    """Stands in for ExecutionContext -- same as_dict() contract."""

    def __init__(self, **over):
        self.data = {"candidate_id": "CAN-1", "candidate_fingerprint": "fp-1",
                     "snapshot_id": "scan-1", "mission_id": "M-1",
                     "contract_id": "CON.F.US.MNQ.U26", "direction": "long",
                     "quantity": 3, "entry_order_id": 900123,
                     "entry_trade_id": 777, "entry_fill_price": 29700.0,
                     "structural_stop_price": 29665.0,
                     "liquidity_target_price": 29760.0,
                     "stop_order_id": 900124, "target_order_id": 900125}
        self.data.update(over)

    def as_dict(self):
        return dict(self.data)


BRAIN = {"model": "gpt-5.6-terra",
         "parsed": {"narrative_direction": "bullish",
                    "current_action": "propose bullish entry",
                    "objective_id": "OBJ_LIQ_BSL_1",
                    "invalidation_id": "INV_PL_1"}}

SHADOW = {"would_have_done": "CONTINUE_TO_MECHANICAL_GATES",
          "envelope": {"authority_mode": "shadow",
                       "hybrid_disposition": "SHADOW_RECORDED_ONLY",
                       "mechanical_proposal": {
                           "mechanical_proposal_id": "MP-abc",
                           "direction": "bullish",
                           "objective_id": "OBJ_LIQ_BSL_1",
                           "invalidation_id": "INV_PL_1",
                           "reward_to_risk": 1.71},
                       "terra_review": {"verdict": "CONFIRM", "confidence": 88,
                                        "material_contradictions": []}}}

TRACE = {"reward_risk": 1.71, "reward_risk_floor": 1.0,
         "legacy_floor_verdict": "WOULD_PASS",
         "eligible_only_because_floor_moved": False}

GOVERNOR = {"account_regime": "COMBINE_50K", "profit_governor_result": "SIZE_REDUCED",
            "candidate_contracts_before_profit_governor": 8,
            "candidate_contracts_after_profit_governor": 3}


def opened(session, **over):
    return TL.open_lineage(session_id=session, execution_context=Ctx(**over),
                           brain_result=BRAIN, shadow=SHADOW,
                           decision_trace=TRACE, governor=GOVERNOR)


# ══════════════════════════════════════════════════════════════════════════════
class TestTheJoinIsComplete:
    """decision -> candidate -> order -> fill -> exit, without guessing."""

    def test_the_entry_half_carries_every_identity(self, session):
        row = opened(session)
        for field in ("snapshot_id", "candidate_id", "candidate_fingerprint",
                      "mission_id", "entry_order_id", "entry_trade_id",
                      "entry_fill_price", "stop_order_id", "target_order_id",
                      "structural_stop_price", "liquidity_target_price"):
            assert row[field] is not None, field

    def test_both_brains_are_joined_to_the_trade(self, session):
        """Months later, which thesis caused this order?"""
        row = opened(session)
        assert row["production_direction"] == "bullish"
        assert row["production_objective_id"] == "OBJ_LIQ_BSL_1"
        assert row["production_model"] == "gpt-5.6-terra"
        assert row["mechanical_proposal_id"] == "MP-abc"
        assert row["terra_review_verdict"] == "CONFIRM"
        assert row["hybrid_would_have_done"] == "CONTINUE_TO_MECHANICAL_GATES"

    def test_the_doctrine_in_force_is_recorded(self, session):
        """A trade must be interpretable against the rules it was taken under."""
        row = opened(session)
        assert row["reward_risk_floor"] == 1.0
        assert row["legacy_floor_verdict"] == "WOULD_PASS"
        assert row["account_regime"] == "COMBINE_50K"
        assert row["contracts_before_profit_governor"] == 8
        assert row["contracts_after_profit_governor"] == 3

    def test_the_exit_half_completes_it(self, session):
        row = opened(session)
        closed = TL.close_lineage(session_id=session, lineage=row,
                                  exit_price=29760.0, exit_reason="TARGET",
                                  exit_trade_id=888, realized_pnl_usd=360.0,
                                  mfe_points=64.0, mae_points=-6.0,
                                  reconciled=True)
        assert closed["state"] == "CLOSED"
        assert closed["exit_reason"] == "TARGET"
        assert closed["realized_r"] == 1.714     # 60 pts / 35 pts risk
        assert closed["reconciled"] is True
        assert closed["time_in_trade_seconds"] is not None

    def test_both_halves_survive_as_separate_rows(self, session):
        row = opened(session)
        TL.close_lineage(session_id=session, lineage=row, exit_price=29760.0,
                         exit_reason="TARGET", reconciled=True)
        rows = TL.load_lineage(session)
        assert [r["state"] for r in rows] == ["OPEN", "CLOSED"]
        assert rows[0]["exit_price"] is None, "the OPEN row must not be rewritten"


class TestRealizedR:

    @pytest.mark.parametrize("direction,exit_price,expected", [
        ("long", 29760.0, 1.714),      # +60 on 35 risk
        ("long", 29665.0, -1.0),       # stopped
        ("short", 29640.0, 1.714),
        ("short", 29735.0, -1.0),
    ])
    def test_r_is_measured_against_structural_risk(self, direction, exit_price,
                                                   expected):
        base = {"entry_fill_price": 29700.0, "direction": direction,
                "structural_stop_price": 29665.0 if direction == "long" else 29735.0,
                "exit_price": exit_price}
        assert TL.realized_r(base) == expected

    def test_r_describes_the_trade_not_the_position_size(self, session):
        """The profit governor may size a Combine trade down; R must not move."""
        a = TL.realized_r({"entry_fill_price": 29700.0, "direction": "long",
                           "structural_stop_price": 29665.0, "exit_price": 29760.0})
        assert a == 1.714   # no contract count anywhere in the calculation

    def test_incomplete_geometry_returns_none_rather_than_guessing(self):
        for bad in ({}, {"entry_fill_price": 29700.0},
                    {"entry_fill_price": 29700.0, "structural_stop_price": 29700.0,
                     "exit_price": 29760.0}):        # zero risk
            assert TL.realized_r(bad) is None

    def test_an_unstated_exit_cause_is_unknown_not_inferred(self, session):
        row = opened(session)
        closed = TL.close_lineage(session_id=session, lineage=row,
                                  exit_price=29759.0)
        assert closed["exit_reason"] == TL.EXIT_UNKNOWN, (
            "a near-target price is not proof of a target fill")


class TestItCanNeverCostATrade:

    def test_no_write_path_raises(self, monkeypatch, session):
        monkeypatch.setattr(TL, "_root", lambda sid: "\x00://impossible")
        row = TL.open_lineage(session_id=session, execution_context=Ctx())
        assert row["lineage_write_ok"] is False
        closed = TL.close_lineage(session_id=session, lineage=row,
                                  exit_price=1.0, exit_reason="STOP")
        assert closed["lineage_write_ok"] is False
        assert closed["state"] == "CLOSED", "the record still forms in memory"

    def test_hostile_inputs_are_absorbed(self, session):
        row = TL.open_lineage(session_id=session, execution_context={},
                              brain_result=None, shadow=None,
                              decision_trace=None, governor=None)
        assert row["schema_version"] == TL.LINEAGE_SCHEMA
        assert row["candidate_id"] is None

    def test_nothing_here_returns_a_permission(self):
        """Evidence, never authority."""
        src = open(os.path.join(ROOT, "src", "broker", "trade_lineage.py"),
                   encoding="utf-8").read()
        body = "\n".join(l for l in src.splitlines()
                         if not l.strip().startswith("#"))
        for forbidden in ("authoriz", "permit", "approve", "raise NoCandidate",
                          "RiskRejection", "gated_submit", "place_order"):
            assert forbidden not in body, forbidden

    def test_no_gate_consults_it(self):
        """It must not be imported by anything that can refuse a trade."""
        import subprocess
        out = subprocess.run(["git", "grep", "-l", "trade_lineage", "--",
                              "src/broker/luna_candidate_producer.py",
                              "src/broker/topstepx_combine_risk.py",
                              "src/broker/capital_profit_governor.py"],
                             capture_output=True, text=True, cwd=ROOT)
        assert out.stdout.strip() == "", out.stdout


class TestLineageAccounting:

    def test_every_open_trade_must_close(self, session):
        row = opened(session)
        assert TL.reconcile_lineage(session)["status"] == "LINEAGE_INCOMPLETE"
        assert TL.reconcile_lineage(session)["unclosed_candidates"] == ["CAN-1"]
        TL.close_lineage(session_id=session, lineage=row, exit_price=29760.0,
                         exit_reason="TARGET", reconciled=True)
        out = TL.reconcile_lineage(session)
        assert out["status"] == "RECONCILED"
        assert (out["opened"], out["closed"]) == (1, 1)

    def test_an_empty_session_reconciles_trivially(self, session):
        assert TL.reconcile_lineage(session)["status"] == "RECONCILED"


class TestSessionTape:
    """The only evidence on the roadmap that expires."""

    BARS = [{"timestamp": f"2026-08-10T14:{m:02d}:00+00:00", "open": 29700.0,
             "high": 29710.0, "low": 29690.0, "close": 29705.0}
            for m in range(0, 40, 5)]

    def test_the_tape_is_archived_per_session(self, session, tmp_path):
        out = TL.archive_tape(session_id=session,
                              contract_id="CON.F.US.MNQ.U26", bars=self.BARS,
                              decision_timestamps=["2026-08-10T14:10:00+00:00"])
        assert out["tape_write_ok"] is True
        assert out["bar_count"] == len(self.BARS)
        assert out["first_bar"] < out["last_bar"]
        root = TL._root(session)
        assert os.path.exists(os.path.join(root, "session_tape.jsonl"))
        manifest = json.load(open(os.path.join(root, "session_tape_manifest.json"),
                                  encoding="utf-8"))
        assert manifest["decision_timestamps"] == ["2026-08-10T14:10:00+00:00"]

    def test_forward_coverage_is_answerable(self, session):
        TL.archive_tape(session_id=session, contract_id="C", bars=self.BARS)
        early = TL.tape_covers(session_id=session,
                               after_timestamp="2026-08-10T14:10:00+00:00")
        assert early["scoreable"] is True and early["bars_after"] > 0
        late = TL.tape_covers(session_id=session,
                              after_timestamp="2026-08-10T23:00:00+00:00")
        assert late["scoreable"] is False
        assert late["reason"] == "no bars after the decision"

    def test_a_session_with_no_tape_says_so_plainly(self, session):
        out = TL.tape_covers(session_id=session, after_timestamp="2026-08-10T14:00:00+00:00")
        assert out["scoreable"] is False
        assert out["reason"] == "no session tape archived"

    def test_archiving_never_raises(self, monkeypatch, session):
        monkeypatch.setattr(TL, "_root", lambda sid: "\x00://impossible")
        out = TL.archive_tape(session_id=session, contract_id="C", bars=self.BARS)
        assert out["tape_write_ok"] is False
        assert "error" in out


class TestWiredIntoTheSession:
    """PHASES 3, 4, 8, 13, 14 — the recorder rides along; it never steers."""

    def session_obj(self, tmp_path, monkeypatch):
        from broker import topstepx_production_session as PS
        obj = PS.ProductionSession.__new__(PS.ProductionSession)
        obj.session_id = "PROD-TEST"
        obj._lineage = None
        monkeypatch.setattr(TL, "_root", lambda sid: str(tmp_path / str(sid)))
        return obj

    def test_the_recorder_is_called_after_the_fact_never_before(self):
        """Order of operations is the whole safety argument."""
        src = open(os.path.join(ROOT, "src", "broker",
                                "topstepx_production_session.py"),
                   encoding="utf-8").read()
        entry = src.index("_record_entry_lineage(ctx, candidate)")
        built = src.index("ctx = self.runner.build_execution_context")
        assert built < entry, "lineage must follow the confirmed fill"
        exit_call = src.index("self._record_exit_lineage(")
        measured = src.index("observation = self.runner.measure_exit_slippage")
        assert measured < exit_call, "lineage must follow the measured exit"

    def test_entry_lineage_survives_a_candidate_with_no_extras(self, tmp_path,
                                                               monkeypatch):
        obj = self.session_obj(tmp_path, monkeypatch)
        row = obj._record_entry_lineage(Ctx(), candidate=object())
        assert row is not None and row["candidate_id"] == "CAN-1"
        assert row["mechanical_proposal_id"] is None   # honest absence

    def test_two_brain_absence_never_invalidates_a_real_trade(self, tmp_path,
                                                              monkeypatch):
        """PHASE 11 — production and shadow are independent."""
        obj = self.session_obj(tmp_path, monkeypatch)

        class Cand:
            extras = {"brain_result": BRAIN}      # no shadow at all
        row = obj._record_entry_lineage(Ctx(), Cand())
        assert row["production_direction"] == "bullish"
        assert row["hybrid_disposition"] is None
        assert row["candidate_id"] == "CAN-1"

    def test_exit_reason_comes_from_the_venue_not_from_price(self, tmp_path,
                                                            monkeypatch):
        from broker import topstepx_session_ledger as LG
        obj = self.session_obj(tmp_path, monkeypatch)
        obj._lineage = obj._record_entry_lineage(Ctx(), object())
        closed = obj._record_exit_lineage(
            exit_type="EXIT_TARGET", fill_price=29760.0, exit_order_id=1,
            observation={}, attribution=LG.EXPANSION_BOT, fills=[{"id": 55}])
        assert closed["exit_reason"] == "EXIT_TARGET"
        assert closed["exit_trade_id"] == 55
        assert closed["reconciled"] is True
        assert closed["realized_r"] == 1.714

    def test_a_manual_fill_is_not_marked_reconciled(self, tmp_path, monkeypatch):
        """PHASE 9 — origin comes from the tag join, never from proximity."""
        from broker import topstepx_session_ledger as LG
        obj = self.session_obj(tmp_path, monkeypatch)
        obj._lineage = obj._record_entry_lineage(Ctx(), object())
        closed = obj._record_exit_lineage(
            exit_type="EXIT_FLATTEN", fill_price=29760.0, exit_order_id=1,
            observation={}, attribution=LG.MANUAL_OPERATOR, fills=[])
        assert closed["reconciled"] is False

    def test_the_open_row_is_cleared_so_a_second_trade_cannot_inherit_it(
            self, tmp_path, monkeypatch):
        from broker import topstepx_session_ledger as LG
        obj = self.session_obj(tmp_path, monkeypatch)
        obj._lineage = obj._record_entry_lineage(Ctx(), object())
        obj._record_exit_lineage(exit_type="EXIT_STOP", fill_price=29665.0,
                                 exit_order_id=1, observation={},
                                 attribution=LG.EXPANSION_BOT, fills=[])
        assert obj._lineage is None

    @pytest.mark.parametrize("victim", ["open_lineage", "close_lineage"])
    def test_recorder_failure_cannot_reach_the_trade(self, tmp_path, monkeypatch,
                                                     victim):
        """PHASE 14 — fault injection. RECORDER_CAUSED_TRADE_FAILURES = 0."""
        def boom(*a, **k):
            raise RuntimeError("recorder exploded")
        monkeypatch.setattr(TL, victim, boom)
        obj = self.session_obj(tmp_path, monkeypatch)
        obj._lineage = obj._record_entry_lineage(Ctx(), object()) or {"x": 1}
        out = obj._record_exit_lineage(exit_type="EXIT_TARGET", fill_price=1.0,
                                       exit_order_id=1, observation={},
                                       attribution="EXPANSION_BOT", fills=[])
        assert out is None or isinstance(out, dict)   # absorbed, never raised

    def test_the_tape_call_is_guarded_in_the_launcher(self):
        src = open(os.path.join(ROOT, "tools", "topstepx_production_session.py"),
                   encoding="utf-8").read()
        block = src[src.index("from broker.trade_lineage import archive_tape"):]
        block = block[:block.index("return results")]
        assert "except Exception" in block, "tape capture must never end a session"
        assert src.index("loop.final_flat_state()") < src.index("archive_tape")

    def test_no_existing_disposition_changed(self):
        """PHASE 13 — the wiring adds capture; it returns nothing new to callers."""
        src = open(os.path.join(ROOT, "src", "broker",
                                "topstepx_production_session.py"),
                   encoding="utf-8").read()
        entry_ret = src[src.index('return {"observation": observation, "context"'):]
        assert "lineage" not in entry_ret[:200], (
            "reconcile_entry's return contract must be unchanged")
