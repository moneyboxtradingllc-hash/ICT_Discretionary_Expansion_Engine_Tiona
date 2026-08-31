"""TOPSTEPX COMBINE SMOKE — locks for role reporting, risk doctrine, signed
bracket geometry, one-use authorization, Luna authorship and engine wiring.

No network, no model calls, no orders.
"""
from __future__ import annotations

import os
import sys
from datetime import datetime, timedelta, timezone

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src"))

from ai_brain.model_pricing import PRICING, PRODUCTION_MODEL  # noqa: E402

from ai_brain.production_model import PRODUCTION_MODEL  # noqa: E402

from ai_brain import engine_payload_audit as audit            # noqa: E402
from ai_brain.luna_health import (                            # noqa: E402
    LUNA_PRICING, REQUIRED_MODEL, calculate_cost, run_health_check,
)
from broker import topstepx_account_role as role              # noqa: E402
from broker import topstepx_smoke_auth as auth                # noqa: E402
from broker.topstepx_client import ORDER_SIDE, ORDER_TYPE, TopstepXContract  # noqa: E402
from broker.topstepx_combine_risk import (                    # noqa: E402
    MAX_RISK_PER_TRADE_USD, SMOKE_MAX_CONTRACTS, BracketGeometry, RiskRejection,
    build_bracket as _build_bracket, risk_for, ticks_between,
)


def build_bracket(**kw):
    """Production-doctrine bracket for these legacy geometry locks.

    The first-day smoke law (2026-08-05) made $20 / 10 points / 1.5R the
    DEFAULTS. These tests predate it and assert PRODUCTION geometry, so they
    state the production caps explicitly rather than silently inheriting
    whichever doctrine happens to be default. Smoke-law behavior has its own
    file: tests/test_smoke_risk_law.py.
    """
    kw.setdefault("max_risk_usd", MAX_RISK_PER_TRADE_USD)
    kw.setdefault("max_stop_points", None)
    kw.setdefault("min_reward_to_risk", None)
    return _build_bracket(**kw)

MNQ = TopstepXContract(id="CON.F.US.MNQ.U26", name="MNQU6",
                       description="Micro E-mini Nasdaq-100: September 2026",
                       tick_size=0.25, tick_value=0.5, active=True)
FP = "acct:fc84f7a928d9"


# ══════════════════════════════════════════════════════════════════════════════
class TestAccountRole:

    def test_simulated_is_never_rendered_as_practice(self):
        """REGRESSION — 2026-08-04 misreport.

        The preflight told the operator his Trading Combine was a Practice
        Account because the venue's `simulated` flag was rendered as
        'SIMULATED (practice)'. A Combine is simulated too.
        """
        env = {"TOPSTEPX_ACCOUNT_ROLE": "TRADING_COMBINE"}
        lines = " ".join(role.report_lines(True, env)).lower()
        assert "practice" not in lines
        assert "simulated" in lines and "trading_combine" in lines

    def test_environment_and_role_are_separate_facts(self):
        d = role.describe(True, {"TOPSTEPX_ACCOUNT_ROLE": "TRADING_COMBINE"})
        assert d["venue_environment"] == "SIMULATED"
        assert d["operator_declared_account_role"] == role.TRADING_COMBINE

    def test_a_combine_breach_is_flagged_as_consequential(self):
        d = role.describe(True, {"TOPSTEPX_ACCOUNT_ROLE": "TRADING_COMBINE"})
        assert d["role_is_consequential"] is True
        assert "consequences" in " ".join(role.report_lines(True, d and {"TOPSTEPX_ACCOUNT_ROLE": "TRADING_COMBINE"})).lower()

    def test_a_live_environment_is_still_shouted(self):
        lines = " ".join(role.report_lines(False, {"TOPSTEPX_ACCOUNT_ROLE": "FUNDED"}))
        assert "REAL MONEY" in lines and "LIVE" in lines

    def test_an_undeclared_role_degrades_rather_than_raising(self):
        assert role.resolve_role({}) == role.UNDECLARED
        assert role.resolve_role({"TOPSTEPX_ACCOUNT_ROLE": "nonsense"}) == role.UNDECLARED

    def test_role_never_governs_routing(self):
        """The invariant: role is reporting/policy and cannot select an account.

        Checked structurally rather than by grepping prose — the docstring is
        allowed to explain the rule, the code is not allowed to break it. No
        public function may accept an account identifier, and the module may not
        import the client that can resolve one.
        """
        import ast
        import inspect

        d = role.describe(True, {"TOPSTEPX_ACCOUNT_ROLE": "TRADING_COMBINE"})
        assert d["role_governs_routing"] is False

        tree = ast.parse(inspect.getsource(role))
        banned_params = {"account", "account_id", "account_name", "fingerprint",
                         "account_fingerprint", "client", "session"}
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef):
                params = {a.arg for a in node.args.args + node.args.kwonlyargs}
                leaked = params & banned_params
                assert not leaked, f"{node.name}() must not accept {leaked}"
            if isinstance(node, (ast.Import, ast.ImportFrom)):
                mod = getattr(node, "module", "") or ""
                names = " ".join(a.name for a in node.names)
                assert "topstepx_client" not in f"{mod} {names}", \
                    "role module must not import the account-resolving client"

    def test_role_is_case_and_separator_tolerant(self):
        for v in ("trading combine", "Trading-Combine", "TRADING_COMBINE"):
            assert role.resolve_role({"TOPSTEPX_ACCOUNT_ROLE": v}) == role.TRADING_COMBINE


