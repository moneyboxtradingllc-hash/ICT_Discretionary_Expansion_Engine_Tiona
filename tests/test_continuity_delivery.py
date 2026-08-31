"""A gap must reach the Brain as words, and must refuse an entry.

Detecting a hole is worth nothing if the detection stays inside the data feed.
On 2026-08-11 the organism HAD the evidence that its history was broken -- the
timestamps were right there in the payload -- and no layer was capable of
saying so. `degraded[]` carried only `prior_session_levels_absent`.

So these tests cross the two boundaries that matter:

    scan cycle  -> snapshot["candle_continuity"]
    snapshot    -> brain_input degraded[]          (the Brain is TOLD)
    snapshot    -> CandidateProducer               (an entry is REFUSED)

The refusal is deliberately not "caution about thin data". `find_swings`
confirms a pivot against its neighbours on BOTH sides, so across a hole it can
manufacture the very structure a thesis is priced off. A level derived from
corrupted topology must never reach the risk gate to be judged on its size.
"""
from __future__ import annotations

import json
import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))

from ai_brain.brain_input import build_brain_input               # noqa: E402
from broker.luna_candidate_producer import (                     # noqa: E402
    CandidateProducer, NoCandidate)
from data_feed import candle_continuity as CONT                  # noqa: E402

FIXTURE = os.path.join(ROOT, "tests", "fixtures",
                       "mnq_20260811_1420Z_1510Z_1m.json")
FIRST_MISSING = "2026-08-11T14:42:00+00:00"
LAST_MISSING = "2026-08-11T15:00:00+00:00"


def tape() -> list:
    with open(FIXTURE, encoding="utf-8") as fh:
        return json.load(fh)["bars"]


def holed() -> list:
    return [b for b in tape() if not (FIRST_MISSING <= b["timestamp"] <= LAST_MISSING)]


def snapshot_with(candles: list) -> dict:
    """A snapshot carrying a continuity report for the given tape."""
    return {"timestamp": candles[-1]["timestamp"],
            "candle_continuity": CONT.summarize(candles, timeframe="1m"),
            "timeframes": {"1m": {"recent_candles": candles[-5:]}}}


class TestTheBrainIsTold:

    def test_a_gap_appears_in_degraded(self):
        payload = build_brain_input(snapshot_with(holed()), {})
        markers = [d for d in payload["degraded"] if d.startswith("candle_gap:")]
        assert markers, payload["degraded"]
        assert "missing=19" in markers[0]
        assert "recovered=false" in markers[0]

    def test_a_whole_tape_adds_no_marker(self):
        payload = build_brain_input(snapshot_with(tape()), {})
        assert not [d for d in payload["degraded"] if d.startswith("candle_gap:")]

    def test_the_marker_names_the_actual_missing_span(self):
        payload = build_brain_input(snapshot_with(holed()), {})
        marker = [d for d in payload["degraded"] if d.startswith("candle_gap:")][0]
        assert FIRST_MISSING in marker and LAST_MISSING in marker

    def test_a_snapshot_without_a_report_is_unchanged(self):
        """Older archives and replays carry none; they must still build."""
        payload = build_brain_input(
            {"timestamp": "t", "timeframes": {"1m": {"recent_candles": tape()[-5:]}}}, {})
        assert not [d for d in payload["degraded"] if d.startswith("candle_gap")]

    def test_an_unreadable_report_says_so_rather_than_staying_silent(self):
        snap = snapshot_with(holed())
        snap["candle_continuity"] = {"continuous": False, "gaps": "not-a-list"}
        payload = build_brain_input(snap, {})
        assert any(d.startswith("candle_") for d in payload["degraded"])

    def test_building_the_payload_never_raises_on_a_broken_report(self):
        snap = snapshot_with(holed())
        snap["candle_continuity"] = {"gaps": [{"missing_minutes": "x"}]}
        assert isinstance(build_brain_input(snap, {}), dict)


