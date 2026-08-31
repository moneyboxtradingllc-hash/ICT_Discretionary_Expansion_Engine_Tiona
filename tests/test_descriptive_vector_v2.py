"""REFINE-DESCRIPTIVE-MEMORY-VECTOR-V2 (2026-08-06).

The ten proposed August 6 records were reviewed and REFUSED before authoring --
not because the records were wrong, but because the similarity space was. The
review measured it:

  * `delivery_direction` was routed through `_norm_dir()`, a DIRECTIONAL
    normaliser. Every real ICT delivery state fell through to `none`, so one
    dimension was on in all ten records and in five of six queries. It added
    +0.05..0.07 to every pair and was solely responsible for the
    volatility-expansion query returning a "match" (0.5345 with it, 0.4629
    without).
  * `structure_state` and `liquidity_state` were invisible.
  * confidence and exhaustion dimensions were permanently zero.
  * records #4/#5/#6 had byte-identical vectors while #5 differed materially.
  * ranking tie-breaks fell through to JSONL append order.

The corpus was still empty, so the space was replaced rather than migrated.
These tests hold the new one.
"""
from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src"))

from _step7_fixture import detected as _detected      # noqa: E402
from _step7_fixture import priced as _priced          # noqa: E402

from ai_brain.production_model import (PRODUCTION_MODEL,  # noqa: E402
                                       brain_contract_fingerprint)
from ai_retrieval import descriptive_memory as DM              # noqa: E402
from ai_retrieval import embedding_v2 as EV2                   # noqa: E402
from ai_retrieval import memory_authoring as MA                # noqa: E402
from ai_retrieval import retrieval_contract as RC              # noqa: E402
from ai_retrieval import vector_store                          # noqa: E402
from ai_retrieval.retrieval import (apply_session_cap,          # noqa: E402
                                    collapse_recurrence, query_vector,
                                    ranking_tuple, retrieve_analogs,
                                    segment_duration)
from broker.luna_candidate_producer import (CandidateProducer,  # noqa: E402
                                            NoCandidate)
from broker.topstepx_client import TopstepXContract            # noqa: E402

ARCHIVE = os.path.join("data", "replay_sessions", "PROD-20260806")
V2_DIR = os.path.join(ARCHIVE, "analysis", "proposed_descriptive_memory_v2_1")
V2_EQUAL_DIR = os.path.join(ARCHIVE, "analysis", "proposed_descriptive_memory_v2")
V1_DIR = os.path.join(ARCHIVE, "analysis", "proposed_descriptive_memory")
MNQ = TopstepXContract(id="CON.F.US.MNQ.U26", name="MNQU6", description="MNQ",
                       tick_size=0.25, tick_value=0.5, active=True)
EMPTY_LEVEL = {"level": None, "timeframe": None, "basis": None,
               "registered_at": None}

archived = pytest.mark.skipif(not os.path.isdir(ARCHIVE),
                              reason="PROD-20260806 archive is git-ignored")


def record(**over):
    base = dict(
        session_id="PROD-20260806", session_date="2026-08-06", instrument="MNQ",
        contract="CON.F.US.MNQ.U26", segment_start="11:31:44",
        segment_end="11:42:39", scan_count=10, source_model=PRODUCTION_MODEL,
        brain_contract_fingerprint_suffix="abc123",
        market_regime="range_rotation", volatility_state="toxic",
        session_phase="lunch", narrative_phase="transition",
        delivery_state="accumulation_building", structure_state="witness_quiet",
        structure_evidence={"bos_count": 0, "mss_count": 0, "quiet": True,
                            "parser": "structure_witness_v1"},
        liquidity_state="two_sided_pools", protected_high=EMPTY_LEVEL,
        protected_low=EMPTY_LEVEL, active_draw_present=True,
        exhaustion_present=False, direction_distribution={"conflicted": 10},
        action_distribution={"stand_down": 10}, dominant_direction="conflicted",
        dominant_action="stand_down",
        phase_confidence_summary={"observations": 10, "mean": 61.0,
                                  "min": 40.0, "max": 80.0},
        candidate_count=0, trade_count=0,
        no_candidate_reasons=["action_declines_entry"],
        source_artifact_ids=["a.json"], source_artifact_digest="d1",
        created_at="2026-08-06T20:00:00+00:00")
    base.update(over)
    return DM.make_descriptive_record(**base)


@pytest.fixture
def store(tmp_path, monkeypatch):
    monkeypatch.setenv("AI_RETRIEVAL_DIR", str(tmp_path / "retrieval"))
    return tmp_path


def v2_records():
    import glob
    return sorted([json.load(open(p, encoding="utf-8"))
                   for p in glob.glob(os.path.join(V2_DIR, "mem_*.json"))],
                  key=lambda r: r["segment_start"])


has_v2 = pytest.mark.skipif(not os.path.isdir(V2_DIR),
                            reason="v2 proposals are git-ignored")


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
         "phase_confidence_summary": {"mean": 61.0, "min": 40.0, "max": 80.0}}
    q.update(over)
    return q


