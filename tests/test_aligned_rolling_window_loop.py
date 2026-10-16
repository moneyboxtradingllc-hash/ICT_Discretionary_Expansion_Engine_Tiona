"""N1: retained formation custody through the real ProductionLoop's aligned window.

The candle store replays Codex's natural W5 seed, the P2H healthy bearish 5m
formation (validated by the 14:55 bucket, first visible at the 14:59 scan) and
a quiet non-raiding tail, minute by minute. ProductionLoop._scan_once fetches
300 bars and keeps CONT.coherent_window's 15m-aligned slice. The store is full
at 17:59 (13:00-17:59, 300 bars); at 18:00 the aligned window is 13:15-18:00
(286 bars), it regrows to 300 by 18:14, and shrinks again at 18:15, 18:30 and
18:45.

At f822371 every such step raised rolling_context_unavailable: derived state
stopped being current and the formation was dropped at 18:00 for good (CP3,
N1). The existing F loop test ends at 15:06 with a 127-bar window and never
reaches a full sliding window. Here the window slides through four alignment
steps, without the Brain and in both cognition lanes.
"""
from datetime import datetime, timedelta

import pytest

import test_campaign_scope as T
import test_po3_execution_identity as X
import test_production_scan_loop as P
import test_reversal_foundation_proof_closure as RF
from broker import topstepx_production_loop as PL
from broker import topstepx_session_authorization as SA
from broker.luna_candidate_producer import CandidateProducer
from broker.topstepx_client import TopstepXContract
from broker.topstepx_production_session import ProductionSession
from broker.topstepx_quote_provider import LiveQuoteProvider

MNQ = TopstepXContract(id=T.CONTRACT, name="MNQZ6", description="MNQ",
                       tick_size=0.25, tick_value=0.5, active=True)
FORMATION = ("bearish", "5m")
STEPS = {"18:00": ("13:15", 286), "18:15": ("13:30", 286),
         "18:30": ("13:45", 286), "18:45": ("14:00", 286)}


def _tail(until):
    """Monotone, non-raiding minutes from 15:05 through `until`."""
    rows, high = [], 29505.0
    at = datetime.fromisoformat("2026-08-19T15:05:00+00:00")
    while at.strftime("%H:%M") <= until:
        rows.append((at.strftime("%H:%M"), high, high - 1.0, high - 0.75))
        high -= 0.25
        at += timedelta(minutes=1)
    return rows


class _Candles:
    def __init__(self, tape):
        self.tape, self.end = tape, 0

    def fetch_1m_candles(self, symbol, lookback_bars=300):
        return [dict(bar) for bar in self.tape[:self.end][-lookback_bars:]]


def _run(root, monkeypatch, *, until, brain_from=None, ecu=False, missed=None):
    """Scan every minute through `until`, except the minutes inside the
    inclusive `missed` range. Returns one row per scanned minute, the Brain
    payloads and the count of live Po3 stability advances."""
    from live_scan.production_scan_cycle import ProductionScanCycle
    from structure.po3_alignment_manager import Po3StabilityManager
    X._isolate(root, monkeypatch)
    head = T._tape()[:106]
    tape = head + X._bars(list(X._P2H) + _tail(until), head[-1]["close"])
    clock = [datetime.fromisoformat(tape[0]["timestamp"])]
    venue = P.Session(place=lambda payload: (_ for _ in ()).throw(P.VenueTouched("venue reached")))
    runtime = P.Runtime(venue.market_hub)
    quotes = LiveQuoteProvider(venue.market_hub, MNQ, clock=lambda: clock[0])
    session = ProductionSession(session=venue, account_fingerprint=P.FP, contract=MNQ,
                                mission_id="M", store_dir=str(root), runtime=runtime,
                                quote_provider=quotes, clock=lambda: clock[0],
                                fill_deadline_seconds=0.2)
    auth = P.authorization(root, session_id="N1", contract_id=T.CONTRACT,
                           session_date="20260819", decision_window="09:30-16:00",
                           issued_at="2026-08-19T13:00:00+00:00")
    mission = SA.ProductionSessionMission(authorization=auth, store_dir=str(root))
    cycle = ProductionScanCycle(symbol="MNQ", contract_id=T.CONTRACT, session_id="N1",
                                quote_provider=quotes)
    candles = _Candles(tape)
    loop = PL.ProductionLoop(
        production_session=session, session_mission=mission,
        producer=CandidateProducer(account_fingerprint=P.FP, contract=MNQ),
        candles=candles, runtime=runtime, account_id=77, armed=False,
        scan_cycle=cycle, clock=lambda: clock[0], in_window=lambda: True)
    advances = []
    original = Po3StabilityManager.update

    def counted(instance, results):
        if instance is cycle.po3_stability:
            advances.append(True)
        return original(instance, results)
    monkeypatch.setattr(Po3StabilityManager, "update", counted)
    calls, rows = [], {}
    for end in range(20, len(tape) + 1):
        bar = tape[end - 1]
        hm = bar["timestamp"][11:16]
        if missed and missed[0] <= hm <= missed[1]:
            continue
        candles.end = end
        clock[0] = datetime.fromisoformat(bar["timestamp"]) + timedelta(minutes=1)
        venue.market_hub.emit("GatewayQuote", [T.CONTRACT, {
            "bestBid": bar["close"], "bestAsk": bar["close"] + MNQ.tick_size}])
        brain = brain_from is not None and hm >= brain_from
        if hm == brain_from:
            RF._mock_current_brain(monkeypatch, calls)
            monkeypatch.setenv("BRAIN_ECU_MODE", "true" if ecu else "false")
        before = len(calls)
        result = loop._scan_once(invoke_brain=brain)
        window = (loop.last_window or {}).get("window") or []
        records = cycle.reversal_formation_custody._records
        rows[hm] = dict(
            result=result, brain_calls=len(calls) - before,
            payload=calls[-1] if len(calls) > before else None,
            first=window[0]["timestamp"][11:16], bars=len(window),
            current=cycle.derived_state_is_current(),
            coverage=dict(cycle._chronology_coverage),
            revision=(cycle._history.revision, cycle._derived_revision),
            tip=cycle._processed_tip, window_tip=window[-1]["timestamp"],
            formation=({k: records[FORMATION].get(k) for k in
                        ("validation_timestamp", "anchor_identity", "history_revision")}
                       if FORMATION in records else None))
    return rows, calls, advances, tape


