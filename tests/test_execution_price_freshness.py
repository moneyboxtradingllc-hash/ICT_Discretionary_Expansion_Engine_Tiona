"""EXEC-PRICE-FRESHNESS-1 — a settled close is market truth, not a price.

2026-08-20, 11:02:10 ET. Luna held a bearish thesis at confidence 70, with
`bearish_breaker` and `bearish_ote_after_reclaim` execution-eligible and the
29240.25 sell-side objective authorized. She was handed:

    current_price = 29404.25

The contemporaneous 1m candle was:

    open 29440.75   high 29457.25   low 29423.25   close 29429.50

The market did not trade 29404.25 at any point in that minute. It was the
previous SETTLED close, and `_current_price()` published it as the price of
right now. `_reference_price()` then made it the candidate's `entry_price` --
the origin of every stop distance, reward ratio and side-check in the producer.

Against the 29470.25 protected high that fiction measured a 66.00-point stop
and died on the 40-point ceiling. Every price the market actually offered in
that candle implied 13.00 to 47.00.

    THE DEFECT IS NOT THAT THE NUMBER WAS OLD.
    IT IS THAT TWO DIFFERENT QUESTIONS SHARED ONE FIELD.

"What has the market done" is answered by settled candles and always was.
"What does this trade cost me right now" is answered by a live quote. This unit
separates them, and proves the second never silently falls back to the first --
because that fallback is what put a fictional 66-point stop in front of a real
trade.

Nothing here invents market data. `LiveQuoteProvider` already streamed the real
bid and ask into memory for the submit boundary, and `topstepx_slippage` already
owned MAX_QUOTE_AGE_SECONDS. The decision lane simply never asked.
"""
from __future__ import annotations

import os
import sys
from datetime import datetime, timezone

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from _step7_fixture import detected as _detected                   # noqa: E402

from ai_brain.production_model import PRODUCTION_MODEL              # noqa: E402
from broker import topstepx_execution_price as EP                   # noqa: E402
from broker.luna_candidate_producer import (CandidateProducer,      # noqa: E402
                                            NoCandidate)
from broker.topstepx_client import TopstepXContract                 # noqa: E402
from broker.topstepx_slippage import MAX_QUOTE_AGE_SECONDS, capture_quote  # noqa: E402

CID = "CON.F.US.MNQ.U26"
FP = "acct:fc84f7a928d9"
NOW = datetime(2026, 8, 20, 15, 2, 10, tzinfo=timezone.utc)
MNQ = TopstepXContract(id=CID, name="MNQU6", description="MNQ",
                       tick_size=0.25, tick_value=0.5, active=True)

# ── the tape, verbatim ────────────────────────────────────────────────────────
STALE_SETTLED = 29404.25        # the 11:00 close, handed over as "current"
CANDLE_OPEN = 29440.75
CANDLE_HIGH = 29457.25
CANDLE_LOW = 29423.25
CANDLE_CLOSE = 29429.50
PROTECTED_HIGH = 29470.25       # 5m, the structural invalidation
SELL_SIDE = 29240.25            # OBJ_LIQ_SSL_2, Luna's own named objective
CEILING = 40.0                  # the absolute stop ceiling in force that day


def quote(bid, ask, *, age=0.4):
    return capture_quote(market_hub_quote={"bestBid": bid, "bestAsk": ask,
                                           "lastPrice": bid},
                         contract_id=CID, market_data_age_seconds=age,
                         now=NOW)


def block(bid, ask, *, age=0.4):
    return EP.from_capture(quote(bid, ask, age=age))