# ══════════════════════════════════════════════════════════════════════════════
class TestManifest:
    """1-6. One manifest, shared by writer and reader."""

    def test_1_the_vector_has_the_declared_dimension_count(self):
        assert EV2.EMBED_DIM_V2 == EV2.MANIFEST["dimensions"]
        assert len(record()["feature_vector"]) == EV2.EMBED_DIM_V2

    def test_2_the_manifest_covers_every_index_exactly_once(self):
        covered = []
        for g in EV2.MANIFEST["groups"]:
            assert g["end"] - g["start"] == g["size"]
            covered += list(range(g["start"], g["end"]))
        assert covered == list(range(EV2.EMBED_DIM_V2))
        assert sum(g["size"] for g in EV2.MANIFEST["groups"]) == EV2.EMBED_DIM_V2

    def test_3_writer_and_reader_use_the_same_manifest(self, store):
        rec = record()
        assert rec["embedding_manifest_fingerprint"] == EV2.manifest_fingerprint()
        assert RC.retrieval_policy()["embedding_manifest_fingerprint"] == \
            EV2.manifest_fingerprint()
        vector_store.add_record(rec)
        out = retrieve_analogs(query(), persist_log=False, today="2026-08-07")
        assert out["embedding_manifest_fingerprint"] == EV2.manifest_fingerprint()
        assert out["returned"] == 1

    def test_4_an_unsupported_embedding_version_is_rejected(self, store):
        vector_store.add_record({**record(), "embedding_version": "v1"})
        out = retrieve_analogs(query(), persist_log=False, today="2026-08-07")
        assert out["returned"] == 0
        assert out["rejected_reasons"] == {"embedding_version_mismatch": 1}

    def test_5_a_wrong_dimension_vector_is_rejected(self, store):
        bad = record()
        bad["feature_vector"] = bad["feature_vector"][:40]
        vector_store.add_record(bad)
        out = retrieve_analogs(query(), persist_log=False, today="2026-08-07")
        assert out["returned"] == 0
        assert out["rejected_reasons"] == {"embedding_dimension_mismatch": 1}

    def test_6_a_mismatched_manifest_fingerprint_is_rejected(self, store):
        vector_store.add_record({**record(),
                                 "embedding_manifest_fingerprint": "emb:deadbeef"})
        out = retrieve_analogs(query(), persist_log=False, today="2026-08-07")
        assert out["returned"] == 0
        assert out["rejected_reasons"] == {"embedding_manifest_mismatch": 1}

    def test_a_tampered_vector_is_rejected(self, store):
        bad = record()
        bad["feature_vector"] = [1.0] * EV2.EMBED_DIM_V2   # fingerprint no longer matches
        vector_store.add_record(bad)
        out = retrieve_analogs(query(), persist_log=False, today="2026-08-07")
        assert out["returned"] == 0
        assert out["rejected_reasons"] == {"feature_vector_fingerprint_mismatch": 1}

    def test_no_cosine_is_computed_across_incompatible_spaces(self, store):
        """One space per ranking. A 47-dimension legacy record and a
        55-dimension descriptive record must never appear in the same list --
        cosine between them would return a number rather than fail."""
        vector_store.add_record(record())                       # v2
        vector_store.add_record({"memory_type": "market", "instrument": "MNQ",
                                 "embedding": [1.0] * 47,       # legacy space
                                 "provenance": {"direction_source": "ai_brain",
                                                "source_validated": True}})
        out = retrieve_analogs(query(), persist_log=False, today="2026-08-07")
        assert out["vector_space"] == "v2"
        assert out["returned"] == 1
        assert out["rejected_reasons"] == {"legacy_record_in_v2_corpus": 1}
        assert out["analogs"][0]["memory_type"] == DM.MEMORY_TYPE_DESCRIPTIVE

    def test_a_legacy_only_corpus_is_read_in_the_legacy_space(self, store):
        """The older AB-3 subsystem keeps working; it is simply never mixed."""
        vector_store.add_record({"memory_type": "market", "instrument": "MNQ",
                                 "embedding": [1.0] * 47,
                                 "provenance": {"direction_source": "ai_brain",
                                                "source_validated": True}})
        out = retrieve_analogs(query(), persist_log=False, today="2026-08-07",
                               min_similarity=0.0)
        assert out["vector_space"] == "legacy"
        assert out["embedding_version"] == "legacy.47"


class TestMissingValueLaw:
    """7. Incompleteness is never a shared feature."""

    def test_7_missing_categoricals_contribute_no_shared_positive_feature(self):
        a, _ = EV2.embed_v2({"direction_distribution": {"conflicted": 1},
                             "scan_count": 1,
                             "structure_evidence": {"bos_count": 0, "mss_count": 0,
                                                    "quiet": True}})
        # Two records that share ONLY their emptiness must not resemble each
        # other. Every unknown group is zeros, so only the direction point mass
        # and the quiet flag remain -- both real statements, not absences.
        for g in EV2.MANIFEST["groups"]:
            if g["name"] in ("direction_distribution", "structure_evidence"):
                continue
            assert not any(a[g["start"]:g["end"]]), g["name"]

    def test_no_group_contains_an_unknown_or_none_category(self):
        for g in EV2.MANIFEST["groups"]:
            for cat in (g["categories"] or []):
                assert cat not in ("unknown", "none", "n/a", ""), (g["name"], cat)

    def test_unknown_values_are_reported_not_silently_zeroed(self):
        _, notes = EV2.embed_v2({"market_regime": "made_up_regime",
                                 "direction_distribution": {"conflicted": 1},
                                 "scan_count": 1,
                                 "structure_evidence": {"bos_count": 0,
                                                        "mss_count": 0,
                                                        "quiet": True}})
        assert any("market_regime:unrepresented" in n for n in notes)


class TestDelivery:
    """8-9. The block v1 could not see."""

    def test_8_actual_delivery_states_map_distinctly(self):
        w = EV2.block_weights()["delivery_state"]
        seen = {}
        for state in EV2.DELIVERY_STATES:
            vec = record(delivery_state=state)["feature_vector"]
            block = tuple(vec[EV2._GROUP["delivery_state"]["start"]:
                              EV2._GROUP["delivery_state"]["end"]])
            assert sum(block) == pytest.approx(w), state
            assert block not in seen, f"{state} collides with {seen.get(block)}"
            seen[block] = state
        assert len(seen) == len(EV2.DELIVERY_STATES)

    def test_9_delivery_never_routes_through_norm_dir(self):
        import ast
        tree = ast.parse(open("src/ai_retrieval/embedding_v2.py", encoding="utf-8").read())
        names = {n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute)}
        names |= {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)}
        assert "_norm_dir" not in names
        # and the v1 collapse must be impossible: every real state has a slot
        # v1 routed delivery through _norm_dir, which recognises DIRECTIONAL
        # tokens. The five PO3 alignment states all collapsed to "none"; the
        # directional states would have collapsed to a direction, losing the
        # alignment. v2 gives every authoritative state its own slot.
        from ai_retrieval.embedding import _norm_dir
        collapsed = {state: _norm_dir(state) for state in EV2.DELIVERY_STATES}
        assert len(set(collapsed.values())) < len(EV2.DELIVERY_STATES), (
            "the legacy normaliser must lose information the v2 block keeps")
        g = EV2._GROUP["delivery_state"]
        assert g["size"] == len(EV2.DELIVERY_STATES)

    def test_the_dead_universal_delivery_dimension_is_gone(self):
        a = record(delivery_state="accumulation_building")["feature_vector"]
        b = record(delivery_state="mixed")["feature_vector"]
        g = EV2._GROUP["delivery_state"]
        shared = [i for i in range(g["start"], g["end"]) if a[i] and b[i]]
        assert not shared, "two different delivery states share a dimension"


