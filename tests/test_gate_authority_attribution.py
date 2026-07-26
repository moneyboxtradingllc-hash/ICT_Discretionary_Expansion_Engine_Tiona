"""GATE-ATTRIBUTION — name the authority that refused.

`mech_gate` ANDs six independent authorities into one boolean, and the author
recorded only that boolean. A NO_TRADE therefore said
`final_gate_authorizes: False` without naming which authority refused, which is
how the regime permission matrix vetoed live for weeks before a replay surfaced
it.

Several authorities are env-gated and default ON — REGIME_AUTHORITY_ENABLED,
DIRECTION_CONFLICT_VETO, RULE_GOVERNANCE_ENABLED, STRUCTURE_AUTHORSHIP_FIREWALL.
The answer is not to disable them; it is to make a block attributable on the scan
it happens.
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from integrations.ninjatrader.deterministic.facts_provider import (
    build_facts_from_snapshot,
)

_ALL_PERMISSIONS = {
    "narrative_permits_trade", "commander_permits_trade", "council_permits_trade",
    "regime_permission_allowed", "no_promoted_rule_block", "trigger_requirement_met",
}


def _snapshot():
    return {
        "qualification": {"direction": "bearish", "status": "qualified"},
        "playbook": {"direction": "bearish", "selected_playbook": "trend_continuation"},
        "narrative_authority": {"invalidation_level": 28650.0},
        "structure": {"5m": {"bos": True, "last_swing_high": 28631.25,
                             "last_swing_low": 28427.0}},
        "liquidity": {"5m": {"sweep_detected": True}},
        "expansion": {"5m": {"displacement_detected": True}},
        "toolbox": {"preferred_tool": "", "tool_candidates": []},
        "trade_intent": {"entry_zone": {}},
        "timeframes": {},
    }


def _gate(**overrides):
    g = {"trigger_requirement_met": True, "narrative_permits_trade": True,
         "commander_permits_trade": True, "council_permits_trade": True,
         "regime_permission_allowed": True, "no_promoted_rule_block": True}
    g.update(overrides)
    return g


def _facts(**overrides):
    return build_facts_from_snapshot(
        _snapshot(), {"direction": "bearish", "decision": "ready_for_execution"},
        _gate(**overrides), 28540.0)


class TestEveryAuthorityIsRecorded:
    def test_all_six_permissions_are_reported(self):
        assert set(_facts()["_gate_permissions"]) == _ALL_PERMISSIONS

    def test_a_fully_permitted_gate_names_no_blockers(self):
        f = _facts()
        assert f["_gate_blockers"] == []
        assert f["final_gate_authorizes"] is True


class TestARefusalIsAttributable:
    @pytest.mark.parametrize("authority", sorted(_ALL_PERMISSIONS))
    def test_each_authority_names_itself_when_it_refuses(self, authority):
        f = _facts(**{authority: False})
        assert f["final_gate_authorizes"] is False
        assert authority in f["_gate_blockers"], (
            f"{authority} refused but did not appear in gate_blockers")

    def test_the_regime_veto_is_named(self):
        """The exact failure that hid for weeks behind a bare False."""
        f = _facts(regime_permission_allowed=False)
        assert f["_gate_blockers"] == ["regime_permission_allowed"]

    def test_multiple_refusals_are_all_named(self):
        f = _facts(regime_permission_allowed=False, no_promoted_rule_block=False)
        assert set(f["_gate_blockers"]) == {"regime_permission_allowed",
                                            "no_promoted_rule_block"}

    def test_permitting_authorities_are_not_blamed(self):
        f = _facts(council_permits_trade=False)
        assert "narrative_permits_trade" not in f["_gate_blockers"]
        assert f["_gate_permissions"]["narrative_permits_trade"] is True


class TestAttributionDoesNotChangeTheVerdict:
    """Diagnostics must observe, never decide."""

    def test_final_gate_still_requires_every_authority(self):
        for a in sorted(_ALL_PERMISSIONS):
            assert _facts(**{a: False})["final_gate_authorizes"] is False

    def test_the_diagnostic_keys_are_not_mechanical_facts(self):
        from integrations.ninjatrader.deterministic.author import _REQUIRED_FACT_KEYS
        assert "_gate_permissions" not in _REQUIRED_FACT_KEYS
        assert "_gate_blockers" not in _REQUIRED_FACT_KEYS
