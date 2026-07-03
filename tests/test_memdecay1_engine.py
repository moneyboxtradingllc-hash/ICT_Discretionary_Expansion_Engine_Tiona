"""
MEM-DECAY-1 — Memory Decay Engine regression lock.

The organism must remember pain — but it must also learn how to heal.

TEST A: streak-4 block still fires (day 0 behavior unchanged)
TEST B: blocked bucket enters cooldown (same-day re-evals stay blocked)
TEST C: cooldown decays over clean sessions -> probation opens
TEST D: probation trade opens defensively (existing mutation actuators:
        size halved, confidence -10%, no hard block)
TEST E: probation win restores the bucket (reopened; streak reset)
TEST F: probation loss re-locks the bucket with a DOUBLED cooldown
TEST G: decay never erases scar history (locked/probation/relock/reopen
        events all preserved; reopened records persist)

All state lives in a temp dir — never live adaptive memory.
"""
import json
import os
import sys
import tempfile
import unittest

sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from adaptive_learning.performance_tables import record_result           # noqa: E402
from adaptive_learning.adaptive_policy_engine import (                    # noqa: E402
    generate_adaptive_policy_report,
)
from adaptive_learning.adaptive_mutation_engine import mutate_candidate   # noqa: E402
from adaptive_learning.memory_decay_engine import (                       # noqa: E402
    evaluate_bucket_decay, load_scar_state, SCAR_STATE_FILE,
)

_CAND = {"symbol": "QQQ", "playbook": "sweep", "tool": "fvg",
         "session": "morning", "regime": "trend", "volatility": "normal"}

D1, D2, D3, D4, D5, D6, D7 = ("2026-07-06", "2026-07-07", "2026-07-08",
                              "2026-07-09", "2026-07-10", "2026-07-13",
                              "2026-07-14")


class _Scarred(unittest.TestCase):
    """Fixture: 4 consecutive losses in the 'session:morning' bucket on D1."""

    def setUp(self):
        self._tmp = tempfile.mkdtemp()
        for _ in range(4):
            record_result("QQQ", "session", "morning", "loss", -1.0,
                          base_dir=self._tmp)

    def _report(self, today):
        return generate_adaptive_policy_report(_CAND, base_dir=self._tmp,
                                               today=today)

    def _session_decay(self, report):
        return report["dimensions"]["session"]["decay"]


class TestA_BlockStillFires(_Scarred):
    def test_streak4_blocks_on_lock_day(self):
        rep = self._report(D1)
        self.assertTrue(rep["trade_block_recommended"])
        self.assertFalse(rep["probation_active"])
        d = self._session_decay(rep)
        self.assertEqual(d["decay_status"], "scarred")
        self.assertEqual(d["raw_loss_streak"], 4)


class TestB_Cooldown(_Scarred):
    def test_same_day_reevaluations_stay_blocked(self):
        self._report(D1)                       # lock
        for _ in range(5):                     # scan every minute, same day
            rep = self._report(D1)
        self.assertTrue(rep["trade_block_recommended"])
        d = self._session_decay(rep)
        self.assertEqual(d["scar_age_sessions"], 0)   # lock day never counts

    def test_first_clean_session_counts_but_still_blocked(self):
        self._report(D1)
        rep = self._report(D2)
        self.assertTrue(rep["trade_block_recommended"])
        d = self._session_decay(rep)
        self.assertEqual(d["decay_status"], "cooldown")
        self.assertEqual(d["scar_age_sessions"], 1)
        self.assertEqual(d["cooldown_required"], 2)
        self.assertEqual(d["decayed_loss_streak"], 3)   # 4 raw - 1 clean


class TestC_DecayOpensProbation(_Scarred):
    def test_two_clean_sessions_grant_probation(self):
        self._report(D1)
        self._report(D2)
        rep = self._report(D3)
        self.assertFalse(rep["trade_block_recommended"])
        self.assertTrue(rep["probation_active"])
        d = self._session_decay(rep)
        self.assertEqual(d["decay_status"], "probation")
        self.assertIn("cooldown served", d["rehabilitation_reason"])


class TestD_ProbationIsDefensive(_Scarred):
    def test_probation_uses_existing_defensive_actuators(self):
        self._report(D1); self._report(D2)
        rep = self._report(D3)
        self.assertTrue(rep["confidence_penalty_recommended"])
        self.assertTrue(rep["risk_reduction_recommended"])
        self.assertFalse(rep["confidence_boost_recommended"])
        mut = mutate_candidate({"confidence": 60, "qty": 4}, rep)
        self.assertFalse(mut["trade_blocked"])          # test trade allowed
        self.assertEqual(mut["new_qty"], 2)             # size halved
        self.assertEqual(mut["new_confidence"], 54.0)   # -10%
        self.assertIn("PROBATION", " ".join(rep["recommended_adjustments"]))

    def test_probation_persists_through_breakeven(self):
        self._report(D1); self._report(D2); self._report(D3)   # probation
        record_result("QQQ", "session", "morning", "breakeven", 0.0,
                      base_dir=self._tmp)
        rep = self._report(D4)
        self.assertTrue(rep["probation_active"])
        self.assertFalse(rep["trade_block_recommended"])


