"""SUPPORT-OPERATOR-TERMINATED-SESSION-CLOSURE + verified authoring projection.

PROD-20260807 ended the way production sessions often will: a human stopped it.
The old law demanded four launcher files by name, so a session whose end state
was entirely knowable became unauthorable for a filing reason -- while the
alternative, inventing the four files, would have put a forged launcher exit
into the evidence chain.

Both failure modes are tested here. An operator close proves the same
invariants through a post-session attestation that never claims to be native,
never predates the session it describes, and fails closed the moment any
load-bearing invariant is unproven. The projection that reshapes sealed evidence
into the authoring layout carries a hash for every file and four permitted
operations -- there is no fifth.
"""
from __future__ import annotations

import collections
import copy
import datetime as _dt
import hashlib
import json
import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))
sys.path.insert(0, os.path.join(ROOT, "tools"))

from ai_retrieval import memory_authoring as MA          # noqa: E402
from ai_retrieval import session_closure as SC           # noqa: E402

ARCHIVE = os.path.join(ROOT, "data", "replay_sessions", "PROD-20260807")
PROJECTION = os.path.join(ROOT, "data", "replay_sessions", "_projections",
                          "PROD-20260807")
NATIVE = os.path.join(ROOT, "data", "replay_sessions", "PROD-20260806")


def _load(path):
    if not os.path.exists(path):
        pytest.skip(f"{path} not present in this checkout")
    return json.load(open(path, encoding="utf-8"))


def attestation():
    return _load(os.path.join(ARCHIVE, "closure",
                              "session_closure_attestation.json"))


