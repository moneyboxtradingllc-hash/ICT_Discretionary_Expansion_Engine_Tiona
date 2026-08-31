"""PRAC-RELEASE-1 — the practice lane is eligible, or it names why it is not.

Two properties matter more than the gate list itself:

  * the Combine cannot be reached by accident. It is refused by IDENTITY, not
    by convention, and there is no fall-through from PRAC to it; and
  * nothing here arms. `arm_eligible` is a REPORT, only FINAL can produce it,
    and arming stays an explicit separate operator action.

The evaluator is pure, so every gate is testable without a market.
"""
from __future__ import annotations

import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src"))

from operational_readiness import prac_release as PR             # noqa: E402


def _facts(**over):
    facts = {
        "tracked_source_clean": True, "dirty_tracked_files": [],
        "brain_fingerprint": "brain:deadbeefdeadbeef",
        "account_id": PR.PRAC_ACCOUNT_ID,
        "account_fingerprint": PR.PRAC_ACCOUNT_FINGERPRINT,
        "simulated": True, "can_trade": True, "is_visible": True,
        "contract_id": "CON.F.US.MNQ.U26",
        "open_positions": 0, "bot_working_orders": 0, "foreign_working_orders": 0,
        "protection": {"authorized": True, "reasons": []},
        "doctrine": {"max_risk_usd": 350.0, "max_contracts": 15,
                     "preferred_stop_points": 35.0, "absolute_stop_points": 50.0,
                     "min_reward_to_risk": 1.0},
        "production_bracketless": False,
        "brain_enabled": True, "model": PR.expected_model(), "provider_calls": 0,
        "session_authorization_valid": True,
    }
    facts.update(over)
    return facts


def _failed(report):
    return {g["gate"] for g in report["failed"]}


class TestPrepMode:
    def test_a_healthy_prep_passes_without_an_authorization(self):
        r = PR.evaluate(_facts(session_authorization_valid=False), mode=PR.PREP)
        assert r["failed"] == []
        assert r["prep_complete"] is True

    def test_prep_can_never_report_arm_eligible(self):
        r = PR.evaluate(_facts(), mode=PR.PREP)
        assert r["arm_eligible"] is False

    def test_prep_states_the_authorization_is_deferred_not_missing(self):
        r = PR.evaluate(_facts(session_authorization_valid=False), mode=PR.PREP)
        gate = [g for g in r["gates"] if g["gate"] == "session_authorization_deferred"][0]
        assert "NOT ISSUED" in gate["detail"]


class TestFinalMode:
    def test_a_healthy_final_is_arm_eligible(self):
        r = PR.evaluate(_facts(), mode=PR.FINAL)
        assert r["failed"] == []
        assert r["arm_eligible"] is True

    def test_final_refuses_without_todays_authorization(self):
        r = PR.evaluate(_facts(session_authorization_valid=False), mode=PR.FINAL)
        assert "session_authorization" in _failed(r)
        assert r["arm_eligible"] is False

    def test_eligibility_is_a_report_not_an_action(self):
        r = PR.evaluate(_facts(), mode=PR.FINAL)
        assert r["arming_is_a_separate_operator_action"] is True


class TestTheCombineIsUnreachable:
    def test_the_combine_id_is_refused_by_identity(self):
        r = PR.evaluate(_facts(account_id=22222222,
                               account_fingerprint="acct:bbbbbbbbbbbb"), mode=PR.FINAL)
        assert "not_a_forbidden_account" in _failed(r)
        assert "account_is_prac" in _failed(r)
        assert r["arm_eligible"] is False

    def test_the_retired_account_is_refused_by_identity(self):
        r = PR.evaluate(_facts(account_id=33333333,
                               account_fingerprint="acct:cccccccccccc"), mode=PR.FINAL)
        assert "not_a_forbidden_account" in _failed(r)

    def test_the_refusal_names_which_account_it_was(self):
        r = PR.evaluate(_facts(account_id=22222222), mode=PR.FINAL)
        gate = [g for g in r["gates"] if g["gate"] == "not_a_forbidden_account"][0]
        assert "COMBINE_ACCOUNT" in gate["detail"]

    def test_a_prac_id_with_a_retired_fingerprint_is_refused(self):
        r = PR.evaluate(_facts(account_fingerprint="acct:cccccccccccc"), mode=PR.FINAL)
        assert "account_fingerprint_is_prac" in _failed(r)
        assert "not_a_forbidden_account" in _failed(r)

    def test_a_combine_id_with_a_prac_fingerprint_is_refused(self):
        r = PR.evaluate(_facts(account_id=22222222), mode=PR.FINAL)
        assert "account_is_prac" in _failed(r)


class TestAccountState:
    @pytest.mark.parametrize("field,gate", [
        ("simulated", "account_simulated"),
        ("can_trade", "account_can_trade"),
        ("is_visible", "account_visible"),
    ])
    def test_a_false_account_flag_is_refused(self, field, gate):
        assert gate in _failed(PR.evaluate(_facts(**{field: False}), mode=PR.FINAL))

    def test_an_open_position_is_refused(self):
        assert "flat" in _failed(PR.evaluate(_facts(open_positions=1), mode=PR.FINAL))

    def test_a_bot_working_order_is_refused(self):
        assert "no_bot_working_orders" in _failed(
            PR.evaluate(_facts(bot_working_orders=2), mode=PR.FINAL))

    def test_foreign_orders_are_reported_not_silently_absorbed(self):
        r = PR.evaluate(_facts(foreign_working_orders=3), mode=PR.FINAL)
        gate = [g for g in r["gates"] if g["gate"] == "foreign_orders_reported"][0]
        assert "3 foreign working order(s)" in gate["detail"]
        assert r["arm_eligible"] is True          # reported, not a blocker