# ══════════════════════════════════════════════════════════════════════════════
class TestTheBlock:
    def test_a_fresh_quote_is_available_and_fresh(self):
        b = block(CANDLE_OPEN, CANDLE_OPEN + 0.25)
        assert b["available"] is True and b["fresh"] is True
        assert b["best_bid"] == CANDLE_OPEN
        assert b["source"] == EP.SOURCE
        assert b["unavailable_reason"] is None

    def test_the_freshness_bound_is_the_one_the_submit_boundary_already_uses(self):
        """No new threshold. A second consumer of an existing standard."""
        assert block(1.0, 2.0)["max_age_seconds"] == MAX_QUOTE_AGE_SECONDS

    @pytest.mark.parametrize("age,fresh", [
        (0.0, True), (4.99, True), (MAX_QUOTE_AGE_SECONDS, True),
        (5.01, False), (60.0, False), (1e9, False),
    ])
    def test_freshness_is_decided_at_the_existing_bound(self, age, fresh):
        assert block(100.0, 100.25, age=age)["fresh"] is fresh

    def test_a_stale_quote_is_published_in_full_not_discarded(self):
        """Evidence is labelled, never dropped for being inconvenient."""
        b = block(CANDLE_OPEN, CANDLE_HIGH, age=45.0)
        assert b["fresh"] is False
        assert b["best_bid"] == CANDLE_OPEN          # still there
        assert b["age_seconds"] == 45.0              # and it says how old
        assert b["unavailable_reason"] == EP.STALE_QUOTE

    def test_no_provider_is_a_positive_statement(self):
        b = EP.from_capture(None)
        assert b["available"] is False
        assert b["unavailable_reason"] == EP.NO_QUOTE_PROVIDER

    def test_a_quote_with_no_sides_is_distinguished_from_no_provider(self):
        b = EP.from_capture(quote(None, None))
        assert b["unavailable_reason"] == EP.NO_QUOTE_RECEIVED

    def test_a_missing_quote_reports_an_enormous_age_not_zero(self):
        """The provider's own contract: absent reads stale, never fresh."""
        assert EP.from_capture(quote(1.0, 2.0, age=1e9))["fresh"] is False


class TestTheExecutableSide:
    def test_a_buy_pays_the_ask_and_a_sell_hits_the_bid(self):
        b = block(29440.75, 29441.00)
        assert EP.executable_price(b, "bullish") == 29441.00
        assert EP.executable_price(b, "bearish") == 29440.75

    @pytest.mark.parametrize("word,expected", [
        ("buy", 29441.00), ("long", 29441.00), ("bullish", 29441.00),
        ("sell", 29440.75), ("short", 29440.75), ("bearish", 29440.75),
    ])
    def test_direction_synonyms_resolve_to_one_side(self, word, expected):
        assert EP.executable_price(block(29440.75, 29441.00), word) == expected

    def test_an_unresolved_direction_is_refused_not_guessed(self):
        b = block(29440.75, 29441.00)
        assert EP.executable_price(b, "conflicted") is None
        assert EP.refusal(b, "conflicted") == EP.SIDE_NOT_QUOTED


class TestItNeverFallsBack:
    """The whole point. There is no argument that permits the settled close."""

    def test_a_stale_block_prices_nothing(self):
        b = block(CANDLE_OPEN, CANDLE_HIGH, age=90.0)
        assert EP.executable_price(b, "bearish") is None
        assert EP.refusal(b, "bearish") == EP.STALE_QUOTE

    def test_an_absent_block_prices_nothing(self):
        assert EP.executable_price(EP.unavailable(EP.NO_QUOTE_PROVIDER),
                                   "bearish") is None

    def test_the_module_exposes_no_settled_close_fallback(self):
        """Structural, not textual: no public callable accepts a substitute."""
        import inspect
        for name in ("executable_price", "refusal"):
            params = inspect.signature(getattr(EP, name)).parameters
            assert set(params) == {"block", "direction"}, (name, list(params))

    def test_the_refusal_names_the_age_rather_than_saying_stale(self):
        text = EP.describe(block(CANDLE_OPEN, CANDLE_HIGH, age=73.5))
        assert "73.50s" in text and "STALE" in text