class TestStructure:
    """10-13. Structured features, not display strings."""

    def _witness(self, bos, mss):
        """A post-UNIT-3 witness: every proposition states its evaluability.

        The rows used to carry event booleans alone. Under UNIT 3 a witness that
        states no capability is UNKNOWN, and UNKNOWN may not claim authoritative
        quiet -- so a fixture without evaluations would be testing the vector of
        a legacy payload, not of the contract these assertions describe.
        """
        tfs = ("15m", "5m", "3m", "1m")
        ok = {"capability": "DETECTOR_EVALUATED", "reason": None}
        return {tf: {"bos_event": i < bos, "mss_event": i < mss,
                     "bos_evaluation": dict(ok), "mss_evaluation": dict(ok)}
                for i, tf in enumerate(tfs)}

    def test_10_bos_count_is_represented(self):
        g = EV2._GROUP["structure_evidence"]
        w = EV2.block_weights()["structure_evidence"]
        scale = w / (2.0 ** 0.5)
        vals = []
        for bos in range(5):
            ev = EV2.structure_evidence(self._witness(bos, 0))
            vec = record(structure_evidence=ev)["feature_vector"]
            vals.append(vec[g["start"]])
        assert vals[0] == 0.0                      # quiet -> flag, not a count
        for i, bos in enumerate((1, 2, 3, 4), start=1):
            assert vals[i] == pytest.approx(bos / 4 * scale)
        assert vals == sorted(vals)                # intensity preserved

    def test_11_mss_count_is_represented(self):
        g = EV2._GROUP["structure_evidence"]
        w = EV2.block_weights()["structure_evidence"]
        ev = EV2.structure_evidence(self._witness(0, 2))
        assert record(structure_evidence=ev)["feature_vector"][g["start"] + 1] == \
            pytest.approx(0.5 * w / (2.0 ** 0.5))

    def test_12_quiet_structure_is_represented_distinctly(self):
        g = EV2._GROUP["structure_evidence"]
        w = EV2.block_weights()["structure_evidence"]
        quiet = record(structure_evidence=EV2.structure_evidence(self._witness(0, 0)))
        active = record(structure_evidence=EV2.structure_evidence(self._witness(1, 0)))
        assert quiet["feature_vector"][g["start"] + 2] == pytest.approx(w)
        assert active["feature_vector"][g["start"] + 2] == 0.0

    def test_13_an_absent_witness_is_rejected_not_read_as_quiet(self):
        for bad in ({}, None, {"15m": "not-a-dict"}):
            with pytest.raises(EV2.EmbeddingError) as exc:
                EV2.structure_evidence(bad)
            assert "structure_witness_absent" in str(exc.value)

    def test_counts_are_capped_so_one_reading_cannot_dominate(self):
        g = EV2._GROUP["structure_evidence"]
        w = EV2.block_weights()["structure_evidence"]
        cap = w / (2.0 ** 0.5)
        vec = record(structure_evidence={"bos_count": 99, "mss_count": 99,
                                         "quiet": False})["feature_vector"]
        assert vec[g["start"]] == pytest.approx(cap)
        assert vec[g["start"] + 1] == pytest.approx(cap)

    def test_a_malformed_structure_record_is_refused(self):
        with pytest.raises(EV2.EmbeddingError):
            EV2.embed_v2({"structure_evidence": "witness_quiet",
                          "direction_distribution": {"conflicted": 1},
                          "scan_count": 1})


class TestLiquidity:
    """14. Four real configurations, not one collapsed token."""

    def test_14_liquidity_states_map_distinctly(self):
        assert EV2.liquidity_state(29800, 29200) == "two_sided_pools"
        assert EV2.liquidity_state(29800, None) == "buy_side_only"
        assert EV2.liquidity_state(None, 29200) == "sell_side_only"
        assert EV2.liquidity_state(None, None) == "no_pools"
        w = EV2.block_weights()["liquidity_state"]
        seen = set()
        for state in EV2.LIQUIDITY_STATES:
            g = EV2._GROUP["liquidity_state"]
            vec = record(liquidity_state=state)["feature_vector"]
            block = tuple(vec[g["start"]:g["end"]])
            assert sum(block) == pytest.approx(w)   # weighted, still unit-before-weight
            seen.add(block)
        assert len(seen) == 4

    def test_buy_side_only_is_not_sell_side_only(self):
        """For a directional system these are opposite situations. v1 called
        both `one_sided_pool` and embedded neither."""
        g = EV2._GROUP["liquidity_state"]
        a = record(liquidity_state="buy_side_only")["feature_vector"]
        b = record(liquidity_state="sell_side_only")["feature_vector"]
        assert a[g["start"]:g["end"]] != b[g["start"]:g["end"]]


