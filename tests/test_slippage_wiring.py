"""WIRE-LIVE-SLIPPAGE-CAPTURE — capture and measurement inside the real runner.

Every test drives the production components. The venue seam raises if reached,
so "no order endpoint is called" is proven by construction.
"""
from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timedelta, timezone

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src"))

from broker import topstepx_execution_runner as R                  # noqa: E402
from broker import topstepx_session_ledger as LG                   # noqa: E402
from broker import topstepx_slippage as SL                         # noqa: E402
from broker import topstepx_smoke_auth as auth                     # noqa: E402
from broker.topstepx_candidate_freshness import (                  # noqa: E402
    CandidateSnapshot, LiquidityObjective,
)
from broker.topstepx_client import TopstepXContract                # noqa: E402
from broker.topstepx_combine_risk import (build_production_bracket,   # noqa: E402
                                          PRODUCTION_MAX_RISK_USD)

CID = "CON.F.US.MNQ.U26"
FP = "acct:fc84f7a928d9"
NOW = datetime(2026, 8, 5, 15, 30, tzinfo=timezone.utc)
MNQ = TopstepXContract(id=CID, name="MNQU6", description="MNQ",
                       tick_size=0.25, tick_value=0.5, active=True)
VOL = {"volatility_state": "expansion", "expansion_state": "expanding",
       "structural_level_identity": "protected_swing_low@29700"}


class VenueTouched(AssertionError):
    """The order path was reached. Never allowed in these tests."""


class BlockedSession:
    def __init__(self, positions=None, orders=None):
        self._p, self._o = list(positions or []), list(orders or [])
        self.place_calls = 0

    def open_positions(self):
        return list(self._p)

    def open_orders(self):
        return list(self._o)

    def place_order(self, payload):
        self.place_calls += 1
        raise VenueTouched("place_order reached")

    def cancel_order(self, oid):
        raise VenueTouched("cancel_order reached")

    def close_position(self, cid):
        raise VenueTouched("close_position reached")


def objective(price=29790.0):
    return LiquidityObjective("prior_session_high@29790.0", "prior_session_high",
                              price, NOW - timedelta(minutes=2))


def snapshot(direction="bullish", entry=29760.0, stop=None, target=None):
    # A bearish thesis inverts the geometry: stop ABOVE entry, target BELOW.
    if stop is None:
        stop = 29750.0 if direction == "bullish" else 29770.0
    if target is None:
        target = 29790.0 if direction == "bullish" else 29730.0
    return CandidateSnapshot(
        candidate_id="cand-A", snapshot_id="snap-1", direction=direction,
        entry_price=entry, invalidation_price=stop, objective=objective(target),
        contract_id=CID, account_fingerprint=FP, created_at=NOW - timedelta(minutes=1),
        narrative="bullish continuation")


def market(**over):
    kw = dict(current_price=29760.0, high_since=29762.0, low_since=29758.0,
              tick_size=0.25, snapshot_id="snap-1", contract_id=CID,
              account_fingerprint=FP, account_state_digest="", data_age_seconds=2.0,
              in_window=True, manual_activity=False, now=NOW)
    kw.update(over)
    return kw


def quote(bid=29759.75, ask=29760.0, age=0.3, at=None, cid=CID):
    return SL.QuoteCapture(captured_at=at or NOW, best_bid=bid, best_ask=ask,
                           last_trade=bid, contract_id=cid,
                           market_data_age_seconds=age, volatility_state="expansion")


def runner(session=None, cs=None, direction="bullish"):
    cs = cs or snapshot(direction=direction)
    s = session or BlockedSession()
    r = R.ExecutionRunner(session=s, account_fingerprint=FP, contract=MNQ,
                          clock=lambda: NOW)
    r.confirm_readiness({"verdict": "READY"})
    r._to(R.WAITING_FOR_CANDIDATE, "ready")
    out = build_production_bracket(
        direction=cs.direction, entry_price=cs.entry_price,
        invalidation_level=cs.invalidation_price, target_price=cs.objective.price,
        contract=MNQ, evidence=VOL)
    r.geometry = out["geometry"]
    return r, s, cs


