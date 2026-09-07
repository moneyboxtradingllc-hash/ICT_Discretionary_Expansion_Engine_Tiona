"""PROD-20260904: a positive venue refusal the mission was never told about.

THE LIVE SHAPE, corrected against the flight recorder. PROD-20260904-T1
consumed its attempt, the request reached Topstep, and Topstep refused it:

    orderId       3491481775
    errorCode     2
    errorMessage  "Brackets cannot be used with Position Brackets.
                   You must enable Auto OCO Brackets."

The mission stranded in ATTEMPT_CONSUMED with order_id=null and
token_spent=false -- a phantom active mission that refused every later scan,
which is PROD-20260810 with the recording hole moved one step later.

WHAT THIS FILE ORIGINALLY SAID, AND WHY IT WAS WRONG. The first version of
this docstring, and the message of commit d6a3813, said Topstep refused
"without minting an order id" and that the canonical law "required an id it
could not have". The ledger says otherwise: the venue DID return
3491481775, in the body of the very exception the runner caught.

So of the two holes, only the second one actually caused this incident:

  1. `venue_rejected_zero_fill` REQUIRED `venue_order_id`. Real, and worth
     removing -- a venue CAN refuse before minting an id -- but NOT the
     blocker here, because the id was available all along.
  2. It had NO PRODUCTION CALLER. Every call site in the whole tree was a
     test. The runner reconciled, found flat-and-empty, and halted -- and the
     durable mission was never told. THIS is what stranded T1.

The distinction matters for anyone reading back: the fix that mattered was
the wiring, not the relaxation.

WHAT REPLACES IT, and the line these tests are really about:

    ATTRIBUTION IS DECIDED AT THE EXCEPTION, NEVER AT THE RECONCILIATION.

Flat-and-empty is not evidence of a refusal. It is equally consistent with a
request still in flight, and with one that was never sent at all. So a bare
exception, a timeout, an unreachable host, a server error and a pre-transport
auth failure all reconcile to exactly what they did before -- unknown-
submission law -- while a positive `TopstepXError` refusal, and only that,
may close the mission.

NO NETWORK. Every venue interaction here is a stub.

FIXTURE, NOT EVIDENCE. `NO_ID_REJECTION` below is a CONSTRUCTED body that
exercises the no-order-id shape. It is not the PROD-20260904 response, and
must never be read back as one -- the real body is quoted above and lives in
data/integration/topstepx/submissions_PROD-20260904.jsonl.
"""
from __future__ import annotations

import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))
sys.path.insert(0, os.path.join(ROOT, "tests"))

from broker import topstepx_execution_runner as R          # noqa: E402
from broker import topstepx_mission_state as MS            # noqa: E402
from broker.topstepx_client import TopstepXError           # noqa: E402
from broker.topstepx_session_authorization import (        # noqa: E402
    AuthorizationRefused, ProductionSessionMission, SessionAuthorization)

# The SAME orchestration harness the production lifecycle tests use. Importing
# it rather than rebuilding it is the point: hole 2 lived underneath a passing
# suite precisely because the tests owned a path production did not take.
from test_production_scan_loop import (                    # noqa: E402
    CID, FP, MNQ, NOW, Session, build)

SESSION = "PROD-TEST-ATTRIB"
OPEN_ARGS = dict(positions=0, working_orders=0, unknown_external=False,
                 in_window=True)

#: A CONSTRUCTED no-order-id refusal. NOT the PROD-20260904 body -- that one
#: carried orderId 3491481775. See the module docstring.
NO_ID_REJECTION = {"success": False, "errorCode": 2,
                   "errorMessage": "Invalid order: account violation",
                   "fillVolume": 0}


# ══════════════════════════════════════════════════════════════════════════════
# the canonical law
# ══════════════════════════════════════════════════════════════════════════════
def mission_at(tmp_path, name="M1"):
    """One mission that has consumed its attempt, and nothing more."""
    auth = SessionAuthorization(
        session_id=SESSION, account_fingerprint=FP, contract_id=CID,
        session_date="2026-09-04", decision_window="09:30-14:00 America/New_York",
        daily_loss_budget_usd=725.00)
    auth.authorization_fingerprint = "auth:test"
    sm = ProductionSessionMission(authorization=auth, store_dir=str(tmp_path))
    sm.load_existing()
    m = sm.open_trade_mission(**OPEN_ARGS)
    m.consume_attempt(candidate_fingerprint="cand:x", token_id="tok:x")
    return sm, m