class TestDirectionDistribution:
    """15-16. The whole distribution, not just the mode."""

    def test_15_direction_distributions_normalize_to_one(self):
        props = EV2.direction_proportions(
            {"bearish": 8, "conflicted": 8, "neutral": 6, "bullish": 2}, 24)
        assert sum(props.values()) == pytest.approx(1.0)
        assert props["bearish"] == pytest.approx(8 / 24)

    def test_16_a_mixed_segment_differs_from_a_pure_bearish_one(self):
        mixed = record(scan_count=24, dominant_direction="bearish",
                       action_distribution={"stand_down": 24},
                       direction_distribution={"bearish": 8, "conflicted": 8,
                                               "neutral": 6, "bullish": 2})
        pure = record(scan_count=24, dominant_direction="bearish",
                      action_distribution={"stand_down": 24},
                      direction_distribution={"bearish": 24})
        g = EV2._GROUP["direction_distribution"]
        assert mixed["feature_vector"][g["start"]:g["end"]] != \
            pure["feature_vector"][g["start"]:g["end"]]
        assert EV2.cosine_v2(mixed["feature_vector"], pure["feature_vector"]) < 0.999

    def test_an_incomplete_distribution_is_refused(self):
        with pytest.raises(EV2.EmbeddingError) as exc:
            EV2.direction_proportions({"bearish": 3}, 10)
        assert "incomplete" in str(exc.value)

    def test_an_unsupported_direction_token_is_refused(self):
        with pytest.raises(EV2.EmbeddingError) as exc:
            EV2.direction_proportions({"sideways": 10}, 10)
        assert "unsupported_direction_vocabulary" in str(exc.value)

    def test_every_block_contributes_equal_magnitude_from_direction(self):
        """L2 normalisation: a mixed segment must not be quieter than a pure
        one merely because it was mixed."""
        import numpy as np
        g = EV2._GROUP["direction_distribution"]
        w = EV2.block_weights()["direction_distribution"]
        for dist, n in (({"conflicted": 10}, 10),
                        ({"bearish": 8, "conflicted": 8, "neutral": 6, "bullish": 2}, 24)):
            vec = record(scan_count=n, direction_distribution=dist,
                         action_distribution={"stand_down": n})["feature_vector"]
            assert np.linalg.norm(vec[g["start"]:g["end"]]) == pytest.approx(w)


class TestConfidenceAndExhaustion:
    """17-20."""

    def test_17_18_confidence_mean_and_dispersion_are_populated(self):
        g = EV2._GROUP["confidence"]
        w = EV2.block_weights()["confidence"]
        scale = w / (2.0 ** 0.5)          # bounded internally, then weighted
        vec = record(phase_confidence_summary={"mean": 61.0, "min": 40.0,
                                               "max": 80.0})["feature_vector"]
        assert vec[g["start"]] == pytest.approx(0.61 * scale)
        assert vec[g["start"] + 1] == pytest.approx(0.40 * scale)
        assert vec[g["start"]] != 0.0, "v1 hardcoded this to zero"

    def test_19_no_invented_delivery_confidence_exists(self):
        names = {g["name"] for g in EV2.MANIFEST["groups"]}
        assert "delivery_confidence" not in names
        assert EV2._GROUP["confidence"]["size"] == 2   # mean + dispersion only

    def test_out_of_range_confidence_is_rejected_not_clipped(self):
        for bad in (140.0, -5.0):
            with pytest.raises(EV2.EmbeddingError) as exc:
                record(phase_confidence_summary={"mean": bad, "min": bad, "max": bad})
            assert "confidence_out_of_range" in str(exc.value)
            assert "not clipped" in str(exc.value)

    def test_20_no_permanently_dead_exhaustion_dimension_remains(self):
        """v1 carried an exhaustion scalar nothing ever wrote. v2 populates it
        from the INDEPENDENT `shared_market_context._exhaustion_present`."""
        g = EV2._GROUP["exhaustion"]
        w = EV2.block_weights()["exhaustion"]
        on = record(exhaustion_present=True)["feature_vector"][g["start"]:g["end"]]
        off = record(exhaustion_present=False)["feature_vector"][g["start"]:g["end"]]
        assert on == [pytest.approx(w), 0.0] and off == [0.0, pytest.approx(w)]
        assert on != off

    def test_the_exhaustion_writer_exists(self):
        from shared_context.shared_market_context import _exhaustion_present
        assert callable(_exhaustion_present)

    def test_exhaustion_is_not_a_restatement_of_narrative_phase(self):
        """They must be independently settable, or the block is redundant."""
        a = record(narrative_phase="transition", exhaustion_present=True)
        b = record(narrative_phase="exhaustion", exhaustion_present=False)
        ga, gp = EV2._GROUP["exhaustion"], EV2._GROUP["narrative_phase"]
        w = EV2.block_weights()["exhaustion"]
        assert a["feature_vector"][ga["start"]] == pytest.approx(w)
        assert b["feature_vector"][ga["start"]] == 0.0
        assert a["feature_vector"][gp["start"]:gp["end"]] != \
            b["feature_vector"][gp["start"]:gp["end"]]


class TestProtectedLevels:
    """21-23. One shape; presence only in similarity."""

    def test_21_22_protected_level_schema_is_normalised(self):
        absent, present = record(), record(
            protected_low={"level": 29493.25, "timeframe": "5m",
                           "basis": "sell_side_raid_rejected",
                           "registered_at": "2026-08-06T17:59:00+00:00"})
        for rec in (absent, present):
            for side in ("high", "low"):
                for suffix in ("level", "timeframe", "basis", "registered_at"):
                    assert f"protected_{side}_{suffix}" in rec
            # never a nested dict under the same schema field
            assert not isinstance(rec["protected_low_level"], dict)
            assert not isinstance(rec["protected_high_level"], dict)
        assert absent["protected_low_level"] is None
        assert present["protected_low_level"] == 29493.25
        assert present["protected_low_timeframe"] == "5m"

    def test_23_raw_price_does_not_drive_similarity(self):
        """Only PRESENCE enters the vector. Two different levels must produce
        the same vector, so no absolute price can leak into cosine."""
        a = record(protected_low={"level": 29493.25, "timeframe": "5m",
                                  "basis": "x", "registered_at": "t"})
        b = record(protected_low={"level": 21000.00, "timeframe": "5m",
                                  "basis": "x", "registered_at": "t"})
        assert a["feature_vector"] == b["feature_vector"]
        assert EV2.cosine_v2(a["feature_vector"], b["feature_vector"]) == \
            pytest.approx(1.0)

    def test_presence_still_separates_from_absence(self):
        g = EV2._GROUP["protected_low"]
        w = EV2.block_weights()["protected_low"]
        assert record()["feature_vector"][g["start"]] == 0.0
        assert record(protected_low={"level": 1.0, "timeframe": None,
                                     "basis": None,
                                     "registered_at": None}
                      )["feature_vector"][g["start"]] == pytest.approx(w)


