"""Structural invalidation identity is the execution stop authority."""
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))), "src"))

import test_luna_candidate_producer as LCP  # noqa: E402
from broker import luna_candidate_producer as producer_module  # noqa: E402
from broker.luna_candidate_producer import NoCandidate  # noqa: E402


def catalog(*rows):
    return [dict(invalidation_id=i, type="protected_low", price=p,
                 timeframe="5m", swing_id=f"SW-{i}", source="test.catalog",
                 registered_at="2026-08-05T15:00:00+00:00") for i, p in rows]


def make(monkeypatch, *, selected="INV_A", level=29330.0, rows=None,
         direction="bullish", price=29380.0, legacy=True):
    monkeypatch.setattr(producer_module, "authorized_invalidation_catalog",
                        lambda *_args: list(rows if rows is not None else
                                            catalog(("INV_A", 29330.0),
                                                    ("INV_B", 29365.5))))
    bi = LCP.brain_input(price=price,
                         buy_side=(price + 100 if direction == "bullish" else None),
                         sell_side=(price - 100 if direction == "bearish" else None),
                         prot_low=(29330.0 if direction == "bullish" else None),
                         prot_high=(29400.0 if direction == "bearish" else None))
    parsed = LCP.parsed(narrative_direction=direction,
                        active_draw=("buy side liquidity above" if direction == "bullish"
                                     else "sell side liquidity below"),
                        invalidation_id=selected, invalidation_level=level)
    return LCP.produce(p=LCP.producer() if legacy else
                       producer_module.CandidateProducer(account_fingerprint=LCP.FP,
                                                         contract=LCP.MNQ),
                       bi=bi, res=LCP.result(parsed=parsed))


def test_exact_id_owns_price_and_provenance(monkeypatch):
    candidate = make(monkeypatch)
    assert candidate.invalidation_price == 29330.0
    evidence = candidate.extras["structural_invalidation"]
    assert evidence["structure_identity"] == "INV_A"
    assert evidence["authorized_catalog_row"]["swing_id"] == "SW-INV_A"


def test_distance_does_not_rank(monkeypatch):
    candidate = make(monkeypatch, selected="INV_A", level=29330.0)
    assert candidate.invalidation_price != 29365.5


@pytest.mark.parametrize("selected,level,reason", [
    ("INV_A", 29365.5, "invalidation_level_mismatch"),
    ("UNKNOWN", 29330.0, "invalidation_id_unknown"),
    (None, 29330.0, "invalidation_id_missing"),
])
def test_identity_or_coherence_failure_refuses(monkeypatch, selected, level, reason):
    with pytest.raises(NoCandidate) as exc:
        make(monkeypatch, selected=selected, level=level,
             legacy=(selected is not None))
    assert exc.value.reason == reason


def test_empty_catalog_cannot_be_rescued_by_numeric_level(monkeypatch):
    with pytest.raises(NoCandidate) as exc:
        make(monkeypatch, rows=[], legacy=False)
    assert exc.value.reason == "invalidation_id_missing"


@pytest.mark.parametrize("direction,price,stop", [
    ("bullish", 29330.0, 29330.0),
    ("bearish", 29330.0, 29320.0),
])
def test_wrong_side_catalog_object_refuses(monkeypatch, direction, price, stop):
    with pytest.raises(NoCandidate) as exc:
        make(monkeypatch, selected="INV_A" if direction == "bullish" else "INV_B",
             level=stop, direction=direction, price=price,
             rows=(catalog(("INV_A", 29330.0), ("INV_B", 29320.0))
                   if direction == "bearish" else None))
    assert exc.value.reason == "invalidation_wrong_side"


def test_off_tick_catalog_price_refuses(monkeypatch):
    with pytest.raises(NoCandidate) as exc:
        make(monkeypatch, rows=catalog(("INV_A", 29330.13)), level=29330.13)
    assert exc.value.reason == "invalidation_off_tick"


def test_wider_structural_stop_is_preserved_for_downstream_sizing(monkeypatch):
    candidate = make(monkeypatch, selected="INV_B", level=29365.5)
    assert candidate.invalidation_price == 29365.5
    assert abs(29380.0 - candidate.invalidation_price) == 14.5


def test_quantity_scales_after_stop_is_fixed_and_never_rewrites_it():
    from broker.topstepx_combine_risk import build_production_bracket
    contract = LCP.MNQ
    near = build_production_bracket(direction="bullish", entry_price=30000.0,
                                    invalidation_level=29990.0,
                                    target_price=30050.0, contract=contract)
    far = build_production_bracket(direction="bullish", entry_price=30000.0,
                                   invalidation_level=29950.0,
                                   target_price=30050.0, contract=contract,
                                   evidence={"volatility_state": "elevated",
                                             "structural_level_identity": "INV_B"})
    assert near["sizing"]["contracts"] == 15
    assert far["sizing"]["contracts"] < near["sizing"]["contracts"]
    assert far["geometry"].stop_price == 29950.0
    assert far["geometry"].stop_price != 29990.0
