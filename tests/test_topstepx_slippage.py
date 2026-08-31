"""LIVE-SLIPPAGE-EVIDENCE-CAPTURE locks. No network, no orders."""
from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timedelta, timezone

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src"))

from broker import topstepx_slippage as SL                          # noqa: E402
from broker.topstepx_client import TopstepXContract                 # noqa: E402
from broker.topstepx_combine_risk import (                          # noqa: E402
    PRODUCTION_MAX_RISK_USD, SLIPPAGE_RESERVE_TICKS_PER_SIDE,
    friction_per_contract, size_for_risk,
)

MNQ = TopstepXContract(id="CON.F.US.MNQ.U26", name="MNQU6", description="MNQ",
                       tick_size=0.25, tick_value=0.5, active=True)
CID = MNQ.id
T = datetime(2026, 8, 5, 17, 11, 0, tzinfo=timezone.utc)
REQ = T + timedelta(milliseconds=200)


def quote(bid=29760.25, ask=29760.5, last=29760.25, age=0.4, cid=CID,
          at=T, vol="expansion"):
    return SL.QuoteCapture(captured_at=at, best_bid=bid, best_ask=ask,
                           last_trade=last, contract_id=cid,
                           market_data_age_seconds=age, volatility_state=vol)


def entry(**kw):
    base = dict(capture=quote(), direction="buy", fill_price=29760.5, quantity=1,
                tick_size=0.25, tick_value=0.5, contract_id=CID, request_at=REQ,
                attribution="EXPANSION_BOT", candidate_id="cand-1")
    base.update(kw)
    return SL.measure_entry(**base)


def exit_obs(**kw):
    base = dict(capture=quote(), direction="buy", exit_type=SL.EXIT_STOP,
                requested_price=29750.5, fill_price=29750.5, quantity=1,
                tick_size=0.25, tick_value=0.5, contract_id=CID,
                attribution="EXPANSION_BOT", candidate_id="cand-1")
    base.update(kw)
    return SL.measure_exit(**base)


# ══════════════════════════════════════════════════════════════════════════════
class TestEntryFormulas:

    def test_a_long_measures_fill_minus_ask(self):
        o = entry(fill_price=29761.0)          # paid 2 ticks above the ask
        assert o["expected_price"] == 29760.5
        assert o["slippage_points"] == pytest.approx(0.5)
        assert o["slippage_ticks"] == pytest.approx(2.0)
        assert o["slippage_dollars_per_contract"] == pytest.approx(1.0)

    def test_a_short_measures_bid_minus_fill(self):
        o = entry(direction="sell", fill_price=29759.75)   # sold 2 ticks below bid
        assert o["expected_price"] == 29760.25
        assert o["slippage_ticks"] == pytest.approx(2.0)

    def test_a_perfect_fill_is_zero(self):
        assert entry(fill_price=29760.5)["slippage_ticks"] == pytest.approx(0.0)

    def test_a_favorable_fill_stays_negative(self):
        """Price improvement must not be clamped — clamping biases the reserve."""
        o = entry(fill_price=29760.25)
        assert o["slippage_ticks"] == pytest.approx(-1.0)
        assert o["favorable"] is True

    def test_total_dollars_scale_with_quantity(self):
        o = entry(fill_price=29761.0, quantity=3)
        assert o["slippage_dollars_total"] == pytest.approx(3.0)

    def test_latencies_are_recorded(self):
        o = entry(ack_at=REQ + timedelta(milliseconds=180),
                  fill_at=REQ + timedelta(milliseconds=900))
        assert o["ack_latency_ms"] == 180 and o["fill_latency_ms"] == 900


