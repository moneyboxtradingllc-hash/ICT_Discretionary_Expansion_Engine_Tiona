"""REFINE-DESCRIPTIVE-MEMORY-BLOCK-WEIGHTING (2026-08-06).

Equal-weight v2 treated market regime, narrative direction and delivery as equal
contributors to confidence dispersion and protected-low presence. The audit
measured the consequence: the bullish-expansion query scored 0.5374 against
segment #1 while regime, direction and narrative phase ALL contradicted and
contributed exactly 0, and session phase + delivery + liquidity + active draw +
exhaustion each supplied 17.2% of the numerator.

The profile bake-off then proved something more important: **no weighting can
fix this**. A probe differing from the base state only in direction still scores
0.8576 at load=1.50, because in a one-hot block a contradiction contributes 0 to
the numerator -- it never subtracts -- and one disagreement out of thirteen
blocks is always a small fraction.

So v2.1 does two things. Weights order the records that do not contradict, and a
LOAD-BEARING CONTRADICTION GATE removes the ones that do. Contradiction is a
rule, not a distance.
"""
from __future__ import annotations

import json
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src"))

from ai_brain.production_model import brain_contract_fingerprint  # noqa: E402
from ai_retrieval import descriptive_memory as DM                 # noqa: E402
from ai_retrieval import embedding_v2 as EV2                      # noqa: E402
from ai_retrieval import memory_authoring as MA                   # noqa: E402
from ai_retrieval import retrieval_contract as RC                 # noqa: E402
from ai_retrieval import vector_store                             # noqa: E402
from ai_retrieval.retrieval import query_vector, retrieve_analogs  # noqa: E402

ARCHIVE = os.path.join("data", "replay_sessions", "PROD-20260806")
V21_DIR = os.path.join(ARCHIVE, "analysis", "proposed_descriptive_memory_v2_1")
V2_DIR = os.path.join(ARCHIVE, "analysis", "proposed_descriptive_memory_v2")
V1_DIR = os.path.join(ARCHIVE, "analysis", "proposed_descriptive_memory")
EMPTY = {"level": None, "timeframe": None, "basis": None, "registered_at": None}

has_v21 = pytest.mark.skipif(not os.path.isdir(V21_DIR),
                             reason="v2.1 proposals are git-ignored")


def spec(**over):
    base = dict(
        session_id="SYNTH", session_date="2026-08-06", instrument="MNQ",
        contract="CON.F.US.MNQ.U26", segment_start="11:00:00",
        segment_end="11:20:00", scan_count=10, source_model="gpt-5.6-terra",
        brain_contract_fingerprint_suffix="x", market_regime="range_rotation",
        volatility_state="toxic", session_phase="lunch",
        narrative_phase="transition", delivery_state="accumulation_building",
        structure_state="witness_quiet",
        structure_evidence={"bos_count": 0, "mss_count": 0, "quiet": True},
        liquidity_state="two_sided_pools", protected_high=EMPTY,
        protected_low=EMPTY, active_draw_present=True, exhaustion_present=False,
        direction_distribution={"conflicted": 10},
        action_distribution={"stand_down": 10}, dominant_direction="conflicted",
        dominant_action="stand_down",
        phase_confidence_summary={"mean": 60.0, "min": 50.0, "max": 70.0},
        candidate_count=0, trade_count=0, no_candidate_reasons=["x"],
        source_artifact_ids=["a"], source_artifact_digest="d",
        created_at="2026-08-06T20:00:00+00:00")
    base.update(over)
    return base


def vec(**over):
    return DM.make_descriptive_record(**spec(**over))["feature_vector"]


def contra(a_over=None, b_over=None):
    return EV2.contradiction_report(vec(**(a_over or {})), vec(**(b_over or {})))


def sim(a_over=None, b_over=None):
    return EV2.cosine_v2(vec(**(a_over or {})), vec(**(b_over or {})))