# ══════════════════════════════════════════════════════════════════════════════
class TestBracketGeometry:

    def test_a_long_puts_the_stop_below_and_target_above(self):
        g = build_bracket(direction="bullish", entry_price=20000.0,
                          invalidation_level=19975.0, target_price=20050.0,
                          contract=MNQ)
        assert g.side == "buy" and g.side_code == ORDER_SIDE["buy"] == 0
        assert g.stop_price < g.entry_price < g.target_price
        assert g.stop_is_correct_side() and g.target_is_correct_side()
        assert g.stop_ticks == 100 and g.target_ticks == 200

    def test_a_short_puts_the_stop_above_and_target_below(self):
        g = build_bracket(direction="bearish", entry_price=20000.0,
                          invalidation_level=20025.0, target_price=19950.0,
                          contract=MNQ)
        assert g.side == "sell" and g.side_code == ORDER_SIDE["sell"] == 1
        assert g.target_price < g.entry_price < g.stop_price
        assert g.stop_is_correct_side() and g.target_is_correct_side()
        assert g.stop_ticks == 100 and g.target_ticks == 200

    def test_dollar_risk_matches_the_mnq_tick_value(self):
        g = build_bracket(direction="bullish", entry_price=20000.0,
                          invalidation_level=19975.0, target_price=20050.0,
                          contract=MNQ)
        # 25 points / 0.25 = 100 ticks; 100 * $0.50 = $50.00
        assert g.stop_ticks == 100
        assert g.risk_usd == 50.00
        assert risk_for(100, 1, MNQ) == 50.00

    def test_a_wrong_side_stop_is_rejected_for_a_long(self):
        with pytest.raises(RiskRejection) as exc:
            build_bracket(direction="bullish", entry_price=20000.0,
                          invalidation_level=20010.0, target_price=20050.0,
                          contract=MNQ)
        assert exc.value.reason == "wrong_side_stop"

    def test_a_wrong_side_stop_is_rejected_for_a_short(self):
        with pytest.raises(RiskRejection) as exc:
            build_bracket(direction="bearish", entry_price=20000.0,
                          invalidation_level=19990.0, target_price=19950.0,
                          contract=MNQ)
        assert exc.value.reason == "wrong_side_stop"

    def test_a_wrong_side_target_is_rejected(self):
        with pytest.raises(RiskRejection) as exc:
            build_bracket(direction="bullish", entry_price=20000.0,
                          invalidation_level=19975.0, target_price=19990.0,
                          contract=MNQ)
        assert exc.value.reason == "wrong_side_target"

    def test_a_zero_distance_stop_is_rejected(self):
        with pytest.raises(RiskRejection) as exc:
            build_bracket(direction="bullish", entry_price=20000.0,
                          invalidation_level=20000.0, target_price=20050.0,
                          contract=MNQ)
        assert exc.value.reason == "zero_distance_stop"

    def test_a_missing_invalidation_is_rejected(self):
        with pytest.raises(RiskRejection) as exc:
            build_bracket(direction="bullish", entry_price=20000.0,
                          invalidation_level=None, target_price=20050.0,
                          contract=MNQ)
        assert exc.value.reason == "missing_invalidation"

    def test_a_non_directional_thesis_cannot_author_an_entry(self):
        for d in ("neutral", "conflicted", "", None):
            with pytest.raises(RiskRejection) as exc:
                build_bracket(direction=d, entry_price=20000.0,
                              invalidation_level=19975.0, target_price=20050.0,
                              contract=MNQ)
            assert exc.value.reason == "non_directional_thesis"

    def test_invalid_tick_metadata_is_rejected(self):
        bad = TopstepXContract(id="x", name="x", description="", tick_size=0,
                               tick_value=0.5, active=True)
        with pytest.raises(RiskRejection) as exc:
            build_bracket(direction="bullish", entry_price=20000.0,
                          invalidation_level=19975.0, target_price=20050.0,
                          contract=bad)
        assert exc.value.reason == "invalid_tick_metadata"

    def test_a_stale_or_invalid_price_is_rejected(self):
        with pytest.raises(RiskRejection) as exc:
            build_bracket(direction="bullish", entry_price=0.0,
                          invalidation_level=-10.0, target_price=50.0,
                          contract=MNQ)
        assert exc.value.reason == "stale_or_invalid_price"

    def test_tick_conversion_never_rounds_a_stop_wider(self):
        # 10.4 points = 41.6 ticks -> 41 ticks, never 42
        assert ticks_between(20000.0, 19989.6, MNQ) == 41

    def test_the_serialized_payload_matches_the_official_schema(self):
        g = build_bracket(direction="bullish", entry_price=20000.0,
                          invalidation_level=19975.0, target_price=20050.0,
                          contract=MNQ)
        p = g.as_order_payload(26234765, MNQ.id, custom_tag="smoke-1")
        assert p["type"] == ORDER_TYPE["market"] == 2
        assert p["side"] == 0                       # Bid/buy
        assert p["size"] == 1
        assert p["contractId"] == "CON.F.US.MNQ.U26"
        # Signed per the live venue (2026-08-05): long -> stop negative,
        # target positive. The published example is unsigned; the gateway is not.
        assert p["stopLossBracket"] == {"ticks": -100, "type": ORDER_TYPE["stop"]}
        assert p["takeProfitBracket"] == {"ticks": 200, "type": ORDER_TYPE["limit"]}
        assert p["limitPrice"] is None and p["stopPrice"] is None and p["trailPrice"] is None
        assert set(p) == {"accountId", "contractId", "type", "side", "size", "limitPrice",
                          "stopPrice", "trailPrice", "customTag",
                          "stopLossBracket", "takeProfitBracket"}

    def test_bracket_ticks_are_signed_relative_to_entry(self):
        """CORRECTED by the venue 2026-08-05.

        This test previously asserted unsigned ticks, which is what the
        published example shows. The gateway rejects that:
          "Invalid stop loss ticks (40). Ticks should be less than zero
           when longing."
        """
        long_g = build_bracket(direction="bullish", entry_price=20000.0,
                               invalidation_level=19975.0, target_price=20050.0, contract=MNQ)
        short_g = build_bracket(direction="bearish", entry_price=20000.0,
                                invalidation_level=20025.0, target_price=19950.0, contract=MNQ)
        lp = long_g.as_order_payload(1, MNQ.id)
        assert lp["stopLossBracket"]["ticks"] < 0 < lp["takeProfitBracket"]["ticks"]
        sp = short_g.as_order_payload(1, MNQ.id)
        assert sp["takeProfitBracket"]["ticks"] < 0 < sp["stopLossBracket"]["ticks"]
        # magnitudes unchanged — only the representation
        for g, p in ((long_g, lp), (short_g, sp)):
            assert abs(p["stopLossBracket"]["ticks"]) == g.stop_ticks
            assert abs(p["takeProfitBracket"]["ticks"]) == g.target_ticks


