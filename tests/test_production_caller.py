"""WIRE-PRODUCTION-SLIPPAGE-CALLER — the production lane, end to end.

These tests drive `ProductionSession`, the caller that closes the gap where
`build_production_bracket` had zero callers and only smoke tooling reached
`gated_submit`. The venue seam raises on any write, so "no order is placed" is
proven by construction rather than asserted after the fact.
"""
from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timedelta, timezone

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src"))

from broker import topstepx_execution_runner as R                   # noqa: E402
from broker import topstepx_session_ledger as LG                    # noqa: E402
from broker import topstepx_slippage as SL                          # noqa: E402
from broker import topstepx_smoke_auth as auth                      # noqa: E402
from broker.topstepx_candidate_freshness import (                   # noqa: E402
    CandidateSnapshot, LiquidityObjective,
)
from broker.topstepx_client import TopstepXContract                 # noqa: E402
from broker.topstepx_combine_risk import (                          # noqa: E402
    ABSOLUTE_MAX_STOP_POINTS, PRODUCTION_MAX_CONTRACTS, PRODUCTION_MAX_RISK_USD,
    RiskRejection,
)
from broker.topstepx_production_session import (                    # noqa: E402
    ProductionLaneRefused, ProductionSession,
)
from broker.topstepx_quote_provider import (                        # noqa: E402
    LiveQuoteProvider, QuoteProviderError,
)

CID = "CON.F.US.MNQ.U26"
OTHER_CID = "CON.F.US.ES.U26"
FP = "acct:fc84f7a928d9"
NOW = datetime(2026, 8, 5, 15, 30, tzinfo=timezone.utc)
MNQ = TopstepXContract(id=CID, name="MNQU6", description="MNQ",
                       tick_size=0.25, tick_value=0.5, active=True)
VOL = {"volatility_state": "expansion", "expansion_state": "expanding",
       "structural_level_identity": "protected_swing_low@29700"}


class VenueTouched(AssertionError):
    """A write endpoint was reached. Never allowed in these tests."""


class BlockedSession:
    def __init__(self, positions=None, orders=None, hub=None):
        self._p, self._o = list(positions or []), list(orders or [])
        self.market_hub = hub
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


class FakeHub:
    """Records handlers and replays events. Opens no connection."""

    def __init__(self):
        self.handlers = {}
        self.connects = 0

    def on(self, event, handler):
        self.handlers.setdefault(event, []).append(handler)

    def emit(self, event, args):
        for h in self.handlers.get(event, []):
            h(args)

    def connect(self):
        self.connects += 1
        raise VenueTouched("a second market connection was opened")


def objective(price=29790.0):
    return LiquidityObjective("prior_session_high@29790.0", "prior_session_high",
                              price, NOW - timedelta(minutes=2))


def snapshot(direction="bullish", entry=29760.0, stop=None, target=None,
             extras=None):
    if stop is None:
        stop = 29750.0 if direction == "bullish" else 29770.0
    if target is None:
        target = 29790.0 if direction == "bullish" else 29730.0
    return CandidateSnapshot(
        candidate_id="cand-A", snapshot_id="snap-1", direction=direction,
        entry_price=entry, invalidation_price=stop, objective=objective(target),
        contract_id=CID, account_fingerprint=FP, created_at=NOW - timedelta(minutes=1),
        narrative="bullish continuation",
        extras=(extras if extras is not None else {"volatility_evidence": VOL}))


def market(**over):
    kw = dict(current_price=29760.0, high_since=29762.0, low_since=29758.0,
              tick_size=0.25, snapshot_id="snap-1", contract_id=CID,
              account_fingerprint=FP, account_state_digest="", data_age_seconds=2.0,
              in_window=True, manual_activity=False, now=NOW)
    kw.update(over)
    return kw


def mint(cs, size=PRODUCTION_MAX_CONTRACTS):
    return lambda: auth.issue(
        phrase=auth.AUTHORIZATION_PHRASE, account_fingerprint=FP, contract_id=CID,
        candidate_fingerprint=cs.fingerprint(), snapshot_id=cs.snapshot_id,
        direction=cs.direction, stop_price=cs.invalidation_price,
        target_price=cs.objective.price, target_identity=cs.objective.identity,
        max_risk_usd=PRODUCTION_MAX_RISK_USD, max_contracts=size, now=NOW)


