"""WIRE-PRODUCTION-SCAN-LOOP — the Brain reaching the protected order path.

`--arm` used to change a printed line. These tests lock that it now controls the
only branch capable of reaching `gated_submit`, and that everything upstream of
that branch runs identically whether armed or not.

No real venue endpoint is reachable: the session fake raises on every write.
"""
from __future__ import annotations

import os
import sys
from datetime import datetime, timedelta, timezone

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src"))

from _step7_fixture import detected as _detected      # noqa: E402
from _step7_fixture import priced as _priced          # noqa: E402

from ai_brain.production_model import PRODUCTION_MODEL  # noqa: E402
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from broker import topstepx_production_loop as PL                   # noqa: E402
from broker import topstepx_session_authorization as SA             # noqa: E402
from broker import topstepx_session_ledger as LG                    # noqa: E402
from broker import topstepx_slippage as SL                          # noqa: E402
from broker.luna_candidate_producer import CandidateProducer        # noqa: E402
from broker.topstepx_client import TopstepXContract                 # noqa: E402
from broker.topstepx_production_session import ProductionSession    # noqa: E402
from broker.topstepx_quote_provider import LiveQuoteProvider        # noqa: E402
from live_scan.production_scan_cycle import ProductionScanCycle     # noqa: E402

CID = "CON.F.US.MNQ.U26"
FP = "acct:fc84f7a928d9"
NOW = datetime(2026, 8, 6, 15, 0, tzinfo=timezone.utc)
MNQ = TopstepXContract(id=CID, name="MNQU6", description="MNQ",
                       tick_size=0.25, tick_value=0.5, active=True)


class VenueTouched(AssertionError):
    """A real venue write was reached. Never allowed."""


class Hub:
    def __init__(self):
        self.handlers = {}

    def on(self, event, handler):
        self.handlers.setdefault(event, []).append(handler)

    def emit(self, event, args):
        for h in self.handlers.get(event, []):
            h(args)


class Session:
    def __init__(self, positions=None, orders=None, place=None, trades=None):
        self.market_hub = Hub()
        self._trades = list(trades or [])
        self._p, self._o = list(positions or []), list(orders or [])
        self.account = type("A", (), {"id": 77})()
        self.place_calls = 0
        self._place = place

    def open_positions(self):
        return list(self._p)

    def open_orders(self):
        return list(self._o)

    def query_orders(self, *, statuses=None, contract_id=None):
        # The certified COMPLETE discovery surface. The daily-loss governor
        # asks for it before sizing, and an incomplete view fails closed.
        return list(self._o)

    def recent_trades(self, since=None):
        # LUNA-DAILY-LOSS-BUDGET-GOVERNOR-1. The double must carry the real
        # production seam or it stops standing in for it: the governor reads
        # realized session P&L here before a candidate may be sized. No trades
        # means a full, untouched budget -- which is what these lifecycle tests
        # have always assumed implicitly.
        return list(self._trades)

    def place_order(self, payload):
        self.place_calls += 1
        if self._place is None:
            raise VenueTouched("real place_order reached")
        return self._place(payload)

    def cancel_order(self, oid):
        raise VenueTouched("cancel_order reached")

    def close_position(self, cid):
        raise VenueTouched("close_position reached")


class Runtime:
    def __init__(self, hub):
        self.hub = hub
        self.pump_owner_id = "production-startup"
        self.contract = MNQ

    def health(self):
        return {"pump_owner": "production-startup", "pump_thread_alive": True,
                "active_contracts": [CID], "last_quote_age": 0.5,
                "connection_generation": 1, "subscriber_count": 2,
                "subscribers": ["candle-provider", "quote-provider"]}

    def note_subscriber(self, name):
        return None

    @property
    def is_running(self):
        return True


