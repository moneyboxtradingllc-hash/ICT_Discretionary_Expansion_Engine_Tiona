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
         direction="bullish", price=29380.0, legacy=True,
         volatility_state=None, expansion_state=None):
    monkeypatch.setattr(producer_module, "authorized_invalidation_catalog",
                        lambda *_args: list(rows if rows is not None else
                                            catalog(("INV_A", 29330.0),
                                                    ("INV_B", 29365.5))))
    bi = LCP.brain_input(price=price,
                         buy_side=(price + 100 if direction == "bullish" else None),
                         sell_side=(price - 100 if direction == "bearish" else None),
                         prot_low=(29330.0 if direction == "bullish" else None),
                         prot_high=(29400.0 if direction == "bearish" else None))
    bi["market"].update({
        "volatility_state": volatility_state,
        "volatility_state_temporal_class": "authority_settled_baseline",
        "expansion_state": expansion_state,
    })
    parsed = LCP.parsed(narrative_direction=direction,
                        active_draw=("buy side liquidity above" if direction == "bullish"
                                     else "sell side liquidity below"),
                        invalidation_id=selected, invalidation_level=level,
                        objective_id=(None if legacy else
                                      "OBJ_LIQ_BSL_1" if direction == "bullish"
                                      else "OBJ_LIQ_SSL_1"))
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


def test_candidate_transports_same_scan_mechanical_risk_evidence(monkeypatch):
    candidate = make(monkeypatch, volatility_state="elevated",
                     expansion_state="expanding", legacy=False)
    evidence = candidate.extras["volatility_evidence"]
    assert evidence == {
        "schema": "candidate.volatility_evidence.v1",
        "source": "brain_input.market",
        "snapshot_id": "snap-1",
        "market_data_timestamp": "2026-08-05T15:29:30+00:00",
        "brain_input_timestamp": "2026-08-05T15:29:00+00:00",
        "volatility_state": "elevated",
        "volatility_state_temporal_class": "authority_settled_baseline",
        "expansion_state": "expanding",
        "structural_level_identity": "INV_A",
        "structural_level_source": "test.catalog",
    }


@pytest.mark.parametrize("claim", [float("nan"), float("inf"),
                                    float("-inf"), True, object(), "not-a-price"])
def test_non_real_brain_invalidation_claim_refuses(monkeypatch, claim):
    with pytest.raises(NoCandidate) as exc:
        make(monkeypatch, level=claim, legacy=False)
    assert exc.value.reason == "invalidation_invalid"


@pytest.mark.parametrize("catalog_price", [float("nan"), float("inf"),
                                            float("-inf"), True, object()])
def test_non_real_catalog_price_refuses(monkeypatch, catalog_price):
    with pytest.raises(NoCandidate) as exc:
        make(monkeypatch, level=29330.0,
             rows=catalog(("INV_A", catalog_price)), legacy=False)
    assert exc.value.reason == "invalidation_invalid"


def test_finite_claim_within_existing_tick_tolerance_is_accepted(monkeypatch):
    candidate = make(monkeypatch, level=29330.0 + 1e-8, legacy=False)
    assert candidate.invalidation_price == 29330.0


def test_production_candidate_to_risk_wide_stop_contract(monkeypatch, tmp_path):
    import test_production_caller as production

    quantities = []
    for stop_points in (20.0, 36.0, 40.0, 50.0):
        entry = 30000.0
        stop = entry - stop_points
        candidate = make(
            monkeypatch, selected="INV_WIDE", level=stop,
            rows=catalog(("INV_WIDE", stop)), price=entry, legacy=False,
            volatility_state=("elevated" if stop_points > 35.0 else "stable"),
            expansion_state="compression")
        session, _, _ = production.make(tmp_path / str(stop_points))
        runner = session.build_runner(candidate)
        quantities.append(runner.geometry.size)
        assert runner.geometry.stop_price == stop
        assert runner.geometry.stop_points == stop_points
        assert runner.geometry.size <= 15
        assert runner.geometry.risk_usd <= 350.0

    assert quantities == sorted(quantities, reverse=True)
    assert quantities[0] > quantities[-1]


def test_extended_stop_without_volatility_justification_refuses(monkeypatch, tmp_path):
    import test_production_caller as production
    from broker.topstepx_combine_risk import RiskRejection

    candidate = make(monkeypatch, selected="INV_WIDE", level=29960.0,
                     rows=catalog(("INV_WIDE", 29960.0)), price=30000.0,
                     legacy=False, volatility_state="stable",
                     expansion_state="compression")
    session, _, _ = production.make(tmp_path)
    with pytest.raises(RiskRejection, match="extended_volatility_unsupported"):
        session.build_runner(candidate)


def test_extended_stop_without_verified_structural_identity_refuses(
        monkeypatch, tmp_path):
    import test_production_caller as production
    from broker.topstepx_combine_risk import RiskRejection

    candidate = make(monkeypatch, selected="INV_WIDE", level=29960.0,
                     rows=catalog(("INV_WIDE", 29960.0)), price=30000.0,
                     legacy=False, volatility_state="elevated")
    candidate.extras["volatility_evidence"]["structural_level_identity"] = ""
    session, _, _ = production.make(tmp_path)
    with pytest.raises(RiskRejection, match="extended_volatility_unsupported"):
        session.build_runner(candidate)


def test_present_malformed_canonical_evidence_cannot_fall_back(monkeypatch, tmp_path):
    import test_production_caller as production
    from broker.topstepx_combine_risk import RiskRejection

    candidate = make(monkeypatch, selected="INV_WIDE", level=29960.0,
                     rows=catalog(("INV_WIDE", 29960.0)), price=30000.0,
                     legacy=False, volatility_state="elevated")
    candidate.extras.update(volatility_evidence={},
                            volatility_state="elevated",
                            expansion_state="expanding")
    session, _, _ = production.make(tmp_path)
    with pytest.raises(RiskRejection, match="extended_volatility_unsupported"):
        session.build_runner(candidate)


def test_stop_above_absolute_ceiling_refuses_even_with_evidence(monkeypatch, tmp_path):
    import test_production_caller as production
    from broker.topstepx_combine_risk import RiskRejection

    candidate = make(monkeypatch, selected="INV_WIDE", level=29949.0,
                     rows=catalog(("INV_WIDE", 29949.0)), price=30000.0,
                     legacy=False, volatility_state="elevated",
                     expansion_state="expanding")
    session, _, _ = production.make(tmp_path)
    with pytest.raises(RiskRejection, match="stop_distance_above_cap"):
        session.build_runner(candidate)


def test_wide_stop_with_nan_claim_never_reaches_risk(monkeypatch):
    with pytest.raises(NoCandidate) as exc:
        make(monkeypatch, selected="INV_WIDE", level=float("nan"),
             rows=catalog(("INV_WIDE", 29960.0)), price=30000.0,
             legacy=False, volatility_state="elevated",
             expansion_state="expanding")
    assert exc.value.reason == "invalidation_invalid"
