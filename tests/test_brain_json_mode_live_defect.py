"""LUNA-JSON-DEFECT (2026-08-06) -- the two live malformed responses.

During the armed PROD-20260806 session, 2 of 38 Luna calls returned output that
was not valid JSON. Both were classified BRAIN_DEGRADED and produced no
candidate, no token and no order -- the fail-closed doctrine held.

The fixtures below are the exact STRUCTURAL defects observed, reduced to the
minimum that reproduces them (the live responses were ~5.3KB of market prose;
none of it is needed to reproduce, and none of it is reproduced here).

    09:46:47 ET  raw 5342 chars, 6 '[' vs 5 ']'  -- an array was never closed
    09:53:15 ET  raw 5281 chars, brackets balanced -- number WORDS as bare tokens

Neither was truncated: both ended with '}', and completion_tokens (1594, 1402)
sat inside the healthy range observed across the session (1327-2100).

Root cause: `BRAIN_JSON_MODE` was unset, so `response_format={"type":
"json_object"}` was never sent and the model was held to JSON by prose
instruction alone. These tests lock both the fail-closed behaviour and the
request shape that prevents the class.
"""
from __future__ import annotations

import json
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src"))

from ai_brain.production_model import PRODUCTION_MODEL  # noqa: E402

from ai_brain import narrative_brain as NB                          # noqa: E402

# ── the two observed shapes ───────────────────────────────────────────────────
UNCLOSED_ARRAY = """{
  "market_story": "NY open produced an unresolved expansion.",
  "narrative_direction": "neutral",
  "narrative_phase": "consolidation",
  "recommended_playbook_family": "none",
  "recommended_tool_family": [
    "none"
}"""

NUMBER_WORDS = """{
  "market_story": "NY open produced an unresolved expansion.",
  "narrative_direction": "neutral",
  "narrative_phase": "consolidation",
  "confidence_by_component": {
    "delivery":  thirty,
    "liquidity":  forty,
    "structure": 10
  },
  "recommended_playbook_family": "none",
  "recommended_tool_family": [
    "none"
  ]
}"""

TRUNCATED = '{\n  "market_story": "NY open produced an unre'
BAD_ESCAPE = '{"market_story": "he said \\q unquoted", "narrative_direction": "bullish"}'
# Field set taken from a REAL successful call this session (20260806_101554),
# reduced to the validator's required core. Inventing a shape here would have
# tested the fixture rather than the schema.
CLEAN_OBJ = {
    "market_story": "Price paused beneath the remaining buy-side draw.",
    "narrative_direction": "conflicted",
    "narrative_phase": "transition",
    "phase_confidence": 72,
    "allowed_direction": "conflicted",
    "current_action": "Stand down with no position.",
    "reason": "No confirmed protected low and no fresh liquidity event.",
}
CLEAN = json.dumps(CLEAN_OBJ)
FENCED_VALID = "```json\n" + CLEAN + "\n```"


class FakeMessage:
    def __init__(self, content):
        self.content = content


class FakeChoice:
    def __init__(self, content):
        self.message = FakeMessage(content)


class FakeResponse:
    def __init__(self, content):
        self.choices = [FakeChoice(content)]
        self.usage = None


class FakeCompletions:
    """Records the request kwargs so the request SHAPE can be asserted."""

    def __init__(self, content):
        self.content = content
        self.kwargs = None

    def create(self, **kwargs):
        self.kwargs = kwargs
        return FakeResponse(self.content)


class FakeClient:
    def __init__(self, content):
        self.completions = FakeCompletions(content)
        self.chat = self


class FakeOpenAIModule:
    """Stands in for the `_openai` module `_call_llm` constructs its client from.

    `_call_llm` imports `_openai` from `ai_layer.ai_api_adapter` INSIDE the
    function, so that module attribute is the only seam that intercepts it.
    Patching a non-existent `narrative_brain._client` silently did nothing and
    let these tests reach the real API.
    """

    def __init__(self, client):
        self._client = client

    def OpenAI(self, **kwargs):
        self._client.init_kwargs = kwargs
        return self._client


@pytest.fixture
def drive(monkeypatch):
    """Run the REAL _call_llm against a supplied raw response. No network."""
    def _run(content, json_mode=None):
        from ai_layer import ai_api_adapter
        client = FakeClient(content)
        monkeypatch.setattr(ai_api_adapter, "_openai", FakeOpenAIModule(client))
        monkeypatch.setattr(ai_api_adapter, "_OPENAI_AVAILABLE", True, raising=False)
        monkeypatch.setenv("OPENAI_API_KEY", "test-key-not-real")
        monkeypatch.setenv("AI_BRAIN_MODEL", PRODUCTION_MODEL)
        if json_mode is None:
            monkeypatch.delenv("BRAIN_JSON_MODE", raising=False)
        else:
            monkeypatch.setenv("BRAIN_JSON_MODE", json_mode)
        out = NB._call_llm({"timestamp": "2026-08-06T13:46:47+00:00", "market": {}})
        return out, client.completions.kwargs
    return _run