# ══════════════════════════════════════════════════════════════════════════════
class TestTheElevenOhTwoRegression:
    """The real producer, the real numbers, the real geometry."""

    @staticmethod
    def _bearish(execution_block):
        bi = {
            "timestamp": "2026-08-20T15:02:00+00:00",
            "market": {"current_price": STALE_SETTLED,
                       "settled_price_basis": "settled_close:1m",
                       "execution_price": execution_block},
            "liquidity": {"nearest_buy_side": 29520.0, "nearest_sell_side": SELL_SIDE},
            "protected_swings": {
                "protected_low": {"level": 29348.5,
                                  "timestamp": "2026-08-20T14:58:00+00:00"},
                "protected_high": {"level": PROTECTED_HIGH,
                                   "timestamp": "2026-08-20T14:35:00+00:00"},
            },
        }
        parsed = {"narrative_direction": "bearish", "narrative_phase": "continuation",
                  "invalidation_level": PROTECTED_HIGH,
                  "active_draw": "sell side liquidity below",
                  "recommended_playbook_family": "continuation",
                  "recommended_tool_family": ["fvg"],
                  "market_story": "rejected buy-side raid, bearish delivery toward 29240.25",
                  "current_action": "await_retest"}
        producer = CandidateProducer(allow_prose_objective_fallback=True,
                                     account_fingerprint=FP, contract=MNQ)
        return producer.produce(
            brain_result={"ok": True, "parsed": parsed, "fallback_reason": None,
                          "model": PRODUCTION_MODEL},
            brain_input=bi, snapshot=_detected("ifvg", "fvg"),
            qualification={"qualified": True},
            engine_inventory={"liquidity": "PRESENT_AND_POPULATED"},
            snapshot_id="snap-1102",
            market_data_timestamp="2026-08-20T15:02:10+00:00",
            latest_closed_bar_timestamp="2026-08-20T15:01:00+00:00", now=NOW)

    def test_the_candidate_is_priced_from_the_bid_not_the_settled_close(self):
        c = self._bearish(block(CANDLE_OPEN, CANDLE_OPEN + 0.25))
        assert c.entry_price == CANDLE_OPEN
        assert c.entry_price != STALE_SETTLED

    def test_the_stop_is_29_50_points_not_66_00(self):
        """The number that vetoed a 6.8R trade was measured from a fiction."""
        c = self._bearish(block(CANDLE_OPEN, CANDLE_OPEN + 0.25))
        risk = c.invalidation_price - c.entry_price
        assert risk == 29.50
        assert risk <= CEILING                       # legal at the 40 in force
        assert PROTECTED_HIGH - STALE_SETTLED == 66.00   # what it used to be
        assert 66.00 > CEILING                           # and why it died

    def test_the_reward_ratio_recovers(self):
        c = self._bearish(block(CANDLE_OPEN, CANDLE_OPEN + 0.25))
        assert c.objective.price == SELL_SIDE
        assert round(c.extras["expected_reward_to_risk"], 2) == 6.80

    @pytest.mark.parametrize("bid,expected_stop", [
        (CANDLE_HIGH, 13.00),      # the top of the rejection wick
        (CANDLE_OPEN, 29.50),      # ten seconds after the candle opened
        (CANDLE_CLOSE, 40.75),     # where the NEXT scan sampled — over by 0.75
        (CANDLE_LOW, 47.00),       # the worst price the candle ever printed
    ])
    def test_every_price_the_candle_actually_traded(self, bid, expected_stop):
        """The stale field sat 19.00 points below the candle's own low."""
        assert PROTECTED_HIGH - bid == expected_stop
        assert bid > STALE_SETTLED
        c = self._bearish(block(bid, bid + 0.25))
        assert c.invalidation_price - c.entry_price == expected_stop

    def test_the_settled_close_is_still_carried_for_audit(self):
        c = self._bearish(block(CANDLE_OPEN, CANDLE_OPEN + 0.25))
        assert c.extras["settled_price_at_authorship"] == STALE_SETTLED
        assert c.extras["settled_price_basis"] == "settled_close:1m"
        assert c.extras["execution_price_evidence"]["best_bid"] == CANDLE_OPEN
        assert c.extras["execution_price_evidence"]["age_seconds"] == 0.4

    def test_a_stale_quote_refuses_rather_than_using_the_settled_close(self):
        with pytest.raises(NoCandidate) as exc:
            self._bearish(block(CANDLE_OPEN, CANDLE_OPEN + 0.25, age=90.0))
        assert exc.value.reason == "execution_price_unavailable"
        assert EP.STALE_QUOTE in exc.value.detail

    def test_no_quote_at_all_refuses(self):
        with pytest.raises(NoCandidate) as exc:
            self._bearish(EP.unavailable(EP.NO_QUOTE_PROVIDER))
        assert exc.value.reason == "execution_price_unavailable"

    def test_the_refusal_names_the_settled_price_it_declined_to_use(self):
        with pytest.raises(NoCandidate) as exc:
            self._bearish(EP.unavailable(EP.NO_QUOTE_PROVIDER))
        assert str(STALE_SETTLED) in exc.value.detail
        assert "settled" in exc.value.detail.lower()

    def test_the_refusal_is_its_own_trace_stage(self):
        """Unpriceable is not 'bad geometry'. An audit must tell them apart."""
        with pytest.raises(NoCandidate) as exc:
            self._bearish(EP.unavailable(EP.NO_QUOTE_PROVIDER))
        assert exc.value.decision_trace["evidence_integrity"] == "NO_EXECUTABLE_PRICE"