class TestCombineRiskDoctrine:

    def test_the_cap_is_exactly_250(self):
        assert MAX_RISK_PER_TRADE_USD == 250.00

    def test_the_smoke_cap_is_exactly_one_contract(self):
        assert SMOKE_MAX_CONTRACTS == 1

    def test_risk_above_the_cap_is_rejected_not_resized(self):
        """501 ticks * $0.50 = $250.50 — over by fifty cents, still refused."""
        with pytest.raises(RiskRejection) as exc:
            build_bracket(direction="bullish", entry_price=20000.0,
                          invalidation_level=20000.0 - (501 * 0.25),
                          target_price=20050.0, contract=MNQ)
        assert exc.value.reason == "risk_above_cap"
        assert "not adjustable" in str(exc.value)

    def test_risk_exactly_at_the_cap_is_allowed(self):
        g = build_bracket(direction="bullish", entry_price=20000.0,
                          invalidation_level=20000.0 - (500 * 0.25),
                          target_price=20050.0, contract=MNQ)
        assert g.risk_usd == 250.00

    def test_size_above_the_smoke_cap_is_rejected(self):
        with pytest.raises(RiskRejection) as exc:
            build_bracket(direction="bullish", entry_price=20000.0,
                          invalidation_level=19975.0, target_price=20050.0,
                          contract=MNQ, size=2)
        assert exc.value.reason == "size_above_cap"   # renamed: the cap is a parameter now

    def test_the_invalidation_is_never_moved_to_fit_the_budget(self):
        """The stop equals the Brain's level exactly, or the trade is refused."""
        g = build_bracket(direction="bullish", entry_price=20000.0,
                          invalidation_level=19987.5, target_price=20050.0, contract=MNQ)
        assert g.stop_price == 19987.5


