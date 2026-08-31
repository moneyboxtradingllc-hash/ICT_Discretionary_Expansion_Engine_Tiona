"""STEP 4B.12 §5 — a negative is a claim, and it needs a capability behind it.

`liquidity[tf]["failed_breakout"]` has been published as `False` on every scan
this bot has ever run. That word asserts a capable detector looked and found
nothing. It never looked, and it cannot: the predicate is unsatisfiable through
two INDEPENDENT contradictions.

    #1 CONTROL FLOW
       high branch reached only when   last_close >= ref_high
       its body requires               last_close <  ref_high

    #2 CANDIDATE UNIVERSE
       ref_high = max(pierced_highs), and pool membership already gives
                                       prior <= ref_high
       the predicate requires          prior >  ref_high

Both symmetric on the low side. #2 is the deeper defect: the proposition cannot
be a DESCENDANT of the pierced pool at all, because pool membership asserts the
prior close sat inside the level while a failed breakout asserts it sat beyond.

These tests do NOT repair the predicate -- the market doctrine it should express
is unresolved, and a reachable sibling with different reference semantics exists
in `manipulation_detector`. They pin the honest REPRESENTATION of the defect so
that a future repair has to be deliberate, and so the Brain stops receiving a
permanent `False` dressed up as evidence.
"""
from __future__ import annotations

import os
import random
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))

from structure.liquidity_engine import (                      # noqa: E402
    CAPABILITY_EVALUATED,
    CAPABILITY_UNAVAILABLE_SENSOR,
    CAPABILITY_UNEVALUABLE_EVIDENCE,
    FAILED_BREAKOUT_UNREACHABLE,
    PRIOR_AUTHORITATIVE,
    PRIOR_NO_OBSERVATION,
    analyze_liquidity,
)



# ── CLASS G PREREQUISITE ONLY (STEP 4B.12 §4 UNIT 1) ─────────────────────────
# The bars here are synthetic and carry no source-member provenance, so no
# canonical swing evidence exists and `find_swings` certifies nothing without
# it. The geometry assumption is requested explicitly so these fixtures can
# still reach their actual subject.
#
# THE SUBJECT IS UNCHANGED: capability semantics. Every EVALUATED /
# UNEVALUABLE_EVIDENCE / UNAVAILABLE_SENSOR assertion below is asserted exactly
# as before. This wrapper supplies a prerequisite; it does not soften a claim.
def analyze_liquidity_geometry_only(*args, **kwargs):
    kwargs.setdefault("allow_uncadenced", True)
    return analyze_liquidity(*args, **kwargs)


def bar(t, o, h, l, c):
    return {"timestamp": f"2026-08-12T18:{t:02d}:00+00:00", "open": o,
            "high": h, "low": l, "close": c, "volume": 10,
            "members": 1, "expected_members": 1, "complete": True}


def a_real_sweep():
    """POSITIVE CONTROL. A swing high at 121 is confirmed by neighbours, then a
    later bar wicks through it to 125 and closes back down at 95. This series
    must produce sweep_detected -- otherwise every 'and failed_breakout stayed
    False' assertion below would be passing for the wrong reason."""
    return [bar(0, 100, 105, 95, 100), bar(1, 100, 110, 98, 108),
            bar(2, 108, 121, 105, 118), bar(3, 118, 112, 100, 104),
            bar(4, 104, 108, 96, 100), bar(5, 100, 125, 94, 95)]


class TestTheSweepFixtureIsNotVacuous:

    def test_the_positive_control_actually_sweeps(self):
        out = analyze_liquidity_geometry_only(a_real_sweep(),
                                {"close": 100.0, "authority": PRIOR_AUTHORITATIVE})
        assert out["sweep_detected"] is True
        assert out["sweep_direction"] == "above_high"


