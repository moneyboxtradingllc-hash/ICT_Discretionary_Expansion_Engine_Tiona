"""The three recovery paths: functional, bounded, and counted.

`REPAIR_PROMPT_TEMPLATE` embedded a literal JSON example with unescaped braces,
so `str.format()` read `{"narrative_direction": ...}` as a placeholder and
raised KeyError before any request left the process. Every repair path had been
inert -- the zero repair calls on 2026-08-10 were not restraint, the machinery
could not fire.

Fixing it makes three paths capable of spending money, so the guarantees that
matter are the bounds, not the fix:

    normal scan          1 request
    worst case           4 requests   primary -> json -> family -> invalidation
    recursion            impossible: a repair result is only ever accepted or
                         rejected, never fed back into another call

Both SOFT repair gates are off by default and stay off -- an offline replay of
today's 116 responses showed they would fire on 60 legitimate directional
stand-downs, doubling spend to argue with correct answers.

TRANSPORT COUNTS ARE ASSERTED, not accounting rows: a test that counts ledger
writes cannot see a duplicate network call. No test contacts OpenAI.
"""
from __future__ import annotations

import json
import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))

from ai_brain import ai_call_ledger as L                    # noqa: E402
from ai_brain import narrative_brain as nb                  # noqa: E402
from ai_brain.brain_prompt import REPAIR_PROMPT_TEMPLATE    # noqa: E402


# ── a client that counts every outbound transport ────────────────────────────
class CountingCompletions:
    """Counts REAL transport calls, through either surface."""

    def __init__(self, contents, *, raise_with=None):
        self.contents = list(contents)
        self.raise_with = raise_with
        self.transport_calls = 0
        self.kwargs = []
        outer = self

        class _WRR:
            def create(self, **kw):
                return _Raw(outer._next(kw))
        self.with_raw_response = _WRR()

    def _next(self, kw):
        self.transport_calls += 1
        self.kwargs.append(kw)
        if self.raise_with:
            raise self.raise_with
        content = (self.contents.pop(0) if self.contents
                   else self.contents_default())
        return _Resp(content)

    def contents_default(self):
        return json.dumps(GOOD)

    def create(self, **kw):
        return self._next(kw)


class _Raw:
    def __init__(self, resp):
        self._resp = resp
        self.headers = {"x-request-id": "req_1"}

    def parse(self):
        return self._resp


class _Resp:
    def __init__(self, content):
        self.choices = [type("C", (), {"message": type("M", (), {"content": content})()})()]
        self.usage = None
        self.id = "resp_1"
        self.model = "gpt-5.6-terra"


#: A schema-valid directional stand-down -- the shape 60 of today's 116 scans
#: produced, and the shape the soft-repair gates would wrongly "fix".
GOOD = {"market_story": "a" * 80, "narrative_direction": "bearish",
        "narrative_phase": "distribution", "current_action": "stand_down",
        "dominant_reasoning": "b" * 120, "recommended_playbook_family": "none",
        "recommended_tool_family": ["none"], "invalidation_level": None,
        "phase_confidence": 60, "allowed_direction": "bearish",
        "reason": "r" * 40}


@pytest.fixture
def brain(monkeypatch, tmp_path):
    import ai_layer.ai_api_adapter as adapter
    monkeypatch.setenv("OPENAI_API_KEY", "k")
    monkeypatch.setenv("AI_BRAIN_MODEL", "gpt-5.6-terra")
    monkeypatch.setenv("AI_BRAIN_DIR", str(tmp_path))
    monkeypatch.setattr(adapter, "_OPENAI_AVAILABLE", True)

    def install(completions):
        chat = type("Chat", (), {"completions": completions})()
        client = type("Cl", (), {"__init__":
                                 lambda self, **kw: setattr(self, "chat", chat)})
        monkeypatch.setattr(adapter, "_openai", type("M", (), {"OpenAI": client}))
        return completions
    return install


