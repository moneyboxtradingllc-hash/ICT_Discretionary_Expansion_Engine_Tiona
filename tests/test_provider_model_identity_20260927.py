"""PROVIDER-MODEL-IDENTITY-1 — the model that ANSWERED must be the model we authorized.

Found in the GPT-6 Luna migration review (2026-09-25): `narrative_brain._call_llm`
set the Brain result's `model` to the REQUESTED name, and the provider's
`resp.model` reached only the AI call ledger. `production_model.model_matches()`
existed and had no caller on the live path. A response served by any other model
would have been parsed, validated and handed to the producer as gpt-6-luna's.

The owner's ruling: a response is sovereign only if the SERVED identity passes
`model_matches()`. A mismatch fails closed through the existing fallback path,
is recorded durably with both identities, is never repaired, and is never
retried on another model.

These tests drive the REAL `_call_llm` and `run_narrative_brain` through a stub
transport. No test contacts OpenAI.
"""
from __future__ import annotations

import json
import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))
sys.path.insert(0, os.path.join(ROOT, "tests"))

from ai_brain import ai_call_ledger as L                     # noqa: E402
from ai_brain import narrative_brain as nb                   # noqa: E402
from ai_brain.production_model import PRODUCTION_MODEL, model_matches  # noqa: E402

REQUESTED = "gpt-6-luna"
DATED = "gpt-6-luna-2026-09-22"

#: A schema-valid read, so the ONLY thing that can refuse it is identity.
GOOD = {"market_story": "a" * 80, "narrative_direction": "bearish",
        "narrative_phase": "distribution", "current_action": "stand_down",
        "dominant_reasoning": "b" * 120, "recommended_playbook_family": "none",
        "recommended_tool_family": ["none"], "invalidation_level": None,
        "phase_confidence": 60, "allowed_direction": "bearish",
        "reason": "r" * 40}


# ── a transport that serves a CHOSEN identity, whatever was requested ─────────
class _Resp:
    def __init__(self, content, served):
        self.choices = [type("C", (), {"message": type("M", (), {"content": content})()})()]
        self.usage = None
        self.id = "resp_1"
        if served is not _ABSENT:
            self.model = served


_ABSENT = object()


class _Raw:
    def __init__(self, resp):
        self._resp = resp
        self.headers = {"x-request-id": "req_served_1"}

    def parse(self):
        return self._resp


class ServingCompletions:
    """Counts every outbound transport and records what each one requested."""

    def __init__(self, served, content=None):
        self.served = served
        self.content = content or json.dumps(GOOD)
        self.requested_models = []
        outer = self

        class _WRR:
            def create(self, **kw):
                outer.requested_models.append(kw.get("model"))
                return _Raw(_Resp(outer.content, outer.served))
        self.with_raw_response = _WRR()

    @property
    def transport_calls(self):
        return len(self.requested_models)


@pytest.fixture
def brain(monkeypatch, tmp_path):
    import ai_layer.ai_api_adapter as adapter
    monkeypatch.setenv("OPENAI_API_KEY", "k")
    monkeypatch.setenv("AI_BRAIN_MODEL", REQUESTED)
    monkeypatch.setenv("AI_BRAIN_DIR", str(tmp_path))
    monkeypatch.setattr(adapter, "_OPENAI_AVAILABLE", True)

    def install(served, content=None):
        comp = ServingCompletions(served, content)
        chat = type("Chat", (), {"completions": comp})()
        client = type("Cl", (), {"__init__":
                                 lambda self, **kw: setattr(self, "chat", chat)})
        monkeypatch.setattr(adapter, "_openai", type("M", (), {"OpenAI": client}))
        return comp
    return install