class TestRulingAOrderIdIsOptionalOnlyUnderAttribution:
    """1. attributed + flat + no order + zero fill + NO venue order id."""

    def test_1_an_attributed_rejection_with_no_order_id_terminalizes(self, tmp_path):
        sm, m = mission_at(tmp_path)
        assert m.order_id is None
        out = m.venue_rejected_zero_fill(
            venue_order_id=None, error_code=2,
            error_message="Invalid order: account violation",
            positions=0, working_orders=0, venue_attributed=True)
        assert out["state"] == MS.VENUE_REJECTED_ZERO_FILL
        assert m.state == MS.VENUE_REJECTED_ZERO_FILL

    def test_1b_no_order_id_is_invented(self, tmp_path):
        """The mission says it has no id, rather than carrying a fabricated one."""
        sm, m = mission_at(tmp_path)
        m.venue_rejected_zero_fill(venue_order_id=None, error_code=2,
                                   error_message="x", positions=0,
                                   working_orders=0, venue_attributed=True)
        assert m.order_id is None
        assert MS.load(m.path).order_id is None

    def test_1c_the_conservative_default_is_preserved(self, tmp_path):
        """No id AND no attribution -> REFUSED. The ambiguous caller's answer."""
        sm, m = mission_at(tmp_path)
        with pytest.raises(MS.MissionStateError, match="positively attributed"):
            m.venue_rejected_zero_fill(venue_order_id=None, error_code=2,
                                       error_message="x", positions=0,
                                       working_orders=0)
        assert m.state == MS.ATTEMPT_CONSUMED, "an unattributed read may not close it"

    def test_1d_attribution_does_not_excuse_any_other_fact(self, tmp_path):
        """Attribution replaces the ORDER ID requirement and nothing else."""
        sm, m = mission_at(tmp_path)
        for kw in ({"positions": None, "working_orders": None},
                   {"positions": 1, "working_orders": 0},
                   {"positions": 0, "working_orders": 1}):
            with pytest.raises(MS.MissionStateError):
                m.venue_rejected_zero_fill(venue_order_id=None, venue_attributed=True,
                                           error_code=2, error_message="x", **kw)
        assert m.state == MS.ATTEMPT_CONSUMED

    def test_the_attribution_itself_is_durable(self, tmp_path):
        """A later reader must see WHY closing without an id was legal."""
        sm, m = mission_at(tmp_path)
        m.venue_rejected_zero_fill(venue_order_id=None, error_code=2,
                                   error_message="Invalid order: account violation",
                                   positions=0, working_orders=0,
                                   venue_attributed=True)
        reread = MS.load(m.path)
        assert reread.venue_attributed is True
        assert reread.venue_error_code == 2
        assert reread.venue_error_message == "Invalid order: account violation"

    def test_a_legacy_record_reads_back_unattributed(self, tmp_path):
        """Records written before RULING A must not gain an attribution."""
        sm, m = mission_at(tmp_path)
        m.venue_rejected_zero_fill(venue_order_id=3385801549, positions=0,
                                   working_orders=0)
        import json
        data = json.load(open(m.path, encoding="utf-8"))
        data.pop("venue_attributed")
        json.dump(data, open(m.path, "w", encoding="utf-8"))
        assert MS.load(m.path).venue_attributed is False


class TestRulingDTokenSpent:
    """2. token_spent = true. A positive venue refusal is a venue boundary."""

    def test_2_token_spent_is_true_on_an_attributed_rejection(self, tmp_path):
        sm, m = mission_at(tmp_path)
        assert m.token_spent is False
        m.venue_rejected_zero_fill(venue_order_id=None, error_code=2,
                                   error_message="x", positions=0,
                                   working_orders=0, venue_attributed=True)
        assert m.token_spent is True

    def test_2b_it_is_durable_not_only_in_memory(self, tmp_path):
        sm, m = mission_at(tmp_path)
        m.venue_rejected_zero_fill(venue_order_id=None, positions=0,
                                   working_orders=0, venue_attributed=True)
        assert MS.load(m.path).token_spent is True

    def test_2c_an_order_id_bearing_rejection_also_spends_it(self, tmp_path):
        """An order id can only have come from the venue: same boundary."""
        sm, m = mission_at(tmp_path)
        m.venue_rejected_zero_fill(venue_order_id=3385801549, error_code=2,
                                   error_message="x", positions=0,
                                   working_orders=0)
        assert MS.load(m.path).token_spent is True

    def test_2d_a_refused_write_spends_nothing(self, tmp_path):
        """Pre-transport / ambiguous never reaches the boundary at all."""
        sm, m = mission_at(tmp_path)
        with pytest.raises(MS.MissionStateError):
            m.venue_rejected_zero_fill(venue_order_id=None, positions=0,
                                       working_orders=0)
        assert MS.load(m.path).token_spent is False