def contiguous_1m(count=90, start="2026-08-06T13:30:00+00:00", price=29880.0):
    """A realistic contiguous 1m tape starting on a 15m boundary.

    The old default here was a SINGLE bar carrying only a timestamp, which was
    harmless while the scan cycle was stubbed out. CONTINUITY-2C made the loop
    require a bounded, continuous, bucket-aligned window, and one dummy bar is
    correctly refused -- so the stub now supplies history a real provider could
    actually have returned. The contract was not loosened to suit the fixture;
    the fixture was never realistic.
    """
    from datetime import datetime as _dt, timedelta as _td
    base = _dt.fromisoformat(start)
    return [{"timestamp": (base + _td(minutes=i)).isoformat(),
             "open": price, "high": price + 2, "low": price - 2,
             "close": price, "volume": 10} for i in range(count)]


class Candles:
    """Provider stub: returns bars, or raises like a stale feed."""

    def __init__(self, bars=None, raise_exc=None):
        self.bars = bars if bars is not None else contiguous_1m()
        self.raise_exc = raise_exc
        self.calls = 0

    def fetch_1m_candles(self, symbol, lookback_bars=300):
        self.calls += 1
        if self.raise_exc:
            raise self.raise_exc
        return list(self.bars)


# ── scan-cycle stub: the pipeline is exercised in its own tests ───────────────
def brain_input(price=29880.0, buy=29910.25, sell=29840.0, low=29875.0, high=29915.0):
    return {"timestamp": "2026-08-06T14:59:00+00:00",
            "market": _priced({"current_price": price}),
            "liquidity": {"nearest_buy_side": buy, "nearest_sell_side": sell},
            "protected_swings": {
                "protected_low": {"level": low, "timestamp": "2026-08-06T14:00:00+00:00"},
                "protected_high": {"level": high, "timestamp": "2026-08-06T14:05:00+00:00"}}}


def parsed(**over):
    p = {"narrative_direction": "bullish", "narrative_phase": "continuation",
         "invalidation_level": 29875.0, "active_draw": "buy side liquidity above",
         "recommended_playbook_family": "continuation",
         "recommended_tool_family": ["fvg"], "market_story": "bullish continuation",
         "current_action": "await_retest"}
    p.update(over)
    return p


class Cycle:
    """Stands in for ProductionScanCycle, returning its exact output contract."""

    def __init__(self, source="llm", output=None, bi=None, fallback=None):
        self.source, self.fallback = source, fallback
        self.output = parsed() if output is None else output
        self.bi = bi or brain_input()
        self.scans = 0

    def scan(self, bars, now=None, deep_1m=None):
        # LUNA-CROSS-SESSION-PO3-CONTEXT-1: the production seam is
        # `cycle.scan(bars, now=..., deep_1m=...)`. The fake accepts and IGNORES
        # the deep series -- these tests are about the loop's lifecycle, not
        # about context -- but it must keep the real callable's shape, or the
        # double drifts from the seam it stands in for while staying green.
        self.scans += 1
        block = {"source": self.source, "output": self.output,
                 "fallback_reason": self.fallback, "llm_model": PRODUCTION_MODEL,
                 "warnings": []}
        return {"snapshot": {"market": {"high_since": 29882.0, "low_since": 29878.0},
                             "qualification": {"qualified": True},
                             **_detected("ifvg", "fvg")},
                "brain_block": block,
                "brain_input": self.bi,
                "brain_result": ProductionScanCycle.to_brain_result(block),
                "qualification": {"qualified": True},
                "engine_inventory": {"liquidity": "PRESENT_AND_POPULATED"},
                "snapshot_id": "snap-1",
                "market_data_timestamp": "2026-08-06T14:59:30+00:00",
                "latest_closed_bar_timestamp": "2026-08-06T14:59:00+00:00",
                "scan_count": self.scans, "source": self.source}


def authorization(tmp_path, session_id="S1", **over):
    kw = dict(session_id=session_id, account_fingerprint=FP, contract_id=CID,
              session_date=NOW.strftime("%Y%m%d"), decision_window="09:30-14:00",
              issued_at=NOW.isoformat(),
              path=os.path.join(str(tmp_path), f"session_auth_{session_id}.json"),
              # LUNA-DAILY-LOSS-BUDGET-GOVERNOR-1: the armed lifecycle these
              # tests exercise runs through verify(), so the budget is signed.
              daily_loss_budget_usd=SA.DAILY_LOSS_BUDGET_USD)
    kw.update(over)
    a = SA.SessionAuthorization(**kw)
    a.authorization_fingerprint = a.fingerprint()
    return a