@pytest.fixture
def store(tmp_path, monkeypatch):
    monkeypatch.setenv("AI_RETRIEVAL_DIR", str(tmp_path / "r"))
    return tmp_path


def query(**over):
    q = {"session": "lunch", "contract": "CON.F.US.MNQ.U26",
         "market_regime": {"regime_label": "range_rotation",
                           "volatility_state": "toxic"},
         "narrative_authority": {"narrative_direction": "conflicted",
                                 "narrative_phase": "transition",
                                 "active_liquidity_draw": "29500"},
         "shared_context": {"delivery_state": "accumulation_building",
                            "exhaustion_present": False},
         "protected_swings": {},
         "liquidity": {"nearest_buy_side": 29800.0, "nearest_sell_side": 29200.0},
         "STRUCTURE_WITNESS": {tf: {"bos_event": False, "mss_event": False}
                               for tf in ("15m", "5m", "3m", "1m")},
         "phase_confidence_summary": {"mean": 60.0, "min": 50.0, "max": 70.0}}
    q.update(over)
    return q


# ══════════════════════════════════════════════════════════════════════════════
class TestWeightsAreExplicitAndBound:
    """1-4."""

    def test_1_every_block_has_an_explicit_weight(self):
        weights = EV2.block_weights()
        names = {g["name"] for g in EV2.MANIFEST["groups"]}
        assert set(weights) == names
        tiers = (set(EV2.LOAD_BEARING_BLOCKS) | set(EV2.CONTEXTUAL_BLOCKS)
                 | set(EV2.DIAGNOSTIC_BLOCKS))
        assert tiers == names, "a block belongs to no authority tier"

    def test_2_weights_are_in_the_manifest(self):
        assert EV2.MANIFEST["block_weights"] == EV2.block_weights()
        assert EV2.MANIFEST["weight_profile"] == EV2.ACTIVE_PROFILE
        assert EV2.MANIFEST["authority_tiers"]["load_bearing"]

    def test_3_weights_are_in_the_retrieval_fingerprint(self):
        policy = RC.retrieval_policy()
        assert policy["block_weights"] == EV2.block_weights()
        before = RC.retrieval_contract_fingerprint()
        prev = EV2.ACTIVE_PROFILE
        try:
            EV2.ACTIVE_PROFILE = "AUTHORITY_TIERED_B"
            assert RC.retrieval_contract_fingerprint() != before
        finally:
            EV2.ACTIVE_PROFILE = prev
        assert RC.retrieval_contract_fingerprint() == before

    def test_4_every_weight_is_finite_and_positive(self):
        for name, w in EV2.block_weights().items():
            assert isinstance(w, float) and w > 0 and w == w and w < 1e6, name

    def test_35_the_brain_contract_fingerprint_changed(self):
        assert brain_contract_fingerprint() != "brain:6118d5eedf9fca60"
        assert brain_contract_fingerprint().startswith("brain:")