def quoted(hub, bid=29759.75, ask=29760.0, cid=CID):
    hub.emit("GatewayQuote", [cid, {"bestBid": bid, "bestAsk": ask,
                                    "lastPrice": bid}])


def make(tmp_path, session=None, hub=None, quote_provider=None, mission="M-1"):
    hub = hub if hub is not None else FakeHub()
    s = session or BlockedSession(hub=hub)
    ps = ProductionSession(session=s, account_fingerprint=FP, contract=MNQ,
                           mission_id=mission, store_dir=str(tmp_path),
                           quote_provider=quote_provider, clock=lambda: NOW)
    return ps, s, hub


# ══════════════════════════════════════════════════════════════════════════════
class TestTheGapThisMissionCloses:

    def test_production_bracket_now_has_a_caller(self):
        import inspect

        from broker import topstepx_production_session as PS
        assert "build_production_bracket" in inspect.getsource(PS.ProductionSession.build_runner)

    def test_the_caller_passes_a_quote_provider_to_gated_submit(self):
        import ast
        import inspect
        import textwrap
        tree = ast.parse(textwrap.dedent(inspect.getsource(ProductionSession.submit)))
        call = [n for n in ast.walk(tree) if isinstance(n, ast.Call)
                and getattr(n.func, "attr", "") == "gated_submit"][0]
        assert "quote_provider" in [k.arg for k in call.keywords]

    def test_the_caller_never_imports_smoke_caps(self):
        import ast
        src = open(os.path.join("src", "broker", "topstepx_production_session.py"),
                   encoding="utf-8").read()
        names = set()
        for node in ast.walk(ast.parse(src)):
            if isinstance(node, ast.ImportFrom):
                names.update(a.name for a in node.names)
        assert not [n for n in names if n.startswith("SMOKE_")]


class TestLiveQuoteProvider:

    def test_it_reads_the_existing_hub_and_opens_no_connection(self):
        hub = FakeHub()
        p = LiveQuoteProvider(hub, MNQ, clock=lambda: NOW)
        quoted(hub)
        assert p.capture().best_ask == 29760.0
        assert hub.connects == 0

    def test_it_refuses_to_exist_without_a_hub(self):
        with pytest.raises(QuoteProviderError):
            LiveQuoteProvider(None, MNQ)

    def test_another_contracts_quote_is_ignored(self):
        hub = FakeHub()
        p = LiveQuoteProvider(hub, MNQ, clock=lambda: NOW)
        quoted(hub, cid=OTHER_CID, bid=1.0, ask=2.0)
        assert not p.has_quote()

    def test_no_quote_yet_is_reported_stale_not_fresh(self):
        p = LiveQuoteProvider(FakeHub(), MNQ, clock=lambda: NOW)
        cap = p.capture()
        assert cap.market_data_age_seconds > 1000
        assert p.age_seconds() is None

    def test_capture_is_synchronous_and_does_no_io(self):
        import inspect
        src = inspect.getsource(LiveQuoteProvider)
        for banned in ("requests", "urlopen", "sleep", "connect(", "while "):
            assert banned not in src

    def test_age_grows_with_the_clock(self):
        hub, t = FakeHub(), [NOW]
        p = LiveQuoteProvider(hub, MNQ, clock=lambda: t[0])
        quoted(hub)
        t[0] = NOW + timedelta(seconds=9)
        assert p.age_seconds() == pytest.approx(9.0)


class TestLaneStartup:

    def test_a_flat_account_opens_the_lane(self, tmp_path):
        ps, _, hub = make(tmp_path)
        quoted(hub)
        lane = ps.open_lane()
        assert lane["lane"] == "OPEN" and lane["new_entry_permitted"] is True

    def test_no_market_hub_refuses_the_lane(self, tmp_path):
        ps, _, _ = make(tmp_path, session=BlockedSession(hub=None))
        with pytest.raises(ProductionLaneRefused):
            ps.open_lane()

    def test_a_provider_for_another_contract_refuses_the_lane(self, tmp_path):
        other = TopstepXContract(id=OTHER_CID, name="ESU6", description="ES",
                                 tick_size=0.25, tick_value=12.5, active=True)
        ps, _, hub = make(tmp_path, quote_provider=LiveQuoteProvider(FakeHub(), other))
        with pytest.raises(ProductionLaneRefused, match=OTHER_CID):
            ps.open_lane()

    def test_unexplained_open_state_refuses_the_lane(self, tmp_path):
        ps, _, _ = make(tmp_path, session=BlockedSession(
            positions=[{"contractId": CID, "size": 1}], hub=FakeHub()))
        with pytest.raises(ProductionLaneRefused, match="not flat"):
            ps.open_lane()


