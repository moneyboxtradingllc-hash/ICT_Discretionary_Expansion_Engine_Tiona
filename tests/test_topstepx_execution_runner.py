"""Execution-runner locks: single-flight Brain, staleness, one-entry-ever,
uncertain-submit reconciliation, bracket proof, flatten and final invariant.

No network, no model calls, no orders.
"""
from __future__ import annotations

import os
import sys
from datetime import datetime, timedelta, timezone

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src"))

from ai_brain.production_model import PRODUCTION_MODEL  # noqa: E402

from ai_brain import engine_payload_audit as engine_audit    # noqa: E402
from ai_brain.brain_request_guard import (                   # noqa: E402
    AI_BUSY, AI_OK, AI_STALE, AI_SUPERSEDED, AI_TIMEOUT, BrainBusyError,
    BrainRequestGuard, configured_timeout,
)
from ai_brain.model_pricing import (                         # noqa: E402
    PRICING, PRODUCTION_MODEL, UnknownModelPricing, cost_from_usage,
    estimate_session_cost, pricing_for,
)
from broker import topstepx_execution_runner as R            # noqa: E402
from broker import topstepx_smoke_auth as smoke_auth         # noqa: E402
from broker.topstepx_client import TopstepXContract, TopstepXError  # noqa: E402

MNQ = TopstepXContract(id="CON.F.US.MNQ.U26", name="MNQU6", description="MNQ",
                       tick_size=0.25, tick_value=0.5, active=True)
FP = "acct:fc84f7a928d9"
NOW = datetime(2026, 8, 5, 14, 0, tzinfo=timezone.utc)


class FakeSession:
    """Write-capable venue double. Records everything; invents nothing."""

    def __init__(self, positions=None, orders=None, place=None, raise_on_place=None):
        self._positions = list(positions or [])
        self._orders = list(orders or [])
        self._place = place
        self._raise = raise_on_place
        self.placed, self.cancelled, self.closed = [], [], []

    def open_positions(self):
        return list(self._positions)

    def query_orders(self, *, statuses=None, contract_id=None):
        """`/api/Order/v2/query` -- the COMPLETE discovery surface.

        A venue WITHOUT this method is the degraded `searchOpen` fallback, and
        an INCOMPLETE order view can no longer authorize a close. So a fixture
        that omits it is asserting the outage path, not the normal one.
        """
        rows = self.open_orders()
        if contract_id:
            rows = [o for o in rows
                    if (o.get("contract_id") or o.get("contractId")) == contract_id]
        return rows

    def open_orders(self):
        return list(self._orders)

    def place_order(self, payload):
        self.placed.append(payload)
        if self._raise:
            raise self._raise
        return self._place if self._place is not None else {"order_id": 9056}

    def cancel_order(self, order_id):
        self.cancelled.append(order_id)
        self._orders = [o for o in self._orders if o.get("id") != order_id]
        return {"success": True}

    def close_position(self, contract_id):
        self.closed.append(contract_id)
        self._positions = []
        return {"success": True}


def _engine_payload(drop=()):
    """A payload populating every REQUIRED engine unless asked to drop some."""
    full = {
        "STRUCTURE_WITNESS": {"5m": {"bos_event": True}},
        "liquidity": {"events": [{"tf": "5m", "sweep": "down"}]},
        "delivery": {"state": "bullish_delivery",
                     "po3_15m": {"phase": "distribution"}},
        "market": {"volatility_state": "expansion"},
        "session": "ny_am",
        "adaptive_learning_context": {"grade": "B"},
        "memory_retrieval": {"count": 3, "analogs": [{"id": 1}]},
        "playbook_toolbox": {"long": ["continuation"], "short": []},
        "stance_history": {"available": True, "active": "bullish"},
        "protected_swings": {"protected_low": 19975.0},
    }
    for key in drop:
        full.pop(key, None)
    return full