def build(tmp_path, *, armed=False, cycle=None, session=None, candles=None,
          in_window=True, auth=None):
    s = session or Session()
    hub = s.market_hub
    rt = Runtime(hub)
    qp = LiveQuoteProvider(hub, MNQ, clock=lambda: NOW)
    hub.emit("GatewayQuote", [CID, {"bestBid": 29879.75, "bestAsk": 29880.0}])
    ps = ProductionSession(session=s, account_fingerprint=FP, contract=MNQ,
                           mission_id="M", store_dir=str(tmp_path), runtime=rt,
                           quote_provider=qp, clock=lambda: NOW,
                           # EXEC-PRICE-ANCHOR-1: production waits 30s for the
                           # authoritative full fill. A harness that models a
                           # venue which never fills would spend that in real
                           # wall-clock, once per test. This shortens the WAIT
                           # only -- every refusal, ordering and price assertion
                           # is unchanged, which is what the injectable deadline
                           # exists for.
                           fill_deadline_seconds=0.2)
    a = auth or authorization(tmp_path)
    mission = SA.ProductionSessionMission(authorization=a, store_dir=str(tmp_path))
    loop = PL.ProductionLoop(
        production_session=ps, session_mission=mission,
        producer=CandidateProducer(allow_prose_objective_fallback=True,
                                      account_fingerprint=FP, contract=MNQ),
        candles=candles or Candles(), runtime=rt, account_id=77, armed=armed,
        scan_cycle=cycle or Cycle(), clock=lambda: NOW, in_window=lambda: in_window)
    return loop, ps, s, mission


# ══════════════════════════════════════════════════════════════════════════════
class TestArmGatesTheOrderPath:

    def test_disarmed_stops_at_the_execution_boundary(self, tmp_path):
        loop, _, s, _ = build(tmp_path, armed=False)
        out = loop.scan_once()
        assert out["outcome"] == PL.QUALIFIED_CANDIDATE_OBSERVED
        assert out["execution"] == PL.EXECUTION_DISARMED
        assert s.place_calls == 0

    def test_disarmed_mints_no_token_and_consumes_no_attempt(self, tmp_path):
        loop, _, _, mission = build(tmp_path, armed=False)
        loop.scan_once()
        assert mission.token_count == 0
        assert mission.entry_attempt_count == 0
        assert mission.trades_used() == 0
        assert mission.candidate_count == 1          # the candidate WAS produced

    def test_disarmed_writes_no_durable_mission_file(self, tmp_path):
        loop, _, _, _ = build(tmp_path, armed=False)
        loop.scan_once()
        assert not [f for f in os.listdir(tmp_path) if f.startswith("trade_mission_")]

    def test_armed_reaches_the_submit_path(self, tmp_path):
        loop, _, s, mission = build(tmp_path, armed=True)
        out = loop.scan_once()
        # The venue seam raises, proving the branch was reached without a write.
        assert out["outcome"] in (PL.SUBMITTED, PL.SUBMIT_FAILED)
        assert s.place_calls == 1
        assert mission.entry_attempt_count == 1

    def test_the_arm_flag_is_the_only_difference(self, tmp_path):
        """Same candidate, same sizing; only reachability of execution differs."""
        a, _, _, _ = build(tmp_path / "a", armed=False)
        b, _, _, _ = build(tmp_path / "b", armed=True)
        oa, ob = a.scan_once(), b.scan_once()
        assert oa["outcome"] == PL.QUALIFIED_CANDIDATE_OBSERVED
        assert ob["outcome"] in (PL.SUBMITTED, PL.SUBMIT_FAILED)
        assert oa["sizing"]["size"] == ob["sizing"]["size"]


