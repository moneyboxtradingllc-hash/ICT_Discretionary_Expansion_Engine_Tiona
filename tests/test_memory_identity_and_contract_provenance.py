"""REPAIR-V2_2-DESCRIPTIVE-MEMORY-IDENTITY + BIND-HISTORICAL-BRAIN-CONTRACT.

Two defects, both of which let a record assert something it could not support.

`memory_id` hashes the schema version on purpose: identical inputs must collide
so a second authoring is recognised as a repeat instead of appended as a second
copy of the same moment. The v2.1 -> v2.2 migration updated `schema_version` but
carried the old ids across, so every live record asserted an identity it could
no longer derive -- and the collision that makes re-authoring safe could not
happen.

Separately, `build_records` stamped the CURRENT Brain contract, so re-authoring
a historical session relabelled it with today's. PROD-20260806 ran
`gpt-5.6-luna` while its records claimed a Terra-era contract.

Neither is fixed by relaxing a law. The ids were re-derived to match the
doctrine, and the two collapsed meanings -- who reasoned, what represented it --
were separated so the second can never impersonate the first.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))
sys.path.insert(0, os.path.join(ROOT, "tools"))

from ai_retrieval import descriptive_memory as DM        # noqa: E402
from ai_retrieval import memory_authoring as MA          # noqa: E402
from ai_retrieval import session_brain_contract as SBC   # noqa: E402

STORE = os.path.join(ROOT, "data", "ai_retrieval", "memory_store.jsonl")
NATIVE = os.path.join(ROOT, "data", "replay_sessions", "PROD-20260806")
PROJECTION = os.path.join(ROOT, "data", "replay_sessions", "_projections",
                          "PROD-20260807")
LEDGER = os.path.join(ROOT, "data", "replay_sessions", "_migrations",
                      "descriptive.v2.2-memory-id-repair", "mapping.json")


def live(session=None):
    """The live corpus, optionally scoped to one session.

    The corpus holds two sessions since AUTHOR-PROD-20260807-DESCRIPTIVE-MEMORY.
    Assertions about August 6 re-authoring must be scoped to August 6 -- an
    unscoped comparison against a re-derivation of one archive would fail for
    the honest reason that the other session's records are not in it.
    """
    if not os.path.exists(STORE):
        pytest.skip("live corpus not present")
    records = [json.loads(l) for l in open(STORE, encoding="utf-8") if l.strip()]
    return [r for r in records if session is None or r["session_id"] == session]


def canonical(record):
    return DM.memory_id(
        session_id=record["session_id"], instrument=record["instrument"],
        contract=record["contract"], segment_start=record["segment_start"],
        segment_end=record["segment_end"],
        source_artifact_digest=record["source_artifact_digest"])


# ══════════════════════════════════════════════════════════════════════════════
class TestIdentityLaw:
    """1-3, 21, 23."""

    def test_1_every_live_record_reproduces_its_own_id(self):
        records = live()
        assert records
        for record in records:
            assert record["memory_id"] == canonical(record), \
                f"{record['segment_start']} cannot derive its own id"

    def test_2_schema_version_remains_part_of_identity(self):
        record = live()[0]
        kwargs = dict(session_id=record["session_id"],
                      instrument=record["instrument"],
                      contract=record["contract"],
                      segment_start=record["segment_start"],
                      segment_end=record["segment_end"],
                      source_artifact_digest=record["source_artifact_digest"])
        assert DM.memory_id(**kwargs, schema_version="descriptive.v2.1") \
            != DM.memory_id(**kwargs, schema_version="descriptive.v2.2"), \
            "the schema version must still change identity"

    def test_3_a_v2_1_id_can_no_longer_masquerade_as_v2_2(self):
        for record in live():
            stale = DM.memory_id(
                session_id=record["session_id"],
                instrument=record["instrument"], contract=record["contract"],
                segment_start=record["segment_start"],
                segment_end=record["segment_end"],
                source_artifact_digest=record["source_artifact_digest"],
                schema_version="descriptive.v2.1")
            assert record["memory_id"] != stale
            assert record["schema_version"] == "descriptive.v2.2"

    def test_21_23_corpus_shape_is_sound(self):
        records = live()
        assert len(records) == 16          # 10 August 6 + 6 August 7
        assert {r["embedding_version"] for r in records} == \
            {"descriptive.embedding.v2.2"}
        assert {r["embedding_dimensions"] for r in records} == {58}
        assert {r["authority"] for r in records} == {"CONTEXT_ONLY"}
        assert not any(r["outcome_validated"] for r in records)
        assert len({r["memory_id"] for r in records}) == 16

    def test_24_august_7_is_authored_and_still_carries_no_outcome(self):
        """August 7 was HELD until its provenance was proven. The hold is
        lifted, but being written to the live store grants no new authority."""
        august7 = live("PROD-20260807")
        assert len(august7) == 6
        for record in august7:
            assert record["memory_type"] == "descriptive_observation"
            assert record["authority"] == "CONTEXT_ONLY"
            assert record["outcome_validated"] is False
            assert record["recommendation_authority"] == "none"
            assert record["execution_authority"] == "none"
            assert (record["trade_count"], record["candidate_count"]) == (0, 0)


class TestMigration:
    """4-6, 9-11."""

    def ledger(self):
        if not os.path.exists(LEDGER):
            pytest.skip("migration ledger not present")
        return json.load(open(LEDGER, encoding="utf-8"))

    def test_4_9_the_ledger_maps_every_record(self):
        ledger = self.ledger()
        assert ledger["records"] == 10
        assert len(ledger["mappings"]) == 10
        assert {m["old_memory_id"] for m in ledger["mappings"]} \
            != {m["new_memory_id"] for m in ledger["mappings"]}
        assert {m["new_memory_id"] for m in ledger["mappings"]} == \
            {r["memory_id"] for r in live("PROD-20260806")}
        assert ledger["schema_version_in_identity"] is True

    def test_10_no_mapping_collisions(self):
        mappings = self.ledger()["mappings"]
        assert len({m["old_memory_id"] for m in mappings}) == 10
        assert len({m["new_memory_id"] for m in mappings}) == 10

    def test_5_6_semantics_and_vectors_survived_the_re_id(self):
        """The re-derivation from the archive must still equal the live store.

        STEP 4B.12 §4 UNIT 3 — this equality is no longer universal, and saying
        so is the point of the test rather than a weakening of it.

        The stored records were authored under structure parser v1, which read
        `quiet` as "zero positive BOS/MSS events". v1 could not ask whether the
        propositions behind those zeros had been EVALUATED, because the witness
        carried no evaluability. v2 can, and refuses to call an unevaluable read
        quiet. Rebuilding a v1 segment under v2 is therefore a DIFFERENT READING
        of the same sealed evidence.

        The v1 record is not wrong about what v1 believed, so it is preserved
        byte-for-byte. What must still hold is that everything NOT touched by the
        contract change is identical, and that the delta is exactly the two
        segments and the fields we measured -- never a silent drift somewhere
        else.
        """
        built = {r["segment_start"]: r for r in MA.build_records(NATIVE)["records"]}
        stored = {r["segment_start"]: r for r in live("PROD-20260806")}
        assert set(built) == set(stored) and len(built) == 10

        # The contract marker moves on EVERY record: all ten were authored under
        # v1 and all ten rebuild as v2. The READING moves on exactly two.
        CONTRACT_DELTA = {"12:08:22", "13:17:38"}
        VERSION_FIELDS = {"structure_evidence", "embedding_manifest_fingerprint"}
        READING_FIELDS = {"feature_vector"}
        UNTOUCHED = ("market_regime", "delivery_state", "liquidity_state",
                     "direction_distribution", "volatility_state")

        for start, record in stored.items():
            for field in UNTOUCHED:
                assert record[field] == built[start][field], \
                    f"{start}.{field} drifted; the structure contract does not own it"
            for field in VERSION_FIELDS:
                assert record[field] != built[start][field], \
                    f"{start}.{field} should carry the contract version change"
            for field in READING_FIELDS:
                changed = record[field] != built[start][field]
                assert changed == (start in CONTRACT_DELTA), \
                    f"{start}.{field} moved outside the measured contract delta"

        # HISTORICAL IMMUTABILITY: identity and the v1 reading are untouched.
        for start in CONTRACT_DELTA:
            assert stored[start]["memory_id"] == built[start]["memory_id"]
            v1, v2 = stored[start]["structure_evidence"], built[start]["structure_evidence"]
            assert v1["parser"] == "structure_witness_v1"
            assert v2["parser"] == "structure_witness_v2"
            assert v1["quiet"] is True and v2["quiet"] is False
            assert v2["structure_capability"] == "UNKNOWN"
            # the counts never moved: v2 asserts no new market activity
            assert v1["bos_count"] == v2["bos_count"] == 0
            assert v1["mss_count"] == v2["mss_count"] == 0
            # exactly one vector dimension differs, and dimensionality is stable
            a, b = stored[start]["feature_vector"], built[start]["feature_vector"]
            assert len(a) == len(b)
            assert [i for i, (x, y) in enumerate(zip(a, b)) if abs(x - y) > 1e-9] == [45]

        # the eight untouched segments still match field for field
        for start in set(stored) - CONTRACT_DELTA:
            for field in ("feature_vector", "market_regime", "delivery_state",
                          "liquidity_state", "direction_distribution",
                          "volatility_state"):
                assert stored[start][field] == built[start][field], f"{start}.{field}"

    def test_5_6b_v1_records_stay_comparable_except_where_v1_lacked_evidence(self):
        """The narrow de-authorization: one coordinate, not one corpus.

        An earlier attempt refused every v1 record outright, because the
        whole-manifest gate is all-or-nothing. That was measured to be far wider
        than the truth: across all 16 records exactly ONE coordinate changed
        meaning. A record whose v1 quiet=False rests on an OBSERVED BOS or MSS
        keeps every dimension -- missing evaluability cannot un-happen an event.
        """
        from ai_retrieval import retrieval as R
        from ai_retrieval import embedding_v2 as EV2
        stored = live("PROD-20260806")
        assert len(stored) == 10
        partial = set()
        for record in stored:
            se = record["structure_evidence"]
            assert se["parser"] == "structure_witness_v1"
            compat = R.vector_compatibility(record)
            assert compat["compatible"] is True, "the corpus may not go dark"
            if se["bos_count"] or se["mss_count"]:
                assert compat["mode"] == R.COMPAT_FULL
                assert compat["excluded_dimensions"] == frozenset()
            else:
                assert compat["mode"] == R.COMPAT_PARTIAL
                assert compat["excluded_dimensions"] == \
                    frozenset({EV2.STRUCTURE_QUIET_INDEX})
                partial.add(record["segment_start"])
        assert partial == {"12:08:22", "13:17:38"}

    def test_5_6c_the_stored_quiet_claim_is_preserved_not_corrected(self):
        """We are not calling these memories wrong. We are declining to read one
        coordinate as current evidence."""
        for record in live("PROD-20260806"):
            se = record["structure_evidence"]
            if se["quiet"]:
                assert se["bos_count"] == 0 and se["mss_count"] == 0
                assert se["parser"] == "structure_witness_v1"

    def test_11_migration_is_idempotent(self):
        import repair_descriptive_memory_ids as R
        before = open(STORE, "rb").read()
        assert R.main([]) == 0
        assert open(STORE, "rb").read() == before, "a dry run wrote to the store"
        for record in live():
            assert record["memory_id"] == canonical(record)

    def test_15_an_empty_intersection_cannot_pass_as_agreement(self):
        """The guard against the comparison that previously proved nothing."""
        a = {"09:30:24": {"x": 1}}
        b = {"99:99:99": {"x": 2}}
        joined = set(a) & set(b)
        differences = [k for k in joined if a[k] != b[k]]
        assert differences == []          # vacuously true...
        assert len(joined) == 0           # ...which is exactly why cardinality
        with pytest.raises(AssertionError):
            assert len(joined) == 1, "join cardinality must be asserted"


class TestReauthoringIdempotency:
    """12-14. The load-bearing regression proof."""

    def test_12_re_authoring_august_6_reproduces_the_canonical_ids(self):
        built = MA.build_records(NATIVE)["records"]
        assert len(built) == 10
        assert {r["memory_id"] for r in built} == \
            {r["memory_id"] for r in live("PROD-20260806")}

    def test_13_a_second_authoring_would_append_no_duplicates(self):
        built = MA.build_records(NATIVE)["records"]
        stored = {r["memory_id"] for r in live()}          # all 16
        novel = [r for r in built if r["memory_id"] not in stored]
        assert novel == [], f"{len(novel)} logical duplicates would be appended"

    def test_14_the_logical_join_is_ten_of_ten(self):
        built = {r["segment_start"]: r for r in MA.build_records(NATIVE)["records"]}
        stored = {r["segment_start"]: r for r in live("PROD-20260806")}
        assert len(built) == 10 and len(stored) == 10
        assert len(set(built) & set(stored)) == 10
        assert set(built) - set(stored) == set()
        assert set(stored) - set(built) == set()


class TestBrainContractProvenance:
    """16-20."""

    def test_16_the_source_contract_comes_from_session_evidence(self):
        out = SBC.resolve_source_brain_contract(PROJECTION, "PROD-20260807")
        assert out["source_brain_contract_fingerprint"] == "brain:0212947f0133fc76"
        assert out["source_brain_contract_evidence"] == \
            "session_authorization_record"
        assert out["source_brain_contract_resolution"] == \
            "PROVEN_FROM_SESSION_EVIDENCE"

    def test_16b_august_6_is_honestly_unrecoverable(self):
        """PROD-20260806 predates the field. Saying so beats guessing."""
        out = SBC.resolve_source_brain_contract(NATIVE, "PROD-20260806")
        assert out["source_brain_contract_fingerprint"] == SBC.UNRECORDED
        assert out["source_brain_contract_resolution"] == \
            "UNRECOVERABLE_FROM_EVIDENCE"
        # the runtime commit still pins the contract sources exactly
        assert out["source_runtime_head"] == "7253640"

    def test_17_the_current_contract_cannot_stand_in_for_the_historical_one(self):
        from ai_brain.production_model import brain_contract_fingerprint
        current = brain_contract_fingerprint()
        for record in live():
            provenance = record["provenance"]
            assert provenance["source_brain_contract_fingerprint"] != current
            assert record["brain_contract_fingerprint_suffix"] != current[-6:]
            # and the authoring contract is present, well-formed and LABELLED
            # as such. NOT asserted equal to `current`: that would only hold
            # until a contract source legitimately changes, and one has --
            # REPAIR-PATH-RESTORATION escaped the repair template's literal
            # JSON braces, which `brain_contract_fingerprint` is designed to
            # notice. What must stay true is that the historical contract is
            # not the current one, asserted above.
            authoring = provenance["authoring_contract_fingerprint"]
            assert isinstance(authoring, str) and authoring.startswith("brain:")
            assert authoring != provenance["source_brain_contract_fingerprint"]
            assert "not the contract that produced" in \
                provenance["authoring_contract_note"]

    def test_17b_a_luna_session_no_longer_claims_a_terra_contract(self):
        for record in live("PROD-20260806"):
            assert record["source_model"] == "gpt-5.6-luna"
            assert record["brain_contract_fingerprint_suffix"] == SBC.UNRECORDED
            assert record["provenance"]["source_runtime_head"] == "7253640"

    def test_18_august_7_proposals_carry_their_historical_contract(self):
        built = MA.build_records(PROJECTION)["records"]
        assert built
        for record in built:
            provenance = record["provenance"]
            assert provenance["source_brain_contract_fingerprint"] == \
                "brain:0212947f0133fc76"
            assert record["brain_contract_fingerprint_suffix"] == "33fc76"
            assert provenance["source_runtime_head"] == "d167b20"

    def test_19_20_closure_provenance_survives_both_migrations(self):
        from ai_retrieval import session_closure as SC
        for record in live("PROD-20260806"):
            assert record["provenance"]["closure_type"] == \
                SC.NATIVE_LAUNCHER_CLOSE
        for record in live("PROD-20260807"):
            assert record["provenance"]["closure_type"] == \
                SC.OPERATOR_TERMINATED_CLOSE
        for record in MA.build_records(PROJECTION)["records"]:
            provenance = record["provenance"]
            assert provenance["closure_type"] == SC.OPERATOR_TERMINATED_CLOSE
            assert provenance["contract_identity_provenance"] == \
                "RECOVERED_SESSION_LEVEL"
            assert provenance["observation_window_end_et"] == "13:11:17"


class TestRetrievalUnaffected:
    """7-8, 22."""

    def test_7_8_22_ranking_and_similarity_are_untouched_by_the_re_id(self):
        """Vectors decide ranking; ids only name the winner."""
        import collections
        import importlib
        import tempfile
        tmp = tempfile.mkdtemp(prefix="reid_")
        os.environ["AI_RETRIEVAL_DIR"] = tmp
        os.environ["AI_RETRIEVAL_ENABLED"] = "true"
        records = live("PROD-20260806")
        with open(os.path.join(tmp, "memory_store.jsonl"), "w",
                  encoding="utf-8") as fh:
            for record in records:
                fh.write(json.dumps(record, default=str) + "\n")
        from ai_retrieval import vector_store
        importlib.reload(vector_store)
        from ai_retrieval import retrieval
        importlib.reload(retrieval)

        context = {
            "market_regime": {"regime_label": "chop", "volatility_state": "toxic"},
            "session": "lunch",
            "narrative_authority": {"narrative_phase": "accumulation",
                                    "narrative_direction": "conflicted",
                                    "active_liquidity_draw": True},
            "shared_context": {"delivery_state": "mixed",
                               "exhaustion_present": True},
            "liquidity": {"nearest_buy_side": 29821.75,
                          "nearest_sell_side": 29452.5},
            "protected_swings": {"protected_high": {"level": 29855.0},
                                 "protected_low": {"level": 29493.25}},
            "STRUCTURE_WITNESS": {"bos_count": 0, "mss_count": 0, "quiet": True},
            "phase_confidence_summary": {"mean": 60.0, "min": 45.0, "max": 75.0,
                                         "observations": 20}}
        out = retrieval.retrieve_analogs(context)
        analogs = out.get("analogs") or []
        # the exhaustion query returned exactly these two similarities before
        # the migration; the ids moved, the geometry did not
        assert [round(a["similarity"], 4) for a in analogs] == [0.6695, 0.6691]
        assert all(a["authority"] == "CONTEXT_ONLY" for a in analogs)
        assert all(v <= 2 for v in collections.Counter(
            a["session_id"] for a in analogs).values())
        returned = {a["memory_id"] for a in analogs}
        assert returned <= {r["memory_id"] for r in records}


class TestNoSideEffects:
    """25-26."""

    def test_25_26_migrations_touch_no_authorization_and_no_order_path(self):
        import ast
        for name in ("repair_descriptive_memory_ids.py",
                     "repair_historical_brain_contract.py"):
            tree = ast.parse(open(os.path.join(ROOT, "tools", name),
                                  encoding="utf-8").read())
            called = {getattr(n.func, "attr", "") or getattr(n.func, "id", "")
                      for n in ast.walk(tree) if isinstance(n, ast.Call)}
            for forbidden in ("place_bracket_market_order", "place_order_raw",
                              "gated_submit", "cancel_order", "modify_order",
                              "SessionAuthorization", "authenticate"):
                assert forbidden not in called, f"{name}: {forbidden}"

    def test_the_repo_is_not_carrying_the_live_corpus(self):
        out = subprocess.run(["git", "check-ignore", STORE],
                             capture_output=True, text=True, cwd=ROOT)
        assert out.returncode == 0, "the live corpus must stay git-ignored"