def _candidate(**over):
    c = {
        "snapshot_id": "snap-1",
        "brain_result": {"ok": True, "fallback_reason": None, "model": PRODUCTION_MODEL},
        "ai_state": AI_OK,
        "sovereign": True,
        "direction": "bullish",
        "opportunity": True,
        "playbook_family": "continuation",
        "tool_family": ["fvg"],
        "qualified": True,
        "brain_input": _engine_payload(),
        "account_fingerprint": FP,
        "contract_id": MNQ.id,
        "market_data_age_seconds": 2.0,
        "user_stream_healthy": True,
        "entry_price": 20000.0,
        "invalidation_level": 19995.0,   # 5.00 pts = 20 ticks = $10 (smoke-legal)
        "target_price": 20015.0,        # 15.00 pts = $30 reward = 3.0R
    }
    c.update(over)
    return c


def _runner(session=None, **kw):
    return R.ExecutionRunner(session=session or FakeSession(),
                             account_fingerprint=FP, contract=MNQ,
                             clock=lambda: NOW, **kw)


def _token(now=None):
    return smoke_auth.issue(phrase=smoke_auth.AUTHORIZATION_PHRASE,
                            account_fingerprint=FP, contract_id=MNQ.id,
                            now=now or NOW)


# ══════════════════════════════════════════════════════════════════════════════
class TestProductionModelPricing:
    """Rates follow the production model. Terra costs 12.5x Luna on both sides.

    MODEL-IDENTITY-CONSISTENCY-1 (2026-08-20): this class asserted Terra was in
    force, which was true under the 2026-08-06 migration and false after the
    operator's 2026-08-19 Luna ruling. Where the SUBJECT is the rate, the rate
    is now named explicitly and historically; where the subject is the
    arithmetic, it reads the rate off `PRODUCTION_MODEL` so the next ruling
    cannot leave a stale literal behind again.
    """

    TERRA = {"input": 2.50, "cached_input": 0.25, "output": 15.00}
    LUNA = {"input": 0.20, "cached_input": 0.02, "output": 1.20}

    def test_the_production_pricing_is_in_force(self):
        assert PRICING[PRODUCTION_MODEL] == self.LUNA

    def test_the_reserved_terra_pricing_is_retained_for_historical_cost_audits(self):
        """August 6-19 ran on Terra; that spend must stay reproducible, and
        Terra stays priced for the Combine phase it is reserved for."""
        assert PRICING["gpt-5.6-terra"] == self.TERRA

    def test_the_operator_worked_example_reproduces_on_terra(self):
        """6,800 in + 1,300 out at Terra rates — a HISTORICAL example, so the
        model is named rather than inherited from whatever runs today."""
        est = estimate_session_cost(6800, 1300, 148, model="gpt-5.6-terra")
        per_call = (6800 * 2.50 + 1300 * 15.00) / 1_000_000
        assert est["cost_per_call_usd"] == pytest.approx(per_call, abs=1e-6)
        assert est["session_cost_usd"] == pytest.approx(per_call * 148, abs=1e-4)

    def test_cost_comes_from_returned_usage_not_assumptions(self):
        rate = PRICING[PRODUCTION_MODEL]
        c = cost_from_usage({"prompt_tokens": 1000, "completion_tokens": 100,
                             "prompt_tokens_details": {"cached_tokens": 400}})
        expected = (600 * rate["input"] + 400 * rate["cached_input"]
                    + 100 * rate["output"]) / 1_000_000
        assert c["cost_usd"] == round(expected, 6)

    def test_reasoning_tokens_are_reported_but_not_double_billed(self):
        rate = PRICING[PRODUCTION_MODEL]
        c = cost_from_usage({"prompt_tokens": 0, "completion_tokens": 100,
                             "completion_tokens_details": {"reasoning_tokens": 60}})
        assert c["reasoning_tokens"] == 60
        assert c["cost_usd"] == round(100 * rate["output"] / 1_000_000, 6)

    def test_pricing_lives_in_exactly_one_place(self):
        from ai_brain import luna_health
        assert luna_health.LUNA_PRICING is PRICING[PRODUCTION_MODEL]

    def test_an_unpriced_model_refuses_to_invent_a_cost(self):
        with pytest.raises(UnknownModelPricing):
            pricing_for("gpt-9-imaginary")
        assert cost_from_usage({"prompt_tokens": 1}, "gpt-9-imaginary")["cost_usd"] is None

    def test_cached_tokens_can_never_exceed_prompt_tokens(self):
        c = cost_from_usage({"prompt_tokens": 100, "completion_tokens": 0,
                             "prompt_tokens_details": {"cached_tokens": 500}})
        assert c["fresh_input_tokens"] == 0 and c["cached_input_tokens"] == 100