class TestLunaGating:

    def test_neutral_produces_no_candidate(self, tmp_path):
        loop, _, s, m = build(tmp_path, cycle=Cycle(output={"narrative_direction": "neutral"}))
        out = loop.scan_once()
        assert out["outcome"] == PL.NO_CANDIDATE
        assert m.candidate_count == 0 and s.place_calls == 0

    def test_conflicted_produces_no_candidate(self, tmp_path):
        loop, _, _, m = build(tmp_path,
                              cycle=Cycle(output={"narrative_direction": "conflicted"}))
        assert loop.scan_once()["outcome"] == PL.NO_CANDIDATE
        assert m.candidate_count == 0

    def test_degraded_is_reported_as_brain_failure_not_a_stand_down(self, tmp_path):
        loop, _, _, _ = build(tmp_path, cycle=Cycle(source="degraded", output={}))
        out = loop.scan_once()
        assert out["outcome"] == PL.BRAIN_DEGRADED
        assert out["outcome"] != PL.NO_CANDIDATE

    def test_a_fallback_read_never_authors_a_candidate(self, tmp_path):
        loop, _, _, m = build(tmp_path, cycle=Cycle(source="llm", fallback="json_error"))
        assert loop.scan_once()["outcome"] == PL.BRAIN_DEGRADED
        assert m.candidate_count == 0

    def test_the_exact_degraded_reason_is_captured(self, tmp_path):
        loop, _, _, _ = build(tmp_path, cycle=Cycle(source="degraded", output={},
                                                    fallback="upstream 500"))
        assert "upstream 500" in loop.scan_once()["detail"]

    def test_directional_but_incomplete_produces_no_candidate(self, tmp_path):
        loop, _, _, m = build(tmp_path, cycle=Cycle(output=parsed(invalidation_level=None)))
        assert loop.scan_once()["outcome"] == PL.NO_CANDIDATE
        assert m.candidate_count == 0


class TestProductionSizingReachesTheRunner:

    def test_the_candidate_is_sized_by_production_doctrine(self, tmp_path):
        loop, ps, _, _ = build(tmp_path)
        out = loop.scan_once()
        assert out["sizing"]["size"] > 1              # smoke would force exactly 1
        assert ps.runner.max_risk_usd == 350.0
        assert ps.runner.max_stop_points == 50.0
        assert ps.runner.max_contracts == 15

    def test_the_structural_stop_is_preserved_exactly(self, tmp_path):
        loop, ps, _, _ = build(tmp_path)
        loop.scan_once()
        assert ps.runner.geometry.stop_price == 29875.0

    def test_the_liquidity_objective_is_preserved_exactly(self, tmp_path):
        loop, ps, _, _ = build(tmp_path)
        out = loop.scan_once()
        assert ps.runner.geometry.target_price == 29910.25
        assert out["objective"].startswith("opposing_external_liquidity")

    def test_a_thirty_five_point_stop_uses_the_normal_range(self, tmp_path):
        # 35-pt stop needs a target beyond 52.5 pts to clear the 1.5R floor,
        # otherwise the setup is rejected on reward and proves nothing about range.
        loop, _, _, _ = build(tmp_path, cycle=Cycle(
            bi=brain_input(low=29845.0, buy=29950.0),
            output=parsed(invalidation_level=29845.0)))
        out = loop.scan_once()
        assert out["sizing"]["stop_points"] == 35.0
        assert out["sizing"]["stop_range"] == "NORMAL_STOP_RANGE"

    def test_between_35_and_40_requires_the_extended_volatility_lane(self, tmp_path):
        """The extended lane needs supporting evidence; prose alone will not do."""
        loop, _, _, _ = build(tmp_path, cycle=Cycle(
            bi=brain_input(low=29842.0, buy=29980.0),
            output=parsed(invalidation_level=29842.0)))
        out = loop.scan_once()
        assert out["outcome"] == PL.RISK_REJECTED
        assert "extended" in out["reason"] or "volatility" in out["detail"].lower()

    def test_beyond_the_ceiling_is_rejected_not_squeezed(self, tmp_path):
        """A 60-point structural stop, past the 50-point ceiling. The detail
        must name the CEILING IN FORCE rather than a hardcoded number -- this
        asserted "40" and would have passed a message quoting any 40-ish
        value after the doctrine moved."""
        from broker.topstepx_combine_risk import ABSOLUTE_MAX_STOP_POINTS
        loop, _, _, _ = build(tmp_path, cycle=Cycle(
            bi=brain_input(low=29820.0, buy=30100.0),
            output=parsed(invalidation_level=29820.0)))
        out = loop.scan_once()
        assert out["outcome"] == PL.RISK_REJECTED
        assert f"{ABSOLUTE_MAX_STOP_POINTS:g}-point" in out["detail"]
        assert "not adjustable" in out["detail"]

    def test_all_in_risk_never_exceeds_the_cap(self, tmp_path):
        loop, _, _, _ = build(tmp_path)
        out = loop.scan_once()
        assert out["sizing"]["risk_usd"] <= 250.0