@pytest.fixture(scope="module")
def no_brain(tmp_path_factory):
    with pytest.MonkeyPatch.context() as mp:
        yield _run(tmp_path_factory.mktemp("no-brain"), mp, until="18:46")


def test_the_loop_offers_genuinely_aligned_shrinking_windows(no_brain):
    rows, _, _, _ = no_brain
    assert (rows["17:59"]["first"], rows["17:59"]["bars"]) == ("13:00", 300)
    for hm, step in STEPS.items():
        assert (rows[hm]["first"], rows[hm]["bars"]) == step, hm
    assert (rows["18:14"]["first"], rows["18:14"]["bars"]) == ("13:15", 300)


def test_no_brain_long_window_keeps_derived_state_current_every_minute(no_brain):
    rows, calls, advances, tape = no_brain
    assert calls == []
    for hm, row in rows.items():
        if hm < "13:59":
            # Fewer than the loop's 60 coherent bars: no scan at all.
            assert row["result"]["outcome"] == PL.NO_CANDLES, hm
            continue
        assert row["current"] is True, (hm, row["coverage"])
        assert row["coverage"]["complete"] is True, hm
        assert row["revision"] == (0, 0), hm
        assert row["tip"] == row["window_tip"], hm
        if hm > "13:59":
            assert row["coverage"]["catch_up_bars"] == 0, hm
    # Every settled minute advanced live mechanics exactly once: the first
    # scan replays its 60 prefixes, every later scan settles one new minute.
    assert len(advances) == len(tape)


def test_retained_formation_survives_every_alignment_step(no_brain):
    rows, _, _, _ = no_brain
    held = [hm for hm in rows if hm >= "14:59"]
    first = rows["14:59"]["formation"]
    assert first is not None and first["validation_timestamp"].startswith("2026-08-19T14:55")
    for hm in held:
        assert rows[hm]["formation"] == first, hm
    assert rows["14:58"]["formation"] is None


@pytest.mark.parametrize("ecu", [False, True], ids=["non-ecu", "ecu"])
def test_both_lanes_carry_current_custody_across_the_step(tmp_path, monkeypatch, ecu):
    rows, calls, advances, tape = _run(tmp_path, monkeypatch, until="18:01",
                                       brain_from="17:59", ecu=ecu)
    assert len(calls) == 3
    for hm in ("17:59", "18:00", "18:01"):
        row = rows[hm]
        assert row["brain_calls"] == 1, hm
        payload = row["payload"]
        assert payload["derived_state"] == {
            "history_revision": 0, "derived_revision": 0, "current": True}, hm
        assert payload["active_path_state"]["state_available"] is True, hm
        po3 = [r for r in payload["authorized_tool_catalog"]
               if r.get("tool_family") == "po3_reversal_order_block"]
        assert po3 and {r.get("direction") for r in po3} == {"bearish"}, hm
        assert row["formation"] is not None, hm
        # The consumer still applies its own gates: with no Draw, the campaign
        # Lifecycle refuses; nothing is refused for stale derived state.
        assert row["result"]["outcome"] == PL.NO_CANDIDATE, row["result"]
        assert row["result"]["reason"] == "campaign_lifecycle_refused", row["result"]
    assert rows["18:00"]["bars"] == 286
    assert len(advances) == len(tape)