class TestBrainRequestGuard:

    def _begin(self, g, rid="r1", snap="snap-1"):
        return g.begin(request_id=rid, snapshot_id=snap, snapshot_timestamp="t",
                       market_data_timestamp="t", contract_id=MNQ.id,
                       account_fingerprint=FP, now=NOW)

    def test_only_one_request_can_be_in_flight(self):
        g = BrainRequestGuard()
        self._begin(g, "r1")
        with pytest.raises(BrainBusyError):
            self._begin(g, "r2")
        assert g.telemetry[-1]["state"] == AI_BUSY

    def test_a_completed_request_frees_the_slot(self):
        g = BrainRequestGuard()
        b = self._begin(g, "r1")
        g.complete(b, snapshot_id="snap-1", contract_id=MNQ.id,
                   account_fingerprint=FP, latency_seconds=1.0, now=NOW)
        assert not g.is_busy()
        self._begin(g, "r2")          # no raise

    def test_a_timed_out_request_can_never_re_enter(self):
        """The whole point of poisoning: a late answer is not an answer."""
        g = BrainRequestGuard()
        b = self._begin(g, "r1")
        g.abandon(b, AI_TIMEOUT)
        out = g.complete(b, snapshot_id="snap-1", contract_id=MNQ.id,
                         account_fingerprint=FP, latency_seconds=1.0, now=NOW)
        assert out["state"] == AI_SUPERSEDED
        assert g.is_abandoned("r1")

    def test_a_response_slower_than_the_timeout_is_rejected(self):
        g = BrainRequestGuard(timeout_seconds=45.0)
        b = self._begin(g)
        out = g.complete(b, snapshot_id="snap-1", contract_id=MNQ.id,
                         account_fingerprint=FP, latency_seconds=46.0, now=NOW)
        assert out["state"] == AI_TIMEOUT

    def test_a_superseded_snapshot_is_rejected(self):
        g = BrainRequestGuard()
        b = self._begin(g)
        out = g.complete(b, snapshot_id="snap-2", contract_id=MNQ.id,
                         account_fingerprint=FP, latency_seconds=1.0, now=NOW)
        assert out["state"] == AI_STALE and out["detail"] == "snapshot_superseded"

    def test_a_contract_change_invalidates_the_answer(self):
        g = BrainRequestGuard()
        b = self._begin(g)
        out = g.complete(b, snapshot_id="snap-1", contract_id="CON.F.US.MNQ.Z26",
                         account_fingerprint=FP, latency_seconds=1.0, now=NOW)
        assert out["state"] == AI_STALE and out["detail"] == "contract_mismatch"

    def test_an_account_change_invalidates_the_answer(self):
        g = BrainRequestGuard()
        b = self._begin(g)
        out = g.complete(b, snapshot_id="snap-1", contract_id=MNQ.id,
                         account_fingerprint="acct:other", latency_seconds=1.0, now=NOW)
        assert out["state"] == AI_STALE and out["detail"] == "account_mismatch"

    def test_an_old_but_matching_answer_is_still_stale(self):
        g = BrainRequestGuard(max_response_age_seconds=30.0)
        b = self._begin(g)
        out = g.complete(b, snapshot_id="snap-1", contract_id=MNQ.id,
                         account_fingerprint=FP, latency_seconds=1.0,
                         now=NOW + timedelta(seconds=120))
        assert out["state"] == AI_STALE

    def test_timeout_produces_explicit_telemetry_not_silence(self):
        g = BrainRequestGuard()
        b = self._begin(g)
        entry = g.abandon(b, AI_TIMEOUT)
        assert entry["state"] == AI_TIMEOUT
        assert any(t["state"] == AI_TIMEOUT for t in g.telemetry)

    def test_the_timeout_defaults_to_the_audited_45_seconds(self, monkeypatch):
        monkeypatch.delenv("AI_BRAIN_TIMEOUT_SECONDS", raising=False)
        monkeypatch.delenv("SCAN_INTERVAL_SECONDS", raising=False)
        assert configured_timeout() == 45.0

    def test_the_timeout_can_never_exceed_the_scan_cadence(self, monkeypatch):
        """A Brain timeout longer than the interval guarantees cadence slip."""
        monkeypatch.setenv("AI_BRAIN_TIMEOUT_SECONDS", "300")
        monkeypatch.setenv("SCAN_INTERVAL_SECONDS", "60")
        assert configured_timeout() == 55.0