# ══════════════════════════════════════════════════════════════════════════════
class TestSmokeAuthorization:

    PHRASE = auth.AUTHORIZATION_PHRASE

    def issue(self, **kw):
        kw.setdefault("phrase", self.PHRASE)
        kw.setdefault("account_fingerprint", FP)
        kw.setdefault("contract_id", MNQ.id)
        return auth.issue(**kw)

    def test_the_exact_phrase_mints_a_token(self):
        t = self.issue()
        assert t.token_id.startswith("smoke-") and not t.spent

    def test_a_wrong_phrase_is_refused(self):
        for bad in ("authorize the smoke", "AUTHORIZE TOPSTEPX COMBINE SMOKE", "", "yes"):
            with pytest.raises(auth.AuthorizationError):
                self.issue(phrase=bad)

    def test_whitespace_and_case_do_not_defeat_the_phrase(self):
        assert auth.phrase_is_valid("  " + self.PHRASE.lower() + "  ")

    def test_a_hyphen_variant_is_accepted_as_the_same_words(self):
        assert auth.phrase_is_valid(self.PHRASE.replace("—", "-"))

    def test_the_safe_identifier_carries_no_secret(self):
        t = self.issue()
        d = t.describe()
        assert t._secret and t._secret not in str(d)

    def test_the_token_burns_atomically_at_submission(self):
        t = self.issue()
        auth.authorize_submission(t, account_fingerprint=FP, contract_id=MNQ.id,
                                  size=1, risk_usd=10.0)
        assert t.spent and t.spent_reason == "submission_attempted"

    def test_a_burned_token_cannot_be_reused(self):
        t = self.issue()
        auth.authorize_submission(t, account_fingerprint=FP, contract_id=MNQ.id,
                                  size=1, risk_usd=10.0)
        with pytest.raises(auth.AuthorizationError) as exc:
            auth.authorize_submission(t, account_fingerprint=FP, contract_id=MNQ.id,
                                      size=1, risk_usd=10.0)
        assert "already spent" in str(exc.value)

    def test_an_expired_token_is_refused(self):
        past = datetime.now(timezone.utc) - timedelta(hours=2)
        t = self.issue(now=past, ttl_minutes=30)
        with pytest.raises(auth.AuthorizationError) as exc:
            auth.authorize_submission(t, account_fingerprint=FP, contract_id=MNQ.id,
                                      size=1, risk_usd=10.0)
        assert "expired" in str(exc.value)

    def test_a_token_is_bound_to_the_account(self):
        t = self.issue()
        with pytest.raises(auth.AuthorizationError) as exc:
            auth.authorize_submission(t, account_fingerprint="acct:deadbeef0000",
                                      contract_id=MNQ.id, size=1, risk_usd=10.0)
        assert "different account" in str(exc.value)

    def test_a_token_is_bound_to_the_contract(self):
        t = self.issue()
        with pytest.raises(auth.AuthorizationError):
            auth.authorize_submission(t, account_fingerprint=FP,
                                      contract_id="CON.F.US.MNQ.Z26", size=1, risk_usd=10.0)

    def test_a_token_cannot_authorize_a_larger_size(self):
        t = self.issue()
        with pytest.raises(auth.AuthorizationError) as exc:
            auth.authorize_submission(t, account_fingerprint=FP, contract_id=MNQ.id,
                                      size=2, risk_usd=50.0)
        assert "exceeds the authorized maximum" in str(exc.value)

    def test_a_token_cannot_authorize_more_risk(self):
        t = self.issue()
        with pytest.raises(auth.AuthorizationError) as exc:
            auth.authorize_submission(t, account_fingerprint=FP, contract_id=MNQ.id,
                                      size=1, risk_usd=250.01)
        assert "exceeds the authorized maximum" in str(exc.value)

    def test_no_token_means_no_submission(self):
        with pytest.raises(auth.AuthorizationError) as exc:
            auth.authorize_submission(None, account_fingerprint=FP, contract_id=MNQ.id,
                                      size=1, risk_usd=10.0)
        assert "no operator authorization" in str(exc.value)

    def test_a_rejected_order_still_consumes_the_authorization(self):
        """Burn happens at the ATTEMPT, so a rejection cannot be retried free."""
        t = self.issue()
        auth.authorize_submission(t, account_fingerprint=FP, contract_id=MNQ.id,
                                  size=1, risk_usd=10.0)
        assert t.spent          # regardless of what the venue said next

    def test_a_token_from_another_process_is_refused(self, monkeypatch):
        t = self.issue()
        monkeypatch.setattr(os, "getpid", lambda: t.process_id + 1)
        with pytest.raises(auth.AuthorizationError) as exc:
            auth.authorize_submission(t, account_fingerprint=FP, contract_id=MNQ.id,
                                      size=1, risk_usd=10.0)
        assert "different process" in str(exc.value)