class TestRulingETerminalButNotAFreeRetry:
    """3-6. Terminal, durable, un-phantomed -- and still not a second chance."""

    def closed(self, tmp_path):
        sm, m = mission_at(tmp_path)
        m.venue_rejected_zero_fill(venue_order_id=None, error_code=2,
                                   error_message="Invalid order: account violation",
                                   positions=0, working_orders=0,
                                   venue_attributed=True)
        return sm, m

    def test_3_the_state_is_terminal(self, tmp_path):
        _, m = self.closed(tmp_path)
        assert m.state in MS.TERMINAL_STATES
        assert m.must_reconcile() is False
        assert m.may_attempt_entry()[0] is False

    def test_4_a_durable_reload_remains_terminal(self, tmp_path):
        sm, m = self.closed(tmp_path)
        del sm, m
        reread = MS.load(os.path.join(str(tmp_path),
                                      f"trade_mission_{SESSION}_1.json"))
        assert reread.state == MS.VENUE_REJECTED_ZERO_FILL
        assert reread.state in MS.TERMINAL_STATES
        assert reread.venue_attributed is True
        assert reread.token_spent is True

    def test_5_active_mission_no_longer_sees_it(self, tmp_path):
        """The phantom is gone: THIS is what 'unblocked' may mean, and all."""
        sm, m = mission_at(tmp_path)
        assert sm.active_mission is m
        m.venue_rejected_zero_fill(venue_order_id=None, error_code=2,
                                   error_message="x", positions=0,
                                   working_orders=0, venue_attributed=True)
        sm.load_existing()
        assert sm.active_mission is None
        assert not any(x.must_reconcile() for x in sm.trade_missions)

    def test_6_the_same_session_gets_no_free_retry(self, tmp_path):
        """The attempt/authorization stays SPENT. A fresh session is required.

        Both halves of RULING E in one place, because they are the pair that
        was previously stated as one misleading sentence: the phantom is gone
        AND nothing about that grants another attempt today.
        """
        sm, m = self.closed(tmp_path)
        sm.load_existing()
        assert sm.active_mission is None, "phantom gone"
        ok, why = sm.may_open_trade_mission(**OPEN_ARGS)
        assert ok is False, "a terminal rejection is not a free retry"
        assert "HALTED" in why and "operator review" in why
        with pytest.raises(AuthorizationRefused):
            sm.open_trade_mission(**OPEN_ARGS)
        assert sm.counters()["session_halted_for_review"] is True

    def test_6b_the_evidence_survives_the_retry_refusal(self, tmp_path):
        """The rejected mission is kept, not deleted, and still readable."""
        sm, _ = self.closed(tmp_path)
        sm.load_existing()
        assert len(sm.trade_missions) == 1
        assert sm.venue_rejections() == 1
        assert sm.counters()["entry_attempts"] == 1
        assert sm.counters()["filled_trades"] == 0

    def test_6c_a_fresh_session_is_what_unblocks_it(self, tmp_path):
        """The other side of the same law: a NEW authorization may trade."""
        self.closed(tmp_path)
        fresh_auth = SessionAuthorization(
            session_id="PROD-TEST-ATTRIB-2", account_fingerprint=FP,
            contract_id=CID, session_date="2026-09-04",
            decision_window="09:30-14:00 America/New_York",
            daily_loss_budget_usd=725.00)
        fresh_auth.authorization_fingerprint = "auth:test-2"
        fresh = ProductionSessionMission(authorization=fresh_auth,
                                         store_dir=str(tmp_path))
        fresh.load_existing()
        assert fresh.may_open_trade_mission(**OPEN_ARGS)[0] is True