class TestAnUnrepairedGapRefusesAnEntry:

    def test_a_recent_hole_refuses(self):
        with pytest.raises(NoCandidate) as caught:
            CandidateProducer._assert_candles_continuous(snapshot_with(holed()))
        assert caught.value.reason == "candle_gap_unrecovered"
        assert FIRST_MISSING in str(caught.value)

    def test_a_whole_tape_permits(self):
        CandidateProducer._assert_candles_continuous(snapshot_with(tape()))

    def test_a_repaired_tape_permits(self):
        repaired = CONT.merge(holed(), tape())
        CandidateProducer._assert_candles_continuous(snapshot_with(repaired))

    def test_a_missing_report_is_NOT_treated_as_continuous(self):
        """Absence of evidence is not evidence of absence -- but it is also not
        a refusal, because replays legitimately never measure. It is silence."""
        CandidateProducer._assert_candles_continuous({"timestamp": "t"})

    def test_an_unlocatable_report_refuses(self):
        """No usable `last`, so the horizon cannot be applied -> refuse."""
        with pytest.raises(NoCandidate):
            CandidateProducer._assert_candles_continuous(
                {"candle_continuity": {"continuous": False, "gaps": None,
                                       "last": None}})

    @pytest.mark.parametrize("broken", [
        {"continuous": False, "gaps": "not-iterable-as-dicts", "last": "x"},
        {"continuous": False, "gaps": [None], "last": "2026-08-11T15:10:00+00:00"},
        {"continuous": False, "gaps": [{"missing_minutes": object()}],
         "last": "2026-08-11T15:10:00+00:00"},
    ])
    def test_a_report_that_RAISES_fails_closed(self, broken):
        """The exception path, exercised for real.

        The previous version of this test passed a report that made
        `material_gap` return True by ordinary logic, so the `except` branch was
        never reached -- inverting it to `blocking = False` changed nothing and
        the mutation escaped. A malformed report must refuse, not open.
        """
        with pytest.raises(NoCandidate) as caught:
            CandidateProducer._assert_candles_continuous(
                {"candle_continuity": broken})
        assert caught.value.reason == "candle_gap_unrecovered"

    def test_the_horizon_is_finite_not_the_whole_archive(self):
        assert CandidateProducer.CONTINUITY_HORIZON_MINUTES > 0
        assert CandidateProducer.CONTINUITY_HORIZON_MINUTES <= 24 * 60


class TestTheScanCycleMeasuresIt:

    def test_the_report_is_attached_to_the_snapshot(self):
        import inspect
        from live_scan import production_scan_cycle as PSC
        source = inspect.getsource(PSC.ProductionScanCycle.scan)
        assert 'snapshot["candle_continuity"]' in source, \
            "the scan cycle no longer measures continuity"
        assert "CONT.summarize(candles_1m" in source, \
            "continuity must be measured from the SAME series the engines read"


class TestTheGateIsWIREDNotMerelyDefined:
    """M9 escaped the first campaign: every refusal test called
    `_assert_candles_continuous` directly, so removing its CALL SITE in
    `produce()` changed nothing and all tests still passed.

    That is precisely the failure this whole project keeps rediscovering -- the
    reconcilers had no production caller, the invalidation registry had no
    delivery hop -- a capability that exists and is never invoked. A gate that
    is defined but unwired is not a gate.
    """

    def test_produce_actually_calls_the_continuity_gate(self):
        import inspect
        source = inspect.getsource(CandidateProducer.produce)
        assert "_assert_candles_continuous" in source, \
            "the continuity gate is defined but produce() never calls it"

    def test_the_gate_runs_before_geometry_is_resolved(self):
        """A level derived from corrupted topology must never reach the risk
        gate to be judged on its size."""
        import inspect
        source = inspect.getsource(CandidateProducer.produce)
        gate = source.index("_assert_candles_continuous")
        for later in ("self._invalidation(", "self._objective("):
            assert gate < source.index(later), f"{later} resolves before the gate"

    def test_the_refusal_reason_is_registered_for_tracing(self):
        from broker.luna_candidate_producer import _TRACE_STAGE
        assert "candle_gap_unrecovered" in _TRACE_STAGE