class TestInternalNormalization:
    """5-8. No block may gain authority from dimension count."""

    def test_5_internal_normalization_is_deterministic(self):
        assert vec() == vec()
        assert EV2.MANIFEST["internal_normalization_law"]

    def test_6_dimensionality_does_not_create_authority(self):
        """Every block's pre-weight norm is bounded by 1.0, so a 9-dimension
        one-hot and a 1-dimension presence flag carry the same maximum."""
        weights = EV2.block_weights()
        full = DM.make_descriptive_record(**spec(
            structure_evidence={"bos_count": 4, "mss_count": 4, "quiet": False},
            protected_high={"level": 1.0, "timeframe": None, "basis": None,
                            "registered_at": None},
            protected_low={"level": 1.0, "timeframe": None, "basis": None,
                           "registered_at": None},
            phase_confidence_summary={"mean": 100.0, "min": 0.0, "max": 100.0}))
        norms = EV2.block_norms(full["feature_vector"])
        for name, n in norms.items():
            assert n <= weights[name] + 1e-9, (name, n, weights[name])

    def test_7_confidence_remains_diagnostic(self):
        w = EV2.block_weights()
        assert w["confidence"] < min(w[b] for b in EV2.LOAD_BEARING_BLOCKS)
        assert w["confidence"] <= min(w[b] for b in EV2.CONTEXTUAL_BLOCKS)
        assert "confidence" not in EV2.CONTRADICTION_BLOCKS
        assert "confidence" not in EV2.MANDATORY_QUERY_BLOCKS

    def test_8_missing_values_contribute_zero(self):
        v, notes = EV2.embed_v2({"direction_distribution": {"conflicted": 1},
                                 "scan_count": 1,
                                 "structure_evidence": {"bos_count": 0,
                                                        "mss_count": 0,
                                                        "quiet": True}})
        for g in EV2.MANIFEST["groups"]:
            if g["name"] in ("direction_distribution", "structure_evidence"):
                continue
            assert not any(v[g["start"]:g["end"]]), g["name"]

    def test_structure_intensity_survives_bounding(self):
        """Bounded, not flattened -- bos=1 and bos=4 must stay different."""
        g = EV2._GROUP["structure_evidence"]
        one = vec(structure_evidence={"bos_count": 1, "mss_count": 0, "quiet": False})
        four = vec(structure_evidence={"bos_count": 4, "mss_count": 0, "quiet": False})
        assert one[g["start"]] < four[g["start"]]
        assert one[g["start"]] > 0


class TestQueryCompletenessLaw:
    """9-10. Asking less must not look like a better match."""

    def test_9_missing_mandatory_blocks_refuse_the_query(self, store):
        vector_store.add_record(DM.make_descriptive_record(**spec()))
        q = query()
        q["market_regime"] = {"regime_label": None, "volatility_state": "toxic"}
        out = retrieve_analogs(q, persist_log=False, today="2026-08-07")
        assert out["returned"] == 0
        assert out["refusal"] == "INCOMPLETE_QUERY_MISSING_MANDATORY_BLOCKS"
        assert "market_regime" in out["missing_mandatory_blocks"]

    def test_every_mandatory_block_is_individually_enforced(self, store):
        vector_store.add_record(DM.make_descriptive_record(**spec()))
        removals = {
            "market_regime": lambda q: q["market_regime"].update(
                {"regime_label": None}),
            "volatility_state": lambda q: q["market_regime"].update(
                {"volatility_state": None}),
            "direction_distribution": lambda q: q["narrative_authority"].update(
                {"narrative_direction": None}),
            "delivery_state": lambda q: q["shared_context"].update(
                {"delivery_state": None}),
            "liquidity_state": lambda q: q.update({"liquidity": {}}),
        }
        assert set(removals) == set(EV2.MANDATORY_QUERY_BLOCKS)
        for block, drop in removals.items():
            q = query()
            drop(q)
            out = retrieve_analogs(q, persist_log=False, today="2026-08-07")
            assert out["returned"] == 0, block
            assert block in out["missing_mandatory_blocks"], block

    def test_10_omission_cannot_raise_similarity(self, store):
        """The v2 defect: an unstated block shrinks |q| while contributing
        nothing, so an underspecified query scored HIGHER."""
        vector_store.add_record(DM.make_descriptive_record(**spec()))
        full = retrieve_analogs(query(), persist_log=False, today="2026-08-07")
        partial = query()
        partial["shared_context"] = {"delivery_state": "accumulation_building"}
        partial["phase_confidence_summary"] = {}
        out = retrieve_analogs(partial, persist_log=False, today="2026-08-07")
        assert out["completeness"]["score"] < 1.0
        assert out["incomplete_query"] is True
        if out["analogs"]:
            assert out["analogs"][0]["similarity"] <= \
                full["analogs"][0]["similarity"] + 1e-9

    def test_the_completeness_law_is_bound(self):
        p = RC.retrieval_policy()
        assert p["mandatory_query_blocks"] == list(EV2.MANDATORY_QUERY_BLOCKS)
        assert p["incomplete_query_treatment"]