# ══════════════════════════════════════════════════════════════════════════════
class TestTheTemplateDefect:

    def test_the_template_now_renders(self):
        out = REPAIR_PROMPT_TEMPLATE.format(
            errors="- missing market_story",
            previous=json.dumps({"narrative_direction": "bearish"}))
        assert isinstance(out, str) and len(out) > 500

    def test_the_json_example_appears_literally_as_intended(self):
        out = REPAIR_PROMPT_TEMPLATE.format(errors="e", previous="{}")
        assert '{"narrative_direction": "bearish", "allowed_direction": "bearish",' in out
        assert '"recommended_tool_family": ["none"], "invalidation_level": null}' in out
        assert "{{" not in out and "}}" not in out, "escaping leaked into the prompt"

    def test_both_substitutions_land(self):
        out = REPAIR_PROMPT_TEMPLATE.format(
            errors="- shallow_reasoning", previous='{"a": 1}')
        assert "- shallow_reasoning" in out and '{"a": 1}' in out

    def test_the_only_placeholders_are_errors_and_previous(self):
        import string
        fields = {f for _, f, _, _ in string.Formatter().parse(
            REPAIR_PROMPT_TEMPLATE) if f}
        assert fields == {"errors", "previous"}

    def test_a_repair_call_now_reaches_transport(self, brain):
        """The defect, directly: this used to raise KeyError before sending."""
        c = brain(CountingCompletions([json.dumps(GOOD)]))
        out = nb._call_llm({"timestamp": "t"},
                           repair={"purpose": L.PURPOSE_JSON_REPAIR,
                                   "previous": GOOD, "errors": ["x"]})
        assert c.transport_calls == 1
        assert out["ok"] is True


class TestTransportCounts:
    """7A-7L: assert real outbound calls."""

    def test_A_a_valid_response_is_one_request(self, brain):
        c = brain(CountingCompletions([json.dumps(GOOD)]))
        nb._call_llm({"timestamp": "t"})
        assert c.transport_calls == 1

    def test_H_raw_response_instrumentation_makes_one_call_not_two(self, brain):
        """The failure mode: plain create AND raw create for one logical call."""
        c = brain(CountingCompletions([json.dumps(GOOD)]))
        nb._call_llm({"timestamp": "t"})
        assert c.transport_calls == 1, "instrumentation double-billed"

    def test_H_a_client_without_raw_response_still_makes_one_call(self, brain):
        class NoRaw(CountingCompletions):
            def __init__(self, contents):
                super().__init__(contents)
                del self.with_raw_response
        c = brain(NoRaw([json.dumps(GOOD)]))
        nb._call_llm({"timestamp": "t"})
        assert c.transport_calls == 1

    def test_F_a_transport_failure_is_not_retried(self, brain):
        c = brain(CountingCompletions([], raise_with=TimeoutError("t")))
        out = nb._call_llm({"timestamp": "t"})
        assert c.transport_calls == 1, "a hidden retry occurred"
        assert out["ok"] is False

    def test_G_a_ledger_write_failure_does_not_duplicate_the_request(
            self, brain, monkeypatch, tmp_path):
        blocked = tmp_path / "occupied"
        blocked.write_text("not a directory")
        monkeypatch.setenv("AI_BRAIN_DIR", str(blocked))
        c = brain(CountingCompletions([json.dumps(GOOD)]))
        nb._call_llm({"timestamp": "t"})
        assert c.transport_calls == 1

    def test_I_J_cache_and_request_id_instrumentation_add_no_call(self, brain):
        c = brain(CountingCompletions([json.dumps(GOOD)]))
        nb._call_llm({"timestamp": "t"})
        assert c.transport_calls == 1
        kw = c.kwargs[0]
        assert kw["prompt_cache_key"]
        assert L.CLIENT_REQUEST_HEADER in kw["extra_headers"]

    def test_E_a_malformed_repair_response_does_not_recurse(self, brain):
        """A repair result is accepted or rejected. It never calls again."""
        c = brain(CountingCompletions(["not json at all"]))
        out = nb._call_llm({"timestamp": "t"},
                           repair={"purpose": L.PURPOSE_JSON_REPAIR,
                                   "previous": {}, "errors": ["x"]})
        assert c.transport_calls == 1
        assert out["ok"] is False

    def test_max_retries_is_zero(self):
        src = open(os.path.join(ROOT, "src", "ai_brain", "narrative_brain.py"),
                   encoding="utf-8").read()
        assert "max_retries=0" in src