class TestExitFormulas:

    def test_a_long_stop_filled_below_request_is_adverse(self):
        o = exit_obs(requested_price=29750.5, fill_price=29750.0)
        assert o["slippage_ticks"] == pytest.approx(2.0)
        assert o["exit_side"] == "sell"

    def test_a_short_stop_filled_above_request_is_adverse(self):
        o = exit_obs(direction="sell", requested_price=29770.0, fill_price=29770.5)
        assert o["slippage_ticks"] == pytest.approx(2.0)
        assert o["exit_side"] == "buy"

    def test_an_exact_protective_fill_is_zero(self):
        assert exit_obs(fill_price=29750.5)["slippage_ticks"] == pytest.approx(0.0)

    def test_exit_types_are_preserved_separately(self):
        for t in (SL.EXIT_TARGET, SL.EXIT_STOP, SL.EXIT_EMERGENCY_FLATTEN,
                  SL.EXIT_MANUAL_FLATTEN, SL.EXIT_OTHER):
            assert exit_obs(exit_type=t)["exit_type"] == t

    def test_stop_distance_is_not_slippage(self):
        """A 40-point stop that fills exactly at its price has zero slippage."""
        o = exit_obs(requested_price=29720.5, fill_price=29720.5)
        assert o["slippage_ticks"] == pytest.approx(0.0)

    def test_target_distance_is_not_slippage(self):
        o = exit_obs(exit_type=SL.EXIT_TARGET, requested_price=29800.5,
                     fill_price=29800.5)
        assert o["slippage_ticks"] == pytest.approx(0.0)

    def test_entry_and_exit_records_stay_separate(self):
        assert entry()["kind"] == "ENTRY" and exit_obs()["kind"] == "EXIT"


class TestReliability:

    def test_a_stale_quote_is_unreliable(self):
        assert entry(capture=quote(age=30.0))["quality"] == SL.UNRELIABLE_STALE_QUOTE

    def test_a_missing_ask_is_unreliable_for_a_buy(self):
        assert entry(capture=quote(ask=None))["quality"] == SL.UNRELIABLE_MISSING_QUOTE

    def test_a_quote_after_the_request_is_unreliable(self):
        late = quote(at=REQ + timedelta(seconds=1))
        assert entry(capture=late)["quality"] == SL.UNRELIABLE_QUOTE_AFTER_REQUEST

    def test_a_contract_mismatch_is_unreliable(self):
        o = entry(capture=quote(cid="CON.F.US.MNQ.Z26"))
        assert o["quality"] == SL.UNRELIABLE_CONTRACT_MISMATCH

    def test_an_unlinked_fill_is_unreliable(self):
        o = entry(fill_order_id=1, expected_order_id=2)
        assert o["quality"] == SL.UNRELIABLE_UNLINKED_FILL

    def test_an_unresolved_direction_is_unreliable(self):
        assert entry(direction="sideways")["quality"] == SL.UNRELIABLE_DIRECTION_UNRESOLVED

    def test_unknown_attribution_is_unreliable(self):
        o = entry(attribution="MANUAL_OPERATOR")
        assert o["quality"] == SL.UNRELIABLE_UNKNOWN_ATTRIBUTION
        assert o["reliable"] is False

    def test_an_unreliable_observation_is_still_retained(self, tmp_path):
        led = SL.SlippageLedger(path=str(tmp_path / "s.jsonl"))
        led.record(entry(capture=quote(age=99.0)))
        assert len(led.observations) == 1 and led.reliable() == []


class TestNoPnlDerivation:

    def test_observations_declare_they_are_not_pnl_derived(self):
        assert entry()["derived_from_pnl"] is False
        assert exit_obs()["derived_from_pnl"] is False

    def test_the_module_never_reads_pnl_fields(self):
        """Checked on the PARSED code, not the prose.

        The docstring is allowed to name what it refuses to use; the executable
        statements are not allowed to touch it. Strings and attribute names in
        real code are inspected, comments and docstrings are not.
        """
        import ast
        import inspect
        tree = ast.parse(inspect.getsource(SL))
        banned = {"profitandloss", "realized", "balance", "net_pnl", "gross_pnl",
                  "commissions", "fees"}
        docstrings = set()
        for node in ast.walk(tree):
            if isinstance(node, (ast.Module, ast.FunctionDef, ast.ClassDef)):
                d = ast.get_docstring(node)
                if d:
                    docstrings.add(d)
        for node in ast.walk(tree):
            if isinstance(node, ast.Constant) and isinstance(node.value, str):
                if node.value in docstrings:
                    continue
                assert node.value.lower() not in banned, f"literal {node.value!r}"
            if isinstance(node, ast.Attribute):
                assert node.attr.lower() not in banned, f"attribute {node.attr!r}"

    def test_slippage_ignores_market_movement_between_entry_and_exit(self):
        """Same fills, wildly different trade outcome — slippage is unchanged."""
        a = exit_obs(requested_price=29750.5, fill_price=29750.25)
        b = exit_obs(exit_type=SL.EXIT_TARGET, requested_price=29900.5,
                     fill_price=29900.25)
        assert a["slippage_ticks"] == b["slippage_ticks"] == pytest.approx(1.0)


