"""Ledger + freshness wired into the REAL submit path.

Every scenario drives `ExecutionRunner.gated_submit`, the only sanctioned route
to an order. The venue seam is structurally blocked: `place_order` raises if
reached, so "no write" is proven by construction rather than by inspection.
"""
from __future__ import annotations

import os
import sys
from datetime import datetime, timedelta, timezone

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src"))

from broker import topstepx_execution_runner as R                 # noqa: E402
from broker import topstepx_session_ledger as L                   # noqa: E402
from broker import topstepx_smoke_auth as auth                    # noqa: E402
from broker.topstepx_candidate_freshness import (                 # noqa: E402
    CandidateSnapshot, LiquidityObjective,
)
from broker.topstepx_client import TopstepXContract               # noqa: E402

CID = "CON.F.US.MNQ.U26"
FP = "acct:fc84f7a928d9"
NOW = datetime(2026, 8, 5, 15, 30, tzinfo=timezone.utc)
MNQ = TopstepXContract(id=CID, name="MNQU6", description="MNQ",
                       tick_size=0.25, tick_value=0.5, active=True)


class WriteAttempted(AssertionError):
    """The venue seam was reached. In these tests that is always a failure."""


class BlockedSession:
    """Read-only double whose write seam cannot be reached without failing."""

    def __init__(self, positions=None, orders=None):
        self._positions = list(positions or [])
        self._orders = list(orders or [])
        self.place_calls = 0

    def open_positions(self):
        return list(self._positions)

    def open_orders(self):
        return list(self._orders)

    def place_order(self, payload):
        self.place_calls += 1
        raise WriteAttempted("place_order reached — no order is authorized")

    def cancel_order(self, oid):
        raise WriteAttempted("cancel_order reached")

    def close_position(self, cid):
        raise WriteAttempted("close_position reached")


def objective(price=29910.25, kind="prior_session_high"):
    return LiquidityObjective(f"{kind}@{price}", kind, price, NOW - timedelta(minutes=2))


def snapshot(**over):
    kw = dict(candidate_id="c1", snapshot_id="snap-1", direction="bullish",
              entry_price=29880.0, invalidation_price=29875.0, objective=objective(),
              contract_id=CID, account_fingerprint=FP,
              created_at=NOW - timedelta(minutes=1), narrative="bullish continuation")
    kw.update(over)
    return CandidateSnapshot(**kw)


def market(**over):
    kw = dict(current_price=29885.0, high_since=29890.0, low_since=29878.0,
              tick_size=0.25, snapshot_id="snap-1", contract_id=CID,
              account_fingerprint=FP, account_state_digest="", data_age_seconds=2.0,
              in_window=True, manual_activity=False, now=NOW)
    kw.update(over)
    return kw


def ledger(tmp_path):
    return L.SessionLedger.load_or_new(FP, "20260805", str(tmp_path))


def runner(session):
    r = R.ExecutionRunner(session=session, account_fingerprint=FP, contract=MNQ,
                          clock=lambda: NOW)
    r.confirm_readiness({"verdict": "READY"})
    r._to(R.WAITING_FOR_CANDIDATE, "ready")
    return r


def minter(cs, **over):
    def _mint():
        kw = dict(phrase=auth.AUTHORIZATION_PHRASE, account_fingerprint=FP,
                  contract_id=CID, candidate_fingerprint=cs.fingerprint(),
                  snapshot_id=cs.snapshot_id, direction=cs.direction,
                  stop_price=cs.invalidation_price, target_price=cs.objective.price,
                  target_identity=cs.objective.identity, now=NOW)
        kw.update(over)
        return auth.issue(**kw)
    return _mint


def approve(r, cs):
    """Bring the runner to an approved bracket without touching the venue."""
    r.approve_risk({"direction": cs.direction, "entry_price": cs.entry_price,
                    "invalidation_level": cs.invalidation_price,
                    "target_price": cs.objective.price})
    return r


def drive(r, cs, mkt, session, latest_price=29885.0, led=None, refresh=None):
    return r.gated_submit(account_id=1, ledger=led, candidate_snapshot=cs,
                          market=mkt, latest_price=latest_price,
                          mint_token=minter(cs), refresh=refresh)