# ══════════════════════════════════════════════════════════════════════════════
class TestCandidateIntake:

    def armed(self, session=None):
        r = _runner(session)
        r.confirm_readiness({"verdict": "READY", "generated_at_utc": "x"})
        r.arm(_token())
        return r

    def test_a_healthy_candidate_validates(self):
        r = self.armed()
        out = r.accept_candidate(_candidate())
        assert r.state == R.CANDIDATE_VALIDATED
        assert out["provenance"]["is_sovereign"] is True

    def test_a_deterministic_fallback_candidate_is_refused(self):
        r = self.armed()
        with pytest.raises(R.RunnerHalt) as exc:
            r.accept_candidate(_candidate(
                brain_result={"ok": False, "fallback_reason": "llm_error", "model": PRODUCTION_MODEL}))
        assert exc.value.state == R.AI_FALLBACK

    def test_a_thesis_from_another_model_is_refused(self):
        r = self.armed()
        with pytest.raises(R.RunnerHalt) as exc:
            r.accept_candidate(_candidate(
                brain_result={"ok": True, "fallback_reason": None, "model": "gpt-5.6-sol"}))
        assert exc.value.state == R.AI_FALLBACK

    def test_a_timed_out_brain_candidate_is_refused(self):
        r = self.armed()
        with pytest.raises(R.RunnerHalt) as exc:
            r.accept_candidate(_candidate(ai_state=AI_TIMEOUT))
        assert exc.value.state == R.AI_TIMEOUT

    def test_a_stale_brain_candidate_is_refused(self):
        r = self.armed()
        with pytest.raises(R.RunnerHalt) as exc:
            r.accept_candidate(_candidate(ai_state=AI_STALE))
        assert exc.value.state == R.STALE_CANDIDATE

    @pytest.mark.parametrize("field,value,state", [
        ("direction", "neutral", R.QUALIFICATION_REJECTED),
        ("direction", "conflicted", R.QUALIFICATION_REJECTED),
        ("opportunity", False, R.QUALIFICATION_REJECTED),
        ("playbook_family", "", R.QUALIFICATION_REJECTED),
        ("tool_family", [], R.QUALIFICATION_REJECTED),
        ("qualified", False, R.QUALIFICATION_REJECTED),
        ("sovereign", False, R.AI_FALLBACK),
        ("account_fingerprint", "acct:other", R.ACCOUNT_MISMATCH),
        ("contract_id", "CON.F.US.MNQ.Z26", R.CONTRACT_MISMATCH),
        ("market_data_age_seconds", 500.0, R.STREAM_STALE),
        ("user_stream_healthy", False, R.STREAM_STALE),
    ])
    def test_each_intake_requirement_fails_closed(self, field, value, state):
        r = self.armed()
        with pytest.raises(R.RunnerHalt) as exc:
            r.accept_candidate(_candidate(**{field: value}))
        assert exc.value.state == state

    def test_an_absent_required_engine_disqualifies_the_candidate(self):
        """Module existence is not wiring; absence is disqualifying."""
        r = self.armed()
        with pytest.raises(R.RunnerHalt) as exc:
            r.accept_candidate(_candidate(brain_input=_engine_payload(drop=("liquidity",))))
        assert exc.value.state == R.QUALIFICATION_REJECTED
        assert "liquidity" in exc.value.detail

    def test_an_empty_but_present_engine_is_allowed_and_reported(self):
        """No sweep is a valid market state; a missing organ is not."""
        payload = _engine_payload()
        payload["liquidity"] = {"events": []}
        r = self.armed()
        out = r.accept_candidate(_candidate(brain_input=payload))
        assert "liquidity" in out["empty"]
        assert r.state == R.CANDIDATE_VALIDATED

    def test_a_non_flat_account_blocks_intake(self):
        r = self.armed(FakeSession(positions=[{"id": 1}]))
        with pytest.raises(R.RunnerHalt) as exc:
            r.accept_candidate(_candidate())
        assert exc.value.state == R.RESIDUAL_ORDERS

    def test_existing_working_orders_block_intake(self):
        r = self.armed(FakeSession(orders=[{"id": 5, "contract_id": MNQ.id}]))
        with pytest.raises(R.RunnerHalt) as exc:
            r.accept_candidate(_candidate())
        assert exc.value.state == R.RESIDUAL_ORDERS

    def test_a_second_candidate_is_suppressed_after_an_entry(self):
        r = self.armed()
        r.accept_candidate(_candidate())
        r.approve_risk(_candidate())
        r.submit(account_id=1)
        with pytest.raises(R.RunnerHalt) as exc:
            r.accept_candidate(_candidate())
        assert exc.value.state == R.RESIDUAL_ORDERS


