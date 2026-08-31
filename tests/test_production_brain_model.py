"""UPGRADE-PRODUCTION-BRAIN-TO-GPT-5.6-TERRA (2026-08-06).

The production Brain moves Luna -> Terra. One variable changes: the model.
Risk, sizing, window, trade caps, stop/target doctrine, CandidateProducer
eligibility and prompt semantics are untouched.

The migration's real hazard was not Terra -- it was how the model was resolved.
`AI_BRAIN_MODEL` fell through `AI_MODEL` to `gpt-4o-mini`, and `AI_MODEL=gpt-4o-mini`
is actually set in this deployment. A missing or mistyped model would have run an
armed session on a far weaker Brain while telemetry still named the intended one.
"""
from __future__ import annotations

import json
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src"))

from ai_brain import narrative_brain as NB                          # noqa: E402
from ai_brain import production_model as PM                         # noqa: E402
from ai_brain.brain_schema import empty_brain_output                # noqa: E402
from broker import topstepx_session_authorization as SA             # noqa: E402
from broker.luna_candidate_producer import CandidateProducer, NoCandidate  # noqa: E402
from broker.topstepx_client import TopstepXContract                 # noqa: E402
from live_scan.production_scan_cycle import ProductionScanCycle     # noqa: E402

MNQ = TopstepXContract(id="CON.F.US.MNQ.U26", name="MNQU6", description="MNQ",
                       tick_size=0.25, tick_value=0.5, active=True)


@pytest.fixture(autouse=True)
def clean_env(monkeypatch):
    monkeypatch.delenv("PRODUCTION_ARMED_SESSION", raising=False)
    yield


# ══════════════════════════════════════════════════════════════════════════════
class TestModelResolution:

    def test_luna_is_the_production_model(self):
        """PRAC-MODEL-RULING (2026-08-19, operator): Luna for PRAC validation.

        These tests previously encoded "Terra is doctrine". The DOCTRINE moved,
        not the invariant: there is exactly one production model, its predecessor
        is named, and everything else is refused. Terra is RESERVED for the
        Combine phase -- nothing about its integration failed. The measured
        reason is cost: 739,891 tokens across 29 scans in 39 minutes on
        2026-08-19, all stand_downs.
        """
        assert PM.PRODUCTION_MODEL == "gpt-5.6-luna"
        assert PM.PREVIOUS_PRODUCTION_MODEL == "gpt-5.6-terra"

    def test_the_exact_luna_id_resolves_when_armed(self, monkeypatch):
        monkeypatch.setenv("AI_BRAIN_MODEL", "gpt-5.6-luna")
        assert PM.resolve_model(armed=True) == "gpt-5.6-luna"

    def test_armed_refuses_when_the_model_is_absent(self, monkeypatch):
        monkeypatch.delenv("AI_BRAIN_MODEL", raising=False)
        monkeypatch.setenv("AI_MODEL", "gpt-4o-mini")
        with pytest.raises(PM.ModelResolutionError, match="NO_BRAIN_MODEL"):
            PM.resolve_model(armed=True)

    def test_armed_refuses_terra_while_luna_is_the_prac_doctrine(self, monkeypatch):
        """Terra is reserved, not deprecated -- and still refused by default.

        It returns for the Combine phase through a deliberate ruling and its own
        fresh authorization, never as a config toggle left lying around.
        """
        monkeypatch.setenv("AI_BRAIN_MODEL", "gpt-5.6-terra")
        with pytest.raises(PM.ModelResolutionError, match="reserved for the Combine"):
            PM.resolve_model(armed=True)

    def test_armed_refuses_the_unsuffixed_alias(self, monkeypatch):
        """`gpt-5.6` routes to Sol, not Terra."""
        monkeypatch.setenv("AI_BRAIN_MODEL", "gpt-5.6")
        with pytest.raises(PM.ModelResolutionError, match="routes to gpt-5.6-sol"):
            PM.resolve_model(armed=True)

    @pytest.mark.parametrize("bad", ["gpt-5.6-sol", "gpt-4o-mini", "claude-3", "terra"])
    def test_armed_refuses_any_other_model(self, monkeypatch, bad):
        monkeypatch.setenv("AI_BRAIN_MODEL", bad)
        with pytest.raises(PM.ModelResolutionError):
            PM.resolve_model(armed=True)

    def test_disarmed_diagnostics_remain_usable(self, monkeypatch):
        monkeypatch.delenv("AI_BRAIN_MODEL", raising=False)
        assert PM.resolve_model(armed=False) == PM.PRODUCTION_MODEL

    def test_the_legacy_fallback_chain_is_gone(self):
        import inspect
        # Checked on the CALL, not on prose: the comment explaining the old
        # chain legitimately names gpt-4o-mini.
        import ast
        import textwrap
        tree = ast.parse(textwrap.dedent(inspect.getsource(NB._call_llm)))
        calls = [ast.unparse(n) for n in ast.walk(tree) if isinstance(n, ast.Call)]
        assert not [c for c in calls if "AI_BRAIN_MODEL" in c and "getenv" in c]
        assert any("resolve_model" in c for c in calls)


