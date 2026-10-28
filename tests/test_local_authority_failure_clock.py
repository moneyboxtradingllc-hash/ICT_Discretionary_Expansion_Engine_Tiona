"""LOCAL-AUTHORITY-FAILURE-CLOCK-20261027 -- one clock domain for the composite.

`failure_available_at` must be the CLOSE of the failure's settled source bucket,
the same domain as the body/structure completion edges (`source + timeframe`).
The native `settled_edge_time` (snapshot_builder.settled_source_provenance) is
the OPEN of the bucket's terminal 1m constituent: it proves which bucket was
complete, never a close by itself. Native fields are read, never rewritten.

The producer cases drive the REAL ProductionScanCycle over the constructed
stretched 15m tape (`local_authority_loop.stretched_tape`): the healthy 3m
failure (17:09 bucket, closes 17:12) precedes the 17:15 completion; the
simultaneous variant flattens ONLY the 17:09-17:11 1m bars (lawful OHLC 29240),
moving the real failure into the 17:12 bucket, which closes at 17:15 -- the
completion edge -- so the strict ordering refuses. Nothing is injected into a
producer, certificate or packet.
"""
from __future__ import annotations

import copy
import json
from datetime import datetime, timedelta

import pytest

import local_authority_loop as H
import test_protected_structure_continuity as P
from broker import topstepx_production_loop as PL
from live_scan.production_scan_cycle import ProductionScanCycle
from market_data import local_authority as LA

STRETCH = {"anchor": "15:00", "shift_hours": -2}
SWITCHES = ("EXECUTION_ENABLED", "ALLOW_PAPER_ORDERS", "AUTO_EXECUTION_ENABLED",
            "TOPSTEPX_ARM_ORDERS")


def _at(hm, seconds=0):
    return datetime.fromisoformat(P._cut(hm)) + timedelta(seconds=seconds)


def _failure(tf, source, edge, **extra):
    row = {"owner": "bullish", "source_tf": tf, "level": 29234.25, "side": "low",
           "occurrence_id": f"PROTECTED_SWING_VIOLATED:{P.C}:{tf}:x", **extra}
    if source is not None:
        row["source_bar_time"] = source if "T" in str(source) else P._cut(source)
    if edge is not None:
        row["settled_edge_time"] = edge if ("T" in str(edge) or ":" not in str(edge)) \
            else P._cut(edge)
    return row


# ── the clock itself ──────────────────────────────────────────────────────────
@pytest.mark.parametrize("tf,source,edge,expected", [
    ("1m", "12:00", None, "12:01"),           # pass-through minute: no member list
    ("1m", "12:00", "12:00", "12:01"),        # a 1m terminal constituent is itself
    ("3m", "17:09", "17:11", "17:12"),        # healthy: terminal 17:11 open, closes 17:12
    ("3m", "17:12", "17:14", "17:15"),        # simultaneous with a 17:15 completion
    ("3m", "17:09", None, "17:12"),           # no edge: the canonical bucket close
    ("5m", "16:20", "16:24", "16:25"),
    ("15m", "17:00", "17:14", "17:15"),
], ids=["1m_no_edge", "1m_edge", "3m_healthy", "3m_simultaneous", "3m_no_edge", "5m", "15m"])
def test_failure_availability_is_the_source_bucket_close(tf, source, edge, expected):
    failure = _failure(tf, source, edge)
    before = copy.deepcopy(failure)
    assert LA.failure_available_at(failure) == _at(expected)
    assert failure == before                    # native fields are never rewritten


@pytest.mark.parametrize("tf,source,edge", [
    ("1m", "12:00", "11:59"),                   # edge outside the bucket
    ("3m", "17:09", "17:12"),                   # edge is the NEXT bucket's minute
    ("3m", "17:09", "17:08"),                   # edge before the bucket opened
    ("15m", "17:00", "17:15"),
    ("3m", "17:09", "2026-10-23T17:11:30+00:00"),  # not a constituent minute
    ("3m", "17:09", "garbage"),
    ("2m", "17:00", None),                      # unknown timeframe
    ("3m", None, "17:11"),                      # no source bucket
    ("3m", "garbage", "17:11"),
], ids=["1m_edge_mismatch", "edge_next_bucket", "edge_before_open", "15m_edge_at_close",
        "edge_not_minute", "edge_malformed", "unknown_tf", "no_source", "source_malformed"])
def test_inconsistent_or_unprovable_failure_clock_proves_nothing(tf, source, edge):
    assert LA.failure_available_at(_failure(tf, source, edge)) is None
    assert LA.failure_available_at(None) is None and LA.failure_available_at("x") is None


def test_the_legacy_edge_alone_is_never_the_availability():
    """The defect: returning the terminal OPEN put a 3m failure one minute early."""
    failure = _failure("3m", "17:12", "17:14")
    assert LA.failure_available_at(failure) != LA._dt(failure["settled_edge_time"])
    assert LA.failure_available_at(failure) - LA._dt(failure["settled_edge_time"]) \
        == timedelta(minutes=1)