class TestFailedBreakoutIsDeadByConstruction:

    def test_no_generated_series_produces_a_positive(self):
        """FIXED-SEED NON-VACUOUS REGRESSION OVER AN ACTIVE SEARCH SPACE.

        Deliberately NOT called an exhaustion proof. Sampling 4000 generated
        series cannot exhaust the predicate's state space, and saying otherwise
        would weaken the vocabulary this project depends on. Formal
        unreachability is proven separately and more strongly by construction:
        the control-flow contradiction and the candidate-universe contradiction
        in the module docstring.

        What this test adds is that the sampled population is ACTIVE -- sweeps
        really occur in it -- so the zero is silence from a dead branch rather
        than silence from dead inputs. It is a regression guard, not the proof.
        """
        rng = random.Random(41202)      # fixed seed: this must be reproducible
        sweeps = failed = evaluated = 0
        for _ in range(4000):
            price, series = 100.0, []
            for t in range(12):
                o = price
                c = o + rng.uniform(-8, 8)
                h = max(o, c) + rng.uniform(0, 6)
                l = min(o, c) - rng.uniform(0, 6)
                series.append(bar(t, round(o, 2), round(h, 2),
                                  round(l, 2), round(c, 2)))
                price = c
            out = analyze_liquidity_geometry_only(
                series, {"close": series[-2]["close"],
                         "authority": PRIOR_AUTHORITATIVE})
            evaluated += 1
            sweeps += bool(out["sweep_detected"])
            failed += bool(out["failed_breakout"])
        assert sweeps > 0, "search space is dead; the zero below proves nothing"
        assert failed == 0, (
            f"failed_breakout became reachable ({failed}/{evaluated}). If that "
            "is a deliberate repair, this test must be rewritten to state the "
            "new market doctrine -- not deleted.")

    def test_it_is_never_reported_as_ordinary_absence(self):
        out = analyze_liquidity_geometry_only(a_real_sweep(),
                                {"close": 100.0, "authority": PRIOR_AUTHORITATIVE})
        assert out["failed_breakout"] is False
        assert out["proposition_capability"]["failed_breakout"] == \
            CAPABILITY_UNAVAILABLE_SENSOR
        assert out["capability_reason"]["failed_breakout"] == \
            FAILED_BREAKOUT_UNREACHABLE

    def test_sensor_unavailability_outranks_evidence_unavailability(self):
        """It would be unevaluable with PERFECT evidence, so calling it an
        evidence problem would imply better evidence could fix it."""
        out = analyze_liquidity_geometry_only(a_real_sweep(),
                                {"close": None, "authority": PRIOR_NO_OBSERVATION})
        assert out["proposition_capability"]["sweep_detected"] == \
            CAPABILITY_UNEVALUABLE_EVIDENCE
        assert out["proposition_capability"]["failed_breakout"] == \
            CAPABILITY_UNAVAILABLE_SENSOR

    def test_too_few_candles_is_also_not_ordinary_absence(self):
        out = analyze_liquidity_geometry_only([bar(0, 100, 101, 99, 100)])
        caps = out["proposition_capability"]
        assert caps["sweep_detected"] == CAPABILITY_UNEVALUABLE_EVIDENCE
        assert caps["nearest_buy_side_liquidity"] == CAPABILITY_UNEVALUABLE_EVIDENCE
        assert caps["failed_breakout"] == CAPABILITY_UNAVAILABLE_SENSOR
        assert out["capability_reason"]["sweep_detected"] == \
            "INSUFFICIENT_OBSERVATIONS"


class TestCapabilityIsPropositionScoped:
    """STEP 4B.12 again, in the capability layer: one evidence defect may not
    erase an independent fact, and it may not smear doubt over one either."""

    def test_missing_prior_close_does_not_taint_nearest_liquidity(self):
        out = analyze_liquidity_geometry_only(a_real_sweep(),
                                {"close": None, "authority": PRIOR_NO_OBSERVATION})
        caps = out["proposition_capability"]
        assert caps["sweep_detected"] == CAPABILITY_UNEVALUABLE_EVIDENCE
        assert caps["reclaim_detected"] == CAPABILITY_UNEVALUABLE_EVIDENCE
        assert caps["nearest_buy_side_liquidity"] == CAPABILITY_EVALUATED
        assert caps["nearest_sell_side_liquidity"] == CAPABILITY_EVALUATED
        # The load-bearing half: not merely "labelled EVALUATED" but actually
        # UNCHANGED by the missing prior close. Compared against the same series
        # with full authority, so this cannot pass by both sides being None.
        proven = analyze_liquidity_geometry_only(a_real_sweep(),
                                   {"close": 100.0, "authority": PRIOR_AUTHORITATIVE})
        assert proven["nearest_buy_side_liquidity"] is not None, \
            "fixture publishes no buy-side pool; the comparison below is vacuous"
        for key in ("nearest_buy_side_liquidity", "nearest_sell_side_liquidity"):
            assert out[key] == proven[key], \
                "an independent fact moved because of an unrelated evidence defect"

    def test_an_evaluated_proposition_carries_no_excuse(self):
        out = analyze_liquidity_geometry_only(a_real_sweep(),
                                {"close": 100.0, "authority": PRIOR_AUTHORITATIVE})
        reasons = out["capability_reason"]
        assert set(reasons) == {"failed_breakout"}, \
            "listing a reason for a sound fact invites consumers to distrust it"
        assert out["proposition_capability"]["sweep_detected"] == \
            CAPABILITY_EVALUATED