def mint(cs):
    return lambda: auth.issue(
        phrase=auth.AUTHORIZATION_PHRASE, account_fingerprint=FP, contract_id=CID,
        candidate_fingerprint=cs.fingerprint(), snapshot_id=cs.snapshot_id,
        direction=cs.direction, stop_price=cs.invalidation_price,
        target_price=cs.objective.price, target_identity=cs.objective.identity,
        # The token must authorize what production doctrine sizes to. A literal
        # here is a mirror: when the cap moved to $350 the runner sized past a
        # $250 token and halted before ever reaching the venue.
        max_risk_usd=PRODUCTION_MAX_RISK_USD, max_contracts=15, now=NOW)


def ledger(tmp_path):
    return LG.SessionLedger.load_or_new(FP, "20260805", str(tmp_path))


# ══════════════════════════════════════════════════════════════════════════════
class TestCaptureOrdering:

    def test_capture_happens_after_gates_and_before_persistence(self, tmp_path):
        order = []
        r, s, cs = runner()

        def qp():
            order.append("capture")
            return quote()

        with pytest.raises(R.RunnerHalt):
            r.gated_submit(account_id=1, ledger=ledger(tmp_path), candidate_snapshot=cs,
                           market=market(), latest_price=29760.0, mint_token=mint(cs),
                           quote_provider=qp,
                           on_attempt_consumed=lambda t: order.append("persist"))
        assert order == ["capture", "persist"]

    def test_a_failed_gate_never_captures(self, tmp_path):
        order = []
        r, s, cs = runner()
        with pytest.raises(R.RunnerHalt):
            r.gated_submit(account_id=1, ledger=ledger(tmp_path), candidate_snapshot=cs,
                           market=market(low_since=29740.0),   # invalidation touched
                           latest_price=29760.0, mint_token=mint(cs),
                           quote_provider=lambda: order.append("capture") or quote())
        assert order == [] and s.place_calls == 0

    def test_capture_failure_does_not_block_execution(self, tmp_path):
        """Evidence must never leave an authorized position unprotected."""
        r, s, cs = runner()

        def boom():
            raise RuntimeError("hub unavailable")

        with pytest.raises(R.RunnerHalt):
            r.gated_submit(account_id=1, ledger=ledger(tmp_path), candidate_snapshot=cs,
                           market=market(), latest_price=29760.0, mint_token=mint(cs),
                           quote_provider=boom)
        assert r.capture_failure == "RuntimeError"
        assert s.place_calls == 1        # submission still attempted
        assert r.entry_capture is None

    def test_capture_performs_no_network_call(self):
        import inspect
        src = inspect.getsource(SL.capture_quote)
        for banned in ("requests", "urlopen", "sleep", "poll", "_post"):
            assert banned not in src


class TestReferenceSide:

    def test_a_buy_uses_the_ask(self):
        assert quote().executable_reference("buy") == 29760.0

    def test_a_sell_uses_the_bid(self):
        assert quote().executable_reference("sell") == 29759.75

    def test_midpoint_and_last_are_not_used_as_the_reference(self):
        q = quote(bid=29750.0, ask=29760.0)
        ref = q.executable_reference("buy")
        assert ref == 29760.0 and ref != q.last_trade
        assert ref != (q.best_bid + q.best_ask) / 2