# ══════════════════════════════════════════════════════════════════════════════
# the attribution source: which exception means what
# ══════════════════════════════════════════════════════════════════════════════
class TestRulingBAttributionSource:

    def test_topstepx_error_is_attributed(self):
        assert R.ExecutionRunner._venue_attributed(
            TopstepXError("order rejected", venue_body=NO_ID_REJECTION)) is True
        assert R.ExecutionRunner._venue_attributed(
            TopstepXError("/api/Order/place failed: errorCode=2")) is True

    def test_a_bare_exception_is_never_attributed(self):
        for exc in (TimeoutError("read timed out"), ConnectionResetError("reset"),
                    RuntimeError("boom"), ValueError("x")):
            assert R.ExecutionRunner._venue_attributed(exc) is False

    def test_an_unreachable_venue_is_not_a_refusal(self):
        """It wears TopstepXError and proves the OPPOSITE of its own contract.

        `_default_transport` converts a `URLError` -- a socket that never
        completed -- into a plain `TopstepXError`. The request may still be in
        flight, so reading that as "Topstep refused it" would terminalize a
        mission whose order can still land. The raise site says so itself.
        """
        assert R.ExecutionRunner._venue_attributed(
            TopstepXError("cannot reach https://api.topstepx.com: timed out",
                          venue_refused=False)) is False

    def test_a_server_error_is_not_a_refusal(self):
        """HTTP 5xx: the venue received it and did not say what it did."""
        assert R.ExecutionRunner._venue_attributed(
            TopstepXError("HTTP 503 from https://api.topstepx.com: ...",
                          venue_refused=False)) is False

    def test_the_transport_marks_those_two_shapes_itself(self):
        """Not a string sniff downstream: the RAISE SITE carries the fact."""
        import io
        import urllib.error
        from broker import topstepx_client as C

        def transport_raising(exc):
            def urlopen(*a, **k):
                raise exc
            orig = C.urllib.request.urlopen
            C.urllib.request.urlopen = urlopen
            try:
                with pytest.raises(TopstepXError) as caught:
                    C._default_transport("https://x/api/Order/place", {}, {}, 1.0)
            finally:
                C.urllib.request.urlopen = orig
            return caught.value

        http = lambda code: urllib.error.HTTPError(          # noqa: E731
            "u", code, "err", {}, io.BytesIO(b"body"))

        assert transport_raising(http(503)).venue_refused is False, \
            "a server error is not a refusal"
        assert transport_raising(http(400)).venue_refused is not False, \
            "4xx IS the venue refusing"
        assert transport_raising(
            urllib.error.URLError("connection refused")).venue_refused is False, \
            "an unreachable venue never answered"

    def test_an_auth_failure_before_transmit_is_not_attributed(self):
        """PRE-TRANSPORT. The venue never saw the order, so it never refused it.

        `_authenticate` runs lazily from `_session_token` INSIDE `_post`, so a
        rejected login raises while the request is still being BUILT. Because
        `TopstepXAuthError` inherits `TopstepXError`, it would otherwise
        satisfy RULING B's default and let a flat-and-empty venue close the
        mission as a zero-fill rejection -- terminal, token spent -- on an
        order that was never transmitted.
        """
        from broker.topstepx_client import TopstepXAuthError, TopstepXPinError
        for exc in (TopstepXAuthError("TopstepX login rejected (errorCode=9)"),
                    TopstepXAuthError("needs both a username and an API key"),
                    TopstepXPinError("account pinning refused")):
            assert exc.venue_refused is False, f"{type(exc).__name__} must be pre-transport"
            assert R.ExecutionRunner._venue_attributed(exc) is False, \
                f"{type(exc).__name__} attributed a refusal to a venue never asked"

    def test_an_http_401_at_the_venue_is_a_different_case(self):
        """Named deliberately, because it sits on the other side of the line.

        A 401 from the ORDER endpoint means the request DID reach Topstep and
        Topstep refused it, so it stays attributed like any other 4xx. What is
        excluded above is the login failing before the order is ever sent.
        """
        assert R.ExecutionRunner._venue_attributed(
            TopstepXError("HTTP 401 from https://api.topstepx.com: ...",
                          venue_refused=True)) is True

    def test_a_success_false_body_stays_attributed(self):
        """The ordinary rejection: `_post` raises with the venue's own body."""
        from broker import topstepx_client as C

        client = C.TopstepXClient.__new__(C.TopstepXClient)
        client._session_token = lambda: "t"
        client.base_url = "https://x"
        client._request_with_backoff = lambda *a: dict(NO_ID_REJECTION)
        with pytest.raises(TopstepXError) as exc:
            client._post("/api/Order/place", {})
        assert exc.value.venue_refused is not False
        assert exc.value.venue_body == NO_ID_REJECTION
        assert R.ExecutionRunner._venue_attributed(exc.value) is True


# ══════════════════════════════════════════════════════════════════════════════
# the production wiring: does the hook actually fire?
# ══════════════════════════════════════════════════════════════════════════════
class RefusingVenue(Session):
    """Topstep positively refuses the submission and stays flat and empty.

    `place_order` raises exactly what `TopstepXClient._post` raises when the
    venue answers `success: false` -- body attached, and in PROD-20260904's own
    shape, with NO orderId in it.
    """

    def __init__(self, body=None, exc=None, fills=False, leaves_order=False):
        super().__init__(place=self._refuse)
        self.body = NO_ID_REJECTION if body is None else body
        self.exc = exc
        #: The account is FLAT when the mission opens -- the gate requires it --
        #: so a position or a working order can only appear AT the submission.
        #: That is also the only shape that can really happen.
        self.fills = fills
        self.leaves_order = leaves_order

    def _refuse(self, payload):
        if self.fills:
            self._p = [{"id": 830000001, "contract_id": CID, "side": "long",
                        "size": int(payload.get("size") or 1),
                        "avg_price": 29880.0}]
        if self.leaves_order:
            self._o = [{"id": 901, "contract_id": CID, "status": 1, "type": 4,
                        "side": 1, "size": int(payload.get("size") or 1),
                        "stop_price": 29800.0}]
        if self.exc is not None:
            raise self.exc
        raise TopstepXError(
            f"/api/Order/place failed: errorCode={self.body.get('errorCode')} "
            f"{self.body.get('errorMessage')}", venue_body=self.body)


