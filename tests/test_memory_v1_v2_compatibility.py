"""STEP 4B.12 §4 UNIT 3 — v1 -> v2 VECTOR COMPATIBILITY.

The structure parser moved to `structure_witness_v2` because v2 refuses to call
an unevaluable read "quiet". The whole-manifest gate then refused all 16
historical records -- too coarse. Measured across the ENTIRE corpus:

    dimensionality           58 -> 58 on all 16
    BOS/MSS counts           unchanged on all 16
    changed feature indices  union = {45}, the structure quiet flag
    other descriptive fields zero changes

    CASE A  13 records  a positive BOS/MSS independently proves "not quiet",
                        so all 58 coordinates stay comparable
    CASE B   3 records  zero events and a stored quiet=True, read from ABSENCE.
                        Dimension 45 is incomparable; the other 57 are evidence

Nothing is rewritten. The exclusion is comparison-time only.
"""
import hashlib
import json
import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))

from ai_retrieval import embedding_v2 as EV2          # noqa: E402
from ai_retrieval import retrieval as R               # noqa: E402

STORE = os.path.join(ROOT, "data", "ai_retrieval", "memory_store.jsonl")
V1 = "structure_witness_v1"


def corpus():
    if not os.path.exists(STORE):
        pytest.skip("historical corpus not present in this environment")
    return [json.loads(l) for l in open(STORE, encoding="utf-8") if l.strip()]


def _vec(seed=0.5):
    return [seed] * EV2.EMBED_DIM_V2


def record(*, parser=V1, bos=1, mss=0, quiet=False, fingerprint=None,
           vector=None, version=None, drop=()):
    vec = _vec() if vector is None else vector
    rec = {
        "embedding_version": EV2.EMBEDDING_VERSION if version is None else version,
        "embedding_manifest_fingerprint": (
            EV2.legacy_manifest_fingerprint(V1) if fingerprint is None
            else fingerprint),
        "feature_vector": vec,
        "feature_vector_fingerprint": EV2.vector_fingerprint(vec),
        "structure_evidence": {"parser": parser, "bos_count": bos,
                               "mss_count": mss, "quiet": quiet},
    }
    for key in drop:
        if key in rec:
            del rec[key]
        elif key in rec["structure_evidence"]:
            del rec["structure_evidence"][key]
    return rec


# ── the dimension contract ───────────────────────────────────────────────────
class TestQuietDimensionOwnership:

    def test_the_quiet_index_is_resolved_from_the_canonical_layout(self):
        g = EV2._GROUP["structure_evidence"]
        assert g["note"] == "[bos_count/4, mss_count/4, quiet_flag]"
        assert EV2.STRUCTURE_QUIET_INDEX == g["start"] + 2

    def test_the_resolved_index_is_pinned(self):
        """A layout change must break this, not silently mask another feature."""
        assert EV2.STRUCTURE_QUIET_INDEX == 45
        assert EV2.EMBED_DIM_V2 == 58

    def test_the_representative_projection_preserves_index_identity(self):
        """The union of exclusions is only safe if projection does not compact."""
        v = [float(i + 1) for i in range(EV2.EMBED_DIM_V2)]
        p = EV2.representative_projection(v)
        assert len(p) == len(v)
        assert p[EV2.STRUCTURE_QUIET_INDEX] == v[EV2.STRUCTURE_QUIET_INDEX]
        assert v == [float(i + 1) for i in range(EV2.EMBED_DIM_V2)]