class TestProductionSizing:

    def test_the_lane_sizes_under_production_doctrine_not_smoke(self, tmp_path):
        ps, _, hub = make(tmp_path)
        cs = snapshot()                      # 10-point stop
        r = ps.build_runner(cs)
        assert r.geometry.size > 1           # smoke would have forced exactly 1
        assert r.max_risk_usd == PRODUCTION_MAX_RISK_USD
        assert r.max_stop_points == ABSOLUTE_MAX_STOP_POINTS
        assert r.max_contracts == PRODUCTION_MAX_CONTRACTS

    def test_a_stop_beyond_the_absolute_ceiling_is_rejected_not_resized(self, tmp_path):
        ps, _, _ = make(tmp_path)
        cs = snapshot(stop=29700.0, target=29900.0)   # 60 points
        with pytest.raises(RiskRejection):
            ps.build_runner(cs)

    def test_the_structural_stop_is_never_moved_to_fit(self, tmp_path):
        ps, _, _ = make(tmp_path)
        # 28-point stop, inside the preferred lane. The target must clear the
        # 1.5 R:R floor (42 points) or the setup is rejected on reward, which
        # would prove nothing about whether the stop was moved.
        cs = snapshot(stop=29732.0, target=29825.0)
        r = ps.build_runner(cs)
        assert r.geometry.stop_price == 29732.0


class TestSubmitPath:

    def test_submit_attaches_the_live_quote_and_still_never_fills(self, tmp_path):
        ps, s, hub = make(tmp_path)
        ps.open_lane()
        quoted(hub)
        cs = snapshot()
        with pytest.raises(R.RunnerHalt):
            ps.submit(candidate=cs, market=market(), latest_price=29760.0,
                      mint_token=mint(cs), account_id=1)
        assert ps.runner.entry_capture is not None
        assert ps.runner.entry_capture.best_ask == 29760.0
        assert s.place_calls == 1            # blocked at the venue seam

    def test_a_failed_gate_captures_nothing_and_touches_no_venue(self, tmp_path):
        ps, s, hub = make(tmp_path)
        ps.open_lane()
        quoted(hub)
        cs = snapshot()
        with pytest.raises(R.RunnerHalt):
            ps.submit(candidate=cs, market=market(low_since=29740.0),
                      latest_price=29760.0, mint_token=mint(cs), account_id=1)
        assert ps.runner.entry_capture is None and s.place_calls == 0