class DegradedVenue(RefusingVenue):
    """A venue that refuses, and whose COMPLETE order surface then goes away.

    It answers `v2/query` at the gate -- the mission could not open otherwise --
    and stops answering once the submission has been made, which is exactly how
    a surface degrades mid-flight. Discovery falls back to `searchOpen`,
    ANSWERS, and is honestly labelled INCOMPLETE.
    """

    def query_orders(self, *, statuses=None, contract_id=None):
        if self.place_calls:
            raise TopstepXError("v2/query unavailable")
        return super().query_orders(statuses=statuses, contract_id=contract_id)


def armed_rejection(tmp_path, venue=None):
    """One armed scan through the REAL orchestration, into a refusing venue."""
    venue = venue or RefusingVenue()
    loop, ps, sess, mission = build(tmp_path, armed=True, session=venue)
    out = loop.scan_once()
    mission.load_existing()
    return loop, ps, venue, mission, out


class TestRulingCTheProductionHookFires:
    """11. Through the real wiring, not a hand-called transition."""

    def test_11_the_rejection_reaches_the_durable_mission(self, tmp_path):
        _, _, venue, mission, out = armed_rejection(tmp_path)
        assert venue.place_calls == 1, "exactly one submit attempt, ever"
        assert mission.trade_missions, "the mission was never created"
        m = mission.trade_missions[0]
        assert m.state == MS.VENUE_REJECTED_ZERO_FILL, (
            f"the rejection never reached the mission (state={m.state}); "
            f"scan said {out}")

    def test_11b_it_is_durable_on_disk(self, tmp_path):
        _, _, _, mission, _ = armed_rejection(tmp_path)
        reread = MS.load(mission.mission_path(1))
        assert reread.state == MS.VENUE_REJECTED_ZERO_FILL
        assert reread.venue_attributed is True
        assert reread.token_spent is True
        assert reread.venue_error_code == 2
        assert "account violation" in reread.venue_error_message

    def test_11c_the_hook_is_assigned_not_merely_declared(self, tmp_path):
        """RULING C: a getattr hook nothing ever assigns is not wiring."""
        _, ps, _, _, _ = armed_rejection(tmp_path)
        assert getattr(ps, "rejection_hook", None) is not None
        assert ps.runner.on_venue_rejected is not None
        assert ps.runner.on_venue_rejected is ps.rejection_hook

    def test_11d_a_rebuilt_runner_still_carries_it(self, tmp_path):
        """Both surfaces, exactly like the acknowledgement seam."""
        _, ps, _, _, _ = armed_rejection(tmp_path)
        hook = ps.rejection_hook
        ps.runner = None
        # `build_runner` needs a candidate; the seam assignment is what matters,
        # so assert the source of truth the rebuild reads.
        assert getattr(ps, "rejection_hook", None) is hook

    def test_11e_the_exact_PROD_20260904_shape_is_now_unreachable(self, tmp_path):
        """ATTEMPT_CONSUMED + phantom active mission, after a positive refusal."""
        _, _, _, mission, _ = armed_rejection(tmp_path)
        m = mission.trade_missions[0]
        assert m.state != MS.ATTEMPT_CONSUMED
        assert mission.active_mission is None, "phantom active mission"

    def test_11f_the_session_halts_rather_than_resubmitting(self, tmp_path):
        _, _, venue, mission, _ = armed_rejection(tmp_path)
        ok, why = mission.may_open_trade_mission(**OPEN_ARGS)
        assert ok is False and "HALTED" in why
        assert venue.place_calls == 1