@archived
@has_v2
class TestAugust6UnderV2:
    """24-25, 31-35. The acceptance behaviour the review demanded."""

    def test_24_record_5_is_distinguishable_from_4_and_6(self):
        r = v2_records()
        f4, f5, f6 = (r[3]["feature_vector_fingerprint"],
                      r[4]["feature_vector_fingerprint"],
                      r[5]["feature_vector_fingerprint"])
        assert f4 != f5 and f5 != f6 and f4 != f6
        # and it is delivery + structure + exhaustion that separate #5
        assert r[4]["delivery_state"] != r[3]["delivery_state"]
        assert r[4]["exhaustion_present"] != r[3]["exhaustion_present"]

    def test_no_two_v2_records_share_a_vector(self):
        fps = [r["feature_vector_fingerprint"] for r in v2_records()]
        assert len(set(fps)) == len(fps)

    def test_25_records_4_and_6_remain_recognisably_equivalent(self):
        r = v2_records()
        assert EV2.cosine_v2(r[3]["feature_vector"], r[5]["feature_vector"]) > 0.9

    def test_only_one_universally_on_categorical_dimension_remains(self):
        """The v1 defect was a categorical slot that NOTHING could ever move off.

        Numeric blocks (structure counts, confidence) are legitimately non-zero
        in every record -- their VALUES differ, which is what a numeric feature
        is for. The test is about categorical/two-state slots that are pinned.
        """
        recs = v2_records()
        categorical = [g for g in EV2.MANIFEST["groups"]
                       if g["kind"] in ("one_hot", "two_state")]
        pinned = []
        for g in categorical:
            for j in range(g["start"], g["end"]):
                if all(r["feature_vector"][j] for r in recs):
                    cat = (g["categories"][j - g["start"]] if g["categories"]
                           else f"{g['name']}[{j - g['start']}]")
                    pinned.append((j, g["name"], cat))
        assert len(pinned) == 1, pinned
        assert pinned[0][1] == "liquidity_state"
        assert pinned[0][2] == "two_sided_pools"
        # and unlike v1's dead block, the alternatives are reachable: three
        # other liquidity slots exist and August 6 itself produced buy_side_only
        # at scan level.
        assert EV2._GROUP["liquidity_state"]["size"] == 4

    def test_numeric_blocks_carry_varying_values_not_a_constant(self):
        recs = v2_records()
        for name in ("confidence", "structure_evidence"):
            g = EV2._GROUP[name]
            values = {tuple(round(v, 6) for v in r["feature_vector"][g["start"]:g["end"]])
                      for r in recs}
            assert len(values) > 1, name

    def test_every_v2_record_validates(self):
        """Everything except the CURRENT-contract marker, which they predate.

        STEP 4B.12 §4 UNIT 3 — `validate_descriptive_record` answers "may this
        record be AUTHORED under the contract in force now". These proposals
        were authored under structure parser v1; the contract in force is v2,
        which refuses to call an unevaluable read quiet. So the honest answer is
        no, and that refusal is the write-side gate working.

        Whether they may be READ is a different contract, owned by
        `retrieval.vector_compatibility`, and it is asserted here too so this
        test cannot be satisfied by a corpus that has quietly gone dark.
        """
        from ai_retrieval import embedding_v2 as EV2M
        from ai_retrieval import retrieval as R
        legacy_fp = EV2M.legacy_manifest_fingerprint("structure_witness_v1")
        for rec in v2_records():
            ok, reasons = DM.validate_descriptive_record(rec)
            assert reasons == ["embedding_manifest_fingerprint_mismatch"], \
                (rec["memory_id"], reasons)
            assert ok is False
            assert rec["embedding_manifest_fingerprint"] == legacy_fp
            assert R.vector_compatibility(rec)["compatible"] is True

    def test_48_v2_generation_is_deterministic(self):
        a = MA.build_records(ARCHIVE, now_iso="2026-08-06T20:00:00+00:00")
        b = MA.build_records(ARCHIVE, now_iso="2026-08-06T20:00:00+00:00")
        assert [r["feature_vector_fingerprint"] for r in a["records"]] == \
               [r["feature_vector_fingerprint"] for r in b["records"]]
        assert [r["memory_id"] for r in a["records"]] == \
               [r["memory_id"] for r in b["records"]]

    def test_the_equal_weight_v2_proposals_are_untouched(self):
        """v2.1 wrote to its OWN directory; the equal-weight evidence stands."""
        if not os.path.isdir(V2_EQUAL_DIR):
            pytest.skip("equal-weight v2 proposals absent")
        import glob
        sample = json.load(open(sorted(glob.glob(
            os.path.join(V2_EQUAL_DIR, "mem_*.json")))[0], encoding="utf-8"))
        assert sample["embedding_version"] == "descriptive.embedding.v2"
        assert sample["embedding_manifest_fingerprint"] == "emb:0110829ec9b77839"

    def test_47_the_v1_proposal_evidence_is_untouched(self):
        if not os.path.isdir(V1_DIR):
            pytest.skip("v1 proposals absent")
        import glob
        v1 = glob.glob(os.path.join(V1_DIR, "mem_*.json"))
        assert v1, "v1 evidence was deleted"
        sample = json.load(open(sorted(v1)[0], encoding="utf-8"))
        assert sample["feature_dimensions"] == 47      # still the v1 space
        assert "embedding_version" not in sample


