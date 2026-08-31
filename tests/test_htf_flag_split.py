"""
FLAG-SPLIT — conflict-flag semantics locks (2026-07-30).

Audit verdict (docs/audits/HTF_CONFLICT_FLAGS_AUDIT_20260730.md): the
unfilled-gap condition is a session-long STATE, not a conflict — it latched
100% of scans on 7 sessions (84% of all flag volume) and duplicated
gap_context. Post-split, htf_conflict_flags carries ONLY directional
HTF-vs-narrative disagreement.

Mission contract locks:
  * unfilled gaps alone create NO conflict flag (the split itself)
  * the operator's exact regression: unfilled gap + NEUTRAL htf_bias ->
    no flag, gap_context preserved untouched
  * directional HTF-vs-narrative disagreement still flags (both ways)
  * agreement / neutral narrative / neutral bias -> no flag
  * no new reader: no authority module references htf_conflict_flags
"""
import os
import sys
import unittest

sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from market_data.snapshot_builder import compute_htf_conflict_flags  # noqa: E402


def _ctx(bias="neutral", gap_side="no_meaningful_gap", filled=False):
    return {"htf_bias": bias,
            "gap_context": {"side": gap_side, "filled": filled,
                            "gap_points": 1.5, "gap_pct": 0.21}}


class TestFlagSplit(unittest.TestCase):
    def test_unfilled_gap_alone_creates_no_conflict_flag(self):
        # pre-split this produced ["unfilled_gap_up"] — the latching defect
        ctx = _ctx(bias="bullish", gap_side="gap_up", filled=False)
        self.assertEqual(
            compute_htf_conflict_flags(ctx, "bullish"), [])

    def test_operator_regression_unfilled_gap_neutral_bias(self):
        # Unfilled gap: True / HTF bias: Neutral ->
        # Expected: no directional conflict flag; gap context still present
        ctx = _ctx(bias="neutral", gap_side="gap_down", filled=False)
        before = dict(ctx["gap_context"])
        self.assertEqual(compute_htf_conflict_flags(ctx, "bearish"), [])
        self.assertEqual(ctx["gap_context"], before)   # evidence retained,
        self.assertNotIn("htf_conflict_flags", ctx)    # helper never mutates

    def test_directional_disagreement_still_flags_both_ways(self):
        self.assertEqual(
            compute_htf_conflict_flags(_ctx(bias="bearish"), "bullish"),
            ["htf_bias_bearish_vs_narrative_bullish"])
        self.assertEqual(
            compute_htf_conflict_flags(_ctx(bias="bullish"), "bearish"),
            ["htf_bias_bullish_vs_narrative_bearish"])

    def test_agreement_no_flag(self):
        self.assertEqual(
            compute_htf_conflict_flags(_ctx(bias="bullish"), "bullish"), [])
        self.assertEqual(
            compute_htf_conflict_flags(_ctx(bias="bearish"), "bearish"), [])

    def test_neutral_htf_bias_never_flags(self):
        for nd in ("bullish", "bearish", "neutral", "conflicted", None):
            self.assertEqual(
                compute_htf_conflict_flags(_ctx(bias="neutral"), nd), [])

    def test_neutral_or_absent_narrative_no_flag(self):
        for nd in ("neutral", "conflicted", None, ""):
            self.assertEqual(
                compute_htf_conflict_flags(_ctx(bias="bearish"), nd), [])

    def test_non_dict_context_fails_closed(self):
        for bad in (None, [], "x", 3):
            self.assertEqual(compute_htf_conflict_flags(bad, "bullish"), [])

    def test_no_authority_reader_exists(self):
        # witness doctrine: no gate/qualification/decision/execution module
        # may read the flags. Source-level lock, same style as retirement locks.
        src_root = os.path.join(os.path.dirname(__file__), "..", "src")
        forbidden_dirs = ("execution_gate", "qualification",
                         "decision_authority", "paper_execution", "risk")
        offenders = []
        for d in forbidden_dirs:
            for dirpath, _dn, files in os.walk(os.path.join(src_root, d)):
                for f in files:
                    if not f.endswith(".py"):
                        continue
                    p = os.path.join(dirpath, f)
                    with open(p, encoding="utf-8", errors="ignore") as fh:
                        if "htf_conflict_flags" in fh.read():
                            offenders.append(p)
        self.assertEqual(offenders, [])


if __name__ == "__main__":
    unittest.main()