class TestRulingBThroughTheProductionPath:
    """7. Ambiguous transport stays ambiguous, all the way through the loop."""

    def test_7_a_bare_exception_flat_and_empty_is_not_a_rejection(self, tmp_path):
        venue = RefusingVenue(exc=TimeoutError("read timed out"))
        _, _, _, mission, out = armed_rejection(tmp_path, venue=venue)
        m = mission.trade_missions[0]
        assert m.state != MS.VENUE_REJECTED_ZERO_FILL, (
            "a timeout became a venue rejection because reconciliation saw "
            "position=0 and orders=0 -- the exact inversion RULING B forbids")
        assert m.state == MS.ATTEMPT_CONSUMED
        assert m.token_spent is False
        assert m.venue_attributed is False

    def test_7b_an_unreachable_venue_is_not_a_rejection(self, tmp_path):
        venue = RefusingVenue(exc=TopstepXError(
            "cannot reach https://api.topstepx.com/api/Order/place: timed out",
            venue_refused=False))
        _, _, _, mission, _ = armed_rejection(tmp_path, venue=venue)
        assert mission.trade_missions[0].state != MS.VENUE_REJECTED_ZERO_FILL

    def test_7c_a_server_error_is_not_a_rejection(self, tmp_path):
        venue = RefusingVenue(exc=TopstepXError("HTTP 503 from ...",
                                                venue_refused=False))
        _, _, _, mission, _ = armed_rejection(tmp_path, venue=venue)
        assert mission.trade_missions[0].state != MS.VENUE_REJECTED_ZERO_FILL

    def test_7e_an_auth_failure_does_not_terminalize_the_mission(self, tmp_path):
        """The same law, proven through the REAL loop rather than the helper.

        Before the pre-transport marking, this test closed the mission as
        VENUE_REJECTED_ZERO_FILL with token_spent=True on an order that never
        left the process.
        """
        from broker.topstepx_client import TopstepXAuthError
        venue = RefusingVenue(exc=TopstepXAuthError(
            "TopstepX login rejected (errorCode=9) ApiSubscriptionNotFound"))
        _, _, _, mission, _ = armed_rejection(tmp_path, venue=venue)
        m = mission.trade_missions[0]
        assert m.state != MS.VENUE_REJECTED_ZERO_FILL, (
            "an authentication failure BEFORE transmit was promoted to a "
            "positive venue refusal")
        assert m.state == MS.ATTEMPT_CONSUMED
        assert m.token_spent is False
        assert m.venue_attributed is False
        assert m.must_reconcile() is True

    def test_7d_the_unattributed_mission_still_awaits_reconciliation(self, tmp_path):
        """Not terminal, and honestly so: nobody knows what the venue did."""
        venue = RefusingVenue(exc=TimeoutError("read timed out"))
        _, _, _, mission, _ = armed_rejection(tmp_path, venue=venue)
        m = mission.trade_missions[0]
        assert m.must_reconcile() is True
        assert mission.active_mission is m


class TestTheProducerRefusesEveryIncompleteProof:
    """8-10. Every fact must be positively proven, through the real path."""

    def test_8_a_fill_is_not_a_zero_fill_rejection(self, tmp_path):
        """The venue answered "refused" and a POSITION EXISTS.

        The account is flat when the mission opens -- it has to be -- and the
        position appears at the submission, which is the only shape that can
        actually happen. Whatever the venue said, something landed, so this is
        not a zero fill and must not be closed as one.
        """
        venue = RefusingVenue(fills=True)
        _, _, _, mission, _ = armed_rejection(tmp_path, venue=venue)
        assert mission.trade_missions[0].state != MS.VENUE_REJECTED_ZERO_FILL

    def test_9_a_non_flat_position_blocks_it_at_the_law(self, tmp_path):
        sm, m = mission_at(tmp_path)
        with pytest.raises(MS.MissionStateError, match="not flat"):
            m.venue_rejected_zero_fill(venue_order_id=None, venue_attributed=True,
                                       positions=1, working_orders=0)

    def test_10_a_working_order_blocks_it_through_the_real_path(self, tmp_path):
        """The venue refused the entry -- and something executable is working."""
        venue = RefusingVenue(leaves_order=True)
        _, _, _, mission, _ = armed_rejection(tmp_path, venue=venue)
        assert mission.trade_missions[0].state != MS.VENUE_REJECTED_ZERO_FILL

    def test_10b_an_incomplete_order_view_may_not_terminalize(self, tmp_path):
        """`searchOpen` omits Suspended children BY CONTRACT.

        A venue without the complete `v2/query` surface can be SILENT about
        protection that exists, and absence proven from a surface documented to
        omit rows is not absence. So the answer is not "no orders" but "we
        cannot prove there are none", and the mission stays open.
        """
        _, _, _, mission, _ = armed_rejection(tmp_path, venue=DegradedVenue())
        assert mission.trade_missions[0].state != MS.VENUE_REJECTED_ZERO_FILL
        assert mission.trade_missions[0].state == MS.ATTEMPT_CONSUMED