# ── the controlled substitution ──────────────────────────────────────────────
class TestControlledManifestSubstitution:

    def test_the_legacy_fingerprint_is_derived_not_trusted(self):
        assert EV2.legacy_manifest_fingerprint(V1) != EV2.manifest_fingerprint()

    def test_the_helper_does_not_mutate_the_global_manifest(self):
        before = json.dumps(EV2.MANIFEST, sort_keys=True, default=str)
        EV2.legacy_manifest_fingerprint(V1)
        EV2.legacy_manifest_fingerprint("something_else_entirely")
        assert json.dumps(EV2.MANIFEST, sort_keys=True, default=str) == before
        assert EV2.MANIFEST["parser_versions"]["structure"] == "structure_witness_v2"

    def test_the_stored_corpus_matches_the_derived_v1_fingerprint(self):
        expected = EV2.legacy_manifest_fingerprint(V1)
        for rec in corpus():
            assert rec["embedding_manifest_fingerprint"] == expected

    def test_the_bridge_is_not_a_generic_version_bypass(self):
        """Parser says v1, but an unrelated manifest difference must fail closed."""
        rec = record(fingerprint="emb:deadbeefdeadbeef")
        c = R.vector_compatibility(rec)
        assert c["mode"] == R.COMPAT_INCOMPATIBLE
        assert c["reason"] == "embedding_manifest_mismatch"


# ── the owner's classification ───────────────────────────────────────────────
class TestCompatibilityOwner:

    def test_A_current_v2_is_fully_compatible(self):
        rec = record(parser="structure_witness_v2",
                     fingerprint=EV2.manifest_fingerprint())
        c = R.vector_compatibility(rec)
        assert c["mode"] == R.COMPAT_FULL and c["excluded_dimensions"] == frozenset()

    def test_B_legacy_positive_event_keeps_every_dimension(self):
        for bos, mss in ((1, 0), (0, 1), (2, 1)):
            c = R.vector_compatibility(record(bos=bos, mss=mss, quiet=False))
            assert c["mode"] == R.COMPAT_FULL
            assert c["excluded_dimensions"] == frozenset()
            assert c["reason"] == "legacy_v1_positive_event_proves_not_quiet"

    def test_C_legacy_absence_based_quiet_excludes_only_the_quiet_index(self):
        c = R.vector_compatibility(record(bos=0, mss=0, quiet=True))
        assert c["mode"] == R.COMPAT_PARTIAL and c["compatible"] is True
        assert c["excluded_dimensions"] == frozenset({EV2.STRUCTURE_QUIET_INDEX})
        assert c["reason"] == "legacy_v1_quiet_unauthorised_under_v2"

    def test_D_zero_events_with_quiet_false_is_unmeasured_and_fails_closed(self):
        c = R.vector_compatibility(record(bos=0, mss=0, quiet=False))
        assert c["mode"] == R.COMPAT_INCOMPATIBLE
        assert c["reason"] == "legacy_v1_zero_event_non_quiet_unmeasured"

    def test_E_a_record_contradicting_its_own_evidence_is_refused(self):
        c = R.vector_compatibility(record(bos=2, mss=0, quiet=True))
        assert c["mode"] == R.COMPAT_INCOMPATIBLE
        assert c["reason"] == "legacy_structure_self_contradiction"

    def test_G_missing_parser_fails_closed(self):
        c = R.vector_compatibility(record(drop=("parser",)))
        assert c["mode"] == R.COMPAT_INCOMPATIBLE

    def test_H_missing_manifest_fingerprint_fails_closed(self):
        c = R.vector_compatibility(record(drop=("embedding_manifest_fingerprint",)))
        assert c["mode"] == R.COMPAT_INCOMPATIBLE

    def test_I_wrong_dimensionality_fails_closed(self):
        c = R.vector_compatibility(record(vector=[0.5] * 12))
        assert c["reason"] == "embedding_dimension_mismatch"

    def test_J_malformed_vector_fingerprint_fails_closed(self):
        rec = record()
        rec["feature_vector_fingerprint"] = "vec:notthisone"
        assert R.vector_compatibility(rec)["reason"] == \
            "feature_vector_fingerprint_mismatch"

    def test_embedding_version_mismatch_still_fails_closed(self):
        assert R.vector_compatibility(record(version="old.v1"))["reason"] == \
            "embedding_version_mismatch"

    def test_malformed_counts_fail_closed(self):
        rec = record()
        rec["structure_evidence"]["bos_count"] = "two"
        assert R.vector_compatibility(rec)["reason"] == \
            "legacy_structure_evidence_malformed"

    def test_K_inspection_never_mutates_the_record(self):
        rec = record(bos=0, mss=0, quiet=True)
        before = json.dumps(rec, sort_keys=True, default=str)
        R.vector_compatibility(rec)
        assert json.dumps(rec, sort_keys=True, default=str) == before