class TestRecurrenceAndDiversity:
    """26-29. One session may not speak five times."""

    def test_26_27_same_session_exact_recurrence_uses_one_slot(self, store):
        a = record(segment_start="11:00:00", segment_end="11:10:00",
                   source_artifact_digest="d1")
        b = record(segment_start="12:00:00", segment_end="12:20:00",
                   source_artifact_digest="d2")
        assert a["feature_vector_fingerprint"] == b["feature_vector_fingerprint"]
        vector_store.add_records([a, b])
        out = retrieve_analogs(query(), persist_log=False, today="2026-08-07")
        assert out["returned"] == 1
        analog = out["analogs"][0]
        assert analog["recurrence_count"] == 2
        assert analog["occurrence_spans"] == ["11:00:00-11:10:00",
                                              "12:00:00-12:20:00"]
        assert len(analog["grouped_memory_ids"]) == 2
        assert out["recurrence_groups_collapsed"][0]["count"] == 2

    def test_the_representative_is_deterministic_and_not_confidence_ranked(self):
        short = record(segment_start="11:00:00", segment_end="11:05:00",
                       scan_count=5, direction_distribution={"conflicted": 5},
                       action_distribution={"stand_down": 5},
                       phase_confidence_summary={"mean": 99.0, "min": 99.0,
                                                 "max": 99.0},
                       source_artifact_digest="d1")
        long = record(segment_start="12:00:00", segment_end="12:30:00",
                      scan_count=20, direction_distribution={"conflicted": 20},
                      action_distribution={"stand_down": 20},
                      phase_confidence_summary={"mean": 20.0, "min": 20.0,
                                                "max": 20.0},
                      source_artifact_digest="d2")
        # Same semantic state; they differ only in confidence (diagnostic) and
        # scan count. Representative selection runs on a CONFIDENCE-FREE
        # projection, so the two tie on representative similarity and scan
        # count decides -- the 99-confidence occurrence does NOT win.
        collapsed, groups = collapse_recurrence([(0.9, short), (0.9, long)],
                                                short["feature_vector"])
        assert len(collapsed) == 1
        assert collapsed[0][1]["scan_count"] == 20

    def test_28_different_sessions_stay_independent(self, store):
        a = record(session_id="PROD-A", session_date="2026-08-04",
                   source_artifact_digest="d1")
        b = record(session_id="PROD-B", session_date="2026-08-05",
                   source_artifact_digest="d2")
        assert a["feature_vector_fingerprint"] == b["feature_vector_fingerprint"]
        vector_store.add_records([a, b])
        out = retrieve_analogs(query(), persist_log=False, today="2026-08-07")
        assert out["returned"] == 2
        assert not out["recurrence_groups_collapsed"]

    def test_29_the_per_session_cap_is_enforced(self, store):
        assert RC.MAX_ANALOGS_PER_SOURCE_SESSION == 2
        # SEMANTICALLY distinct states -- differing only in confidence would now
        # form one recurrence group rather than five capped records.
        phases = ("transition", "accumulation", "distribution", "reversal",
                  "continuation")
        for i, phase in enumerate(phases):
            vector_store.add_record(record(
                segment_start=f"1{i}:00:00", segment_end=f"1{i}:20:00",
                source_artifact_digest=f"d{i}", narrative_phase=phase))
        out = retrieve_analogs(query(), persist_log=False, today="2026-08-07",
                               min_similarity=0.0)
        assert out["returned"] == 2
        assert len(out["per_session_cap_exclusions"]) == 3

    def test_the_cap_is_part_of_the_bound_contract(self):
        assert "max_analogs_per_source_session" in RC.retrieval_policy()


class TestDeterministicRanking:
    """30. No dependence on write order."""

    def test_30_ranking_does_not_depend_on_jsonl_append_order(self, tmp_path,
                                                              monkeypatch):
        recs = [record(session_id=f"S{i}", session_date=f"2026-08-0{i+1}",
                       source_artifact_digest=f"d{i}") for i in range(4)]
        seen = []
        for order in (recs, list(reversed(recs))):
            monkeypatch.setenv("AI_RETRIEVAL_DIR",
                               str(tmp_path / f"r{len(seen)}"))
            vector_store.add_records(order)
            out = retrieve_analogs(query(), persist_log=False, today="2026-08-07")
            seen.append([a["memory_id"] for a in out["analogs"]])
        assert seen[0] == seen[1], "ranking still depends on append order"

    def test_the_ranking_tuple_follows_the_bound_order(self):
        assert RC.TIE_BREAK_ORDER == ("similarity_desc", "session_date_desc",
                                      "scan_count_desc", "segment_duration_desc",
                                      "memory_id_asc")
        newer = record(session_date="2026-08-06")
        older = record(session_date="2026-08-01")
        assert ranking_tuple(0.9, newer) < ranking_tuple(0.9, older)

    def test_segment_duration_is_computed_from_the_span(self):
        assert segment_duration({"segment_start": "11:00:00",
                                 "segment_end": "11:20:30"}) == 1230
        assert segment_duration({"segment_start": "x", "segment_end": "y"}) == 0

    def test_the_resolved_ranking_tuple_is_reported(self, store):
        vector_store.add_record(record())
        out = retrieve_analogs(query(), persist_log=False, today="2026-08-07")
        assert out["tie_break_order"] == list(RC.TIE_BREAK_ORDER)
        assert len(out["analogs"][0]["ranking_tuple"]) == 5


