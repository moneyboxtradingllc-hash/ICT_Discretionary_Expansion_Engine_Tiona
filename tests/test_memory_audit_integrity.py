"""AUDIT-PROD-20260806-MEMORY-AND-RETRIEVAL -- integrity locks.

Read-only. These assert what the memory audit concluded, so a future change that
quietly starts writing retrieval memory (or reaches an OpenAI vector store) is
caught rather than discovered later.

Runtime stores are git-ignored; those checks skip cleanly when absent. The
committed report is always checked and must never carry a secret.
"""
from __future__ import annotations

import json
import os
import re
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src"))

DOC = os.path.join("docs", "production", "sessions", "PROD-20260806_MEMORY_AUDIT.md")
INV = os.path.join("data", "replay_sessions", "PROD-20260806", "analysis",
                   "memory_inventory.json")
STORE = os.path.join("data", "ai_retrieval", "memory_store.jsonl")
have_inv = pytest.mark.skipif(not os.path.exists(INV),
                              reason="inventory lives in the ignored archive")


def inventory():
    return json.load(open(INV, encoding="utf-8"))


class TestNoOpenAIVectorStoreUsage:
    """The bot's memory is local. Nothing may reach a hosted vector store."""

    def test_the_repository_never_calls_the_vector_store_api(self):
        import subprocess
        r = subprocess.run(
            ["grep", "-rn", "-e", "vector_stores", "-e", "file_search",
             "-e", "vector_store_ids", "-e", "file_batches",
             "--include=*.py", "src", "tools"],
            capture_output=True, text=True)
        assert not r.stdout.strip(), r.stdout[:400]

    def test_the_repository_never_calls_the_embeddings_api(self):
        import subprocess
        r = subprocess.run(["grep", "-rn", "embeddings.create", "--include=*.py",
                            "src", "tools"], capture_output=True, text=True)
        assert not r.stdout.strip(), r.stdout[:400]

    def test_the_local_embedding_is_deterministic_and_offline(self):
        import inspect

        from ai_retrieval import embedding as E
        src = inspect.getsource(E)
        assert "openai" not in src.lower()
        assert E.EMBED_DIM == 47
        a = E.embed({"market_context": {"regime": "range_rotation"}})
        b = E.embed({"market_context": {"regime": "range_rotation"}})
        assert a == b and len(a) == 47

    @have_inv
    def test_the_inventory_reports_zero_hosted_stores(self):
        v = inventory()["openai_vector_stores"]
        assert v["count"] == 0 and v["bytes"] == 0
        assert v["classification"].startswith("OPENAI_VECTOR_STORE_UNUSED")


class TestRetrievalCorpusIsEmpty:

    @pytest.mark.skipif(not os.path.exists(STORE), reason="store is ignored")
    def test_the_corpus_was_empty_at_audit_time(self):
        """The PROD-20260806 audit found 0 records -- that finding stands as
        history. The corpus was first written on 2026-08-06 by
        AUTHOR-PROD-20260806-DESCRIPTIVE-MEMORY, so emptiness is no longer a
        live invariant. What is asserted now is that anything present is
        descriptive, CONTEXT_ONLY and never outcome-validated."""
        from ai_retrieval import vector_store
        for r in vector_store.load_records():
            assert r.get("memory_type") == "descriptive_observation"
            assert r.get("authority") == "CONTEXT_ONLY"
            assert r.get("outcome_validated") is False

    def test_retrieval_returns_nothing_for_every_representative_context(self):
        from ai_retrieval import retrieval, vector_store
        if vector_store.count():
            pytest.skip("corpus is no longer empty; re-audit before relying on this")
        for ctx in ({"market_context": {"regime": "trend_up"}},
                    {"market_context": {"regime": "trend_down"}},
                    {"market_context": {"regime": "range_rotation"}},
                    {"narrative_context": {"narrative_phase": "exhaustion"}}):
            r = retrieval.retrieve_analogs(ctx, k=5, authoritative_only=True,
                                           min_similarity=0.0, persist_log=False)
            assert r["returned"] == 0 and r["analogs"] == []

    def test_the_production_loop_never_writes_retrieval_memory(self):
        """No scan-to-corpus path exists; nothing was offered or rejected."""
        import ast
        for rel in (os.path.join("src", "broker", "topstepx_production_loop.py"),
                    os.path.join("src", "live_scan", "production_scan_cycle.py")):
            src = open(rel, encoding="utf-8").read()
            calls = {getattr(n.func, "attr", "") for n in ast.walk(ast.parse(src))
                     if isinstance(n, ast.Call)}
            assert "add_record" not in calls and "add_records" not in calls