# ══════════════════════════════════════════════════════════════════════════════
class TestLunaAuthorship:

    def test_only_luna_is_authorized_for_this_mission(self):
        assert REQUIRED_MODEL == PRODUCTION_MODEL

    def test_another_model_is_refused_before_any_call(self, monkeypatch):
        monkeypatch.setenv("OPENAI_API_KEY", "present")
        called = {"n": 0}

        def spy(_payload, repair=None):
            called["n"] += 1
            return {}

        r = run_health_check(model="gpt-5.6-sol", call_llm=spy)
        assert r["verdict"] == "FAIL"
        assert called["n"] == 0, "a non-authorized model must not be called at all"
        assert "authorizes only" in r["blocker"]

    def test_a_deterministic_fallback_is_never_sovereign(self, monkeypatch):
        monkeypatch.setenv("OPENAI_API_KEY", "present")
        r = run_health_check(model=REQUIRED_MODEL, call_llm=lambda p, repair=None: {
            "parsed": None, "ok": False, "raw_response": None,
            "fallback_reason": "llm_error:Timeout", "usage": None, "model": REQUIRED_MODEL})
        assert r["verdict"] == "FAIL"
        assert r["checks"]["no_fallback"] is False
        assert r["checks"].get("sovereign_source") is not True

    def test_a_missing_api_key_fails_closed(self, monkeypatch):
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        r = run_health_check(model=REQUIRED_MODEL, call_llm=lambda p, repair=None: {})
        assert r["verdict"] == "FAIL" and r["checks"]["api_key_present"] is False

    def test_a_wrong_side_invalidation_fails_health(self, monkeypatch):
        monkeypatch.setenv("OPENAI_API_KEY", "present")
        bad = _thesis(direction="bullish", invalidation=20100.0)   # above price 20000
        r = run_health_check(model=REQUIRED_MODEL, call_llm=lambda p, repair=None: {
            "parsed": bad, "ok": True, "raw_response": "{}", "fallback_reason": None,
            "usage": {"prompt_tokens": 10, "completion_tokens": 5}, "model": REQUIRED_MODEL})
        assert r["checks"]["correct_side_invalidation"] is False
        assert r["verdict"] == "FAIL"

    def test_a_healthy_directional_thesis_passes(self, monkeypatch):
        monkeypatch.setenv("OPENAI_API_KEY", "present")
        good = _thesis(direction="bullish", invalidation=19975.0)
        r = run_health_check(model=REQUIRED_MODEL, call_llm=lambda p, repair=None: {
            "parsed": good, "ok": True, "raw_response": "{}", "fallback_reason": None,
            "usage": {"prompt_tokens": 1000, "completion_tokens": 500}, "model": REQUIRED_MODEL})
        assert r["verdict"] == "PASS"
        assert r["direction"] == "bullish" and r["directional"] is True