def verify_projection(path, session_id):
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "_auth_tool", os.path.join(ROOT, "tools",
                                   "author_descriptive_session_memory.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.verify_projection(path, session_id)


# ══════════════════════════════════════════════════════════════════════════════
class TestClosureClasses:
    """1-6."""

    def test_1_native_launcher_closure_is_still_accepted(self):
        out = MA.check_session_closed(NATIVE)
        assert out["ok"] is True, out["reasons"]
        assert out["closure_type"] == SC.NATIVE_LAUNCHER_CLOSE

    def test_2_operator_close_uses_a_distinct_class(self):
        out = MA.check_session_closed(PROJECTION)
        assert out["ok"] is True, out["reasons"]
        assert out["closure_type"] == SC.OPERATOR_TERMINATED_CLOSE
        assert out["closure_type"] != SC.NATIVE_LAUNCHER_CLOSE

    def test_2b_closure_alone_is_not_enough_without_contract_identity(self):
        """The sealed archive proves closure but cannot prove the contract;
        only the projection carries the recovered identity."""
        out = MA.check_session_closed(ARCHIVE)
        assert out["closure_type"] == SC.OPERATOR_TERMINATED_CLOSE
        assert out["ok"] is False
        assert "contract_identity_unrecoverable" in out["reasons"]

    def test_3_an_attestation_cannot_pretend_to_be_a_native_close(self):
        forged = dict(attestation(), closure_type=SC.NATIVE_LAUNCHER_CLOSE)
        reasons = SC.validate_attestation(forged)
        assert any("cannot be attested" in r for r in reasons), reasons

    def test_3b_native_artifacts_win_when_both_exist(self, tmp_path):
        """The attestation is a fallback, never an override."""
        import shutil
        d = tmp_path / "s"
        shutil.copytree(NATIVE, d, dirs_exist_ok=True)
        os.makedirs(d / "closure", exist_ok=True)
        json.dump(attestation(), open(d / "closure" /
                                      "session_closure_attestation.json", "w",
                                      encoding="utf-8"), default=str)
        assert MA.check_session_closed(str(d))["closure_type"] == \
            SC.NATIVE_LAUNCHER_CLOSE

    def test_4_a_backdated_attestation_is_rejected(self):
        att = dict(attestation(),
                   observation_end_utc="2026-08-07T17:11:17+00:00",
                   attestation_created_at="2026-08-07T16:00:00+00:00")
        assert any("backdated" in r for r in SC.validate_attestation(att))

    def test_4b_a_future_dated_attestation_is_rejected(self):
        att = dict(attestation(),
                   attestation_created_at="2030-01-01T00:00:00+00:00")
        assert any("future" in r for r in SC.validate_attestation(att))

    def test_5_every_load_bearing_invariant_is_proven_for_august_7(self):
        verdict = SC.closure_ok(attestation())
        assert verdict["ok"] is True, verdict["reasons"]
        assert verdict["unproven"] == []
        assert set(verdict["invariants"]) == set(SC.LOAD_BEARING)
        assert all(i["status"] in (SC.PROVEN_NATIVE, SC.PROVEN_POST_SESSION)
                   for i in verdict["invariants"].values())

    @pytest.mark.parametrize("invariant", SC.LOAD_BEARING)
    def test_6_removing_any_invariant_fails_closed(self, invariant):
        att = copy.deepcopy(attestation())
        att["facts"].pop(invariant, None)
        verdict = SC.closure_ok(att)
        assert verdict["ok"] is False
        assert invariant in verdict["unproven"]
        assert verdict["verdict"] == "OPERATOR_TERMINATED_CLOSURE_INSUFFICIENT"

    def test_6b_an_unavailable_fact_is_unproven_however_confidently_asserted(self):
        att = copy.deepcopy(attestation())
        att["facts"]["final_positions_known"] = {
            "value": 0, "provenance": SC.UNAVAILABLE,
            "evidence": "we are quite sure", "source": "recollection"}
        assert "final_positions_known" in SC.closure_ok(att)["unproven"]


class TestContractIdentity:
    """7-10."""

    def test_7_recovery_requires_authoritative_session_bound_evidence(self):
        from build_memory_authoring_projection import contract_evidence
        ev = contract_evidence("PROD-20260807")
        assert ev["distinct_contracts"] == ["CON.F.US.MNQ.U26"]
        assert ev["sources"] and ev["sources"][0]["trust"] == "AUTHORITATIVE"
        assert "PROD-20260807" in ev["sources"][0]["session_binding"]

    def test_7b_an_unknown_session_recovers_nothing(self):
        from build_memory_authoring_projection import contract_evidence
        assert contract_evidence("PROD-19990101")["distinct_contracts"] == []

    def test_8_contradictory_contract_evidence_fails_closed(self, monkeypatch):
        import build_memory_authoring_projection as P
        monkeypatch.setattr(P, "contract_evidence", lambda s: {
            "sources": [{"contract": "A"}, {"contract": "B"}],
            "distinct_contracts": ["CON.F.US.MNQ.U26", "CON.F.US.MNQ.Z26"]})
        rc = P.main(["--session-id", "PROD-20260807",
                     "--archive-path", ARCHIVE,
                     "--out", os.path.join(ROOT, "build", "_never")])
        assert rc == 3, "two contracts must refuse, not pick one"

    def test_9_recovered_provenance_is_explicit_on_every_record(self):
        for rec in proposals():
            p = rec["provenance"]
            assert p["contract_identity_provenance"] == "RECOVERED_SESSION_LEVEL"
            assert p["identity_recovery_sources"]

    def test_10_per_scan_absence_is_preserved_truthfully(self):
        for rec in proposals():
            assert rec["provenance"]["per_scan_contract_original"] == "ABSENT"
        index = _load(os.path.join(PROJECTION, "scans", "scan_index.json"))
        assert index["contract_identity"]["per_scan_contract_original"] == "ABSENT"
        assert all(row["contract_original_per_scan"] is None
                   for row in index["scans"])


def proposals():
    d = os.path.join(PROJECTION, "analysis", "proposed_descriptive_memory")
    if not os.path.isdir(d):
        pytest.skip("no dry-run proposals in this checkout")
    out = []
    for name in sorted(os.listdir(d)):
        rec = json.load(open(os.path.join(d, name), encoding="utf-8"))
        if "segment_start" in rec:
            out.append(rec)
    return out


class TestPartialObservationProvenance:
    """11-14."""

    def test_11_observation_end_is_explicit(self):
        for rec in proposals():
            assert rec["provenance"]["observation_window_end_et"] == "13:11:17"
            assert rec["provenance"]["observation_window_start_et"] == "09:30:51"

    def test_12_operator_termination_is_explicit(self):
        for rec in proposals():
            p = rec["provenance"]
            assert p["termination_reason"] == "OPERATOR_REQUESTED_STOP"
            assert p["source_session_completion"] == "OPERATOR_TERMINATED"
            assert p["configured_window_completed"] is False

    def test_13_retrieval_can_see_partial_session_provenance(self):
        """The fact must survive into what a reader actually gets."""
        for rec in proposals():
            assert "source_session_completion" in rec["provenance"]
            assert rec["provenance"]["closure_type"] == \
                SC.OPERATOR_TERMINATED_CLOSE

    def test_14_partial_observation_does_not_claim_absence_of_opportunity(self):
        for rec in proposals():
            claim = rec["provenance"]["partial_observation_claim"]
            assert "NOT a claim that no opportunities existed" in claim
            # scan everything EXCEPT the disclaimer, which necessarily names
            # the very phrases it exists to forbid
            body = copy.deepcopy(rec)
            body["provenance"].pop("partial_observation_claim")
            flat = json.dumps(body).lower()
            for forbidden in ("no opportunities", "nothing to trade",
                              "no setups", "market offered nothing"):
                assert forbidden not in flat, forbidden


class TestProjection:
    """15-21."""

    def test_15_the_manifest_binds_the_sealed_archive_hash(self):
        m = _load(os.path.join(PROJECTION, "projection_manifest.json"))
        src = os.path.join(ARCHIVE, "manifest.json")
        have = hashlib.sha256(open(src, "rb").read()).hexdigest()
        assert m["source_archive_manifest_sha256"] == have
        assert m["runtime_head"] == "d167b20"
        assert m["closure_attestation_sha256"]

    def test_16_every_projected_file_hash_verifies(self):
        m = _load(os.path.join(PROJECTION, "projection_manifest.json"))
        for entry in m["files"]:
            full = os.path.join(PROJECTION,
                                entry["projected_path"].replace("/", os.sep))
            digest = hashlib.sha256(open(full, "rb").read()).hexdigest()
            assert digest == entry["projected_sha256"], entry["projected_path"]
        assert len(m["files"]) == m["file_count"]

    def test_16b_only_four_operations_exist(self):
        import build_memory_authoring_projection as P
        m = _load(os.path.join(PROJECTION, "projection_manifest.json"))
        assert set(m["operations_used"]) <= set(P.OPERATIONS)
        assert len(P.OPERATIONS) == 4

    def test_17_a_bare_directory_cannot_be_an_authoring_source(self, tmp_path):
        (tmp_path / "scans").mkdir()
        ok, why = verify_projection(str(tmp_path), "PROD-20260807")
        assert ok is False and "manifest" in why

    def test_18_a_projection_cannot_cross_sessions(self):
        ok, why = verify_projection(PROJECTION, "PROD-20260806")
        assert ok is False and "PROD-20260806" in why

    def test_19_layout_normalization_cannot_alter_market_semantics(self):
        """Projected inputs must be the archive's own bytes, re-shaped only."""
        m = _load(os.path.join(PROJECTION, "projection_manifest.json"))
        for entry in m["files"]:
            if entry["projection_operation"] != "NORMALIZE_LAYOUT_ONLY":
                continue
            src = os.path.join(ARCHIVE,
                               entry["source_archive_path"].replace("/", os.sep))
            full = json.load(open(src, encoding="utf-8"))
            got = json.load(open(os.path.join(
                PROJECTION, entry["projected_path"].replace("/", os.sep)),
                encoding="utf-8"))
            key = ("input_payload" if entry["projected_path"].startswith("scans/")
                   else "parsed_output")
            assert got == (full.get(key) or {}), entry["projected_path"]

    def test_20_official_authoring_accepts_the_verified_projection(self):
        ok, why = verify_projection(PROJECTION, "PROD-20260807")
        assert ok is True, why

    def test_21_a_tampered_projection_is_rejected(self, tmp_path):
        import shutil
        d = tmp_path / "p"
        shutil.copytree(PROJECTION, d, dirs_exist_ok=True)
        victim = d / "scans" / "scan_index.json"
        victim.write_text(victim.read_text(encoding="utf-8") + " ",
                          encoding="utf-8")
        ok, why = verify_projection(str(d), "PROD-20260807")
        assert ok is False and "altered" in why



def EV2_QUIET_INDEX():
    from ai_retrieval import embedding_v2 as EV2
    return EV2.STRUCTURE_QUIET_INDEX


class TestEndToEnd:
    """22-27."""

    def test_22_august_6_native_authoring_is_unchanged(self):
        """Content, field for field, against the live corpus."""
        built = MA.build_records(NATIVE)
        assert built["status"] == MA.DRY_RUN
        assert len(built["records"]) == 10
        live = {r["segment_start"]: r for r in (
            json.loads(l) for l in open(
                os.path.join(ROOT, "data", "ai_retrieval", "memory_store.jsonl"),
                encoding="utf-8") if l.strip())
            if r["session_id"] == "PROD-20260806"}
        fresh = {r["segment_start"]: r for r in built["records"]}
        assert set(fresh) == set(live)
        # `brain_contract_fingerprint_suffix` now carries the SOURCE contract
        # resolved from session evidence, so it matches the live store again.
        # `embedding` is a legacy-compat alias the STORE adds on write, not
        # something authoring produces.
        skip = {"memory_id", "created_at", "expires_at", "content_digest",
                "embedding"}
        # After BIND-HISTORICAL-BRAIN-CONTRACT-PROVENANCE the live records were
        # re-derived from this same archive, so provenance matches exactly --
        # including the native closure type and the honest statement that
        # August 6's Brain contract was never recorded at runtime.
        # STEP 4B.12 §4 UNIT 3 — the CURRENT authoring contract is structure
        # parser v2; the stored records are v1. A v2 rebuild of a v1 segment is
        # a different READING of the same sealed evidence wherever v1 called a
        # market quiet from absence alone, so field-for-field equality is no
        # longer universal. The delta is measured, bounded and asserted here
        # rather than skipped: 12:08:22 and 13:17:38 move, on the quiet
        # coordinate only, and nothing else in the corpus moves at all.
        CONTRACT_DELTA = {"12:08:22", "13:17:38"}
        VERSION_SCOPED = {"structure_evidence", "embedding_manifest_fingerprint",
                          "content_digest", "structure_state",
                          "feature_vector_fingerprint"}

        for start, record in fresh.items():
            for field in set(record) | set(live[start]):
                if field in skip:
                    continue
                a, b = record.get(field), live[start].get(field)
                if field in VERSION_SCOPED:
                    continue          # asserted precisely in test_22d below
                if field == "feature_vector" and start in CONTRACT_DELTA:
                    moved = [i for i, (x, y) in enumerate(zip(a, b))
                             if abs(x - y) > 1e-9]
                    assert moved == [EV2_QUIET_INDEX()], \
                        f"{start} moved coordinates other than structure quiet"
                    continue
                if field == "provenance":
                    # `authoring_contract_fingerprint` is deliberately a LIVE
                    # value: the contract in force when authoring runs. It
                    # moves whenever a contract source legitimately changes --
                    # REPAIR-PATH-RESTORATION escaped the repair template's
                    # literal JSON braces, and `brain_contract_fingerprint`
                    # hashes those sources ON PURPOSE so exactly that
                    # invalidates an authorization. The HISTORICAL contract is
                    # `source_brain_contract_fingerprint`, compared below, and
                    # that one must never drift.
                    a = {k: v for k, v in (a or {}).items()
                         if k != "authoring_contract_fingerprint"}
                    b = {k: v for k, v in (b or {}).items()
                         if k != "authoring_contract_fingerprint"}
                assert a == b, f"{start}.{field} drifted"
            provenance = record["provenance"]
            assert provenance["closure_type"] == SC.NATIVE_LAUNCHER_CLOSE
            assert provenance["contract_identity_provenance"] == "ORIGINAL_PER_SCAN"
            assert provenance["source_brain_contract_fingerprint"] == \
                live[start]["provenance"]["source_brain_contract_fingerprint"]

    def test_22d_the_v1_to_v2_reading_delta_is_exactly_the_quiet_claim(self):
        """The version-scoped fields, asserted precisely rather than skipped."""
        from ai_retrieval import embedding_v2 as EV2
        from ai_retrieval import retrieval as R
        built = {r["segment_start"]: r for r in MA.build_records(NATIVE)["records"]}
        live_recs = {r["segment_start"]: r for r in (
            json.loads(l) for l in open(
                os.path.join(ROOT, "data", "ai_retrieval", "memory_store.jsonl"),
                encoding="utf-8") if l.strip())
            if r["session_id"] == "PROD-20260806"}
        legacy_fp = EV2.legacy_manifest_fingerprint("structure_witness_v1")

        moved = set()
        for start, stored in live_recs.items():
            v1, v2 = stored["structure_evidence"], built[start]["structure_evidence"]
            # the contract MARKER moves on every record
            assert v1["parser"] == "structure_witness_v1"
            assert v2["parser"] == "structure_witness_v2"
            assert stored["embedding_manifest_fingerprint"] == legacy_fp
            # the counts never move: v2 asserts no new market activity
            assert v1["bos_count"] == v2["bos_count"]
            assert v1["mss_count"] == v2["mss_count"]
            if v1["quiet"] != v2["quiet"]:
                moved.add(start)
                assert v1["quiet"] is True and v2["quiet"] is False
                assert v1["bos_count"] == 0 and v1["mss_count"] == 0
                assert v2["structure_capability"] == "UNKNOWN"
        assert moved == {"12:08:22", "13:17:38"}

        # HISTORICAL IMMUTABILITY + narrow de-authorization
        for start, stored in live_recs.items():
            compat = R.vector_compatibility(stored)
            assert compat["compatible"] is True
            expect_partial = start in moved
            assert (compat["mode"] == R.COMPAT_PARTIAL) == expect_partial
            assert (compat["excluded_dimensions"] ==
                    frozenset({EV2.STRUCTURE_QUIET_INDEX})) == expect_partial

    def test_22e_a_v2_rebuild_may_not_overwrite_the_v1_record(self):
        """The conflict alarm is a feature. It stays armed."""
        built = MA.build_records(NATIVE)["records"]
        changed = [r for r in built if r["segment_start"] in ("12:08:22", "13:17:38")]
        assert len(changed) == 2
        with pytest.raises(MA.AuthoringRefused):
            MA.commit_records(changed, approved=False)

    def test_22c_reauthoring_binds_the_historical_brain_contract(self):
        """Was a recorded DEFECT; fixed by BIND-HISTORICAL-BRAIN-CONTRACT.

        `build_records` used to stamp the CURRENT Brain contract, so
        re-authoring a historical session relabelled it with today's. It now
        resolves from session evidence and never falls back to running code.
        """
        from ai_brain.production_model import brain_contract_fingerprint
        current = brain_contract_fingerprint()
        for record in MA.build_records(NATIVE)["records"]:
            assert record["brain_contract_fingerprint_suffix"] != current[-6:]
            provenance = record["provenance"]
            assert provenance["source_brain_contract_resolution"] ==                 "UNRECOVERABLE_FROM_EVIDENCE"
            assert provenance["source_runtime_head"] == "7253640"
            assert provenance["authoring_contract_fingerprint"] == current

    def test_22b_live_memory_ids_are_canonical(self):
        """Was a recorded DEFECT; fixed by REPAIR-V2_2-DESCRIPTIVE-MEMORY-IDENTITY.

        The v2.2 migration preserved ids derived under v2.1, so a live record
        could not reproduce its own identity and re-authoring would have
        appended ten duplicates. The ids were re-derived; the law that
        `memory_id` hashes the schema version is unchanged.
        """
        from ai_retrieval import descriptive_memory as DM
        records = [json.loads(l) for l in open(
            os.path.join(ROOT, "data", "ai_retrieval", "memory_store.jsonl"),
            encoding="utf-8") if l.strip()]
        for record in records:
            assert record["schema_version"] == "descriptive.v2.2"
            kwargs = dict(session_id=record["session_id"],
                          instrument=record["instrument"],
                          contract=record["contract"],
                          segment_start=record["segment_start"],
                          segment_end=record["segment_end"],
                          source_artifact_digest=record["source_artifact_digest"])
            assert DM.memory_id(**kwargs) == record["memory_id"]
            assert DM.memory_id(**kwargs, schema_version="descriptive.v2.1")                 != record["memory_id"]

    def test_24_embedding_geometry_is_untouched(self):
        """GEOMETRY, which is what this test is named for and owns.

        STEP 4B.12 §4 UNIT 3 separated two things this assertion had merged. The
        geometry -- version, dimensionality, and the vector each record encodes
        to -- is genuinely unchanged. The manifest FINGERPRINT moved, because
        the structure parser moved v1 -> v2 when quiet gained an evaluability
        requirement. That is a semantics change, not a geometry change, so the
        fingerprint is asserted through the controlled substitution rather than
        as a frozen literal.
        """
        from ai_retrieval import embedding_v2 as EV2
        assert EV2.EMBEDDING_VERSION == "descriptive.embedding.v2.2"
        assert EV2.EMBED_DIM_V2 == 58

        # the live contract is v2; the historical corpus is v1
        assert EV2.MANIFEST["parser_versions"]["structure"] == "structure_witness_v2"
        legacy = EV2.legacy_manifest_fingerprint("structure_witness_v1")
        assert legacy == "emb:d432f37dfdd816cd"
        assert EV2.manifest_fingerprint() != legacy

        for rec in proposals():
            assert rec["embedding_dimensions"] == 58
            assert rec["embedding_manifest_fingerprint"] == legacy
            # GEOMETRY PROOF: each record still encodes to exactly its stored
            # vector. The v1 -> v2 change did not move a single coordinate of an
            # already-authored record.
            vector, _ = EV2.embed_v2(rec)
            assert vector == rec["feature_vector"]

    def test_25_the_live_corpus_holds_both_sessions_independently(self):
        """August 7 was authored only after its closure, identity and
        partial-observation provenance were proven. The two sessions remain
        separate observations."""
        path = os.path.join(ROOT, "data", "ai_retrieval", "memory_store.jsonl")
        records = [json.loads(l) for l in open(path, encoding="utf-8")
                   if l.strip()]
        assert len(records) == 16
        by_session = collections.Counter(r["session_id"] for r in records)
        assert by_session == {"PROD-20260806": 10, "PROD-20260807": 6}
        assert len({r["memory_id"] for r in records}) == 16
        assert all(r["authority"] == "CONTEXT_ONLY" for r in records)
        assert not any(r["outcome_validated"] for r in records)

    def test_26_27_no_authorization_and_no_order_path(self):
        import ast
        for name in ("build_session_closure_attestation.py",
                     "build_memory_authoring_projection.py",
                     "author_descriptive_session_memory.py"):
            tree = ast.parse(open(os.path.join(ROOT, "tools", name),
                                  encoding="utf-8").read())
            called = {getattr(n.func, "attr", "") or getattr(n.func, "id", "")
                      for n in ast.walk(tree) if isinstance(n, ast.Call)}
            for forbidden in ("place_bracket_market_order", "place_order_raw",
                              "gated_submit", "cancel_order", "modify_order",
                              "SessionAuthorization"):
                assert forbidden not in called, f"{name}: {forbidden}"

    def test_proposals_stay_context_only_with_no_outcome_authority(self):
        for rec in proposals():
            assert rec["authority"] == "CONTEXT_ONLY"
            assert rec["outcome_validated"] is False
            assert rec["recommendation_authority"] == "none"
            assert rec["execution_authority"] == "none"
            assert rec["memory_type"] == "descriptive_observation"