class TestE_ProbationWinReopens(_Scarred):
    def test_win_restores_bucket(self):
        self._report(D1); self._report(D2); self._report(D3)   # probation
        record_result("QQQ", "session", "morning", "win", 2.0,
                      base_dir=self._tmp)                       # test trade wins
        rep = self._report(D4)
        self.assertFalse(rep["trade_block_recommended"])
        self.assertFalse(rep["probation_active"])
        d = self._session_decay(rep)
        self.assertEqual(d["decay_status"], "reopened")
        self.assertEqual(d["raw_loss_streak"], 0)


class TestF_ProbationLossRelocks(_Scarred):
    def test_loss_relocks_with_doubled_cooldown(self):
        self._report(D1); self._report(D2); self._report(D3)   # probation
        record_result("QQQ", "session", "morning", "loss", -1.0,
                      base_dir=self._tmp)                       # test trade loses
        rep = self._report(D4)
        self.assertTrue(rep["trade_block_recommended"])
        self.assertFalse(rep["probation_active"])
        d = self._session_decay(rep)
        self.assertEqual(d["decay_status"], "scarred")
        self.assertEqual(d["lock_count"], 2)
        self.assertEqual(d["cooldown_required"], 4)             # 2 -> 4

    def test_second_rehabilitation_needs_four_clean_sessions(self):
        self._report(D1); self._report(D2); self._report(D3)
        record_result("QQQ", "session", "morning", "loss", -1.0,
                      base_dir=self._tmp)
        self._report(D4)                                        # re-locked
        for day in (D5, D6, D7):
            rep = self._report(day)
            self.assertTrue(rep["trade_block_recommended"],
                            f"must stay blocked through {day} (3/4 sessions)")
        rep = self._report("2026-07-15")                        # 4th clean session
        self.assertTrue(rep["probation_active"])
        self.assertFalse(rep["trade_block_recommended"])


class TestG_HistoryNeverErased(_Scarred):
    def test_full_scar_history_preserved(self):
        self._report(D1); self._report(D2); self._report(D3)    # lock -> probation
        record_result("QQQ", "session", "morning", "loss", -1.0,
                      base_dir=self._tmp)
        self._report(D4)                                        # relock
        self._report(D5); self._report(D6); self._report(D7)
        self._report("2026-07-15")                              # probation #2
        record_result("QQQ", "session", "morning", "win", 1.5,
                      base_dir=self._tmp)
        self._report("2026-07-16")                              # reopened

        state = load_scar_state("QQQ", base_dir=self._tmp)
        rec = state["session:morning"]
        events = [e["event"] for e in rec["history"]]
        self.assertIn("locked", events)
        self.assertIn("probation_granted", events)
        self.assertIn("relocked", events)
        self.assertIn("reopened", events)
        self.assertEqual(rec["status"], "reopened")             # record persists
        self.assertEqual(rec["lock_count"], 2)                  # pain remembered

    def test_reoffense_after_reopen_relocks_with_longer_cooldown(self):
        self._report(D1); self._report(D2); self._report(D3)
        record_result("QQQ", "session", "morning", "win", 1.5, base_dir=self._tmp)
        self._report(D4)                                        # reopened
        for _ in range(4):                                      # scars return
            record_result("QQQ", "session", "morning", "loss", -1.0,
                          base_dir=self._tmp)
        rep = self._report(D5)
        self.assertTrue(rep["trade_block_recommended"])
        d = self._session_decay(rep)
        self.assertEqual(d["lock_count"], 2)                    # history-aware
        self.assertEqual(d["cooldown_required"], 4)


class TestSafety(unittest.TestCase):
    def test_decay_never_softens_on_error(self):
        # unwritable base_dir path -> engine must return the SAFE (blocked) verdict
        v = evaluate_bucket_decay("QQQ", "session", "morning",
                                  {"loss_streak": 4, "trades": 4},
                                  base_dir="\0invalid\0")
        self.assertTrue(v["block_recommended"])
        self.assertIn("decay_error", v["rehabilitation_reason"])

    def test_healthy_bucket_untouched_and_stateless(self):
        tmp = tempfile.mkdtemp()
        v = evaluate_bucket_decay("QQQ", "session", "morning",
                                  {"loss_streak": 1, "trades": 3},
                                  base_dir=tmp)
        self.assertEqual(v["decay_status"], "healthy")
        self.assertFalse(v["block_recommended"])
        self.assertFalse(os.path.exists(
            os.path.join(tmp, "QQQ", SCAR_STATE_FILE)))

    def test_decay_can_only_soften_never_boost(self):
        tmp = tempfile.mkdtemp()
        for _ in range(4):
            record_result("QQQ", "session", "morning", "loss", -1.0, base_dir=tmp)
        generate_adaptive_policy_report(_CAND, base_dir=tmp, today=D1)
        generate_adaptive_policy_report(_CAND, base_dir=tmp, today=D2)
        rep = generate_adaptive_policy_report(_CAND, base_dir=tmp, today=D3)
        self.assertTrue(rep["probation_active"])
        self.assertFalse(rep["confidence_boost_recommended"])
        self.assertEqual(rep["authority_level"], "observe_only")
        self.assertEqual(rep["posture"], "DEFENSIVE_ONLY")


if __name__ == "__main__":
    unittest.main()