class TestRiskAtSubmit:

    def armed(self, session=None):
        r = _runner(session)
        r.confirm_readiness({"verdict": "READY"})
        r.arm(_token())
        r.accept_candidate(_candidate())
        return r

    def test_risk_is_recalculated_from_the_freshest_price(self):
        r = self.armed()
        r.approve_risk(_candidate())
        assert r.geometry.risk_usd == 10.00
        r.recheck_risk_at_submit(20002.0)     # 7.00 pts to stop = 28 ticks = $14
        assert r.geometry.risk_usd == 14.00

    def test_price_drift_that_pushes_risk_over_the_cap_is_rejected(self):
        """Drift away from the stop widens realized risk; that is a refusal."""
        r = self.armed()
        r.approve_risk(_candidate())
        with pytest.raises(R.RunnerHalt) as exc:
            r.recheck_risk_at_submit(20006.0)   # 11.00 pts > 10-pt smoke cap
        assert exc.value.state == R.RISK_REJECTED

    def test_risk_over_cap_at_approval_is_rejected(self):
        r = self.armed()
        with pytest.raises(R.RunnerHalt) as exc:
            r.approve_risk(_candidate(invalidation_level=19980.0))   # 20 pts > smoke cap
        assert exc.value.state == R.RISK_REJECTED


class TestSubmissionAndUncertainty:

    def armed(self, session):
        r = _runner(session)
        r.confirm_readiness({"verdict": "READY"})
        r.arm(_token())
        r.accept_candidate(_candidate())
        r.approve_risk(_candidate())
        return r

    def test_the_token_burns_before_the_request_leaves(self):
        s = FakeSession()
        r = self.armed(s)
        token = r.token
        r.submit(account_id=1)
        assert token.spent
        states = [t.state for t in r.transitions]
        assert states.index(R.SUBMITTING) < states.index(R.ACKNOWLEDGED)

    def test_a_rejected_order_still_consumed_the_authorization(self):
        s = FakeSession(place={"order_id": None})
        r = self.armed(s)
        with pytest.raises(R.RunnerHalt) as exc:
            r.submit(account_id=1)
        assert exc.value.state == R.SUBMIT_REJECTED
        assert r.token.spent

    def test_a_timeout_after_submit_never_resubmits(self):
        """UNKNOWN is not permission. Reconcile by asking the venue.

        The order LANDS and then the read times out — the genuinely dangerous
        shape, because the naive response is to retry an order that already
        exists.
        """
        class LandsThenTimesOut(FakeSession):
            def place_order(self, payload):
                self.placed.append(payload)
                self._orders = [{"id": 26970, "contract_id": MNQ.id, "type": 4}]
                raise TimeoutError("read timed out")

        s = LandsThenTimesOut()
        r = self.armed(s)
        out = r.submit(account_id=1)
        assert len(s.placed) == 1, "exactly one submit attempt, ever"
        assert out["reconciled"] is True
        assert R.SUBMIT_UNKNOWN in [t.state for t in r.transitions]

    def test_reconciliation_finding_a_position_reports_filled(self):
        s = FakeSession(positions=[{"id": 1, "contract_id": MNQ.id, "size": 1}],
                        raise_on_place=TimeoutError("boom"))
        # account must be flat at intake, so add the position after
        r = self.armed(FakeSession())
        r.session = s
        out = r.submit(account_id=1)
        assert out["reconciled"] and r.state == R.FILLED

    def test_reconciliation_finding_nothing_halts_without_retrying(self):
        s = FakeSession(raise_on_place=TimeoutError("boom"))
        r = self.armed(s)
        with pytest.raises(R.RunnerHalt) as exc:
            r.submit(account_id=1)
        assert exc.value.state == R.SUBMIT_REJECTED
        assert len(s.placed) == 1

    def test_a_second_submit_is_refused_outright(self):
        s = FakeSession()
        r = self.armed(s)
        r.submit(account_id=1)
        with pytest.raises(R.RunnerHalt):
            r.submit(account_id=1)
        assert len(s.placed) == 1