class TestModelIdentityMatching:

    @pytest.mark.parametrize("returned", ["gpt-5.6-luna", "gpt-5.6-luna-2026-07-01"])
    def test_the_production_model_and_its_dated_variants_match(self, returned):
        assert PM.model_matches(returned) is True

    @pytest.mark.parametrize("returned", ["gpt-5.6-terra", "gpt-5.6-sol", "gpt-4o-mini", ""])
    def test_a_different_family_does_not_match(self, returned):
        assert PM.model_matches(returned) is False

    def test_a_model_identity_mismatch_is_not_sovereign(self):
        """If the API served something else, the read is not the authorized Brain."""
        block = {"source": "llm", "output": {"narrative_direction": "bullish"},
                 "fallback_reason": None}
        assert ProductionScanCycle.is_sovereign(block) is True     # source-level
        assert PM.model_matches("gpt-5.6-terra") is False          # identity-level
        # the two together are what production requires
        assert not (ProductionScanCycle.is_sovereign(block)
                    and PM.model_matches("gpt-5.6-terra"))


class TestReasoningConfigUnchanged:

    def test_no_reasoning_effort_is_configured(self, monkeypatch):
        monkeypatch.delenv("AI_BRAIN_REASONING_EFFORT", raising=False)
        assert PM.reasoning_effort() is None

    def test_an_explicit_effort_is_reported_when_set(self, monkeypatch):
        monkeypatch.setenv("AI_BRAIN_REASONING_EFFORT", "high")
        assert PM.reasoning_effort() == "high"

    def test_the_request_sets_no_sampling_controls(self):
        """One variable changes in this migration: the model."""
        import inspect
        src = inspect.getsource(NB._call_llm)
        for banned in ("temperature", "top_p", "max_tokens", "max_completion_tokens"):
            assert banned not in src

    def test_json_mode_is_still_sent(self):
        import inspect
        src = inspect.getsource(NB._call_llm)
        assert "json_object" in src and "json_mode_enabled" in src


class TestBrainContractFingerprint:

    def test_it_is_deterministic(self):
        assert PM.brain_contract_fingerprint() == PM.brain_contract_fingerprint()

    def test_it_carries_no_secret(self):
        fp = PM.brain_contract_fingerprint()
        assert fp.startswith("brain:") and len(fp) == 22

    def test_it_covers_prompt_schema_and_validator(self):
        import inspect
        src = inspect.getsource(PM)
        for part in ("brain_prompt.py", "brain_schema.py", "brain_validation.py"):
            assert part in src