class TestUsageAccounting:

    def test_cost_uses_the_official_luna_pricing(self):
        """Corrected 2026-08-04: the earlier $1.00/$6.00 figures were stale."""
        assert LUNA_PRICING == PRICING[PRODUCTION_MODEL]   # follows the doctrine model

    def test_cached_input_is_billed_at_the_cached_rate(self):
        c = calculate_cost({"prompt_tokens": 1000, "completion_tokens": 0,
                            "prompt_tokens_details": {"cached_tokens": 400}})
        # 600 fresh @ $0.20/M + 400 cached @ $0.02/M
        assert c["fresh_input_tokens"] == 600 and c["cached_input_tokens"] == 400
        rate = PRICING[PRODUCTION_MODEL]
        assert c["cost_usd"] == round(
            (600 * rate["input"] + 400 * rate["cached_input"]) / 1_000_000, 6)

    def test_reasoning_tokens_are_captured_when_present(self):
        c = calculate_cost({"prompt_tokens": 10, "completion_tokens": 20,
                            "completion_tokens_details": {"reasoning_tokens": 7}})
        assert c["reasoning_tokens"] == 7

    def test_cost_accounting_never_raises(self):
        assert calculate_cost({"prompt_tokens": "bad"})["cost_usd"] is None


# ══════════════════════════════════════════════════════════════════════════════
class TestEnginePayloadAudit:

    def test_a_populated_engine_is_reported_populated(self):
        r = audit.audit_payload({"liquidity": {"events": [{"tf": "5m"}]}},
                                {"liquidity": ("liquidity", None, None)})
        assert r["liquidity"]["status"] == audit.PRESENT_AND_POPULATED

    def test_an_all_null_dict_is_empty_not_populated(self):
        """Module existence is not wiring, and neither is a hollow dict."""
        r = audit.audit_payload({"po3": {"phase": None, "manipulation_direction": None}},
                                {"po3": ("po3", None, None)})
        assert r["po3"]["status"] == audit.PRESENT_BUT_EMPTY

    def test_a_missing_key_is_absent(self):
        r = audit.audit_payload({}, {"htf_memory": ("htf_memory", None, None)})
        assert r["htf_memory"]["status"] == audit.ABSENT

    def test_a_gated_off_engine_reports_blocked_not_absent(self, monkeypatch):
        monkeypatch.delenv("VOLUME_WITNESS", raising=False)
        r = audit.audit_payload({}, {"volume_witness": ("volume_witness", "VOLUME_WITNESS", "off")})
        assert r["volume_witness"]["status"] == audit.BLOCKED

    def test_a_gated_on_but_unwired_engine_is_absent(self, monkeypatch):
        monkeypatch.setenv("VOLUME_WITNESS", "on")
        r = audit.audit_payload({}, {"volume_witness": ("volume_witness", "VOLUME_WITNESS", "off")})
        assert r["volume_witness"]["status"] == audit.ABSENT

    def test_nested_paths_resolve(self):
        r = audit.audit_payload({"delivery": {"state": "bullish_delivery"}},
                                {"delivery_state": ("delivery.state", None, None)})
        assert r["delivery_state"]["status"] == audit.PRESENT_AND_POPULATED

    def test_a_fallback_thesis_is_not_sovereign(self):
        p = audit.thesis_provenance({"ok": False, "fallback_reason": "llm_error", "model": "x"})
        assert p["is_sovereign"] is False and p["is_live_llm"] is False

    def test_a_live_llm_thesis_is_sovereign(self):
        p = audit.thesis_provenance({"ok": True, "fallback_reason": None, "model": REQUIRED_MODEL})
        assert p["is_sovereign"] is True


