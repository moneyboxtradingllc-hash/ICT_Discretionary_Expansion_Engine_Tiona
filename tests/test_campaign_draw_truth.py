from __future__ import annotations

import ast
import copy
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from market_data.campaign_draw_truth import (
    CampaignDrawTruth, PROVEN_DELIVERED, PROVEN_NOT_DELIVERED, UNKNOWN)


CONTRACT = "CON.F.US.MNQ.Z26"
SESSION = "PROD-20260914"
START = datetime(2026, 9, 14, 14, 0, tzinfo=timezone.utc)


def bar(offset, *, open_=100, high=100.5, low=99.5, close=100,
        contract=CONTRACT, complete=True):
    stamp = (START + timedelta(minutes=offset)).isoformat()
    return {"timestamp": stamp, "open": open_, "high": high, "low": low,
            "close": close, "volume": 10, "contract": contract,
            "members": 1, "expected_members": 1, "complete": complete}


def source(rows):
    return {"source_bar_time": rows[-1]["timestamp"],
            "temporal_status": "settled",
            "settled_edge_basis": "no_member_list_published"}


def view(direction="bullish", *, identity="opposing_external_liquidity:buyside@105",
         kind="opposing_external_liquidity", price=105, authorized=True):
    return {"direction_authorized": authorized,
            "refusal_reason": None if authorized else "narrative_transfer_unresolved",
            "direction": direction,
            "objective": {"identity": identity, "kind": kind, "price": price},
            "brain_lineage": {"source": "llm", "snapshot_id": "snapshot-event"}}


def tracker(session=SESSION, contract=CONTRACT):
    return CampaignDrawTruth(contract_id=contract, session_id=session,
                             instrument="MNQ")


def observe(t, rows, *, campaign=None, revision=0, current=True,
            session=SESSION, contract=CONTRACT):
    return t.observe(settled_bars=rows, settled_source=source(rows),
                     contract_id=contract, session_id=session,
                     history_revision=revision,
                     derived_state_current=current,
                     accepted_view=campaign)


def test_bullish_settled_bar_proves_delivery_and_progress():
    t = tracker()
    rows = [bar(0)]
    observe(t, rows, campaign=view())
    rows.append(bar(1, high=105.25, low=99.75, close=104))
    result = observe(t, rows, campaign=view())
    assert result["authority_status"] == PROVEN_DELIVERED
    assert result["delivery_evidence_bar"] == rows[1]["timestamp"]
    assert result["highest_price_after_anchor"] == 105.25
    assert result["observed_progress_fraction"] == pytest.approx(1.05)
    assert result["evidence_basis"] == "provider_settled_1m_chart"


def test_bearish_settled_bar_proves_delivery_and_uses_low_extreme():
    t = tracker()
    rows = [bar(0)]
    observe(t, rows, campaign=view(
        "bearish", identity="opposing_external_liquidity:sellside@95", price=95))
    rows.append(bar(1, open_=100, high=100.25, low=94.75, close=96))
    result = observe(t, rows, campaign=view(
        "bearish", identity="opposing_external_liquidity:sellside@95", price=95))
    assert result["authority_status"] == PROVEN_DELIVERED
    assert result["delivery_evidence_bar"] == rows[1]["timestamp"]
    assert result["lowest_price_after_anchor"] == 94.75
    assert result["observed_progress_fraction"] == pytest.approx(1.05)


def test_same_campaign_and_identity_never_resets_anchor_across_scans():
    t = tracker()
    first = [bar(0, high=101, low=99.5, close=100.5)]
    initial = observe(t, first, campaign=view())
    for offset in range(1, 18):
        rows = [bar(i, high=101 + i / 10, low=99.5, close=100.5)
                for i in range(max(0, offset - 4), offset + 1)]
        current = observe(t, rows, campaign=view(), revision=0)
        assert current["anchor_bar_time"] == first[0]["timestamp"]
        assert current["record_id"] == initial["record_id"]
    assert len(t.audit_records) == 1


def test_objective_identity_change_supersedes_and_anchors_new_record():
    t = tracker()
    old = observe(t, [bar(0)], campaign=view())
    rows = [bar(0), bar(1, high=102, close=101)]
    new = observe(t, rows, campaign=view(identity="opposing_external_liquidity:buyside@110",
                                         price=110))
    assert new["record_id"] != old["record_id"]
    assert new["objective_identity"].endswith("buyside@110")
    assert new["anchor_bar_time"] == rows[1]["timestamp"]
    audit = t.audit_records
    assert audit[0]["superseded"] is True
    assert audit[0]["superseded_reason"] == "campaign_or_draw_identity_changed"


def test_campaign_owner_change_starts_new_record_when_authorized():
    t = tracker()
    old = observe(t, [bar(0)], campaign=view())
    rows = [bar(0), bar(1, open_=100, high=100.5, low=99, close=99.5)]
    new = observe(t, rows, campaign=view(
        "bearish", identity="opposing_external_liquidity:sellside@95", price=95))
    assert new["record_id"] != old["record_id"]
    assert new["campaign_direction"] == "bearish"
    assert new["anchor_bar_time"] == rows[-1]["timestamp"]


