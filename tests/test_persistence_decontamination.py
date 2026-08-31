"""DECONTAMINATE-PRODUCTION-MEMORY-AND-CAPITAL-STATE (2026-08-06).

Three persistence-integrity defects proven by the PROD-20260806 memory audit:

1. The suite wrote into live runtime stores -- real "lessons" into
   data/global_memory/, and a **QQQ** thesis into the live active_thesis.json.
2. That stale 2026-06-15 QQQ thesis sat in production state, and the identity
   guard did not catch it: `_load` checked `active["symbol"]` while the record
   stores the instrument at the FILE level, so the guard never fired.
3. capital_history.json carried NO account binding. Anchors 20260706..20260805
   all read 99990.53 -- an Alpaca paper balance, on a $50k Topstep Combine.

Nothing here authors memory. No retrospective August 6 record is inserted.
"""
from __future__ import annotations

import json
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src"))

from adaptive_learning import capital_intelligence_engine as CAP   # noqa: E402
from ai_brain.thesis_lifecycle import ThesisLifecycleEngine        # noqa: E402
from ai_retrieval import vector_store                              # noqa: E402
from deployment import global_memory                               # noqa: E402

IDENT = CAP.capital_identity(venue="TOPSTEPX", account_fingerprint="acct:test",
                             account_mode="COMBINE_SIMULATED", currency="USD")


def write_thesis(root, symbol, active=None):
    d = os.path.join(root, "ai_brain")
    os.makedirs(d, exist_ok=True)
    payload = {"symbol": symbol,
               "active": active or {"thesis_id": "TH_x", "status": "ACTIVE",
                                    "direction": "neutral", "age_scans": 1,
                                    "last_updated_at": "2099-01-01T00:00:00+00:00"}}
    json.dump(payload, open(os.path.join(d, "active_thesis.json"), "w", encoding="utf-8"))
    return d


# ══════════════════════════════════════════════════════════════════════════════
class TestTestsAreIsolatedFromProduction:

    def test_every_runtime_root_is_redirected(self):
        from tests.conftest import RUNTIME_ROOTS
        for var in RUNTIME_ROOTS:
            v = os.environ.get(var)
            assert v, f"{var} is not redirected"
            assert "expansion-test-runtime-" in v, f"{var} still points at {v}"

    def test_a_lesson_written_now_lands_in_the_temporary_root(self, tmp_path):
        assert global_memory.record_lesson("isolation probe", ["test"]) is True
        store = global_memory._store()
        assert "expansion-test-runtime-" in store
        assert "data" + os.sep + "global_memory" not in store

    def test_the_live_lessons_file_is_untouched_by_this_suite(self):
        live = os.path.join("data", "global_memory", "global_lessons.jsonl")
        if not os.path.exists(live):
            pytest.skip("live store absent")
        before = os.path.getsize(live)
        global_memory.record_lesson("second isolation probe", ["test"])
        assert os.path.getsize(live) == before

    def test_a_persisting_thesis_engine_writes_only_to_the_temporary_root(self):
        eng = ThesisLifecycleEngine(symbol="QQQ")   # persist defaults on
        from ai_brain.thesis_lifecycle import _active_path
        assert "expansion-test-runtime-" in _active_path()

    def test_the_mutation_guard_protects_the_expected_files(self):
        from tests.conftest import PROTECTED
        names = [os.path.basename(p) for p in PROTECTED]
        for expected in ("global_lessons.jsonl", "active_thesis.json",
                         "memory_store.jsonl", "capital_history.json"):
            assert expected in names


