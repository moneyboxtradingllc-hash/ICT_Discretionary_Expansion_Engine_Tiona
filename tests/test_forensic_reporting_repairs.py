from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timedelta, timezone

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))

from broker import topstepx_mission_state as MS  # noqa: E402
from broker.topstepx_session_authorization import (  # noqa: E402
    ProductionSessionMission, SessionAuthorization)
from tools import topstepx_ai_usage_audit as AI_AUDIT  # noqa: E402
from tools import topstepx_session_outcome_report as OUTCOME  # noqa: E402
from tools import topstepx_trade_postmortem as POSTMORTEM  # noqa: E402


SESSION = "PROD-FORENSIC-TEST"
BASE = datetime(2026, 9, 9, 14, 0, tzinfo=timezone.utc)


def _write_jsonl(path, rows):
    with open(path, "w", encoding="utf-8") as fh:
        for row in rows:
            fh.write(json.dumps(row, default=str) + "\n")


def _ai_row(*, scan=1, role="primary", purpose="primary",
            model="gpt-5.6-luna", ok=True, fallback_reason=None,
            prompt=100, cached=20, completion=30, response_id="resp"):
    return {
        "schema_version": AI_AUDIT.LEDGER.LEDGER_SCHEMA,
        "at_utc": "2026-09-09T14:00:00+00:00",
        "session_id": SESSION,
        "scan": scan,
        "brain_role": role,
        "call_purpose": purpose,
        "attempt": 1,
        "model_requested": model,
        "model_returned": model,
        "client_request_id": f"req-{scan}-{purpose}",
        "response_id": response_id,
        "ok": ok,
        "fallback_reason": fallback_reason,
        "prompt_tokens": prompt,
        "cached_tokens": cached,
        "uncached_input_tokens": prompt - cached,
        "cache_write_tokens": 0,
        "completion_tokens": completion,
        "reasoning_tokens": 5,
        "total_tokens": prompt + completion,
    }


def test_ai_audit_distinguishes_missing_from_existing_zero_row_file(tmp_path):
    missing = AI_AUDIT.audit(SESSION, ledger_dir=str(tmp_path))
    assert missing["evidence_status"] == "MISSING"
    assert missing["summary"] is None
    assert missing["cost"] is None

    path = tmp_path / f"ai_calls_{SESSION}_20260909.jsonl"
    path.touch()
    zero = AI_AUDIT.audit(SESSION, ledger_dir=str(tmp_path))
    assert zero["evidence_status"] == "PRESENT"
    assert zero["summary"]["requests_total"] == 0
    assert zero["cost"]["known_priced_cost_usd"] == 0.0


def test_ai_audit_accounts_requests_repairs_failures_cache_and_lower_bound(tmp_path):
    rows = [
        _ai_row(scan=1),
        _ai_row(scan=1, purpose="json_repair", prompt=80, cached=0),
        _ai_row(scan=2, role="shadow", purpose="adjudication",
                model="model-without-a-price", ok=False,
                fallback_reason="shadow unavailable", response_id=""),
    ]
    _write_jsonl(tmp_path / f"ai_calls_{SESSION}_20260909.jsonl", rows)
    retrieval = tmp_path / "retrieval_scans.jsonl"
    _write_jsonl(retrieval, [
        {"session_id": SESSION, "scan_id": "1"},
        {"session_id": SESSION, "scan_id": "2"},
    ])

    result = AI_AUDIT.audit(SESSION, ledger_dir=str(tmp_path),
                            retrieval_path=str(retrieval))
    summary = result["summary"]
    cost = result["cost"]
    assert summary["requests_total"] == 3
    assert summary["requests_primary"] == 2
    assert summary["requests_shadow"] == 1
    assert summary["requests_repair"] == 1
    assert summary["requests_failed"] == 1
    assert summary["fallback_bearing_requests"] == 1
    assert summary["scans_with_multiple_requests"] == 1
    assert summary["max_requests_on_identified_scan"] == 2
    assert cost["status"] == "LOWER_BOUND"
    assert cost["total_session_cost_usd"] is None
    assert cost["known_priced_cost_usd"] > 0
    assert cost["unknown_pricing_request_count"] == 1
    assert result["retrieval"]["recorded_retrieval_scans"] == 2
    assert result["retrieval"]["retrieval_scans_with_ai_activity"] == 2


def _candle(minute, high, low):
    return {"timestamp": (BASE + timedelta(minutes=minute)).isoformat(),
            "open": low, "high": high, "low": low, "close": high}


def _mission(*, fill=102, exit_price=104, direction="bullish"):
    return {
        "mission_id": "M1",
        "fill_price": fill,
        "exit_price": exit_price,
        "filled_quantity": 1,
        "exit_type": "STOP",
        "state": "COMPLETE",
        "history": [
            {"state": "POSITION_OPEN", "at": BASE.isoformat()},
            {"state": "COMPLETE", "at": (BASE + timedelta(minutes=5)).isoformat()},
        ],
    }


