"""STEP 4B.12 §5 — `brain_input` is the epistemic border checkpoint.

Everything upstream was already truthful. `liquidity_engine` published
capability, the snapshot preserved it, the archive formatter preserved it -- and
`build_brain_input` emitted a POSITIVE-ONLY `events[]` list, so Terra received a
payload in which "the detector ran and found no sweep" and "the detector could
not answer" were byte-identical.

Traced on the real tape before the repair:

    'failed_breakout'        in Terra payload: False
    'proposition_capability' in Terra payload: False
    'UNAVAILABLE_SENSOR'     in Terra payload: False
    'prior_close_authority'  in Terra payload: False

Perfect upstream truth does not survive a checkpoint that throws away the
passport. These tests assert the SERIALIZED payload, not intermediate dicts,
because the payload is what Terra actually reads.
"""
from __future__ import annotations

import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))

from ai_brain.brain_input import build_brain_input                 # noqa: E402
from structure.liquidity_engine import (                           # noqa: E402
    PRIOR_AUTHORITATIVE, PRIOR_CLOSE_UNPROVEN, PRIOR_NO_OBSERVATION,
    analyze_liquidity,
)

_TFS = ("15m", "5m", "3m", "1m")


def bar(t, o, h, l, c):
    return {"timestamp": f"2026-08-12T18:{t:02d}:00+00:00", "open": o,
            "high": h, "low": l, "close": c, "volume": 10,
            "members": 1, "expected_members": 1, "complete": True}


def sweeping_series():
    """Swing high confirmed at 121, then a bar wicks to 125 and closes at 95."""
    return [bar(0, 100, 105, 95, 100), bar(1, 100, 110, 98, 108),
            bar(2, 108, 121, 105, 118), bar(3, 118, 112, 100, 104),
            bar(4, 104, 108, 96, 100), bar(5, 100, 125, 94, 95)]


def quiet_series():
    return [bar(0, 100, 101, 99, 100), bar(1, 100, 102, 99, 101),
            bar(2, 101, 103, 100, 102), bar(3, 102, 104, 101, 103)]


def payload(candles, prior) -> dict:
    """A Terra payload whose every timeframe carries the same liquidity block,
    so the assertions below are about the CONTRACT, not about one timeframe."""
    # CLASS G PREREQUISITE, BELOW THE BRAIN BOUNDARY ONLY. The bars are
    # synthetic with no source-member provenance, so canonical swing evidence
    # cannot exist and `find_swings` would certify nothing. The geometry
    # assumption is made here, at the liquidity producer -- NOT at
    # `build_brain_input`, which owns the contract actually under test.
    #
    # Every evaluated-negative / unevaluable / unavailable-sensor distinction
    # below is asserted unchanged.
    liq = {tf: analyze_liquidity(candles, prior, allow_uncadenced=True)
           for tf in _TFS}
    snapshot = {"timestamp": "2026-08-12T18:20:00+00:00", "session": "rth",
                "liquidity": liq,
                "timeframes": {tf: {"recent_candles": candles} for tf in _TFS}}
    return build_brain_input(snapshot, stance_history={})


def rows(pl) -> dict:
    return {r["tf"]: r for r in pl["liquidity"]["evaluation"]}


