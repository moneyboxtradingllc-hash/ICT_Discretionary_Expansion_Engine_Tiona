"""SEPARATE-DIRECTION-FROM-ENTRY-ELIGIBILITY (2026-08-06).

The prompt used to instruct Luna that if it could not name a concrete playbook
it "was not confident enough to be directional -- say conflicted instead". That
collapsed three distinct questions into one:

    what is the market delivering?   /   does a setup exist?   /   should we enter?

Live evidence: 84 of 100 raw responses said `conflicted`, and 56 of 56 after
11:10 ET while Luna's own prose read "the 15m sequence remains downward... wait
for renewed bearish acceptance below 29478.5 toward 29241.0". That is a bearish
narrative with a stand-down action, reported as directionless.

Direction and action are now separate. The execution boundary is NOT loosened:
a directional stand-down is a sovereign narrative and never a candidate.
"""
from __future__ import annotations

import os
import sys
from datetime import datetime, timezone

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src"))

from _step7_fixture import detected as _detected      # noqa: E402
from _step7_fixture import priced as _priced          # noqa: E402

from ai_brain.production_model import PRODUCTION_MODEL  # noqa: E402

from ai_brain.brain_schema import empty_brain_output, validate_brain_output  # noqa: E402
from broker.luna_candidate_producer import CandidateProducer, NoCandidate    # noqa: E402
from broker.topstepx_client import TopstepXContract                          # noqa: E402
from live_scan.production_scan_cycle import ProductionScanCycle              # noqa: E402

MNQ = TopstepXContract(id="CON.F.US.MNQ.U26", name="MNQU6", description="MNQ",
                       tick_size=0.25, tick_value=0.5, active=True)
NOW = datetime(2026, 8, 6, 16, 20, tzinfo=timezone.utc)

BRAIN_INPUT = {
    "timestamp": "2026-08-06T16:19:00+00:00",
    "market": _priced({"current_price": 29483.0}),
    "liquidity": {"nearest_buy_side": 29900.0, "nearest_sell_side": 29241.0},
    "protected_swings": {
        "protected_low": {"level": 29478.5, "timestamp": "2026-08-06T16:00:00+00:00"},
        "protected_high": {"level": 29500.0, "timestamp": "2026-08-06T15:10:00+00:00"}},
}


def narrative(**over):
    n = {"narrative_direction": "bearish", "narrative_phase": "transition",
         "market_story": "15m sequence downward; continuation not intact.",
         "active_draw": "Sell-side liquidity at 29241.0"}
    n.update(over)
    return n


def stand_down(direction="bearish", **over):
    base = dict(narrative_direction=direction, allowed_direction=direction,
                current_action="stand_down", recommended_playbook_family="none",
                recommended_tool_family=["none"], invalidation_level=None)
    base.update(over)          # overrides replace, never duplicate
    return narrative(**base)


def entry(direction="bearish", **over):
    base = dict(narrative_direction=direction, allowed_direction=direction,
                current_action="enter on retest of 29500",
                recommended_playbook_family="trend_continuation",
                recommended_tool_family=["fvg"], invalidation_level=29500.0)
    base.update(over)
    return narrative(**base)


def produce(parsed):
    p = CandidateProducer(allow_prose_objective_fallback=True,
                                      account_fingerprint="acct:test", contract=MNQ)
    return p.produce(brain_result={"ok": True, "parsed": parsed,
                                   "fallback_reason": None, "model": PRODUCTION_MODEL},
                     brain_input=BRAIN_INPUT, snapshot=_detected("ifvg", "fvg"),
                     qualification={"qualified": True},
                     engine_inventory={"liquidity": "PRESENT_AND_POPULATED"},
                     snapshot_id="s1",
                     market_data_timestamp="2026-08-06T16:19:30+00:00",
                     latest_closed_bar_timestamp="2026-08-06T16:19:00+00:00", now=NOW)


def as_output(parsed):
    o = empty_brain_output()
    o.update(parsed)
    return o


# ══════════════════════════════════════════════════════════════════════════════
class TestDirectionalStandDownIsValid:

    @pytest.mark.parametrize("direction", ["bearish", "bullish"])
    def test_a_directional_stand_down_is_schema_valid(self, direction):
        assert validate_brain_output(as_output(stand_down(direction)))[0] is True

    def test_none_playbook_and_tool_are_legal_for_stand_down(self):
        o = as_output(stand_down())
        assert o["recommended_playbook_family"] == "none"
        assert o["recommended_tool_family"] == ["none"]
        assert validate_brain_output(o)[0] is True

    def test_null_invalidation_is_legal_for_stand_down(self):
        o = as_output(stand_down())
        assert o["invalidation_level"] is None
        assert validate_brain_output(o)[0] is True

    @pytest.mark.parametrize("direction", ["bearish", "bullish"])
    def test_a_directional_stand_down_is_sovereign(self, direction):
        block = {"source": "llm", "output": as_output(stand_down(direction)),
                 "fallback_reason": None}
        assert ProductionScanCycle.is_sovereign(block) is True

    def test_conflicted_still_means_conflicted(self):
        o = as_output(stand_down("conflicted"))
        assert o["narrative_direction"] == "conflicted"
        assert validate_brain_output(o)[0] is True

    def test_neutral_still_means_neutral(self):
        o = as_output(stand_down("neutral"))
        assert o["narrative_direction"] == "neutral"
        assert validate_brain_output(o)[0] is True