class TestEntryMeasurement:

    def _filled(self, tmp_path, fills=None, fill_price=29760.5):
        r, s, cs = runner()
        r.entry_capture = quote()
        r.submit_at = NOW
        r.ack_at = NOW + timedelta(milliseconds=180)
        r.order_id = 5001
        led = SL.SlippageLedger(path=str(tmp_path / "slip.jsonl"))
        obs = r.measure_entry_slippage(
            fill_event={"price": fill_price, "size": 1, "trade_id": 9001,
                        "at": NOW + timedelta(milliseconds=900)},
            candidate_snapshot=cs, ledger=led, fills=fills)
        return r, cs, led, obs

    def test_the_entry_links_to_its_candidate(self, tmp_path):
        _, cs, _, obs = self._filled(tmp_path)
        assert obs["candidate_id"] == cs.candidate_id == "cand-A"
        assert obs["snapshot_id"] == "snap-1"

    def test_a_long_entry_measures_fill_minus_ask(self, tmp_path):
        _, _, _, obs = self._filled(tmp_path, fill_price=29760.5)
        assert obs["expected_price"] == 29760.0
        assert obs["slippage_ticks"] == pytest.approx(2.0)
        assert obs["reliable"] is True

    def test_the_raw_observation_is_persisted(self, tmp_path):
        _, _, led, _ = self._filled(tmp_path)
        row = json.loads(open(led.path, encoding="utf-8").readline())
        assert row["kind"] == "ENTRY" and row["actual_fill_price"] == 29760.5

    def test_partial_entry_fills_aggregate_by_vwap(self, tmp_path):
        fills = [{"price": 29760.0, "size": 1, "orderId": 5001, "id": 1},
                 {"price": 29761.0, "size": 3, "orderId": 5001, "id": 2}]
        _, _, led, obs = self._filled(tmp_path, fills=fills)
        assert obs["actual_fill_price"] == pytest.approx(29760.75)   # (1*29760+3*29761)/4
        assert obs["quantity"] == 4
        assert obs["partial_fills"]["fill_count"] == 2

    def test_partial_fills_produce_one_observation(self, tmp_path):
        fills = [{"price": 29760.0, "size": 1, "orderId": 5001, "id": 1},
                 {"price": 29761.0, "size": 1, "orderId": 5001, "id": 2},
                 {"price": 29761.5, "size": 1, "orderId": 5001, "id": 3}]
        _, _, led, _ = self._filled(tmp_path, fills=fills)
        assert len(led.observations) == 1

    def test_fills_from_different_orders_cannot_aggregate(self, tmp_path):
        fills = [{"price": 29760.0, "size": 1, "orderId": 5001, "id": 1},
                 {"price": 29761.0, "size": 1, "orderId": 7777, "id": 2}]
        _, _, _, obs = self._filled(tmp_path, fills=fills)
        assert obs["reliable"] is False
        assert obs["partial_fills"]["aggregation_reliable"] is False