def ledger_rows():
    """Every row in this test's private ledger dir, whatever session scoped it.

    The file name carries the process-wide call context's session id, which
    other tests in the suite may have set; reading the whole temp directory
    keeps these assertions independent of test order.
    """
    import glob
    rows = []
    for path in sorted(glob.glob(os.path.join(L.ledger_dir(), "ai_calls_*.jsonl"))):
        rows.extend(L.load(path=path))
    return rows


# ══════════════════════════════════════════════════════════════════════════════
class TestTheProductionModelIsUnchanged:

    def test_production_is_still_gpt_6_luna(self):
        assert PRODUCTION_MODEL == REQUESTED

    @pytest.mark.parametrize("served, ok", [
        (REQUESTED, True), (DATED, True),
        ("gpt-5.6-luna", False), ("gpt-6-sol", False), ("gpt-6-astra", False),
        ("some-unknown-model", False), ("", False), (None, False)])
    def test_model_matches_behaviour_is_preserved(self, served, ok):
        assert model_matches(served, REQUESTED) is ok


class TestAMatchingServedModelIsSovereign:

    def test_exact_served_identity_is_allowed(self, brain):
        c = brain(REQUESTED)
        out = nb._call_llm({"timestamp": "t"})
        assert out["ok"] is True and out["parsed"] is not None
        assert out["fallback_reason"] is None
        assert out["model"] == REQUESTED
        assert out["model_requested"] == REQUESTED
        assert out["model_returned"] == REQUESTED
        assert c.transport_calls == 1

    def test_a_dated_served_identity_is_allowed_and_reported_verbatim(self, brain):
        brain(DATED)
        out = nb._call_llm({"timestamp": "t"})
        assert out["ok"] is True and out["fallback_reason"] is None
        assert out["model"] == DATED, "the author is the SERVED model, not rewritten"
        assert out["model_requested"] == REQUESTED


class TestAMismatchedServedModelFailsClosed:

    @pytest.mark.parametrize("served", ["gpt-5.6-luna", "gpt-6-sol",
                                        "some-unknown-model"])
    def test_refused_before_it_can_become_a_read(self, brain, served):
        brain(served)
        out = nb._call_llm({"timestamp": "t"})
        assert out["ok"] is False
        assert out["parsed"] is None, "content from the wrong model was parsed"
        assert out["fallback_reason"] == (
            f"provider_model_mismatch:requested={REQUESTED}:returned={served}")

    def test_a_response_that_names_no_model_is_refused(self, brain):
        brain(_ABSENT)
        out = nb._call_llm({"timestamp": "t"})
        assert out["ok"] is False and out["parsed"] is None
        assert out["fallback_reason"] == (
            f"provider_model_mismatch:requested={REQUESTED}:returned=absent")

    def test_the_result_never_claims_the_requested_model_authored_it(self, brain):
        brain("gpt-5.6-luna")
        out = nb._call_llm({"timestamp": "t"})
        assert out["model"] is None, "no sovereign author for a mismatched response"
        assert out["model_requested"] == REQUESTED
        assert out["model_returned"] == "gpt-5.6-luna"


class TestTheLedgerKeepsBothFacts:

    def test_a_match_is_recorded_ok_with_both_identities(self, brain):
        brain(DATED)
        nb._call_llm({"timestamp": "t"})
        row = ledger_rows()[-1]
        assert row["model_requested"] == REQUESTED
        assert row["model_returned"] == DATED
        assert row["ok"] is True and row["fallback_reason"] is None
        assert row["request_id"] == "req_served_1"

    def test_a_mismatch_is_recorded_truthfully(self, brain):
        brain("gpt-6-sol")
        nb._call_llm({"timestamp": "t"})
        rows = ledger_rows()
        assert len(rows) == 1, "one response, one row"
        row = rows[0]
        assert row["model_requested"] == REQUESTED
        assert row["model_returned"] == "gpt-6-sol", "the provider's string is not rewritten"
        assert row["ok"] is False
        assert row["fallback_reason"].startswith("provider_model_mismatch:")
        assert row["request_id"] == "req_served_1"


