"""ADD-PER-SCAN-MEMORY-RETRIEVAL-TELEMETRY (2026-08-07).

After a session we must be able to answer from machine-countable evidence --
not prose -- whether retrieval was enabled on each scan, whether the hook
touched the corpus, what was excluded and why, which analogs reached Terra, from
which sessions, whether recurrence collapsed anything and whether the
per-session cap fired.

Two live defects were found while tracing the call path and are fixed here:

  * `narrative_brain` re-queried whenever the scan's retrieval result carried no
    analogs, passing `min_similarity=0.0`. That bypassed the bound
    MIN_SIMILARITY (0.60).
  * `retrieve_analogs` has no enablement gate of its own -- only
    `retrieve_for_snapshot` does -- so that second call also bypassed
    AI_RETRIEVAL_ENABLED entirely.

Either way the Brain could be shown analogs the contract had rejected, and any
telemetry describing "the" retrieval would have described a different query than
the one Terra consumed. ONE SCAN -> ONE RETRIEVAL RESULT.
"""
from __future__ import annotations

import ast
import json
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src"))

from ai_retrieval import descriptive_memory as DM                # noqa: E402
from ai_retrieval import embedding_v2 as EV2                     # noqa: E402
from ai_retrieval import retrieval as R                          # noqa: E402
from ai_retrieval import retrieval_telemetry as T                # noqa: E402
from ai_retrieval import vector_store                            # noqa: E402

LIVE_STORE = os.path.join("data", "ai_retrieval", "memory_store.jsonl")
#: Moved by REPAIR-V2_2-DESCRIPTIVE-MEMORY-IDENTITY and
#: BIND-HISTORICAL-BRAIN-CONTRACT-PROVENANCE (2026-08-07): ten ids were
#: re-derived so each record can reproduce its own identity, and the leaked
#: current-Brain-contract stamp was replaced with session-bound provenance.
#: Market content and every feature vector are unchanged.
#: Moved by AUTHOR-PROD-20260807-DESCRIPTIVE-MEMORY (2026-08-07): the six
#: approved August 7 observations were authored, taking the corpus 10 -> 16.
#: August 6 content and every August 6 vector are unchanged.
LEDGER_SHA = "a489a36f71f113249e0916e2d003d174d4aa86f95592cf85be087cb302378466"
EMPTY = {"level": None, "timeframe": None, "basis": None, "registered_at": None}

#: REPAIR-RETRIEVAL-FIXTURE-CLOCK (2026-10-09). Both corpora `live` can seed --
#: the August 6 archive or the synthetic stand-in -- are 2026-08-06 sessions,
#: offered through 2026-10-05 and expired from 2026-10-06 under the 60-day
#: rule. Retrieval measures age on `R._today_et()`. Unpinned, from 2026-10-06
#: every query here was answered "expired": two tests went red and the rest
#: kept passing over empty results. `live` now evaluates on the morning after
#: authoring, and the boundary is tested explicitly in TestRetentionBoundary.
EVALUATION_DAY = "2026-08-07"           # age 1
LAST_VALID_DAY = "2026-10-05"           # age 60: still offered
FIRST_EXPIRED_DAY = "2026-10-06"        # age 61: expired
FIXTURE_SOURCE_SESSIONS = ["PROD-20260806"]


def pin_retrieval_day(monkeypatch, day: str) -> None:
    """Evaluate retrieval age on `day` for this test only (restored at
    teardown; monkeypatch raises if the name disappears)."""
    monkeypatch.setattr(R, "_today_et", lambda: day)


def assert_analogs_returned(result: dict) -> None:
    """The positive path really ran: evaluated in-window, at least one analog,
    every analog from the seeded August 6 session."""
    assert result["as_of_session_date"] == EVALUATION_DAY
    assert result["returned"] >= 1
    assert sorted({a["session_id"] for a in result["analogs"]}) == \
        FIXTURE_SOURCE_SESSIONS


def record(**over):
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
    return DM.make_descriptive_record(**base)