class TestContradictionControl:
    """11-13. Proven necessary: weighting alone cannot do this."""

    def test_weighting_alone_provably_cannot_separate(self):
        """The finding that motivated the gate. Recorded so it is not
        rediscovered by someone who deletes the gate and raises the weights."""
        opposite_direction = sim(b_over={"direction_distribution": {"bullish": 10},
                                         "dominant_direction": "bullish"})
        assert opposite_direction > 0.8, (
            "a record differing ONLY in direction still scores high under any "
            "weighting -- contradiction contributes 0, never negative")

    def test_11_opposite_regime_plus_direction_is_excluded(self):
        c = contra(b_over={"market_regime": "expansion_up",
                           "direction_distribution": {"bullish": 10},
                           "dominant_direction": "bullish"})
        assert c["excluded"]
        assert set(c["blocks"]) == {"market_regime", "direction_distribution"}

    def test_12_matching_context_cannot_rescue_dual_contradiction(self, store):
        """Session phase, active draw, exhaustion and confidence all agree."""
        vector_store.add_record(DM.make_descriptive_record(**spec(
            market_regime="trend_down",
            direction_distribution={"bearish": 10},
            dominant_direction="bearish")))
        out = retrieve_analogs(query(), persist_log=False, today="2026-08-07",
                               min_similarity=0.0)
        assert out["returned"] == 0
        assert out["rejected_reasons"]["load_bearing_contradiction"] == 1

    def test_13_delivery_cannot_substitute_for_direction(self):
        """Same delivery, opposite thesis: delivery agreement does not make the
        directions equivalent, and the direction disagreement is recorded."""
        c = contra(b_over={"direction_distribution": {"bullish": 10},
                           "dominant_direction": "bullish"})
        assert "direction_distribution" in c["blocks"]
        assert "delivery_state" not in c["blocks"]
        assert c["direction_agreement"] == 0.0

    def test_a_single_contradiction_remains_retrievable(self, store):
        """Constraint 6: a near-neighbour disagreeing on one field survives."""
        vector_store.add_record(DM.make_descriptive_record(
            **spec(delivery_state="mixed")))
        out = retrieve_analogs(query(), persist_log=False, today="2026-08-07")
        assert out["returned"] == 1

    def test_direction_is_compared_as_a_distribution_not_a_label(self):
        """A mixed segment partially agreeing with a conflicted query is NOT a
        contradiction; a pure opposite thesis is."""
        mixed = contra(b_over={"scan_count": 24,
                               "action_distribution": {"stand_down": 24},
                               "direction_distribution": {"bearish": 8,
                                                          "conflicted": 8,
                                                          "neutral": 6,
                                                          "bullish": 2},
                               "dominant_direction": "bearish"})
        assert mixed["direction_agreement"] > EV2.DIRECTION_AGREEMENT_MIN
        assert "direction_distribution" not in mixed["blocks"]

    def test_unstated_blocks_are_never_treated_as_contradictions(self):
        """Silence is not disagreement."""
        a = vec()
        partial, _ = EV2.embed_v2({"direction_distribution": {"conflicted": 1},
                                   "scan_count": 1,
                                   "structure_evidence": {"bos_count": 0,
                                                          "mss_count": 0,
                                                          "quiet": True}})
        assert EV2.contradiction_report(partial, a)["blocks"] == []

    def test_the_gate_is_bound_into_the_contract(self):
        p = RC.retrieval_policy()
        assert p["contradiction_blocks"] == list(EV2.CONTRADICTION_BLOCKS)
        assert p["direction_agreement_min"] == EV2.DIRECTION_AGREEMENT_MIN
        assert p["max_load_bearing_contradictions"] == \
            EV2.MAX_LOAD_BEARING_CONTRADICTIONS