class TestSessionAndTradeMissions:

    def test_a_missing_durable_authorization_refuses_arming(self, tmp_path):
        from tools.topstepx_production_session import load_or_refuse_authorization
        with pytest.raises(SA.AuthorizationRefused, match="NO_SESSION_AUTHORIZATION"):
            load_or_refuse_authorization(armed=True, session_id="missing",
                                         fingerprint=FP, contract_id=CID, now=NOW)

    def test_a_corrupt_authorization_is_refused(self, tmp_path):
        a = authorization(tmp_path)
        a.maximum_risk_per_trade = 9999.0          # edited after signing
        with pytest.raises(SA.AuthorizationRefused, match="AUTHORIZATION_CORRUPT"):
            a.verify(account_fingerprint=FP, contract_id=CID,
                     session_date=NOW.strftime("%Y%m%d"))

    def test_a_fingerprint_mismatch_is_refused(self, tmp_path):
        with pytest.raises(SA.AuthorizationRefused, match="ACCOUNT_MISMATCH"):
            authorization(tmp_path).verify(account_fingerprint="acct:other",
                                           contract_id=CID,
                                           session_date=NOW.strftime("%Y%m%d"))

    def test_a_contract_mismatch_is_refused(self, tmp_path):
        with pytest.raises(SA.AuthorizationRefused, match="CONTRACT_MISMATCH"):
            authorization(tmp_path).verify(account_fingerprint=FP,
                                           contract_id="CON.F.US.ES.U26",
                                           session_date=NOW.strftime("%Y%m%d"))

    def test_an_expired_authorization_does_not_roll_over(self, tmp_path):
        with pytest.raises(SA.AuthorizationRefused, match="EXPIRED"):
            authorization(tmp_path).verify(account_fingerprint=FP, contract_id=CID,
                                           session_date="20260807")

    def test_an_authorization_above_doctrine_is_refused(self, tmp_path):
        a = authorization(tmp_path, maximum_trades=5)
        with pytest.raises(SA.AuthorizationRefused, match="EXCEEDS_DOCTRINE"):
            a.verify(account_fingerprint=FP, contract_id=CID,
                     session_date=NOW.strftime("%Y%m%d"))

    def test_one_attempt_per_trade_mission(self, tmp_path):
        loop, _, s, m = build(tmp_path, armed=True)
        loop.scan_once()
        mission = m.trade_missions[0]
        assert mission.max_attempts == 1
        assert mission.attempt_count == 1
        ok, why = mission.may_attempt_entry()
        assert ok is False

    def test_a_second_trade_mission_requires_the_first_to_be_terminal(self, tmp_path):
        loop, _, _, m = build(tmp_path, armed=True)
        loop.scan_once()
        ok, why = m.may_open_trade_mission(positions=0, working_orders=0,
                                           unknown_external=False, in_window=True)
        assert ok is False
        assert "already active" in why or "reconcil" in why

    def test_a_third_trade_mission_is_refused(self, tmp_path):
        m = SA.ProductionSessionMission(authorization=authorization(tmp_path),
                                        store_dir=str(tmp_path))
        for i in (1, 2):
            mission = m.open_trade_mission(positions=0, working_orders=0,
                                           unknown_external=False, in_window=True)
            mission.transition("COMPLETE", "done")
        ok, why = m.may_open_trade_mission(positions=0, working_orders=0,
                                           unknown_external=False, in_window=True)
        assert ok is False and "maximum" in why

    def test_an_open_position_blocks_another_trade_mission(self, tmp_path):
        m = SA.ProductionSessionMission(authorization=authorization(tmp_path),
                                        store_dir=str(tmp_path))
        ok, why = m.may_open_trade_mission(positions=1, working_orders=0,
                                           unknown_external=False, in_window=True)
        assert ok is False and "flat" in why

    def test_working_orders_block_another_trade_mission(self, tmp_path):
        m = SA.ProductionSessionMission(authorization=authorization(tmp_path),
                                        store_dir=str(tmp_path))
        ok, why = m.may_open_trade_mission(positions=0, working_orders=2,
                                           unknown_external=False, in_window=True)
        assert ok is False and "working order" in why

    def test_unknown_external_activity_blocks_entry(self, tmp_path):
        m = SA.ProductionSessionMission(authorization=authorization(tmp_path),
                                        store_dir=str(tmp_path))
        ok, why = m.may_open_trade_mission(positions=0, working_orders=0,
                                           unknown_external=True, in_window=True)
        assert ok is False and "unknown external" in why

    def test_a_closed_window_blocks_a_new_trade_mission(self, tmp_path):
        m = SA.ProductionSessionMission(authorization=authorization(tmp_path),
                                        store_dir=str(tmp_path))
        ok, why = m.may_open_trade_mission(positions=0, working_orders=0,
                                           unknown_external=False, in_window=False)
        assert ok is False and "window" in why

    def test_never_two_active_trade_missions(self, tmp_path):
        m = SA.ProductionSessionMission(authorization=authorization(tmp_path),
                                        store_dir=str(tmp_path))
        m.open_trade_mission(positions=0, working_orders=0,
                             unknown_external=False, in_window=True)
        with pytest.raises(SA.AuthorizationRefused, match="already active"):
            m.open_trade_mission(positions=0, working_orders=0,
                                 unknown_external=False, in_window=True)