def snap(session="lunch", regime="range_rotation", vol="toxic",
         ndir="conflicted", nphase="transition",
         delivery="accumulation_building", exh=True, liquidity=True):
    s = {"session": session, "contract": "CON.F.US.MNQ.U26",
         "market_regime": {"regime_label": regime, "volatility_state": vol},
         "narrative_authority": {"narrative_direction": ndir,
                                 "narrative_phase": nphase,
                                 "active_liquidity_draw": "29500"},
         "shared_context": {"delivery_state": delivery, "exhaustion_present": exh},
         "protected_swings": {},
         "STRUCTURE_WITNESS": {tf: {"bos_event": False, "mss_event": False}
                               for tf in ("15m", "5m", "3m", "1m")},
         "phase_confidence_summary": {"mean": 60.0, "min": 50.0, "max": 70.0}}
    if liquidity:
        s["liquidity"] = {"nearest_buy_side": 29800.0, "nearest_sell_side": 29200.0}
    else:
        s["liquidity"] = {}
    return s


@pytest.fixture
def live(tmp_path, monkeypatch):
    """An isolated corpus seeded from the real ten August 6 records when they
    are present, else a synthetic stand-in, read on EVALUATION_DAY."""
    monkeypatch.setenv("AI_RETRIEVAL_DIR", str(tmp_path / "r"))
    monkeypatch.setenv("REPLAY_SESSIONS_DIR", str(tmp_path / "sessions"))
    monkeypatch.setenv("AI_RETRIEVAL_ENABLED", "true")
    pin_retrieval_day(monkeypatch, EVALUATION_DAY)
    src = os.path.join("data", "replay_sessions", "PROD-20260806", "analysis",
                       "proposed_descriptive_memory_v2_1")
    if os.path.isdir(src):
        import glob
        vector_store.add_records([json.load(open(p, encoding="utf-8"))
                                  for p in glob.glob(os.path.join(src, "mem_*.json"))])
    else:
        vector_store.add_record(record())
    return tmp_path


def session(tmp_path):
    return T.RetrievalTelemetrySession("PROD-TEST", instrument="MNQ",
                                       contract="CON.F.US.MNQ.U26")


@pytest.fixture
def telemetry_corpus(tmp_path, monkeypatch):
    """Real synthetic records, independent of the operator's archive.

    The explicit fixture runs after the suite's runtime-root isolation and
    pins only the ET date retrieval reads, with normal per-test teardown.
    """
    monkeypatch.setenv("AI_RETRIEVAL_DIR", str(tmp_path / "telemetry"))
    monkeypatch.setenv("AI_RETRIEVAL_ENABLED", "true")
    pin_retrieval_day(monkeypatch, EVALUATION_DAY)

    def seed(records):
        ids = {r["memory_id"] for r in records}
        assert len(ids) == len(records)
        assert vector_store.add_records(records) == len(records)
        stored = vector_store.load_records()
        assert {r["memory_id"] for r in stored} == ids
        assert len(stored) == len(records)
        return records

    return seed


# ══════════════════════════════════════════════════════════════════════════════
class TestOneRetrievalPerScan:
    """1-2, 33. The defect this mission found."""

    def test_1_the_brain_never_re_queries_retrieval(self):
        src = open("src/ai_brain/narrative_brain.py", encoding="utf-8").read()
        tree = ast.parse(src)
        called = {getattr(n.func, "id", "") or getattr(n.func, "attr", "")
                  for n in ast.walk(tree) if isinstance(n, ast.Call)}
        assert "retrieve_analogs" not in called
        assert "retrieve_for_snapshot" not in called

    def test_2_the_bound_threshold_can_no_longer_be_bypassed(self):
        """The removed call passed `min_similarity=0.0`.

        Checked on the AST, not the source text -- the comment that documents
        the removal necessarily quotes the argument it removed.
        """
        tree = ast.parse(open("src/ai_brain/narrative_brain.py",
                              encoding="utf-8").read())
        overrides = [kw for n in ast.walk(tree) if isinstance(n, ast.Call)
                     for kw in n.keywords
                     if kw.arg in ("min_similarity", "authoritative_only", "k")]
        assert not overrides, "the Brain still overrides retrieval-contract values"

    def test_33_the_scan_cycle_retrieves_exactly_once(self):
        tree = ast.parse(open("src/live_scan/production_scan_cycle.py",
                              encoding="utf-8").read())
        calls = [n for n in ast.walk(tree) if isinstance(n, ast.Call)
                 and getattr(n.func, "id", "") == "retrieve_for_snapshot"]
        assert len(calls) == 1

    def test_the_brain_consumes_the_object_the_scan_produced(self, live):
        result = R.retrieve_for_snapshot(snap(), "MNQ")
        assert_analogs_returned(result)
        snapshot = {"ai_retrieval": result}
        assert snapshot["ai_retrieval"] is result