# ══════════════════════════════════════════════════════════════════════════════
class TestTheBrainPayload:
    @staticmethod
    def _built(execution=None, tfs=("1m",)):
        from ai_brain.brain_input import build_brain_input
        bars = [{"timestamp": f"2026-08-20T15:0{i}:00+00:00", "open": 29440.0,
                 "high": 29457.25, "low": 29423.25, "close": CANDLE_CLOSE,
                 "volume": 900} for i in range(5)]
        snapshot = {"timestamp": "2026-08-20T15:02:00+00:00",
                    "timeframes": {tf: {"candles": bars,
                                        "last_candle": {"close": CANDLE_CLOSE}}
                                   for tf in tfs}}
        if execution is not None:
            snapshot["execution_price"] = execution
        return build_brain_input(snapshot, {"available": False})

    def test_both_prices_are_published_side_by_side(self):
        m = self._built(block(CANDLE_OPEN, CANDLE_OPEN + 0.25))["market"]
        assert m["current_price"] == CANDLE_CLOSE            # settled, unchanged
        assert m["execution_price"]["best_bid"] == CANDLE_OPEN
        assert m["execution_price"]["fresh"] is True

    def test_the_settled_field_keeps_its_name_and_meaning(self):
        """Structural consumers must read exactly what they read before."""
        m = self._built(block(1.0, 2.0))["market"]
        assert m["current_price"] == CANDLE_CLOSE
        assert m["settled_price_basis"] == "settled_close:1m"

    def test_an_absent_execution_block_is_stated_as_degraded(self):
        bi = self._built(None)
        assert any(d.startswith("execution_price_unavailable")
                   for d in bi["degraded"]), bi["degraded"]

    def test_a_stale_execution_block_is_stated_as_degraded(self):
        bi = self._built(block(CANDLE_OPEN, CANDLE_HIGH, age=120.0))
        assert "execution_price_stale" in bi["degraded"]

    def test_a_fresh_block_produces_no_price_degradation(self):
        bi = self._built(block(CANDLE_OPEN, CANDLE_OPEN + 0.25))
        assert not [d for d in bi["degraded"] if "execution_price" in d]
        assert not [d for d in bi["degraded"] if "settled_price_basis" in d]