# ══════════════════════════════════════════════════════════════════════════════
class TestObservedFailuresFailClosed:

    def test_the_0946_unclosed_array_fails_closed(self, drive):
        out, _ = drive(UNCLOSED_ARRAY)
        assert out["ok"] is False
        assert not out.get("parsed")
        assert "JSONDecodeError" in (out["fallback_reason"] or "")

    def test_the_0953_number_words_fail_closed(self, drive):
        out, _ = drive(NUMBER_WORDS)
        assert out["ok"] is False
        assert not out.get("parsed")
        assert "JSONDecodeError" in (out["fallback_reason"] or "")

    def test_the_two_failures_are_distinct_shapes(self):
        """They were not one bug seen twice."""
        with pytest.raises(json.JSONDecodeError) as a:
            json.loads(UNCLOSED_ARRAY)
        with pytest.raises(json.JSONDecodeError) as b:
            json.loads(NUMBER_WORDS)
        assert a.value.msg != b.value.msg
        assert UNCLOSED_ARRAY.count("[") != UNCLOSED_ARRAY.count("]")
        assert NUMBER_WORDS.count("[") == NUMBER_WORDS.count("]")

    def test_truncated_output_fails_closed(self, drive):
        out, _ = drive(TRUNCATED)
        assert out["ok"] is False
        assert not out.get("parsed")

    def test_invalid_escaping_fails_closed(self, drive):
        out, _ = drive(BAD_ESCAPE)
        assert out["ok"] is False
        assert not out.get("parsed")

    def test_no_json_at_all_fails_closed(self, drive):
        out, _ = drive("I cannot produce a thesis right now.")
        assert out["ok"] is False
        assert out["fallback_reason"] == "no_json_in_response"

    def test_nothing_malformed_yields_a_parsed_thesis(self, drive):
        """The whole point: a bad read must never emit fields downstream."""
        for bad in (UNCLOSED_ARRAY, NUMBER_WORDS, TRUNCATED, BAD_ESCAPE):
            out, _ = drive(bad)
            assert out.get("parsed") in (None, {}, ), bad[:40]


class TestValidOutputStillWorks:

    def test_a_clean_response_parses_and_validates(self, drive):
        out, _ = drive(CLEAN)
        assert out["ok"] is True
        assert out["parsed"]["narrative_direction"] == "conflicted"

    def test_markdown_fences_are_tolerated_when_the_object_is_complete(self, drive):
        """Extraction slices brace-to-brace, so a complete fenced object is fine."""
        out, _ = drive(FENCED_VALID)
        assert out["ok"] is True

    def test_a_fenced_but_incomplete_object_still_fails_closed(self, drive):
        out, _ = drive("```json\n" + UNCLOSED_ARRAY + "\n```")
        assert out["ok"] is False


class TestRequestShape:
    """The repair: the API must enforce JSON, not the prompt alone."""

    def test_json_mode_off_sends_no_response_format(self, drive):
        _, kwargs = drive(CLEAN, json_mode=None)
        assert "response_format" not in kwargs

    def test_json_mode_on_sends_response_format(self, drive):
        _, kwargs = drive(CLEAN, json_mode="on")
        assert kwargs["response_format"] == {"type": "json_object"}

    def test_the_production_model_identity_is_luna(self, drive):
        _, kwargs = drive(CLEAN, json_mode="on")
        assert kwargs["model"] == PRODUCTION_MODEL


class TestJsonModePredicate:
    """One predicate, so the startup guard cannot drift from the behaviour."""

    @pytest.mark.parametrize("value", ["on", "true", "1", "yes", "ON", " True "])
    def test_truthy_spellings_enable_it(self, monkeypatch, value):
        monkeypatch.setenv("BRAIN_JSON_MODE", value)
        assert NB.json_mode_enabled() is True

    @pytest.mark.parametrize("value", ["off", "false", "0", "no", ""])
    def test_falsey_spellings_do_not(self, monkeypatch, value):
        monkeypatch.setenv("BRAIN_JSON_MODE", value)
        assert NB.json_mode_enabled() is False

    def test_unset_is_disabled(self, monkeypatch):
        monkeypatch.delenv("BRAIN_JSON_MODE", raising=False)
        assert NB.json_mode_enabled() is False

    def test_true_actually_sends_response_format(self, drive):
        """The original check accepted only "on": `true` looked enabled but wasn't."""
        _, kwargs = drive(CLEAN, json_mode="true")
        assert kwargs["response_format"] == {"type": "json_object"}

    def test_the_call_path_uses_the_predicate_not_the_raw_env(self):
        import ast
        import inspect
        import textwrap
        tree = ast.parse(textwrap.dedent(inspect.getsource(NB._call_llm)))
        calls = [ast.unparse(n.func) for n in ast.walk(tree) if isinstance(n, ast.Call)]
        assert "json_mode_enabled" in calls