class TestIdentityFiltersStillExclude:

    def test_qqq_and_identity_less_records_are_excluded(self):
        from doctrine.instrument_identity import retrieval_eligible
        assert retrieval_eligible({"market_context": {"symbol": "QQQ"}})[0] is False
        assert retrieval_eligible({"market_context": {}})[1] == "missing_instrument_identity"
        assert retrieval_eligible({"market_context": {"symbol": "MNQ"}})[0] is True

    def test_degraded_and_fallback_are_not_sovereign(self):
        from live_scan.production_scan_cycle import ProductionScanCycle
        for s in ("degraded", "deterministic", "llm_failed_fallback"):
            assert ProductionScanCycle.is_sovereign(
                {"source": s, "output": {"narrative_direction": "bullish"}}) is False


@have_inv
class TestInventoryIsHonest:

    def test_every_system_carries_proof(self):
        for s in inventory()["systems"]:
            assert s["proof"], s["name"]

    def test_archive_stores_are_not_labelled_retrieval_memory(self):
        for s in inventory()["systems"]:
            if "BRAIN_ARTIFACT_STORE" in s["taxonomy"] or "RAW_SESSION_LOG" in s["taxonomy"]:
                assert "VECTOR_RETRIEVAL_MEMORY" not in s["taxonomy"], s["name"]

    def test_the_retrieval_system_reports_zero_records(self):
        vs = [s for s in inventory()["systems"]
              if s["name"] == "vector_retrieval_memory"][0]
        assert vs["after_records"] in (0, None)
        assert vs["written_during_session"] is False

    def test_slippage_state_reports_no_fills(self):
        sl = [s for s in inventory()["systems"] if s["name"] == "slippage_state"][0]
        assert sl["after_records"] == 0 and sl["written_during_session"] is False

    def test_the_audit_declares_itself_read_only(self):
        assert "READ-ONLY" in inventory()["audit_mode"]


class TestCommittedReportIsSafe:

    def test_the_report_exists(self):
        assert os.path.exists(DOC)

    def test_it_carries_no_credential_or_account_identity(self):
        from dotenv import load_dotenv
        load_dotenv(".env")
        txt = open(DOC, encoding="utf-8").read()
        for k in ("OPENAI_API_KEY", "TOPSTEPX_API_KEY", "TOPSTEPX_USERNAME",
                  "TOPSTEPX_ACCOUNT_ID", "TOPSTEPX_ACCOUNT_FINGERPRINT"):
            v = os.getenv(k)
            if v:
                assert v not in txt, k
        assert not re.search(r"\bacct:[0-9a-f]{12}\b", txt)
        assert not re.search(r"\bauth:[0-9a-f]{16}\b", txt)
        assert not re.search(r"\bsk-[A-Za-z0-9_-]{12,}", txt)

    def test_it_does_not_call_the_archive_learned_memory(self):
        txt = " ".join(open(DOC, encoding="utf-8").read().lower().split())
        assert "the archive is not memory" in txt

    def test_it_states_the_empty_corpus_conclusion(self):
        txt = " ".join(open(DOC, encoding="utf-8").read().lower().split())
        assert "cannot retrieve a single thing from today" in txt

    def test_it_records_that_no_memory_was_written(self):
        txt = open(DOC, encoding="utf-8").read()
        assert "memory records inserted   : 0" in txt
        assert "vector stores created     : 0" in txt