class TestRankingInvariants:
    """14-15, 20-21."""

    def test_14_exact_state_ranks_first(self, store):
        vector_store.add_records([
            DM.make_descriptive_record(**spec(segment_start="11:00:00",
                                              source_artifact_digest="exact")),
            DM.make_descriptive_record(**spec(segment_start="12:00:00",
                                              session_phase="afternoon",
                                              source_artifact_digest="near")),
        ])
        out = retrieve_analogs(query(), persist_log=False, today="2026-08-07")
        assert out["analogs"][0]["segment"].startswith("11:00:00")
        assert out["analogs"][0]["similarity"] > out["analogs"][1]["similarity"]

    def test_15_one_contextual_mismatch_stays_retrievable(self, store):
        vector_store.add_record(DM.make_descriptive_record(
            **spec(session_phase="afternoon")))
        out = retrieve_analogs(query(), persist_log=False, today="2026-08-07")
        assert out["returned"] == 1
        assert out["analogs"][0]["similarity"] > RC.MIN_SIMILARITY

    def test_20_the_threshold_is_a_named_contract_value(self):
        assert RC.MIN_SIMILARITY == 0.60
        assert RC.retrieval_policy()["min_similarity"] == RC.MIN_SIMILARITY

    def test_21_small_weight_perturbations_do_not_flip_invariants(self):
        """Gate decisions must not depend on the third decimal of a weight."""
        cases = [
            ({}, {"market_regime": "expansion_up",
                  "direction_distribution": {"bullish": 10},
                  "dominant_direction": "bullish"}, True),
            ({}, {"session_phase": "afternoon"}, False),
            ({}, {"delivery_state": "mixed"}, False),
        ]
        prev = EV2.ACTIVE_PROFILE
        try:
            for load in (1.15, 1.25, 1.35):
                EV2.WEIGHT_PROFILES["_PERTURB"] = {"load": load,
                                                   "context": 0.75,
                                                   "diagnostic": 0.50}
                EV2.ACTIVE_PROFILE = "_PERTURB"
                for a_over, b_over, expect in cases:
                    assert contra(a_over, b_over)["excluded"] is expect, (
                        load, b_over)
        finally:
            EV2.ACTIVE_PROFILE = prev
            EV2.WEIGHT_PROFILES.pop("_PERTURB", None)

    def test_22_ranking_is_independent_of_append_order(self, tmp_path,
                                                       monkeypatch):
        recs = [DM.make_descriptive_record(**spec(
            session_id=f"S{i}", session_date=f"2026-08-0{i+1}",
            source_artifact_digest=f"d{i}")) for i in range(4)]
        seen = []
        for order in (recs, list(reversed(recs))):
            monkeypatch.setenv("AI_RETRIEVAL_DIR", str(tmp_path / f"r{len(seen)}"))
            vector_store.add_records(order)
            out = retrieve_analogs(query(), persist_log=False, today="2026-08-07")
            seen.append([a["memory_id"] for a in out["analogs"]])
        assert seen[0] == seen[1]

    def test_23_the_same_session_cap_is_still_enforced(self, store):
        """Five SEMANTICALLY DISTINCT states from one session -- varying only
        confidence would now be one recurrence group, which is the point of
        REFINE-SEMANTIC-RECURRENCE-COLLAPSE."""
        phases = ("transition", "accumulation", "distribution", "reversal",
                  "continuation")
        for i, phase in enumerate(phases):
            vector_store.add_record(DM.make_descriptive_record(**spec(
                segment_start=f"1{i}:00:00", segment_end=f"1{i}:20:00",
                source_artifact_digest=f"d{i}", narrative_phase=phase)))
        out = retrieve_analogs(query(), persist_log=False, today="2026-08-07",
                               min_similarity=0.0)
        assert out["returned"] == RC.MAX_ANALOGS_PER_SOURCE_SESSION == 2

    def test_24_recurrence_metadata_remains_truthful(self, store):
        a = DM.make_descriptive_record(**spec(segment_start="11:00:00",
                                              segment_end="11:10:00",
                                              source_artifact_digest="d1"))
        b = DM.make_descriptive_record(**spec(segment_start="12:00:00",
                                              segment_end="12:20:00",
                                              source_artifact_digest="d2"))
        assert a["feature_vector_fingerprint"] == b["feature_vector_fingerprint"]
        vector_store.add_records([a, b])
        out = retrieve_analogs(query(), persist_log=False, today="2026-08-07")
        assert out["returned"] == 1
        assert out["analogs"][0]["recurrence_count"] == 2
        assert out["analogs"][0]["occurrence_spans"] == ["11:00:00-11:10:00",
                                                         "12:00:00-12:20:00"]


