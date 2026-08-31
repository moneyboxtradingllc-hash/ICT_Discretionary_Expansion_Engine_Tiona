"""FULL-STACK-RELEASE-SMOKE-1 guards. All green BEFORE any broker write.

The old `topstepx_execution_smoke.py` builds its own payload and runs its own
poll loop; an AST trace shows it reaches NONE of the current execution
lifecycle. A green run of it would certify machinery that no longer governs
production, which is worse than no smoke at all.

So the release smoke is a WRAPPER around the production `ExecutionRunner`, and
these tests pin the properties that make it safe to point at a real account:
PRAC by identity, one attempt, one contract, attached brackets, the production
lifecycle as the owner, and no path to arming or authorization.
"""
from __future__ import annotations

import ast
import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))
sys.path.insert(0, os.path.join(ROOT, "tools"))

TOOL = os.path.join(ROOT, "tools", "topstepx_release_smoke.py")
SRC = open(TOOL, encoding="utf-8").read()
TREE = ast.parse(SRC)
CALLS = {ast.unparse(n.func) for n in ast.walk(TREE) if isinstance(n, ast.Call)}


def _consts():
    import topstepx_release_smoke as RS
    return RS


class TestAccountIsHardPinned:
    def test_prac_identity_is_operator_supplied_with_no_default(self):
        """LUNA-TOPSTEPX-ONLY: this used to assert the pin was a hardcoded
        CONSTANT, on the reasoning that a canary redirectable by an env var is
        one typo from a funded account. That reasoning still stands -- but the
        literals were one operator's real account numbers and could not ship.

        The guarantee that replaces it is the one that still protects money:
        there is NO DEFAULT. An unset pin refuses outright rather than running
        against whatever account happens to authenticate.
        """
        RS = _consts()
        assert RS.PRAC_ACCOUNT_ID == 11111111          # from the suite's env
        assert RS.PRAC_FINGERPRINT == "acct:66cacd650e99"

    def test_an_unset_pin_refuses_instead_of_defaulting(self, monkeypatch):
        # The pin is bound at MODULE IMPORT, so clearing the environment after
        # the fact proves nothing -- the module must be reloaded to observe an
        # unconfigured install. Reloaded again at the end so the cached module
        # other tests share goes back to the suite's configured identity.
        import importlib
        monkeypatch.delenv("PRAC_ACCOUNT_ID", raising=False)
        monkeypatch.delenv("PRAC_ACCOUNT_FINGERPRINT", raising=False)
        RS = importlib.reload(_consts())
        assert RS.PRAC_ACCOUNT_ID is None
        acct = type("A", (), {"id": 11111111,
                              "name": "PRAC-V2-FIXTURE-00000000"})()
        with pytest.raises(SystemExit) as exc:
            RS.assert_prac(acct)
        assert "no account pin configured" in str(exc.value)
        monkeypatch.undo()
        importlib.reload(RS)

    def test_the_combine_is_refused_by_identity(self):
        RS = _consts()
        assert RS.FORBIDDEN_ACCOUNTS[22222222] == "COMBINE"
        acct = type("A", (), {"id": 22222222, "name": "50KTC-TEST-FIXTURE-B"})()
        with pytest.raises(SystemExit) as exc:
            RS.assert_prac(acct)
        assert "COMBINE" in str(exc.value)

    def test_the_retired_account_is_refused_by_identity(self):
        RS = _consts()
        acct = type("A", (), {"id": 33333333, "name": "50KTC-TEST-FIXTURE-A"})()
        with pytest.raises(SystemExit) as exc:
            RS.assert_prac(acct)
        assert "RETIRED" in str(exc.value)

    def test_an_unknown_account_is_refused_too(self):
        """Not a denylist: anything that is not PRAC is refused."""
        RS = _consts()
        acct = type("A", (), {"id": 99999999, "name": "SOMETHING-ELSE"})()
        with pytest.raises(SystemExit) as exc:
            RS.assert_prac(acct)
        assert "not PRAC" in str(exc.value)

    def test_a_prac_id_with_a_foreign_name_fails_the_fingerprint(self):
        RS = _consts()
        acct = type("A", (), {"id": 11111111, "name": "WRONG-NAME"})()
        with pytest.raises(SystemExit) as exc:
            RS.assert_prac(acct)
        assert "fingerprint" in str(exc.value)

    def test_the_real_prac_identity_passes(self):
        RS = _consts()
        acct = type("A", (), {"id": 11111111, "name": "PRAC-V2-FIXTURE-00000000"})()
        RS.assert_prac(acct)          # no raise