class TestOneShotAndRecursion:
    """3: every family bounded, no loops."""

    def test_L_the_maximum_chain_is_four_and_is_linear(self):
        """Asserted against the SOURCE, so a future loop cannot slip in."""
        src = open(os.path.join(ROOT, "src", "ai_brain", "narrative_brain.py"),
                   encoding="utf-8").read()
        body = src[src.index("def run_narrative_brain("):]
        assert body.count("_call_llm(") == 4, "the number of call sites changed"
        for purpose in ("PURPOSE_JSON_REPAIR", "PURPOSE_FAMILY_REPAIR",
                        "PURPOSE_INVALIDATION_REPAIR"):
            assert body.count(f"LEDGER.{purpose}") == 1, purpose

    def test_no_repair_site_sits_inside_a_loop(self):
        import ast
        src = open(os.path.join(ROOT, "src", "ai_brain", "narrative_brain.py"),
                   encoding="utf-8").read()
        tree = ast.parse(src)
        for node in ast.walk(tree):
            if not isinstance(node, (ast.For, ast.While)):
                continue
            for inner in ast.walk(node):
                if isinstance(inner, ast.Call):
                    name = getattr(inner.func, "id", "")
                    assert name != "_call_llm", "a repair call is inside a loop"

    def test_no_generic_retry_loop_was_introduced(self):
        src = open(os.path.join(ROOT, "src", "ai_brain", "narrative_brain.py"),
                   encoding="utf-8").read()
        for banned in ("for attempt in range", "while not ok",
                       "for _ in range(retries", "max_attempts"):
            assert banned not in src, banned

    def test_the_soft_repair_gates_are_off_by_default(self, monkeypatch):
        """They would fire on 60 legitimate stand-downs. They stay off."""
        monkeypatch.delenv("BRAIN_FAMILY_REPAIR", raising=False)
        monkeypatch.delenv("BRAIN_INVALIDATION_REPAIR", raising=False)
        assert nb._family_repair_enabled() is False
        assert nb._invalidation_repair_enabled() is False


class TestRepairAccounting:
    """5: no repair may spend invisibly."""

    @pytest.mark.parametrize("purpose", [L.PURPOSE_JSON_REPAIR,
                                         L.PURPOSE_FAMILY_REPAIR,
                                         L.PURPOSE_INVALIDATION_REPAIR])
    def test_each_repair_writes_exactly_one_classified_row(self, brain, purpose):
        brain(CountingCompletions([json.dumps(GOOD)]))
        nb.set_call_context(session_id="S-REP", scan=5)
        nb._call_llm({"timestamp": "t"},
                     repair={"purpose": purpose, "previous": {}, "errors": ["e"]})
        nb.set_call_context()
        rows = L.load("S-REP")
        assert len(rows) == 1
        row = rows[0]
        assert row["call_purpose"] == purpose
        assert row["brain_role"] == L.PRIMARY, "a repair is still the primary brain"
        assert row["session_id"] == "S-REP" and row["scan"] == 5
        for field in ("client_request_id", "request_id", "response_id",
                      "model_requested", "model_returned", "prompt_cache_key",
                      "attempt", "latency_seconds"):
            assert row.get(field) is not None, field
        for field in ("prompt_tokens", "cached_tokens", "uncached_input_tokens",
                      "cache_write_tokens", "completion_tokens", "total_tokens"):
            assert field in row, field
        assert "reasoning_tokens" in row

    def test_a_failed_repair_is_still_identifiable(self, brain):
        brain(CountingCompletions([], raise_with=TimeoutError("t")))
        nb.set_call_context(session_id="S-FAIL", scan=2)
        out = nb._call_llm({"timestamp": "t"},
                           repair={"purpose": L.PURPOSE_FAMILY_REPAIR,
                                   "previous": {}, "errors": []})
        nb.set_call_context()
        assert out["ok"] is False
        assert out["client_request_id"].startswith("S-FAIL-s2-primary-family_repair-")

    def test_a_repair_is_never_classified_as_primary(self, brain):
        brain(CountingCompletions([json.dumps(GOOD)]))
        nb.set_call_context(session_id="S-CLS", scan=1)
        nb._call_llm({"timestamp": "t"},
                     repair={"purpose": L.PURPOSE_FAMILY_REPAIR,
                             "previous": {}, "errors": []})
        nb.set_call_context()
        assert L.load("S-CLS")[0]["call_purpose"] != L.PURPOSE_PRIMARY