@has_v21
class TestAugust6UnderWeighting:
    """16-19, 31-34."""

    def _load(self, tmp_path, monkeypatch):
        import glob
        monkeypatch.setenv("AI_RETRIEVAL_DIR", str(tmp_path / "sim"))
        recs = sorted([json.load(open(p, encoding="utf-8"))
                       for p in glob.glob(os.path.join(V21_DIR, "mem_*.json"))],
                      key=lambda r: r["segment_start"])
        vector_store.add_records(recs)
        return recs

    def _q(self, session, regime, vol, ndir, nphase, delivery, bos=1,
           conf=70.0, exh=False, contract="CON.F.US.MNQ.U26"):
        return {"session": session, "contract": contract,
                "market_regime": {"regime_label": regime, "volatility_state": vol},
                "narrative_authority": {"narrative_direction": ndir,
                                        "narrative_phase": nphase,
                                        "active_liquidity_draw": "29500"},
                "shared_context": {"delivery_state": delivery,
                                   "exhaustion_present": exh},
                "protected_swings": {},
                "liquidity": {"nearest_buy_side": 29800.0,
                              "nearest_sell_side": 29200.0},
                "STRUCTURE_WITNESS": {tf: {"bos_event": i < bos,
                                           "mss_event": False}
                                      for i, tf in enumerate(("15m", "5m",
                                                              "3m", "1m"))},
                "phase_confidence_summary": {"mean": conf, "min": conf,
                                             "max": conf}}

    def test_16_exhaustion_retrieves_the_true_exhaustion_segment(self, tmp_path,
                                                                 monkeypatch):
        self._load(tmp_path, monkeypatch)
        out = retrieve_analogs(self._q("morning_continuation", "range_rotation",
                                       "toxic", "conflicted", "exhaustion",
                                       "accumulation_building", conf=85.0,
                                       exh=True),
                               persist_log=False, today="2026-08-07")
        assert out["analogs"][0]["segment"].startswith("11:05:02")
        assert out["analogs"][0]["similarity"] > 0.95

    def test_17_volatility_expansion_remains_absent(self, tmp_path, monkeypatch):
        self._load(tmp_path, monkeypatch)
        out = retrieve_analogs(self._q("afternoon", "high_volatility",
                                       "explosive", "bearish", "distribution",
                                       "manipulation_to_distribution", bos=3),
                               persist_log=False, today="2026-08-07",
                               min_similarity=0.0)
        assert out["returned"] == 0
        assert out["rejected_reasons"]["load_bearing_contradiction"] == 10

    def test_18_the_bullish_expansion_partial_query_issue_is_controlled(
            self, tmp_path, monkeypatch):
        """Two independent mechanisms now cover it: the completeness law makes
        the underspecified form impossible, and the gate removes the complete
        form on semantics."""
        self._load(tmp_path, monkeypatch)
        complete = self._q("ny_open", "expansion_up", "stable", "bullish",
                           "continuation", "full_distribution_alignment",
                           bos=2, conf=80.0)
        out = retrieve_analogs(complete, persist_log=False, today="2026-08-07",
                               min_similarity=0.0)
        assert out["returned"] == 0
        assert out["rejected_reasons"]["load_bearing_contradiction"] == 10

        incomplete = dict(complete)
        incomplete["market_regime"] = {"regime_label": None,
                                       "volatility_state": "stable"}
        out2 = retrieve_analogs(incomplete, persist_log=False,
                                today="2026-08-07", min_similarity=0.0)
        assert out2["returned"] == 0
        assert out2["refusal"] == "INCOMPLETE_QUERY_MISSING_MANDATORY_BLOCKS"

    def test_19_the_bearish_delivery_result_is_removed_with_a_reason(
            self, tmp_path, monkeypatch):
        """Under v2 this returned segment #1 at 0.5129 despite #1 reading
        CONFLICTED in a RANGE ROTATION. It is now excluded, and the exclusion
        names the two contradictions."""
        recs = self._load(tmp_path, monkeypatch)
        q = self._q("morning_continuation", "trend_down", "unstable", "bearish",
                    "distribution", "full_distribution_alignment", bos=2,
                    conf=75.0)
        out = retrieve_analogs(q, persist_log=False, today="2026-08-07",
                               min_similarity=0.0)
        assert out["returned"] == 0
        qv, _ = query_vector(q)
        c = EV2.contradiction_report(qv, recs[0]["feature_vector"])
        assert c["excluded"]
        assert set(c["blocks"]) == {"market_regime", "direction_distribution"}
        assert c["direction_agreement"] == 0.0

    def test_conflicted_rotation_returns_two_ranked_analogs(self, tmp_path,
                                                            monkeypatch):
        self._load(tmp_path, monkeypatch)
        out = retrieve_analogs(self._q("lunch", "range_rotation", "toxic",
                                       "conflicted", "transition",
                                       "accumulation_building", conf=65.0,
                                       exh=True),
                               persist_log=False, today="2026-08-07")
        assert out["returned"] == 2
        assert out["analogs"][0]["segment"].startswith("11:31:44")
        assert out["analogs"][0]["similarity"] > out["analogs"][1]["similarity"]

    def test_neutral_lunch_retains_useful_analogs(self, tmp_path, monkeypatch):
        self._load(tmp_path, monkeypatch)
        out = retrieve_analogs(self._q("lunch", "chop", "stable", "neutral",
                                       "transition", "mixed", conf=70.0),
                               persist_log=False, today="2026-08-07")
        assert out["returned"] == 2
        for a in out["analogs"]:
            assert a["market_regime"] == "chop"
            assert a["dominant_direction"] == "neutral"

    def test_25_cross_contract_levels_remain_withheld(self, tmp_path, monkeypatch):
        self._load(tmp_path, monkeypatch)
        out = retrieve_analogs(self._q("afternoon", "range_rotation", "stable",
                                       "bearish", "accumulation",
                                       "accumulation_building",
                                       contract="CON.F.US.MNQ.Z26"),
                               persist_log=False, today="2026-08-07",
                               min_similarity=0.0)
        assert out["analogs"]
        for a in out["analogs"]:
            assert a["levels_withheld"] is True
            assert "protected_low" not in a

    def test_27_expired_records_remain_excluded(self, tmp_path, monkeypatch):
        self._load(tmp_path, monkeypatch)
        out = retrieve_analogs(self._q("lunch", "range_rotation", "toxic",
                                       "conflicted", "transition",
                                       "accumulation_building", exh=True),
                               persist_log=False, today="2026-12-31")
        assert out["returned"] == 0
        assert out["rejected_reasons"] == {"expired": 10}

    def test_28_all_analogs_remain_context_only(self, tmp_path, monkeypatch):
        self._load(tmp_path, monkeypatch)
        out = retrieve_analogs(self._q("lunch", "range_rotation", "toxic",
                                       "conflicted", "transition",
                                       "accumulation_building", exh=True),
                               persist_log=False, today="2026-08-07")
        for a in out["analogs"]:
            assert a["authority"] == "CONTEXT_ONLY"
            assert a["outcome_validated"] is False
            assert a["recommendation_authority"] == "none"
            assert a["execution_authority"] == "none"

    def test_33_generation_is_deterministic(self):
        a = MA.build_records(ARCHIVE, now_iso="2026-08-06T20:00:00+00:00")
        b = MA.build_records(ARCHIVE, now_iso="2026-08-06T20:00:00+00:00")
        assert [r["feature_vector_fingerprint"] for r in a["records"]] == \
               [r["feature_vector_fingerprint"] for r in b["records"]]
        assert len(a["records"]) == 10       # segmentation unchanged

    def test_the_recurrence_pair_still_occupies_both_slots(self, tmp_path,
                                                           monkeypatch):
        """Phase 13 observation, reported not acted on."""
        recs = self._load(tmp_path, monkeypatch)
        four, six = recs[3], recs[5]
        assert four["feature_vector_fingerprint"] != six["feature_vector_fingerprint"]
        assert EV2.cosine_v2(four["feature_vector"], six["feature_vector"]) > 0.95
        c = EV2.contradiction_report(four["feature_vector"], six["feature_vector"])
        assert c["count"] == 0, "they agree on every load-bearing block"