class TestTheThreeCasesAreStructurallyDistinguishable:
    """CASE A positive+evaluated, CASE B evaluated no positive, CASE C
    unevaluable. All three must differ in the SERIALIZED payload."""

    def case_a(self):
        return payload(sweeping_series(),
                       {"close": 100.0, "authority": PRIOR_AUTHORITATIVE})

    def case_b(self):
        return payload(quiet_series(),
                       {"close": 101.0, "authority": PRIOR_AUTHORITATIVE})

    def case_c(self):
        return payload(sweeping_series(),
                       {"close": None, "authority": PRIOR_NO_OBSERVATION})

    def test_case_A_positive_and_evaluated(self):
        pl = self.case_a()
        assert pl["liquidity"]["events"], "a real sweep produced no event"
        assert all(r["sweep"]["capability"] == "DETECTOR_EVALUATED"
                   for r in rows(pl).values())

    def test_case_B_evaluated_with_no_positive(self):
        pl = self.case_b()
        assert pl["liquidity"]["events"] == []
        for tf in _TFS:
            assert rows(pl)[tf]["sweep"]["capability"] == "DETECTOR_EVALUATED"
            assert "reason" not in rows(pl)[tf]["sweep"]

    def test_case_C_unevaluable_with_the_exact_reason(self):
        pl = self.case_c()
        assert pl["liquidity"]["events"] == []
        for tf in _TFS:
            entry = rows(pl)[tf]["sweep"]
            assert entry["capability"] == "UNEVALUABLE_EVIDENCE"
            assert entry["reason"] == "PREVIOUS_SLOT_NOT_OBSERVED"

    def test_all_three_serialize_differently(self):
        """THE load-bearing assertion. Before the repair B and C were identical
        payloads. Compared as JSON because that is what crosses the wire."""
        a = json.dumps(self.case_a()["liquidity"], sort_keys=True, default=str)
        b = json.dumps(self.case_b()["liquidity"], sort_keys=True, default=str)
        c = json.dumps(self.case_c()["liquidity"], sort_keys=True, default=str)
        assert a != b and b != c and a != c, \
            "two different epistemic states produced one Terra payload"

    def test_B_and_C_are_the_pair_that_used_to_collide(self):
        """Named separately because this specific pair is the defect: both have
        an EMPTY events list, so only the evaluation lane separates them."""
        b, c = self.case_b(), self.case_c()
        assert b["liquidity"]["events"] == c["liquidity"]["events"] == []
        assert rows(b)["3m"]["sweep"] != rows(c)["3m"]["sweep"]

    def test_the_two_reasons_for_unevaluable_stay_distinct(self):
        """A missing observation and an unprovable close are different evidence
        gaps. When this was first written both collapsed to one reason string
        upstream, so it could only pin the CHANNEL. §10 gave each its own
        vocabulary, so the distinction itself is now assertable."""
        unproven = payload(sweeping_series(),
                           {"close": None, "authority": PRIOR_CLOSE_UNPROVEN})
        absent = self.case_c()
        for pl in (unproven, absent):
            assert rows(pl)["1m"]["sweep"]["capability"] == "UNEVALUABLE_EVIDENCE"
        assert rows(unproven)["1m"]["sweep"]["reason"] == "PREVIOUS_SLOT_CLOSE_UNPROVEN"
        assert rows(absent)["1m"]["sweep"]["reason"] == "PREVIOUS_SLOT_NOT_OBSERVED"
        assert rows(unproven)["1m"]["sweep"] != rows(absent)["1m"]["sweep"]


class TestEveryTimeframeStatesItsEvaluability:

    def test_no_timeframe_is_left_to_inference(self):
        """A first design emitted rows only for EXCEPTIONAL timeframes, which
        would have made Terra infer DETECTOR_EVALUATED from a MISSING row --
        absence-as-semantics, one layer later. Silence is evidence only where
        the detector had an opportunity to speak, so the opportunity is
        enumerated."""
        pl = payload(quiet_series(),
                     {"close": 101.0, "authority": PRIOR_AUTHORITATIVE})
        assert set(rows(pl)) == set(_TFS)
        for tf in _TFS:
            assert "sweep" in rows(pl)[tf] and "reclaim" in rows(pl)[tf]

    def test_a_timeframe_with_no_detector_output_says_so(self):
        pl = build_brain_input({"timestamp": "t", "liquidity": {}},
                               stance_history={})
        for tf in _TFS:
            entry = rows(pl)[tf]["sweep"]
            assert entry["capability"] == "UNKNOWN"
            assert entry["reason"] == "NO_DETECTOR_OUTPUT_FOR_TIMEFRAME"

    def test_a_producer_predating_the_contract_is_not_given_one(self):
        """Archived snapshots declare no capability. Inventing DETECTOR_EVALUATED
        for them would rewrite what the bot knew at the time."""
        legacy = {tf: {"sweep_detected": False, "reclaim_detected": False,
                       "failed_breakout": False} for tf in _TFS}
        pl = build_brain_input({"timestamp": "t", "liquidity": legacy},
                               stance_history={})
        for tf in _TFS:
            entry = rows(pl)[tf]["sweep"]
            assert entry["capability"] == "UNKNOWN"
            assert entry["reason"] == "PRODUCER_DID_NOT_STATE_CAPABILITY"
        assert "sensors" not in pl["liquidity"], \
            "a sensor capability was fabricated for a producer that declared none"

    def test_the_legend_defines_every_class_terra_can_receive(self):
        pl = payload(quiet_series(),
                     {"close": 101.0, "authority": PRIOR_AUTHORITATIVE})
        legend = pl["liquidity"]["capability_legend"]
        for cls in ("DETECTOR_EVALUATED", "UNEVALUABLE_EVIDENCE",
                    "UNAVAILABLE_SENSOR", "UNKNOWN"):
            assert cls in legend and legend[cls]
        assert "NOT proof the pattern is absent" in legend["DETECTOR_EVALUATED"], \
            "DETECTOR_EVALUATED must not read to Terra as FALSE_PROVEN"