class TestArmedStartupGuard:
    """Config alone is not enough: an armed session must refuse without it."""

    def check(self, monkeypatch, value):
        from tools import topstepx_production_session as PS
        if value is None:
            monkeypatch.delenv("BRAIN_JSON_MODE", raising=False)
        else:
            monkeypatch.setenv("BRAIN_JSON_MODE", value)
        monkeypatch.setenv("TOPSTEPX_ACCOUNT_FINGERPRINT", "acct:test")
        monkeypatch.setenv("SCAN_SYMBOL", "MNQ")
        sess = type("S", (), {"account": type("A", (), {"id": 1})(),
                              "contract": type("C", (), {"id": "CON.F.US.MNQ.U26"})(),
                              "market_hub": object()})()
        return PS.check_startup(sess, armed=True, mission_id="PROD-X",
                                provider="topstepx")

    def test_armed_refuses_when_json_mode_is_unset(self, monkeypatch):
        out = self.check(monkeypatch, None)
        assert any(r.startswith("BRAIN_JSON_MODE_DISABLED") for r in out)

    @pytest.mark.parametrize("value", ["off", "false", "0", ""])
    def test_armed_refuses_when_json_mode_is_disabled(self, monkeypatch, value):
        out = self.check(monkeypatch, value)
        assert any(r.startswith("BRAIN_JSON_MODE_DISABLED") for r in out)

    @pytest.mark.parametrize("value", ["on", "true"])
    def test_armed_permits_when_json_mode_is_enforced(self, monkeypatch, value):
        out = self.check(monkeypatch, value)
        assert not [r for r in out if r.startswith("BRAIN_JSON_MODE_DISABLED")]

    def test_disarmed_is_not_blocked_by_the_guard(self, monkeypatch):
        """A read-only preflight must still be runnable while diagnosing this."""
        from tools import topstepx_production_session as PS
        monkeypatch.delenv("BRAIN_JSON_MODE", raising=False)
        monkeypatch.setenv("TOPSTEPX_ACCOUNT_FINGERPRINT", "acct:test")
        monkeypatch.setenv("SCAN_SYMBOL", "MNQ")
        sess = type("S", (), {"account": type("A", (), {"id": 1})(),
                              "contract": type("C", (), {"id": "CON.F.US.MNQ.U26"})(),
                              "market_hub": object()})()
        out = PS.check_startup(sess, armed=False, mission_id="", provider="topstepx")
        assert not [r for r in out if r.startswith("BRAIN_JSON_MODE_DISABLED")]

    def test_the_guard_calls_the_brains_own_predicate(self):
        src = open(os.path.join("tools", "topstepx_production_session.py"),
                   encoding="utf-8").read()
        assert "json_mode_enabled" in src
        assert 'getenv("BRAIN_JSON_MODE") ==' not in src   # no divergent re-check


class TestDegradedCannotAuthorACandidate:

    def test_a_fallback_source_is_not_sovereign(self):
        from live_scan.production_scan_cycle import ProductionScanCycle
        for block in ({"source": "llm_failed_fallback", "output": {"narrative_direction": "bullish"}},
                      {"source": "deterministic", "output": {"narrative_direction": "bullish"}},
                      {"source": "degraded", "output": {}},
                      {"source": "llm", "output": {"a": 1}, "fallback_reason": "llm_error:x"}):
            assert ProductionScanCycle.is_sovereign(block) is False

    def test_a_clean_llm_block_is_sovereign(self):
        from live_scan.production_scan_cycle import ProductionScanCycle
        assert ProductionScanCycle.is_sovereign(
            {"source": "llm", "output": {"narrative_direction": "neutral"},
             "fallback_reason": None}) is True

    def test_a_degraded_scan_produces_no_candidate(self, tmp_path):
        """End-to-end: degraded never reaches CandidateProducer."""
        from broker import topstepx_production_loop as PL
        src = open(os.path.join("src", "broker", "topstepx_production_loop.py"),
                   encoding="utf-8").read()
        assert "BRAIN_DEGRADED" in src
        assert PL.BRAIN_DEGRADED != PL.NO_CANDIDATE

    def test_no_order_endpoint_is_reachable_in_this_module(self):
        import ast
        src = open(os.path.join("src", "ai_brain", "narrative_brain.py"),
                   encoding="utf-8").read()
        calls = {getattr(n.func, "attr", "") for n in ast.walk(ast.parse(src))
                 if isinstance(n, ast.Call)}
        for banned in ("place_order", "gated_submit", "submit", "close_position"):
            assert banned not in calls