class TestExitMeasurement:

    def _r(self, direction="bullish"):
        r, s, cs = runner(direction=direction)
        r.order_id = 5001
        return r, cs

    def test_long_target_exit(self, tmp_path):
        r, cs = self._r()
        led = SL.SlippageLedger(path=str(tmp_path / "s.jsonl"))
        obs = r.measure_exit_slippage(
            exit_type=SL.EXIT_TARGET, requested_price=29790.0, fill_price=29789.75,
            quantity=1, quote_capture=quote(), candidate_snapshot=cs, ledger=led)
        assert obs["slippage_ticks"] == pytest.approx(1.0)     # sold 1 tick below
        assert obs["exit_side"] == "sell"

    def test_long_stop_exit(self, tmp_path):
        r, cs = self._r()
        obs = r.measure_exit_slippage(
            exit_type=SL.EXIT_STOP, requested_price=29750.0, fill_price=29749.5,
            quantity=1, quote_capture=quote(), candidate_snapshot=cs)
        assert obs["slippage_ticks"] == pytest.approx(2.0)

    def test_short_target_exit(self, tmp_path):
        r, cs = self._r(direction="bearish")
        obs = r.measure_exit_slippage(
            exit_type=SL.EXIT_TARGET, requested_price=29730.0, fill_price=29730.25,
            quantity=1, quote_capture=quote(), candidate_snapshot=cs)
        assert obs["exit_side"] == "buy"
        assert obs["slippage_ticks"] == pytest.approx(1.0)

    def test_short_stop_exit(self, tmp_path):
        r, cs = self._r(direction="bearish")
        obs = r.measure_exit_slippage(
            exit_type=SL.EXIT_STOP, requested_price=29770.0, fill_price=29770.5,
            quantity=1, quote_capture=quote(), candidate_snapshot=cs)
        assert obs["slippage_ticks"] == pytest.approx(2.0)

    def test_a_long_flatten_uses_the_bid(self, tmp_path):
        r, cs = self._r()
        obs = r.measure_exit_slippage(
            exit_type=SL.EXIT_EMERGENCY_FLATTEN, requested_price=None,
            fill_price=29759.75, quantity=1, quote_capture=quote(),
            candidate_snapshot=cs)
        assert obs["expected_price"] == 29759.75          # best bid
        assert obs["slippage_ticks"] == pytest.approx(0.0)

    def test_a_short_flatten_uses_the_ask(self, tmp_path):
        r, cs = self._r(direction="bearish")
        obs = r.measure_exit_slippage(
            exit_type=SL.EXIT_EMERGENCY_FLATTEN, requested_price=None,
            fill_price=29760.0, quantity=1, quote_capture=quote(),
            candidate_snapshot=cs)
        assert obs["expected_price"] == 29760.0          # best ask

    def test_a_flatten_is_not_compared_to_the_stop(self, tmp_path):
        """Comparing a market flatten to the original stop would be nonsense."""
        r, cs = self._r()
        obs = r.measure_exit_slippage(
            exit_type=SL.EXIT_EMERGENCY_FLATTEN, requested_price=None,
            fill_price=29759.75, quantity=1, quote_capture=quote(),
            candidate_snapshot=cs)
        assert obs["expected_price"] != cs.invalidation_price

    def test_partial_exit_fills_aggregate(self, tmp_path):
        r, cs = self._r()
        fills = [{"price": 29790.0, "size": 2, "orderId": 6001, "id": 1},
                 {"price": 29789.0, "size": 2, "orderId": 6001, "id": 2}]
        obs = r.measure_exit_slippage(
            exit_type=SL.EXIT_TARGET, requested_price=29790.0, fill_price=None,
            quantity=4, quote_capture=quote(), candidate_snapshot=cs, fills=fills)
        assert obs["actual_fill_price"] == pytest.approx(29789.5)
        assert obs["quantity"] == 4


class TestAttribution:

    def test_a_stop_tag_maps_to_its_parent_candidate(self):
        assert SL.candidate_from_order_tag("EXPBOT-tok123-SL") == "tok123"

    def test_a_target_tag_maps_to_its_parent_candidate(self):
        assert SL.candidate_from_order_tag("EXPBOT-tok123-TP") == "tok123"

    def test_an_entry_tag_maps_to_itself(self):
        assert SL.candidate_from_order_tag("EXPBOT-tok123") == "tok123"

    def test_a_foreign_tag_maps_to_nothing(self):
        assert SL.candidate_from_order_tag("someone-else") is None
        assert SL.candidate_from_order_tag(None) is None

    def test_trade_joins_to_order_for_the_tag(self):
        order = {"id": 5001, "customTag": "EXPBOT-tok123"}
        trade = {"id": 9001, "orderId": 5001, "customTag": None}
        assert LG.classify(trade, {"tok123"}, {5001: order}) == LG.EXPANSION_BOT

    def test_a_manual_exit_does_not_update_the_sample(self, tmp_path):
        r, s, cs = runner()
        led = SL.SlippageLedger(path=str(tmp_path / "s.jsonl"))
        r.measure_exit_slippage(
            exit_type=SL.EXIT_MANUAL_FLATTEN, requested_price=29790.0,
            fill_price=29789.0, quantity=1, quote_capture=quote(),
            candidate_snapshot=cs, ledger=led, attribution="MANUAL_OPERATOR")
        assert led.reliable() == [] and len(led.observations) == 1