def _thesis(direction: str, invalidation) -> dict:
    """A minimally schema-valid Brain output for validator tests."""
    return {
        "market_story": "probe story long enough to read as prose",
        "narrative_direction": direction, "narrative_phase": "continuation",
        "phase_confidence": 70, "allowed_direction": direction,
        "current_action": "wait_for_retest", "reason": "probe reason",
        "invalidation_level": invalidation,
        "recommended_playbook_family": "continuation",
        "recommended_tool_family": ["fvg"],
        "preferred_trade_family": "continuation",
        "preferred_playbooks": ["continuation"], "preferred_tools": ["fvg"],
        "dominant_reasoning": "probe dominant reasoning",
    }


# ══════════════════════════════════════════════════════════════════════════════
class TestReadinessReportsSafetyGuards:
    """REGRESSION — live readiness run 2026-08-04 (22:11 ET).

    Readiness reported the risk doctrine but was SILENT on the Brain timeout,
    the single-flight guard, snapshot binding, late-response poisoning and
    execution-runner availability. An operator reading the artifact could not
    tell whether a slow Luna call could overlap a scan, or whether a late answer
    could still authorize exposure. Silence on a safety property is not proof of
    one.
    """

    REQUIRED_CHECK_KEYS = ("brain_timeout", "single_flight", "snapshot_binding",
                           "late_response", "runner")

    def _artifact(self, tmp_path, monkeypatch):
        from broker import topstepx_combine_readiness as rd
        monkeypatch.setattr(rd, "EVIDENCE_PATH", str(tmp_path / "readiness.json"))
        flight = rd.Readiness()
        # Exercise only the guard/runner reporting — no network, no venue.
        flight._guards()
        flight._runner_available()
        return {c.key: c for c in flight.checks}

    def test_readiness_reports_every_safety_guard(self, tmp_path, monkeypatch):
        checks = self._artifact(tmp_path, monkeypatch)
        for key in self.REQUIRED_CHECK_KEYS:
            assert key in checks, f"readiness must report {key}"

    def test_the_guards_are_exercised_not_merely_asserted(self, tmp_path, monkeypatch):
        checks = self._artifact(tmp_path, monkeypatch)
        assert checks["single_flight"].state == "pass"
        assert checks["snapshot_binding"].state == "pass"
        assert checks["late_response"].state == "pass"

    def test_the_reported_timeout_is_the_audited_45_seconds(self, tmp_path, monkeypatch):
        monkeypatch.delenv("AI_BRAIN_TIMEOUT_SECONDS", raising=False)
        monkeypatch.delenv("SCAN_INTERVAL_SECONDS", raising=False)
        checks = self._artifact(tmp_path, monkeypatch)
        assert checks["brain_timeout"].state == "pass"
        assert "45" in checks["brain_timeout"].detail

    def test_the_execution_runner_is_reported_available(self, tmp_path, monkeypatch):
        checks = self._artifact(tmp_path, monkeypatch)
        assert checks["runner"].state == "pass"
        assert "ExecutionRunner" in checks["runner"].detail