class TestEntryReconciliation:

    def entered(self, tmp_path, direction="bullish"):
        ps, s, hub = make(tmp_path)
        ps.open_lane()
        quoted(hub)
        cs = snapshot(direction=direction)
        ps.build_runner(cs)
        ps.runner.entry_capture = ps.quote_provider.capture()
        ps.runner.order_id = 900
        ps.runner.submit_at = NOW
        ps.ledger.record_token("tok-1")
        return ps, s, cs

    def orders(self):
        return [{"id": 900, "customTag": LG.bot_tag("tok-1")}]

    def test_the_entry_produces_one_observation_and_a_context(self, tmp_path):
        ps, _, cs = self.entered(tmp_path)
        out = ps.reconcile_entry(
            candidate=cs, orders=self.orders(),
            trades=[{"orderId": 900, "price": 29760.25, "size": 5}],
            fill_event={"price": 29760.25, "size": 5, "at": NOW, "trade_id": 7},
            stop_order_id=901, target_order_id=902)
        assert out["observation"]["kind"] == "ENTRY"
        assert out["attribution"] == LG.EXPANSION_BOT
        assert len(ps.slippage.observations) == 1

    def test_partial_fills_collapse_to_one_observation(self, tmp_path):
        ps, _, cs = self.entered(tmp_path)
        out = ps.reconcile_entry(
            candidate=cs, orders=self.orders(),
            trades=[{"orderId": 900, "price": 29760.0, "size": 2},
                    {"orderId": 900, "price": 29760.5, "size": 2}],
            fill_event={"price": 29760.0, "size": 4, "at": NOW})
        assert len(ps.slippage.observations) == 1
        assert out["observation"]["quantity"] == 4

    def test_the_context_carries_the_identity_the_exit_will_need(self, tmp_path):
        ps, _, cs = self.entered(tmp_path)
        out = ps.reconcile_entry(
            candidate=cs, orders=self.orders(), trades=[],
            fill_event={"price": 29760.0, "size": 3, "at": NOW},
            stop_order_id=901, target_order_id=902)
        ctx = out["context"]
        assert ctx["candidate_id"] == "cand-A"
        assert ctx["candidate_fingerprint"] == cs.fingerprint()
        assert ctx["stop_order_id"] == 901 and ctx["target_order_id"] == 902
        assert ctx["structural_stop_price"] == cs.invalidation_price
        assert os.path.exists(ps.context_path)

    def test_measurement_failure_never_stops_the_context_being_written(self, tmp_path):
        ps, _, cs = self.entered(tmp_path)
        ps.runner.measure_entry_slippage = lambda **kw: (_ for _ in ()).throw(
            RuntimeError("ledger unavailable"))
        out = ps.reconcile_entry(candidate=cs, orders=[], trades=[],
                                 fill_event={"price": 29760.0, "size": 1, "at": NOW})
        assert out["observation"]["reliable"] is False
        assert os.path.exists(ps.context_path)

    def test_attribution_joins_the_trade_to_its_parent_order(self, tmp_path):
        """The venue strips customTag from trades; the tag lives on the order."""
        ps, _, cs = self.entered(tmp_path)
        out = ps.reconcile_entry(
            candidate=cs, orders=self.orders(),
            trades=[{"orderId": 900, "price": 29760.0, "size": 1, "customTag": None}],
            fill_event={"price": 29760.0, "size": 1, "at": NOW})
        assert out["attribution"] == LG.EXPANSION_BOT

    def test_an_untagged_order_is_not_claimed_as_the_bots(self, tmp_path):
        ps, _, cs = self.entered(tmp_path)
        out = ps.reconcile_entry(
            candidate=cs, orders=[{"id": 900, "customTag": None}],
            trades=[{"orderId": 900, "price": 29760.0, "size": 1}],
            fill_event={"price": 29760.0, "size": 1, "at": NOW})
        assert out["attribution"] == LG.MANUAL_OPERATOR