class TestForeignThesisIsBlocked:

    def test_a_qqq_thesis_cannot_enter_an_mnq_session(self, tmp_path, monkeypatch):
        monkeypatch.setenv("AI_BRAIN_DIR", write_thesis(str(tmp_path), "QQQ"))
        eng = ThesisLifecycleEngine(symbol="MNQ")
        assert eng._active is None
        assert eng.quarantined["reason"] == "foreign_instrument"
        assert eng.quarantined["stored_instrument"] == "QQQ"

    def test_an_identity_less_thesis_cannot_enter_production(self, tmp_path, monkeypatch):
        monkeypatch.setenv("AI_BRAIN_DIR", write_thesis(str(tmp_path), ""))
        eng = ThesisLifecycleEngine(symbol="MNQ")
        assert eng._active is None
        assert eng.quarantined["reason"] == "missing_instrument_identity"

    def test_the_file_level_identity_is_what_the_guard_reads(self, tmp_path, monkeypatch):
        """The original guard read active['symbol'], which the record never sets."""
        monkeypatch.setenv("AI_BRAIN_DIR", write_thesis(str(tmp_path), "QQQ"))
        raw = json.load(open(os.path.join(os.environ["AI_BRAIN_DIR"],
                                          "active_thesis.json"), encoding="utf-8"))
        assert "symbol" not in raw["active"] and raw["symbol"] == "QQQ"
        assert ThesisLifecycleEngine(symbol="MNQ")._active is None

    def test_a_same_instrument_thesis_still_loads(self, tmp_path, monkeypatch):
        monkeypatch.setenv("AI_BRAIN_DIR", write_thesis(str(tmp_path), "MNQ"))
        eng = ThesisLifecycleEngine(symbol="MNQ")
        assert eng.quarantined is None
        assert eng._active is not None

    def test_quarantine_preserves_evidence_without_relabelling(self, tmp_path, monkeypatch):
        d = write_thesis(str(tmp_path), "QQQ")
        monkeypatch.setenv("AI_BRAIN_DIR", d)
        eng = ThesisLifecycleEngine(symbol="MNQ")
        q = eng.quarantined
        assert q["stored_instrument"] == "QQQ"          # not rewritten to MNQ
        raw = json.load(open(os.path.join(d, "active_thesis.json"), encoding="utf-8"))
        assert raw["symbol"] == "QQQ"                   # file untouched

    def test_no_august_6_thesis_is_invented(self, tmp_path, monkeypatch):
        monkeypatch.setenv("AI_BRAIN_DIR", str(tmp_path))
        eng = ThesisLifecycleEngine(symbol="MNQ")
        assert eng._active is None and eng.quarantined is None


class TestCapitalPeakIsAccountScoped:

    def hist(self, tmp_path, payload):
        d = tmp_path / "ACCOUNT"
        d.mkdir(parents=True, exist_ok=True)
        json.dump(payload, open(d / "capital_history.json", "w", encoding="utf-8"))
        return str(tmp_path)

    def test_same_account_history_loads(self, tmp_path):
        base = self.hist(tmp_path, {**IDENT, "peak_equity": 51000.0,
                                    "last_equity": 50042.96, "daily_anchors": {}})
        m = CAP.build_capital_metrics("MNQ", {"equity": 50042.96}, today="20260807",
                                      base_dir=base, identity=IDENT)
        assert m["peak_equity"] == 51000.0
        assert m["peak_equity_source"] == "same_account_history"
        assert m["foreign_history_quarantined"] is None

    def test_identity_less_history_is_excluded(self, tmp_path):
        """The exact live shape: anchors and a peak, no identity fields at all."""
        base = self.hist(tmp_path, {"peak_equity": 99990.53, "last_equity": 50042.96,
                                    "daily_anchors": {"20260805": 99990.53}})
        m = CAP.build_capital_metrics("MNQ", {"equity": 50042.96}, today="20260807",
                                      base_dir=base, identity=IDENT)
        assert m["peak_equity"] == 50042.96
        assert m["peak_equity_source"] == "initialized_from_verified_balance"
        assert m["foreign_history_quarantined"] == "history_has_no_identity"
        assert m["quarantined_peak"] == 99990.53

    def test_a_foreign_account_peak_is_excluded(self, tmp_path):
        foreign = {**IDENT, "account_fingerprint": "acct:someone_else"}
        base = self.hist(tmp_path, {**foreign, "peak_equity": 99990.53})
        m = CAP.build_capital_metrics("MNQ", {"equity": 50042.96}, today="20260807",
                                      base_dir=base, identity=IDENT)
        assert m["peak_equity"] == 50042.96
        assert m["foreign_history_quarantined"] == "identity_mismatch:account_fingerprint"

    def test_a_cross_venue_peak_is_excluded(self, tmp_path):
        base = self.hist(tmp_path, {**IDENT, "venue": "ALPACA", "peak_equity": 99990.53})
        m = CAP.build_capital_metrics("MNQ", {"equity": 50042.96}, today="20260807",
                                      base_dir=base, identity=IDENT)
        assert m["foreign_history_quarantined"] == "identity_mismatch:venue"
        assert m["peak_equity"] == 50042.96

    def test_a_schema_mismatch_is_excluded(self, tmp_path):
        base = self.hist(tmp_path, {**IDENT, "schema_version": 1, "peak_equity": 99990.53})
        m = CAP.build_capital_metrics("MNQ", {"equity": 50042.96}, today="20260807",
                                      base_dir=base, identity=IDENT)
        assert m["foreign_history_quarantined"] == "schema_version_mismatch"

    def test_drawdown_uses_the_same_account_peak(self, tmp_path):
        base = self.hist(tmp_path, {"peak_equity": 99990.53, "daily_anchors": {}})
        m = CAP.build_capital_metrics("MNQ", {"equity": 50042.96}, today="20260807",
                                      base_dir=base, identity=IDENT)
        dd = m.get("drawdown_pct") if m.get("drawdown_pct") is not None else m.get("drawdown")
        assert m["peak_equity"] == 50042.96
        assert not dd, f"drawdown must be ~0 against a same-account peak, got {dd}"

    def test_the_rejected_record_is_preserved_beside_the_new_history(self, tmp_path):
        base = self.hist(tmp_path, {"peak_equity": 99990.53,
                                    "daily_anchors": {"20260805": 99990.53}})
        CAP.track_capital("MNQ", account={"equity": 50042.96}, today="20260807",
                          base_dir=base, identity=IDENT)
        saved = json.load(open(tmp_path / "ACCOUNT" / "capital_history.json",
                               encoding="utf-8"))
        assert saved["account_fingerprint"] == IDENT["account_fingerprint"]
        assert saved["rejected_foreign_history"]["peak_equity"] == 99990.53
        assert saved["initialized_from"] == "verified_same_account_balance"

    def test_identity_is_required_not_assumed(self):
        ok, why = CAP.identity_matches({"peak_equity": 1.0}, IDENT)
        assert ok is False and why == "history_has_no_identity"
        ok, why = CAP.identity_matches(IDENT, None)
        assert ok is False and why == "no_session_identity"


