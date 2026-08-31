"""STEP 4B.12 §11/§12 — raw 1m observations to the serialized Terra payload.

Every unit in this step proved one seam. This proves the CHAIN, because a chain
of correct seams is not itself a guarantee: `ai_context.summary` was perfectly
truthful and never reached Terra at all, and the §10 hole published an honest
`prior_close_authority` beside a capability that contradicted it.

The path under test:

    raw 1m bars
      -> timeframe_builder      aggregation + source-member provenance
      -> venue_calendar         cadence authority + expected terminal
      -> snapshot_builder       previous expected slot + field authority
      -> liquidity_engine       proposition authoring under that authority
      -> build_snapshot         what deterministic consumers read
      -> build_brain_input      what Terra reads
      -> json.dumps             what actually crosses the wire

Eight cases. Each is built by REMOVING or PERTURBING one thing from the healthy
case, so any two that fail to differ are a real information loss and not a
fixture artefact.
"""
from __future__ import annotations

import json
import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))

import market_data.snapshot_builder as SB                           # noqa: E402
import market_data.venue_calendar as VC                             # noqa: E402
from ai_brain.brain_input import build_brain_input                  # noqa: E402
from data_feed.timeframe_builder import build_timeframes            # noqa: E402

_TFS = ("15m", "5m", "3m", "1m")
DAY = "2026-08-12"          # inside the verified ordinary range
# VENUE-CALENDAR-AUTHORITY-HORIZON-1 (2026-08-30): the unverified-date specimen moved from 2026-09-15, which the extended ordinary horizon now covers, to a date the calendar still has no jurisdiction over. The test's subject is unchanged -- it is the date that had to move, not the theorem.
UNVERIFIED = "2027-02-01"   # outside it


def m(day, hh, mm, o, h, l, c):
    return {"timestamp": f"{day}T{hh:02d}:{mm:02d}:00+00:00",
            "open": o, "high": h, "low": l, "close": c, "volume": 10}


#: 18:00 UTC, in minutes since midnight -- the tape's origin.
_ORIGIN = 18 * 60
#: 120 minutes, so EVERY timeframe closes on a complete bucket (120 = 8x15 =
#: 24x5 = 40x3) and every timeframe has enough settled buckets to evaluate.
#:
#: The first version ran forty minutes and CASE A came back
#: UNEVALUABLE_EVIDENCE / INSUFFICIENT_OBSERVATIONS on 15m -- two settled
#: buckets is fewer than MIN_CANDLES, so the engine was right and the fixture
#: was too short. A positive control that cannot reach one timeframe cannot
#: prove anything about it.
_MINUTES = 120


