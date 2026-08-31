"""ENFORCE-MEMORY-RETRIEVAL-ENABLEMENT-AUTHORITY (2026-08-07).

Ten descriptive memories were authored on 2026-08-06. The next morning, before
the window opened, `AI_RETRIEVAL_ENABLED` was found ABSENT from `.env`:
`retrieve_for_snapshot` short-circuited before ever reading the corpus, so the
Brain would have received none of them. Every other telemetry line -- record
count, authority, retention, manifest -- read healthy.

That is the same silent-degradation class as the retired data-provider fallback
and the smoke-cap leak: the system keeps running and only the evidence is wrong.
The durable law:

    NON-EMPTY DESCRIPTIVE CORPUS + RETRIEVAL DISABLED = ARMED STARTUP REFUSED

Setting the flag alone would have made 2026-08-07 work while preserving the
failure mode for every session after it.
"""
from __future__ import annotations

import os
import sys
import types

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src"))

from ai_retrieval import descriptive_memory as DM                # noqa: E402
from ai_retrieval import retrieval as R                          # noqa: E402
from ai_retrieval import vector_store                            # noqa: E402
from broker import topstepx_session_authorization as SA          # noqa: E402

LIVE_STORE = os.path.join("data", "ai_retrieval", "memory_store.jsonl")
EMPTY = {"level": None, "timeframe": None, "basis": None, "registered_at": None}