# ── N1 + D: missed-scan reconstruction ────────────────────────────────────────
# After a normal 19:29 scan (aligned window 14:30-19:29, 300 bars) the loop
# misses 19:30-19:38. At 19:39 it fetches 300 bars, keeps the aligned
# 14:45-19:39 (295 bars) and the rolling catch-up replays the nine missed
# prefixes. Each is rebuilt as the newest 295 bars of the joined history up to
# its cutoff (14:36-19:30 ... 14:44-19:38), a length slice that is NOT bucket
# aligned, so its leading 5m bucket (14:35, then 14:40) has fewer than five
# constituents. Formation custody must read that truncated bucket as rollout
# (D, aefa3bb) or it drops the retained bearish 5m formation for good.
# An every-minute aligned window always starts on a 15m boundary and never
# presents a truncated leading 5m bucket, so ordinary rollout does not need D.
MISSED = ("19:30", "19:38")


def _leading_buckets(monkeypatch):
    """Spy on custody: record every check whose source-timeframe history
    starts with a truncated bucket."""
    from market_data import reversal_formation as R
    seen, original = [], R.ReversalFormationCustody._still_current

    def spy(self, snapshot, record, revision, contract, session,
            canonical_timeframes, releases=None):
        result = original(self, snapshot, record, revision, contract, session,
                          canonical_timeframes, releases)
        index = R.ReversalFormationCustody._history_index(
            canonical_timeframes, record.get("source_tf"))
        lead = min(index) if index else None
        if lead is not None and R._truncated_bucket(index[lead]):
            seen.append(dict(cutoff=snapshot["timestamp"][11:16], lead=lead[11:16],
                             members=index[lead].get("members"),
                             witness=lead in (record.get("witness_bars") or {}),
                             current=result))
        return result
    monkeypatch.setattr(R.ReversalFormationCustody, "_still_current", spy)
    return seen


@pytest.fixture(scope="module")
def missed_scan(tmp_path_factory):
    with pytest.MonkeyPatch.context() as mp:
        seen = _leading_buckets(mp)
        yield _run(tmp_path_factory.mktemp("missed"), mp, until="19:39",
                   missed=MISSED), seen


def test_missed_scan_reconstruction_keeps_the_formation(missed_scan):
    (rows, calls, advances, tape), seen = missed_scan
    assert calls == []
    assert not any(MISSED[0] <= hm <= MISSED[1] for hm in rows)
    assert (rows["19:29"]["first"], rows["19:29"]["bars"]) == ("14:30", 300)
    after = rows["19:39"]
    assert (after["first"], after["bars"]) == ("14:45", 295)
    assert after["current"] is True, after["coverage"]
    assert after["coverage"]["complete"] is True
    assert after["coverage"]["catch_up_bars"] == 9
    assert after["revision"] == (0, 0) and after["tip"] == after["window_tip"]
    assert after["formation"] is not None
    assert after["formation"] == rows["19:29"]["formation"] == rows["14:59"]["formation"]
    assert len(advances) == len(tape)


def test_only_the_reconstructed_prefixes_present_a_truncated_witness(missed_scan):
    (rows, _, _, _), seen = missed_scan
    # The cold start replays its own prefixes (13:00-13:58); after it, only the
    # nine reconstructed catch-up prefixes start mid-bucket.
    late = [s for s in seen if s["cutoff"] > "13:59"]
    assert late, "the reconstructed-prefix path was not exercised"
    assert {s["cutoff"] for s in late} <= {f"19:{m}" for m in range(30, 39)}
    assert {s["lead"] for s in late} == {"14:35", "14:40"}
    assert any(s["witness"] and s["lead"] == "14:35" for s in late)
    assert all(s["current"] is True for s in late)


def test_d_parent_predicate_loses_the_formation_on_reconstruction(tmp_path, monkeypatch):
    # Activated control. With the truncated-bucket predicate disabled,
    # _still_current is the D-parent (55582a9) check: the truncated leading
    # bucket counts as coverage and its digest no longer matches the witness.
    from market_data import reversal_formation as R
    monkeypatch.setattr(R, "_truncated_bucket", lambda bar: False)
    rows, calls, _, _ = _run(tmp_path, monkeypatch, until="19:39", missed=MISSED)
    assert calls == []
    assert rows["19:29"]["formation"] == rows["14:59"]["formation"] is not None
    assert rows["19:39"]["coverage"]["catch_up_bars"] == 9
    assert rows["19:39"]["current"] is True
    assert rows["19:39"]["formation"] is None