class TestOneAttemptOneContract:
    def test_size_is_exactly_one(self):
        assert _consts().SMOKE_SIZE == 1

    def test_geometry_is_far_inside_production_caps(self):
        RS = _consts()
        assert RS.SMOKE_STOP_POINTS == 10.0        # $20 vs the $250 cap
        assert RS.SMOKE_TARGET_POINTS == 20.0      # R = 2.0 vs the 1.0 floor
        assert RS.SMOKE_STOP_POINTS < 40.0         # absolute ceiling

    def test_there_is_no_retry_loop_around_submit(self):
        """The order has left the process; a retry is a second entry."""
        fn = [n for n in ast.walk(TREE) if isinstance(n, ast.FunctionDef)
              and n.name == "phase_b"][0]
        submits = [n for n in ast.walk(fn) if isinstance(n, ast.Call)
                   and ast.unparse(n.func).endswith("runner.submit")]
        assert len(submits) == 1
        loops = [n for n in ast.walk(fn) if isinstance(n, (ast.For, ast.While))]
        for loop in loops:
            assert not any(ast.unparse(c.func).endswith("runner.submit")
                           for c in ast.walk(loop) if isinstance(c, ast.Call))


class TestTheProductionLifecycleIsTheOwner:
    def test_it_drives_the_production_execution_runner(self):
        assert "R.ExecutionRunner" in CALLS

    def test_it_enables_the_prompt_post_fill_lifecycle(self):
        assigned = {ast.unparse(t): ast.unparse(n.value)
                    for n in ast.walk(TREE) if isinstance(n, ast.Assign)
                    for t in n.targets}
        assert assigned.get("runner.prompt_fill_authority") == "True"

    def test_it_reaches_the_current_post_fill_methods(self):
        for method in ("establish_structural_protection", "abandon_unfilled_entry",
                       "mission_owns_order"):
            assert any(method in c for c in CALLS), method

    def test_geometry_comes_from_the_production_bracket_builder(self):
        assert "build_bracket" in CALLS

    def test_the_old_smoke_does_NOT_reach_the_current_lifecycle(self):
        """Why this wrapper exists at all. Pinned so the gap cannot be forgotten."""
        old = open(os.path.join(ROOT, "tools", "topstepx_execution_smoke.py"),
                   encoding="utf-8").read()
        for method in ("ExecutionRunner", "prompt_fill_authority", "acquire_full_fill",
                       "authorize_actual_fill", "protective_children",
                       "reanchor_protection_to_structure", "verify_protection"):
            assert method not in old, f"{method} unexpectedly present in the old smoke"


class TestBracketlessIsImpossible:
    def test_the_wrapper_never_mentions_bracketless(self):
        assert "BRACKETLESS" not in SRC.upper()

    def test_the_payload_carries_attached_brackets(self):
        """Production's `as_order_payload` always attaches both legs."""
        from broker.topstepx_combine_risk import BracketGeometry
        import inspect
        body = inspect.getsource(BracketGeometry.as_order_payload)
        assert "stopLossBracket" in body and "takeProfitBracket" in body


class TestPhaseSeparation:
    def test_phase_b_requires_explicit_authorization(self):
        RS = _consts()
        rc = RS.main(["--phase", "b"])           # flag absent
        assert rc == 2

    def test_phase_a_runs_before_phase_b_in_the_ab_path(self):
        fn = [n for n in ast.walk(TREE) if isinstance(n, ast.FunctionDef)
              and n.name == "main"][0]
        order = [ast.unparse(n.func) for n in ast.walk(fn)
                 if isinstance(n, ast.Call) and ast.unparse(n.func) in ("phase_a", "phase_b")]
        assert order.index("phase_a") < order.index("phase_b")

    def test_a_failed_phase_a_blocks_the_broker_write(self):
        src = ast.unparse([n for n in ast.walk(TREE) if isinstance(n, ast.FunctionDef)
                           and n.name == "main"][0])
        assert "if not ok_a" in src and "return 2" in src

    def test_a_stand_down_is_not_treated_as_a_failure(self):
        """PHASE A asks whether Terra WORKS, not whether it will trade."""
        fn = ast.unparse([n for n in ast.walk(TREE) if isinstance(n, ast.FunctionDef)
                          and n.name == "phase_a"][0])
        # the pass predicate is transport + parse, never the action value
        assert "ok = source == 'llm' and returned == model and bool(parsed)" in fn

    def test_no_semantic_reroll_of_terra(self):
        """One inference. A loop around the Brain call would be a re-roll."""
        fn = [n for n in ast.walk(TREE) if isinstance(n, ast.FunctionDef)
              and n.name == "phase_a"][0]
        brain_calls = [n for n in ast.walk(fn) if isinstance(n, ast.Call)
                       and "run_narrative_brain" in ast.unparse(n.func)]
        assert len(brain_calls) == 1
        for loop in [n for n in ast.walk(fn) if isinstance(n, (ast.For, ast.While))]:
            assert not any("run_narrative_brain" in ast.unparse(c.func)
                           for c in ast.walk(loop) if isinstance(c, ast.Call))


class TestItCannotArmOrAuthorize:
    def test_it_never_issues_a_canonical_session_authorization(self):
        for banned in ("issue_authorization", "ProductionSessionMission",
                       "session_auth", "write_authorization"):
            assert banned not in SRC, banned

    def test_it_never_arms(self):
        assigned = {ast.unparse(t) for n in ast.walk(TREE) if isinstance(n, ast.Assign)
                    for t in n.targets}
        assert not any(a.endswith(".armed") or a == "armed" for a in assigned)
        assert "PRODUCTION_ARMED_SESSION" not in SRC

    def test_it_does_not_override_the_decision_window(self):
        """Phase A must not consult or force the window; that would test a
        modified bot rather than the completed one."""
        for banned in ("window_open", "in_window", "SESSION_DATE_OVERRIDE",
                       "DECISION_WINDOW"):
            assert banned not in SRC, banned