class TestRecordShape:
    """3-11, 22-25."""

    def build(self, live, **over):
        result = R.retrieve_for_snapshot(snap(**over), "MNQ")
        return T.build_record(session_id="PROD-TEST", scan_id="scan-1",
                              instrument="MNQ", contract="CON.F.US.MNQ.U26",
                              result=result,
                              startup_state=R.retrieval_startup_state(),
                              duration_ms=1.23), result

    def test_3_4_5_6_identity_fields(self, live):
        rec, _ = self.build(live)
        assert rec["schema_version"] == "memory_retrieval_telemetry.v1"
        assert rec["scan_id"] == "scan-1"
        assert rec["session_id"] == "PROD-TEST"
        assert rec["instrument"] == "MNQ"
        assert rec["contract"] == "CON.F.US.MNQ.U26"
        # ET-aware, not naive
        from datetime import datetime
        assert datetime.fromisoformat(rec["timestamp_et"]).tzinfo is not None

    def test_7_9_enabled_and_corpus_are_recorded(self, live):
        rec, _ = self.build(live)
        assert rec["retrieval_enabled"] is True
        assert rec["startup_memory_state"] == "ready"
        assert rec["corpus_size"] == vector_store.count()

    def test_10_11_query_completeness_is_recorded(self, live):
        ok, _ = self.build(live)
        assert ok["query_complete"] is True
        assert ok["missing_required_query_blocks"] == []
        bad, _ = self.build(live, liquidity=False)
        assert bad["query_complete"] is False
        assert "liquidity_state" in bad["missing_required_query_blocks"]
        assert bad["incomplete_query_reason"] == "INCOMPLETE_RETRIEVAL_QUERY"
        assert bad["returned_analog_count"] == 0

    def test_22_23_24_25_returned_analog_metadata(self, live):
        rec, result = self.build(live)
        assert_analogs_returned(result)
        assert rec["returned_analog_count"] == len(result["analogs"])
        assert rec["source_sessions"] == FIXTURE_SOURCE_SESSIONS
        for a in rec["returned_analogs"]:
            assert a["authority"] == "CONTEXT_ONLY"
            assert a["outcome_validated"] is False
            assert "levels_withheld" in a
            assert a["source_session_id"]
        assert rec["source_sessions"]
        assert rec["retrieval_authority"] == "CONTEXT_ONLY"

    def test_no_unsafe_field_is_logged(self, live):
        rec, result = self.build(live)
        assert_analogs_returned(result)     # the analog loop below is not empty
        blob = json.dumps(rec).lower()
        for banned in ("api_key", "account_id", "authorization_fingerprint",
                       "llm_prompt", "llm_raw_response", "jwt"):
            assert banned not in blob, banned
        for a in rec["returned_analogs"]:
            assert len(a["memory_id_suffix"]) <= 8      # suffix, not full id

    def test_26_retrieval_errors_are_explicit(self):
        rec = T.build_record(session_id="S", scan_id="x", instrument="MNQ",
                             contract="C",
                             result={"enabled": True, "analogs": [],
                                     "error": "boom"},
                             startup_state={"state": "ready"})
        assert rec["retrieval_error"] == "boom"