class TestAuthorizationBindsTheBrain:

    def auth(self, **over):
        kw = dict(session_id="S", account_fingerprint="acct:x",
                  contract_id="CON.F.US.MNQ.U26", session_date="20260807",
                  # PRE-NY-EXECUTION-WINDOW-1: the canonical window moved to
                  # 09:00. `verify()` fail-closes on a record minted under a
                  # different doctrine, so the old literal stopped being a
                  # MATCHING authorization -- which is this test's whole subject.
                  decision_window="09:00-14:00 America/New_York", issued_at="t",
                  brain_model=PM.PRODUCTION_MODEL,
                  brain_reasoning_effort=PM.reasoning_effort() or "",
                  brain_contract_fingerprint=PM.brain_contract_fingerprint(),
                  # RESOLVED, NOT DEFAULTED. Every other binding above already
                  # mirrors production `issue()`; retrieval was the one left to
                  # take the dataclass default, and `verify()` fail-closes when
                  # it disagrees with the runtime. `.env` sets
                  # AI_RETRIEVAL_ENABLED=true, so ANY sibling test that calls
                  # load_dotenv() leaks it process-wide and a literal `False`
                  # here would decide these assertions on test ORDER rather
                  # than on their subject. Resolving through the same canonical
                  # source weakens nothing: verify() still enforces the
                  # retrieval binding, and the tests that exercise a MISMATCH
                  # pass it explicitly via `over`.
                  retrieval_enabled=SA._issue_retrieval_state(),
                  # LUNA-DAILY-LOSS-BUDGET-GOVERNOR-1: an authorization meant
                  # to VERIFY must now sign the session loss budget. The
                  # sentinel is None by design, so it is supplied explicitly
                  # rather than defaulted; this test's subject is unchanged.
                  daily_loss_budget_usd=SA.DAILY_LOSS_BUDGET_USD)
        kw.update(over)
        a = SA.SessionAuthorization(**kw)
        a.authorization_fingerprint = a.fingerprint()
        return a

    def test_the_fingerprint_changes_with_the_model(self):
        assert self.auth().fingerprint() != self.auth(brain_model="gpt-5.6-terra").fingerprint()

    def test_the_fingerprint_changes_with_reasoning_effort(self):
        assert self.auth().fingerprint() != self.auth(brain_reasoning_effort="high").fingerprint()

    def test_the_fingerprint_changes_with_the_brain_contract(self):
        assert self.auth().fingerprint() != self.auth(
            brain_contract_fingerprint="brain:0000000000000000").fingerprint()

    def test_the_fingerprint_changes_with_the_json_mode_requirement(self):
        assert self.auth().fingerprint() != self.auth(json_mode_required=False).fingerprint()

    def test_an_authorization_issued_for_the_other_tier_cannot_arm_this_one(self):
        a = self.auth(brain_model="gpt-5.6-terra")
        with pytest.raises(SA.AuthorizationRefused, match="BRAIN_MODEL_MISMATCH"):
            a.verify(account_fingerprint="acct:x", contract_id="CON.F.US.MNQ.U26",
                     session_date="20260807")

    def test_an_authorization_issued_for_the_production_tier_cannot_arm_sol(self, monkeypatch):
        a = self.auth()
        monkeypatch.setattr(PM, "PRODUCTION_MODEL", "gpt-5.6-sol")
        with pytest.raises(SA.AuthorizationRefused, match="BRAIN_MODEL_MISMATCH"):
            a.verify(account_fingerprint="acct:x", contract_id="CON.F.US.MNQ.U26",
                     session_date="20260807")

    def test_a_changed_brain_contract_invalidates_the_authorization(self, monkeypatch):
        a = self.auth()
        monkeypatch.setattr(PM, "brain_contract_fingerprint",
                            lambda: "brain:ffffffffffffffff")
        with pytest.raises(SA.AuthorizationRefused, match="BRAIN_CONTRACT_CHANGED"):
            a.verify(account_fingerprint="acct:x", contract_id="CON.F.US.MNQ.U26",
                     session_date="20260807")

    def test_a_changed_reasoning_effort_invalidates_the_authorization(self, monkeypatch):
        a = self.auth()
        monkeypatch.setenv("AI_BRAIN_REASONING_EFFORT", "high")
        with pytest.raises(SA.AuthorizationRefused, match="REASONING_EFFORT_MISMATCH"):
            a.verify(account_fingerprint="acct:x", contract_id="CON.F.US.MNQ.U26",
                     session_date="20260807")

    def test_a_matching_authorization_still_verifies(self):
        self.auth().verify(account_fingerprint="acct:x",
                           contract_id="CON.F.US.MNQ.U26", session_date="20260807")

    def test_the_issuer_resolves_brain_terms_from_code(self):
        import ast
        import inspect
        import textwrap
        tree = ast.parse(textwrap.dedent(inspect.getsource(SA.issue)))
        src = ast.unparse(tree)
        assert "PM.PRODUCTION_MODEL" in src
        assert "PM.brain_contract_fingerprint()" in src


