from __future__ import annotations

import json
import os
import sys
import tempfile
from datetime import datetime, timedelta, timezone

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))

from broker.execution_observability import elapsed_seconds, invalidation_age  # noqa: E402
from broker import topstepx_slippage as SL  # noqa: E402
from broker import topstepx_submission_record as SUB  # noqa: E402


T0 = datetime(2026, 9, 11, 14, 0, tzinfo=timezone.utc)
CID = "CON.F.US.MNQ.U26"


def capture(at=T0):
    return SL.QuoteCapture(at, 29370.0, 29370.25, 29370.0, CID, 0.2)


def test_invalidation_age_uses_structural_evidence_timestamp():
    age = invalidation_age(evidence_timestamp=T0.isoformat(),
                           observed_at=T0 + timedelta(seconds=37))
    assert age["status"] == "KNOWN"
    assert age["seconds"] == pytest.approx(37.0)


@pytest.mark.parametrize("value", [None, "not-a-time"])
def test_invalidation_age_unknown_never_becomes_zero(value):
    age = invalidation_age(evidence_timestamp=value, observed_at=T0)
    assert age["status"] == "UNKNOWN"
    assert age["seconds"] is None


def test_entry_latency_uses_quote_time_and_full_fill_completion():
    observed = SL.measure_entry(
        capture=capture(), direction="buy", fill_price=29370.416667,
        quantity=3, tick_size=0.25, tick_value=0.5, contract_id=CID,
        request_at=T0 + timedelta(milliseconds=1),
        fill_at=T0 + timedelta(seconds=5),
        fill_order_id=7, expected_order_id=7, attribution="EXPANSION_BOT")
    assert observed["quote_observation_timestamp"] == T0.isoformat()
    assert observed["full_fill_vwap"] == pytest.approx(29370.416667)
    assert observed["full_fill_completion_timestamp"] == (T0 + timedelta(seconds=5)).isoformat()
    assert observed["quote_to_full_fill_seconds"] == pytest.approx(5.0)
    assert observed["entry_price_drift_points"] == pytest.approx(0.166667, abs=1e-6)
    assert observed["entry_price_drift_ticks"] == pytest.approx(0.6667)


def test_multi_fill_completion_timestamp_string_is_supported():
    observed = SL.measure_entry(
        capture=capture(), direction="buy", fill_price=29370.416667,
        quantity=3, tick_size=0.25, tick_value=0.5, contract_id=CID,
        request_at=T0, fill_at=(T0 + timedelta(seconds=5)).isoformat(),
        attribution="EXPANSION_BOT")
    assert observed["quote_to_full_fill_seconds"] == pytest.approx(5.0)


def test_missing_fill_time_keeps_latency_unknown():
    observed = SL.measure_entry(
        capture=capture(), direction="buy", fill_price=29370.25,
        quantity=1, tick_size=0.25, tick_value=0.5, contract_id=CID,
        request_at=T0, fill_at=None, attribution="EXPANSION_BOT")
    assert observed["quote_to_full_fill_seconds"] is None
    assert observed["full_fill_completion_timestamp"] is None


def test_submission_record_durably_carries_invalidation_age():
    with tempfile.TemporaryDirectory(dir=ROOT) as directory:
        row = SUB.open_submission(
            store_dir=directory, session_id="S1", mission_id="S1-T1",
            payload={"contractId": CID, "size": 1}, custom_tag="tag",
            geometry={"structural_invalidation": {
                "structure_identity": "INV_A", "evidence_timestamp": T0.isoformat()}})
        path = os.path.join(directory, "submissions_S1.jsonl")
        disk = json.loads(open(path, encoding="utf-8").readline())
        assert row["observability"]["invalidation_age"]["status"] == "KNOWN"
        assert disk["observability"]["invalidation_age"]["seconds"] >= 0