class TestNoRecoveryToAnotherModel:
    """End to end through the real orchestrator."""

    @pytest.fixture
    def snapshot(self):
        from test_phase_ai_brain_llm import _snap
        return _snap()

    @staticmethod
    def full_read():
        """A complete, deep read, so nothing but identity can refuse it."""
        from test_phase_ai_brain_llm import _GOOD_LLM
        return json.dumps(_GOOD_LLM)

    @staticmethod
    def run(snapshot):
        from ai_brain.stance_memory import StanceMemory
        return nb.run_narrative_brain(snapshot, "MNQ", StanceMemory(persist=False))

    @pytest.fixture
    def on(self, monkeypatch):
        monkeypatch.setenv("AI_BRAIN_ENABLED", "true")
        monkeypatch.setenv("AI_BRAIN_LLM", "true")

    def test_a_mismatch_takes_the_explicit_fallback_with_one_request(
            self, brain, on, snapshot):
        c = brain("gpt-5.6-luna", content=self.full_read())
        res = self.run(snapshot)
        assert c.transport_calls == 1, "a mismatch was retried or repaired"
        assert c.requested_models == [REQUESTED], "a request went to another model"
        assert res["source"] == "llm_failed_fallback"
        assert str(res["fallback_reason"]).startswith("provider_model_mismatch:")
        assert res["llm_model"] is None
        assert res["llm_model_requested"] == REQUESTED
        assert res["llm_model_returned"] == "gpt-5.6-luna"

    def test_a_matching_response_is_still_the_live_read(self, brain, on, snapshot):
        c = brain(REQUESTED, content=self.full_read())
        res = self.run(snapshot)
        assert res["fallback_reason"] is None
        assert res["source"] == "llm"
        assert res["llm_model"] == REQUESTED
        assert set(c.requested_models) == {REQUESTED}


def produce_with(**brain_result_fields):
    """The producer's own test harness, with only the Brain result varied."""
    from test_luna_candidate_producer import produce, result
    return produce(res=result(**brain_result_fields))


class TestCandidateAuthorityDownstream:
    """A mismatch cannot become a candidate; a dated match is not refused."""

    def test_the_producer_refuses_a_mismatch_before_candidate_authority(self):
        from broker.luna_candidate_producer import NoCandidate
        with pytest.raises(NoCandidate) as exc:
            produce_with(ok=False, parsed=None, model=None,
                         fallback_reason=(f"provider_model_mismatch:requested="
                                          f"{REQUESTED}:returned=gpt-5.6-luna"))
        assert exc.value.reason == "fallback_not_authoritative"

    def test_the_producer_still_refuses_another_family(self):
        from broker.luna_candidate_producer import NoCandidate
        with pytest.raises(NoCandidate) as exc:
            produce_with(model="gpt-5.6-luna")
        assert exc.value.reason == "wrong_model"

    def test_the_producer_accepts_a_dated_served_identity(self):
        cand = produce_with(model=DATED)
        assert cand is not None

    def test_the_runner_accepts_a_dated_served_identity(self):
        from test_topstepx_execution_runner import TestCandidateIntake, _candidate
        import broker.topstepx_execution_runner as R
        r = TestCandidateIntake().armed()
        r.accept_candidate(_candidate(
            brain_result={"ok": True, "fallback_reason": None, "model": DATED}))
        assert r.state == R.CANDIDATE_VALIDATED

    def test_the_runner_still_refuses_another_family(self):
        from test_topstepx_execution_runner import TestCandidateIntake, _candidate
        import broker.topstepx_execution_runner as R
        r = TestCandidateIntake().armed()
        with pytest.raises(R.RunnerHalt) as exc:
            r.accept_candidate(_candidate(
                brain_result={"ok": True, "fallback_reason": None,
                              "model": "gpt-5.6-luna"}))
        assert exc.value.state == R.AI_FALLBACK