class TestFillProtectionAndExit:

    def filled(self, position_after_fill=False):
        """Drive to FILLED against a flat account, then seed the post-fill state.

        Intake legitimately refuses a non-flat account, so a live position can
        only be seeded AFTER the entry — which is also the true sequence.
        """
        s = FakeSession()
        r = _runner(s)
        r.confirm_readiness({"verdict": "READY"})
        r.arm(_token())
        r.accept_candidate(_candidate())
        r.approve_risk(_candidate())
        r.submit(account_id=1)
        r.confirm_fill({"size": 1, "price": 20001.0, "contract_id": MNQ.id})
        if position_after_fill:
            s._positions = [{"id": 1, "contract_id": MNQ.id, "size": 1}]
        return r, s

    def test_a_correct_bracket_reaches_protected(self):
        r, _ = self.filled()
        r.verify_protection([
            {"id": 1, "contract_id": MNQ.id, "type": 4, "stop_price": 19995.0},
            {"id": 2, "contract_id": MNQ.id, "type": 1, "limit_price": 20015.0},
        ])
        assert r.state == R.PROTECTED

    def test_fill_drift_from_the_candidate_reference_is_recorded(self):
        """RENAMED: this is drift vs the CANDIDATE reference price, not slippage.

        True slippage compares the fill to the executable quote captured at
        submit (see topstepx_slippage). Calling this value slippage conflated
        market movement since candidate creation with execution quality.
        """
        r, _ = self.filled()
        fill = [t for t in r.transitions if t.state == R.FILLED][-1]
        assert fill.evidence["reference_drift"] == 1.0
        assert "entry_slippage" not in fill.evidence

    def test_a_wrong_size_fill_halts(self):
        r, _ = self.filled()
        r2 = _runner()
        r2.confirm_readiness({"verdict": "READY"})
        r2.arm(_token())
        r2.accept_candidate(_candidate())
        r2.approve_risk(_candidate())
        r2.submit(account_id=1)
        with pytest.raises(R.RunnerHalt) as exc:
            r2.confirm_fill({"size": 2, "price": 20001.0, "contract_id": MNQ.id})
        assert exc.value.state == R.PROTECTION_MISSING

    def test_missing_protection_triggers_emergency_flatten(self):
        r, s = self.filled(position_after_fill=True)
        r.verify_protection([{"id": 1, "contract_id": MNQ.id, "type": 4, "stop_price": 19995.0}])
        assert s.closed == [MNQ.id]
        assert r.state in (R.EMERGENCY_FLATTENING, R.RESIDUAL_ORDERS)

    def test_a_wrongly_signed_bracket_triggers_emergency_flatten(self):
        """A 'stop' above entry on a long is a target wearing a stop's name."""
        r, s = self.filled(position_after_fill=True)
        r.verify_protection([
            {"id": 1, "contract_id": MNQ.id, "type": 4, "stop_price": 20090.0},
            {"id": 2, "contract_id": MNQ.id, "type": 1, "limit_price": 20015.0},
        ])
        assert s.closed == [MNQ.id]

    def test_no_fill_event_halts_as_fill_timeout(self):
        r = _runner()
        r.confirm_readiness({"verdict": "READY"})
        r.arm(_token())
        r.accept_candidate(_candidate())
        r.approve_risk(_candidate())
        r.submit(account_id=1)
        with pytest.raises(R.RunnerHalt) as exc:
            r.confirm_fill({})
        assert exc.value.state == R.FILL_TIMEOUT

    def test_a_residual_opposing_order_is_cancelled_and_recorded_as_a_defect(self):
        # The venue's real shape: a protective leg carries parentOrderId = the
        # entry order. Measured live 2026-08-10 on orders 3386076130/131, whose
        # parent was the entry 3386076129. That lineage is what proves the
        # order is ours and therefore safe to cancel.
        leg = {"id": 77, "contract_id": MNQ.id, "type": 1, "parentOrderId": 9056}
        s = FakeSession(orders=[dict(leg)])
        r, _ = self.filled()
        r.session = s
        out = r.observe_exit({"reason": "stop_filled", "price": 19995.0}, [dict(leg)])
        assert out["residual_cancelled"] == [77]
        assert out["oco_defect"] is True

    def test_an_unaccounted_order_on_our_contract_is_never_cancelled(self):
        """No lineage -> it might be the operator's. Report, never cancel."""
        stranger = {"id": 88, "contract_id": MNQ.id, "type": 1}
        s = FakeSession(orders=[dict(stranger)])
        r, _ = self.filled()
        r.session = s
        out = r.observe_exit({"reason": "stop_filled"}, [dict(stranger)])
        assert out["residual_cancelled"] == []
        assert out["unaccounted_same_contract"] == [88]
        assert s.cancelled == [], "cancelled an order we could not prove was ours"

    def test_an_order_on_another_contract_is_ignored_entirely(self):
        other = {"id": 99, "contract_id": "CON.F.US.ES.U26", "type": 1,
                 "parentOrderId": 9056}
        s = FakeSession(orders=[dict(other)])
        r, _ = self.filled()
        r.session = s
        out = r.observe_exit({"reason": "stop_filled"}, [dict(other)])
        assert out["residual_cancelled"] == []
        assert out["foreign_other_contract"] == [99]
        assert s.cancelled == []

    def test_a_clean_oco_records_no_defect(self):
        r, _ = self.filled()
        out = r.observe_exit({"reason": "target_filled"}, [])
        assert out["residual_cancelled"] == [] and out["oco_defect"] is False


