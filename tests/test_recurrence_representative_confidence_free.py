"""REMOVE-CONFIDENCE-FROM-RECURRENCE-REPRESENTATIVE (2026-08-06).

The declared law said **confidence may never decide the recurrence
representative**. The representative ordering then began with FULL-VECTOR
cosine -- and the confidence block sits in that vector at diagnostic weight
0.50. So confidence could still decide the representative, indirectly.

A failing test caught exactly this. The assertion was rewritten around the
contradiction instead of the contradiction being removed. These tests restore
the original claim and hold the real fix: ordinary retrieval similarity keeps
using the complete weighted v2.1 vector, and representative selection alone runs
on a projection with the diagnostic block zeroed.
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
from ai_retrieval import retrieval_contract as RC                 # noqa: E402
from ai_retrieval import vector_store                             # noqa: E402
from ai_retrieval.retrieval import retrieve_analogs               # noqa: E402

ARCHIVE = os.path.join("data", "replay_sessions", "PROD-20260806")
V21_DIR = os.path.join(ARCHIVE, "analysis", "proposed_descriptive_memory_v2_1")
EMPTY = {"level": None, "timeframe": None, "basis": None, "registered_at": None}

has_v21 = pytest.mark.skipif(not os.path.isdir(V21_DIR),
                             reason="v2.1 proposals are git-ignored")


def spec(**over):
    base = dict(
        session_id="PROD-20260806", session_date="2026-08-06", instrument="MNQ",
        contract="CON.F.US.MNQ.U26", segment_start="11:00:00",
        segment_end="11:20:00", scan_count=10, source_model="gpt-5.6-terra",
        brain_contract_fingerprint_suffix="x", market_regime="range_rotation",
        volatility_state="toxic", session_phase="lunch",
        narrative_phase="transition", delivery_state="accumulation_building",
        structure_state="witness_quiet",
        structure_evidence={"bos_count": 0, "mss_count": 0, "quiet": True},
        liquidity_state="two_sided_pools", protected_high=EMPTY,
        protected_low=EMPTY, active_draw_present=True, exhaustion_present=True,
        direction_distribution={"conflicted": 10},
        action_distribution={"stand_down": 10}, dominant_direction="conflicted",
        dominant_action="stand_down",
        phase_confidence_summary={"mean": 60.0, "min": 50.0, "max": 70.0},
        candidate_count=0, trade_count=0, no_candidate_reasons=["x"],
        source_artifact_ids=["a"], source_artifact_digest="d",
        created_at="2026-08-06T20:00:00+00:00")
    base.update(over)
    return base


def rec(**over):
    return DM.make_descriptive_record(**spec(**over))


def conf(value):
    return {"mean": value, "min": value, "max": value}


@pytest.fixture
def store(tmp_path, monkeypatch):
    monkeypatch.setenv("AI_RETRIEVAL_DIR", str(tmp_path / "r"))
    return tmp_path


def query(exhaustion=True, **over):
    q = {"session": "lunch", "contract": "CON.F.US.MNQ.U26",
         "market_regime": {"regime_label": "range_rotation",
                           "volatility_state": "toxic"},
         "narrative_authority": {"narrative_direction": "conflicted",
                                 "narrative_phase": "transition",
                                 "active_liquidity_draw": "29500"},
         "shared_context": {"delivery_state": "accumulation_building",
                            "exhaustion_present": exhaustion},
         "protected_swings": {},
         "liquidity": {"nearest_buy_side": 29800.0, "nearest_sell_side": 29200.0},
         # UNIT 3 — this is described below as a QUIET query, and quiet is now a
         # claim that requires an evaluated read. A witness stating no
         # evaluability is UNKNOWN, which cannot be authoritative quiet, so
         # without these the fixture would be a legacy payload rather than the
         # quiet query these assertions are about.
         "STRUCTURE_WITNESS": {
             tf: {"bos_event": False, "mss_event": False,
                  "bos_evaluation": {"capability": "DETECTOR_EVALUATED",
                                     "reason": None},
                  "mss_evaluation": {"capability": "DETECTOR_EVALUATED",
                                     "reason": None}}
             for tf in ("15m", "5m", "3m", "1m")},
         "phase_confidence_summary": {"mean": 60.0, "min": 50.0, "max": 70.0}}
    q.update(over)
    return q


def v21_records():
    import glob
    return sorted([json.load(open(p, encoding="utf-8"))
                   for p in glob.glob(os.path.join(V21_DIR, "mem_*.json"))],
                  key=lambda r: r["segment_start"])


# ══════════════════════════════════════════════════════════════════════════════
class TestTheProjection:
    """5, plus the guard that keeps it tied to the manifest."""

    def test_5_the_projection_excludes_every_confidence_coordinate(self):
        g = EV2._GROUP["confidence"]
        vec = [1.0] * EV2.EMBED_DIM_V2
        proj = EV2.representative_projection(vec)
        assert proj[g["start"]:g["end"]] == [0.0] * g["size"]
        assert vec[g["start"]:g["end"]] == [1.0] * g["size"]      # not mutated
        for i in range(EV2.EMBED_DIM_V2):
            if not (g["start"] <= i < g["end"]):
                assert proj[i] == vec[i]
        assert EV2.REPRESENTATIVE_EXCLUDED_GROUPS == ("confidence",)

    def test_confidence_cannot_reach_either_norm(self):
        """Zeroing on BOTH sides, not just the numerator: a confidence value
        must not move the denominator either."""
        a = rec(phase_confidence_summary=conf(5.0))
        b = rec(phase_confidence_summary=conf(95.0))
        c = rec(phase_confidence_summary=conf(50.0))
        base = rec()
        scores = {EV2.representative_similarity(base["feature_vector"],
                                                x["feature_vector"])
                  for x in (a, b, c)}
        assert len(scores) == 1, "confidence still moves representative cosine"

    def test_the_excluded_indices_come_from_the_manifest_not_literals(self):
        """A raw index would drift the moment the layout moves."""
        import ast
        tree = ast.parse(open("src/ai_retrieval/embedding_v2.py",
                              encoding="utf-8").read())
        fn = next(n for n in ast.walk(tree)
                  if isinstance(n, ast.FunctionDef)
                  and n.name == "representative_projection")
        literals = [n.value for n in ast.walk(fn)
                    if isinstance(n, ast.Constant) and isinstance(n.value, int)]
        assert not literals, f"hardcoded index in the projection: {literals}"

    def test_no_second_vector_space_is_persisted(self, store):
        """The projection is computed on demand; the stored record keeps one
        vector and one fingerprint."""
        r = rec()
        vector_store.add_record(r)
        stored = vector_store.load_records()[0]
        assert stored["feature_vector"] == r["feature_vector"]
        assert "representative_vector" not in stored
        assert EV2.vector_fingerprint(stored["feature_vector"]) == \
            stored["feature_vector_fingerprint"]


class TestRepresentativeIsConfidenceFree:
    """1-4, 8-9. The restored claim."""

    def test_1_members_differing_only_in_confidence_still_group(self, store):
        vector_store.add_records([
            rec(segment_start="11:00:00", source_artifact_digest="d1"),
            rec(segment_start="12:00:00", source_artifact_digest="d2",
                phase_confidence_summary=conf(95.0))])
        out = retrieve_analogs(query(), persist_log=False, today="2026-08-07")
        assert out["returned"] == 1
        assert out["analogs"][0]["recurrence_count"] == 2

    def test_2_confidence_alone_cannot_change_the_representative(self, tmp_path,
                                                                 monkeypatch):
        """THE RESTORED ASSERTION.

        The same two occurrences, with only their confidence swapped between
        runs. Under the old full-vector ordering the representative moved.
        """
        picks = []
        for a_conf, b_conf in ((20.0, 99.0), (99.0, 20.0)):
            monkeypatch.setenv("AI_RETRIEVAL_DIR",
                               str(tmp_path / f"r{len(picks)}"))
            long_seg = rec(segment_start="11:00:00", segment_end="11:30:00",
                           scan_count=20, source_artifact_digest="d1",
                           direction_distribution={"conflicted": 20},
                           action_distribution={"stand_down": 20},
                           phase_confidence_summary=conf(a_conf))
            short_seg = rec(segment_start="12:00:00", segment_end="12:05:00",
                            scan_count=5, source_artifact_digest="d2",
                            direction_distribution={"conflicted": 5},
                            action_distribution={"stand_down": 5},
                            phase_confidence_summary=conf(b_conf))
            vector_store.add_records([long_seg, short_seg])
            out = retrieve_analogs(query(), persist_log=False,
                                   today="2026-08-07")
            assert out["returned"] == 1
            picks.append(out["analogs"][0]["representative_memory_id"]
                         == long_seg["memory_id"])
        assert picks == [True, True], "the representative moved with confidence"

    def test_3_high_confidence_cannot_defeat_a_higher_scan_count(self, store):
        long_seg = rec(segment_start="11:00:00", segment_end="11:30:00",
                       scan_count=20, source_artifact_digest="d1",
                       direction_distribution={"conflicted": 20},
                       action_distribution={"stand_down": 20},
                       phase_confidence_summary=conf(10.0))
        short_seg = rec(segment_start="12:00:00", segment_end="12:05:00",
                        scan_count=5, source_artifact_digest="d2",
                        direction_distribution={"conflicted": 5},
                        action_distribution={"stand_down": 5},
                        phase_confidence_summary=conf(100.0))
        vector_store.add_records([short_seg, long_seg])   # short written FIRST
        out = retrieve_analogs(query(), persist_log=False, today="2026-08-07")
        assert out["analogs"][0]["representative_memory_id"] == \
            long_seg["memory_id"]

    def test_4_very_low_confidence_cannot_disqualify_a_representative(self, store):
        floor = rec(segment_start="11:00:00", segment_end="11:30:00",
                    scan_count=20, source_artifact_digest="d1",
                    direction_distribution={"conflicted": 20},
                    action_distribution={"stand_down": 20},
                    phase_confidence_summary=conf(0.0))
        other = rec(segment_start="12:00:00", segment_end="12:10:00",
                    scan_count=8, source_artifact_digest="d2",
                    direction_distribution={"conflicted": 8},
                    action_distribution={"stand_down": 8},
                    phase_confidence_summary=conf(95.0))
        vector_store.add_records([floor, other])
        out = retrieve_analogs(query(), persist_log=False, today="2026-08-07")
        assert out["analogs"][0]["representative_memory_id"] == floor["memory_id"]

    def test_8_representative_selection_is_deterministic(self, store):
        vector_store.add_records([
            rec(segment_start=f"1{i}:00:00", segment_end=f"1{i}:20:00",
                source_artifact_digest=f"d{i}",
                phase_confidence_summary=conf(30.0 + 20 * i))
            for i in range(3)])
        picks = {retrieve_analogs(query(), persist_log=False,
                                  today="2026-08-07"
                                  )["analogs"][0]["representative_memory_id"]
                 for _ in range(5)}
        assert len(picks) == 1

    def test_9_representative_is_independent_of_insertion_order(self, tmp_path,
                                                                monkeypatch):
        members = [rec(segment_start=f"1{i}:00:00", segment_end=f"1{i}:20:00",
                       source_artifact_digest=f"d{i}",
                       phase_confidence_summary=conf(30.0 + 20 * i))
                   for i in range(3)]
        picks = []
        for order in (members, list(reversed(members))):
            monkeypatch.setenv("AI_RETRIEVAL_DIR",
                               str(tmp_path / f"r{len(picks)}"))
            vector_store.add_records(order)
            out = retrieve_analogs(query(), persist_log=False,
                                   today="2026-08-07")
            picks.append(out["analogs"][0]["representative_memory_id"])
        assert picks[0] == picks[1]

    def test_both_similarities_are_reported_per_member(self, store):
        vector_store.add_records([
            rec(segment_start="11:00:00", source_artifact_digest="d1"),
            rec(segment_start="12:00:00", source_artifact_digest="d2",
                phase_confidence_summary=conf(95.0))])
        an = retrieve_analogs(query(), persist_log=False,
                              today="2026-08-07")["analogs"][0]
        assert set(an["member_similarities"]) == set(an["grouped_memory_ids"])
        assert set(an["member_representative_similarities"]) == \
            set(an["grouped_memory_ids"])
        assert an["member_similarities"] != \
            an["member_representative_similarities"]


class TestOrdinaryRetrievalUnchanged:
    """6-7. Only representative selection changed."""

    def test_6_ordinary_similarity_still_uses_the_full_vector(self):
        a = rec(phase_confidence_summary=conf(60.0))
        b = rec(phase_confidence_summary=conf(5.0))
        full = EV2.cosine_v2(a["feature_vector"], b["feature_vector"])
        proj = EV2.representative_similarity(a["feature_vector"],
                                             b["feature_vector"])
        assert full != proj, "confidence no longer affects ordinary cosine"
        assert proj > full

    def test_7_structure_and_exhaustion_still_move_representative_similarity(self):
        base = rec()
        same = EV2.representative_similarity(base["feature_vector"],
                                             rec()["feature_vector"])
        struct = EV2.representative_similarity(
            base["feature_vector"],
            rec(structure_evidence={"bos_count": 4, "mss_count": 0,
                                    "quiet": False},
                structure_state="witness_bos_4_mss_0")["feature_vector"])
        exh = EV2.representative_similarity(
            base["feature_vector"], rec(exhaustion_present=False)["feature_vector"])
        assert same > struct and same > exh

    def test_the_threshold_and_caps_were_not_touched(self):
        assert RC.MIN_SIMILARITY == 0.60
        assert RC.MAX_ANALOGS == 5
        assert RC.MAX_ANALOGS_PER_SOURCE_SESSION == 2


class TestPolicyBinding:
    """18."""

    def test_the_policy_is_bound_into_the_contract(self):
        p = RC.retrieval_policy()
        assert p["representative_similarity_is_confidence_free"] is True
        assert p["representative_similarity_excludes"] == ["confidence"]
        assert p["semantic_recurrence_policy_version"] == "semantic_recurrence.v1.1"

    def test_18_the_brain_contract_fingerprint_changed(self):
        assert brain_contract_fingerprint() != "brain:cf9d16baeb09cc23"
        assert brain_contract_fingerprint().startswith("brain:")

    def test_the_embedding_manifest_matches_the_declared_version(self):
        """v2.2 (2026-08-07) corrected the delivery vocabulary against its
        authoritative producer, which moved the geometry deliberately."""
        assert EV2.EMBEDDING_VERSION == "descriptive.embedding.v2.2"
        assert EV2.EMBED_DIM_V2 == EV2.MANIFEST["dimensions"]
        assert EV2.manifest_fingerprint().startswith("emb:")


@has_v21
class TestAugust6StillHolds:
    """10-17."""

    def _load(self, tmp_path, monkeypatch):
        monkeypatch.setenv("AI_RETRIEVAL_DIR", str(tmp_path / "sim"))
        recs = v21_records()
        vector_store.add_records(recs)
        return recs

    def test_10_11_12_grouping_and_slot_use_are_unchanged(self, tmp_path,
                                                          monkeypatch):
        recs = self._load(tmp_path, monkeypatch)
        out = retrieve_analogs(query(), persist_log=False, today="2026-08-07")
        first = out["analogs"][0]
        assert first["recurrence_count"] == 2
        assert sorted(first["grouped_memory_ids"]) == sorted(
            [recs[3]["memory_id"], recs[5]["memory_id"]])          # #4 and #6
        assert recs[4]["memory_id"] not in first["grouped_memory_ids"]  # not #5
        assert out["returned"] == 2                                # one slot each

    def test_the_representative_tracks_market_evidence_not_confidence(
            self, tmp_path, monkeypatch):
        """Which occurrence speaks for the group follows the STRUCTURE the query
        describes, and nothing else.

        #4 carries bos=1, #6 is quiet, and their confidence means are 67.73 and
        73.69. A quiet query is an exact structural match for #6; a bos=1 query
        is an exact match for #4. The representative follows that -- not the
        confidence value, which under the old full-vector ordering was part of
        the decision.
        """
        recs = self._load(tmp_path, monkeypatch)
        four, six = recs[3], recs[5]

        rep = retrieve_analogs(query(), persist_log=False,
                               today="2026-08-07")["analogs"][0]
        assert rep["representative_memory_id"] == six["memory_id"]
        assert rep["member_representative_similarities"][six["memory_id"]] == 1.0

        bos_q = query()
        bos_q["STRUCTURE_WITNESS"] = {tf: {"bos_event": i < 1, "mss_event": False}
                                      for i, tf in enumerate(("15m", "5m",
                                                              "3m", "1m"))}
        rep2 = retrieve_analogs(bos_q, persist_log=False,
                                today="2026-08-07")["analogs"][0]
        assert rep2["representative_memory_id"] == four["memory_id"]
        # the GROUP is identical in both cases -- only its spokesman moved
        assert rep["grouped_memory_ids"] == rep2["grouped_memory_ids"]

    def test_the_representative_never_moves_with_confidence_alone(
            self, tmp_path, monkeypatch):
        """Same query, same records, one member's confidence perturbed by 35
        points: the representative must not move."""
        import copy
        recs = v21_records()
        picks = []
        for bump in (0.0, 35.0):
            monkeypatch.setenv("AI_RETRIEVAL_DIR",
                               str(tmp_path / f"c{len(picks)}"))
            mutated = []
            for i, r in enumerate(recs):
                c = copy.deepcopy(r)
                if i == 3:                       # move ONLY #4's confidence
                    summary = dict(c["phase_confidence_summary"])
                    summary["mean"] = min(100.0, summary["mean"] + bump)
                    c["phase_confidence_summary"] = summary
                    c["feature_vector"] = DM.embed_descriptive(c)
                    c["feature_vector_fingerprint"] = \
                        EV2.vector_fingerprint(c["feature_vector"])
                mutated.append(c)
            vector_store.add_records(mutated)
            out = retrieve_analogs(query(), persist_log=False,
                                   today="2026-08-07")
            picks.append(out["analogs"][0]["representative_memory_id"])
        assert picks[0] == picks[1], "confidence moved the representative"

    def test_13_14_gate_precedes_grouping_and_cap_follows(self, tmp_path,
                                                          monkeypatch):
        self._load(tmp_path, monkeypatch)
        out = retrieve_analogs(query(), persist_log=False, today="2026-08-07")
        assert out["rejected_reasons"].get("load_bearing_contradiction", 0) > 0
        for g in out["recurrence_groups_collapsed"]:
            assert g["count"] >= 2
        assert out["returned"] <= RC.MAX_ANALOGS_PER_SOURCE_SESSION

    def test_15_16_analogs_stay_context_only_and_carry_no_execution_fields(
            self, tmp_path, monkeypatch):
        self._load(tmp_path, monkeypatch)
        out = retrieve_analogs(query(), persist_log=False, today="2026-08-07")
        assert out["analogs"]
        for a in out["analogs"]:
            assert a["authority"] == "CONTEXT_ONLY"
            assert a["outcome_validated"] is False
            assert a["recommendation_authority"] == "none"
            assert a["execution_authority"] == "none"
            for field in ("risk_usd", "contracts", "size", "reward_to_risk",
                          "invalidation_level", "objective", "stop_points"):
                assert field not in a, field

    def test_17_the_live_corpus_is_untouched_by_these_tests(self):
        live = os.path.join("data", "ai_retrieval", "memory_store.jsonl")
        if not os.path.exists(live):
            pytest.skip("live store absent")
        assert "data" + os.sep + "ai_retrieval" not in vector_store._store_path()