# ── actual producer trajectories ─────────────────────────────────────────────
def _simultaneous(tape):
    out = copy.deepcopy(tape)
    for bar in out:
        if bar["timestamp"] in (P._cut("17:09"), P._cut("17:10"), P._cut("17:11")):
            bar.update(open=29240.0, high=29240.0, low=29240.0, close=29240.0)
    return out


def _producer_walk(tmp_path, tape, tag):
    """The real cycle, minute by minute, the way the loop drives it."""
    with pytest.MonkeyPatch.context() as m:
        for key in ("OCCURRENCE_LEDGER_DIR", "AI_BRAIN_DIR", "AI_RETRIEVAL_DIR",
                    "REPLAY_SESSIONS_DIR"):
            m.setenv(key, str(tmp_path / tag / key))
        cycle = ProductionScanCycle(symbol="MNQ", contract_id=P.C, session_id=f"CLOCK-{tag}",
                                    local_authority_profile=LA.OFFLINE_TEST_PROFILE_V1)
        walk = {}
        for hm in ["16:00"] + H.minutes("17:00", "17:16"):
            cut = P._cut(hm)
            bars = [b for b in tape if b["timestamp"] <= cut][-300:]
            scan = cycle.scan(bars, now=datetime.fromisoformat(cut) + timedelta(minutes=1),
                              invoke_brain=False)
            path = scan["snapshot"]["active_path_state"]
            walk[hm] = {"packet": copy.deepcopy(cycle.local_authority._generation),
                        "failure": copy.deepcopy(path.get("last_invalidated")),
                        "events": copy.deepcopy(cycle.local_authority.diagnostics[-1]["events"]),
                        "route": LA.local_refinements(path).get("delivery_change")}
    return walk


@pytest.fixture(scope="module")
def trajectories(tmp_path_factory):
    tape = H.stretched_tape(P.TAPE, **STRETCH)
    root = tmp_path_factory.mktemp("failure_clock")
    return {"healthy": _producer_walk(root, tape, "healthy"),
            "simultaneous": _producer_walk(root, _simultaneous(tape), "simultaneous")}


def test_healthy_earlier_failure_still_completes_the_15m_composite(trajectories):
    walk = trajectories["healthy"]
    published = {hm: row["packet"] for hm, row in walk.items() if row["packet"]}
    assert min(published) == "17:14"            # nothing before completion (prefix)
    packet = published["17:14"]
    failure = packet["failure"]
    assert (failure["source_tf"], failure["source_bar_time"]) == ("3m", P._cut("17:09"))
    assert failure["available_at"] == P._cut("17:12")      # the 3m bucket's close
    assert packet["completed_at"] == P._cut("17:15")
    assert LA._dt(failure["available_at"]) < LA._dt(packet["completed_at"])
    # The native ActivePath failure keeps its own clocks untouched.
    native = walk["17:14"]["failure"]
    assert native["source_bar_time"] == P._cut("17:09")
    assert native["settled_edge_time"] == P._cut("17:11")
    assert walk["17:14"]["route"]


def test_simultaneous_failure_and_completion_publish_no_composite(trajectories):
    walk = trajectories["simultaneous"]
    native = walk["17:15"]["failure"]
    # The real failure moved into the 17:12 bucket, knowable at its 17:15 close.
    assert (native["source_tf"], native["source_bar_time"]) == ("3m", P._cut("17:12"))
    assert native["settled_edge_time"] == P._cut("17:14")
    assert LA.failure_available_at(native) == _at("17:15")
    assert all(row["packet"] is None and not row["route"] for row in walk.values())
    reasons = {e.get("reason") for row in walk.values() for e in row["events"]}
    assert "confirmation_not_after_settled_failure" in reasons


@pytest.mark.parametrize("ecu", [True, False], ids=["ecu", "non_ecu"])
def test_simultaneous_case_reaches_no_composite_route_through_the_launch_built_loop(
        tmp_path_factory, ecu):
    tape = _simultaneous(H.stretched_tape(P.TAPE, **STRETCH))
    with pytest.MonkeyPatch.context() as m:
        for name in SWITCHES:
            m.setenv(name, "true")
        m.setattr(LA, "RELEASE_SELECTION", LA.PRODUCTION_PROFILE_V1)   # CONTROLLED fixture
        result = H.run(m, tmp_path_factory.mktemp(f"clock_loop_{ecu}"), ecu=ecu, profile=None,
                       warmup="16:00", schedule=H.minutes("17:10", "17:18"), act_from="17:12",
                       direction="bearish", tape=tape, launcher=True)
    assert result["cycle"].local_authority.profile is LA.PRODUCTION_PROFILE_V1
    routed = [s for s in result["scans"]
              if LA.local_refinements(s["snapshot"]["active_path_state"]).get("delivery_change")]
    assert routed == []
    payload = json.dumps(result["scans"][-1]["brain_input"], default=str)
    assert "raid_reclaim_delivery_change" not in payload
    for hm, out in result["outputs"].items():
        if out.get("outcome") == PL.QUALIFIED_CANDIDATE_OBSERVED:
            # Any candidate here is a native route, never the refused composite.
            assert "ldc:" not in json.dumps(out, default=str), hm
    assert result["zero_orders"] and result["tokens"] == 0 and result["attempts"] == 0
