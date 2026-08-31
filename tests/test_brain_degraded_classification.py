"""LUNA-DEGRADED-CLASSIFICATION (2026-08-06) -- the three valid-JSON degradations.

Three of 38 live calls parsed cleanly, validated as CORE-schema-valid, and were
still classified degraded. Cause, identical in all three and reproduced offline:

    recommended_tool_family returned as a bare string, e.g. "fvg",
    where the OUTPUT schema requires a list.

`validate_brain_output` rejects the whole object on a type mismatch, so
`empty_brain_output()` replaced the entire read -- direction, invalidation and
draw included. Two of the three were economically complete theses.

The degradation was CORRECT: the schema really was violated. What was wrong was
(a) the prompt contradicted itself about the container, and (b) the reason was
buried in output["warnings"], so the block's top level showed source=degraded
with fallback_reason=None and nothing else.

These tests lock the classification, the reason telemetry, and the sovereignty
law. Nothing here promotes a degraded read.
"""
from __future__ import annotations

import json
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src"))

from ai_brain import narrative_brain as NB                          # noqa: E402
from ai_brain.brain_schema import (                                 # noqa: E402
    empty_brain_output, validate_brain_output, validate_llm_core,
)
from live_scan.production_scan_cycle import ProductionScanCycle     # noqa: E402

# The exact field values observed, minimised. Full 5KB narratives add nothing.
OBSERVED = {
    "09:43:01": {"recommended_tool_family": "ote_retracement",
                 "recommended_playbook_family": "trend_continuation",
                 "narrative_direction": "bearish", "invalidation_level": 29458.75},
    "10:00:48": {"recommended_tool_family": "none",
                 "recommended_playbook_family": "none",
                 "narrative_direction": "conflicted", "invalidation_level": None},
    "10:17:12": {"recommended_tool_family": "fvg",
                 "recommended_playbook_family": "trend_continuation",
                 "narrative_direction": "bullish", "invalidation_level": 29558.5},
}


def output_with(**over):
    o = empty_brain_output()
    o.update(over)
    return o


# ══════════════════════════════════════════════════════════════════════════════
class TestObservedDegradationsReproduce:

    @pytest.mark.parametrize("ts", sorted(OBSERVED))
    def test_a_string_tool_family_fails_output_validation(self, ts):
        bad = output_with(recommended_tool_family=OBSERVED[ts]["recommended_tool_family"])
        ok, reason = validate_brain_output(bad)
        assert ok is False
        assert "recommended_tool_family" in reason and "wrong type" in reason

    @pytest.mark.parametrize("ts", sorted(OBSERVED))
    def test_the_same_read_passes_once_the_container_is_a_list(self, ts):
        good = output_with(
            recommended_tool_family=[OBSERVED[ts]["recommended_tool_family"]])
        ok, reason = validate_brain_output(good)
        assert ok is True, reason

    def test_core_llm_validation_passed_which_is_why_it_reached_output_validation(self):
        """CORE validation does not police tool_family; the OUTPUT schema does."""
        core = {"market_story": "s", "narrative_direction": "bullish",
                "narrative_phase": "continuation", "phase_confidence": 70,
                "allowed_direction": "bullish", "current_action": "a", "reason": "r",
                "recommended_tool_family": "fvg"}
        assert validate_llm_core(core)[0] is True

    def test_all_three_share_one_cause(self):
        reasons = set()
        for ts, f in OBSERVED.items():
            ok, reason = validate_brain_output(
                output_with(recommended_tool_family=f["recommended_tool_family"]))
            reasons.add(reason)
        assert len(reasons) == 1, reasons


class TestDegradedReasonTelemetry:
    """No degraded call may be reasonless."""

    def test_a_schema_fallback_reports_its_field(self):
        out = empty_brain_output()
        out["warnings"] = ["schema fallback: recommended_tool_family wrong type: str"]
        r = NB.degraded_reason("degraded", out)
        assert r and "recommended_tool_family" in r
        assert r.startswith("schema_invalid:")

    def test_a_fallback_reason_wins_when_present(self):
        r = NB.degraded_reason("llm_failed_fallback", {}, "llm_error:JSONDecodeError:x")
        assert r == "llm_error:JSONDecodeError:x"

    def test_a_reasonless_degraded_source_still_gets_a_reason(self):
        assert NB.degraded_reason("degraded", {}) == "non_sovereign_source:degraded"
        assert NB.degraded_reason("deterministic", {}) == "non_sovereign_source:deterministic"

    def test_a_clean_llm_read_has_no_degraded_reason(self):
        assert NB.degraded_reason("llm", empty_brain_output(), None) is None

    def test_an_llm_source_with_a_fallback_is_still_reasoned(self):
        assert NB.degraded_reason("llm", {}, "invalid_schema:x") == "invalid_schema:x"

    def test_the_block_exposes_degraded_reason_at_the_top_level(self):
        import ast
        import inspect
        import textwrap
        src = textwrap.dedent(inspect.getsource(NB.run_narrative_brain))
        assert '"degraded_reason"' in src