class TestSafetyRepairsPreserved:
    """Terra must not weaken a single August 6 repair."""

    def output(self, **over):
        o = empty_brain_output()
        o.update({"narrative_direction": "bearish", "allowed_direction": "bearish",
                  "current_action": "stand_down", "recommended_playbook_family": "none",
                  "recommended_tool_family": ["none"], "invalidation_level": None})
        o.update(over)
        return o

    def test_json_mode_predicate_survives(self, monkeypatch):
        monkeypatch.setenv("BRAIN_JSON_MODE", "on")
        assert NB.json_mode_enabled() is True
        monkeypatch.setenv("BRAIN_JSON_MODE", "off")
        assert NB.json_mode_enabled() is False

    def test_tool_family_container_normalization_survives(self):
        from ai_brain.brain_validation import normalize_tool_family_container
        assert normalize_tool_family_container("fvg")[0] == ["fvg"]
        assert normalize_tool_family_container("made_up")[0] == "made_up"

    def test_direction_and_action_remain_separate(self):
        o = self.output()
        assert o["narrative_direction"] == "bearish"
        assert o["current_action"] == "stand_down"

    def test_a_directional_stand_down_produces_no_candidate(self):
        with pytest.raises(NoCandidate) as e:
            CandidateProducer(allow_prose_objective_fallback=True,
                                      account_fingerprint="acct:x", contract=MNQ).produce(
                brain_result={"ok": True, "parsed": self.output(), "fallback_reason": None,
                              "model": PM.PRODUCTION_MODEL},
                brain_input={"timestamp": "t", "market": {"current_price": 29500.0},
                             "liquidity": {}, "protected_swings": {}},
                snapshot={}, qualification={"qualified": True},
                engine_inventory={}, snapshot_id="s",
                market_data_timestamp="t", latest_closed_bar_timestamp="t")
        assert e.value.reason == "action_declines_entry"

    def test_a_deterministic_fallback_is_never_sovereign(self):
        assert ProductionScanCycle.is_sovereign(
            {"source": "deterministic", "output": self.output()}) is False

    def test_degraded_reason_is_still_emitted(self):
        assert NB.degraded_reason("degraded", {}) == "non_sovereign_source:degraded"


class TestEvaluationCannotTrade:

    def test_the_evaluation_output_is_labelled_counterfactual(self):
        d = "data/replay_sessions/_terra_eval"
        if not os.path.isdir(d):
            pytest.skip("evaluation directory is local and ignored")
        rows = os.path.join(d, "terra_eval_rows.json")
        if os.path.exists(rows):
            assert "COUNTERFACTUAL" in json.load(open(rows, encoding="utf-8"))["label"]

    def test_the_producer_module_reaches_no_order_endpoint(self):
        import ast
        src = open(os.path.join("src", "broker", "luna_candidate_producer.py"),
                   encoding="utf-8").read()
        calls = {getattr(n.func, "attr", "") for n in ast.walk(ast.parse(src))
                 if isinstance(n, ast.Call)}
        for banned in ("place_order", "gated_submit", "consume_attempt", "close_position"):
            assert banned not in calls