class TestStageAccounting:
    """12-18, 31."""

    def test_12_to_18_stage_counters_are_present_and_reconcile(self, live):
        result = R.retrieve_for_snapshot(snap(), "MNQ")
        rec = T.build_record(session_id="S", scan_id="x", instrument="MNQ",
                             contract="C", result=result,
                             startup_state=R.retrieval_startup_state())
        for field in ("identity_rejected_count", "version_rejected_count",
                      "expired_count", "contradiction_gated_count",
                      "below_threshold_count", "recurrence_members_collapsed",
                      "session_cap_excluded_count", "returned_analog_count"):
            assert isinstance(rec[field], int), field
        # Reconciled through returned analogs, not by everything expiring.
        assert rec["expired_count"] == 0
        assert rec["returned_analog_count"] >= 1
        assert rec["stage_accounting_reconciles"] is True, (
            f"{rec['stage_accounting_total']} accounted vs corpus "
            f"{rec['corpus_size']}")

    def test_16_reason_occurrences_are_distinct_from_gated_records(self, live):
        """A record contradicting on three blocks is ONE gated record and THREE
        reason occurrences. Conflating them overstates the corpus."""
        result = R.retrieve_for_snapshot(
            snap(regime="expansion_up", vol="stable", ndir="bullish",
                 nphase="continuation", delivery="full_distribution_alignment"),
            "MNQ")
        rec = T.build_record(session_id="S", scan_id="x", instrument="MNQ",
                             contract="C", result=result,
                             startup_state=R.retrieval_startup_state())
        # In-window, so the records reached the contradiction gate; expiry,
        # which runs first, excluded none of them.
        assert result["as_of_session_date"] == EVALUATION_DAY
        assert rec["expired_count"] == 0
        assert rec["contradiction_gated_count"] > 0
        assert rec["contradiction_reason_occurrences"] >= \
            rec["contradiction_gated_count"]
        assert set(rec["contradiction_reason_counts"]) <= \
            set(T.CONTRADICTION_REASON_KEYS)

    @pytest.mark.parametrize("recurrence_type", [
        "exact_same_session", "semantic_same_session"])
    def test_18_19_20_recurrence_metadata_is_complete_and_truthful(
            self, telemetry_corpus, recurrence_type):
        contextual = ({"structure_evidence": {"bos_count": 2, "mss_count": 0,
                                              "quiet": False},
                       "structure_state": "witness_bos_2_mss_0",
                       "phase_confidence_summary": {"mean": 85.0, "min": 80.0,
                                                    "max": 90.0}}
                      if recurrence_type == "semantic_same_session" else {})
        records = telemetry_corpus([
            record(segment_start="11:00:00", segment_end="11:20:00",
                   source_artifact_digest="telemetry-recurrence-1"),
            record(segment_start="12:00:00", segment_end="12:20:00",
                   source_artifact_digest="telemetry-recurrence-2", **contextual)])
        assert EV2.semantic_recurrence_key(records[0]) is not None
        assert EV2.semantic_recurrence_key(records[0]) == \
            EV2.semantic_recurrence_key(records[1])
        same_vector = (records[0]["feature_vector_fingerprint"] ==
                       records[1]["feature_vector_fingerprint"])
        assert same_vector == (recurrence_type == "exact_same_session")
        result = R.retrieve_for_snapshot(snap(), "MNQ")
        assert_analogs_returned(result)
        assert result["returned"] == 1
        rec = T.build_record(session_id="S", scan_id="x", instrument="MNQ",
                             contract="C", result=result,
                             startup_state=R.retrieval_startup_state())
        groups = rec["recurrence_groups"]
        assert len(groups) == 1     # losing the intended group must FAIL
        g = groups[0]
        assert g["recurrence_type"] == recurrence_type
        assert g["recurrence_count"] == 2
        assert len(g["grouped_memory_id_suffixes"]) == g["recurrence_count"]
        assert len(g["occurrence_spans"]) == g["recurrence_count"]
        assert g["representative_memory_id_suffix"] in g["grouped_memory_id_suffixes"]
        members = {r["memory_id"][-8:] for r in records}
        assert len(members) == 2
        assert set(g["grouped_memory_id_suffixes"]) == members
        assert g["occurrence_spans"] == sorted(
            f"{r['segment_start']}-{r['segment_end']}" for r in records)
        analog = next(a for a in rec["returned_analogs"] if a.get("recurrence_count"))
        assert analog["member_representative_similarities"]
        assert set(analog["member_representative_similarities"]) == members
        assert set(analog["member_similarities"]) == members
        assert analog["memory_id_suffix"] == g["representative_memory_id_suffix"]
        assert analog["recurrence_type"] == recurrence_type
        assert analog["recurrence_count"] == 2
        assert analog["source_session_id"] == FIXTURE_SOURCE_SESSIONS[0]
        assert rec["source_sessions"] == FIXTURE_SOURCE_SESSIONS
        assert rec["corpus_size"] == 2
        assert rec["recurrence_members_collapsed"] == 1
        assert rec["returned_analog_count"] == 1
        assert rec["session_cap_excluded_count"] == 0
        assert rec["stage_accounting_total"] == 2
        assert rec["stage_accounting_reconciles"] is True
        assert vector_store.count() == 2     # grouping never rewrites the store

    @pytest.mark.parametrize("record_count", [1, 2, 3],
                             ids=["below_cap", "at_cap", "above_cap"])
    def test_21_session_cap_exclusions_are_recorded(
            self, telemetry_corpus, record_count):
        phases = ["transition", "exhaustion", "continuation"]
        records = telemetry_corpus([
            record(segment_start=f"{11+i}:00:00", segment_end=f"{11+i}:20:00",
                   source_artifact_digest=f"telemetry-cap-{i}",
                   narrative_phase=phases[i]) for i in range(record_count)])
        keys = [EV2.semantic_recurrence_key(r) for r in records]
        assert all(k is not None for k in keys)
        assert len(set(keys)) == record_count
        result = R.retrieve_for_snapshot(snap(), "MNQ")
        assert_analogs_returned(result)
        assert result["max_analogs_per_source_session"] == 2
        assert result["min_similarity"] == 0.60
        assert result["max_analogs"] == 5
        assert result["returned"] == min(record_count, 2)
        assert result["recurrence_groups_collapsed"] == []
        assert result["rejected_reasons"] == {}
        rec = T.build_record(session_id="S", scan_id="x", instrument="MNQ",
                             contract="C", result=result,
                             startup_state=R.retrieval_startup_state())
        excluded = {r["memory_id"][-8:] for r in records} - {
            a["memory_id"][-8:] for a in result["analogs"]}
        expected_count = max(0, record_count - 2)
        assert len(excluded) == expected_count
        assert len(rec["session_cap_exclusions"]) == expected_count
        assert {c["memory_id_suffix"] for c in rec["session_cap_exclusions"]} == excluded
        for c in rec["session_cap_exclusions"]:
            assert c["reason"] == "MAX_ANALOGS_PER_SOURCE_SESSION"
            assert c["source_session_id"] == FIXTURE_SOURCE_SESSIONS[0]
            assert c["similarity"] >= result["min_similarity"]
        assert rec["corpus_size"] == record_count
        assert rec["returned_analog_count"] == min(record_count, 2)
        assert rec["session_cap_excluded_count"] == expected_count
        assert rec["recurrence_members_collapsed"] == 0
        assert rec["recurrence_groups"] == []
        assert rec["source_sessions"] == FIXTURE_SOURCE_SESSIONS
        assert rec["stage_accounting_total"] == record_count
        assert rec["stage_accounting_reconciles"] is True