class TestSovereigntyLawUnchanged:

    def test_valid_json_alone_does_not_confer_sovereignty(self):
        """All three parsed cleanly and none were sovereign."""
        for ts, f in OBSERVED.items():
            block = {"source": "degraded", "output": empty_brain_output(),
                     "fallback_reason": None}
            assert ProductionScanCycle.is_sovereign(block) is False

    @pytest.mark.parametrize("source", ["degraded", "deterministic",
                                        "llm_failed_fallback", "contaminated_input"])
    def test_non_llm_sources_are_never_sovereign(self, source):
        assert ProductionScanCycle.is_sovereign(
            {"source": source, "output": {"narrative_direction": "bullish"}}) is False

    def test_an_empty_output_is_never_sovereign_even_from_llm(self):
        assert ProductionScanCycle.is_sovereign(
            {"source": "llm", "output": {}, "fallback_reason": None}) is False

    def test_a_complete_llm_read_is_sovereign(self):
        assert ProductionScanCycle.is_sovereign(
            {"source": "llm", "output": {"narrative_direction": "bullish"},
             "fallback_reason": None}) is True

    def test_no_repair_invents_direction_invalidation_or_objective(self):
        """empty_brain_output is the degraded baseline: it asserts nothing."""
        e = empty_brain_output()
        assert e["narrative_direction"] == "neutral"
        assert e["invalidation_level"] is None
        assert e["recommended_playbook_family"] == ""
        assert e["recommended_tool_family"] == []
        assert e["direction_provenance"]["source"] == "fallback_none"


class TestContainerNormalization:
    """A RECOGNISED bare string becomes a one-item list. Nothing else changes."""

    def test_a_recognised_concrete_family_is_containerised(self):
        from ai_brain.brain_validation import normalize_tool_family_container
        v, note = normalize_tool_family_container("fvg")
        assert v == ["fvg"]
        assert note["reason"] == "string_to_list_container"

    def test_none_becomes_a_one_item_list(self):
        from ai_brain.brain_validation import normalize_tool_family_container
        assert normalize_tool_family_container("none")[0] == ["none"]

    @pytest.mark.parametrize("tok", ["ote_retracement", "fvg", "none", "wait",
                                     "order_block", "confirmation_required"])
    def test_every_recognised_token_normalises(self, tok):
        from ai_brain.brain_validation import normalize_tool_family_container
        assert normalize_tool_family_container(tok)[0] == [tok]

    @pytest.mark.parametrize("tok", ["some_made_up_tool", "bullish_fvg", "",
                                     "liquidity_sweep_reversal_v2", "guess"])
    def test_an_unknown_string_is_left_untouched_and_fails_closed(self, tok):
        from ai_brain.brain_validation import normalize_tool_family_container
        v, note = normalize_tool_family_container(tok)
        assert v == tok and note is None
        assert validate_brain_output(output_with(recommended_tool_family=tok))[0] is False

    def test_a_list_is_never_altered(self):
        from ai_brain.brain_validation import normalize_tool_family_container
        v, note = normalize_tool_family_container(["fvg"])
        assert v == ["fvg"] and note is None

    def test_it_never_invents_a_family_for_an_empty_value(self):
        from ai_brain.brain_validation import normalize_tool_family_container
        for empty in (None, [], ""):
            v, note = normalize_tool_family_container(empty)
            assert v == empty and note is None

    def test_normalisation_runs_before_validation_in_the_pipeline(self):
        from ai_brain.brain_validation import normalize_output
        out, notes = normalize_output(output_with(recommended_tool_family="fvg"), [])
        assert out["recommended_tool_family"] == ["fvg"]
        assert validate_brain_output(out)[0] is True
        assert any(n["reason"] == "string_to_list_container" for n in notes)

    def test_the_normalisation_is_reported_in_notes(self):
        from ai_brain.brain_validation import normalize_output
        _, notes = normalize_output(output_with(recommended_tool_family="fvg"), [])
        note = [n for n in notes if n["reason"] == "string_to_list_container"][0]
        assert note["raw"] == "fvg" and note["normalized"] == ["fvg"]


