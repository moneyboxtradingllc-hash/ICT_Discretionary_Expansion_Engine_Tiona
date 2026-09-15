"""V1 profile evidence is tape-derived, complete-or-unavailable, and observational."""
from __future__ import annotations

from datetime import datetime, timezone

from data_feed.volume_profile import profile_from_minutes, with_price_location
from market_data.vap_provider import VapCaptureProvider

UTC = timezone.utc
CONTRACT = "CON.F.US.MNQ.U26"


def row(minute, levels, *, status="COMPLETE"):
    return {"minute": minute, "status": status, "tick_size": 0.25,
            "levels": levels}


def test_identical_prints_count_but_identical_batch_replay_does_not(tmp_path):
    capture = VapCaptureProvider(contract_id=CONTRACT, tick_size=.25, store_dir=str(tmp_path))
    capture._attached_minute = datetime(2026, 9, 15, 14, 0, tzinfo=UTC)
    args = [CONTRACT, [{"contractId": CONTRACT, "price": 25000.0, "volume": 1,
                        "timestamp": "2026-09-15T14:01:01+00:00"},
                       {"contractId": CONTRACT, "price": 25000.0, "volume": 1,
                        "timestamp": "2026-09-15T14:01:01+00:00"}]]
    assert capture._ingest_event(args, 1) == 2
    assert capture._ingest_event(args, 1) == 0
    bucket = next(iter(capture._open.values()))
    assert sum(bucket["levels"].values()) == 2


def test_rejects_naive_off_grid_and_nonpositive_volume(tmp_path):
    c = VapCaptureProvider(contract_id=CONTRACT, tick_size=.25, store_dir=str(tmp_path))
    assert not c._ingest_trade({"contractId": CONTRACT, "price": 1, "volume": 1,
                                "timestamp": "2026-09-15T10:00:00"}, 1)
    assert not c._ingest_trade({"contractId": CONTRACT, "price": 1.1, "volume": 1,
                                "timestamp": "2026-09-15T10:00:00+00:00"}, 1)
    assert not c._ingest_trade({"contractId": CONTRACT, "price": 1, "volume": 0,
                                "timestamp": "2026-09-15T10:00:00+00:00"}, 1)


def test_profile_math_ties_and_location_are_deterministic():
    records = [row("2026-09-10T14:00:00+00:00", {400: 10, 401: 20, 402: 20, 403: 10})]
    out = profile_from_minutes(records, start="2026-09-10T14:00:00+00:00",
                               end="2026-09-10T14:01:00+00:00")
    # VWAP is exactly halfway between tied POCs; lower wins the documented tie.
    assert out["poc"] == 100.25
    assert out["vwap"] == 100.375
    # The final adjacent tie includes BOTH levels rather than biasing a side.
    assert out["val"] == 100.0 and out["vah"] == 100.75
    located = with_price_location(out, 101.0)
    assert located["price_location"] == "above_value"


def test_half_open_interval_and_incomplete_rows_are_not_profile_evidence():
    records = [row("2026-09-10T14:00:00+00:00", {400: 5}),
               row("2026-09-10T14:01:00+00:00", {401: 500}),
               row("2026-09-10T14:00:30+00:00", {402: 500}, status="INTERRUPTED")]
    out = profile_from_minutes(records, start="2026-09-10T14:00:00+00:00",
                               end="2026-09-10T14:01:00+00:00")
    assert out["total_volume"] == 5
    assert out["poc"] == 100.0


def test_volume_profile_is_not_delivered_to_brain_input():
    from ai_brain.brain_input import build_brain_input
    payload = build_brain_input({"timestamp": "2026-09-15T14:00:00+00:00",
                                 "volume_profile": {"available": True, "poc": 1}}, {})
    assert "volume_profile" not in payload
    assert "volume_profile" not in payload.get("market", {})