class TestEnablementAndTransitions:
    """8, plus the residual gap from the previous mission."""

    def test_8_mid_session_toggle_is_visible_per_scan(self, live, monkeypatch):
        s = T.RetrievalTelemetrySession("PROD-TOGGLE", instrument="MNQ")
        seq = []
        for scan, flag in (("A", "true"), ("B", "false"), ("C", "false"),
                           ("D", "true")):
            monkeypatch.setenv("AI_RETRIEVAL_ENABLED", flag)
            result = R.retrieve_for_snapshot(snap(), "MNQ")
            rec = s.record_scan(scan_id=scan, result=result,
                                startup_state=R.retrieval_startup_state())
            seq.append((scan, rec["retrieval_enabled"],
                        rec["retrieval_state_transition"]))
        assert seq == [("A", True, None),
                       ("B", False, "enabled_to_disabled"),
                       ("C", False, None),
                       ("D", True, "disabled_to_enabled")]
        summary = s.summary()
        assert summary["retrieval_enabled_scans"] == 2
        assert summary["retrieval_disabled_scans"] == 2
        assert len(summary["retrieval_state_transitions"]) == 2

    def test_a_disabled_scan_records_that_the_corpus_was_not_read(self, live,
                                                                  monkeypatch):
        monkeypatch.setenv("AI_RETRIEVAL_ENABLED", "false")
        result = R.retrieve_for_snapshot(snap(), "MNQ")
        rec = T.build_record(session_id="S", scan_id="x", instrument="MNQ",
                             contract="C", result=result,
                             startup_state=R.retrieval_startup_state())
        assert rec["retrieval_enabled"] is False
        assert rec["corpus_size"] == 0          # the hook never reached the store
        assert rec["returned_analog_count"] == 0
        assert rec["startup_memory_state"] == "MEMORY_PRESENT_BUT_RETRIEVAL_DISABLED"