class TestExitReconciliation:

    def positioned(self, tmp_path):
        ps, s, hub = make(tmp_path)
        ps.open_lane()
        quoted(hub)
        cs = snapshot()
        ps.build_runner(cs)
        ps.runner.entry_capture = ps.quote_provider.capture()
        ps.runner.order_id = 900
        ps.ledger.record_token("tok-1")
        ps.reconcile_entry(candidate=cs, orders=[], trades=[],
                           fill_event={"price": 29760.0, "size": 3, "at": NOW},
                           stop_order_id=901, target_order_id=902)
        ps.slippage.observations.clear()
        return ps, cs

    def test_a_target_exit_is_measured_against_the_liquidity_objective(self, tmp_path):
        ps, cs = self.positioned(tmp_path)
        out = ps.reconcile_exit(candidate=cs, exit_type=SL.EXIT_TARGET, trades=[],
                                orders=[], exit_order_id=902,
                                fill_price=29790.0, quantity=3)
        assert out["requested_price"] == cs.objective.price
        assert out["observation"]["exit_type"] == SL.EXIT_TARGET

    def test_a_stop_exit_is_measured_against_the_structural_stop(self, tmp_path):
        ps, cs = self.positioned(tmp_path)
        out = ps.reconcile_exit(candidate=cs, exit_type=SL.EXIT_STOP, trades=[],
                                orders=[], exit_order_id=901,
                                fill_price=29749.5, quantity=3)
        assert out["requested_price"] == cs.invalidation_price

    def test_a_flatten_is_not_measured_against_a_price_it_never_aimed_at(self, tmp_path):
        ps, cs = self.positioned(tmp_path)
        out = ps.reconcile_exit(candidate=cs, exit_type=SL.EXIT_EMERGENCY_FLATTEN,
                                trades=[], orders=[], exit_order_id=903,
                                fill_price=29755.0, quantity=3)
        assert out["requested_price"] is None

    def test_entry_and_exit_pair_into_exactly_one_round_trip(self, tmp_path):
        ps, cs = self.positioned(tmp_path)
        ps.slippage.observations.clear()
        ps.runner.measure_entry_slippage(
            fill_event={"price": 29760.0, "size": 3, "at": NOW},
            candidate_snapshot=cs, ledger=ps.slippage)
        ps.reconcile_exit(
            candidate=cs, exit_type=SL.EXIT_TARGET, trades=[],
            orders=[{"id": 902, "customTag": LG.bot_tag("tok-1") + "-TP"}],
            exit_order_id=902, fill_price=29790.0, quantity=3)
        assert ps.slippage.round_trips() == 1

    def test_a_venue_derived_protective_leg_is_the_bots_own_order(self, tmp_path):
        """Mission F: the venue suffixes the entry tag for the stop and target.

        Read literally those legs are unknown tags, which would mark every
        stop/target exit unreliable — no round trip could ever accumulate — and
        trip the pause law on the bot's own stop firing.
        """
        ps, cs = self.positioned(tmp_path)
        for suffix, oid in (("-SL", 901), ("-TP", 902)):
            out = ps.reconcile_exit(
                candidate=cs, exit_type=SL.EXIT_STOP, trades=[],
                orders=[{"id": oid, "customTag": LG.bot_tag("tok-1") + suffix}],
                exit_order_id=oid, fill_price=29750.0, quantity=3)
            assert out["attribution"] == LG.EXPANSION_BOT

    def test_an_unrelated_tagged_order_is_still_an_intruder(self, tmp_path):
        ps, cs = self.positioned(tmp_path)
        out = ps.reconcile_exit(
            candidate=cs, exit_type=SL.EXIT_STOP, trades=[],
            orders=[{"id": 905, "customTag": LG.bot_tag("someone-else") + "-SL"}],
            exit_order_id=905, fill_price=29750.0, quantity=3)
        assert out["attribution"] == LG.UNKNOWN_EXTERNAL

    def test_the_sample_is_reported_as_insufficient_until_it_is_earned(self, tmp_path):
        ps, cs = self.positioned(tmp_path)
        out = ps.reconcile_exit(candidate=cs, exit_type=SL.EXIT_TARGET, trades=[],
                                orders=[], exit_order_id=902, fill_price=29790.0,
                                quantity=3)
        assert out["sample"]["sufficient"] is False


class TestRestartRecovery:

    def test_an_unresolved_context_with_an_open_position_forbids_a_new_entry(self, tmp_path):
        ps, _, hub = make(tmp_path)
        # The provider only sees quotes published AFTER it attaches to the hub,
        # so the lane opens first — exactly as it does at startup.
        ps.open_lane()
        quoted(hub)
        cs = snapshot()
        ps.build_runner(cs)
        ps.runner.order_id = 900
        ps.reconcile_entry(candidate=cs, orders=[], trades=[],
                           fill_event={"price": 29760.0, "size": 3, "at": NOW})

        fresh, _, hub2 = make(tmp_path, session=BlockedSession(
            positions=[{"contractId": CID, "size": 3}], hub=FakeHub()))
        lane = fresh.open_lane()
        assert lane["lane"] == "RECOVERY"
        assert lane["new_entry_permitted"] is False
        assert lane["context"]["candidate_id"] == "cand-A"

    def test_recovery_reloads_the_stop_and_target_order_ids(self, tmp_path):
        ps, _, hub = make(tmp_path)
        # The provider only sees quotes published AFTER it attaches to the hub,
        # so the lane opens first — exactly as it does at startup.
        ps.open_lane()
        quoted(hub)
        cs = snapshot()
        ps.build_runner(cs)
        ps.runner.order_id = 900
        ps.reconcile_entry(candidate=cs, orders=[], trades=[],
                           fill_event={"price": 29760.0, "size": 3, "at": NOW},
                           stop_order_id=901, target_order_id=902)
        ctx = SL.ExecutionContext.load(ps.context_path)
        assert (ctx.stop_order_id, ctx.target_order_id) == (901, 902)

    def test_a_restart_still_recognises_the_bots_own_orders(self, tmp_path):
        """Without persisted tokens, recovery reads our own fills as an intruder."""
        led = LG.SessionLedger.load_or_new(FP, "20260805", str(tmp_path))
        led.record_token("tok-1")
        led.save()
        again = LG.SessionLedger.load_or_new(FP, "20260805", str(tmp_path))
        assert "tok-1" in again.known_token_ids
        assert LG.classify({"orderId": 900}, again.known_token_ids,
                           {900: {"customTag": LG.bot_tag("tok-1")}}) == LG.EXPANSION_BOT


