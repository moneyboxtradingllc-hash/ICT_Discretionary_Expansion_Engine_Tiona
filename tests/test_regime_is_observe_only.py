"""REGIME OBSERVE-ONLY — the regime classifier informs, it does not decide.

Operator decision, 2026-07-26. This exists because the veto came back once
already under a different name.

regime_classifier.py has always carried the silencing: authority_level
"observe_only", confidence_modifier 0, "NEVER modifies decisions, execution,
risk, or AI confidence". Phase 5F.2 then added regime_permission_matrix.py — a
SEPARATE execution authority defaulting to "true" — which re-armed the veto
without touching the module that had been silenced.

Replayed on 2026-07-24: PO3 distribution, bearish narrative, valid order block,
valid OTE, valid execution geometry — rejected because the regime label read
`range_rotation` and _REVERSAL_ONLY_REGIMES permits only reversal families.
Distribution and range rotation cannot both describe the trading timeframe, and
the regime classifier consumes a far narrower evidence set than the pipeline that
produced the narrative. It must not outrank it.

Principle: evidence is additive, disagreement is evidence, disagreement is not
automatic rejection. Execution authority belongs to the institutional narrative
pipeline.
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from regime_authority.regime_permission_matrix import evaluate_regime_permissions
from regime_classification.regime_classifier import classify_regime


def _snapshot(regime_label="range_rotation", playbook="trend_continuation"):
    return {
        "market_regime": {"regime_label": regime_label,
                          "volatility_state": "stable",
                          "expansion_state": "early_expansion"},
        "playbook": {"selected_playbook": playbook},
    }


class TestTheClassifierNeverGainsAuthority:
    def test_authority_level_is_observe_only(self):
        r = classify_regime({}, None)
        assert r["authority_level"] == "observe_only"

    def test_confidence_modifier_is_always_zero(self):
        assert classify_regime({}, None)["confidence_modifier"] == 0

    def test_it_still_reports_its_evidence(self):
        """Observe-only means silent authority, not silent output — the label,
        score and reasoning must keep flowing as evidence."""
        r = classify_regime({}, None)
        for k in ("regime_label", "trend_score", "confidence", "evidence"):
            assert k in r


class TestThePermissionMatrixIsDisarmed:
    def test_disabled_permits_a_continuation_setup_in_a_range_label(self, monkeypatch):
        """The exact 2026-07-24 shape: a continuation playbook under a
        `range_rotation` label must NOT be rejected."""
        monkeypatch.setenv("REGIME_AUTHORITY_ENABLED", "false")
        p = evaluate_regime_permissions(_snapshot())
        assert p["allowed"] is True
        assert p["enabled"] is False

    def test_disabled_permits_every_playbook_family(self, monkeypatch):
        monkeypatch.setenv("REGIME_AUTHORITY_ENABLED", "false")
        for pb in ("trend_continuation", "manipulation_to_distribution",
                   "liquidity_sweep_reversal", "opening_drive", "range_expansion"):
            assert evaluate_regime_permissions(_snapshot(playbook=pb))["allowed"] is True

    def test_disabled_permits_under_every_regime_label(self, monkeypatch):
        monkeypatch.setenv("REGIME_AUTHORITY_ENABLED", "false")
        for label in ("range_rotation", "chop", "unknown", "high_volatility",
                      "trend_down", "reversal_attempt"):
            assert evaluate_regime_permissions(
                _snapshot(regime_label=label))["allowed"] is True

    def test_disabled_does_not_cap_risk(self, monkeypatch):
        """A silenced authority must not throttle sizing by the back door."""
        monkeypatch.setenv("REGIME_AUTHORITY_ENABLED", "false")
        assert evaluate_regime_permissions(_snapshot())["risk_multiplier_cap"] == 1.0


class TestTheVetoIsRealWhenArmed:
    """Pins WHY the switch matters. If this ever stops failing, the matrix has
    changed shape and the guard above may no longer be protecting anything."""

    def test_armed_rejects_a_continuation_setup_in_a_range_label(self, monkeypatch):
        monkeypatch.setenv("REGIME_AUTHORITY_ENABLED", "true")
        p = evaluate_regime_permissions(_snapshot())
        assert p["enabled"] is True
        assert p["allowed"] is False, (
            "armed matrix should still reject continuation under range_rotation — "
            "this is the behaviour REGIME_AUTHORITY_ENABLED=false exists to disable")

    def test_armed_permits_a_reversal_setup_in_the_same_label(self, monkeypatch):
        """Confirms the rejection is family-based, not a blanket block."""
        monkeypatch.setenv("REGIME_AUTHORITY_ENABLED", "true")
        p = evaluate_regime_permissions(_snapshot(playbook="liquidity_sweep_reversal"))
        assert p["allowed"] is True


class TestTheLauncherPreservesTheDecision:
    def test_the_launch_script_disables_regime_authority(self):
        """The operator decision lives in the launcher; a silent removal here is
        how this regressed the first time."""
        path = os.path.join(os.path.dirname(__file__), "..",
                            "launch_ninjatrader_mnq_deterministic_sim.ps1")
        text = open(path, encoding="utf-8").read()
        assert 'REGIME_AUTHORITY_ENABLED = "false"' in text, (
            "the deterministic launcher must disable regime execution authority")


class TestLegScopeStaysOffUntilRecalibrated:
    """LEG-SCOPE corrects directional_efficiency, but every threshold consuming
    it was calibrated against the broken value. Measured A/B at 2026-07-24 12:56:
    off -> liquidity_sweep_reversal, ready_for_execution, 5.75pt stop;
    on  -> no setup at all. Half-fixed detects less than either whole state."""

    def test_the_launcher_disables_leg_scoped_metrics(self):
        path = os.path.join(os.path.dirname(__file__), "..",
                            "launch_ninjatrader_mnq_deterministic_sim.ps1")
        text = open(path, encoding="utf-8").read()
        assert 'PO3_LEG_SCOPED_METRICS = "off"' in text, (
            "leg-scoped metrics must stay off until the thresholds that consume "
            "directional_efficiency are recalibrated against the corrected value")

    def test_the_corrected_implementation_is_still_available(self):
        """Off is a deferral, not a deletion — the fix must remain reachable."""
        from structure import po3_config as cfg
        from volatility.expansion_detector import _leg_slice
        assert callable(_leg_slice)
        assert hasattr(cfg, "leg_scope_enabled")