class TestReserveLaw:

    def _fill(self, led, n, kind="ENTRY", cand=None):
        for i in range(n):
            obs = (entry(candidate_id=cand or f"c{i}", fill_order_id=i,
                         expected_order_id=i)
                   if kind == "ENTRY" else
                   exit_obs(candidate_id=cand or f"c{i}", order_id=i))
            led.record(obs)

    def test_the_provisional_reserve_is_two_ticks_per_side(self):
        assert SLIPPAGE_RESERVE_TICKS_PER_SIDE == 2.0
        f = friction_per_contract(MNQ)
        assert f["slippage_reserve"] == pytest.approx(2.00)
        assert f["total"] == pytest.approx(3.22)
        assert f["slippage_is_measured"] is False

    def test_one_fill_cannot_change_the_reserve(self, tmp_path):
        led = SL.SlippageLedger(path=str(tmp_path / "s.jsonl"))
        led.record(entry())
        ok, why = led.may_revisit_reserve()
        assert ok is False and "insufficient sample" in why

    def test_twenty_fills_without_ten_round_trips_cannot_change_it(self, tmp_path):
        led = SL.SlippageLedger(path=str(tmp_path / "s.jsonl"))
        self._fill(led, 20, "ENTRY")            # entries only: no round trips
        assert led.sample_status()["reliable_observations"] >= 20
        assert led.round_trips() == 0
        assert led.may_revisit_reserve()[0] is False

    def test_ten_round_trips_without_twenty_observations_cannot_change_it(self, tmp_path):
        led = SL.SlippageLedger(path=str(tmp_path / "s.jsonl"))
        for i in range(9):                       # 9 pairs = 18 observations
            led.record(entry(candidate_id=f"c{i}", fill_order_id=i, expected_order_id=i))
            led.record(exit_obs(candidate_id=f"c{i}", order_id=i))
        st = led.sample_status()
        assert st["reliable_observations"] == 18 < SL.MIN_RELIABLE_OBSERVATIONS
        assert led.may_revisit_reserve()[0] is False

    def test_both_thresholds_together_unlock_review_only(self, tmp_path):
        led = SL.SlippageLedger(path=str(tmp_path / "s.jsonl"))
        for i in range(10):
            led.record(entry(candidate_id=f"c{i}", fill_order_id=i, expected_order_id=i))
            led.record(exit_obs(candidate_id=f"c{i}", order_id=i))
        ok, why = led.may_revisit_reserve()
        assert ok is True and why is None
        # unlocking review must NOT move the live reserve
        assert SLIPPAGE_RESERVE_TICKS_PER_SIDE == 2.0
        assert "reviewed doctrine change" in led.statistics()["note"]

    def test_unreliable_observations_never_count_toward_the_sample(self, tmp_path):
        led = SL.SlippageLedger(path=str(tmp_path / "s.jsonl"))
        for i in range(30):
            led.record(entry(capture=quote(age=99.0), candidate_id=f"c{i}"))
        assert led.sample_status()["reliable_observations"] == 0
        assert led.may_revisit_reserve()[0] is False


class TestPersistence:

    def test_raw_observations_are_written_before_summaries(self, tmp_path):
        p = tmp_path / "s.jsonl"
        led = SL.SlippageLedger(path=str(p))
        led.record(entry(fill_price=29761.0))
        row = json.loads(open(p, encoding="utf-8").readline())
        assert row["actual_fill_price"] == 29761.0 and row["expected_price"] == 29760.5

    def test_the_ledger_reloads(self, tmp_path):
        p = tmp_path / "s.jsonl"
        SL.SlippageLedger(path=str(p)).record(entry())
        assert len(SL.SlippageLedger.load(str(p)).observations) == 1

    def test_a_corrupt_line_does_not_lose_the_rest(self, tmp_path):
        p = tmp_path / "s.jsonl"
        led = SL.SlippageLedger(path=str(p))
        led.record(entry())
        with open(p, "a", encoding="utf-8") as fh:
            fh.write("{broken\n")
        led.record(entry())
        assert len(SL.SlippageLedger.load(str(p)).observations) == 2

    def test_no_credentials_are_persisted(self, tmp_path):
        p = tmp_path / "s.jsonl"
        SL.SlippageLedger(path=str(p)).record(entry())
        body = open(p, encoding="utf-8").read().lower()
        for banned in ("token", "apikey", "api_key", "password", "bearer", "jwt"):
            assert banned not in body


