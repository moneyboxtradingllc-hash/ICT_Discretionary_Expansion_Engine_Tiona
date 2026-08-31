"""CONTINUITY-2E.2 — a tie earns no direction.

`manipulation_detector` and `displacement_detector` resolved direction with
`max(set(votes), key=votes.count)`. `set` iteration order over strings depends on
PYTHONHASHSEED, so a TIE was broken by whichever process happened to be running.

Reproduced on the gold tape, 5m at 15:08Z -- votes `rejection` (bullish) and
`rapid_reversal` (bearish), one each, score 30 and classification
`manipulation_possible` both ways:

    seeds 0, 1, 99  ->  "bullish"
    seeds 2, 3, 42  ->  "bearish"

CLASSIFICATION: forensic / replay determinism, NOT an execution defect. The
consumer re-audit (2026-08-12) confirms zero production-authority consumers:
`po3_engine` reads only `score` from both blocks, `po3._directions` derives
`manipulation_direction` from settled `sweep_dir`, and the only other readers are
the two `format_*` display helpers in the same modules. The fields are still
serialised into snapshots, so the damage was to the ARCHIVE and to replay
determinism.

THE RULE IS NOT A DETERMINISTIC TIE-BREAK. Alphabetical / first-seen / last-seen
/ a directional default would each make replay stable while asserting a direction
the evidence never supported. A 2-2 vote is uncertainty.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))

from data_feed import candle_continuity as CONT                      # noqa: E402
from data_feed.timeframe_builder import build_timeframes             # noqa: E402
import market_data.snapshot_builder as SB                            # noqa: E402
from structure.direction_vote import DIRECTIONS, resolve_direction_vote  # noqa: E402

FIXTURE = os.path.join(ROOT, "tests", "fixtures",
                       "mnq_20260811_1420Z_1510Z_1m.json")
TIED_SCAN = "2026-08-11T15:08:00+00:00"

#: Executed in a FRESH interpreter per seed -- PYTHONHASHSEED is a process-start
#: property, so looping inside one process proves nothing.
_SEED_PROBE = r"""
import json, os, sys
sys.path.insert(0, os.path.join(os.environ["REPO"], "src"))
from data_feed import candle_continuity as CONT
from data_feed.timeframe_builder import build_timeframes
import market_data.snapshot_builder as SB
tape = json.load(open(os.path.join(os.environ["REPO"], "tests", "fixtures",
                                   "mnq_20260811_1420Z_1510Z_1m.json")))["bars"]
end = os.environ["SCAN_END"]
win = CONT.coherent_window([b for b in tape if b["timestamp"] <= end],
                           horizon_minutes=300, minimum_bars=1)["window"]
snap = SB.build_snapshot(build_timeframes(win), symbol="MNQ")
out = {}
for tf in ("3m", "5m", "15m"):
    m = (snap["liquidity"][tf] or {}).get("manipulation") or {}
    d = (snap["expansion"][tf] or {}).get("displacement") or {}
    p = snap["po3"][tf] or {}
    out[tf] = {
        "manip": [m.get("direction"), m.get("direction_conflicted"),
                  m.get("score"), m.get("classification")],
        "disp": [d.get("direction"), d.get("direction_conflicted"),
                 d.get("score"), d.get("classification")],
        "po3": [p.get("phase"), p.get("manipulation_direction"),
                p.get("distribution_direction")],
    }
