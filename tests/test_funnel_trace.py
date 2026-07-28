"""The funnel must name the FIRST refusal, and must never lie about progress.

A NO_TRADE that died at `authority` and one held a single scan short on setup age
print identically today. On 2026-07-24 the second case happened at 09:42 — every
authority permitted, the trigger was confirmed, risk allowed, and the setup was
one scan young — and nothing in the log said so.

The trace is telemetry: it reads only what the gate already publishes and never
re-derives a verdict.
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from integrations.ninjatrader.deterministic.funnel import funnel_console, funnel_trace


def _snapshot(**over):
    snap = {
        "directional_authority": {"bias": "bearish", "source": "liquidity.active_liquidity_draw",
                                  "intact": True},
        "qualification": {"status": "qualified", "opportunity_score": 78},
        "playbook": {"selected_playbook": "liquidity_sweep_reversal"},
        "toolbox": {"preferred_tool": "bearish_ifvg"},
    }
    snap.update(over)
    return snap


def _gate(**over):
    g = {
        "execution_enabled": True, "allow_execution": True, "gate_status": "authorized",
        "setup_age_requirement": 2, "setup_age_actual": 3, "setup_age_effective": 3,
        "setup_age_requirement_met": True,
        "required_trigger_status": "confirmed", "actual_trigger_status": "confirmed",
        "trigger_requirement_met": True,
        "authorization_checks": {"risk_allows_trade": True, "regime_permission_allowed": True,
                                 "council_permits_trade": True, "narrative_permits_trade": True,
                                 "commander_permits_trade": True, "no_promoted_rule_block": True,
                                 "thesis_invalidation_ok": True, "brain_authorship_ok": True,
                                 "lifecycle_allows_trade": True, "setup_not_invalidated": True},
    }
    g.update(over)
    return g


class TestItNamesTheFirstRefusal:
    def test_a_clean_scan_authorizes(self):
        t = funnel_trace(_snapshot(), {"decision": "ready_for_execution"}, _gate())
        assert t["stopped_at"] is None
        assert t["authorized"] is True
        assert t["reached"] == 9

    def test_the_09_42_case_stops_at_setup_age_not_at_the_gate(self):
        """Everything permitted, trigger confirmed, one scan short."""
        t = funnel_trace(
            _snapshot(), {"decision": "ready_for_execution"},
            _gate(allow_execution=False, gate_status="blocked", setup_age_actual=1,
                  setup_age_effective=1, setup_age_requirement_met=False))
        assert t["stopped_at"] == "setup_age"
        assert t["stopped_because"] == "1 of 2 scans"
        assert "SETUP_AGE" in funnel_console(t)

    def test_no_authority_stops_first_even_when_later_stages_also_fail(self):
        t = funnel_trace(
            _snapshot(directional_authority={"bias": "neutral", "source": None}),
            {"decision": "stand_down"},
            _gate(allow_execution=False, trigger_requirement_met=False,
                  actual_trigger_status="unknown"))
        assert t["stopped_at"] == "authority"

    def test_a_silent_veto_is_attributed_by_name(self):
        checks = _gate()["authorization_checks"]
        checks["council_permits_trade"] = False
        checks["narrative_permits_trade"] = False
        t = funnel_trace(_snapshot(), {"decision": "ready_for_execution"},
                         _gate(allow_execution=False, authorization_checks=checks))
        assert t["stopped_at"] == "permissions"
        assert "council" in t["stopped_because"] and "narrative" in t["stopped_because"]


class TestItReportsProgressHonestly:
    def test_reached_counts_stages_that_did_not_refuse(self):
        early = funnel_trace(_snapshot(directional_authority={"bias": "neutral"}),
                             {"decision": "stand_down"}, _gate(allow_execution=False))
        late = funnel_trace(_snapshot(), {"decision": "ready_for_execution"},
                            _gate(allow_execution=False, gate_status="blocked",
                                  setup_age_actual=1, setup_age_requirement_met=False))
        assert late["reached"] > early["reached"]

    def test_an_absent_requirement_is_not_a_refusal(self):
        t = funnel_trace(_snapshot(), {"decision": "ready_for_execution"},
                         _gate(setup_age_requirement=0, required_trigger_status=None))
        assert t["stopped_at"] is None

    def test_execution_disabled_still_reports_would_authorize(self):
        t = funnel_trace(_snapshot(), {"decision": "ready_for_execution"},
                         _gate(execution_enabled=False, allow_execution=False,
                               gate_status="blocked", would_authorize_if_enabled=True))
        assert t["stopped_at"] == "gate"
        assert "would_authorize=True" in t["stopped_because"]


class TestItNeverBreaksAScan:
    @pytest.mark.parametrize("bad", [None, {}, {"qualification": None}])
    def test_degenerate_input_returns_a_trace(self, bad):
        t = funnel_trace(bad, None, None)
        assert "stopped_at" in t and "line" in t

    def test_a_hostile_gate_does_not_raise(self):
        class Hostile(dict):
            def get(self, *a, **k):
                raise RuntimeError("boom")
        # non-empty, or `gate or {}` swaps it out before it can raise; and the
        # decision must PASS, or the trace stops before it ever reads the gate
        t = funnel_trace(_snapshot(), {"decision": "ready_for_execution"},
                         Hostile(allow_execution=False))
        assert t["stopped_at"] == "trace_error"