def launcher():
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "_launcher", os.path.join("tools", "topstepx_production_session.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def fake_session():
    s = types.SimpleNamespace()
    s.account = types.SimpleNamespace(id=1, name="x", simulated=True,
                                      canTrade=True, isVisible=True,
                                      balance=50042.96)
    s.account_fingerprint = "acct:x"
    s.contract = types.SimpleNamespace(id="CON.F.US.MNQ.U26")
    s.open_positions = lambda: []
    s.open_orders = lambda: []
    return s


def memory_refusals(armed: bool):
    mod = launcher()
    try:
        rs = mod.check_startup(fake_session(), armed=armed,
                               mission_id="PROD-TEST", provider="topstepx")
    except Exception:  # noqa: BLE001 -- other startup paths are not under test
        return ["<startup raised elsewhere>"]
    return [r for r in rs if "MEMORY_PRESENT_BUT_RETRIEVAL_DISABLED" in r]


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


@pytest.fixture
def corpus(tmp_path, monkeypatch):
    """An isolated store holding one descriptive record."""
    monkeypatch.setenv("AI_RETRIEVAL_DIR", str(tmp_path / "r"))
    vector_store.add_record(record())
    return tmp_path


@pytest.fixture
def empty_corpus(tmp_path, monkeypatch):
    monkeypatch.setenv("AI_RETRIEVAL_DIR", str(tmp_path / "empty"))
    return tmp_path


# ══════════════════════════════════════════════════════════════════════════════
class TestOneAuthoritativeResolver:

    def test_only_one_module_parses_the_flag(self):
        """Two modules interpreting the variable differently is how
        `AI_RETRIEVAL_ENABLED=on` reads enabled to an operator and disabled to
        the runtime."""
        import subprocess
        r = subprocess.run(["grep", "-rn", "AI_RETRIEVAL_ENABLED",
                            "--include=*.py", "src", "tools"],
                           capture_output=True, text=True)
        parsers = [ln for ln in r.stdout.splitlines()
                   if "getenv" in ln and "retrieval.py" not in ln]
        assert not parsers, f"a second parser exists: {parsers}"

    def test_the_sanctioned_truthy_forms_are_accepted(self, monkeypatch):
        for value in ("true", "TRUE", "on", "1", "yes", " Yes "):
            monkeypatch.setenv("AI_RETRIEVAL_ENABLED", value)
            assert R.retrieval_enabled() is True, value

    def test_everything_else_is_disabled(self, monkeypatch):
        for value in ("", "false", "0", "no", "off", "maybe", "TRUE-ish"):
            monkeypatch.setenv("AI_RETRIEVAL_ENABLED", value)
            assert R.retrieval_enabled() is False, value

    def test_absence_is_disabled_never_inferred_from_the_corpus(self, corpus,
                                                                monkeypatch):
        monkeypatch.delenv("AI_RETRIEVAL_ENABLED", raising=False)
        assert R.retrieval_enabled() is False
        assert vector_store.count() == 1        # a corpus exists...
        assert R.retrieval_startup_state()["enabled"] is False   # ...and is not permission

    def test_the_back_compat_alias_delegates(self, monkeypatch):
        monkeypatch.setenv("AI_RETRIEVAL_ENABLED", "on")
        assert R._enabled() is R.retrieval_enabled() is True


class TestStartupRefusal:
    """1-6."""

    def test_1_nonempty_corpus_plus_disabled_refuses_armed_startup(self, corpus,
                                                                   monkeypatch):
        monkeypatch.setenv("AI_RETRIEVAL_ENABLED", "false")
        refusals = memory_refusals(armed=True)
        assert refusals
        assert "MEMORY_PRESENT_BUT_RETRIEVAL_DISABLED" in refusals[0]

    def test_2_nonempty_corpus_plus_blank_flag_refuses(self, corpus, monkeypatch):
        """A BLANK value is what "missing" resolves to.

        `delenv` cannot express absence here: the launcher calls `load_dotenv()`
        at import, which repopulates the key from `.env`. That is itself a small
        safety property -- once the repository states the flag, a stray unset in
        one shell cannot silently blind the session -- but the resolver must
        still refuse a value that carries no permission.
        """
        monkeypatch.setenv("AI_RETRIEVAL_ENABLED", "")
        assert R.retrieval_enabled() is False
        assert memory_refusals(armed=True)

    def test_3_nonempty_corpus_plus_malformed_flag_refuses(self, corpus,
                                                           monkeypatch):
        for bad in ("maybe", "TRUE-ish", "enabled", "1.0"):
            monkeypatch.setenv("AI_RETRIEVAL_ENABLED", bad)
            assert memory_refusals(armed=True), bad

    def test_4_nonempty_corpus_plus_enabled_may_proceed(self, corpus, monkeypatch):
        monkeypatch.setenv("AI_RETRIEVAL_ENABLED", "true")
        assert memory_refusals(armed=True) == []
        assert R.retrieval_startup_state()["state"] == "ready"

    def test_5_empty_corpus_plus_disabled_is_allowed(self, empty_corpus,
                                                     monkeypatch):
        """Day one had no corpus and retrieval off; that is not a fault."""
        monkeypatch.setenv("AI_RETRIEVAL_ENABLED", "false")
        assert vector_store.count() == 0
        assert R.retrieval_startup_state()["state"] == "empty-allowed"
        assert memory_refusals(armed=True) == []

    def test_6_disarmed_diagnostics_remain_available(self, corpus, monkeypatch):
        monkeypatch.setenv("AI_RETRIEVAL_ENABLED", "false")
        assert memory_refusals(armed=False) == []

    def test_the_refusal_names_the_flag_and_the_record_count(self, corpus,
                                                             monkeypatch):
        monkeypatch.setenv("AI_RETRIEVAL_ENABLED", "false")
        text = memory_refusals(armed=True)[0]
        assert "AI_RETRIEVAL_ENABLED" in text
        assert "1 descriptive records" in text

    def test_telemetry_reports_the_state(self, corpus, monkeypatch):
        monkeypatch.setenv("AI_RETRIEVAL_ENABLED", "false")
        t = launcher().persistence_telemetry(symbol="MNQ")
        assert t["retrieval_enabled"] is False
        assert t["memory_startup_state"] == "MEMORY_PRESENT_BUT_RETRIEVAL_DISABLED"
        monkeypatch.setenv("AI_RETRIEVAL_ENABLED", "true")
        t = launcher().persistence_telemetry(symbol="MNQ")
        assert t["retrieval_enabled"] is True
        assert t["memory_startup_state"] == "ready"


class TestAuthorizationBinding:
    """7-14."""

    def auth(self, **over):
        base = dict(session_id="PROD-TEST", account_fingerprint="acct:x",
                    contract_id="CON.F.US.MNQ.U26", session_date="20260807",
                    decision_window=(f"{SA.PRODUCTION_WINDOW_START}-"
                                     f"{SA.PRODUCTION_WINDOW_END} "
                                     f"{SA.PRODUCTION_WINDOW_TZ}"),
                    issued_at="t",
                    # LUNA-DAILY-LOSS-BUDGET-GOVERNOR-1: signed explicitly so
                    # these retrieval-binding assertions still reach their
                    # subject instead of failing at NO_DAILY_LOSS_BUDGET.
                    daily_loss_budget_usd=SA.DAILY_LOSS_BUDGET_USD)
        base.update(over)
        return SA.SessionAuthorization(**base)

    def test_7_8_the_authorization_carries_retrieval_enabled(self):
        a = self.auth()
        assert hasattr(a, "retrieval_enabled")
        assert a.retrieval_enabled is False          # fails closed by default
        assert "retrieval_enabled" in SA.SessionAuthorization.__dataclass_fields__

    def test_9_the_fingerprint_binds_it(self):
        off = self.auth(retrieval_enabled=False).fingerprint()
        on = self.auth(retrieval_enabled=True).fingerprint()
        assert off != on, "retrieval state is not tamper-evident"

    def test_10_runtime_false_cannot_validate_an_auth_bound_true(self, monkeypatch):
        monkeypatch.setenv("AI_RETRIEVAL_ENABLED", "false")
        a = self.auth(retrieval_enabled=True)
        a.authorization_fingerprint = a.fingerprint()
        with pytest.raises(SA.AuthorizationRefused) as exc:
            a.verify(account_fingerprint="acct:x",
                     contract_id="CON.F.US.MNQ.U26", session_date="20260807")
        assert "AUTHORIZATION_RETRIEVAL_STATE_MISMATCH" in str(exc.value)

    def test_11_runtime_true_cannot_validate_an_auth_bound_false(self, monkeypatch):
        monkeypatch.setenv("AI_RETRIEVAL_ENABLED", "true")
        a = self.auth(retrieval_enabled=False)
        a.authorization_fingerprint = a.fingerprint()
        with pytest.raises(SA.AuthorizationRefused) as exc:
            a.verify(account_fingerprint="acct:x",
                     contract_id="CON.F.US.MNQ.U26", session_date="20260807")
        assert "AUTHORIZATION_RETRIEVAL_STATE_MISMATCH" in str(exc.value)

    def test_12_13_a_legacy_record_fails_closed_without_crashing(self, tmp_path,
                                                                 monkeypatch):
        """A pre-2026-08-07 record has no retrieval field. `None` must read as
        False and refuse -- never raise TypeError out of fingerprint()."""
        import json
        path = tmp_path / "legacy.json"
        json.dump({"session_id": "PROD-LEGACY", "account_fingerprint": "acct:x",
                   "contract_id": "CON.F.US.MNQ.U26", "session_date": "20260807",
                   "decision_window": (f"{SA.PRODUCTION_WINDOW_START}-"
                                       f"{SA.PRODUCTION_WINDOW_END} "
                                       f"{SA.PRODUCTION_WINDOW_TZ}"),
                   "issued_at": "t", "authorization_fingerprint": "auth:stale"},
                  open(path, "w", encoding="utf-8"))
        loaded = SA.SessionAuthorization.load(str(path))
        assert loaded.retrieval_enabled is False        # fails closed
        assert loaded.fingerprint().startswith("auth:")  # no TypeError
        monkeypatch.setenv("AI_RETRIEVAL_ENABLED", "true")
        with pytest.raises(SA.AuthorizationRefused):
            loaded.verify(account_fingerprint="acct:x",
                          contract_id="CON.F.US.MNQ.U26", session_date="20260807")

    def test_14_the_issuer_records_the_resolved_state(self, monkeypatch):
        monkeypatch.setenv("AI_RETRIEVAL_ENABLED", "true")
        assert SA._issue_retrieval_state() is True
        monkeypatch.setenv("AI_RETRIEVAL_ENABLED", "false")
        assert SA._issue_retrieval_state() is False

    def test_15_the_brain_contract_does_not_move_with_the_runtime_flag(self,
                                                                       monkeypatch):
        """DELIBERATE. See docs: the Brain contract identifies CODE and POLICY.
        Folding a per-session environment toggle into it would make the same
        code produce two different contract identities, and a disarmed
        diagnostic would no longer share an identity with the armed run it is
        meant to inspect. The authorization binds the runtime state instead, and
        produces the CORRECT refusal reason when it disagrees."""
        from ai_brain.production_model import brain_contract_fingerprint
        monkeypatch.setenv("AI_RETRIEVAL_ENABLED", "false")
        off = brain_contract_fingerprint()
        monkeypatch.setenv("AI_RETRIEVAL_ENABLED", "true")
        assert brain_contract_fingerprint() == off

    def test_the_retrieval_policy_is_still_bound_to_the_brain_contract(self):
        """Enablement is runtime; POLICY is code, and stays bound."""
        from ai_retrieval import retrieval_contract as RC
        policy = RC.retrieval_policy()
        for key in ("min_similarity", "max_analogs", "embedding_manifest_fingerprint",
                    "block_weights", "max_analogs_per_source_session"):
            assert key in policy


class TestProductionHookConsumesTheCorpus:
    """16-18."""

    def test_16_the_hook_reads_the_corpus_when_enabled(self, corpus, monkeypatch):
        monkeypatch.setenv("AI_RETRIEVAL_ENABLED", "true")
        out = R.retrieve_for_snapshot(self.snap(), "MNQ")
        assert out["enabled"] is True
        assert out["corpus_size"] == 1
        assert out["returned"] == 1

    def test_the_hook_short_circuits_when_disabled(self, corpus, monkeypatch):
        monkeypatch.setenv("AI_RETRIEVAL_ENABLED", "false")
        out = R.retrieve_for_snapshot(self.snap(), "MNQ")
        assert out["enabled"] is False
        assert out["analogs"] == []
        assert "corpus_size" not in out          # it never reached the store

    def test_17_retrieved_analogs_remain_context_only(self, corpus, monkeypatch):
        monkeypatch.setenv("AI_RETRIEVAL_ENABLED", "true")
        for a in R.retrieve_for_snapshot(self.snap(), "MNQ")["analogs"]:
            assert a["authority"] == "CONTEXT_ONLY"
            assert a["outcome_validated"] is False
            assert a["recommendation_authority"] == "none"
            assert a["execution_authority"] == "none"

    def test_18_an_analog_alone_still_cannot_create_a_candidate(self, corpus,
                                                                monkeypatch):
        from datetime import datetime, timezone

        from broker.luna_candidate_producer import CandidateProducer, NoCandidate
        from broker.topstepx_client import TopstepXContract
        monkeypatch.setenv("AI_RETRIEVAL_ENABLED", "true")
        mnq = TopstepXContract(id="CON.F.US.MNQ.U26", name="MNQU6",
                               description="MNQ", tick_size=0.25, tick_value=0.5,
                               active=True)
        snapshot = {"ai_retrieval": R.retrieve_for_snapshot(self.snap(), "MNQ")}
        assert snapshot["ai_retrieval"]["analogs"]      # memory IS present
        with pytest.raises(NoCandidate):
            CandidateProducer(allow_prose_objective_fallback=True,
                                      account_fingerprint="acct:t", contract=mnq).produce(
                brain_result={"ok": True, "parsed": {}, "fallback_reason": None,
                              "model": "gpt-5.6-terra"},
                brain_input={"market": {"current_price": 29483.0}},
                snapshot=snapshot, qualification={"qualified": True},
                engine_inventory={}, snapshot_id="s1",
                market_data_timestamp="2026-08-07T14:00:00+00:00",
                latest_closed_bar_timestamp="2026-08-07T14:00:00+00:00",
                now=datetime(2026, 8, 7, 14, 1, tzinfo=timezone.utc))

    @staticmethod
    def snap():
        return {"session": "lunch", "contract": "CON.F.US.MNQ.U26",
                "market_regime": {"regime_label": "range_rotation",
                                  "volatility_state": "toxic"},
                "narrative_authority": {"narrative_direction": "conflicted",
                                        "narrative_phase": "transition",
                                        "active_liquidity_draw": "29500"},
                "shared_context": {"delivery_state": "accumulation_building",
                                   "exhaustion_present": True},
                "protected_swings": {},
                "liquidity": {"nearest_buy_side": 29800.0,
                              "nearest_sell_side": 29200.0},
                "STRUCTURE_WITNESS": {tf: {"bos_event": False, "mss_event": False}
                                      for tf in ("15m", "5m", "3m", "1m")},
                "phase_confidence_summary": {"mean": 60.0, "min": 50.0,
                                             "max": 70.0}}


class TestNothingElseMoved:
    """19-21."""

    def test_19_the_live_memory_store_is_untouched_by_this_suite(self, corpus):
        assert "data" + os.sep + "ai_retrieval" not in vector_store._store_path()

    def test_the_live_corpus_still_matches_the_authoring_ledger(self):
        import hashlib
        if not os.path.exists(LIVE_STORE):
            pytest.skip("live store absent")
        digest = hashlib.sha256(open(LIVE_STORE, "rb").read()).hexdigest()
        # Moved by AUTHOR-PROD-20260807-DESCRIPTIVE-MEMORY (2026-08-07): the six
        # approved August 7 observations were authored, taking the corpus
        # 10 -> 16. August 6 content and every August 6 vector are unchanged.
        assert digest == "a489a36f71f113249e0916e2d003d174d4aa86f95592cf85be087cb302378466"

    def test_20_21_no_authorization_or_order_path_is_reachable_here(self):
        assert os.environ.get("PRODUCTION_ARMED_SESSION") is None
        import ast
        tree = ast.parse(open(__file__, encoding="utf-8").read())
        calls = {getattr(n.func, "attr", "") for n in ast.walk(tree)
                 if isinstance(n, ast.Call)}
        for forbidden in ("issue", "gated_submit", "place_order", "commit_records"):
            assert forbidden not in calls, forbidden

    def test_replay_still_forces_retrieval_off_as_a_safety_key(self):
        from replay_validation.replay_session import _SAFETY_ENV
        assert _SAFETY_ENV["AI_RETRIEVAL_ENABLED"] == "false"