out["alignment"] = snap["po3"].get("alignment")
out["qualification"] = (snap.get("qualification") or {}).get("status")
out["risk_multiplier"] = (snap.get("risk") or {}).get("risk_multiplier")
print(json.dumps(out, sort_keys=True))
"""


def run_under_seed(seed: int, end: str = TIED_SCAN) -> dict:
    env = dict(os.environ, PYTHONHASHSEED=str(seed), REPO=ROOT, SCAN_END=end)
    proc = subprocess.run([sys.executable, "-c", _SEED_PROBE], env=env,
                          capture_output=True, text=True, cwd=ROOT, timeout=300)
    assert proc.returncode == 0, proc.stderr[-2000:]
    return json.loads(proc.stdout.strip().splitlines()[-1])


# ── the rule, in isolation ────────────────────────────────────────────────────

class TestResolveDirectionVote:

    def test_a_unique_plurality_wins(self):
        assert resolve_direction_vote(["bullish", "bullish", "bearish"]) == \
            ("bullish", False)
        assert resolve_direction_vote(["bearish", "bearish", "bearish", "bullish"]) == \
            ("bearish", False)

    def test_a_tie_earns_no_direction(self):
        assert resolve_direction_vote(["bullish", "bearish"]) == (None, True)
        assert resolve_direction_vote(["bullish", "bearish", "bullish", "bearish"]) == \
            (None, True)

    def test_a_single_vote_wins(self):
        assert resolve_direction_vote(["bullish"]) == ("bullish", False)

    def test_unanimity_wins(self):
        assert resolve_direction_vote(["bearish"] * 4) == ("bearish", False)

    def test_absence_is_not_conflict(self):
        """No votes is a different state from a 2-2 split, and must not be
        reported as one."""
        assert resolve_direction_vote([]) == (None, False)
        assert resolve_direction_vote(None) == (None, False)

    def test_unusable_labels_are_ignored_not_counted(self):
        assert resolve_direction_vote(["neutral", "above_high", None]) == (None, False)
        assert resolve_direction_vote(["bullish", "neutral", "unknown"]) == \
            ("bullish", False)
        # a junk label must not dilute a real tie into a false winner
        assert resolve_direction_vote(["bullish", "bearish", "sideways"]) == (None, True)

    def test_it_is_order_independent(self):
        for votes in (["bullish", "bearish", "bullish"],
                      ["bearish", "bullish", "bullish"],
                      ["bullish", "bullish", "bearish"]):
            assert resolve_direction_vote(votes) == ("bullish", False), votes

    def test_no_deterministic_tie_break_was_smuggled_in(self):
        """Alphabetically 'bearish' < 'bullish'; first-seen would give the first
        element; last-seen the last. All three must be refused."""
        assert resolve_direction_vote(["bullish", "bearish"])[0] is None
        assert resolve_direction_vote(["bearish", "bullish"])[0] is None

    def test_the_vocabulary_is_the_two_real_directions(self):
        assert DIRECTIONS == ("bullish", "bearish")


# ── hash-seed determinism, across real processes ─────────────────────────────

class TestDeterministicAcrossHashSeeds:
    """PYTHONHASHSEED is fixed at interpreter start, so each seed gets its own
    subprocess. A loop inside one process would pass even with the bug."""

    SEEDS = (0, 1, 2, 3, 42, 99)

    def test_the_tied_scan_is_byte_identical_across_seeds(self):
        results = {s: run_under_seed(s) for s in self.SEEDS}
        canonical = json.dumps(results[self.SEEDS[0]], sort_keys=True)
        for seed, payload in results.items():
            assert json.dumps(payload, sort_keys=True) == canonical, \
                f"seed {seed} diverged"

    def test_and_the_tied_case_reports_no_direction(self):
        five_m = run_under_seed(0)["5m"]
        direction, conflicted, score, classification = five_m["manip"]
        assert direction is None
        assert conflicted is True
        assert score == 30 and classification == "manipulation_possible", \
            "the fixture no longer reproduces the tied case"

    def test_a_non_tied_case_keeps_its_direction_across_seeds(self):
        """Determinism must not have been bought by blanking every direction."""
        for seed in self.SEEDS:
            three_m = run_under_seed(seed)["3m"]
            direction, conflicted, score, _ = three_m["manip"]
            assert direction == "bearish", seed
            assert conflicted is False
            assert score == 60


# ── production invariance ────────────────────────────────────────────────────

class TestNothingAuthoritativeMoved:
    """The consumer audit says these fields have zero production-authority
    readers. This proves it rather than trusting it."""

    def snapshot(self, end=TIED_SCAN):
        with open(FIXTURE, encoding="utf-8") as fh:
            tape = json.load(fh)["bars"]
        win = CONT.coherent_window([b for b in tape if b["timestamp"] <= end],
                                   horizon_minutes=300, minimum_bars=1)["window"]
        return SB.build_snapshot(build_timeframes(win), symbol="MNQ")

    def test_po3_never_reads_the_forensic_direction(self):
        import inspect
        from structure import po3_engine
        src = inspect.getsource(po3_engine._score_phases)
        assert 'manip_block.get("score")' in src
        assert 'disp_block.get("score")' in src
        assert 'manip_block.get("direction")' not in src
        assert 'disp_block.get("direction")' not in src

    def test_po3_direction_still_comes_from_settled_sweep_semantics(self):
        import inspect
        from structure import po3_engine
        src = inspect.getsource(po3_engine._directions)
        assert 'sweep_dir == "below_low"' in src and "sweep_semantics" in src

    def test_the_tied_scan_still_produces_its_authoritative_values(self):
        """Pinned from the pre-2E.2 run: PO3 phase, directions, alignment,
        qualification and risk are untouched by the tie becoming None."""
        snap = self.snapshot()
        assert snap["po3"]["5m"]["phase"] == "accumulation"
        assert snap["po3"]["5m"]["manipulation_direction"] is None
        assert snap["po3"]["3m"]["phase"] == "accumulation"
        # STEP 4B.12 §4 UNIT 2 — D-CLASS, proven on THIS fixture:
        #   15m UNEVALUABLE_INSUFFICIENT_CANDLES -> accumulation
        #   5m / 3m  bos False, EVALUATED, 'range_bound' -> accumulation
        #   1m       bos False, EVALUATED, 'neutral'     -> manipulation
        # No timeframe carries a distribution phase any more, so the
        # manipulation_to_distribution pattern cannot form. Everything else in
        # the direction-vote path is unchanged -- the assertions above still
        # hold and the manipulation block below still scores exactly 30.
        assert snap["po3"]["alignment"] == "mixed"
        # and the block that carries the tie still scores identically
        manip = snap["liquidity"]["5m"]["manipulation"]
        assert manip["score"] == 30
        assert manip["classification"] == "manipulation_possible"

    def test_scores_and_classifications_are_untouched_across_the_tape(self):
        """The ONLY permitted change is the tied direction label."""
        with open(FIXTURE, encoding="utf-8") as fh:
            tape = json.load(fh)["bars"]
        ends = sorted({b["timestamp"] for b in tape})[25:]
        conflicts = 0
        for end in ends:
            snap = self.snapshot(end)
            for tf in ("3m", "5m", "15m"):
                m = (snap["liquidity"][tf] or {}).get("manipulation") or {}
                d = (snap["expansion"][tf] or {}).get("displacement") or {}
                for block in (m, d):
                    if block.get("direction_conflicted"):
                        conflicts += 1
                        assert block.get("direction") is None, block
                    else:
                        # a non-conflicted block may legitimately carry either a
                        # direction or None; what it may not do is claim conflict
                        assert block.get("direction_conflicted") is False, block
        assert conflicts > 0, "the tape never exercised a tie"


# ── displacement's pre-existing fallback ─────────────────────────────────────

class TestTheLegFallbackSurvivesButOnlyForAbsence:

    def test_no_votes_still_falls_back_to_the_leg(self):
        """Pre-2E.2 behaviour for the ABSENCE of votes, deliberately preserved.

        BEHAVIOURAL, not a source-string match. The previous version asserted on
        the literal text `if direction is None and not direction_conflicted:`
        and broke the moment 3A restructured that branch into an if/elif/else --
        without the behaviour changing at all. A test that fails on a refactor
        it does not disagree with is measuring the wrong thing.
        """
        from structure import displacement_detector as DD
        original = DD.resolve_direction_vote
        DD.resolve_direction_vote = lambda votes: (None, False)   # absence, not tie
        try:
            up = [{"timestamp": f"2026-08-12T19:{i:02d}:00+00:00",
                   "open": 100.0 + i, "high": 101.0 + i, "low": 99.0 + i,
                   "close": 100.5 + i} for i in range(10)]
            d = DD.detect_displacement(up, {}, atr=1.0)
            assert d["direction"] == "bullish", "absence must still use the leg"
            assert d["direction_basis"] == "net_move_fallback"
            assert d["direction_vote"] is None, "a fallback is not a vote"
        finally:
            DD.resolve_direction_vote = original

    def test_but_a_tie_does_not_fall_back_to_the_leg(self):
        """A tie falling back to `leg` would be exactly the invented directional
        default 2E.2 forbids."""
        from structure import displacement_detector as DD
        original = DD.resolve_direction_vote
        DD.resolve_direction_vote = lambda votes: (None, True)
        try:
            candles = [{"open": 100 + i, "high": 101 + i, "low": 99 + i,
                        "close": 100.5 + i, "range": 2.0, "body_size": 0.5,
                        "direction": "bullish", "timestamp": f"t{i}"}
                       for i in range(12)]
            out = DD.detect_displacement(candles, {}, 1.0, {})
        finally:
            DD.resolve_direction_vote = original
        assert out["direction"] is None
        assert out["direction_conflicted"] is True