@archived
@has_v2
class TestQueryBehaviourUnderV2:
    """31-35. Results follow from the evidence, not from tuning."""

    def _load(self, tmp_path, monkeypatch):
        monkeypatch.setenv("AI_RETRIEVAL_DIR", str(tmp_path / "sim"))
        vector_store.add_records(v2_records())

    def _q(self, session, regime, vol, ndir, nphase, delivery, bos=1,
           draw="29500", conf=70.0, exh=False, contract="CON.F.US.MNQ.U26"):
        return {"session": session, "contract": contract,
                "market_regime": {"regime_label": regime, "volatility_state": vol},
                "narrative_authority": {"narrative_direction": ndir,
                                        "narrative_phase": nphase,
                                        "active_liquidity_draw": draw},
                "shared_context": {"delivery_state": delivery,
                                   "exhaustion_present": exh},
                "protected_swings": {},
                "liquidity": {"nearest_buy_side": 29800.0,
                              "nearest_sell_side": 29200.0},
                "STRUCTURE_WITNESS": {tf: {"bos_event": i < bos, "mss_event": False}
                                      for i, tf in enumerate(("15m", "5m", "3m", "1m"))},
                "phase_confidence_summary": {"mean": conf, "min": conf, "max": conf}}

    def test_32_no_bullish_expansion_analog_exists_in_the_corpus(self, tmp_path,
                                                                 monkeypatch):
        """August 6 contained no bullish expansion, and nothing claims it did.

        NOTE, stated rather than tuned away: v2 can return a PARTIAL-state
        analog for this query (~0.59) because the query and the 09:30 segment
        genuinely share seven features -- ny_open, full_distribution_alignment
        delivery, BOS=2, two-sided pools, active draw, no exhaustion, similar
        confidence. That is real evidence, not the v1 artifact: v1 returned
        nothing here only because it was blind to every one of those features.
        What must never happen is a returned analog PRETENDING to be a bullish
        expansion, so that is what is asserted.
        """
        self._load(tmp_path, monkeypatch)
        out = retrieve_analogs(self._q("ny_open", "expansion_up", "stable",
                                       "bullish", "continuation",
                                       "full_distribution_alignment", bos=2),
                               persist_log=False, today="2026-08-07",
                               min_similarity=0.0)
        for a in out["analogs"]:
            assert a["market_regime"] != "expansion_up"
            assert a["dominant_direction"] != "bullish"
            assert a["authority"] == "CONTEXT_ONLY"
        # no record in the corpus claims the queried state at all
        assert not [r for r in v2_records()
                    if r["market_regime"] == "expansion_up"
                    or r["dominant_direction"] == "bullish"]

    def test_the_bullish_expansion_query_is_fully_gated(self, tmp_path,
                                                        monkeypatch):
        """v2 returned this at 0.465-0.587 depending on how much of the state
        the query stated. v2.1 removes it by RULE, not by score: every record
        contradicts the query on regime, volatility and direction at once."""
        self._load(tmp_path, monkeypatch)
        q = self._q("ny_open", "expansion_up", "stable", "bullish",
                    "continuation", "full_distribution_alignment", bos=2,
                    conf=80.0)
        out = retrieve_analogs(q, persist_log=False, today="2026-08-07",
                               min_similarity=0.0)
        assert out["returned"] == 0
        assert out["rejected_reasons"]["load_bearing_contradiction"] == 10
        qv, _ = query_vector(q)
        for rec in v2_records():
            c = EV2.contradiction_report(qv, rec["feature_vector"])
            assert c["excluded"]
            assert "market_regime" in c["blocks"]
            assert "direction_distribution" in c["blocks"]

    def test_34_the_false_volatility_expansion_match_is_gone(self, tmp_path,
                                                             monkeypatch):
        """v1 returned this at 0.5345, of which a dead dimension supplied enough
        to clear the floor. v2 dropped it to 0.4273 on score. v2.1 removes it on
        semantics: every record contradicts regime, volatility and delivery."""
        self._load(tmp_path, monkeypatch)
        q = self._q("afternoon", "high_volatility", "explosive", "bearish",
                    "distribution", "manipulation_to_distribution", bos=3)
        out = retrieve_analogs(q, persist_log=False, today="2026-08-07",
                               min_similarity=0.0)
        assert out["returned"] == 0
        assert out["rejected_reasons"]["load_bearing_contradiction"] == 10

    def test_31_35_the_exact_state_query_ranks_the_right_segment_first(
            self, tmp_path, monkeypatch):
        self._load(tmp_path, monkeypatch)
        out = retrieve_analogs(self._q("morning_continuation", "range_rotation",
                                       "toxic", "conflicted", "exhaustion",
                                       "accumulation_building", bos=1, conf=85.0,
                                       exh=True),
                               persist_log=False, today="2026-08-07")
        assert out["returned"] >= 1
        assert out["analogs"][0]["segment"].startswith("11:05:02")
        assert out["analogs"][0]["similarity"] > 0.9

    def test_conflicted_rotation_no_longer_takes_three_slots(self, tmp_path,
                                                             monkeypatch):
        """The v1 failure: three indistinguishable lunch segments at 1.0000."""
        self._load(tmp_path, monkeypatch)
        out = retrieve_analogs(self._q("lunch", "range_rotation", "toxic",
                                       "conflicted", "transition",
                                       "accumulation_building", conf=65.0,
                                       exh=True),
                               persist_log=False, today="2026-08-07")
        assert out["returned"] == 2
        assert len({a["similarity"] for a in out["analogs"]}) == 2
        assert out["per_session_cap_exclusions"]

    def test_36_expired_records_do_not_retrieve(self, tmp_path, monkeypatch):
        self._load(tmp_path, monkeypatch)
        out = retrieve_analogs(self._q("lunch", "range_rotation", "toxic",
                                       "conflicted", "transition",
                                       "accumulation_building"),
                               persist_log=False, today="2026-12-31")
        assert out["returned"] == 0
        assert out["rejected_reasons"] == {"expired": 10}
        assert vector_store.count() == 10

    def test_39_cross_contract_levels_are_withheld(self, tmp_path, monkeypatch):
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
            assert "protected_low" not in a and "protected_high" not in a
            assert a["market_regime"]        # categorical features survive

    def test_40_every_analog_remains_context_only(self, tmp_path, monkeypatch):
        self._load(tmp_path, monkeypatch)
        for nphase in ("transition", "exhaustion", "accumulation"):
            out = retrieve_analogs(self._q("lunch", "range_rotation", "toxic",
                                           "conflicted", nphase,
                                           "accumulation_building"),
                                   persist_log=False, today="2026-08-07",
                                   min_similarity=0.0)
            for a in out["analogs"]:
                assert a["authority"] == "CONTEXT_ONLY"
                assert a["outcome_validated"] is False
                assert a["recommendation_authority"] == "none"
                assert a["execution_authority"] == "none"


class TestIdentityStillHolds:
    """37-38. Unchanged by the vector refit."""

    def test_37_foreign_instruments_do_not_retrieve(self, store):
        vector_store.add_record({**record(), "instrument": "QQQ"})
        out = retrieve_analogs(query(), persist_log=False, today="2026-08-07")
        assert out["returned"] == 0
        assert out["rejected_reasons"] == {"retired_instrument:qqq": 1}

    def test_38_identity_less_records_do_not_retrieve(self, store):
        naked = {k: v for k, v in record().items()
                 if k not in ("instrument", "provenance")}
        vector_store.add_record(naked)
        out = retrieve_analogs(query(), persist_log=False, today="2026-08-07")
        assert out["returned"] == 0
        assert out["rejected_reasons"] == {"missing_instrument_identity": 1}