class TestRepairCacheBehaviour:
    """6: audited, not assumed."""

    def test_the_repair_stable_prefix_is_identical_to_primary(self, brain):
        """The repair turn is APPENDED after the dynamic user message, so the
        cacheable prefix is unchanged -- which makes sharing the key correct
        rather than convenient."""
        c = brain(CountingCompletions([json.dumps(GOOD), json.dumps(GOOD)]))
        nb._call_llm({"timestamp": "t"})
        nb._call_llm({"timestamp": "t"},
                     repair={"purpose": L.PURPOSE_JSON_REPAIR,
                             "previous": {}, "errors": ["e"]})
        primary, repair = c.kwargs
        assert primary["messages"][0] == repair["messages"][0]
        assert len(primary["messages"]) == 2 and len(repair["messages"]) == 3
        assert repair["messages"][2]["role"] == "user"
        assert primary["prompt_cache_key"] == repair["prompt_cache_key"]

    def test_the_repair_key_carries_no_session_scan_or_time(self, brain):
        c = brain(CountingCompletions([json.dumps(GOOD)]))
        nb.set_call_context(session_id="PROD-ZZ", scan=99)
        nb._call_llm({"timestamp": "t"},
                     repair={"purpose": L.PURPOSE_JSON_REPAIR,
                             "previous": {}, "errors": ["e"]})
        nb.set_call_context()
        key = c.kwargs[0]["prompt_cache_key"]
        assert "PROD-ZZ" not in key and "99" not in key


class TestSessionTelemetry:
    """8."""

    def test_every_required_counter_is_exposed(self, tmp_path, monkeypatch):
        monkeypatch.setenv("AI_BRAIN_DIR", str(tmp_path))
        for scan, purpose in ((1, L.PURPOSE_PRIMARY), (2, L.PURPOSE_PRIMARY),
                              (2, L.PURPOSE_JSON_REPAIR),
                              (2, L.PURPOSE_FAMILY_REPAIR),
                              (2, L.PURPOSE_INVALIDATION_REPAIR)):
            L.record(session_id="TEL", scan=scan, role=L.PRIMARY, purpose=purpose)
        s = L.summarize(L.load("TEL"))
        assert s["primary_calls"] == 2
        assert s["json_repair_calls"] == 1
        assert s["family_repair_calls"] == 1
        assert s["invalidation_repair_calls"] == 1
        assert s["repair_calls_total"] == 3
        assert s["shadow_calls"] == 0
        assert s["total_ai_calls"] == 5
        assert s["scans_with_repairs"] == 1
        assert s["max_ai_calls_observed_single_scan"] == 4

    def test_K_shadow_calls_stay_zero_with_mode_off(self, tmp_path, monkeypatch):
        monkeypatch.setenv("AI_BRAIN_DIR", str(tmp_path))
        monkeypatch.setenv("TWO_BRAIN_MODE", "off")
        L.record(session_id="TEL2", scan=1, role=L.PRIMARY,
                 purpose=L.PURPOSE_PRIMARY)
        assert L.summarize(L.load("TEL2"))["shadow_calls"] == 0


class TestV8DoctrineUnchanged:
    """9: the structure work is not touched by this mission."""

    def test_risk_numbers(self):
        from broker.topstepx_combine_risk import (ABSOLUTE_MAX_STOP_POINTS,
                                                  MIN_REWARD_TO_RISK,
                                                  PREFERRED_MAX_STOP_POINTS,
                                                  PRODUCTION_MAX_CONTRACTS,
                                                  PRODUCTION_MAX_RISK_USD)
        assert (ABSOLUTE_MAX_STOP_POINTS, PREFERRED_MAX_STOP_POINTS,
                PRODUCTION_MAX_RISK_USD, PRODUCTION_MAX_CONTRACTS,
                MIN_REWARD_TO_RISK) == (50.0, 35.0, 350.00, 15, 1.0)

    def test_structure_flip_vocabulary_intact(self):
        from structure import structure_flip as SF
        assert SF.FLIP_TYPES == {SF.BROKEN_SUPPORT_FLIP,
                                 SF.BROKEN_RESISTANCE_FLIP}
        assert SF.MAX_ACTIVE_FLIPS_PER_SIDE == 2

    def test_directional_bos_intact(self):
        from structure.structure_engine import analyze_structure
        c = [{"open": x, "high": x + 2.0, "low": x - 2.0, "close": x,
              "volume": 100}
             for x in [110, 108, 106, 104, 100, 104, 106, 108, 110, 106, 102,
                       96]]
        # CLASS G swing geometry (timestamp-less fixture) + a REAL transition.
        #
        # STEP 4B.12 §4 UNIT 2: the series used to end ...102, 96, 92 with the
        # swing low at 98, so the break happened at 96 and the final bar 92 was
        # ALREADY BEYOND. The old position predicate could not tell those apart.
        # It now ends ON the break bar, and the previous expected close (102) is
        # supplied so the directional break this test pins is a genuine event.
        out = analyze_structure(c, allow_uncadenced=True,
                                transition={"state": "EVALUABLE",
                                            "previous_close": 102.0})
        assert out["bos_direction"] == "bearish"
        assert out["broken_level"] == out["last_swing_low"]