# ══════════════════════════════════════════════════════════════════════════════
class TestGatedPath:

    def test_1_a_clean_candidate_reaches_the_blocked_write_boundary(self, tmp_path):
        """The happy path traverses every gate and stops at the blocked seam.

        The seam raises, which the runner treats as post-submit UNCERTAINTY and
        reconciles (finding nothing) rather than retrying — exactly right, and
        the reason the halt is SUBMIT_REJECTED rather than the raw exception.
        """
        s = BlockedSession()
        r = approve(runner(s), snapshot())
        with pytest.raises(R.RunnerHalt) as exc:
            drive(r, snapshot(), market(), s, led=ledger(tmp_path))
        assert exc.value.state == R.SUBMIT_REJECTED
        assert s.place_calls == 1                      # reached the seam exactly once
        assert r.token is not None and r.token.spent   # burned before the request
        assert R.SUBMIT_UNKNOWN in [t.state for t in r.transitions]

    def test_2_manual_activity_after_approval_invalidates(self, tmp_path):
        s = BlockedSession()
        r = approve(runner(s), snapshot())
        with pytest.raises(R.RunnerHalt) as exc:
            drive(r, snapshot(), market(manual_activity=True), s, led=ledger(tmp_path))
        assert exc.value.state == R.MANUAL_ACTIVITY_DETECTED
        assert s.place_calls == 0
        assert r.geometry is None and r.token is None   # bracket + token destroyed

    def test_3_unknown_external_order_pauses_the_runner(self, tmp_path):
        s = BlockedSession(orders=[{"id": 1, "contractId": CID, "customTag": "mystery"}])
        r = approve(runner(s), snapshot())
        with pytest.raises(R.RunnerHalt) as exc:
            drive(r, snapshot(), market(), s, led=ledger(tmp_path))
        assert exc.value.state == R.EXTERNAL_ACTIVITY_UNRESOLVED
        assert s.place_calls == 0

    def test_4_a_swept_objective_is_named_precisely(self, tmp_path):
        s = BlockedSession()
        r = approve(runner(s), snapshot())
        with pytest.raises(R.RunnerHalt) as exc:
            drive(r, snapshot(), market(high_since=29915.0, current_price=29912.0),
                  s, led=ledger(tmp_path))
        assert exc.value.state == R.OBJECTIVE_SWEPT
        assert s.place_calls == 0

    def test_5_a_materially_delivered_objective_is_rejected(self, tmp_path):
        s = BlockedSession()
        r = approve(runner(s), snapshot())
        with pytest.raises(R.RunnerHalt) as exc:
            drive(r, snapshot(), market(current_price=29905.0, high_since=29905.0),
                  s, led=ledger(tmp_path))
        assert exc.value.state == R.OBJECTIVE_MATERIALLY_DELIVERED
        assert s.place_calls == 0

    def test_6_a_touched_invalidation_kills_the_candidate(self, tmp_path):
        s = BlockedSession()
        r = approve(runner(s), snapshot())
        with pytest.raises(R.RunnerHalt) as exc:
            drive(r, snapshot(), market(low_since=29870.0), s, led=ledger(tmp_path))
        assert exc.value.state == R.INVALIDATION_TOUCHED
        assert s.place_calls == 0 and r.geometry is None

    def test_7_reward_collapse_rejects_without_moving_anything(self, tmp_path):
        """Price drift that ruins R must not be fixed by moving stop or target."""
        s = BlockedSession()
        cs = snapshot()
        r = approve(runner(s), cs)
        before_stop, before_target = r.geometry.stop_price, r.geometry.target_price
        with pytest.raises(R.RunnerHalt) as exc:
            drive(r, cs, market(), s, latest_price=29906.0, led=ledger(tmp_path))
        assert exc.value.state in (R.RISK_REJECTED, R.REWARD_COLLAPSED, R.RISK_DRIFTED)
        assert s.place_calls == 0
        assert (before_stop, before_target) == (29875.0, 29910.25)   # untouched

    def test_8_risk_above_twenty_rejects_without_tightening_the_stop(self, tmp_path):
        s = BlockedSession()
        cs = snapshot(invalidation_price=29855.0)      # 25 pts = $50 > $20 cap
        r = runner(s)
        with pytest.raises(R.RunnerHalt) as exc:
            approve(r, cs)
        assert exc.value.state == R.RISK_REJECTED
        assert s.place_calls == 0

    def test_9_a_superseded_snapshot_is_refused(self, tmp_path):
        s = BlockedSession()
        r = approve(runner(s), snapshot())
        with pytest.raises(R.RunnerHalt) as exc:
            drive(r, snapshot(), market(snapshot_id="snap-2"), s, led=ledger(tmp_path))
        assert exc.value.state == R.SNAPSHOT_SUPERSEDED
        assert s.place_calls == 0

    def test_10_same_target_price_different_objective_breaks_the_token(self, tmp_path):
        """Identity is part of the thesis even when the number matches."""
        s = BlockedSession()
        cs = snapshot()
        r = approve(runner(s), cs)
        other = snapshot(objective=objective(29910.25, "session_high"))
        mint = minter(other)          # token bound to a DIFFERENT objective identity
        with pytest.raises(R.RunnerHalt) as exc:
            r.gated_submit(account_id=1, ledger=ledger(tmp_path), candidate_snapshot=cs,
                           market=market(), latest_price=29885.0, mint_token=mint)
        assert exc.value.state == R.TOKEN_BINDING_MISMATCH
        assert s.place_calls == 0

    def test_11_a_contract_change_invalidates_everything(self, tmp_path):
        s = BlockedSession()
        r = approve(runner(s), snapshot())
        with pytest.raises(R.RunnerHalt) as exc:
            drive(r, snapshot(), market(contract_id="CON.F.US.MNQ.Z26"), s,
                  led=ledger(tmp_path))
        assert exc.value.state == R.CONTRACT_MISMATCH
        assert s.place_calls == 0 and r.geometry is None

    def test_12_a_stale_market_stream_blocks_submission(self, tmp_path):
        s = BlockedSession()
        r = approve(runner(s), snapshot())
        with pytest.raises(R.RunnerHalt) as exc:
            drive(r, snapshot(), market(data_age_seconds=600.0), s, led=ledger(tmp_path))
        assert exc.value.state == R.STREAM_STALE
        assert s.place_calls == 0