class TestCandidateBoundaryUnchanged:
    """41-45. The load-bearing set, re-proven against the v2 view."""

    def _produce(self, parsed, brain_input, snapshot):
        # STEP 7: these assert that a retrieved analog cannot supply a
        # missing invalidation/objective. The selected tool must exist
        # first, or the producer declines on the tool instead and the
        # test would pass for the wrong reason.
        snapshot = {**(snapshot or {}), **_detected("ifvg", "fvg")}
        return CandidateProducer(allow_prose_objective_fallback=True,
                                      account_fingerprint="acct:test", contract=MNQ).produce(
            brain_result={"ok": True, "parsed": parsed, "fallback_reason": None,
                          "model": PRODUCTION_MODEL},
            brain_input=brain_input, snapshot=snapshot,
            qualification={"qualified": True},
            engine_inventory={"liquidity": "PRESENT_AND_POPULATED"},
            snapshot_id="s1", market_data_timestamp="2026-08-06T16:19:00+00:00",
            latest_closed_bar_timestamp="2026-08-06T16:19:00+00:00",
            now=datetime(2026, 8, 6, 16, 20, tzinfo=timezone.utc))

    def _snapshot(self):
        rec = record(dominant_direction="bearish",
                     direction_distribution={"bearish": 10},
                     protected_high={"level": 29500.0, "timeframe": "5m",
                                     "basis": "x", "registered_at": "t"},
                     protected_low={"level": 29478.5, "timeframe": "5m",
                                    "basis": "x", "registered_at": "t"})
        return {"ai_retrieval": {"enabled": True, "authority": "observe_only",
                                 "retrieval_authority": RC.AUTHORITY_LABEL,
                                 "analogs": [{"similarity": 1.0, **rec}]}}

    def test_41_an_analog_alone_cannot_produce_a_candidate(self):
        with pytest.raises(NoCandidate):
            self._produce({}, {"market": _priced({"current_price": 29483.0})},
                          self._snapshot())

    def test_42_an_analog_cannot_supply_a_missing_invalidation(self):
        parsed = {"narrative_direction": "bearish", "allowed_direction": "bearish",
                  "current_action": "enter on retest of 29500",
                  "recommended_playbook_family": "trend_continuation",
                  "recommended_tool_family": ["fvg"], "invalidation_level": None,
                  "active_draw": "Sell-side liquidity at 29241.0"}
        with pytest.raises(NoCandidate) as exc:
            self._produce(parsed, {"market": _priced({"current_price": 29483.0}),
                                   "liquidity": {"nearest_sell_side": 29241.0},
                                   "protected_swings": {}}, self._snapshot())
        assert "invalidation" in exc.value.reason

    def test_43_an_analog_cannot_supply_a_liquidity_objective(self):
        parsed = {"narrative_direction": "bearish", "allowed_direction": "bearish",
                  "current_action": "enter on retest of 29500",
                  "recommended_playbook_family": "trend_continuation",
                  "recommended_tool_family": ["fvg"], "invalidation_level": 29500.0,
                  "active_draw": None}
        with pytest.raises(NoCandidate) as exc:
            self._produce(parsed, {"market": _priced({"current_price": 29483.0}),
                                   "liquidity": {},
                                   "protected_swings": {"protected_high": {
                                       "level": 29500.0,
                                       "timestamp": "2026-08-06T15:10:00+00:00"}}},
                          self._snapshot())
        assert "objective" in exc.value.reason

    def test_44_45_no_risk_or_sizing_field_exists_to_read(self):
        from ai_retrieval.retrieval import _descriptive_view
        rec = record()
        view = _descriptive_view(rec, 1.0, "CON.F.US.MNQ.U26")
        for field in ("risk_usd", "max_risk", "contracts", "size", "quantity",
                      "reward_to_risk", "min_r", "stop_points", "leverage"):
            assert field not in rec, field
            assert field not in view, field


class TestContractBindingAndHygiene:
    """46, 49-52."""

    @archived
    def test_46_a_dry_run_leaves_the_live_corpus_unchanged(self, tmp_path):
        """Byte-identical, whatever the corpus already holds."""
        live = os.path.join("data", "ai_retrieval", "memory_store.jsonl")
        before = open(live, "rb").read() if os.path.exists(live) else b""
        built = MA.build_records(ARCHIVE)
        MA.write_proposed(built["records"], str(tmp_path / "proposed"))
        after = open(live, "rb").read() if os.path.exists(live) else b""
        assert after == before

    def test_49_the_brain_contract_changes_when_the_manifest_changes(self):
        before = brain_contract_fingerprint()
        original = EV2.MANIFEST["dimensions"]
        try:
            EV2.MANIFEST["dimensions"] = original + 1
            assert brain_contract_fingerprint() != before
        finally:
            EV2.MANIFEST["dimensions"] = original
        assert brain_contract_fingerprint() == before

    def test_50_the_brain_contract_changes_when_diversity_policy_changes(self):
        before = brain_contract_fingerprint()
        original = RC.MAX_ANALOGS_PER_SOURCE_SESSION
        try:
            RC.MAX_ANALOGS_PER_SOURCE_SESSION = 4
            assert brain_contract_fingerprint() != before
        finally:
            RC.MAX_ANALOGS_PER_SOURCE_SESSION = original
        assert brain_contract_fingerprint() == before

    def test_the_contract_binds_every_v2_policy_field(self):
        policy = RC.retrieval_policy()
        for key in ("embedding_version", "embedding_dimensions",
                    "embedding_manifest_fingerprint", "normalization_law",
                    "missing_value_law", "min_similarity", "max_analogs",
                    "max_analogs_per_source_session", "max_age_days",
                    "authority_label", "withhold_levels_across_contracts",
                    "recurrence_collapse_same_session", "tie_break_order"):
            assert key in policy, key

    def test_51_these_tests_use_an_isolated_store(self, store):
        vector_store.add_record(record())
        assert "data" + os.sep + "ai_retrieval" not in vector_store._store_path()

    def test_52_the_suite_never_writes_to_the_live_memory_store(self):
        """The live corpus was empty until PROD-20260806 was authored on
        2026-08-06. Emptiness was never the invariant -- ISOLATION was. What
        must hold forever is that the suite writes to a redirected root and
        leaves the live store byte-identical (also enforced globally by the
        conftest mutation guard)."""
        assert "data" + os.sep + "ai_retrieval" not in vector_store._store_path()