class TestFinalInvariant:

    def _run_to_exit(self, session):
        r = _runner(session)
        r.confirm_readiness({"verdict": "READY"})
        r.arm(_token())
        r.accept_candidate(_candidate())
        r.approve_risk(_candidate())
        r.submit(account_id=1)
        r.confirm_fill({"size": 1, "price": 20000.0, "contract_id": MNQ.id})
        return r

    def test_a_clean_finish_verifies(self):
        r = self._run_to_exit(FakeSession())
        checks = r.verify_clean(current_fingerprint=FP)
        assert r.state == R.VERIFIED_CLEAN
        assert all(checks.values())

    def test_a_remaining_position_fails_the_invariant(self):
        s = FakeSession()
        r = self._run_to_exit(s)
        s._positions = [{"id": 1, "contract_id": MNQ.id}]
        with pytest.raises(R.RunnerHalt) as exc:
            r.verify_clean(current_fingerprint=FP)
        assert exc.value.state == R.FLATTEN_FAILED

    def test_a_residual_working_order_fails_the_invariant(self):
        s = FakeSession()
        r = self._run_to_exit(s)
        s._orders = [{"id": 9, "contract_id": MNQ.id}]
        with pytest.raises(R.RunnerHalt) as exc:
            r.verify_clean(current_fingerprint=FP)
        assert exc.value.state == R.RESIDUAL_ORDERS

    def test_a_changed_account_fingerprint_fails_the_invariant(self):
        r = self._run_to_exit(FakeSession())
        with pytest.raises(R.RunnerHalt) as exc:
            r.verify_clean(current_fingerprint="acct:changed")
        assert exc.value.state == R.ACCOUNT_MISMATCH

    def test_the_final_check_asks_rest_even_when_realtime_says_flat(self):
        class Counting(FakeSession):
            def __init__(self):
                super().__init__()
                self.position_reads = 0

            def open_positions(self):
                self.position_reads += 1
                return []

        s = Counting()
        r = self._run_to_exit(s)
        before = s.position_reads
        r.verify_clean(current_fingerprint=FP)
        assert s.position_reads > before

    def test_the_artifact_is_redacted_and_complete(self, tmp_path):
        r = self._run_to_exit(FakeSession())
        r.verify_clean(current_fingerprint=FP)
        art = r.build_artifact(readiness_ref="ref", candidate=_candidate(),
                               intake={"inventory": {}, "empty": [], "provenance": {}},
                               luna_usage=cost_from_usage({"prompt_tokens": 6800,
                                                           "completion_tokens": 1300}))
        p = r.write_artifact(str(tmp_path / "lifecycle.json"))
        body = open(p, encoding="utf-8").read()
        assert art["succeeded"] is True
        assert "[REDACTED]" in body                       # accountId digest masked
        # Cost follows the production model; Terra is 12.5x Luna per token.
        rate = PRICING[PRODUCTION_MODEL]
        expected = (6800 * rate["input"] + 1300 * rate["output"]) / 1_000_000
        assert art["luna_usage"]["cost_usd"] == pytest.approx(expected, abs=1e-6)
        assert art["transitions"] and art["risk"]["risk_usd"] == 10.0

    def test_every_transition_is_timestamped(self):
        r = self._run_to_exit(FakeSession())
        assert all(t.at is not None for t in r.transitions)
        assert [t.state for t in r.transitions][:4] == [
            R.READINESS_CONFIRMED, R.AUTHORIZED, R.WAITING_FOR_CANDIDATE, R.CANDIDATE_RECEIVED]

    def test_the_failure_state_vocabulary_is_complete(self):
        for s in ("AUTH_EXPIRED", "STALE_CANDIDATE", "AI_TIMEOUT", "AI_FALLBACK",
                  "QUALIFICATION_REJECTED", "RISK_REJECTED", "SUBMIT_REJECTED",
                  "ACK_TIMEOUT", "FILL_TIMEOUT", "PROTECTION_MISSING", "STREAM_STALE",
                  "ACCOUNT_MISMATCH", "CONTRACT_MISMATCH", "EMERGENCY_FLATTENING",
                  "FLATTEN_FAILED", "RESIDUAL_ORDERS"):
            assert s in R.FAILURE_STATES