class TestRoundTripPairing:

    def _pair(self, led, cid, direction="bullish"):
        led.record({"kind": "ENTRY", "reliable": True, "candidate_id": cid,
                    "contract_id": CID, "direction": direction, "slippage_ticks": 1.0})
        led.record({"kind": "EXIT", "reliable": True, "candidate_id": cid,
                    "contract_id": CID, "direction": direction, "slippage_ticks": 1.0})

    def test_one_lifecycle_makes_one_round_trip(self, tmp_path):
        led = SL.SlippageLedger(path=str(tmp_path / "s.jsonl"))
        self._pair(led, "cand-A")
        assert led.round_trips() == 1

    def test_different_candidates_never_pair(self, tmp_path):
        led = SL.SlippageLedger(path=str(tmp_path / "s.jsonl"))
        led.record({"kind": "ENTRY", "reliable": True, "candidate_id": "A",
                    "contract_id": CID, "direction": "bullish", "slippage_ticks": 1.0})
        led.record({"kind": "EXIT", "reliable": True, "candidate_id": "B",
                    "contract_id": CID, "direction": "bullish", "slippage_ticks": 1.0})
        assert led.round_trips() == 0

    def test_a_direction_mismatch_never_pairs(self, tmp_path):
        led = SL.SlippageLedger(path=str(tmp_path / "s.jsonl"))
        led.record({"kind": "ENTRY", "reliable": True, "candidate_id": "A",
                    "contract_id": CID, "direction": "bullish", "slippage_ticks": 1.0})
        led.record({"kind": "EXIT", "reliable": True, "candidate_id": "A",
                    "contract_id": CID, "direction": "bearish", "slippage_ticks": 1.0})
        assert led.round_trips() == 0

    def test_a_contract_mismatch_never_pairs(self, tmp_path):
        led = SL.SlippageLedger(path=str(tmp_path / "s.jsonl"))
        led.record({"kind": "ENTRY", "reliable": True, "candidate_id": "A",
                    "contract_id": CID, "direction": "bullish", "slippage_ticks": 1.0})
        led.record({"kind": "EXIT", "reliable": True, "candidate_id": "A",
                    "contract_id": "CON.F.US.MNQ.Z26", "direction": "bullish",
                    "slippage_ticks": 1.0})
        assert led.round_trips() == 0

    def test_an_observation_without_identity_cannot_pair(self, tmp_path):
        led = SL.SlippageLedger(path=str(tmp_path / "s.jsonl"))
        led.record({"kind": "ENTRY", "reliable": True, "candidate_id": "",
                    "contract_id": CID, "direction": "bullish", "slippage_ticks": 1.0})
        led.record({"kind": "EXIT", "reliable": True, "candidate_id": "",
                    "contract_id": CID, "direction": "bullish", "slippage_ticks": 1.0})
        assert led.round_trips() == 0

    def test_counters_survive_restart(self, tmp_path):
        p = str(tmp_path / "s.jsonl")
        self._pair(SL.SlippageLedger(path=p), "cand-A")
        assert SL.SlippageLedger.load(p).round_trips() == 1


class TestExecutionContext:

    def test_identity_survives_process_reconciliation(self, tmp_path):
        r, s, cs = runner()
        r.order_id = 5001
        r.entry_capture = quote()
        path = str(tmp_path / "ctx.json")
        r.build_execution_context(
            candidate_snapshot=cs, mission_id="m-1",
            fill_event={"price": 29760.5, "trade_id": 9001},
            stop_order_id=5002, target_order_id=5003, path=path)
        again = SL.ExecutionContext.load(path)
        assert again.candidate_id == "cand-A"
        assert again.candidate_fingerprint == cs.fingerprint()
        assert again.structural_stop_price == 29750.0
        assert again.liquidity_target_price == 29790.0
        assert again.stop_order_id == 5002 and again.target_order_id == 5003