def test_forming_bar_cannot_prove_delivery():
    t = tracker()
    rows = [bar(0), bar(1, high=106, low=99, close=105, complete=False)]
    result = observe(t, rows, campaign=view())
    assert result["authority_status"] == UNKNOWN
    assert "not_proven_settled" in result["authority_reason"]
    assert result.get("delivery_evidence_bar") is None


def test_settled_source_bar_that_reaches_objective_proves_delivery():
    t = tracker()
    rows = [bar(0)]
    anchor = observe(t, rows, campaign=view())
    rows.append(bar(1, high=105, low=99.5, close=104))
    delivered = observe(t, rows, campaign=view())
    assert anchor["authority_status"] == PROVEN_NOT_DELIVERED
    assert delivered["authority_status"] == PROVEN_DELIVERED


def test_open_minute_hole_makes_negative_delivery_unknown():
    t = tracker()
    rows = [bar(0)]
    observe(t, rows, campaign=view())
    rows.append(bar(2, high=103, low=99.5, close=102))
    result = observe(t, rows, campaign=view())
    assert result["authority_status"] == UNKNOWN
    assert result["coverage_status"] == "INCOMPLETE"
    assert any("venue_open_observation_absent" in issue
               for issue in result["history_issues"])


def test_positive_delivery_remains_proven_after_later_history_gap():
    t = tracker()
    rows = [bar(0)]
    observe(t, rows, campaign=view())
    rows.append(bar(1, high=105.5, low=99, close=104))
    first = observe(t, rows, campaign=view())
    assert first["authority_status"] == PROVEN_DELIVERED
    rows.append(bar(3, high=104, low=98, close=99))
    later = observe(t, rows, campaign=view())
    assert later["authority_status"] == PROVEN_DELIVERED
    assert later["coverage_status"] == "INCOMPLETE"
    assert later["progress_authoritative"] is False
    assert later["observed_progress_fraction"] is None


def test_scheduled_break_bar_without_opportunity_authority_is_unknown():
    t = tracker()
    # 16:14 ET, followed by a 16:15 ET bar in the repository's CME halt.
    anchor_stamp = datetime(2026, 9, 14, 20, 14, tzinfo=timezone.utc)
    halt_stamp = datetime(2026, 9, 14, 20, 15, tzinfo=timezone.utc)
    rows = [{**bar(0), "timestamp": anchor_stamp.isoformat()}]
    observe(t, rows, campaign=view())
    rows.append({**bar(1, high=106), "timestamp": halt_stamp.isoformat()})
    result = observe(t, rows, campaign=None)
    assert result["authority_status"] == UNKNOWN
    assert "bar_without_trade_opportunity_authority" in result["authority_reason"]
    assert result.get("delivery_evidence_bar") is None


def test_malformed_candle_is_unknown_not_a_negative_or_positive_claim():
    t = tracker()
    rows = [bar(0), bar(1, high=105, low=101, close=104)]
    rows[1]["open"] = 99  # outside the row's low/high range
    result = observe(t, rows, campaign=view())
    assert result["authority_status"] == UNKNOWN
    assert "malformed_candle" in result["authority_reason"]


def test_contract_mismatch_refuses_measurement():
    t = tracker()
    rows = [bar(0), bar(1, high=106, contract="CON.F.US.MNQ.H27")]
    result = observe(t, rows, campaign=view())
    assert result["authority_status"] == UNKNOWN
    assert "contract_mismatch" in result["authority_reason"]


def test_conflicting_duplicate_bar_is_unknown():
    t = tracker()
    first = bar(0)
    conflicting = {**first, "high": 101}
    rows = [first, conflicting]
    result = observe(t, rows, campaign=view())
    assert result["authority_status"] == UNKNOWN
    assert "conflicting_duplicate_candle" in result["authority_reason"]


def test_history_revision_supersedes_old_record_and_reanchors_from_fresh_view():
    t = tracker()
    old = observe(t, [bar(0)], campaign=view(), revision=0)
    rows = [bar(0), bar(1, high=103, close=102)]
    new = observe(t, rows, campaign=view(), revision=1)
    assert new["record_id"] != old["record_id"]
    assert new["anchor_bar_time"] == rows[-1]["timestamp"]
    assert t.audit_records[0]["superseded_reason"] == \
        "canonical_history_revision_changed"


def test_revision_invalidation_preserves_audit_and_removes_active_authority():
    t = tracker()
    rows = [bar(0)]
    prior = observe(t, rows, campaign=view())
    t.invalidate_for_history_revision(7)
    assert t.audit_records[0]["record_id"] == prior["record_id"]
    assert t.audit_records[0]["superseded"] is True
    assert t.audit_records[0]["invalidated_by_history_revision"] == 7
    result = observe(t, rows, campaign=None, revision=7)
    assert result["authority_status"] == UNKNOWN
    assert result["authority_reason"] == "no_accepted_campaign_draw"