class TestWindowAndCounters:

    def test_a_closed_window_produces_no_candidate(self, tmp_path):
        loop, _, s, _ = build(tmp_path, in_window=False)
        out = loop.scan_once()
        assert out["outcome"] == PL.WINDOW_CLOSED
        assert s.place_calls == 0

    def test_a_position_is_still_managed_after_the_window_closes(self, tmp_path):
        """The entry window gates NEW entries; it never abandons exposure."""
        s = Session(positions=[{"contractId": CID, "size": 3}])
        loop, ps, _, _ = build(tmp_path, in_window=False, session=s)
        assert loop.final_flat_state()["positions"] == 1
        assert loop.final_flat_state()["flat"] is False

    def test_counters_track_candidates_separately_from_trades(self, tmp_path):
        loop, _, _, m = build(tmp_path, armed=False)
        loop.scan_once()
        loop.scan_once()
        c = m.counters()
        assert c["candidates"] == 2
        assert c["entry_attempts"] == 0 and c["filled_trades"] == 0
        assert c["trade_missions_used"] == 0

    def test_a_stale_feed_is_reported_not_treated_as_no_setup(self, tmp_path):
        from data_feed import DataFeedError
        loop, _, _, _ = build(tmp_path, candles=Candles(raise_exc=DataFeedError("stale")))
        out = loop.scan_once()
        assert out["outcome"] == PL.NO_CANDLES


class TestRestartRecovery:

    def test_a_restart_inherits_the_spent_attempt(self, tmp_path):
        loop, _, _, m = build(tmp_path, armed=True)
        loop.scan_once()
        assert m.entry_attempt_count == 1

        fresh = SA.ProductionSessionMission(authorization=authorization(tmp_path),
                                            store_dir=str(tmp_path))
        fresh.load_existing()
        assert fresh.trades_used() == 1
        assert fresh.entry_attempt_count == 1

    def test_a_restart_cannot_reattempt_the_same_trade_mission(self, tmp_path):
        loop, _, _, m = build(tmp_path, armed=True)
        loop.scan_once()
        fresh = SA.ProductionSessionMission(authorization=authorization(tmp_path),
                                            store_dir=str(tmp_path))
        fresh.load_existing()
        reloaded = fresh.trade_missions[0]
        ok, why = reloaded.may_attempt_entry()
        assert ok is False