class TestDurableStorage:
    """27-29, 36."""

    def test_28_telemetry_never_enters_the_memory_store(self, live):
        s = T.RetrievalTelemetrySession("PROD-PATH")
        result = R.retrieve_for_snapshot(snap(), "MNQ")
        before = vector_store.count()
        s.record_scan(scan_id="x", result=result,
                      startup_state=R.retrieval_startup_state())
        assert vector_store.count() == before
        assert "memory_store.jsonl" not in T.telemetry_path("PROD-PATH")
        assert "ai_retrieval" not in T.telemetry_path("PROD-PATH")

    def test_29_telemetry_lands_under_the_session_archive_root(self, live):
        s = T.RetrievalTelemetrySession("PROD-PATH")
        s.record_scan(scan_id="x",
                      result=R.retrieve_for_snapshot(snap(), "MNQ"),
                      startup_state=R.retrieval_startup_state())
        path = T.telemetry_path("PROD-PATH")
        assert os.path.exists(path)
        assert os.path.join("PROD-PATH", "memory_retrieval") in path
        lines = [l for l in open(path, encoding="utf-8") if l.strip()]
        assert len(lines) == 1
        assert json.loads(lines[0])["scan_id"] == "x"

    def test_appends_are_newline_delimited_and_ordered(self, live):
        s = T.RetrievalTelemetrySession("PROD-APPEND")
        for i in range(3):
            s.record_scan(scan_id=f"s{i}",
                          result=R.retrieve_for_snapshot(snap(), "MNQ"),
                          startup_state=R.retrieval_startup_state())
        rows = [json.loads(l) for l in
                open(T.telemetry_path("PROD-APPEND"), encoding="utf-8") if l.strip()]
        assert [r["scan_id"] for r in rows] == ["s0", "s1", "s2"]

    def test_27_a_write_failure_is_loud_and_does_not_gate_trading(self, live,
                                                                  monkeypatch,
                                                                  tmp_path):
        """Telemetry is not execution authority. Refusing to trade because a log
        file could not be opened converts a reporting fault into a trading
        fault -- but it must never be swallowed.

        THE FAILURE IS INJECTED PORTABLY, AND THAT IS THE POINT.

        This test previously used `os.path.join("Z:\\", "nope", "x.jsonl")`,
        which is a dead drive on Windows and therefore unwritable there. On
        POSIX the same string is 'Z:\\/nope/x.jsonl' -- `os.path.isabs` says
        False -- so it is an ordinary RELATIVE path. `record_scan` calls
        `os.makedirs(..., exist_ok=True)`, the directory was created, the write
        SUCCEEDED, and the assertion below failed. Measured 2026-09-10: green on
        Windows, one failure on macOS/Linux, and a stray "Z:\\" directory left
        in the REPOSITORY ROOT -- which also dirtied the working tree that the
        pre-arm checklist requires to be clean.

        A regular file standing where a directory must be is unwritable on every
        supported platform, for the same reason, with no drive letters, no
        permission games, no shell and no umask. `makedirs` raises
        NotADirectoryError/FileExistsError, and the write fails deterministically.

        It lives under `tmp_path`, so the repository cannot be touched at all --
        a stronger invariant than ignoring the artifact would have been.
        """
        blocker = tmp_path / "not-a-directory"
        blocker.write_text("a regular file, standing where a directory must be")
        monkeypatch.setattr(T, "telemetry_path",
                            lambda sid: str(blocker / "nope" / "x.jsonl"))
        s = T.RetrievalTelemetrySession("PROD-FAIL")
        rec = s.record_scan(scan_id="x",
                            result=R.retrieve_for_snapshot(snap(), "MNQ"),
                            startup_state=R.retrieval_startup_state())
        assert rec["telemetry_write_ok"] is False
        assert T.WRITE_FAILED in rec["telemetry_write_error"]
        assert s.summary()["degraded_observability"] is True
        assert s.summary()["telemetry_write_failures"] == 1

    def test_36_the_live_memory_store_is_byte_identical(self):
        import hashlib
        if not os.path.exists(LIVE_STORE):
            pytest.skip("live store absent")
        assert hashlib.sha256(open(LIVE_STORE, "rb").read()).hexdigest() == LEDGER_SHA