def _at(day, offset, o, h, l, c):
    total = _ORIGIN + offset
    return m(day, total // 60, total % 60, o, h, l, c)


def raw_tape(day=DAY):
    """Two quiet hours holding one raidable pool, then a final-minute raid.

    The pool is a single minute at 19:07 printing 121 -- placed so it is a
    CONFIRMED fractal high on all four timeframes at once (its 15m bucket
    19:00-19:14 is flanked by lower buckets, and likewise for 5m/3m/1m). The
    last minute, 19:59, wicks to 125 and closes back at 95: resting beyond
    price, reached, rejected.

    CASE A proves this really produces a sweep. Everything asserting an absence
    below depends on that, which is why it is tested first and separately.
    """
    bars = []
    for k in range(_MINUTES):
        base = 100.0 + (k % 4)
        bars.append(_at(day, k, base, base + 1, base - 1, base + 0.5))
    bars[67] = _at(day, 67, 108, 121, 105, 118)      # 19:07 — the pool
    bars[68] = _at(day, 68, 118, 112, 100, 104)      # its right shoulder
    bars[119] = _at(day, 119, 100, 125, 94, 95)      # 19:59 — the raid
    return bars


def terra(bars, *, break_calendar=False):
    """The whole chain, exactly as production runs it."""
    raw = build_timeframes(bars)
    original = VC.expected_buckets
    if break_calendar:
        VC.expected_buckets = lambda *a, **k: (_ for _ in ()).throw(
            RuntimeError("calendar unavailable"))
    try:
        snap = SB.build_snapshot(raw, symbol="MNQ")
    finally:
        VC.expected_buckets = original
    payload = build_brain_input(snap, stance_history={})
    return snap, payload, json.dumps(payload, default=str)


def evaluation(payload) -> dict:
    return {r["tf"]: r for r in payload["liquidity"]["evaluation"]}


def sweep_of(snap, tf):
    return ((snap.get("liquidity") or {}).get(tf) or {}).get("sweep_detected")


# --------------------------------------------------------------------------
# The eight cases, each one perturbation away from CASE A.
# --------------------------------------------------------------------------

def case_a():
    """HEALTHY. Canonical previous slot, authoritative close, real raid."""
    return terra(raw_tape())


def case_b():
    """INTERIOR member missing, TERMINAL present. Bucket degraded, close proven."""
    bars = [b for b in raw_tape() if not b["timestamp"].endswith("T19:51:00+00:00")]
    return terra(bars)


def case_c():
    """TERMINAL member missing. Bucket exists, its close cannot be proven."""
    bars = [b for b in raw_tape() if not b["timestamp"].endswith("T19:54:00+00:00")]
    return terra(bars)


def case_d():
    """PREVIOUS EXPECTED SLOT absent. A whole 5m slot never observed."""
    drop = {f"{DAY}T19:{mm}:00+00:00" for mm in range(50, 55)}
    bars = [b for b in raw_tape() if b["timestamp"] not in drop]
    return terra(bars)


def case_e():
    """CADENCE UNKNOWN. Same tape, a date outside the verified ranges."""
    return terra(raw_tape(UNVERIFIED))


def case_f():
    """CALENDAR FAILURE. Cadence machinery raises; array neighbour still exists."""
    return terra(raw_tape(), break_calendar=True)


class TestCaseAIsARealPositive:
    """Everything below asserts an absence. If CASE A were not a genuine
    positive, all of it would pass for the wrong reason."""

    def test_the_chain_produces_a_real_sweep(self):
        snap, payload, _ = case_a()
        assert any(sweep_of(snap, tf) for tf in _TFS), \
            "the healthy tape produced no sweep; every negative below is vacuous"
        assert payload["liquidity"]["events"], "the sweep never reached Terra"

    def test_terra_is_told_the_detector_evaluated(self):
        _snap, payload, _ = case_a()
        for tf in _TFS:
            assert evaluation(payload)[tf]["sweep"]["capability"] == \
                "DETECTOR_EVALUATED"


class TestFieldAuthoritySurvivesTheWholeChain:
    """A DEGRADED CANDLE IS NOT A DEGRADED FIELD -- proven end to end rather
    than at the resolver."""

    def test_case_B_interior_gap_leaves_the_proposition_evaluable(self):
        _snap, payload, _ = case_b()
        caps = {evaluation(payload)[tf]["sweep"]["capability"] for tf in _TFS}
        assert "UNEVALUABLE_EVIDENCE" not in caps, \
            "an interior member gap withheld a close that `bars[-1]` proves"

    def test_case_C_terminal_gap_withholds_with_the_right_reason(self):
        _snap, payload, _ = case_c()
        reasons = {evaluation(payload)[tf]["sweep"].get("reason") for tf in _TFS}
        assert "PREVIOUS_SLOT_CLOSE_UNPROVEN" in reasons

    def test_B_and_C_are_not_the_same_payload(self):
        """They differ by ONE minute, and that minute is the terminal
        constituent. Membership counts cannot tell them apart; identity can."""
        _sa, _pa, blob_b = case_b()
        _sb, _pb, blob_c = case_c()
        assert blob_b != blob_c


class TestEachEvidenceGapKeepsItsOwnName:

    @pytest.mark.parametrize("case,reason", [
        (case_c, "PREVIOUS_SLOT_CLOSE_UNPROVEN"),
        (case_d, "PREVIOUS_SLOT_NOT_OBSERVED"),
        (case_e, "EXPECTED_SLOT_AUTHORITY_UNAVAILABLE"),
        (case_f, "EXPECTED_SLOT_AUTHORITY_UNAVAILABLE"),
    ])
    def test_the_reason_reaches_terra(self, case, reason):
        _snap, payload, _blob = case()
        reasons = {evaluation(payload)[tf]["sweep"].get("reason") for tf in _TFS}
        assert reason in reasons, f"expected {reason}, saw {reasons}"

    def test_a_close_gap_and_a_missing_slot_are_distinguishable(self):
        _s1, p1, _b1 = case_c()
        _s2, p2, _b2 = case_d()
        assert (json.dumps(p1["liquidity"], sort_keys=True, default=str)
                != json.dumps(p2["liquidity"], sort_keys=True, default=str))


class TestNoSyntheticPositiveEscapesToEitherWorld:
    """§10 in the integrated setting: the deterministic booleans and the Terra
    payload must not be able to disagree."""

    @pytest.mark.parametrize("case", [case_c, case_d, case_e, case_f])
    def test_neither_world_reports_a_raid(self, case):
        snap, payload, _blob = case()
        for tf in _TFS:
            liq = (snap.get("liquidity") or {}).get(tf) or {}
            row = evaluation(payload).get(tf, {})
            if row.get("sweep", {}).get("capability") != "DETECTOR_EVALUATED":
                assert liq.get("sweep_detected") is not True, \
                    f"{tf}: a scorer saw a sweep the Brain was told was unknown"
                assert liq.get("reclaim_detected") is not True

    def test_case_F_had_a_usable_number_and_refused_it(self):
        """The whole point of §10: under calendar failure the array neighbour's
        close is present and numeric. Availability is not authorisation."""
        bars = raw_tape()
        raw = build_timeframes(bars)
        assert raw["5m"][-2]["close"] is not None, \
            "no array neighbour to refuse; this test proves nothing"
        snap, payload, _ = case_f()
        assert payload["liquidity"]["events"] == []
        assert not any(sweep_of(snap, tf) for tf in _TFS)


class TestTheDeadSensorAndLegacyInputs:

    def test_case_G_failed_breakout_is_sensor_scoped_everywhere(self):
        _snap, payload, blob = case_a()
        rec = payload["liquidity"]["sensors"]["liquidity_engine.failed_breakout"]
        assert rec["capability"] == "UNAVAILABLE_SENSOR"
        assert rec["reason"] == "PREDICATE_UNREACHABLE_DOCTRINE_UNRESOLVED"
        assert '"failed_breakout": false' not in blob.lower(), \
            "a market negative was published for a sensor that cannot evaluate"

    def test_case_G_survives_every_other_failure(self):
        """Restoring cadence would not make the predicate reachable, so it must
        never be relabelled as an evidence or cadence problem."""
        for case in (case_c, case_d, case_e, case_f):
            _snap, payload, _blob = case()
            rec = payload["liquidity"]["sensors"]["liquidity_engine.failed_breakout"]
            assert rec["capability"] == "UNAVAILABLE_SENSOR"

    def test_case_H_archived_input_is_not_given_knowledge_it_never_had(self):
        """A snapshot recorded before the capability contract declares nothing.
        Backfilling DETECTOR_EVALUATED would rewrite what the bot knew then."""
        legacy = {tf: {"sweep_detected": False, "reclaim_detected": False,
                       "failed_breakout": False} for tf in _TFS}
        payload = build_brain_input({"timestamp": "t", "liquidity": legacy},
                                    stance_history={})
        for tf in _TFS:
            entry = evaluation(payload)[tf]["sweep"]
            assert entry["capability"] == "UNKNOWN"
            assert entry["reason"] == "PRODUCER_DID_NOT_STATE_CAPABILITY"
        assert "sensors" not in payload["liquidity"], \
            "a sensor capability was invented for a producer that declared none"


class TestAllEightCasesAreMutuallyDistinguishable:

    #: E and F are the ONE pair that must NOT differ at the Brain boundary.
    #: An unverified schedule and a calendar machinery failure have the same
    #: proposition-level consequence -- the previous expected slot cannot be
    #: identified -- and Terra has no use for which internal component was
    #: unavailable. Their forensic distinction lives in diagnostics instead.
    _INTENTIONALLY_IDENTICAL_TO_TERRA = {("E_cadence_unknown", "F_calendar_failure")}

    def payloads(self):
        out = {}
        for name, case in (("A_healthy", case_a), ("B_interior_gap", case_b),
                           ("C_terminal_gap", case_c), ("D_slot_absent", case_d),
                           ("E_cadence_unknown", case_e),
                           ("F_calendar_failure", case_f)):
            snap, payload, _blob = case()
            out[name] = (snap, json.dumps(payload["liquidity"], sort_keys=True,
                                          default=str))
        return out

    def test_no_two_cases_collide_except_the_sanctioned_pair(self):
        """The single assertion this whole module exists to make. Any collision
        is an information loss somewhere in the chain, whatever each individual
        seam claims about itself -- with one deliberate exception, named above
        rather than tolerated silently."""
        blobs = {k: v[1] for k, v in self.payloads().items()}
        collisions = {(a, b) for a in blobs for b in blobs
                      if a < b and blobs[a] == blobs[b]}
        assert collisions == self._INTENTIONALLY_IDENTICAL_TO_TERRA, \
            f"unexpected indistinguishable Terra payloads: " \
            f"{collisions - self._INTENTIONALLY_IDENTICAL_TO_TERRA}"

    def test_the_sanctioned_pair_is_still_separable_forensically(self):
        """Same consequence, different cause. Terra is spared the implementation
        detail; the archive must not be. This is what stops the sanctioned
        collision above from becoming an excuse to lose the distinction.

        Found by this module: before it, `cadence_rule` died inside the resolver
        and the two incidents were byte-identical EVERYWHERE downstream.
        """
        snaps = {k: v[0] for k, v in self.payloads().items()}
        rules = {}
        for name in ("E_cadence_unknown", "F_calendar_failure"):
            liq = (snaps[name].get("liquidity") or {}).get("5m") or {}
            assert liq.get("prior_close_authority") == "PREVIOUS_SLOT_CADENCE_UNKNOWN"
            rules[name] = liq.get("prior_cadence_rule")
            assert rules[name], f"{name} lost its forensic cause"
        assert rules["E_cadence_unknown"] != rules["F_calendar_failure"]
        assert "OUTSIDE_AUTHORITY" in rules["E_cadence_unknown"]
        assert "calendar unavailable" in rules["F_calendar_failure"]

    def test_the_implementation_detail_does_not_reach_terra(self):
        """The other half of the same contract: diagnostics keep the cause, the
        Brain does not receive raw exception text."""
        for case in (case_e, case_f):
            _snap, _payload, blob = case()
            assert "prior_cadence_rule" not in blob
            assert "calendar unavailable" not in blob


# --------------------------------------------------------------------------
# STEP 4B.12 §4 UNIT 3 — STRUCTURE EPISTEMICS OVER THE SAME REAL CHAIN.
#
# The liquidity cases above already build raw bars, run the production snapshot
# builder, and construct the actual Brain payload. Structure rides that same
# chain, so its epistemics are certified here rather than against a replica
# serializer -- and the perturbations that starve liquidity of a previous close
# starve the BOS transition of exactly the same evidence.
# --------------------------------------------------------------------------
class TestStructureEpistemicsReachTerra:

    def bos(self, payload, tf):
        return payload["STRUCTURE_WITNESS"][tf]["bos_evaluation"]

    def mss(self, payload, tf):
        return payload["STRUCTURE_WITNESS"][tf]["mss_evaluation"]

    def test_case_A_evaluated_negative_says_so(self):
        _snap, payload, _blob = case_a()
        row = payload["STRUCTURE_WITNESS"]["5m"]
        assert row["bos_event"] is False
        assert self.bos(payload, "5m") == {"capability": "DETECTOR_EVALUATED",
                                           "reason": None}

    def test_case_C_unevaluable_close_reaches_terra_with_its_cause(self):
        _snap, payload, blob = case_c()
        assert payload["STRUCTURE_WITNESS"]["5m"]["bos_event"] is False
        assert self.bos(payload, "5m") == {
            "capability": "UNEVALUABLE_EVIDENCE",
            "reason": "UNEVALUABLE_PREVIOUS_CLOSE"}
        assert "UNEVALUABLE_PREVIOUS_CLOSE" in blob

    def test_case_D_missing_slot_keeps_its_own_name(self):
        _snap, payload, blob = case_d()
        assert self.bos(payload, "5m")["reason"] == "UNEVALUABLE_PREVIOUS_SLOT"
        assert "UNEVALUABLE_PREVIOUS_SLOT" in blob

    def test_cadence_loss_is_evidence_shaped_not_a_dead_sensor(self):
        """0/1000 on tape; the real chain reaches it, so it is not synthetic."""
        for case in (case_e, case_f):
            _snap, payload, _blob = case()
            for tf in ("1m", "3m", "5m", "15m"):
                ev = self.bos(payload, tf)
                assert ev["capability"] == "UNEVALUABLE_EVIDENCE"
                assert ev["reason"] == "UNEVALUABLE_CADENCE"

    def test_the_evaluated_and_unevaluable_payloads_differ(self):
        """The measured defect: these two blobs used to be indistinguishable."""
        _sa, pa, _ba = case_a()
        _sc, pc, _bc = case_c()
        assert pa["STRUCTURE_WITNESS"]["5m"]["bos_event"] == \
            pc["STRUCTURE_WITNESS"]["5m"]["bos_event"]
        assert pa["STRUCTURE_WITNESS"]["5m"] != pc["STRUCTURE_WITNESS"]["5m"]
        assert json.dumps(pa["STRUCTURE_WITNESS"], default=str, sort_keys=True) \
            != json.dumps(pc["STRUCTURE_WITNESS"], default=str, sort_keys=True)

    def test_mss_carries_the_same_distinction_over_the_real_chain(self):
        _sa, pa, _ba = case_a()
        _sc, pc, _bc = case_c()
        assert pa["STRUCTURE_WITNESS"]["5m"]["mss_event"] is False
        assert pc["STRUCTURE_WITNESS"]["5m"]["mss_event"] is False
        assert self.mss(pa, "5m")["capability"] == "DETECTOR_EVALUATED"
        assert self.mss(pc, "5m") == {"capability": "UNEVALUABLE_EVIDENCE",
                                      "reason": "UNEVALUABLE_TRANSITION"}

    def test_every_case_states_a_capability_for_every_timeframe(self):
        """No missing row anywhere on the real chain: silence is never inferred."""
        for case in (case_a, case_b, case_c, case_d, case_e, case_f):
            _snap, payload, _blob = case()
            for tf in ("1m", "3m", "5m", "15m"):
                for prop in ("bos_evaluation", "mss_evaluation"):
                    cap = payload["STRUCTURE_WITNESS"][tf][prop]["capability"]
                    assert cap in ("DETECTOR_EVALUATED", "UNEVALUABLE_EVIDENCE",
                                   "UNKNOWN")
                    assert cap != "UNAVAILABLE_SENSOR"

    def test_terra_is_never_handed_a_directional_structure_verdict(self):
        _snap, payload, _blob = case_a()
        for tf in ("1m", "3m", "5m", "15m"):
            assert set(payload["STRUCTURE_WITNESS"][tf]) == {
                "last_swing_high", "last_swing_low", "bos_event", "mss_event",
                "bos_evaluation", "mss_evaluation"}