class TestReserveUnchanged:

    def test_the_reserve_is_unchanged_after_one_round_trip(self, tmp_path):
        from broker.topstepx_combine_risk import SLIPPAGE_RESERVE_TICKS_PER_SIDE
        led = SL.SlippageLedger(path=str(tmp_path / "s.jsonl"))
        led.record({"kind": "ENTRY", "reliable": True, "candidate_id": "A",
                    "contract_id": CID, "direction": "bullish", "slippage_ticks": 8.0})
        led.record({"kind": "EXIT", "reliable": True, "candidate_id": "A",
                    "contract_id": CID, "direction": "bullish", "slippage_ticks": 8.0})
        assert SLIPPAGE_RESERVE_TICKS_PER_SIDE == 2.0

    def test_the_reserve_is_unchanged_after_the_threshold(self, tmp_path):
        from broker.topstepx_combine_risk import SLIPPAGE_RESERVE_TICKS_PER_SIDE
        led = SL.SlippageLedger(path=str(tmp_path / "s.jsonl"))
        for i in range(10):
            for kind in ("ENTRY", "EXIT"):
                led.record({"kind": kind, "reliable": True, "candidate_id": f"c{i}",
                            "contract_id": CID, "direction": "bullish",
                            "slippage_ticks": 0.0})
        assert led.may_revisit_reserve()[0] is True
        assert SLIPPAGE_RESERVE_TICKS_PER_SIDE == 2.0     # unmoved, by design

    def test_evidence_cannot_alter_thesis_geometry(self):
        import ast
        import inspect
        tree = ast.parse(inspect.getsource(SL))
        for node in ast.walk(tree):
            if isinstance(node, ast.Attribute):
                assert node.attr not in ("invalidation_price", "objective",
                                         "stop_price", "target_price")


# ══════════════════════════════════════════════════════════════════════════════
class TestFullMockedLifecycle:
    """CandidateSnapshot -> production bracket -> gated_submit -> capture ->
    fill -> protection -> exit -> two observations -> one round trip."""

    def test_the_whole_chain(self, tmp_path):
        cs = snapshot()
        s = BlockedSession()
        r, s, cs = runner(session=s, cs=cs)
        stop_before, target_before = r.geometry.stop_price, r.geometry.target_price
        qty_before = r.geometry.size
        led = SL.SlippageLedger(path=str(tmp_path / "slip.jsonl"))

        with pytest.raises(R.RunnerHalt):
            r.gated_submit(account_id=1, ledger=ledger(tmp_path), candidate_snapshot=cs,
                           market=market(), latest_price=29760.0, mint_token=mint(cs),
                           quote_provider=lambda: quote())
        assert r.entry_capture is not None
        r.order_id = 5001
        r.submit_at, r.ack_at = NOW, NOW + timedelta(milliseconds=180)

        entry_obs = r.measure_entry_slippage(
            fill_event={"price": 29760.25, "size": qty_before, "trade_id": 9001,
                        "at": NOW + timedelta(milliseconds=800)},
            candidate_snapshot=cs, ledger=led)

        r.build_execution_context(candidate_snapshot=cs, mission_id="m-1",
                                  fill_event={"price": 29760.25, "trade_id": 9001},
                                  stop_order_id=5002, target_order_id=5003,
                                  path=str(tmp_path / "ctx.json"))

        exit_obs = r.measure_exit_slippage(
            exit_type=SL.EXIT_TARGET, requested_price=cs.objective.price,
            fill_price=29789.75, quantity=qty_before, quote_capture=quote(),
            candidate_snapshot=cs, ledger=led, order_id=5003, trade_id=9002)

        # identity preserved end to end
        assert entry_obs["candidate_id"] == exit_obs["candidate_id"] == "cand-A"
        # geometry and size untouched by measurement
        assert r.geometry.stop_price == stop_before == 29750.0
        assert r.geometry.target_price == target_before == 29790.0
        assert r.geometry.size == qty_before
        # two reliable observations, one complete round trip
        assert len(led.reliable()) == 2
        assert led.round_trips() == 1
        # reserve untouched
        from broker.topstepx_combine_risk import SLIPPAGE_RESERVE_TICKS_PER_SIDE
        assert SLIPPAGE_RESERVE_TICKS_PER_SIDE == 2.0
        assert led.may_revisit_reserve()[0] is False      # 2 of 20, 1 of 10
        # no real write
        assert s.place_calls == 1        # blocked seam, nothing left the process
        summary = led.statistics()
        assert summary["entry"]["n"] == 1 and summary["exit"]["n"] == 1