class TestAtomicRecheck:

    def test_activity_appearing_in_the_final_recheck_aborts(self, tmp_path):
        """Nothing may slip in between the last validation and the request."""
        s = BlockedSession()
        cs = snapshot()
        r = approve(runner(s), cs)
        refresh = lambda: {"market": market(), "latest_price": 29885.0,
                           "orders": [{"id": 9, "contractId": CID, "customTag": None}],
                           "positions": []}
        with pytest.raises(R.RunnerHalt) as exc:
            r.gated_submit(account_id=1, ledger=ledger(tmp_path), candidate_snapshot=cs,
                           market=market(), latest_price=29885.0,
                           mint_token=minter(cs), refresh=refresh)
        assert exc.value.state in (R.ACCOUNT_STATE_CHANGED, R.EXTERNAL_ACTIVITY_UNRESOLVED)
        assert s.place_calls == 0

    def test_the_token_is_minted_only_after_every_gate_passes(self, tmp_path):
        minted = {"n": 0}

        def counting_mint():
            minted["n"] += 1
            return minter(snapshot())()

        s = BlockedSession()
        r = approve(runner(s), snapshot())
        with pytest.raises(R.RunnerHalt):
            r.gated_submit(account_id=1, ledger=ledger(tmp_path),
                           candidate_snapshot=snapshot(),
                           market=market(low_since=29870.0), latest_price=29885.0,
                           mint_token=counting_mint)
        assert minted["n"] == 0, "no token may be minted for a candidate that fails a gate"

    def test_the_bot_tag_carries_the_token_id(self, tmp_path):
        s = BlockedSession()
        cs = snapshot()
        r = approve(runner(s), cs)
        with pytest.raises(R.RunnerHalt):
            drive(r, cs, market(), s, led=ledger(tmp_path))
        submitting = [t for t in r.transitions if t.state == R.SUBMITTING][-1]
        assert submitting.evidence["token_burn"]["token_id"] == r.token.token_id


