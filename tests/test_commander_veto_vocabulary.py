"""COMMANDER-VOCAB — vetoes must read the vocabulary their producer emits.

The LIQUIDITY_VACUUM guardian tested `regime_label == "liquidity_vacuum"`, but
`liquidity_vacuum` is a VOLATILITY state. classify_regime can only emit ten
labels and that is not among them, so a HOSTILE safety veto had never once been
reachable.

_regime_family carried five unmatchable values borrowed from three vocabularies:
`accumulation`/`distribution` are PO3 PHASES, `liquidity_vacuum` is a volatility
state, and `consolidation`/`dead` are emitted by nothing at all.

Same class as `is_expanding = exp_state == "expanding"` in regime_features —
right key, wrong vocabulary, permanently false, invisible in aggregate output.
These tests assert against the PRODUCERS' real vocabularies so a future rename
breaks a test instead of silently disabling a veto.
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from market_commander.market_commander import (
    _guardian, _regime_family, FAM_DIRECTIONAL, FAM_ROTATIONAL,
    FAM_TRANSITIONAL, FAM_INERT, FAM_HOSTILE, FAM_UNKNOWN,
)
from regime_classification.regime_classifier import _FAMILIES

# The producers' actual vocabularies.
REGIME_LABELS = set(_FAMILIES)
VOLATILITY_STATES = {"stable", "expanding", "unstable", "toxic", "explosive",
                     "liquidity_vacuum"}
PO3_PHASES = {"accumulation", "manipulation", "distribution", "transition",
              "no_phase"}


def _view(regime="trend_down", vol="stable", **extra):
    v = {"market_regime": {"regime_label": regime, "volatility_state": vol}}
    v.update(extra)
    return v


class TestTheVocabulariesAreDistinct:
    def test_liquidity_vacuum_is_volatility_not_regime(self):
        assert "liquidity_vacuum" in VOLATILITY_STATES
        assert "liquidity_vacuum" not in REGIME_LABELS

    def test_accumulation_and_distribution_are_po3_not_regime(self):
        for v in ("accumulation", "distribution"):
            assert v in PO3_PHASES
            assert v not in REGIME_LABELS

    def test_consolidation_and_dead_are_emitted_by_nothing(self):
        for v in ("consolidation", "dead"):
            assert v not in REGIME_LABELS
            assert v not in VOLATILITY_STATES
            assert v not in PO3_PHASES


class TestTheLiquidityVacuumVetoFires:
    def test_it_fires_on_the_volatility_state(self):
        g = _guardian(_view(vol="liquidity_vacuum"))
        assert g["kind"] == "veto"
        assert g["member"] == "LIQUIDITY_VACUUM"
        assert g["family"] == FAM_HOSTILE

    def test_it_fires_on_an_explicit_flag(self):
        assert _guardian({"market_regime": {}, "liquidity_vacuum": True})["member"] \
            == "LIQUIDITY_VACUUM"

    def test_it_outranks_a_healthy_trend_read(self):
        """A vacuum is hostile regardless of what the trend says."""
        assert _guardian(_view(regime="trend_down", vol="liquidity_vacuum"))["kind"] \
            == "veto"

    def test_it_does_not_fire_on_normal_tape(self):
        assert _guardian(_view(regime="trend_down", vol="stable")) is None

    def test_a_regime_label_can_never_trigger_it(self):
        """The old shape. regime_label is not where this signal lives, so putting
        the string there must do nothing."""
        assert _guardian(_view(regime="liquidity_vacuum", vol="stable")) is None

    def test_the_support_names_the_real_source(self):
        g = _guardian(_view(vol="liquidity_vacuum"))
        assert any("volatility_state" in s for s in g["supports"])


class TestRegimeFamilyMapsOnlyRealLabels:
    @pytest.mark.parametrize("regime,expected", [
        ("expansion_up", FAM_DIRECTIONAL), ("expansion_down", FAM_DIRECTIONAL),
        ("trend_up", FAM_DIRECTIONAL), ("trend_down", FAM_DIRECTIONAL),
        ("high_volatility", FAM_DIRECTIONAL),
        ("range_rotation", FAM_ROTATIONAL), ("chop", FAM_ROTATIONAL),
        ("reversal_attempt", FAM_TRANSITIONAL),
        ("low_volatility", FAM_INERT),
        ("unknown", FAM_UNKNOWN),
    ])
    def test_every_real_label_maps(self, regime, expected):
        assert _regime_family(_view(regime=regime)) == expected

    def test_every_producible_label_is_covered(self):
        """No regime the classifier can emit falls through unhandled except the
        one that means unhandled."""
        for label in REGIME_LABELS:
            fam = _regime_family(_view(regime=label))
            if label != "unknown":
                assert fam != FAM_UNKNOWN, f"{label} falls through to UNKNOWN"

    def test_a_vacuum_overrides_the_regime_family(self):
        assert _regime_family(_view(regime="trend_up", vol="liquidity_vacuum")) \
            == FAM_HOSTILE

    @pytest.mark.parametrize("dead", ["accumulation", "distribution",
                                      "consolidation", "dead", "liquidity_vacuum"])
    def test_foreign_vocabulary_in_regime_label_is_not_special_cased(self, dead):
        """These used to have branches. A value the producer cannot emit must
        fall through, not carry meaning."""
        assert _regime_family(_view(regime=dead, vol="stable")) == FAM_UNKNOWN


class TestPo3IsNotBridgedHere:
    def test_po3_distribution_does_not_change_the_regime_family(self):
        """_w_po3 already maps distribution to DIRECTIONAL. Routing the same
        phase to TRANSITIONAL here would make two paths disagree about one piece
        of evidence."""
        with_po3 = _view(regime="chop", po3={"alignment": "full_distribution_alignment"})
        assert _regime_family(with_po3) == FAM_ROTATIONAL