class TestProtectionAndDoctrine:
    def test_an_unattested_protection_authority_is_refused(self):
        r = PR.evaluate(_facts(protection={"authorized": False,
                                           "reasons": ["PROTECTION_ATTESTATION_MISSING: …"]}),
                        mode=PR.FINAL)
        assert "protection_authority" in _failed(r)
        assert "PROTECTION_ATTESTATION_MISSING" in [
            g for g in r["gates"] if g["gate"] == "protection_authority"][0]["detail"]

    def test_bracketless_production_is_refused(self):
        """BRACKETLESS is a smoke diagnostic. The bot owns protection."""
        assert "attached_brackets_not_bracketless" in _failed(
            PR.evaluate(_facts(production_bracketless=True), mode=PR.FINAL))

    @pytest.mark.parametrize("key,bad,gate", [
        ("max_risk_usd", 500.0, "max_risk_usd"),
        ("max_contracts", 30, "max_contracts"),
        ("preferred_stop_points", 45.0, "preferred_stop_points"),
        ("absolute_stop_points", 45.0, "absolute_stop_ceiling"),
        ("min_reward_to_risk", 0.5, "min_reward_to_risk"),
    ])
    def test_a_drifted_doctrine_number_is_refused(self, key, bad, gate):
        doc = dict(_facts()["doctrine"]); doc[key] = bad
        assert gate in _failed(PR.evaluate(_facts(doctrine=doc), mode=PR.FINAL))

    def test_the_45_point_ceiling_belongs_to_a_different_engine(self):
        """40 is this engine's absolute ceiling; 45 was the other discussion."""
        assert PR.EXPECTED_ABSOLUTE_STOP == 50.0
        assert PR.EXPECTED_PREFERRED_STOP == 35.0


class TestBrain:
    def test_a_disabled_brain_is_refused(self):
        assert "brain_enabled" in _failed(PR.evaluate(_facts(brain_enabled=False),
                                                      mode=PR.FINAL))

    def test_a_substituted_model_is_refused(self):
        assert "model_is_the_production_tier" in _failed(
            PR.evaluate(_facts(model="gpt-4o-mini"), mode=PR.FINAL))

    def test_the_gate_tracks_the_model_owner_not_a_literal(self):
        """A hardcoded tier made a correct lane fail after the operator ruling."""
        from ai_brain.production_model import PRODUCTION_MODEL
        assert PR.expected_model() == PRODUCTION_MODEL

    def test_a_provider_call_during_preflight_is_refused(self):
        """Preflight RESOLVES the model; it must never invoke it."""
        assert "no_provider_call_during_preflight" in _failed(
            PR.evaluate(_facts(provider_calls=1), mode=PR.FINAL))


class TestSourceIdentity:
    def test_dirty_tracked_source_is_refused_and_named(self):
        r = PR.evaluate(_facts(tracked_source_clean=False,
                               dirty_tracked_files=["src/broker/x.py"]), mode=PR.FINAL)
        assert "source_tracked_clean" in _failed(r)
        assert "src/broker/x.py" in [
            g for g in r["gates"] if g["gate"] == "source_tracked_clean"][0]["detail"]


class TestTheToolCannotArm:
    def test_the_preflight_tool_has_no_write_or_arm_path(self):
        import ast
        path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                            "tools", "prac_release_preflight.py")
        tree = ast.parse(open(path, encoding="utf-8").read())
        called = {ast.unparse(n.func) for n in ast.walk(tree) if isinstance(n, ast.Call)}
        for banned in ("place_order", "cancel_order", "modify_order", "close_position",
                       "gated_submit", "ExecutionRunner", "build_runner", "mint_token"):
            assert not any(banned in c for c in called), banned

    def test_it_uses_the_write_incapable_session(self):
        path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                            "tools", "prac_release_preflight.py")
        src = open(path, encoding="utf-8").read()
        assert "TopstepXReadOnlySession" in src
        assert "TopstepXLiveSession" not in src

    def test_no_code_path_arms_anything(self):
        """AST, not substring: `resolve_model(armed=True)` RESOLVES a model.

        A text match on `armed=True` flags that call, which asks the model
        authority which model an armed session would use -- the exact question
        a preflight should ask, and no arming at all. The proposition is
        "nothing here arms", so it is checked structurally.
        """
        import ast
        path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                            "tools", "prac_release_preflight.py")
        tree = ast.parse(open(path, encoding="utf-8").read())

        armed_calls = [ast.unparse(n.func) for n in ast.walk(tree)
                       if isinstance(n, ast.Call)
                       for kw in n.keywords
                       if kw.arg == "armed" and getattr(kw.value, "value", None) is True]
        assert armed_calls == ["resolve_model"], armed_calls

        assigned = {ast.unparse(t) for n in ast.walk(tree) if isinstance(n, ast.Assign)
                    for t in n.targets}
        assert not any(a.endswith(".armed") or a == "armed" for a in assigned), assigned

        env_writes = [n for n in ast.walk(tree) if isinstance(n, ast.Subscript)
                      and "environ" in ast.unparse(n)]
        assert not any("ARMED" in ast.unparse(n) for n in env_writes)