class TestRegressions:

    def test_the_one_entry_latch_survives(self, tmp_path):
        s = BlockedSession()
        r = approve(runner(s), snapshot())
        with pytest.raises(R.RunnerHalt):
            drive(r, snapshot(), market(), s, led=ledger(tmp_path))
        assert s.place_calls == 1
        with pytest.raises(R.RunnerHalt) as exc:
            drive(r, snapshot(), market(), s, led=ledger(tmp_path))
        assert exc.value.state == R.RESIDUAL_ORDERS
        assert s.place_calls == 1, "the latch must prevent a second venue call"

    def test_manual_activity_never_increments_the_bot_trade_count(self, tmp_path):
        led = ledger(tmp_path)
        led.reconcile_trades([{"contractId": CID, "size": 5, "profitAndLoss": 40.0,
                               "fees": 1.8, "customTag": None}])
        assert led.bot_filled_trade_count() == 0

    def test_unknown_activity_is_never_silently_bot(self, tmp_path):
        led = ledger(tmp_path)
        led.record("order", {"customTag": "EXPBOT-neverissued", "contractId": CID})
        assert led.unknown_count() == 1
        assert led.requires_pause() is not None

    def test_no_repair_helper_exists_on_the_runner(self):
        for banned in ("adjust_stop", "tighten_stop", "widen_stop", "move_target",
                       "extend_target", "replace_objective",
                       "recalculate_target_to_fit_R", "recalculate_stop_to_fit_risk"):
            assert not hasattr(R.ExecutionRunner, banned)

    def test_no_second_order_path_was_introduced(self):
        """gated_submit must be the only route that can call place_order."""
        import inspect
        src = inspect.getsource(R)
        assert src.count("self.session.place_order(") == 1

    def test_the_caps_are_unchanged(self):
        from broker.topstepx_combine_risk import (
            MAX_RISK_PER_TRADE_USD, SMOKE_MAX_CONTRACTS, SMOKE_MAX_RISK_USD,
        )
        assert (SMOKE_MAX_RISK_USD, SMOKE_MAX_CONTRACTS, MAX_RISK_PER_TRADE_USD) == (
            20.00, 1, 250.00)

    def test_every_new_gate_state_is_a_registered_failure(self):
        for st in (R.EXTERNAL_ACTIVITY_UNRESOLVED, R.OBJECTIVE_SWEPT,
                   R.OBJECTIVE_MATERIALLY_DELIVERED, R.INVALIDATION_TOUCHED,
                   R.SNAPSHOT_SUPERSEDED, R.ACCOUNT_STATE_CHANGED, R.RISK_DRIFTED,
                   R.REWARD_COLLAPSED, R.TOKEN_BINDING_MISMATCH,
                   R.MANUAL_ACTIVITY_DETECTED):
            assert st in R.FAILURE_STATES

    def test_refusals_are_not_collapsed_into_one_generic_reason(self, tmp_path):
        seen = set()
        for over in ({"manual_activity": True}, {"high_since": 29915.0,
                     "current_price": 29912.0}, {"low_since": 29870.0},
                     {"snapshot_id": "snap-2"}, {"data_age_seconds": 600.0}):
            s = BlockedSession()
            r = approve(runner(s), snapshot())
            with pytest.raises(R.RunnerHalt) as exc:
                drive(r, snapshot(), market(**over), s, led=ledger(tmp_path))
            seen.add(exc.value.state)
        assert len(seen) == 5, f"gates must be distinguishable, got {seen}"


class TestDurableAttemptOrdering:
    """The consumption hook must fire AFTER every gate and BEFORE the transport."""

    def test_the_hook_fires_before_the_venue_is_touched(self, tmp_path):
        order = []

        class Recording(BlockedSession):
            def place_order(self, payload):
                order.append("transport")
                return super().place_order(payload)

        s = Recording()
        cs = snapshot()
        r = approve(runner(s), cs)
        with pytest.raises(R.RunnerHalt):
            r.gated_submit(account_id=1, ledger=ledger(tmp_path), candidate_snapshot=cs,
                           market=market(), latest_price=29885.0, mint_token=minter(cs),
                           on_attempt_consumed=lambda tid: order.append("persisted"))
        assert order[:2] == ["persisted", "transport"]

    def test_a_refused_candidate_never_fires_the_hook(self, tmp_path):
        """No gate refusal may consume the durable attempt."""
        fired = []
        s = BlockedSession()
        r = approve(runner(s), snapshot())
        with pytest.raises(R.RunnerHalt):
            r.gated_submit(account_id=1, ledger=ledger(tmp_path),
                           candidate_snapshot=snapshot(),
                           market=market(low_since=29870.0), latest_price=29885.0,
                           mint_token=minter(snapshot()),
                           on_attempt_consumed=lambda tid: fired.append(tid))
        assert fired == [] and s.place_calls == 0

    def test_a_hook_failure_prevents_submission(self, tmp_path):
        """If the attempt cannot be persisted, nothing may be sent."""
        s = BlockedSession()
        cs = snapshot()
        r = approve(runner(s), cs)

        def failing(tid):
            raise RuntimeError("could not verify ATTEMPT_CONSUMED on disk")

        with pytest.raises(RuntimeError):
            r.gated_submit(account_id=1, ledger=ledger(tmp_path), candidate_snapshot=cs,
                           market=market(), latest_price=29885.0, mint_token=minter(cs),
                           on_attempt_consumed=failing)
        assert s.place_calls == 0