def _plan(direction="bullish"):
    geometry = {
        "entry_price": 100,
        "stop_price": 95,
        "target_price": 110,
        "stop_points": 5,
        "target_points": 10,
    }
    if direction is not None:
        geometry["direction"] = direction
    return {"geometry": geometry, "side": "BUY", "quantity": 1}


def test_postmortem_uses_actual_fill_relative_target_distance():
    candles = [_candle(i, 106 if i != 3 else 108, 100) for i in range(5)]
    result = POSTMORTEM.analyse(_mission(), _plan(), candles, after_minutes=1)

    assert result["coverage_status"] == "COMPLETE"
    assert result["path"]["mfe_points"] == 6
    assert result["target_points_actual_fill_relative"] == 8
    assert result["points_short_of_target"] == 2
    assert result["fraction_of_target_reached"] == 0.75
    assert result["planned_points_short_of_target"] == 2
    assert result["planned_fraction_of_target_reached"] == 0.8
    assert result["target_touched_in_trade"]["status"] == "NO"
    assert result["stop_touched_in_trade"]["status"] == "NO"


@pytest.mark.parametrize("missing", [0, 2, 4])
def test_postmortem_marks_missing_leading_interior_or_trailing_minutes_unknown(missing):
    candles = [_candle(i, 105, 100) for i in range(5) if i != missing]
    coverage, overlapping, full = POSTMORTEM.interval_coverage(
        candles, BASE, BASE + timedelta(minutes=5))
    evidence = POSTMORTEM.touch_evidence(
        coverage, overlapping, full, 110, above=True)
    assert coverage["status"] == "INCOMPLETE"
    assert evidence["status"] == "UNKNOWN"


def test_postmortem_boundary_bar_cannot_prove_a_negative_touch():
    candles = [_candle(i, 105, 100) for i in range(3)]
    coverage, overlapping, full = POSTMORTEM.interval_coverage(
        candles, BASE + timedelta(seconds=30),
        BASE + timedelta(minutes=2, seconds=30))
    evidence = POSTMORTEM.touch_evidence(
        coverage, overlapping, full, 110, above=True)
    assert coverage["status"] == "COMPLETE"
    assert evidence["status"] == "UNKNOWN"


def test_postmortem_missing_direction_does_not_use_bearish_math():
    result = POSTMORTEM.analyse(
        _mission(fill=102, exit_price=104), _plan(direction=None),
        [_candle(i, 108, 100) for i in range(5)], after_minutes=1)
    assert result["direction"] is None
    assert result["realised_points"] is None
    assert result["path"] is None
    assert result["target_touched_in_trade"]["status"] == "UNKNOWN"


def _saved_authorization(store, session=SESSION):
    path = os.path.join(store, f"session_auth_{session}.json")
    auth = SessionAuthorization(
        session_id=session, account_fingerprint="acct:test",
        contract_id="CON.F.US.MNQ.U26", session_date="2026-09-09",
        decision_window="09:30-14:00 America/New_York",
        daily_loss_budget_usd=725.0, issued_at="2026-09-09T13:00:00+00:00",
        path=path)
    auth.authorization_fingerprint = auth.fingerprint()
    auth.save()
    return auth


def test_outcome_report_uses_owner_accounting_and_halts_after_zero_fill(tmp_path):
    store = str(tmp_path)
    auth = _saved_authorization(store)
    owner = ProductionSessionMission(auth, store)
    owner.load_existing()
    mission = owner.open_trade_mission(positions=0, working_orders=0,
                                       unknown_external=False, in_window=True)
    mission.consume_attempt(candidate_fingerprint="candidate", token_id="token")
    mission.venue_rejected_zero_fill(
        venue_order_id="ORD-1", error_code=2, error_message="rejected",
        positions=0, working_orders=0)

    accounting = OUTCOME.authorization_accounting(store, SESSION)
    assert accounting["status"] == "OWNER_DERIVED"
    assert accounting["trade_missions_allowed"] == 2
    assert accounting["trade_missions_used"] == 0
    assert accounting["remaining_allowance"] == 2
    assert accounting["submissions_made"] == 1
    assert accounting["entry_attempts"] == 1
    assert accounting["venue_rejections"] == 1
    assert accounting["session_halted_for_review"] is True
    assert accounting["may_open_new_trade_mission"] is False
    assert accounting["filled_trades"] is None
    assert accounting["round_trips"] is None


def test_outcome_report_does_not_turn_reloaded_callback_counters_into_zero(tmp_path):
    store = str(tmp_path)
    auth = _saved_authorization(store, session="PROD-FORENSIC-COMPLETE")
    owner = ProductionSessionMission(auth, store)
    owner.load_existing()
    mission = owner.open_trade_mission(positions=0, working_orders=0,
                                       unknown_external=False, in_window=True)
    mission.consume_attempt(candidate_fingerprint="candidate", token_id="token")
    mission.transition(MS.COMPLETE, "durable terminal record")

    accounting = OUTCOME.authorization_accounting(store, "PROD-FORENSIC-COMPLETE")
    assert accounting["trade_missions_used"] == 1
    assert accounting["filled_trades"] is None
    assert accounting["round_trips"] is None
