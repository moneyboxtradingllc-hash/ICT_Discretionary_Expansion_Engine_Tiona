"""REFINE-SEMANTIC-RECURRENCE-COLLAPSE (2026-08-06).

The exact-vector recurrence rule was too narrow. August 6 segments #4 and #6
agree on every load-bearing block, on session phase, on narrative phase and on
the direction distribution; they differ only in the structure witness
(contextual) and in confidence (diagnostic). Their vectors are therefore not
identical -- cosine 0.9749 -- so exact-vector collapse never fired, and the two
consumed BOTH of the session's allowed retrieval slots. A future Terra query
would have read one quiet Thursday as two independent precedents.

Recurrence is now decided on SEMANTIC FIELDS, never on cosine. A high similarity
score alone must never authorise grouping: two records can score 0.97 while
disagreeing on delivery, and delivery is load-bearing.
"""
from __future__ import annotations

import copy
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


def key(**over):
    return EV2.semantic_recurrence_key(rec(**over))


def groups(a_over, b_over):
    ka, kb = key(**a_over), key(**b_over)
    return ka is not None and ka == kb


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
                            "exhaustion_present": True},
         "protected_swings": {},
         "liquidity": {"nearest_buy_side": 29800.0, "nearest_sell_side": 29200.0},
         "STRUCTURE_WITNESS": {tf: {"bos_event": False, "mss_event": False}
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
class TestCollapseHappens:
    """1-2, 5-6, 18-19."""

    def test_1_exact_same_session_vectors_collapse(self, store):
        a = rec(segment_start="11:00:00", segment_end="11:10:00",
                source_artifact_digest="d1")
        b = rec(segment_start="12:00:00", segment_end="12:20:00",
                source_artifact_digest="d2")
        assert a["feature_vector_fingerprint"] == b["feature_vector_fingerprint"]
        vector_store.add_records([a, b])
        out = retrieve_analogs(query(), persist_log=False, today="2026-08-07")
        assert out["returned"] == 1
        assert out["analogs"][0]["recurrence_type"] == "exact_same_session"

    def test_2_semantically_recurrent_vectors_collapse(self, store):
        """Different vectors, same market state."""
        a = rec(segment_start="11:00:00", segment_end="11:10:00",
                source_artifact_digest="d1")
        b = rec(segment_start="12:00:00", segment_end="12:20:00",
                source_artifact_digest="d2",
                structure_evidence={"bos_count": 2, "mss_count": 0,
                                    "quiet": False},
                structure_state="witness_bos_2_mss_0",
                phase_confidence_summary={"mean": 85.0, "min": 80.0,
                                          "max": 90.0})
        assert a["feature_vector_fingerprint"] != b["feature_vector_fingerprint"]
        vector_store.add_records([a, b])
        out = retrieve_analogs(query(), persist_log=False, today="2026-08-07")
        assert out["returned"] == 1
        assert out["analogs"][0]["recurrence_type"] == "semantic_same_session"
        assert out["analogs"][0]["recurrence_count"] == 2

    def test_5_grouping_preserves_both_underlying_records(self, store):
        vector_store.add_records([
            rec(segment_start="11:00:00", source_artifact_digest="d1"),
            rec(segment_start="12:00:00", source_artifact_digest="d2",
                phase_confidence_summary={"mean": 90.0, "min": 90.0,
                                          "max": 90.0})])
        assert vector_store.count() == 2      # collapse is retrieval-only
        retrieve_analogs(query(), persist_log=False, today="2026-08-07")
        assert vector_store.count() == 2

    def test_6_a_group_consumes_one_retrieval_slot(self, store):
        for i in range(4):
            vector_store.add_record(rec(
                segment_start=f"1{i}:00:00", segment_end=f"1{i}:20:00",
                source_artifact_digest=f"d{i}",
                phase_confidence_summary={"mean": 60.0 + i, "min": 50.0,
                                          "max": 70.0}))
        out = retrieve_analogs(query(), persist_log=False, today="2026-08-07")
        assert out["returned"] == 1
        assert out["analogs"][0]["recurrence_count"] == 4

    def test_7_the_second_session_slot_stays_available(self, store):
        vector_store.add_records([
            rec(segment_start="11:00:00", source_artifact_digest="d1"),
            rec(segment_start="12:00:00", source_artifact_digest="d2",
                phase_confidence_summary={"mean": 90.0, "min": 90.0,
                                          "max": 90.0}),
            # a genuinely distinct state from the SAME session
            rec(segment_start="13:00:00", source_artifact_digest="d3",
                narrative_phase="exhaustion")])
        out = retrieve_analogs(query(), persist_log=False, today="2026-08-07")
        assert out["returned"] == 2
        assert out["analogs"][0]["recurrence_count"] == 2
        assert out["analogs"][1].get("recurrence_count") is None

    def test_18_confidence_alone_does_not_prevent_recurrence(self):
        assert groups({}, {"phase_confidence_summary": {"mean": 99.0,
                                                        "min": 99.0,
                                                        "max": 99.0}})

    def test_19_structure_witness_alone_may_collapse(self):
        assert groups({}, {"structure_evidence": {"bos_count": 3,
                                                  "mss_count": 1,
                                                  "quiet": False},
                           "structure_state": "witness_bos_3_mss_1"})
        assert "structure_evidence" in EV2.RECURRENCE_PERMITTED_CONTEXTUAL_DIFFERENCES

    def test_exhaustion_alone_may_collapse(self):
        assert groups({}, {"exhaustion_present": False})
        assert "exhaustion_present" in EV2.RECURRENCE_PERMITTED_CONTEXTUAL_DIFFERENCES


class TestCollapseRefused:
    """8-17. The semantic field law, not the score, decides."""

    def test_8_different_sessions_do_not_collapse(self, store):
        a = rec(session_id="PROD-A", session_date="2026-08-04",
                source_artifact_digest="d1")
        b = rec(session_id="PROD-B", session_date="2026-08-05",
                source_artifact_digest="d2")
        assert a["feature_vector_fingerprint"] == b["feature_vector_fingerprint"]
        vector_store.add_records([a, b])
        out = retrieve_analogs(query(), persist_log=False, today="2026-08-07")
        assert out["returned"] == 2
        assert not out["recurrence_groups_collapsed"]

    def test_9_different_contracts_do_not_collapse(self):
        assert not groups({}, {"contract": "CON.F.US.MNQ.Z26"})

    def test_10_different_instruments_do_not_collapse(self):
        assert not groups({}, {"instrument": "ES"})

    def test_11_different_regimes_do_not_collapse(self):
        assert not groups({}, {"market_regime": "chop"})

    def test_12_different_volatility_does_not_collapse(self):
        assert not groups({}, {"volatility_state": "stable"})

    def test_13_different_delivery_does_not_collapse(self):
        assert not groups({}, {"delivery_state": "mixed"})

    def test_14_materially_different_direction_does_not_collapse(self):
        assert not groups({}, {"direction_distribution": {"neutral": 10},
                               "dominant_direction": "neutral"})
        # 33% shift is well outside the tolerance
        assert not groups({}, {"direction_distribution": {"conflicted": 10,
                                                          "neutral": 5},
                               "scan_count": 15,
                               "action_distribution": {"stand_down": 15}})

    def test_a_direction_shift_inside_tolerance_still_collapses(self):
        assert EV2.DIRECTION_COMPONENT_TOLERANCE == 0.10
        assert groups({}, {"direction_distribution": {"conflicted": 20},
                           "scan_count": 20,
                           "action_distribution": {"stand_down": 20}})

    def test_15_different_liquidity_does_not_collapse(self):
        assert not groups({}, {"liquidity_state": "buy_side_only"})

    def test_16_different_active_draw_does_not_collapse(self):
        assert not groups({}, {"active_draw_present": False})

    def test_17_different_protected_presence_does_not_collapse(self):
        assert not groups({}, {"protected_low": {"level": 29500.0,
                                                 "timeframe": "5m",
                                                 "basis": "x",
                                                 "registered_at": "t"}})

    def test_different_manifest_or_version_does_not_collapse(self):
        a, b = rec(), rec()
        b["embedding_manifest_fingerprint"] = "emb:deadbeef"
        assert EV2.semantic_recurrence_key(a) != EV2.semantic_recurrence_key(b)
        c = rec()
        c["embedding_version"] = "descriptive.embedding.v9"
        assert EV2.semantic_recurrence_key(a) != EV2.semantic_recurrence_key(c)

    def test_contextual_exact_fields_are_enforced(self):
        assert not groups({}, {"session_phase": "afternoon"})
        assert not groups({}, {"narrative_phase": "accumulation"})

    def test_a_high_cosine_alone_never_authorises_grouping(self, store):
        """0.97 similarity with a delivery disagreement must stay two records."""
        a = rec(segment_start="11:00:00", source_artifact_digest="d1")
        b = rec(segment_start="12:00:00", source_artifact_digest="d2",
                delivery_state="mixed")
        assert EV2.cosine_v2(a["feature_vector"], b["feature_vector"]) > 0.85
        vector_store.add_records([a, b])
        out = retrieve_analogs(query(), persist_log=False, today="2026-08-07")
        assert not out["recurrence_groups_collapsed"]

    def test_an_unkeyable_record_never_groups(self):
        assert EV2.semantic_recurrence_key({}) is None
        broken = rec()
        broken["direction_distribution"] = {}
        assert EV2.semantic_recurrence_key(broken) is None


class TestRepresentativeAndOrdering:
    """20-24."""

    def test_20_representative_selection_is_deterministic(self, store):
        """Same inputs, same representative, every time."""
        members = [rec(segment_start=f"1{i}:00:00", segment_end=f"1{i}:20:00",
                       source_artifact_digest=f"d{i}")
                   for i in range(3)]
        vector_store.add_records(members)
        picks = {retrieve_analogs(query(), persist_log=False,
                                  today="2026-08-07"
                                  )["analogs"][0]["representative_memory_id"]
                 for _ in range(5)}
        assert len(picks) == 1

    def test_21_confidence_is_not_a_selection_criterion(self, store):
        """With similarity TIED, scan count decides -- not confidence.

        Confidence still sits in the vector at diagnostic weight, so it can
        move similarity; what it may never be is a RULE in the ordering. The
        two members here carry identical confidence, so similarity ties and the
        tie-break law is what is actually under test.
        """
        assert "confidence" not in " ".join(RC.RECURRENCE_REPRESENTATIVE_ORDER)
        long_seg = rec(segment_start="11:00:00", segment_end="11:30:00",
                       scan_count=20, source_artifact_digest="d1",
                       direction_distribution={"conflicted": 20},
                       action_distribution={"stand_down": 20})
        short_seg = rec(segment_start="12:00:00", segment_end="12:05:00",
                        scan_count=5, source_artifact_digest="d2",
                        direction_distribution={"conflicted": 5},
                        action_distribution={"stand_down": 5})
        vector_store.add_records([short_seg, long_seg])   # short written FIRST
        out = retrieve_analogs(query(), persist_log=False, today="2026-08-07")
        assert out["returned"] == 1
        assert out["analogs"][0]["representative_memory_id"] ==             long_seg["memory_id"]

    def test_a_more_confident_occurrence_does_not_win_on_confidence_alone(
            self, store):
        """Equal similarity contribution from every other block; the member
        with 99 confidence must not be preferred BECAUSE it is confident."""
        a = rec(segment_start="11:00:00", segment_end="11:30:00", scan_count=20,
                source_artifact_digest="d1",
                direction_distribution={"conflicted": 20},
                action_distribution={"stand_down": 20},
                phase_confidence_summary={"mean": 60.0, "min": 50.0,
                                          "max": 70.0})
        b = rec(segment_start="12:00:00", segment_end="12:30:00", scan_count=20,
                source_artifact_digest="d2",
                direction_distribution={"conflicted": 20},
                action_distribution={"stand_down": 20},
                phase_confidence_summary={"mean": 99.0, "min": 99.0,
                                          "max": 99.0})
        vector_store.add_records([a, b])
        out = retrieve_analogs(query(), persist_log=False, today="2026-08-07")
        assert out["returned"] == 1
        # `a` matches the query's own confidence profile, so it leads on
        # similarity; the 99-confidence member does not win for being confident.
        assert out["analogs"][0]["representative_memory_id"] == a["memory_id"]
        assert out["analogs"][0]["diagnostic_differences"]["confidence_mean"]

    def test_similarity_leads_the_representative_law(self):
        assert RC.RECURRENCE_REPRESENTATIVE_ORDER[0] == "similarity_desc"

    def test_22_ranking_is_independent_of_append_order(self, tmp_path,
                                                       monkeypatch):
        members = [rec(segment_start=f"1{i}:00:00", source_artifact_digest=f"d{i}",
                       phase_confidence_summary={"mean": 60.0 + i, "min": 50.0,
                                                 "max": 70.0})
                   for i in range(3)]
        distinct = rec(segment_start="14:00:00", source_artifact_digest="dx",
                       narrative_phase="exhaustion")
        seen = []
        for order in ([*members, distinct], [distinct, *reversed(members)]):
            monkeypatch.setenv("AI_RETRIEVAL_DIR", str(tmp_path / f"r{len(seen)}"))
            vector_store.add_records(order)
            out = retrieve_analogs(query(), persist_log=False, today="2026-08-07")
            seen.append([(a["memory_id"], a.get("recurrence_count"))
                         for a in out["analogs"]])
        assert seen[0] == seen[1]

    def test_23_contradiction_gating_precedes_grouping(self, store):
        """A gated record can never appear inside a recurrence group."""
        vector_store.add_records([
            rec(segment_start="11:00:00", source_artifact_digest="d1"),
            rec(segment_start="12:00:00", source_artifact_digest="d2",
                market_regime="trend_down",
                direction_distribution={"bearish": 10},
                dominant_direction="bearish")])
        out = retrieve_analogs(query(), persist_log=False, today="2026-08-07",
                               min_similarity=0.0)
        assert out["rejected_reasons"]["load_bearing_contradiction"] == 1
        assert out["returned"] == 1
        assert out["analogs"][0].get("recurrence_count") is None

    def test_24_the_session_cap_runs_after_grouping(self, store):
        """Three recurrent + two distinct: the group takes ONE slot, so a
        distinct state gets the second rather than being crowded out."""
        for i in range(3):
            vector_store.add_record(rec(
                segment_start=f"1{i}:00:00", source_artifact_digest=f"g{i}",
                phase_confidence_summary={"mean": 60.0 + i, "min": 50.0,
                                          "max": 70.0}))
        vector_store.add_record(rec(segment_start="14:00:00",
                                    source_artifact_digest="dx",
                                    narrative_phase="exhaustion"))
        out = retrieve_analogs(query(), persist_log=False, today="2026-08-07")
        assert out["returned"] == 2
        assert out["analogs"][0]["recurrence_count"] == 3
        assert out["analogs"][1].get("recurrence_count") is None

    def test_30_recurrence_metadata_is_truthful(self, store):
        a = rec(segment_start="11:00:00", segment_end="11:10:00",
                source_artifact_digest="d1")
        b = rec(segment_start="12:00:00", segment_end="12:20:00",
                source_artifact_digest="d2",
                phase_confidence_summary={"mean": 90.0, "min": 90.0,
                                          "max": 90.0})
        vector_store.add_records([a, b])
        out = retrieve_analogs(query(), persist_log=False, today="2026-08-07")
        an = out["analogs"][0]
        assert an["recurrence_count"] == 2
        assert an["occurrence_spans"] == ["11:00:00-11:10:00",
                                          "12:00:00-12:20:00"]
        assert sorted(an["grouped_memory_ids"]) == sorted(
            [a["memory_id"], b["memory_id"]])
        assert set(an["member_similarities"]) == set(an["grouped_memory_ids"])
        assert an["diagnostic_differences"]["confidence_mean"]
        assert an["representative_memory_id"] in an["grouped_memory_ids"]


@has_v21
class TestAugust6:
    """3-4, 25-29."""

    def _load(self, tmp_path, monkeypatch):
        monkeypatch.setenv("AI_RETRIEVAL_DIR", str(tmp_path / "sim"))
        recs = v21_records()
        vector_store.add_records(recs)
        return recs

    def _q(self, session, regime, vol, ndir, nphase, delivery, bos=1,
           conf=70.0, exh=False):
        return {"session": session, "contract": "CON.F.US.MNQ.U26",
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

    def test_3_records_4_and_6_form_one_group(self):
        recs = v21_records()
        assert len(recs) == 10
        k = {}
        for i, r in enumerate(recs, 1):
            k.setdefault(EV2.semantic_recurrence_key(r), []).append(i)
        grouped = sorted(v for v in k.values() if len(v) > 1)
        assert grouped == [[4, 6]], grouped

    def test_4_record_5_does_not_join(self):
        recs = v21_records()
        assert recs[4]["delivery_state"] != recs[3]["delivery_state"]
        assert EV2.semantic_recurrence_key(recs[4]) != \
            EV2.semantic_recurrence_key(recs[3])

    def test_record_3_does_not_join(self):
        """Agrees on every load-bearing field and on direction; held out by
        session phase and narrative phase. #3 IS the exhaustion segment."""
        recs = v21_records()
        three, four = recs[2], recs[3]
        for f in EV2.RECURRENCE_LOAD_BEARING_FIELDS:
            assert three[f] == four[f], f
        assert three["narrative_phase"] != four["narrative_phase"]
        assert three["session_phase"] != four["session_phase"]
        assert EV2.semantic_recurrence_key(three) != \
            EV2.semantic_recurrence_key(four)

    def test_the_group_takes_one_slot_and_a_distinct_state_takes_the_other(
            self, tmp_path, monkeypatch):
        recs = self._load(tmp_path, monkeypatch)
        out = retrieve_analogs(self._q("lunch", "range_rotation", "toxic",
                                       "conflicted", "transition",
                                       "accumulation_building", conf=65.0,
                                       exh=True),
                               persist_log=False, today="2026-08-07")
        assert out["returned"] == 2
        first, second = out["analogs"]
        assert first["recurrence_type"] == "semantic_same_session"
        assert first["recurrence_count"] == 2
        assert sorted(first["grouped_memory_ids"]) == sorted(
            [recs[3]["memory_id"], recs[5]["memory_id"]])
        assert first["representative_memory_id"] == recs[3]["memory_id"]
        # the second slot goes to a genuinely different state
        assert second["memory_id"] == recs[2]["memory_id"]
        assert second.get("recurrence_count") is None

    def test_the_group_reports_its_real_differences(self, tmp_path, monkeypatch):
        self._load(tmp_path, monkeypatch)
        out = retrieve_analogs(self._q("lunch", "range_rotation", "toxic",
                                       "conflicted", "transition",
                                       "accumulation_building", conf=65.0,
                                       exh=True),
                               persist_log=False, today="2026-08-07")
        an = out["analogs"][0]
        assert "structure_evidence" in an["contextual_differences"]
        assert "confidence_mean" in an["diagnostic_differences"]
        assert len(an["member_similarities"]) == 2

    def test_28_exhaustion_still_retrieves_the_true_segment(self, tmp_path,
                                                            monkeypatch):
        recs = self._load(tmp_path, monkeypatch)
        out = retrieve_analogs(self._q("morning_continuation", "range_rotation",
                                       "toxic", "conflicted", "exhaustion",
                                       "accumulation_building", conf=85.0,
                                       exh=True),
                               persist_log=False, today="2026-08-07")
        assert out["analogs"][0]["memory_id"] == recs[2]["memory_id"]
        assert out["analogs"][0]["similarity"] > 0.99

    @pytest.mark.parametrize("label,args", [
        ("bullish expansion", ("ny_open", "expansion_up", "stable", "bullish",
                               "continuation", "full_distribution_alignment")),
        ("bearish delivery", ("morning_continuation", "trend_down", "unstable",
                              "bearish", "distribution",
                              "full_distribution_alignment")),
        ("volatility expansion", ("afternoon", "high_volatility", "explosive",
                                  "bearish", "distribution",
                                  "manipulation_to_distribution")),
    ])
    def test_25_26_27_absent_states_remain_empty(self, tmp_path, monkeypatch,
                                                 label, args):
        self._load(tmp_path, monkeypatch)
        out = retrieve_analogs(self._q(*args, bos=2),
                               persist_log=False, today="2026-08-07",
                               min_similarity=0.0)
        assert out["returned"] == 0, label
        assert out["rejected_reasons"]["load_bearing_contradiction"] == 10

    def test_29_every_analog_remains_context_only(self, tmp_path, monkeypatch):
        self._load(tmp_path, monkeypatch)
        for args in (("lunch", "range_rotation", "toxic", "conflicted",
                      "transition", "accumulation_building"),
                     ("lunch", "chop", "stable", "neutral", "transition",
                      "mixed")):
            out = retrieve_analogs(self._q(*args), persist_log=False,
                                   today="2026-08-07")
            for a in out["analogs"]:
                assert a["authority"] == "CONTEXT_ONLY"
                assert a["outcome_validated"] is False
                assert a["recommendation_authority"] == "none"
                assert a["execution_authority"] == "none"

    def test_the_structure_display_matches_the_embedded_evidence(self):
        """Defect found this mission: the display string was the MODE of the
        per-scan labels while the vector read the segment MEAN, so #3 and #4
        displayed `witness_quiet` while carrying bos=1."""
        for r in v21_records():
            ev = r["structure_evidence"]
            expected = ("witness_quiet" if ev["quiet"]
                        else f"witness_bos_{ev['bos_count']}_mss_{ev['mss_count']}")
            assert r["structure_state"] == expected, r["memory_id"]

    def test_generation_remains_deterministic_and_ten_segments(self):
        a = MA.build_records(ARCHIVE, now_iso="2026-08-06T20:00:00+00:00")
        b = MA.build_records(ARCHIVE, now_iso="2026-08-06T20:00:00+00:00")
        assert len(a["records"]) == 10
        assert [r["feature_vector_fingerprint"] for r in a["records"]] == \
               [r["feature_vector_fingerprint"] for r in b["records"]]

    def test_all_ten_records_still_validate(self):
        """Everything except the CURRENT-contract check, which they cannot pass.

        STEP 4B.12 §4 UNIT 3 — `validate_descriptive_record` is the AUTHORING
        gate: it answers "may this record be written under the contract in force
        now". The stored records were authored under structure parser v1 and the
        contract in force is v2, so the honest answer is no -- and that refusal
        is the write-side protection working, not corpus rot. Their readability
        is a separate question, settled by `vector_compatibility`.
        """
        from ai_retrieval import embedding_v2 as EV2
        from ai_retrieval import retrieval as R
        legacy_fp = EV2.legacy_manifest_fingerprint("structure_witness_v1")
        for r in v21_records():
            ok, reasons = DM.validate_descriptive_record(r)
            # the ONLY reason may be the contract-version marker
            assert reasons == ["embedding_manifest_fingerprint_mismatch"], \
                (r["memory_id"], reasons)
            assert ok is False
            assert r["embedding_manifest_fingerprint"] == legacy_fp
            # and every one of them remains READABLE
            assert R.vector_compatibility(r)["compatible"] is True
            assert not DM.scan_evaluative_language(r)

    def test_a_current_contract_record_still_validates_cleanly(self):
        """The gate is version-scoped, not broken: rebuild under v2 and it passes."""
        import os
        from ai_retrieval import memory_authoring as MA
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        native = os.path.join(root, "data", "replay_sessions", "PROD-20260806")
        if not os.path.isdir(native):
            pytest.skip("archive not present in this checkout")
        for rec in MA.build_records(native)["records"]:
            ok, reasons = DM.validate_descriptive_record(rec)
            assert ok, (rec["memory_id"], reasons)


class TestContractAndHygiene:
    """31-33."""

    def test_the_policy_is_bound_into_the_contract(self):
        p = RC.retrieval_policy()
        assert p["recurrence_mode"] == "semantic_same_session"
        assert p["recurrence_load_bearing_fields"] == \
            list(EV2.RECURRENCE_LOAD_BEARING_FIELDS)
        assert p["recurrence_contextual_exact_fields"] == \
            list(EV2.RECURRENCE_CONTEXTUAL_EXACT_FIELDS)
        assert p["direction_component_tolerance"] == \
            EV2.DIRECTION_COMPONENT_TOLERANCE
        assert p["recurrence_representative_order"][0] == "similarity_desc"

    def test_32_the_brain_contract_fingerprint_changed(self):
        assert brain_contract_fingerprint() != "brain:8ced919ee82fba0a"
        assert brain_contract_fingerprint().startswith("brain:")

    def test_the_caps_were_not_raised(self):
        assert RC.MAX_ANALOGS == 5
        assert RC.MAX_ANALOGS_PER_SOURCE_SESSION == 2
        assert RC.MIN_SIMILARITY == 0.60

    def test_31_the_suite_never_writes_to_the_live_corpus(self):
        """The live corpus was empty until PROD-20260806 was authored on
        2026-08-06. Emptiness was never the invariant -- ISOLATION was. What
        must hold forever is that the suite writes to a redirected root and
        leaves the live store byte-identical (also enforced globally by the
        conftest mutation guard)."""
        assert "data" + os.sep + "ai_retrieval" not in vector_store._store_path()