class TestArmedLifecycleMocked:
    """A full mocked lifecycle: submit -> fill -> protection -> exit -> flat."""

    def lifecycle(self, tmp_path):
        acks = {"orderId": 900}
        s = Session(place=lambda payload: acks)
        loop, ps, sess, m = build(tmp_path, armed=True, session=s)
        out = loop.scan_once()
        return loop, ps, sess, m, out

    def test_the_attempt_is_durable_before_the_request_leaves(self, tmp_path):
        loop, ps, s, m, out = self.lifecycle(tmp_path)
        assert m.trade_missions[0].attempt_count == 1
        assert os.path.exists(m.mission_path(1))

    def test_quantity_survives_from_sizing_to_the_runner(self, tmp_path):
        loop, ps, s, m, out = self.lifecycle(tmp_path)
        assert ps.runner.geometry.size == out["sizing"]["size"]
        assert ps.runner.geometry.size > 1

    def test_entry_and_exit_produce_two_observations_and_one_round_trip(self, tmp_path):
        loop, ps, s, m, out = self.lifecycle(tmp_path)
        cand = loop.active_candidate
        ps.runner.order_id = 900
        ps.runner.entry_capture = ps.quote_provider.capture()
        ps.ledger.record_token("tok-1")
        orders = [{"id": 900, "customTag": LG.bot_tag("tok-1")},
                  {"id": 902, "customTag": LG.bot_tag("tok-1") + "-TP"}]
        qty = ps.runner.geometry.size

        loop.reconcile_after_fill(
            candidate=cand, fill_event={"price": 29880.0, "size": qty, "at": NOW},
            trades=[{"orderId": 900, "price": 29880.0, "size": qty}], orders=orders,
            stop_order_id=901, target_order_id=902)
        loop.reconcile_after_exit(
            candidate=cand, exit_type=SL.EXIT_TARGET, trades=[], orders=orders,
            exit_order_id=902, fill_price=29910.25, quantity=qty)

        assert len(ps.slippage.observations) == 2
        assert ps.slippage.round_trips() == 1
        assert m.counters()["filled_trades"] == 1
        assert m.counters()["round_trips"] == 1

    def test_the_trade_mission_is_terminal_after_the_exit(self, tmp_path):
        loop, ps, s, m, out = self.lifecycle(tmp_path)
        cand = loop.active_candidate
        ps.runner.order_id = 900
        ps.runner.entry_capture = ps.quote_provider.capture()
        loop.reconcile_after_fill(
            candidate=cand, fill_event={"price": 29880.0, "size": 3, "at": NOW},
            trades=[], orders=[], stop_order_id=901, target_order_id=902)
        loop.reconcile_after_exit(candidate=cand, exit_type=SL.EXIT_TARGET, trades=[],
                                  orders=[], exit_order_id=902, fill_price=29910.25,
                                  quantity=3)
        assert m.trade_missions[0].state == "COMPLETE"

    def test_a_second_trade_mission_opens_only_after_a_clean_first(self, tmp_path):
        loop, ps, s, m, out = self.lifecycle(tmp_path)
        cand = loop.active_candidate
        ps.runner.order_id = 900
        ps.runner.entry_capture = ps.quote_provider.capture()
        loop.reconcile_after_fill(
            candidate=cand, fill_event={"price": 29880.0, "size": 3, "at": NOW},
            trades=[], orders=[], stop_order_id=901, target_order_id=902)
        loop.reconcile_after_exit(candidate=cand, exit_type=SL.EXIT_TARGET, trades=[],
                                  orders=[], exit_order_id=902, fill_price=29910.25,
                                  quantity=3)
        ok, why = m.may_open_trade_mission(positions=0, working_orders=0,
                                           unknown_external=False, in_window=True)
        assert ok is True, why

    def test_no_real_venue_write_occurs_anywhere(self, tmp_path):
        loop, ps, s, m, out = self.lifecycle(tmp_path)
        assert s.place_calls == 1          # the mocked ack, never a live endpoint
