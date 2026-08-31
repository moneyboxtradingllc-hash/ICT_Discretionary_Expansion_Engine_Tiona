"""STEP 4B.12 §4 UNIT 3 — TWO TERRA LANES, ONE EPISTEMIC ANSWER.

`STRUCTURE_WITNESS` is not the only factual structure channel Terra receives.
`MTF_MARKET_STATE` reads the SAME producer and had the same collapse:
`bos_event` is None and `mss_event` is False both when the engine evaluated and
found nothing and when it could not evaluate at all.

Repairing one lane and not the other would have let Unit 3 claim Terra's
structure epistemics were fixed while the identical false absence arrived
through a second door. These tests exist to keep the two lanes from ever
disagreeing about whether structure was evaluated.

The derived `quiet` authority in `embedding_v2` is the third consumer of the
same knowledge state, and is covered here for the same reason.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from ai_brain import brain_input as BI
from ai_brain.brain_input import build_brain_input
from ai_retrieval import embedding_v2 as EV2
from market_state import mtf_market_state as MTF

TFS = ("1m", "3m", "5m", "15m")


def _block(*, bos=False, mss=False, bos_eval="EVALUATED", mss_eval="EVALUATED"):
    return {"bos": bos, "mss": mss, "last_swing_high": 100.0,
            "last_swing_low": 90.0, "bos_evaluability": bos_eval,
            "mss_evaluability": mss_eval, "bos_direction": None,
            "broken_level": None, "break_close": None}


def _payload(struct):
    """The REAL production path: producer -> mtf build -> brain payload."""
    state = MTF.build(structure=struct, liquidity={}, protected_swings={},
                      structure_flips=[], price=95.0, timestamp="t")
    return build_brain_input({"structure": struct, "mtf_market_state": state}, {})


class TestBlockNamesCannotDrift:
    """brain_input mirrors two contract constants rather than importing them."""

    def test_the_mirrored_block_names_match_the_producer(self):
        assert BI._MTF_CONFIRMED == MTF.CONFIRMED
        assert BI._MTF_REALTIME == MTF.REALTIME


class TestCrossLaneConsistency:

    def test_evaluated_fixture_agrees_across_both_lanes(self):
        struct = {tf: _block() for tf in TFS}
        p = _payload(struct)
        wit, mtf = p["STRUCTURE_WITNESS"], p["MTF_MARKET_STATE"]
        for tf in TFS:
            rt = mtf["timeframes"][tf][MTF.REALTIME]
            cf = mtf["timeframes"][tf][MTF.CONFIRMED]
            assert wit[tf]["bos_evaluation"] == rt["bos_evaluation"]
            assert wit[tf]["mss_evaluation"] == cf["mss_evaluation"]
            assert rt["bos_evaluation"]["capability"] == "DETECTOR_EVALUATED"

    def test_unevaluable_fixture_agrees_across_both_lanes(self):
        struct = {tf: _block(bos_eval="UNEVALUABLE_PREVIOUS_CLOSE",
                             mss_eval="UNEVALUABLE_TRANSITION") for tf in TFS}
        p = _payload(struct)
        wit, mtf = p["STRUCTURE_WITNESS"], p["MTF_MARKET_STATE"]
        for tf in TFS:
            rt = mtf["timeframes"][tf][MTF.REALTIME]
            cf = mtf["timeframes"][tf][MTF.CONFIRMED]
            assert wit[tf]["bos_evaluation"] == rt["bos_evaluation"]
            assert wit[tf]["mss_evaluation"] == cf["mss_evaluation"]
            assert rt["bos_evaluation"]["reason"] == "UNEVALUABLE_PREVIOUS_CLOSE"
            assert cf["mss_evaluation"]["reason"] == "UNEVALUABLE_TRANSITION"

    def test_the_mtf_collapse_is_actually_gone(self):
        """`bos_event=None` meant two different things. Now it says which."""
        ev = _payload({tf: _block() for tf in TFS})["MTF_MARKET_STATE"]
        un = _payload({tf: _block(bos_eval="UNEVALUABLE_CADENCE",
                                  mss_eval="UNEVALUABLE_TRANSITION")
                       for tf in TFS})["MTF_MARKET_STATE"]
        a = ev["timeframes"]["5m"][MTF.REALTIME]
        b = un["timeframes"]["5m"][MTF.REALTIME]
        assert a["bos_event"] is None and b["bos_event"] is None
        assert a != b

    def test_mtf_keeps_every_field_it_already_published(self):
        struct = {tf: _block() for tf in TFS}
        raw = MTF.build(structure=struct, liquidity={}, protected_swings={},
                        structure_flips=[], price=95.0, timestamp="t")
        out = _payload(struct)["MTF_MARKET_STATE"]
        assert set(out) == set(raw)
        for tf in TFS:
            for blk in (MTF.CONFIRMED, MTF.REALTIME):
                assert set(raw["timeframes"][tf][blk]).issubset(
                    set(out["timeframes"][tf][blk]))

    def test_the_producer_object_is_not_mutated(self):
        """The snapshot has other consumers; none of them asked for this."""
        struct = {tf: _block() for tf in TFS}
        state = MTF.build(structure=struct, liquidity={}, protected_swings={},
                          structure_flips=[], price=95.0, timestamp="t")
        build_brain_input({"structure": struct, "mtf_market_state": state}, {})
        assert "bos_evaluation" not in state["timeframes"]["1m"][MTF.REALTIME]
        assert "mss_evaluation" not in state["timeframes"]["1m"][MTF.CONFIRMED]

    def test_no_directional_authority_is_added_to_either_lane(self):
        p = _payload({tf: _block() for tf in TFS})
        for tf in TFS:
            assert "bias" not in p["STRUCTURE_WITNESS"][tf]
            assert "state" not in p["STRUCTURE_WITNESS"][tf]
            assert "broken_level" not in p["STRUCTURE_WITNESS"][tf]

    def test_a_missing_mtf_state_does_not_raise_or_invent(self):
        p = build_brain_input({"structure": {tf: _block() for tf in TFS}}, {})
        assert p["MTF_MARKET_STATE"] == {}


class TestQuietAuthority:
    """`quiet` is a claim about the market, so it needs an evaluated read."""

    def _witness(self, struct):
        return build_brain_input({"structure": struct}, {})["STRUCTURE_WITNESS"]

    def test_evaluated_zero_events_may_still_be_quiet(self):
        ev = EV2.structure_evidence(self._witness({tf: _block() for tf in TFS}))
        assert (ev["bos_count"], ev["mss_count"]) == (0, 0)
        assert ev["quiet"] is True
        assert ev["structure_capability"] == "DETECTOR_EVALUATED"

    def test_unevaluable_bos_may_not_become_authoritative_quiet(self):
        struct = {tf: _block() for tf in TFS}
        struct["3m"] = _block(bos_eval="UNEVALUABLE_PREVIOUS_CLOSE",
                              mss_eval="UNEVALUABLE_TRANSITION")
        ev = EV2.structure_evidence(self._witness(struct))
        assert (ev["bos_count"], ev["mss_count"]) == (0, 0)
        assert ev["quiet"] is False
        assert ev["structure_capability"] == "UNEVALUABLE_EVIDENCE"

    def test_unevaluable_mss_alone_is_enough_to_withdraw_quiet(self):
        struct = {tf: _block() for tf in TFS}
        struct["15m"] = _block(mss_eval="UNEVALUABLE_TRANSITION")
        ev = EV2.structure_evidence(self._witness(struct))
        assert ev["quiet"] is False
        assert ev["structure_capability"] == "UNEVALUABLE_EVIDENCE"

    def test_legacy_witness_may_not_become_authoritative_quiet(self):
        legacy = {tf: {"last_swing_high": 100.0, "last_swing_low": 90.0,
                       "bos_event": False, "mss_event": False} for tf in TFS}
        ev = EV2.structure_evidence(legacy)
        assert ev["quiet"] is False
        assert ev["structure_capability"] == "UNKNOWN"

    def test_withdrawing_quiet_does_not_claim_structure_occurred(self):
        """One false claim may not be replaced by its opposite."""
        struct = {tf: _block() for tf in TFS}
        struct["1m"] = _block(bos_eval="UNEVALUABLE_CADENCE",
                              mss_eval="UNEVALUABLE_TRANSITION")
        ev = EV2.structure_evidence(self._witness(struct))
        # counts stay honestly zero: no event is asserted. The vector block for
        # a non-quiet zero-count read is all zeros -- distinct from quiet's
        # [0, 0, 1] and from any real event.
        assert ev["bos_count"] == 0 and ev["mss_count"] == 0
        assert ev["quiet"] is False

    def test_a_real_event_still_suppresses_quiet_for_the_ordinary_reason(self):
        struct = {tf: _block() for tf in TFS}
        struct["5m"] = _block(bos=True)
        ev = EV2.structure_evidence(self._witness(struct))
        assert ev["bos_count"] == 1
        assert ev["quiet"] is False
        assert ev["structure_capability"] == "DETECTOR_EVALUATED"

    def test_capability_is_read_from_the_witness_not_re_derived(self):
        """One owner for the mapping. embedding_v2 reads, brain_input maps."""
        hand = {tf: {"bos_event": False, "mss_event": False,
                     "bos_evaluation": {"capability": "DETECTOR_EVALUATED",
                                        "reason": None},
                     "mss_evaluation": {"capability": "DETECTOR_EVALUATED",
                                        "reason": None}} for tf in TFS}
        assert EV2.structure_evidence(hand)["structure_capability"] == \
            "DETECTOR_EVALUATED"
        hand["1m"]["bos_evaluation"] = {"capability": "UNEVALUABLE_EVIDENCE",
                                        "reason": "UNEVALUABLE_CADENCE"}
        assert EV2.structure_evidence(hand)["structure_capability"] == \
            "UNEVALUABLE_EVIDENCE"

    def test_unknown_outranks_unevaluable(self):
        """Weakest link wins: not knowing the contract is the weakest state."""
        hand = {tf: {"bos_event": False, "mss_event": False,
                     "bos_evaluation": {"capability": "UNEVALUABLE_EVIDENCE",
                                        "reason": "UNEVALUABLE_CADENCE"},
                     "mss_evaluation": {"capability": "UNEVALUABLE_EVIDENCE",
                                        "reason": "UNEVALUABLE_TRANSITION"}}
                for tf in TFS}
        hand["15m"] = {"bos_event": False, "mss_event": False}
        assert EV2.structure_evidence(hand)["structure_capability"] == "UNKNOWN"