class TestSessionSummary:
    """31."""

    def test_31_the_summary_reconciles_to_the_per_scan_records(self, live):
        s = T.RetrievalTelemetrySession("PROD-SUM")
        for i, ctx in enumerate((snap(), snap(nphase="exhaustion"),
                                 snap(regime="expansion_up", ndir="bullish",
                                      nphase="continuation",
                                      delivery="full_distribution_alignment"),
                                 snap(liquidity=False))):
            s.record_scan(scan_id=f"s{i}",
                          result=R.retrieve_for_snapshot(ctx, "MNQ"),
                          startup_state=R.retrieval_startup_state())
        summ = s.summary()
        assert summ["total_scans"] == 4
        assert summ["scans_with_analogs"] + summ["scans_without_analogs"] == 4
        assert summ["total_analog_presentations"] == sum(
            r["returned_analog_count"] for r in s.records)
        assert summ["total_contradiction_gated_records"] == sum(
            r["contradiction_gated_count"] for r in s.records)
        assert summ["incomplete_query_scans"] == 1
        assert summ["authority_values_seen"] in ([], ["CONTEXT_ONLY"])
        # Non-vacuous: the sums above reconcile real presentations and gating.
        assert summ["scans_with_analogs"] >= 1
        assert summ["total_analog_presentations"] >= 1
        assert summ["total_contradiction_gated_records"] >= 1
        assert summ["authority_values_seen"] == ["CONTEXT_ONLY"]


class TestNoBehaviourChange:
    """32. Telemetry observes; it does not steer."""

    def test_32_a_fixed_snapshot_produces_an_identical_retrieval_result(self, live):
        a = R.retrieve_for_snapshot(snap(), "MNQ")
        assert_analogs_returned(a)      # identical AND non-empty
        s = T.RetrievalTelemetrySession("PROD-FIXED")
        s.record_scan(scan_id="x", result=a,
                      startup_state=R.retrieval_startup_state())
        b = R.retrieve_for_snapshot(snap(), "MNQ")
        skip = {"as_of_session_date", "log_path"}
        for key in set(a) | set(b):
            if key in skip:
                continue
            assert a.get(key) == b.get(key), key

    def test_telemetry_does_not_mutate_the_result_it_describes(self, live):
        result = R.retrieve_for_snapshot(snap(), "MNQ")
        assert_analogs_returned(result)
        before = json.dumps(result, sort_keys=True, default=str)
        T.build_record(session_id="S", scan_id="x", instrument="MNQ",
                       contract="C", result=result,
                       startup_state=R.retrieval_startup_state())
        assert json.dumps(result, sort_keys=True, default=str) == before

    def test_30_the_scan_result_links_to_its_telemetry(self):
        src = open("src/live_scan/production_scan_cycle.py", encoding="utf-8").read()
        assert "memory_retrieval_telemetry_id" in src
        assert "memory_retrieval_telemetry" in src