class TestSessionOwnsNoTransport:
    """The execution session consumes market state; it never owns the socket."""

    def test_it_has_no_pump_loop_of_its_own(self):
        assert not hasattr(ProductionSession, "_pump_forever")

    def test_it_never_calls_pump_reconnect_or_close(self):
        import ast
        src = open(os.path.join("src", "broker", "topstepx_production_session.py"),
                   encoding="utf-8").read()
        calls = [getattr(n.func, "attr", "") for n in ast.walk(ast.parse(src))
                 if isinstance(n, ast.Call)]
        for banned in ("pump", "reconnect", "close", "connect_market_hub"):
            assert banned not in calls

    def test_it_starts_no_thread(self):
        import ast
        src = open(os.path.join("src", "broker", "topstepx_production_session.py"),
                   encoding="utf-8").read()
        assert "Thread" not in src

    def test_start_pump_without_a_runtime_is_refused_not_improvised(self, tmp_path):
        ps, _, _ = make(tmp_path)
        with pytest.raises(ProductionLaneRefused, match="shared market runtime"):
            ps.start_pump()


class TestStartupTelemetryAndRefusals:

    def test_telemetry_declares_the_caller_wiring(self, tmp_path):
        ps, _, hub = make(tmp_path)
        # The provider only sees quotes published AFTER it attaches to the hub,
        # so the lane opens first — exactly as it does at startup.
        ps.open_lane()
        quoted(hub)
        out = ps.telemetry()
        assert "SLIPPAGE CAPTURE             : WIRED THROUGH LIVE CALLER" in out
        assert "Topstep realtime in-memory quote stream" in out

    def test_telemetry_is_ascii_safe_for_a_cp1252_console(self, tmp_path):
        ps, _, hub = make(tmp_path)
        # The provider only sees quotes published AFTER it attaches to the hub,
        # so the lane opens first — exactly as it does at startup.
        ps.open_lane()
        quoted(hub)
        ps.telemetry().encode("cp1252")

    def test_a_foreign_data_provider_refuses_startup(self):
        from tools.topstepx_production_session import check_startup as chk
        s = BlockedSession(hub=FakeHub())
        s.account = type("A", (), {"id": 1})()
        s.contract = MNQ
        os.environ.setdefault("TOPSTEPX_ACCOUNT_FINGERPRINT", FP)
        out = chk(s, armed=False, mission_id="", provider="alpaca")
        assert any(r.startswith("FOREIGN_DATA_PROVIDER") for r in out)

    def test_an_armed_session_without_a_mission_id_refuses_startup(self):
        from tools.topstepx_production_session import check_startup as chk
        s = BlockedSession(hub=FakeHub())
        s.account = type("A", (), {"id": 1})()
        s.contract = MNQ
        os.environ.setdefault("TOPSTEPX_ACCOUNT_FINGERPRINT", FP)
        out = chk(s, armed=True, mission_id="", provider="topstepx")
        assert any(r.startswith("NO_MISSION_ID") for r in out)

    def test_the_entry_point_enforces_the_fingerprint_at_the_pin(self):
        """Pinning by id alone accepts whichever account now holds that id."""
        import ast
        import textwrap
        src = open(os.path.join("tools", "topstepx_production_session.py"),
                   encoding="utf-8").read()
        pin = [n for n in ast.walk(ast.parse(textwrap.dedent(src)))
               if isinstance(n, ast.Call) and getattr(n.func, "attr", "") == "pin"][0]
        assert "expected_fingerprint" in [k.arg for k in pin.keywords]

    def test_the_entry_point_places_no_order_unless_armed(self):
        import ast
        src = open(os.path.join("tools", "topstepx_production_session.py"),
                   encoding="utf-8").read()
        calls = [getattr(n.func, "attr", "") for n in ast.walk(ast.parse(src))
                 if isinstance(n, ast.Call)]
        for banned in ("place_order", "submit", "close_position", "cancel_order"):
            assert banned not in calls