class TestTheDeadSensorReachesTerraAsCapabilityNotAsFalse:

    def pl(self):
        return payload(sweeping_series(),
                       {"close": 100.0, "authority": PRIOR_AUTHORITATIVE})

    def test_it_arrives_sensor_keyed(self):
        rec = self.pl()["liquidity"]["sensors"]["liquidity_engine.failed_breakout"]
        assert rec["capability"] == "UNAVAILABLE_SENSOR"
        assert rec["reason"] == "PREDICATE_UNREACHABLE_DOCTRINE_UNRESOLVED"
        assert sorted(rec["timeframes"]) == sorted(_TFS)

    def test_no_market_boolean_is_presented_to_terra(self):
        """A capability record is not a market claim. Publishing `False` beside
        it would hand back the exact confusion the record exists to prevent."""
        blob = json.dumps(self.pl()["liquidity"], default=str)
        assert '"failed_breakout": false' not in blob.lower()
        assert "failed_breakout" in blob, "the capability record vanished"

    def test_the_record_does_not_speak_for_the_market_or_other_sensors(self):
        rec = self.pl()["liquidity"]["sensors"]["liquidity_engine.failed_breakout"]
        assert "not a claim that failed breakouts did or did not occur" in \
            rec["scope_note"]
        assert "does not speak for any other sensor" in rec["scope_note"]

    def test_the_live_manipulation_sibling_is_NOT_wired_in(self):
        """`manipulation_detector._failed_breakout` fires 202/1000 on the real
        tape, but exposing it to Terra hands over NEW market evidence, which is
        a doctrine decision and not an epistemics repair. It stays out until
        canonical failed-breakout doctrine is ruled.
        """
        liq = {tf: dict(analyze_liquidity(sweeping_series(),
                                         {"close": 100.0,
                                          "authority": PRIOR_AUTHORITATIVE},
                                         allow_uncadenced=True),
                        manipulation={"score": 40, "components": [
                            {"name": "failed_breakout", "present": True,
                             "points": 15, "detail": "closed above 120 then back below"}]})
               for tf in _TFS}
        pl = build_brain_input({"timestamp": "t", "liquidity": liq},
                               stance_history={})
        blob = json.dumps(pl, default=str)
        assert "closed above 120 then back below" not in blob, \
            "the manipulation sibling leaked into the Terra payload"
        sensors = pl["liquidity"]["sensors"]
        assert list(sensors) == ["liquidity_engine.failed_breakout"], \
            "a second failed-breakout producer appeared under Terra's eyes"


class TestThePositiveInventoryIsUnchanged:
    """`events[]` is consumed as a positive fact list. The evaluability lane is
    additive; it may not alter what a positive-triggered consumer sees."""

    def test_a_real_sweep_still_produces_the_same_event_shape(self):
        pl = payload(sweeping_series(),
                     {"close": 100.0, "authority": PRIOR_AUTHORITATIVE})
        ev = pl["liquidity"]["events"][0]
        assert ev["tf"] in _TFS
        assert ev["sweep"] == "above_high"
        assert ev["reclaim"] is True

    def test_nearest_liquidity_survives_an_unrelated_evidence_defect(self):
        proven = payload(sweeping_series(),
                         {"close": 100.0, "authority": PRIOR_AUTHORITATIVE})
        withheld = payload(sweeping_series(),
                           {"close": None, "authority": PRIOR_NO_OBSERVATION})
        assert proven["liquidity"]["nearest_buy_side"] is not None, \
            "fixture publishes no buy-side pool; the comparison is vacuous"
        for key in ("nearest_buy_side", "nearest_sell_side"):
            assert proven["liquidity"][key] == withheld["liquidity"][key]