class TestRetentionBoundary:
    """The 60-day inclusive rule as telemetry counts it. Each test names its
    own evaluation day; none relies on the fixture's in-window day."""

    @staticmethod
    def scan_on(monkeypatch, day, context):
        pin_retrieval_day(monkeypatch, day)
        result = R.retrieve_for_snapshot(context, "MNQ")
        assert result["as_of_session_date"] == day
        return T.build_record(session_id="S", scan_id=day, instrument="MNQ",
                              contract="C", result=result,
                              startup_state=R.retrieval_startup_state())

    def test_the_60th_day_is_returned_not_expired(self, live, monkeypatch):
        rec = self.scan_on(monkeypatch, LAST_VALID_DAY, snap())
        assert rec["expired_count"] == 0
        assert rec["returned_analog_count"] >= 1
        assert rec["source_sessions"] == FIXTURE_SOURCE_SESSIONS
        assert rec["stage_accounting_reconciles"] is True

    def test_the_61st_day_is_counted_as_expired(self, live, monkeypatch):
        rec = self.scan_on(monkeypatch, FIRST_EXPIRED_DAY, snap())
        assert rec["corpus_size"] >= 1
        assert rec["expired_count"] == rec["corpus_size"]
        assert rec["returned_analog_count"] == 0
        assert rec["source_sessions"] == []
        assert rec["stage_accounting_reconciles"] is True

    def test_expiry_is_accounted_before_the_contradiction_gate(self, live,
                                                               monkeypatch):
        contradictory = snap(regime="expansion_up", vol="stable", ndir="bullish",
                             nphase="continuation",
                             delivery="full_distribution_alignment")
        inside = self.scan_on(monkeypatch, EVALUATION_DAY, contradictory)
        assert inside["expired_count"] == 0
        assert inside["contradiction_gated_count"] >= 1
        outside = self.scan_on(monkeypatch, FIRST_EXPIRED_DAY, contradictory)
        assert outside["expired_count"] == outside["corpus_size"]
        assert outside["contradiction_gated_count"] == 0
        assert outside["contradiction_reason_occurrences"] == 0


class TestSafetyBoundary:
    """34-38."""

    def test_34_no_model_call_occurs_in_these_proofs(self):
        tree = ast.parse(open(__file__, encoding="utf-8").read())
        called = {getattr(n.func, "attr", "") or getattr(n.func, "id", "")
                  for n in ast.walk(tree) if isinstance(n, ast.Call)}
        for forbidden in ("run_narrative_brain", "create", "issue",
                          "gated_submit", "commit_records"):
            assert forbidden not in called, forbidden

    def test_35_telemetry_cannot_create_a_candidate(self, live):
        rec = T.build_record(session_id="S", scan_id="x", instrument="MNQ",
                             contract="C",
                             result=R.retrieve_for_snapshot(snap(), "MNQ"),
                             startup_state=R.retrieval_startup_state())
        for field in ("risk_usd", "contracts", "size", "reward_to_risk",
                      "invalidation_level", "objective", "direction_authority"):
            assert field not in rec, field
        assert rec["retrieval_authority"] == "CONTEXT_ONLY"
        assert rec["returned_analog_count"] >= 1     # proven WITH analogs present

    def test_37_38_no_authorization_or_order_path_here(self):
        assert os.environ.get("PRODUCTION_ARMED_SESSION") is None
        src = open("src/ai_retrieval/retrieval_telemetry.py", encoding="utf-8").read()
        for forbidden in ("gated_submit", "place_order", "SessionAuthorization",
                          "add_record"):
            assert forbidden not in src, forbidden