class TestTheBrainCanTellSilenceApartFromIgnorance:
    """STEP 4B.12 §5 at the Brain boundary.

    `_liquidity_lines` emitted a line only on a POSITIVE. So a timeframe whose
    sweep was genuinely absent and a timeframe whose sweep could not be
    evaluated at all produced byte-identical output: nothing. The Brain read
    that silence as settled negative evidence. Same defect as §3H, second site.
    """

    def formatted(self, liq_1m: dict) -> list:
        from ai_layer.ai_snapshot_formatter import _liquidity_lines
        return _liquidity_lines({"1m": liq_1m})

    def evaluated_absent(self) -> dict:
        return analyze_liquidity_geometry_only(
            [bar(0, 100, 101, 99, 100), bar(1, 100, 102, 99, 101),
             bar(2, 101, 103, 100, 102), bar(3, 102, 104, 101, 103)],
            {"close": 101.0, "authority": PRIOR_AUTHORITATIVE})

    def withheld(self) -> dict:
        return analyze_liquidity_geometry_only(a_real_sweep(),
                                 {"close": None, "authority": PRIOR_NO_OBSERVATION})

    def test_the_two_cases_no_longer_produce_identical_output(self):
        """THE load-bearing assertion. If this ever passes by both sides being
        empty it is worthless, so both sides are also checked for content."""
        absent = self.formatted(self.evaluated_absent())
        unknown = self.formatted(self.withheld())
        assert absent != unknown, \
            "a withheld sweep and an absent sweep read identically to the Brain"
        assert any("NOT EVALUATED" in ln for ln in unknown)
        assert not any("NOT EVALUATED" in ln for ln in absent), \
            "an evaluated negative was reported as unknown"

    def test_the_withheld_case_names_the_timeframe_and_the_reason(self):
        line = next(ln for ln in self.formatted(self.withheld())
                    if "NOT EVALUATED" in ln)
        assert "1m" in line
        # §10 sharpened this vocabulary: the reason now names the ACTUAL missing
        # prerequisite rather than a generic "close unavailable".
        assert "previous expected market slot was not observed" in line
        assert "not as absence of a sweep" in line

    def test_a_real_sweep_still_reports_normally(self):
        out = analyze_liquidity_geometry_only(a_real_sweep(),
                                {"close": 100.0, "authority": PRIOR_AUTHORITATIVE})
        lines = self.formatted(out)
        assert any("Liquidity sweep above_high on 1m" in ln for ln in lines)
        assert not any("NOT EVALUATED" in ln for ln in lines)

    def test_the_dead_sensor_is_declared_rather_than_left_silent(self):
        lines = self.formatted(self.evaluated_absent())
        assert any("liquidity_engine sensor is UNAVAILABLE" in ln for ln in lines), \
            "the reader was left to infer a negative from a sensor that never ran"

    def test_the_capability_claim_is_scoped_to_the_SENSOR_not_the_CONCEPT(self):
        """The first version of this line said "no failed-breakout evidence
        exists in either direction" -- and that was FALSE on the very snapshot
        it was measured against, because `manipulation_detector._failed_breakout`
        reported a positive on 3m and 1m of that same scan.

        A capability claim belongs to a sensor. Two producers sharing an English
        name are not one proposition, and a dead one may not speak for the live
        one.
        """
        line = next(ln for ln in self.formatted(self.evaluated_absent())
                    if "UNAVAILABLE" in ln)
        assert "liquidity_engine" in line, "the claim does not name its sensor"
        assert "nothing about failed breakouts seen by any other sensor" in line
        for global_claim in ("no failed-breakout evidence exists",
                            "no failed breakout occurred",
                            "failed breakout is impossible"):
            assert global_claim not in line, \
                f"a sensor capability was stated as a market fact: {global_claim!r}"

    def test_archived_payloads_keep_their_original_silence(self):
        """Snapshots recorded before this contract carry no capability map.
        Inventing an 'unknown' for them would rewrite what the bot knew at the
        time -- the same reasoning as `_bucket_is_settled` trusting unlabelled
        history rather than fabricating incompleteness."""
        legacy = {"sweep_detected": False, "reclaim_detected": False,
                  "failed_breakout": False}
        assert self.formatted(legacy) == []


class TestTheSiblingSensorIsReachable:
    """The repo's ONLY documented definition of the concept lives in
    `manipulation_detector._failed_breakout` -- 'closed beyond a level, then
    closed back inside'. It is reachable, so 'failed breakout' is not an
    impossible market event; only THIS implementation of it is impossible.

    Measured on the real MNQ tape, same 1000 evaluations:
        liquidity[tf]["failed_breakout"]        0
        manipulation component failed_breakout  202

    Pinned so that a future doctrine ruling starts from evidence, not memory.
    """

    def test_the_documented_sibling_can_fire(self):
        from structure.manipulation_detector import _failed_breakout
        window = [bar(0, 100, 101, 99, 100), bar(1, 100, 126, 99, 125),
                  bar(2, 125, 126, 110, 112)]
        present, detail, direction = _failed_breakout(window, [120.0], [90.0])
        assert present is True
        assert direction == "above_high"
        assert "120" in detail

    def test_the_two_sensors_do_not_share_a_reference_rule(self):
        """`manipulation` draws from max(highs); `liquidity` draws from a
        pierced pool. They are not the same proposition, so re-plumbing one into
        the other is a doctrine decision, not a refactor."""
        from structure.manipulation_detector import _failed_breakout
        window = [bar(0, 100, 101, 99, 100), bar(1, 100, 126, 99, 125),
                  bar(2, 125, 126, 110, 112)]
        highs = [120.0, 118.0]
        present, _detail, _d = _failed_breakout(window, highs, [90.0])
        assert present is True, "sibling needs no pierced pool at all"