class TestAnEarlierUnknownPoisonsALaterRejection:
    """The second path PROD-20260904 review asked about.

    A submission whose outcome was never established, followed by a refusal on
    a later attempt, cannot yield a clean zero-fill rejection: the FIRST order
    may exist. The final exception plus an empty position/order view is not
    enough, because "empty right now" says nothing about an order that has not
    surfaced yet.

    It is refused at three independent layers, which is why the live path can
    afford not to re-litigate history on every reconcile.
    """

    def ledger_with_unknown_then_rejection(self, tmp_path):
        from broker import topstepx_submission_record as SUB
        sm, m = mission_at(tmp_path)
        for raw, exc in ((None, "TimeoutError: read timed out"),
                         ({"orderId": 1, "success": False, "errorCode": 2,
                           "errorMessage": "refused"}, "TopstepXError")):
            rec = SUB.open_submission(store_dir=str(tmp_path), session_id=SESSION,
                                      mission_id=m.mission_id, payload={"size": 1},
                                      custom_tag="t", token_id="tok:x")
            SUB.record_response(store_dir=str(tmp_path), session_id=SESSION,
                                submission=rec, raw_response=raw,
                                transport_exception=exc)
        return sm, m

    def test_the_ledger_refuses_it(self, tmp_path):
        """LAYER 1 -- the evidence the bounded repair reads."""
        from broker import topstepx_submission_record as SUB
        _, m = self.ledger_with_unknown_then_rejection(tmp_path)
        ev = SUB.mission_venue_evidence(str(tmp_path), SESSION, m.mission_id,
                                        token_id="tok:x")
        ok, why = SUB.zero_fill_rejection(ev, positions=0, working_orders=0)
        assert ok is False
        assert any("unknown" in w for w in why), why

    def test_the_repair_tool_refuses_it(self, tmp_path, monkeypatch):
        """LAYER 2 -- the operator command, end to end."""
        helper = TestTheBoundedLocalRepair()
        _, m = helper.repo(tmp_path, transport_only=True)
        code = helper.run(tmp_path, monkeypatch,
                          extra=["--phrase", "CLOSE THIS MISSION AS VENUE "
                                             "REJECTED ZERO FILL"])
        assert code != 0
        assert MS.load(m.path).state == MS.ATTEMPT_CONSUMED

    def test_a_second_attempt_cannot_happen_at_all(self, tmp_path):
        """LAYER 3 -- and the reason the composite stays unreachable live.

        The runner refuses a second submit outright, the mission refuses a
        second consumed attempt, and an unreconciled mission blocks opening
        another one. The live reconciler is never handed a mission with an
        earlier unknown AND a later refusal to weigh.
        """
        sm, m = mission_at(tmp_path)
        assert m.must_reconcile() is True
        with pytest.raises(MS.MissionStateError,
                           match="allowance exhausted|already spent"):
            m.consume_attempt(candidate_fingerprint="c2", token_id="t2")
        ok, why = sm.may_open_trade_mission(**OPEN_ARGS)
        assert ok is False, why


class TestTheAcknowledgementLifecycleIsUnchanged:
    """12. The seam this one mirrors must be exactly where it was."""

    def test_12_an_acknowledged_order_still_reaches_the_mission(self, tmp_path):
        from test_execution_lifecycle_closure import (V13_ORDER_ID, VenueDouble,
                                                      armed_scan)
        _, _, _, mission, out = armed_scan(tmp_path,
                                           venue=VenueDouble(fill_on_place=True))
        assert out["outcome"] == "SUBMITTED", out
        mission.load_existing()
        m = mission.trade_missions[0]
        assert str(m.order_id) == str(V13_ORDER_ID)
        assert m.token_spent is True
        assert m.state != MS.VENUE_REJECTED_ZERO_FILL

    def test_12b_an_acknowledgement_never_sets_the_attribution_flag(self, tmp_path):
        """`venue_attributed` is the REJECTION's fact and only that."""
        from test_execution_lifecycle_closure import VenueDouble, armed_scan
        _, _, _, mission, _ = armed_scan(tmp_path,
                                         venue=VenueDouble(fill_on_place=True))
        mission.load_existing()
        assert mission.trade_missions[0].venue_attributed is False

    def test_12c_both_hooks_are_wired_on_the_same_runner(self, tmp_path):
        _, ps, _, _, _ = armed_rejection(tmp_path)
        assert ps.runner.on_venue_acknowledged is not None
        assert ps.runner.on_venue_rejected is not None
        assert ps.runner.on_venue_acknowledged is not ps.runner.on_venue_rejected


# ══════════════════════════════════════════════════════════════════════════════
# the bounded local repair for the mission already stranded on disk
# ══════════════════════════════════════════════════════════════════════════════
class FakeLiveSession:
    """Stands in for `TopstepXLiveSession`. Reads only; refuses to place."""

    def __init__(self, positions=(), orders=(), complete=True):
        self.account = type("A", (), {"id": 90000042, "name": "TEST"})()
        self._p, self._o = list(positions), list(orders)
        self.complete = complete

    def authenticate(self):
        return {"ok": True}

    def pin(self, *, account_id=None, expected_fingerprint=""):
        return self.account

    def resolve_contract(self, text="MNQ"):
        return MNQ

    def open_positions(self):
        return list(self._p)

    def open_orders(self):
        return list(self._o)

    def query_orders(self, *, statuses=None, contract_id=None):
        if not self.complete:
            raise TopstepXError("v2/query unavailable")
        return list(self._o)