class TestTheThreeAfterRepair:
    """Recorded outcome of replaying each raw through the repaired path."""

    @pytest.mark.parametrize("ts,tool,direction,valid", [
        ("09:43:01", "ote_retracement", "bearish", True),
        ("10:00:48", "none", "conflicted", True),
        ("10:17:12", "fvg", "bullish", True),
    ])
    def test_each_now_validates(self, ts, tool, direction, valid):
        from ai_brain.brain_validation import normalize_output
        out, _ = normalize_output(
            output_with(recommended_tool_family=tool, narrative_direction=direction), [])
        assert validate_brain_output(out)[0] is valid

    def test_the_conflicted_read_is_valid_but_produces_no_candidate(self):
        """Sovereign is not the same as tradeable. Conflicted stands down."""
        from ai_brain.brain_validation import normalize_output
        out, _ = normalize_output(
            output_with(recommended_tool_family="none",
                        narrative_direction="conflicted"), [])
        assert validate_brain_output(out)[0] is True
        assert out["narrative_direction"] not in ("bullish", "bearish")

    def test_the_historical_artifacts_were_not_rewritten(self):
        """Evidence is not edited after the fact."""
        import glob
        for p in glob.glob("data/ai_brain/20260806_09430*_MNQ.json"):
            d = json.load(open(p, encoding="utf-8"))
            assert d["source"] == "degraded"


class TestPromptContradictionFixed:
    """The prompt told the model both things at once."""

    def test_the_prose_now_demands_an_array(self):
        src = open(os.path.join("src", "ai_brain", "brain_prompt.py"),
                   encoding="utf-8").read()
        assert "JSON ARRAY containing exactly ONE" in src
        assert "MUST be a single tool family token" not in src

    def test_the_template_still_shows_a_list(self):
        src = open(os.path.join("src", "ai_brain", "brain_prompt.py"),
                   encoding="utf-8").read()
        assert '"recommended_tool_family": ["<one of:' in src


class TestFlagsRemainDisabled:
    """Neither disabled flag would have changed any of the three."""

    def test_keep_shallow_uses_a_different_variable_name(self, monkeypatch):
        """BRAIN_KEEP_SHALLOW does nothing; the real name is longer."""
        monkeypatch.setenv("BRAIN_KEEP_SHALLOW", "true")
        monkeypatch.delenv("BRAIN_KEEP_SHALLOW_REASONING", raising=False)
        assert NB._keep_shallow_enabled() is False
        monkeypatch.setenv("BRAIN_KEEP_SHALLOW_REASONING", "true")
        assert NB._keep_shallow_enabled() is True

    def test_keep_shallow_only_applies_to_shallow_reasoning_errors(self):
        """The three failed on a TYPE error, not prose depth."""
        import inspect
        src = inspect.getsource(NB.run_narrative_brain)
        assert 'startswith("shallow_reasoning")' in src

    def test_family_repair_is_an_extra_llm_call_not_alias_normalisation(self):
        import inspect
        src = inspect.getsource(NB.run_narrative_brain)
        i = src.find("_family_repair_enabled()")
        assert i > 0, "family-repair gate not found"
        assert "_call_llm(brain_input, repair=" in src[i:i + 400]

    def test_both_flags_default_off(self, monkeypatch):
        for var in ("BRAIN_KEEP_SHALLOW_REASONING", "BRAIN_FAMILY_REPAIR"):
            monkeypatch.delenv(var, raising=False)
        assert NB._keep_shallow_enabled() is False
        assert NB._family_repair_enabled() is False


class TestNoVenueReach:

    def test_no_order_endpoint_is_reachable_from_the_brain(self):
        import ast
        src = open(os.path.join("src", "ai_brain", "narrative_brain.py"),
                   encoding="utf-8").read()
        calls = {getattr(n.func, "attr", "") for n in ast.walk(ast.parse(src))
                 if isinstance(n, ast.Call)}
        for banned in ("place_order", "gated_submit", "close_position", "cancel_order"):
            assert banned not in calls