class TestStartupGuards:

    def session(self):
        return type("S", (), {"account": type("A", (), {"id": 1})(),
                              "contract": type("C", (), {"id": "CON.F.US.MNQ.U26"})(),
                              "market_hub": object()})()

    def test_armed_refuses_a_foreign_thesis(self, tmp_path, monkeypatch):
        from tools import topstepx_production_session as PS
        monkeypatch.setenv("AI_BRAIN_DIR", write_thesis(str(tmp_path), "QQQ"))
        monkeypatch.setenv("SCAN_SYMBOL", "MNQ")
        monkeypatch.setenv("TOPSTEPX_ACCOUNT_FINGERPRINT", "acct:test")
        monkeypatch.setenv("AI_BRAIN_MODEL", "gpt-5.6-terra")
        monkeypatch.setenv("BRAIN_JSON_MODE", "on")
        out = PS.check_startup(self.session(), armed=True, mission_id="M",
                               provider="topstepx")
        assert any(r.startswith("FOREIGN_THESIS_STATE") for r in out), out

    def test_disarmed_diagnostics_remain_possible(self, tmp_path, monkeypatch):
        from tools import topstepx_production_session as PS
        monkeypatch.setenv("AI_BRAIN_DIR", write_thesis(str(tmp_path), "QQQ"))
        monkeypatch.setenv("SCAN_SYMBOL", "MNQ")
        monkeypatch.setenv("TOPSTEPX_ACCOUNT_FINGERPRINT", "acct:test")
        out = PS.check_startup(self.session(), armed=False, mission_id="",
                               provider="topstepx")
        assert not [r for r in out if r.startswith("FOREIGN_THESIS_STATE")]

    def test_telemetry_reports_persistence_health_without_secrets(self, tmp_path,
                                                                  monkeypatch):
        from tools import topstepx_production_session as PS
        monkeypatch.setenv("AI_BRAIN_DIR", write_thesis(str(tmp_path), "QQQ"))
        t = PS.persistence_telemetry(symbol="MNQ")
        assert t["vector_records"] == 0
        assert "quarantined" in t["foreign_thesis"]
        assert "acct:" not in json.dumps(t)