class TestTheSilentFallbackIsNowVisible:
    """1m -> 3m -> 5m -> 15m promoted a fifteen-minute close to 'current'."""

    @pytest.mark.parametrize("tf", ["3m", "5m", "15m"])
    def test_a_coarser_basis_is_declared_degraded(self, tf):
        bi = TestTheBrainPayload._built(block(1.0, 2.0), tfs=(tf,))
        assert bi["market"]["settled_price_basis"] == f"settled_close:{tf}"
        assert f"settled_price_basis:settled_close:{tf}" in bi["degraded"]

    def test_the_finest_timeframe_is_not_flagged(self):
        bi = TestTheBrainPayload._built(block(1.0, 2.0), tfs=("1m",))
        assert not [d for d in bi["degraded"] if d.startswith("settled_price_basis")]

    def test_the_basis_was_previously_unknowable(self):
        """The price is unchanged; what it IS now travels with it."""
        bi = TestTheBrainPayload._built(block(1.0, 2.0), tfs=("15m",))
        assert bi["market"]["current_price"] == CANDLE_CLOSE   # same number
        assert bi["market"]["settled_price_basis"] == "settled_close:15m"


# ══════════════════════════════════════════════════════════════════════════════
class TestTheScanCycleWiring:
    @staticmethod
    def _cycle(provider):
        from live_scan.production_scan_cycle import ProductionScanCycle
        return ProductionScanCycle("MNQ", quote_provider=provider)

    def test_a_wired_provider_reaches_the_snapshot(self):
        b = self._cycle(lambda: quote(CANDLE_OPEN, CANDLE_OPEN + 0.25))._execution_price()
        assert b["available"] is True and b["best_bid"] == CANDLE_OPEN

    def test_no_provider_yields_a_stated_absence(self):
        b = self._cycle(None)._execution_price()
        assert b["available"] is False
        assert b["unavailable_reason"] == EP.NO_QUOTE_PROVIDER

    def test_a_throwing_provider_is_distinguished_from_an_absent_one(self):
        def boom():
            raise RuntimeError("hub dropped")
        b = self._cycle(boom)._execution_price()
        assert b["unavailable_reason"] == EP.QUOTE_PROVIDER_FAILED

    def test_a_broken_stream_never_breaks_the_scan(self):
        def boom():
            raise RuntimeError("hub dropped")
        assert self._cycle(boom)._execution_price()["available"] is False

    def test_the_production_loop_hands_the_session_provider_to_the_cycle(self):
        """AST: the loop must pass the session's provider, not build its own."""
        import ast
        import inspect
        from broker.topstepx_production_loop import ProductionLoop
        src = ast.parse(inspect.getsource(ProductionLoop.__init__).lstrip())
        calls = [n for n in ast.walk(src) if isinstance(n, ast.Call)
                 and "ProductionScanCycle" in ast.unparse(n.func)]
        assert calls, "the loop no longer constructs the scan cycle"
        kw = {k.arg: ast.unparse(k.value) for k in calls[0].keywords}
        assert "quote_provider" in kw
        assert "production_session" in kw["quote_provider"]
        assert "LiveQuoteProvider" not in kw["quote_provider"], \
            "the decision lane must reuse the session's provider, not open a second stream"


class TestPostFillAuthorityIsUntouched:
    """This unit owns PRE-ENTRY economics only."""

    def test_the_runner_still_reauthorizes_against_the_actual_fill(self):
        from broker.topstepx_execution_runner import ExecutionRunner
        assert hasattr(ExecutionRunner, "authorize_actual_fill")
        assert hasattr(ExecutionRunner, "reanchor_protection_to_structure")

    def test_this_unit_added_no_import_to_the_runner(self):
        import inspect
        from broker import topstepx_execution_runner as R
        assert "topstepx_execution_price" not in inspect.getsource(R)