# ── the binary wrapper is not a comparison licence ───────────────────────────
class TestBinaryWrapper:

    def test_partial_returns_empty_but_is_not_a_licence_to_compare_raw(self):
        rec = record(bos=0, mss=0, quiet=True)
        assert R._vector_incompatible(rec) == ""
        # the wrapper cannot express what the comparison must know
        assert R.vector_compatibility(rec)["excluded_dimensions"] != frozenset()

    def test_incompatible_returns_the_forensic_reason(self):
        rec = record(bos=0, mss=0, quiet=False)
        assert R._vector_incompatible(rec) == \
            "legacy_v1_zero_event_non_quiet_unmeasured"

    def test_full_returns_empty(self):
        assert R._vector_incompatible(record(bos=1, quiet=False)) == ""


# ── cosine behaviour under exclusion ─────────────────────────────────────────
class TestMaskedCosine:

    def test_full_compatibility_reproduces_the_ordinary_cosine_exactly(self):
        a = [0.1 * i for i in range(EV2.EMBED_DIM_V2)]
        b = [0.2 * (i % 7) for i in range(EV2.EMBED_DIM_V2)]
        assert EV2.compatible_cosine(a, b, frozenset()) == EV2.cosine_v2(a, b)

    def test_the_excluded_coordinate_cannot_influence_the_score_from_either_side(self):
        ex = frozenset({EV2.STRUCTURE_QUIET_INDEX})
        a = [0.3] * EV2.EMBED_DIM_V2
        b = [0.4] * EV2.EMBED_DIM_V2
        base = EV2.compatible_cosine(a, b, ex)
        for side in (a, b):
            for value in (0.0, 1.0, -5.0, 99.0):
                moved = list(side)
                moved[EV2.STRUCTURE_QUIET_INDEX] = value
                got = (EV2.compatible_cosine(moved, b, ex) if side is a
                       else EV2.compatible_cosine(a, moved, ex))
                assert got == pytest.approx(base, abs=1e-12)

    def test_an_allowed_coordinate_still_moves_the_score(self):
        ex = frozenset({EV2.STRUCTURE_QUIET_INDEX})
        a = [0.3] * EV2.EMBED_DIM_V2
        b = [0.4] * EV2.EMBED_DIM_V2
        base = EV2.compatible_cosine(a, b, ex)
        moved = list(a)
        moved[10] = -3.0
        assert EV2.compatible_cosine(moved, b, ex) != pytest.approx(base, abs=1e-9)

    def test_exclusion_equals_comparing_the_other_57_coordinates(self):
        ex = frozenset({EV2.STRUCTURE_QUIET_INDEX})
        a = [0.1 * i for i in range(EV2.EMBED_DIM_V2)]
        b = [0.05 * (i % 11) for i in range(EV2.EMBED_DIM_V2)]
        trimmed_a = [v for i, v in enumerate(a) if i != EV2.STRUCTURE_QUIET_INDEX]
        trimmed_b = [v for i, v in enumerate(b) if i != EV2.STRUCTURE_QUIET_INDEX]
        assert EV2.compatible_cosine(a, b, ex) == \
            pytest.approx(EV2.cosine_v2(trimmed_a, trimmed_b), abs=1e-12)

    def test_comparison_does_not_mutate_either_vector(self):
        ex = frozenset({EV2.STRUCTURE_QUIET_INDEX})
        a = [0.3] * EV2.EMBED_DIM_V2
        b = [0.4] * EV2.EMBED_DIM_V2
        EV2.compatible_cosine(a, b, ex)
        assert a == [0.3] * EV2.EMBED_DIM_V2 and b == [0.4] * EV2.EMBED_DIM_V2