class TestNoMemoryWasAuthored:

    def test_the_retrieval_corpus_is_still_empty(self):
        assert vector_store.count() == 0

    def test_no_retrospective_august_6_record_exists(self):
        for rec in vector_store.load_records():
            mc = rec.get("market_context") or {}
            assert not str(mc.get("timestamp", "")).startswith("2026-08-06")

    def test_this_mission_added_no_memory_writer(self):
        import ast
        for rel in (os.path.join("src", "broker", "topstepx_production_loop.py"),
                    os.path.join("src", "live_scan", "production_scan_cycle.py")):
            src = open(rel, encoding="utf-8").read()
            calls = {getattr(n.func, "attr", "") for n in ast.walk(ast.parse(src))
                     if isinstance(n, ast.Call)}
            assert "add_record" not in calls and "add_records" not in calls


QUARANTINE_DIR = os.path.join("data", "replay_sessions", "_quarantine",
                              "retired_instrument", "QQQ")
ARCHIVED_THESIS = os.path.join(QUARANTINE_DIR,
                               "active_thesis_TH_942090b5acb7_20260615.json")
# Recorded before the move; the archived bytes must still hash to this.
SOURCE_SHA256 = "731218aa8d219af12f2b6250bc8f87851dc6c7f41b19a81349190791fa5b1d67"


class TestRetiredQqqThesisArchived:
    """ARCHIVE-RETIRED-QQQ-ACTIVE-THESIS (2026-08-06).

    The stale QQQ thesis was already unreachable, but leaving a retired-instrument
    record at the canonical active-state path is needless ambiguity. It was moved,
    not deleted, and not relabelled.
    """

    def test_the_canonical_active_path_is_absent(self):
        assert not os.path.exists(os.path.join("data", "ai_brain", "active_thesis.json"))

    def test_no_placeholder_was_created(self):
        """Absence must mean 'no active thesis', not an invented empty one."""
        live = os.path.join("data", "ai_brain", "active_thesis.json")
        assert not os.path.exists(live)

    @pytest.mark.skipif(not os.path.exists(ARCHIVED_THESIS),
                        reason="quarantine is git-ignored; not present in a fresh clone")
    def test_the_archived_thesis_exists_and_matches_the_recorded_hash(self):
        import hashlib
        got = hashlib.sha256(open(ARCHIVED_THESIS, "rb").read()).hexdigest()
        assert got == SOURCE_SHA256

    @pytest.mark.skipif(not os.path.exists(ARCHIVED_THESIS), reason="ignored archive")
    def test_the_archived_record_was_not_relabelled(self):
        raw = json.load(open(ARCHIVED_THESIS, encoding="utf-8"))
        assert raw["symbol"] == "QQQ"
        assert raw["active"]["thesis_id"] == "TH_942090b5acb7"
        assert raw["active"]["created_at"].startswith("2026-06-15")

    def test_the_mnq_loader_returns_no_active_thesis(self, tmp_path, monkeypatch):
        monkeypatch.setenv("AI_BRAIN_DIR", os.path.join("data", "ai_brain"))
        eng = ThesisLifecycleEngine(symbol="MNQ")
        assert eng._active is None
        assert eng.quarantined is None      # nothing foreign left to quarantine

    def test_no_production_path_resolves_into_the_quarantine(self, monkeypatch):
        from ai_brain.thesis_lifecycle import _active_path, _archive_path
        from ai_retrieval import vector_store
        monkeypatch.setenv("AI_BRAIN_DIR", os.path.join("data", "ai_brain"))
        monkeypatch.setenv("AI_RETRIEVAL_DIR", os.path.join("data", "ai_retrieval"))
        for path in (_active_path(), _archive_path("2026-08-07T00:00:00"),
                     vector_store._store_path()):
            assert "_quarantine" not in path

    def test_no_production_module_references_the_quarantine_directory(self):
        import subprocess
        r = subprocess.run(["grep", "-rn", "replay_sessions", "--include=*.py",
                            "src", "tools"], capture_output=True, text=True)
        offenders = [l for l in r.stdout.splitlines()
                     if "_quarantine" in l or "retired_instrument" in l]
        # the launcher may NAME the directory for telemetry, but must not load it
        assert not [l for l in offenders if "open(" in l or "json.load" in l], offenders

    def test_a_future_qqq_thesis_at_the_active_path_is_still_rejected(self, tmp_path,
                                                                      monkeypatch):
        """The guard stays enforced; the move did not replace it."""
        monkeypatch.setenv("AI_BRAIN_DIR", write_thesis(str(tmp_path), "QQQ"))
        eng = ThesisLifecycleEngine(symbol="MNQ")
        assert eng._active is None
        assert eng.quarantined["reason"] == "foreign_instrument"

    def test_an_identity_less_thesis_is_still_rejected(self, tmp_path, monkeypatch):
        monkeypatch.setenv("AI_BRAIN_DIR", write_thesis(str(tmp_path), ""))
        eng = ThesisLifecycleEngine(symbol="MNQ")
        assert eng.quarantined["reason"] == "missing_instrument_identity"

    def test_the_archived_file_cannot_enter_retrieval(self):
        from doctrine.instrument_identity import retrieval_eligible
        if os.path.exists(ARCHIVED_THESIS):
            raw = json.load(open(ARCHIVED_THESIS, encoding="utf-8"))
            ok, why = retrieval_eligible({"symbol": raw["symbol"]})
            assert ok is False and "qqq" in why
        assert vector_store.count() == 0

    def test_no_replacement_mnq_thesis_was_created(self):
        journal = os.path.join("data", "ai_brain", "theses", "20260806_theses.jsonl")
        assert not os.path.exists(journal)
        assert not os.path.exists(os.path.join("data", "ai_brain", "active_thesis.json"))