def test_changed_bar_used_by_draw_supersedes_current_authority():
    t = tracker()
    rows = [bar(0)]
    observe(t, rows, campaign=view())
    rows.append(bar(1, high=102))
    observe(t, rows, campaign=view())
    repaired = [bar(0), bar(1, high=105.5, low=99, close=104)]
    result = observe(t, repaired, campaign=view())
    assert result["anchor_bar_time"] == repaired[-1]["timestamp"]
    assert result["record_id"] != t.audit_records[0]["record_id"]
    assert t.audit_records[0]["superseded_reason"] == \
        "campaign_input_bar_superseded"


def test_restart_does_not_resurrect_old_process_authority():
    old_process = tracker()
    rows = [bar(0)]
    observe(old_process, rows, campaign=view())
    rows.append(bar(1, high=103))
    old_process_result = observe(old_process, rows, campaign=view())
    assert old_process_result["authority_status"] == PROVEN_NOT_DELIVERED
    restarted = tracker()
    no_brain_view = observe(restarted, rows, campaign=None)
    assert no_brain_view["authority_status"] == UNKNOWN
    assert no_brain_view["authority_reason"] == "no_accepted_campaign_draw"
    fresh = observe(restarted, rows, campaign=view())
    assert fresh["anchor_bar_time"] == rows[-1]["timestamp"]
    assert fresh["record_id"] != old_process_result["record_id"]


def test_anchor_is_the_settled_source_bar_not_local_or_brain_time():
    t = tracker()
    rows = [bar(0), bar(1)]
    authored = view()
    authored["requested_at"] = "2035-01-01T00:00:00Z"
    authored["brain_completed_at"] = "2035-01-01T00:01:00Z"
    result = observe(t, rows, campaign=authored)
    assert result["anchor_bar_time"] == rows[-1]["timestamp"]
    assert result["anchor_price_basis"] == "settled_1m_source_bar_close"


def test_progress_fraction_is_observation_not_a_delivery_threshold():
    t = tracker()
    # Exactly 75% progress, but the objective has not been reached.
    rows = [bar(0)]
    observe(t, rows, campaign=view(price=105))
    rows.append(bar(1, high=103.75, low=99.5, close=103))
    result = observe(t, rows, campaign=view(price=105))
    assert result["observed_progress_fraction"] == pytest.approx(0.75)
    assert result["authority_status"] == PROVEN_NOT_DELIVERED
    assert "substantially" not in str(result).lower()


def test_authoritative_fact_api_has_no_raw_trade_or_candidate_consumer():
    root = Path(__file__).resolve().parents[1]
    module = root / "src" / "market_data" / "campaign_draw_truth.py"
    source_text = module.read_text(encoding="utf-8")
    assert "trade_interval_truth" not in source_text
    assert "current_action" not in source_text
    assert "candidate_direction_authorized" not in source_text
    # The fact is attached to the scan result only. It is not inserted into the
    # snapshot that CandidateProducer or Brain receives.
    cycle_source = (root / "src" / "live_scan" / "production_scan_cycle.py").read_text(
        encoding="utf-8")
    tree = ast.parse(cycle_source)
    assert any(isinstance(n, ast.Dict)
               and any(isinstance(k, ast.Constant)
                       and k.value == "campaign_draw_truth" for k in n.keys)
               for n in ast.walk(tree))
    assert '"campaign_draw_truth": campaign_draw_truth' in cycle_source
    assert 'snapshot["campaign_draw_truth"]' not in cycle_source


def test_current_fact_does_not_change_candidate_objective_or_snapshot():
    from live_scan.production_scan_cycle import ProductionScanCycle

    cycle = ProductionScanCycle(symbol="MNQ", session_id=SESSION,
                                contract_id=CONTRACT)
    rows = [bar(0)]
    snapshot = {
        "contract_id": CONTRACT,
        "timestamp": rows[0]["timestamp"],
        "settled_source": {"1m": source(rows)},
        "derived_state": {"history_revision": 0, "current": True},
        "timeframes": {"1m": {"last_candle": rows[0]}},
        "liquidity": {},
    }
    before = copy.deepcopy(snapshot)
    brain = {
        "source": "llm", "llm_model": "gpt-6-luna",
        "output": {"narrative_direction": "bullish",
                   "active_draw": "buy side liquidity",
                   "current_action": "stand_down"},
        "narrative_continuity": {"control_state": "campaign_established"},
        "narrative_authority_guard": {"status": "unchanged"},
    }
    from ai_brain import narrative_continuity
    original = narrative_continuity.candidate_direction_authorized
    narrative_continuity.candidate_direction_authorized = lambda *args, **kwargs: (
        True, "narrative_direction_authorized")
    try:
        result = cycle._campaign_draw_observation(
            snapshot, [{**rows[0], "complete": True}], brain,
            {"liquidity": {"nearest_buy_side": 105}}, invoke_brain=True)
    finally:
        narrative_continuity.candidate_direction_authorized = original
    assert result["authority_status"] == PROVEN_NOT_DELIVERED
    assert result["objective_identity"] == \
        "opposing_external_liquidity:buyside@105"
    assert snapshot == before