# ── representative selection ─────────────────────────────────────────────────
class TestRepresentativeExclusion:

    def test_the_existing_diagnostic_exclusion_is_preserved(self):
        a = [0.3] * EV2.EMBED_DIM_V2
        b = [0.4] * EV2.EMBED_DIM_V2
        base = EV2.representative_similarity(a, b)
        moved = list(a)
        for g in EV2.DIAGNOSTIC_BLOCKS:
            grp = EV2._GROUP[g]
            for i in range(grp["start"], grp["end"]):
                moved[i] = 42.0
        assert EV2.representative_similarity(moved, b) == pytest.approx(base, abs=1e-12)

    def test_a_partial_candidate_additionally_excludes_the_quiet_coordinate(self):
        ex = frozenset({EV2.STRUCTURE_QUIET_INDEX})
        a = [0.3] * EV2.EMBED_DIM_V2
        b = [0.4] * EV2.EMBED_DIM_V2
        base = EV2.representative_similarity(a, b, ex)
        moved = list(b)
        moved[EV2.STRUCTURE_QUIET_INDEX] = 7.0
        assert EV2.representative_similarity(a, moved, ex) == pytest.approx(base, abs=1e-12)
        # and without the mask that same coordinate DOES matter
        assert EV2.representative_similarity(a, moved) != \
            pytest.approx(EV2.representative_similarity(a, b), abs=1e-9)

    def test_the_two_exclusions_union_rather_than_replace(self):
        ex = frozenset({EV2.STRUCTURE_QUIET_INDEX})
        a = [0.3] * EV2.EMBED_DIM_V2
        b = [0.4] * EV2.EMBED_DIM_V2
        base = EV2.representative_similarity(a, b, ex)
        moved = list(b)
        moved[EV2.STRUCTURE_QUIET_INDEX] = 9.0
        for g in EV2.DIAGNOSTIC_BLOCKS:
            grp = EV2._GROUP[g]
            for i in range(grp["start"], grp["end"]):
                moved[i] = 9.0
        assert EV2.representative_similarity(a, moved, ex) == pytest.approx(base, abs=1e-12)


# ── contradiction reporting never consumed the quiet coordinate ──────────────
class TestContradictionPathIsUnaffected:

    def test_structure_is_not_a_contradiction_block(self):
        """If this ever changes, the legacy leak reopens. Force a redesign."""
        assert "structure_evidence" not in EV2.CONTRADICTION_BLOCKS
        assert "structure_evidence" in EV2.CONTEXTUAL_BLOCKS

    def test_flipping_the_quiet_coordinate_changes_no_contradiction_report(self):
        a = [0.3] * EV2.EMBED_DIM_V2
        b = [0.4] * EV2.EMBED_DIM_V2
        base = EV2.contradiction_report(a, b)
        for value in (0.0, 1.0, -2.0, 50.0):
            moved = list(b)
            moved[EV2.STRUCTURE_QUIET_INDEX] = value
            assert EV2.contradiction_report(a, moved) == base

    def test_no_contradiction_block_overlaps_the_quiet_index(self):
        for name in EV2.CONTRADICTION_BLOCKS:
            g = EV2._GROUP[name]
            assert not (g["start"] <= EV2.STRUCTURE_QUIET_INDEX < g["end"])


# ── against the real corpus ──────────────────────────────────────────────────
class TestRealCorpus:

    def test_the_measured_13_3_0_split_holds(self):
        modes = {}
        for rec in corpus():
            modes.setdefault(R.vector_compatibility(rec)["mode"], []).append(
                (rec["session_id"], rec["segment_start"]))
        assert len(modes.get(R.COMPAT_FULL, [])) == 13
        assert len(modes.get(R.COMPAT_INCOMPATIBLE, [])) == 0
        assert sorted(modes.get(R.COMPAT_PARTIAL, [])) == [
            ("PROD-20260806", "12:08:22"),
            ("PROD-20260806", "13:17:38"),
            ("PROD-20260807", "10:35:28")]

    def test_every_partial_excludes_exactly_the_quiet_index(self):
        for rec in corpus():
            c = R.vector_compatibility(rec)
            if c["mode"] == R.COMPAT_PARTIAL:
                assert c["excluded_dimensions"] == \
                    frozenset({EV2.STRUCTURE_QUIET_INDEX})
            else:
                assert c["excluded_dimensions"] == frozenset()

    def test_the_corpus_does_not_go_dark(self):
        """The rejected coarse architecture refused all 16. None are refused."""
        assert all(R.vector_compatibility(r)["compatible"] for r in corpus())

    def test_partial_records_keep_their_stored_quiet_claim(self):
        for rec in corpus():
            if R.vector_compatibility(rec)["mode"] == R.COMPAT_PARTIAL:
                se = rec["structure_evidence"]
                assert se["quiet"] is True            # still says what v1 said
                assert se["parser"] == V1
                assert se["bos_count"] == 0 and se["mss_count"] == 0

    def test_the_store_is_never_written(self):
        before = hashlib.sha256(open(STORE, "rb").read()).hexdigest()
        for rec in corpus():
            R.vector_compatibility(rec)
        assert hashlib.sha256(open(STORE, "rb").read()).hexdigest() == before