class TestLegacyAuthorizationFailsClosed:
    """A pre-Terra authorization must refuse, not crash the armed startup."""

    def test_a_record_missing_brain_fields_does_not_raise_typeerror(self):
        from broker import topstepx_session_authorization as SA
        a = SA.SessionAuthorization(
            session_id="LEGACY", account_fingerprint="acct:x",
            contract_id="CON.F.US.MNQ.U26", session_date="20260806",
            decision_window="09:30-14:00 America/New_York", issued_at="t")
        a.brain_model = None
        a.brain_reasoning_effort = None
        a.brain_contract_fingerprint = None
        assert a.fingerprint().startswith("auth:")     # no TypeError

    def test_it_refuses_rather_than_exploding(self):
        from broker import topstepx_session_authorization as SA
        a = SA.SessionAuthorization(
            session_id="LEGACY", account_fingerprint="acct:x",
            contract_id="CON.F.US.MNQ.U26", session_date="20260806",
            decision_window="09:30-14:00 America/New_York", issued_at="t")
        a.authorization_fingerprint = "auth:staleplaceholder"
        a.brain_model = None
        with pytest.raises(SA.AuthorizationRefused):
            a.verify(account_fingerprint="acct:x",
                     contract_id="CON.F.US.MNQ.U26", session_date="20260806")


def _live_conftest():
    """The conftest module pytest actually LOADED.

    `import tests.conftest` creates a second module object whose _BEFORE is
    empty, so the guard's real recorded hashes are only visible through the
    plugin manager.
    """
    import sys
    for mod in list(sys.modules.values()):
        if getattr(mod, "__file__", None) and                 os.path.basename(mod.__file__) == "conftest.py" and                 getattr(mod, "_BEFORE", None):
            return mod
    raise AssertionError("the mutation guard did not record any baseline")


class TestArchiveMissionTouchedNoExecutionPath:
    """The move was a filesystem operation. No order endpoint became reachable."""

    def test_the_mission_process_is_not_an_armed_session(self):
        assert os.environ.get("PRODUCTION_ARMED_SESSION") is None

    def test_the_only_route_to_an_order_still_refuses_when_disarmed(self, tmp_path):
        from tests.test_production_scan_loop import build
        loop, _, sess, mission = build(tmp_path, armed=False)
        out = loop.scan_once()
        assert out["execution"] == "EXECUTION_DISARMED"
        assert sess.place_calls == 0            # no /api/Order/place
        assert mission.entry_attempt_count == 0  # no attempt burned

    def test_protected_files_are_unchanged_except_the_authorized_removal(self):
        """Item 11. The stale active thesis was removed ON PURPOSE.

        The mutation guard hashes it as `<absent>` at sessionstart and again at
        sessionfinish, so a consistent absence is not a false failure -- but the
        removal must be stated, not left to look like an accident.
        """
        conftest = _live_conftest()
        before, digest = conftest._BEFORE, conftest._digest
        active = os.path.join("data", "ai_brain", "active_thesis.json")
        assert active in conftest.PROTECTED
        assert before.get(active) == "<absent>"      # authorized removal
        for p in conftest.PROTECTED:
            if p == active:
                continue
            assert digest(p) == before.get(p), f"{p} mutated by the suite"

    def test_the_local_retrieval_corpus_remains_empty(self):
        assert vector_store.count() == 0