class TestTheBoundedLocalRepair:
    """The stranded mission is finished by the SAME law, never by hand.

    PROD-20260904-T1 is already on disk in ATTEMPT_CONSUMED and the source fix
    cannot reach backwards. These prove the operator's one command does what it
    says -- and refuses when any fact is missing.
    """

    def repo(self, tmp_path, *, transport_only=False, fill=False):
        """A mission stranded exactly as PROD-20260904-T1 is."""
        from broker import topstepx_submission_record as SUB
        sm, m = mission_at(tmp_path)
        rec = SUB.open_submission(
            store_dir=str(tmp_path), session_id=SESSION, mission_id=m.mission_id,
            payload={"accountId": 90000042, "contractId": CID, "size": 3,
                     "customTag": "EXPBOT-PROD-abc"},
            custom_tag="EXPBOT-PROD-abc", token_id="tok:x")
        if transport_only:
            SUB.record_response(store_dir=str(tmp_path), session_id=SESSION,
                                submission=rec, raw_response=None,
                                transport_exception="TimeoutError: read timed out")
        else:
            body = dict(NO_ID_REJECTION)
            if fill:
                body["fillVolume"] = 1
            SUB.record_response(store_dir=str(tmp_path), session_id=SESSION,
                                submission=rec, raw_response=body,
                                transport_exception="TopstepXError: rejected")
        return sm, m

    def run(self, tmp_path, monkeypatch, *, venue=None, extra=()):
        import tools.topstepx_repair_rejected_mission as REPAIR
        monkeypatch.setattr(REPAIR, "TopstepXLiveSession",
                            lambda *a, **k: venue or FakeLiveSession())
        monkeypatch.setenv("TOPSTEPX_ACCOUNT_ID", "90000042")
        argv = ["--session", SESSION, "--mission", "1",
                "--store-dir", str(tmp_path), *extra]
        monkeypatch.setattr(sys, "argv", ["repair", *argv])
        return REPAIR.main()

    def test_it_closes_the_stranded_mission_through_the_canonical_law(
            self, tmp_path, monkeypatch):
        sm, m = self.repo(tmp_path)
        code = self.run(tmp_path, monkeypatch,
                        extra=["--phrase", "CLOSE THIS MISSION AS VENUE "
                                           "REJECTED ZERO FILL"])
        assert code == 0
        reread = MS.load(m.path)
        assert reread.state == MS.VENUE_REJECTED_ZERO_FILL
        assert reread.state in MS.TERMINAL_STATES
        assert reread.venue_attributed is True
        assert reread.token_spent is True
        sm.load_existing()
        assert sm.active_mission is None, "the phantom is what this removes"
        assert sm.may_open_trade_mission(**OPEN_ARGS)[0] is False, \
            "and it is still not a retry"

    def test_the_phrase_is_required(self, tmp_path, monkeypatch):
        _, m = self.repo(tmp_path)
        assert self.run(tmp_path, monkeypatch) != 0
        assert MS.load(m.path).state == MS.ATTEMPT_CONSUMED

    def test_a_dry_run_writes_nothing(self, tmp_path, monkeypatch):
        _, m = self.repo(tmp_path)
        code = self.run(tmp_path, monkeypatch,
                        extra=["--dry-run", "--phrase",
                               "CLOSE THIS MISSION AS VENUE REJECTED ZERO FILL"])
        assert code == 0
        assert MS.load(m.path).state == MS.ATTEMPT_CONSUMED

    @pytest.mark.parametrize("venue,kw", [
        (FakeLiveSession(positions=[{"id": 1, "contract_id": CID, "size": 1}]), {}),
        (FakeLiveSession(orders=[{"id": 901, "contract_id": CID, "status": 1,
                                  "type": 4, "size": 1}]), {}),
        (FakeLiveSession(complete=False), {}),
        (None, {"transport_only": True}),
        (None, {"fill": True}),
    ])
    def test_it_refuses_every_incomplete_proof(self, tmp_path, monkeypatch,
                                               venue, kw):
        """A position, a working order, an incomplete view, an unknown
        submission, a fill -- any one of them and nothing is written."""
        _, m = self.repo(tmp_path, **kw)
        code = self.run(tmp_path, monkeypatch, venue=venue,
                        extra=["--phrase", "CLOSE THIS MISSION AS VENUE "
                                           "REJECTED ZERO FILL"])
        assert code != 0
        assert MS.load(m.path).state == MS.ATTEMPT_CONSUMED

    def test_an_already_terminal_mission_is_refused(self, tmp_path, monkeypatch):
        _, m = self.repo(tmp_path)
        m.venue_rejected_zero_fill(venue_order_id=None, positions=0,
                                   working_orders=0, venue_attributed=True)
        assert self.run(tmp_path, monkeypatch,
                        extra=["--phrase", "CLOSE THIS MISSION AS VENUE "
                                           "REJECTED ZERO FILL"]) != 0

    def test_it_can_place_nothing(self):
        """READ-ONLY by construction, asserted on the source itself."""
        import inspect
        import tools.topstepx_repair_rejected_mission as REPAIR
        src = inspect.getsource(REPAIR)
        for forbidden in ("place_order", "cancel_order", "close_position",
                          "modify_order"):
            assert forbidden not in src, f"{forbidden} is reachable"