class TestStatistics:

    def test_the_report_separates_entry_and_exit(self, tmp_path):
        led = SL.SlippageLedger(path=str(tmp_path / "s.jsonl"))
        led.record(entry(fill_price=29761.0))
        led.record(exit_obs(fill_price=29750.0))
        s = led.statistics()
        assert s["entry"]["n"] == 1 and s["exit"]["n"] == 1

    def test_percentiles_and_worst_are_reported(self, tmp_path):
        led = SL.SlippageLedger(path=str(tmp_path / "s.jsonl"))
        for px in (29760.5, 29760.75, 29761.0, 29761.5):
            led.record(entry(fill_price=px))
        e = led.statistics()["entry"]
        assert e["n"] == 4 and e["worst"] == pytest.approx(4.0)
        assert e["p90"] >= e["median"] and e["p95"] >= e["p90"]

    def test_breakdowns_exist(self, tmp_path):
        led = SL.SlippageLedger(path=str(tmp_path / "s.jsonl"))
        led.record(entry(fill_price=29761.0))
        led.record(entry(direction="sell", fill_price=29759.75))
        led.record(exit_obs(exit_type=SL.EXIT_TARGET, fill_price=29750.0))
        s = led.statistics()
        assert set(s["entry_by_direction"]) == {"buy", "sell"}
        assert SL.EXIT_TARGET in s["exit_by_type"]
        assert s["entry_by_volatility"] and s["by_spread_bucket"]


class TestRiskIntegration:

    def test_sizing_includes_the_active_reserve(self):
        with_reserve = size_for_risk(40.0, MNQ)["all_in_risk_per_contract"]
        assert with_reserve == pytest.approx(40.0 * 2.0 + 1.22 + 2.00)

    def test_the_forty_point_quantity_is_calculated_not_assumed(self):
        s = size_for_risk(40.0, MNQ)
        per = 83.22
        assert s["all_in_risk_per_contract"] == pytest.approx(per)
        assert s["contracts"] == int(PRODUCTION_MAX_RISK_USD // per)
        assert s["all_in_planned_risk"] == pytest.approx(332.88, abs=0.01)
        assert (s["contracts"] + 1) * per > PRODUCTION_MAX_RISK_USD

    @pytest.mark.parametrize("pts", [5, 10, 20, 35, 39.75, 40])
    def test_all_in_risk_never_exceeds_the_cap(self, pts):
        assert size_for_risk(pts, MNQ)["all_in_planned_risk"] <= PRODUCTION_MAX_RISK_USD

    def test_a_bigger_reserve_sizes_down_not_up(self):
        base = size_for_risk(20.0, MNQ)["contracts"]
        bigger = size_for_risk(20.0, MNQ, slippage_reserve_ticks_per_side=10.0)["contracts"]
        assert bigger <= base

    def test_measurement_cannot_alter_thesis_geometry(self):
        """Slippage evidence touches sizing only — never the levels."""
        import inspect
        src = inspect.getsource(SL)
        for banned in ("invalidation_level", "build_bracket", "target_price ="):
            assert banned not in src


class TestCaptureDoesNotDelayProtection:

    def test_capture_is_pure_and_touches_no_venue(self):
        import inspect
        src = inspect.getsource(SL)
        for banned in ("place_order", "cancel_order", "close_position",
                       "requests.", "urlopen"):
            assert banned not in src

    def test_capture_from_a_quote_dict_is_immediate(self):
        c = SL.capture_quote(market_hub_quote={"bestBid": 1.0, "bestAsk": 1.25,
                                               "lastPrice": 1.0},
                             contract_id=CID, market_data_age_seconds=0.1)
        assert c.best_ask == 1.25 and c.spread_ticks(0.25) == pytest.approx(1.0)

    def test_a_missing_quote_block_still_captures(self):
        c = SL.capture_quote(market_hub_quote={}, contract_id=CID,
                             market_data_age_seconds=0.1)
        assert c.best_bid is None and c.best_ask is None