class TestAuthorizationGating:

    def test_the_runner_never_mints_a_token(self):
        import ast
        import inspect
        tree = ast.parse(inspect.getsource(R))
        for node in ast.walk(tree):
            if isinstance(node, ast.Attribute) and node.attr == "issue":
                pytest.fail("execution runner must never mint an authorization")

    def test_an_expired_token_cannot_arm_the_runner(self):
        old = smoke_auth.issue(phrase=smoke_auth.AUTHORIZATION_PHRASE,
                               account_fingerprint=FP, contract_id=MNQ.id,
                               now=NOW - timedelta(hours=3))
        r = _runner()
        r.confirm_readiness({"verdict": "READY"})
        with pytest.raises(R.RunnerHalt) as exc:
            r.arm(old)
        assert exc.value.state == R.AUTH_EXPIRED

    def test_a_spent_token_cannot_arm_the_runner(self):
        t = _token()
        t.burn("earlier")
        r = _runner()
        r.confirm_readiness({"verdict": "READY"})
        with pytest.raises(R.RunnerHalt) as exc:
            r.arm(t)
        assert exc.value.state == R.AUTH_EXPIRED

    def test_a_non_ready_readiness_artifact_blocks_arming(self):
        r = _runner()
        with pytest.raises(R.RunnerHalt):
            r.confirm_readiness({"verdict": "NOT_READY"})
