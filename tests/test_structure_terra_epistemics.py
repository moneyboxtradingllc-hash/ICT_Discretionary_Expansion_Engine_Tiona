"""STEP 4B.12 §4 UNIT 3 — STRUCTURE -> TERRA EPISTEMIC PROPAGATION.

Unit 2 taught the engine to tell an evaluated no-event from a transition it
could not evaluate. Nothing carried that across the Brain boundary: measured on
1000 scan x timeframe opportunities, FOUR distinct internal BOS states arrived
at Terra as one `bos_event: false`.

    EVALUATED_NO_EVENT                   630
    EVALUATED_NO_EVENT_ALREADY_BEYOND    278
    UNEVALUABLE_PREVIOUS_CLOSE             3
    UNEVALUABLE_PREVIOUS_SLOT              1

The regressions below are NOT synthetic where they need not be. The 3m and 1m
pairs are lifted from the measured tape, where the two witness rows were
BYTE-IDENTICAL while the underlying knowledge state differed. That is the
non-vacuous form: a test that only proves "False stayed False" would have
passed against the defect.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from ai_brain.brain_input import (STRUCTURE_CAPABILITIES, build_brain_input,
                                  structure_evaluation, structure_evaluations)


def _struct(tf_blocks):
    return {tf: dict(b) for tf, b in tf_blocks.items()}


def _witness(struct):
    return build_brain_input({"structure": struct}, {})["STRUCTURE_WITNESS"]


def _block(*, bos=False, mss=False, hi=None, lo=None,
           bos_eval="EVALUATED", mss_eval="EVALUATED"):
    return {"bos": bos, "mss": mss, "last_swing_high": hi, "last_swing_low": lo,
            "bos_evaluability": bos_eval, "mss_evaluability": mss_eval}


# ── the measured collisions ──────────────────────────────────────────────────
class TestRealMeasuredCollisions:
    """Frozen from the 2026-08-12 tape, 250-scan scope."""

    def test_3m_evaluated_vs_previous_close_no_longer_identical(self):
        """18:02 vs 18:14 on 3m. Same swings, same false, different knowledge."""
        evaluated = _struct({"3m": _block(hi=29924.0, lo=29888.25)})
        unevaluable = _struct({"3m": _block(
            hi=29924.0, lo=29888.25,
            bos_eval="UNEVALUABLE_PREVIOUS_CLOSE",
            mss_eval="UNEVALUABLE_TRANSITION")})

        a, b = _witness(evaluated)["3m"], _witness(unevaluable)["3m"]

        # the collapse that WAS: levels and event booleans still agree
        assert a["last_swing_high"] == b["last_swing_high"] == 29924.0
        assert a["last_swing_low"] == b["last_swing_low"] == 29888.25
        assert a["bos_event"] is False and b["bos_event"] is False

        # and the distinction that now survives
        assert a != b
        assert a["bos_evaluation"] == {"capability": "DETECTOR_EVALUATED",
                                       "reason": None}
        assert b["bos_evaluation"] == {"capability": "UNEVALUABLE_EVIDENCE",
                                       "reason": "UNEVALUABLE_PREVIOUS_CLOSE"}

    def test_1m_evaluated_vs_previous_slot_no_longer_identical(self):
        """18:05 vs 18:12 on 1m. The missing slot, not the unproven close."""
        evaluated = _struct({"1m": _block(hi=29915.5, lo=29901.5)})
        unevaluable = _struct({"1m": _block(
            hi=29915.5, lo=29901.5,
            bos_eval="UNEVALUABLE_PREVIOUS_SLOT",
            mss_eval="UNEVALUABLE_TRANSITION")})

        a, b = _witness(evaluated)["1m"], _witness(unevaluable)["1m"]
        assert a["bos_event"] is False and b["bos_event"] is False
        assert a["last_swing_high"] == b["last_swing_high"] == 29915.5
        assert b["bos_evaluation"]["capability"] == "UNEVALUABLE_EVIDENCE"
        assert b["bos_evaluation"]["reason"] == "UNEVALUABLE_PREVIOUS_SLOT"
        assert a["bos_evaluation"]["capability"] == "DETECTOR_EVALUATED"

    def test_the_two_causes_do_not_blur_into_each_other(self):
        """A missing slot and an unprovable close are different facts."""
        slot = _witness(_struct({"1m": _block(
            bos_eval="UNEVALUABLE_PREVIOUS_SLOT")}))["1m"]
        close = _witness(_struct({"1m": _block(
            bos_eval="UNEVALUABLE_PREVIOUS_CLOSE")}))["1m"]
        assert slot["bos_evaluation"]["capability"] == close["bos_evaluation"]["capability"]
        assert slot["bos_evaluation"]["reason"] != close["bos_evaluation"]["reason"]

    def test_mss_evaluated_vs_unevaluable_transition(self):
        """The MSS boolean is false in both; the evaluation must not be."""
        evaluated = _witness(_struct({"3m": _block(hi=29924.0, lo=29888.25)}))["3m"]
        unevaluable = _witness(_struct({"3m": _block(
            hi=29924.0, lo=29888.25,
            bos_eval="UNEVALUABLE_PREVIOUS_CLOSE",
            mss_eval="UNEVALUABLE_TRANSITION")}))["3m"]
        assert evaluated["mss_event"] is False
        assert unevaluable["mss_event"] is False
        assert unevaluable["mss_evaluation"] == {
            "capability": "UNEVALUABLE_EVIDENCE",
            "reason": "UNEVALUABLE_TRANSITION"}
        assert evaluated["mss_evaluation"]["capability"] == "DETECTOR_EVALUATED"


# ── the three states Terra must be able to read ──────────────────────────────
class TestThreeStatesAreDistinguishable:

    def test_evaluated_positive(self):
        row = _witness(_struct({"5m": _block(bos=True)}))["5m"]
        assert row["bos_event"] is True
        assert row["bos_evaluation"]["capability"] == "DETECTOR_EVALUATED"

    def test_evaluated_negative(self):
        row = _witness(_struct({"5m": _block(bos=False)}))["5m"]
        assert row["bos_event"] is False
        assert row["bos_evaluation"]["capability"] == "DETECTOR_EVALUATED"
        assert row["bos_evaluation"]["reason"] is None

    def test_unevaluable_is_not_an_evaluated_negative(self):
        row = _witness(_struct({"5m": _block(
            bos_eval="UNEVALUABLE_CADENCE")}))["5m"]
        assert row["bos_event"] is False
        assert row["bos_evaluation"]["capability"] == "UNEVALUABLE_EVIDENCE"

    def test_a_positive_event_was_never_ambiguous_and_still_is_not(self):
        """Measured: all 88 BOS positives were one internal state. Keep it."""
        row = _witness(_struct({"1m": _block(bos=True, mss=True)}))["1m"]
        assert (row["bos_event"], row["mss_event"]) == (True, True)


# ── absence may never be promoted to evidence ────────────────────────────────
class TestAbsenceIsNeverEvidence:

    def test_missing_producer_block_is_unknown_not_evaluated(self):
        wit = _witness({})
        for tf in ("1m", "3m", "5m", "15m"):
            assert wit[tf]["bos_event"] is False
            assert wit[tf]["bos_evaluation"]["capability"] == "UNKNOWN"
            assert wit[tf]["mss_evaluation"]["capability"] == "UNKNOWN"

    def test_legacy_producer_without_evaluability_is_unknown(self):
        """A pre-Unit-2 structure block states no evaluability. Not a negative."""
        legacy = {"1m": {"bos": False, "mss": False,
                         "last_swing_high": 100.0, "last_swing_low": 90.0}}
        row = _witness(legacy)["1m"]
        assert row["last_swing_high"] == 100.0
        assert row["bos_evaluation"]["capability"] == "UNKNOWN"
        assert row["bos_evaluation"]["reason"] == "PRODUCER_DID_NOT_STATE_EVALUABILITY"

    def test_every_timeframe_gets_a_row_so_silence_is_never_inferred(self):
        wit = _witness(_struct({"1m": _block()}))
        for tf in ("1m", "3m", "5m", "15m"):
            assert isinstance(wit[tf], dict)
            assert "bos_evaluation" in wit[tf] and "mss_evaluation" in wit[tf]

    def test_a_non_string_evaluability_cannot_pass_as_evaluated(self):
        for junk in (None, "", 0, True, [], {}):
            assert structure_evaluation(junk)["capability"] == "UNKNOWN"


# ── synthetic forensic coverage for causes the tape never produced ───────────
class TestForensicCausesWithoutRealObservations:
    """CURRENT_CLOSE, CADENCE and INSUFFICIENT_CANDLES were 0/1000 in scope.

    They are real producer tokens (`swing_evidence.TRANSITION_*` and the
    structure engine's insufficient-data return), so they are covered
    synthetically rather than manufactured from tape.
    """

    def test_current_close_unproven_SYNTHETIC(self):
        row = _witness(_struct({"3m": _block(
            bos_eval="UNEVALUABLE_CURRENT_CLOSE")}))["3m"]
        assert row["bos_event"] is False
        assert row["bos_evaluation"] == {"capability": "UNEVALUABLE_EVIDENCE",
                                         "reason": "UNEVALUABLE_CURRENT_CLOSE"}

    def test_cadence_unknown_SYNTHETIC(self):
        row = _witness(_struct({"15m": _block(
            bos_eval="UNEVALUABLE_CADENCE")}))["15m"]
        assert row["bos_evaluation"]["reason"] == "UNEVALUABLE_CADENCE"

    def test_insufficient_candles_SYNTHETIC(self):
        row = _witness(_struct({"1m": _block(
            bos_eval="UNEVALUABLE_INSUFFICIENT_CANDLES",
            mss_eval="UNEVALUABLE_INSUFFICIENT_CANDLES")}))["1m"]
        assert row["bos_evaluation"]["reason"] == "UNEVALUABLE_INSUFFICIENT_CANDLES"
        assert row["mss_evaluation"]["reason"] == "UNEVALUABLE_INSUFFICIENT_CANDLES"

    def test_no_transition_evidence_SYNTHETIC(self):
        """The structure engine's own fallback token when no evidence arrives."""
        row = _witness(_struct({"5m": _block(
            bos_eval="UNEVALUABLE_NO_TRANSITION_EVIDENCE")}))["5m"]
        assert row["bos_evaluation"]["capability"] == "UNEVALUABLE_EVIDENCE"
        assert row["bos_evaluation"]["reason"] == "UNEVALUABLE_NO_TRANSITION_EVIDENCE"

    def test_the_exact_producer_token_is_never_generalised_away(self):
        """Five causes, five reasons. A shared capability is not a shared cause."""
        causes = ("UNEVALUABLE_PREVIOUS_SLOT", "UNEVALUABLE_PREVIOUS_CLOSE",
                  "UNEVALUABLE_CURRENT_CLOSE", "UNEVALUABLE_CADENCE",
                  "UNEVALUABLE_INSUFFICIENT_CANDLES")
        reasons = {structure_evaluation(c)["reason"] for c in causes}
        assert reasons == set(causes)


# ── the contract shape itself ────────────────────────────────────────────────
class TestContractShape:

    def test_structure_never_claims_an_unavailable_sensor(self):
        """The engine exists. Every measured failure is evidence-shaped.

        This once also asserted the absence of UNAVAILABLE_SENSOR from a
        `_capability_legend` published inside the witness. That key was removed
        from production: every non-`_disclaimer` witness key is a TIMEFRAME by
        convention, and the vocabulary is already defined once under
        `liquidity.capability_legend`. The proposition under test never depended
        on the legend, so it is asserted directly.
        """
        wit = _witness(_struct({"1m": _block(bos_eval="UNEVALUABLE_CADENCE")}))
        for tf in ("1m", "3m", "5m", "15m"):
            for prop in ("bos_evaluation", "mss_evaluation"):
                cap = wit[tf][prop]["capability"]
                assert cap != "UNAVAILABLE_SENSOR"
                assert cap in STRUCTURE_CAPABILITIES

    def test_no_capability_outside_the_declared_three_can_be_published(self):
        """The coarse vocabulary is closed, whatever the producer token was."""
        for token in ("EVALUATED", "UNEVALUABLE_PREVIOUS_SLOT",
                      "UNEVALUABLE_PREVIOUS_CLOSE", "UNEVALUABLE_CURRENT_CLOSE",
                      "UNEVALUABLE_CADENCE", "UNEVALUABLE_INSUFFICIENT_CANDLES",
                      "UNEVALUABLE_TRANSITION", "UNEVALUABLE_NO_TRANSITION_EVIDENCE",
                      "SOMETHING_THE_PRODUCER_NEVER_EMITS", "", None):
            assert structure_evaluation(token)["capability"] in STRUCTURE_CAPABILITIES
        assert set(STRUCTURE_CAPABILITIES) == {
            "DETECTOR_EVALUATED", "UNEVALUABLE_EVIDENCE", "UNKNOWN"}

    def test_the_event_keys_keep_their_names_and_meaning(self):
        """`bos` beside `bos_event` would be a second answer to one question."""
        row = _witness(_struct({"1m": _block()}))["1m"]
        assert "bos" not in row and "mss" not in row
        assert {"bos_event", "mss_event", "bos_evaluation", "mss_evaluation",
                "last_swing_high", "last_swing_low"} == set(row)

    def test_directional_authority_is_still_withheld(self):
        """AI-BRAIN-H2 stands. Unit 3 adds epistemics, not direction."""
        row = _witness(_struct({"1m": _block(bos=True)}))["1m"]
        for leaked in ("bias", "state", "bos_direction", "broken_level",
                       "break_close", "position_beyond_swing_high",
                       "position_beyond_swing_low"):
            assert leaked not in row

    def test_evaluations_helper_and_witness_agree(self):
        block = _block(bos_eval="UNEVALUABLE_PREVIOUS_SLOT")
        direct = structure_evaluations(block)
        row = _witness({"1m": block})["1m"]
        assert row["bos_evaluation"] == direct["bos_evaluation"]
        assert row["mss_evaluation"] == direct["mss_evaluation"]