class TestUntouchedEvidenceAndAuthority:
    """26, 29-32, 34, 36."""

    def test_26_foreign_instruments_remain_excluded(self, store):
        vector_store.add_record({**DM.make_descriptive_record(**spec()),
                                 "instrument": "QQQ"})
        out = retrieve_analogs(query(), persist_log=False, today="2026-08-07")
        assert out["returned"] == 0
        assert out["rejected_reasons"] == {"retired_instrument:qqq": 1}

    def test_29_30_weighting_cannot_reach_execution(self):
        """The weight map is read by the encoder and the contract. Nothing in
        the execution path imports it."""
        import ast
        for rel in ("broker/luna_candidate_producer.py",
                    "broker/topstepx_execution_runner.py",
                    "broker/topstepx_production_loop.py"):
            tree = ast.parse(open(os.path.join("src", rel), encoding="utf-8").read())
            for node in ast.walk(tree):
                if isinstance(node, (ast.Import, ast.ImportFrom)):
                    mod = getattr(node, "module", "") or ""
                    names = [a.name for a in node.names]
                    assert "embedding_v2" not in mod, rel
                    assert "embedding_v2" not in names, rel
                    assert "block_weights" not in names, rel

    def test_an_analog_view_still_carries_no_risk_or_sizing_field(self):
        from ai_retrieval.retrieval import _descriptive_view
        rec = DM.make_descriptive_record(**spec())
        view = _descriptive_view(rec, 1.0, "CON.F.US.MNQ.U26")
        for field in ("risk_usd", "contracts", "size", "reward_to_risk",
                      "stop_points", "leverage", "invalidation_level"):
            assert field not in rec and field not in view, field

    def test_31_v1_proposals_remain_untouched(self):
        if not os.path.isdir(V1_DIR):
            pytest.skip("v1 proposals absent")
        import glob
        sample = json.load(open(sorted(glob.glob(
            os.path.join(V1_DIR, "mem_*.json")))[0], encoding="utf-8"))
        assert sample["feature_dimensions"] == 47
        assert "embedding_version" not in sample

    def test_32_equal_weight_v2_proposals_remain_untouched(self):
        if not os.path.isdir(V2_DIR):
            pytest.skip("equal-weight v2 proposals absent")
        import glob
        sample = json.load(open(sorted(glob.glob(
            os.path.join(V2_DIR, "mem_*.json")))[0], encoding="utf-8"))
        assert sample["embedding_version"] == "descriptive.embedding.v2"
        assert sample["embedding_manifest_fingerprint"] == "emb:0110829ec9b77839"
        assert sample["embedding_manifest_fingerprint"] != EV2.manifest_fingerprint()

    def test_34_the_suite_never_writes_to_the_live_corpus(self):
        """The live corpus was empty until PROD-20260806 was authored on
        2026-08-06. Emptiness was never the invariant -- ISOLATION was. What
        must hold forever is that the suite writes to a redirected root and
        leaves the live store byte-identical (also enforced globally by the
        conftest mutation guard)."""
        assert "data" + os.sep + "ai_retrieval" not in vector_store._store_path()