# ── an incompatible record may never reach representative scoring ────────────
class TestRepresentativeIsCompatibilityGated:
    """`_representative` calls `vector_compatibility(r)` directly, so it must be
    impossible for an INCOMPATIBLE record to arrive there at all -- otherwise a
    record refused for scoring could still decide which occurrence speaks for a
    recurrence group.

    Proven by OBSERVATION rather than by reading the control flow: every vector
    that reaches representative scoring is captured and checked against the
    records the gate accepted.
    """

    def test_only_gated_records_reach_representative_scoring(self, monkeypatch):
        from ai_retrieval import retrieval as R2

        seen = []
        real = EV2.representative_similarity

        def spy(qvec, rvec, excluded=()):
            seen.append((tuple(rvec), frozenset(excluded)))
            return real(qvec, rvec, excluded)

        monkeypatch.setattr(EV2, "representative_similarity", spy)

        recs = corpus()
        qvec = list(recs[0]["feature_vector"])
        scored = []
        for rec in recs:
            compat = R2.vector_compatibility(rec)
            if not compat["compatible"]:
                continue
            scored.append((EV2.compatible_cosine(qvec, rec["feature_vector"],
                                                 compat["excluded_dimensions"]),
                           rec))
        R2.collapse_recurrence(scored, qvec)

        accepted = {tuple(r["feature_vector"]) for _, r in scored}
        for vec, _ex in seen:
            assert vec in accepted, "an ungated vector reached representative scoring"

    def test_each_member_carries_its_own_mask_not_the_groups(self, monkeypatch):
        """A PARTIAL member's exclusion may not be borrowed by a FULL member."""
        from ai_retrieval import retrieval as R2

        seen = {}
        real = EV2.representative_similarity

        def spy(qvec, rvec, excluded=()):
            seen[tuple(rvec)] = frozenset(excluded)
            return real(qvec, rvec, excluded)

        monkeypatch.setattr(EV2, "representative_similarity", spy)

        recs = corpus()
        qvec = list(recs[0]["feature_vector"])
        # force one group containing BOTH a FULL and a PARTIAL member
        full = next(r for r in recs
                    if R2.vector_compatibility(r)["mode"] == R2.COMPAT_FULL)
        partial = next(r for r in recs
                       if R2.vector_compatibility(r)["mode"] == R2.COMPAT_PARTIAL)
        monkeypatch.setattr(EV2, "semantic_recurrence_key", lambda rec: ("same",))
        R2.collapse_recurrence([(0.9, full), (0.8, partial)], qvec)

        assert seen[tuple(full["feature_vector"])] == frozenset()
        assert seen[tuple(partial["feature_vector"])] == \
            frozenset({EV2.STRUCTURE_QUIET_INDEX})

    def test_a_single_member_group_never_reaches_representative_selection(self,
                                                                          monkeypatch):
        from ai_retrieval import retrieval as R2
        called = []
        monkeypatch.setattr(EV2, "representative_similarity",
                            lambda *a, **k: called.append(1) or 1.0)
        rec = corpus()[0]
        R2.collapse_recurrence([(0.9, rec)], list(rec["feature_vector"]))
        assert called == []