class TestCleanupRequiresProof:
    def test_cleanup_uses_the_certified_recovery(self):
        assert any("abandon_unfilled_entry" in c for c in CALLS)

    def test_success_requires_a_final_venue_read(self):
        fn = ast.unparse([n for n in ast.walk(TREE) if isinstance(n, ast.FunctionDef)
                          and n.name == "phase_b"][0])
        assert "session.open_positions()" in fn and "session.open_orders()" in fn
        assert "return bool(outcome.get('established')) and cleanup.get('safe')" in fn

    def test_foreign_orders_are_never_cancelled_by_the_wrapper(self):
        assert "cancel_order" not in CALLS

    def test_it_refuses_to_start_when_not_flat(self):
        fn = ast.unparse([n for n in ast.walk(TREE) if isinstance(n, ast.FunctionDef)
                          and n.name == "phase_b"][0])
        assert "if positions or foreign:" in fn


class TestFillsStayAttributable:
    def test_the_canary_carries_a_bot_tag(self):
        """The prior smoke reported 0 trades / $0 because customTag was None."""
        assert "bot_tag" in CALLS
        assert "custom_tag=tag" in SRC


class TestGeometryIsAnchoredToTheLiveQuote:
    """The defect that cost the previous canary its re-anchor proof.

    Canary 2 anchored to the last CLOSED canonical 1m bar (29528.25) while the
    market was at 29545.75. That is 17.5 points of STALENESS, not slippage: the
    fill made the smoke geometry unlawful (R = 0.091) and the runner correctly
    refused to re-anchor. Production reprices against a live quote at the submit
    boundary; the wrapper did not, so the wrapper was wrong.
    """

    def test_the_reference_comes_from_the_live_quote_provider(self):
        assert "LiveQuoteProvider" in CALLS
        assert any("quotes.describe" in c for c in CALLS)

    def test_the_stale_canonical_bar_path_is_gone(self):
        """No fallback to the last closed bar; that is what broke canary 2."""
        fn = ast.unparse([n for n in ast.walk(TREE) if isinstance(n, ast.FunctionDef)
                          and n.name == "phase_b"][0])
        assert "CON_F_US_MNQ" not in fn and ".jsonl" not in fn
        assert "json.loads(line)" not in fn

    def test_the_buy_reference_is_the_ask_matching_production(self):
        """Production's slippage contract: BUY slippage = fill - best_ask."""
        fn = ast.unparse([n for n in ast.walk(TREE) if isinstance(n, ast.FunctionDef)
                          and n.name == "phase_b"][0])
        assert "ref = float(q['best_ask'])" in fn
        import inspect
        from broker import topstepx_slippage as SL
        assert "fill_price - captured_best_ask" in inspect.getsource(SL)

    def test_a_stale_quote_refuses_before_any_broker_write(self):
        import topstepx_release_smoke as RS
        assert RS.MAX_QUOTE_AGE_SECONDS == 30.0        # production's max_market_age
        fn = ast.unparse([n for n in ast.walk(TREE) if isinstance(n, ast.FunctionDef)
                          and n.name == "phase_b"][0])
        assert "if age > MAX_QUOTE_AGE_SECONDS:" in fn
        # the refusal must precede submit in source order
        assert fn.index("MAX_QUOTE_AGE_SECONDS") < fn.index("runner.submit")

    def test_a_missing_quote_refuses_before_any_broker_write(self):
        fn = ast.unparse([n for n in ast.walk(TREE) if isinstance(n, ast.FunctionDef)
                          and n.name == "phase_b"][0])
        assert "if not q.get('has_quote') or q.get('best_ask') is None:" in fn
        assert fn.index("has_quote") < fn.index("runner.submit")

    def test_the_geometry_handed_to_build_bracket_derives_from_that_reference(self):
        fn = ast.unparse([n for n in ast.walk(TREE) if isinstance(n, ast.FunctionDef)
                          and n.name == "phase_b"][0])
        assert "stop_abs = ref - SMOKE_STOP_POINTS" in fn
        assert "target_abs = ref + SMOKE_TARGET_POINTS" in fn
        assert "invalidation_level=stop_abs" in fn and "target_price=target_abs" in fn


class TestFlightRecorderIsMandatory:
    def test_both_recorder_fields_are_configured_before_submit(self):
        """`_recording()` is false unless BOTH are set; canary 1 lost the venue
        body because neither was."""
        fn = ast.unparse([n for n in ast.walk(TREE) if isinstance(n, ast.FunctionDef)
                          and n.name == "phase_b"][0])
        assert "runner.submission_store_dir" in fn
        assert "runner.submission_session_id" in fn
        assert fn.index("runner.submission_store_dir") < fn.index("runner.submit")
