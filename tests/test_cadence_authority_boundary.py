"""STEP 4B.12 §9 RESIDUE + §10 — array adjacency may not author market adjacency
when cadence authority is unknown or unavailable.

Two failures, one law:

    A. UNVERIFIED SCHEDULE. `is_expected` is False for every minute of an
       unverified date, so `expected_buckets` returns [] -- and the caller read
       that as "no expected slot sits between these bars" when the calendar had
       actually said "I have no jurisdiction here". Silence from an authority
       that never had jurisdiction became proof of absence.

    B. CALENDAR FAILURE. The exception path returned UNCADENCED_LEGACY, whose
       consumer bridged to `candles[-2]`.

Neither can identify the immediately previous EXPECTED market slot, so neither
may author a prior-close-dependent proposition.

WHY THE LABEL-ONLY FIX WAS REJECTED. Marking capability UNEVALUABLE_EVIDENCE
while still COMPUTING sweep/reclaim from a bridged close repairs what Terra is
told and leaves the booleans intact for the scoring, routing and
positive-trigger consumers that never read capability -- two different realities
inside one engine. The refusal therefore lives at the authoring boundary.
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
from structure.liquidity_engine import (                            # noqa: E402
    CAPABILITY_EVALUATED, CAPABILITY_UNAVAILABLE_SENSOR,
    CAPABILITY_UNEVALUABLE_EVIDENCE, MIN_CANDLES, PRIOR_ADJACENT,
    PRIOR_AUTHORITATIVE, PRIOR_CADENCE_UNKNOWN, PRIOR_CLOSE_UNPROVEN,
    PRIOR_MAY_AUTHOR, PRIOR_NO_OBSERVATION, PRIOR_UNCADENCED,
    analyze_liquidity)

_TFS = ("15m", "5m", "3m", "1m")


def bar(day, hh, mm, o, h, l, c):
    return {"timestamp": f"{day}T{hh:02d}:{mm:02d}:00+00:00", "open": o,
            "high": h, "low": l, "close": c, "volume": 10,
            "members": 1, "expected_members": 1, "complete": True}


def real_sweep(day="2026-08-12"):
    """POSITIVE CONTROL SERIES. A swing high confirmed at 121, then a bar wicks
    through it to 125 and closes back at 95. Under authoritative cadence this
    MUST produce a sweep -- otherwise every "no positive" assertion below would
    be passing because nothing was ever there."""
    rows = [(0, 100, 105, 95, 100), (1, 100, 110, 98, 108),
            (2, 108, 121, 105, 118), (3, 118, 112, 100, 104),
            (4, 104, 108, 96, 100), (5, 100, 125, 94, 95)]
    return [bar(day, 18, m, o, h, l, c) for m, o, h, l, c in rows]



# ── CLASS P, NOT CLASS G (STEP 4B.12 §4 UNIT 1) ──────────────────────────────
# This file's SUBJECT is cadence / previous-slot authority, so it must NOT waive
# swing authority to get green. It does not have to: these bars are real 1m
# objects on a VERIFIED date carrying `expected_members`, so canonical swing
# evidence genuinely exists for them and is supplied instead of bypassed.
#
# Only 2 of 23 tests ever needed it -- the two that require a POSITIVE sweep.
# Every cadence-authority assertion in this file passed untouched.
def real_swing_evidence(series):
    from market_data.swing_evidence import build_swing_evidence
    return build_swing_evidence(series, series, 1)


class TestTheAuthorityTableIsExhaustiveAndClosed:

    def test_every_state_the_resolver_can_return_is_classified(self):
        for state in (PRIOR_ADJACENT, PRIOR_AUTHORITATIVE, PRIOR_CLOSE_UNPROVEN,
                      PRIOR_NO_OBSERVATION, PRIOR_CADENCE_UNKNOWN,
                      PRIOR_UNCADENCED):
            assert state in PRIOR_MAY_AUTHOR, f"{state} has no authority ruling"

    def test_only_two_states_may_author(self):
        allowed = {k for k, v in PRIOR_MAY_AUTHOR.items() if v}
        assert allowed == {PRIOR_ADJACENT, PRIOR_AUTHORITATIVE}

    def test_an_unrecognised_authority_never_authors(self):
        """An unknown authority is an unknown, and unknown never authorises. The
        next exotic state must not become good enough by carrying a float."""
        out = analyze_liquidity(real_sweep(),
                                {"authority": "SOME_FUTURE_STATE", "close": 100.0})
        assert out["sweep_detected"] is False
        assert out["proposition_capability"]["sweep_detected"] == \
            CAPABILITY_UNEVALUABLE_EVIDENCE

    def test_a_value_alone_does_not_authorise(self):
        """The old resolver asked `prior_close is not None`. A perfectly good
        float under a non-authorising state must still be refused."""
        out = analyze_liquidity(real_sweep(),
                                {"authority": PRIOR_CADENCE_UNKNOWN, "close": 100.0})
        assert out["sweep_detected"] is False


class TestThePositiveControlIsReal:

    def test_authoritative_cadence_produces_a_genuine_sweep(self):
        series = real_sweep()
        out = analyze_liquidity(series,
                                {"authority": PRIOR_AUTHORITATIVE, "close": 100.0},
                                swing_evidence=real_swing_evidence(series))
        assert out["sweep_detected"] is True
        assert out["sweep_direction"] == "above_high"
        assert out["reclaim_detected"] is True
        assert out["proposition_capability"]["sweep_detected"] == CAPABILITY_EVALUATED


class TestCadenceFailureCannotAuthorABoolean:
    """The same series, the same geometry, only cadence authority removed."""

    def under(self, authority):
        series = real_sweep()
        # Real swing evidence, deliberately: the variable under test is the
        # PRIOR-CLOSE authority state, so swing authority is held constant and
        # authoritative rather than waived.
        return analyze_liquidity(series, {"authority": authority},
                                 swing_evidence=real_swing_evidence(series))

    @pytest.mark.parametrize("authority", [PRIOR_CADENCE_UNKNOWN, PRIOR_UNCADENCED,
                                           PRIOR_NO_OBSERVATION, PRIOR_CLOSE_UNPROVEN])
    def test_no_positive_survives_a_non_authorising_state(self, authority):
        out = self.under(authority)
        assert out["sweep_detected"] is False
        assert out["sweep_direction"] is None
        assert out["reclaim_detected"] is False

    @pytest.mark.parametrize("authority,reason", [
        (PRIOR_CADENCE_UNKNOWN, "EXPECTED_SLOT_AUTHORITY_UNAVAILABLE"),
        (PRIOR_UNCADENCED, "NO_CADENCE_SUPPLIED"),
        (PRIOR_NO_OBSERVATION, "PREVIOUS_SLOT_NOT_OBSERVED"),
        (PRIOR_CLOSE_UNPROVEN, "PREVIOUS_SLOT_CLOSE_UNPROVEN"),
    ])
    def test_the_reason_names_the_actual_missing_prerequisite(self, authority, reason):
        """A calendar-authority failure reported as a close problem would tell a
        reader better price data could repair it. Nothing is wrong with the
        candles in that case."""
        out = self.under(authority)
        assert out["capability_reason"]["sweep_detected"] == reason

    def test_independent_facts_are_untouched(self):
        series = real_sweep()
        proven = analyze_liquidity(series,
                                   {"authority": PRIOR_AUTHORITATIVE, "close": 100.0},
                                   swing_evidence=real_swing_evidence(series))
        withheld = self.under(PRIOR_CADENCE_UNKNOWN)
        assert proven["nearest_buy_side_liquidity"] is not None, \
            "fixture publishes no buy-side pool; the comparison is vacuous"
        for key in ("nearest_buy_side_liquidity", "nearest_sell_side_liquidity"):
            assert withheld[key] == proven[key]
        assert withheld["proposition_capability"]["nearest_buy_side_liquidity"] == \
            CAPABILITY_EVALUATED

    def test_the_dead_sensor_still_dominates(self):
        """Restoring cadence would not make that predicate reachable, so it is
        not a cadence problem and must not be relabelled as one."""
        out = self.under(PRIOR_CADENCE_UNKNOWN)
        assert out["proposition_capability"]["failed_breakout"] == \
            CAPABILITY_UNAVAILABLE_SENSOR
        assert out["capability_reason"]["failed_breakout"] == \
            "PREDICATE_UNREACHABLE_DOCTRINE_UNRESOLVED"


class TestTheResolverConvergesBothFailures:

    def series(self, day):
        raw = build_timeframes([bar(day, 18, m, 100.0 + m, 101.0 + m,
                                    99.0 + m, 100.5 + m) for m in range(15)])["5m"]
        return raw, [raw[0], raw[-1]]

    def test_an_unverified_schedule_is_cadence_unknown_not_adjacency(self):
        """§9 RESIDUE. This previously returned ADJACENT_SETTLED: the array
        neighbour was asserted to be the previous market slot purely because an
        authority with no jurisdiction returned an empty list."""
        raw, settled = self.series("2027-02-01")
        out = SB._previous_slot_close(settled, raw, 5)
        assert out["authority"] == PRIOR_CADENCE_UNKNOWN
        assert "close" not in out, "a close was published without cadence authority"
        assert "OUTSIDE_AUTHORITY" in out["cadence_rule"]

    def test_a_verified_schedule_still_resolves_normally(self):
        raw, settled = self.series("2026-08-12")
        out = SB._previous_slot_close(settled, raw, 5)
        assert out["authority"] in (PRIOR_ADJACENT, PRIOR_AUTHORITATIVE)

    def test_a_calendar_failure_is_cadence_unknown_not_uncadenced_legacy(self):
        """§10. The exception path returned UNCADENCED_LEGACY, which the consumer
        bridged. Both failures now converge on one non-authorising state."""
        raw, settled = self.series("2026-08-12")
        original = VC.expected_buckets
        VC.expected_buckets = lambda *a, **k: (_ for _ in ()).throw(
            RuntimeError("calendar unavailable"))
        try:
            out = SB._previous_slot_close(settled, raw, 5)
        finally:
            VC.expected_buckets = original
        assert out["authority"] == PRIOR_CADENCE_UNKNOWN
        assert "close" not in out
        assert "calendar unavailable" in out["cadence_rule"]


class TestDeterministicConsumersCannotSeeSyntheticPositives:
    """THE reason a capability-only repair was insufficient. These consumers
    read the booleans and never read capability."""

    def snapshot_under_calendar_failure(self):
        bars = [bar("2026-08-12", 18, m, 100.0 + m, 101.0 + m, 99.0 + m,
                    100.5 + m) for m in range(40)]
        bars += real_sweep()[-1:]
        raw = build_timeframes(bars)
        original = VC.expected_buckets
        VC.expected_buckets = lambda *a, **k: (_ for _ in ()).throw(
            RuntimeError("calendar unavailable"))
        try:
            return SB.build_snapshot(raw, symbol="MNQ")
        finally:
            VC.expected_buckets = original

    def test_no_boolean_positive_is_emitted_from_a_bridged_close(self):
        snap = self.snapshot_under_calendar_failure()
        for tf in _TFS:
            liq = (snap.get("liquidity") or {}).get(tf) or {}
            if not liq:
                continue
            assert liq.get("sweep_detected") is not True, \
                f"{tf}: a scorer would receive a sweep authored by a bridge"
            assert liq.get("reclaim_detected") is not True
            assert liq.get("sweep_direction") is None

    def test_terra_receives_the_cadence_reason(self):
        snap = self.snapshot_under_calendar_failure()
        payload = build_brain_input(snap, stance_history={})
        rows = {r["tf"]: r for r in payload["liquidity"]["evaluation"]}
        seen = {rows[tf]["sweep"].get("reason") for tf in _TFS if tf in rows}
        assert "EXPECTED_SLOT_AUTHORITY_UNAVAILABLE" in seen
        assert payload["liquidity"]["events"] == []

    def test_both_worlds_agree(self):
        """The whole point. The deterministic world and the cognitive world must
        not be able to disagree about whether a sweep happened."""
        snap = self.snapshot_under_calendar_failure()
        payload = build_brain_input(snap, stance_history={})
        booleans = {(snap["liquidity"].get(tf) or {}).get("sweep_detected")
                    for tf in _TFS}
        assert True not in booleans
        assert json.dumps(payload["liquidity"]["events"]) == "[]"


class TestTheMaskingCoincidenceCannotSilentlyReopen:

    def test_min_candles_is_not_what_protects_the_bridge(self):
        """`len(settled) < 2` produces UNCADENCED_LEGACY, which used to bridge.
        It was masked only because MIN_CANDLES (4) is larger than 2 -- a
        coincidence of constants, not an authority contract. The protection is
        now the authority table, so it holds at any MIN_CANDLES."""
        assert MIN_CANDLES > 2, "if this ever changes the masking disappears"
        assert PRIOR_MAY_AUTHOR[PRIOR_UNCADENCED] is False, \
            "the bridge is masked by a constant rather than refused by authority"

    def test_the_legacy_bridge_must_be_requested_out_loud(self):
        without = analyze_liquidity(real_sweep())
        with_optin = analyze_liquidity(real_sweep(), allow_uncadenced=True)
        assert without["sweep_detected"] is False
        assert with_optin["sweep_detected"] is True, \
            "the legacy opt-in no longer reaches the same answer it used to"