class TestStandDownNeverBecomesACandidate:
    """The execution boundary is unchanged."""

    @pytest.mark.parametrize("direction", ["bearish", "bullish"])
    def test_a_bare_stand_down_produces_no_candidate(self, direction):
        with pytest.raises(NoCandidate) as e:
            produce(stand_down(direction))
        assert e.value.reason == "action_declines_entry"

    @pytest.mark.parametrize("direction", ["bearish", "bullish"])
    def test_a_stand_down_that_names_a_family_still_produces_no_candidate(self, direction):
        """The old refusal was incidental (playbook 'none'); this one is explicit."""
        with pytest.raises(NoCandidate) as e:
            produce(stand_down(direction, recommended_playbook_family="trend_continuation",
                               recommended_tool_family=["fvg"], invalidation_level=29500.0))
        assert e.value.reason == "action_declines_entry"

    @pytest.mark.parametrize("action", ["stand_down", "Stand down and wait", "no_trade",
                                        "STAND_DOWN", "wait for confirmation", "flat"])
    def test_every_declining_action_is_refused(self, action):
        with pytest.raises(NoCandidate) as e:
            produce(stand_down(recommended_playbook_family="trend_continuation",
                               recommended_tool_family=["fvg"],
                               invalidation_level=29500.0, current_action=action))
        assert e.value.reason == "action_declines_entry"

    def test_direction_alone_can_never_create_a_candidate(self):
        with pytest.raises(NoCandidate):
            produce(narrative(current_action="stand_down"))

    def test_the_gate_reads_the_action_not_the_playbook(self):
        import ast
        import inspect
        import textwrap
        src = textwrap.dedent(inspect.getsource(
            CandidateProducer._assert_action_permits_entry))
        assert "current_action" in src
        tree = ast.parse(src)
        assert any(isinstance(n, ast.Raise) for n in ast.walk(tree))


class TestEntryRequirementsUnchanged:

    def test_a_complete_entry_still_produces_a_candidate(self):
        c = produce(entry("bearish"))
        assert c.direction == "bearish"
        assert c.invalidation_price == 29500.0

    def test_an_entry_without_a_playbook_is_refused(self):
        with pytest.raises(NoCandidate) as e:
            produce(entry(recommended_playbook_family="none"))
        assert e.value.reason != "action_declines_entry"

    def test_an_entry_without_a_tool_family_is_refused(self):
        with pytest.raises(NoCandidate):
            produce(entry(recommended_tool_family=["none"]))

    def test_an_entry_without_an_invalidation_is_refused(self):
        with pytest.raises(NoCandidate):
            produce(entry(invalidation_level=None))

    def test_an_entry_needs_a_named_liquidity_objective(self):
        with pytest.raises(NoCandidate):
            produce(entry(active_draw=""))


class TestPromptContractRepaired:

    def test_the_conflated_instruction_is_gone(self):
        src = open(os.path.join("src", "ai_brain", "brain_prompt.py"),
                   encoding="utf-8").read()
        assert "not confident enough to be directional" not in src
        assert "downgrade to" not in src

    def test_direction_and_action_are_declared_separate(self):
        from ai_brain.brain_prompt import BRAIN_SYSTEM_PROMPT as P
        assert "DIRECTION AND ACTION ARE SEPARATE QUESTIONS" in P
        assert "stand_down" in P

    def test_the_prompt_states_what_conflicted_means(self):
        from ai_brain.brain_prompt import BRAIN_SYSTEM_PROMPT as P
        assert "genuinely opposed and neither dominates" in P

    def test_the_prompt_no_longer_forbids_none_for_directional_stand_down(self):
        src = open(os.path.join("src", "ai_brain", "brain_prompt.py"),
                   encoding="utf-8").read()
        assert "ONLY legal when narrative_direction is conflicted/neutral" not in src


class TestTelemetrySeparation:

    def test_the_loop_reports_direction_and_action_separately(self):
        from broker.topstepx_production_loop import ProductionLoop
        t = ProductionLoop._narrative_telemetry(
            {"output": as_output(stand_down("bearish"))})
        assert t["direction"] == "bearish"
        assert t["action"] == "stand_down"

    def test_conflicted_and_bearish_stand_down_are_distinguishable(self):
        from broker.topstepx_production_loop import ProductionLoop
        a = ProductionLoop._narrative_telemetry({"output": as_output(stand_down("bearish"))})
        b = ProductionLoop._narrative_telemetry({"output": as_output(stand_down("conflicted"))})
        assert a["direction"] != b["direction"]
        assert a["action"] == b["action"] == "stand_down"


class TestSafetyUnchanged:

    def test_malformed_json_remains_degraded(self):
        from ai_brain import narrative_brain as NB
        assert NB.degraded_reason("llm_failed_fallback", {},
                                  "llm_error:JSONDecodeError:x") is not None

    def test_deterministic_fallback_remains_non_sovereign(self):
        assert ProductionScanCycle.is_sovereign(
            {"source": "deterministic", "output": as_output(entry())}) is False

    def test_an_unknown_tool_family_string_remains_degraded(self):
        assert validate_brain_output(
            as_output(entry(recommended_tool_family="made_up"))) [0] is False

    def test_no_order_endpoint_is_reachable_from_the_producer(self):
        import ast
        src = open(os.path.join("src", "broker", "luna_candidate_producer.py"),
                   encoding="utf-8").read()
        calls = {getattr(n.func, "attr", "") for n in ast.walk(ast.parse(src))
                 if isinstance(n, ast.Call)}
        for banned in ("place_order", "gated_submit", "submit", "consume_attempt"):
            assert banned not in calls
