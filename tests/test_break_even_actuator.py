"""BREAK-EVEN-2 — the venue actuator. Exactly-once EFFECT, never once-per-request.

NO BROKER. NO PROVIDER. NO NETWORK. Every venue payload is the REAL normalised
`TopstepXClient` shape (`contract_id`, `parent_order_id`, numeric `type`), the
contract MISSION-RECONCILIATION-VENUE-TRUTH-1 had to restore.

The doctrine under test, in one line: an acknowledgement proves a request was
accepted; only a readback proves a stop moved. And unlike re-anchoring, a failed
advance HOLDS — the position is already protected, so flattening it to resolve
our own bookkeeping would be the worse outcome.
"""
from __future__ import annotations

import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))

from broker import break_even as BE                                  # noqa: E402
from broker import break_even_actuator as ACT                        # noqa: E402
from broker.topstepx_client import TopstepXContract                  # noqa: E402

CID = "CON.F.US.MNQ.U26"
MNQ = TopstepXContract(id=CID, name="MNQ", description="", tick_size=0.25,
                       tick_value=0.50, active=True)

# ── SYNTHETIC lineage. These ids are FIXTURE, not history. ──────────────────
#
# The 2026-08-24 GEOMETRY below is real, measured evidence. Its protective
# CHILD ORDER IDS are not: that trade was closed manually before protective
# lineage was ever established, so no 08-24 stop-order id was positively
# observed. Deliberately obvious numbers, so a fixture can never be read back
# as venue evidence. The REAL observed lineage (3446535520 / 22 / 23) belongs to
# the 2026-08-25 T2 specimen and is used only where that specimen is the subject.
ENTRY, STOP_ID, TARGET_ID = 9900001, 9900002, 9900003

# ── 2026-08-24 GEOMETRY — real, measured ────────────────────────────────────
S_FILL, S_STOP, S_TARGET = 29090.25, 29110.25, 28947.75
S_SIZE = 8
S_BE = 29088.50            # certified executable short break-even
S_TRIGGER = 29070.25       # +1R on the ask


def position(size=S_SIZE, avg=S_FILL, side="short"):
    return {"id": 830922009, "contract_id": CID, "side": side, "size": size,
            "avg_price": avg, "opened_at": "2026-08-24T14:49:20.296104+00:00"}


def stop_order(price=S_STOP, oid=STOP_ID, parent=ENTRY, size=S_SIZE):
    return {"id": oid, "contract_id": CID, "status": 1, "type": 4, "side": 0,
            "size": size, "limit_price": None, "stop_price": price,
            "parent_order_id": parent}


def target_order(price=S_TARGET, oid=TARGET_ID, parent=ENTRY, size=S_SIZE):
    return {"id": oid, "contract_id": CID, "status": 1, "type": 1, "side": 0,
            "size": size, "limit_price": price, "stop_price": None,
            "parent_order_id": parent}


class Venue:
    """A venue whose modify actually lands, unless told otherwise."""

    def __init__(self, positions=None, orders=None, *, effect=True,
                 raises=False, response=None):
        self._p = list(positions if positions is not None else [position()])
        self._o = list(orders if orders is not None else
                       [stop_order(), target_order()])
        self.effect, self.raises, self.response = effect, raises, response
        self.modifies = []

    def open_positions(self):
        return [dict(p) for p in self._p]

    def open_orders(self):
        return [dict(o) for o in self._o]

    def query_orders(self, *, statuses=None, contract_id=None):
        """`/api/Order/v2/query` -- the COMPLETE discovery surface.

        Production reads this, not `searchOpen`, because `searchOpen` omits
        Suspended bracket children by venue contract. A fixture without this
        method models the degraded fallback, where absence can never be proven.
        No status filter is applied, matching production.
        """
        rows = [dict(o) for o in self._o]
        if contract_id:
            rows = [o for o in rows
                    if (o.get("contract_id") or o.get("contractId")) == contract_id]
        return rows

    def recent_trades(self, since=None):
        return []

    def modify_order(self, order_id, *, size=None, limit_price=None,
                     stop_price=None, trail_price=None):
        self.modifies.append({"order_id": order_id, "stop_price": stop_price,
                              "limit_price": limit_price})
        if self.effect:
            for o in self._o:
                if o["id"] == order_id:
                    if stop_price is not None:
                        o["stop_price"] = stop_price
                    if limit_price is not None:
                        o["limit_price"] = limit_price
        if self.raises:
            raise TimeoutError("read timed out")
        return self.response if self.response is not None else {"success": True}


class BlindVenue(Venue):
    def open_positions(self):
        raise RuntimeError("venue unreachable")


class BlindAfterModify(Venue):
    """Answers once, then goes dark — the ambiguous-timeout heart."""

    def __init__(self, *a, **k):
        super().__init__(*a, **k)
        self._reads = 0

    def open_positions(self):
        self._reads += 1
        if self._reads > 1:
            raise RuntimeError("venue unreachable")
        return super().open_positions()


def apply_short(venue, proposed=S_BE, **kw):
    return ACT.apply_break_even(session=venue, contract_id=CID,
                                entry_order_id=ENTRY, direction="short",
                                proposed_stop=proposed, **kw)


# ══ 1-3 · TRIGGER AUTHORITY IS THE DECISION LAYER, NOT THIS ONE ═════════════
class TestDecisionLayerBoundary:
    """This unit never decides IF. These prove the seam it consumes."""

    def decide(self, quote):
        return BE.evaluate(direction="short", entry_fill_price=S_FILL,
                           initial_stop_price=S_STOP, active_protective_stop=S_STOP,
                           current_price=quote, armed=True, contract=MNQ,
                           quantity=S_SIZE)

    def test_below_1R_proposes_nothing(self):
        assert self.decide(29075.0)["outcome"] == BE.HOLD

    def test_at_1R_proposes_the_certified_price(self):
        d = self.decide(S_TRIGGER)
        assert d["outcome"] == BE.PROPOSE
        assert d["initial_risk_points"] == 20.0
        assert d["break_even_price"] == S_BE

    def test_beyond_1R_still_proposes_the_same_price(self):
        assert self.decide(29050.0)["break_even_price"] == S_BE

    def test_no_quote_refuses(self):
        assert self.decide(None)["outcome"] == BE.REFUSED


# ══ 6-8 · MONOTONIC HOLD ════════════════════════════════════════════════════
class TestMonotonicHold:

    def test_stop_already_at_break_even_sends_nothing(self):
        v = Venue(orders=[stop_order(S_BE), target_order()])
        out = apply_short(v)
        assert out["outcome"] == ACT.HELD
        assert out["reason"] == ACT.ALREADY_PROTECTED
        assert v.modifies == [], "a second write was sent"

    def test_stop_already_better_than_break_even_sends_nothing(self):
        """An operator moved it further. Never weaken manual protection."""
        v = Venue(orders=[stop_order(29080.0), target_order()])
        out = apply_short(v)
        assert out["outcome"] == ACT.HELD
        assert v.modifies == []

    def test_a_worse_stop_is_advanced(self):
        v = Venue()
        out = apply_short(v)
        assert out["outcome"] == ACT.APPLIED
        assert out["active_protective_stop"] == S_BE
        assert len(v.modifies) == 1

    def test_the_write_never_widens(self):
        """Proposing a WIDER stop must be refused, not sent."""
        v = Venue(orders=[stop_order(29095.0), target_order()])
        out = apply_short(v, proposed=29105.0)
        assert out["outcome"] == ACT.HELD
        assert v.modifies == []


# ══ 4-5 · PRECONDITIONS ═════════════════════════════════════════════════════
class TestPreconditions:

    def test_unknown_venue_never_mutates(self):
        v = BlindVenue()
        out = apply_short(v)
        assert out["outcome"] == ACT.REFUSED
        assert out["reason"] == ACT.VENUE_UNKNOWN
        assert v.modifies == []

    def test_no_position_holds(self):
        v = Venue(positions=[])
        assert apply_short(v)["outcome"] == ACT.HELD
        assert v.modifies == []

    def test_a_size_change_fails_closed(self):
        v = Venue(positions=[position(size=4)])
        out = apply_short(v, expected_size=S_SIZE)
        assert out["outcome"] == ACT.REFUSED
        assert out["reason"] == ACT.SIZE_MISMATCH
        assert v.modifies == []

    def test_a_non_price_is_refused(self):
        v = Venue()
        assert apply_short(v, proposed=None)["outcome"] == ACT.REFUSED
        assert v.modifies == []


# ══ 14 · LINEAGE ════════════════════════════════════════════════════════════
class TestLineage:

    def test_a_foreign_missions_stop_is_never_modified(self):
        v = Venue(orders=[stop_order(parent=999999999), target_order(parent=999999999)])
        out = apply_short(v)
        assert out["outcome"] == ACT.PROTECTION_DEFECT
        assert v.modifies == [], "a foreign stop was modified"

    def test_a_missing_owned_stop_is_a_protection_defect(self):
        v = Venue(orders=[target_order()])
        out = apply_short(v)
        assert out["outcome"] == ACT.PROTECTION_DEFECT
        assert out["reason"] == ACT.NO_STOP
        assert v.modifies == []

    def test_two_candidate_stops_are_ambiguous_not_guessed(self):
        v = Venue(orders=[stop_order(), stop_order(oid=777), target_order()])
        out = apply_short(v)
        assert out["outcome"] == ACT.PROTECTION_DEFECT
        assert out["reason"] == ACT.AMBIGUOUS_LINEAGE
        assert v.modifies == []

    def test_the_correct_stop_id_is_the_one_modified(self):
        v = Venue()
        apply_short(v)
        assert v.modifies[0]["order_id"] == STOP_ID


# ══ 10-12 · THE AMBIGUOUS TIMEOUT ═══════════════════════════════════════════
class TestAmbiguousTimeout:
    """The central failure case: the request is gone and the answer is not back."""

    def test_timeout_after_the_effect_landed_is_APPLIED_not_retried(self):
        v = Venue(effect=True, raises=True)
        out = apply_short(v)
        assert out["outcome"] == ACT.APPLIED
        assert out["retryable"] is False
        assert out["active_protective_stop"] == S_BE
        assert len(v.modifies) == 1, "a duplicate write followed a lost ack"

    def test_timeout_before_the_effect_leaves_protection_intact_and_retryable(self):
        v = Venue(effect=False, raises=True)
        out = apply_short(v)
        assert out["outcome"] == ACT.AMBIGUOUS
        assert out["reason"] == ACT.EFFECT_ABSENT
        assert out["retryable"] is True
        assert out["active_protective_stop"] == S_STOP, "protection was disturbed"

    def test_an_unreadable_venue_after_the_write_is_never_retried(self):
        v = BlindAfterModify(effect=True)
        out = apply_short(v)
        assert out["outcome"] == ACT.AMBIGUOUS
        assert out["reason"] == ACT.EFFECT_UNKNOWN
        assert out["retryable"] is False, "a duplicate write on unknown state"

    def test_a_malformed_response_is_judged_by_readback_not_by_the_body(self):
        v = Venue(effect=True, response={"garbage": True})
        assert apply_short(v)["outcome"] == ACT.APPLIED

    def test_accepted_but_not_yet_visible_is_AMBIGUOUS_not_rejected(self):
        """THE SEMANTIC GATE. `_post` raises when the venue answers
        `success: false`, so a RETURNED body means the venue ACCEPTED. If the
        readback does not show it yet, propagation may still be in flight.
        Calling that a rejection would let the modify land afterwards against a
        record saying it never happened."""
        v = Venue(effect=False)
        out = apply_short(v)
        assert out["outcome"] == ACT.AMBIGUOUS
        assert out["reason"] == ACT.EFFECT_UNPROVEN
        assert out["active_protective_stop"] == S_STOP
        assert out["retryable"] is False, "no blind retry on an unproven effect"

    def test_a_late_landing_modify_is_recognised_on_the_next_tick(self):
        """The exact scenario the mislabel would have corrupted."""
        v = Venue(effect=False)
        assert apply_short(v)["outcome"] == ACT.AMBIGUOUS
        for o in v._o:                      # the write lands a moment later
            if o["id"] == STOP_ID:
                o["stop_price"] = S_BE
        again = apply_short(v)
        assert again["outcome"] == ACT.HELD
        assert again["reason"] == ACT.ALREADY_PROTECTED
        assert len(v.modifies) == 1, "a second write followed a late landing"


# ══ 9 · REJECTION ═══════════════════════════════════════════════════════════
class TestRejectionLeavesProtectionAlone:

    def test_an_explicit_venue_refusal_is_REJECTED_and_final(self):
        """`success: false` reaches us as TopstepXError carrying `venue_body`.
        Definitive: nothing is in flight, so nothing can land later."""
        from broker.topstepx_client import TopstepXError

        class Refusing(Venue):
            def modify_order(self, order_id, **kw):
                self.modifies.append({"order_id": order_id,
                                      "stop_price": kw.get("stop_price"),
                                      "limit_price": kw.get("limit_price")})
                raise TopstepXError("/api/Order/modify failed: errorCode=3",
                                    venue_body={"success": False, "errorCode": 3,
                                                "errorMessage": "order not modifiable"})
        v = Refusing(effect=False)
        out = apply_short(v)
        assert out["outcome"] == ACT.REJECTED
        assert out["reason"] == ACT.EXPLICIT_REJECTION
        assert out["retryable"] is False
        assert out["venue_rejection"]["errorCode"] == 3
        assert out["active_protective_stop"] == S_STOP

    def test_a_transport_failure_is_NOT_an_explicit_rejection(self):
        """Same exception TYPE, no venue verdict: the effect is unknown, and
        the discriminator is the body, never the class."""
        from broker.topstepx_client import TopstepXError

        class Broken(Venue):
            def modify_order(self, order_id, **kw):
                self.modifies.append({"order_id": order_id,
                                      "stop_price": kw.get("stop_price"),
                                      "limit_price": kw.get("limit_price")})
                raise TopstepXError("HTTP 503")
        v = Broken(effect=False)
        out = apply_short(v)
        assert out["outcome"] == ACT.AMBIGUOUS
        assert out["reason"] == ACT.EFFECT_ABSENT
        assert out["retryable"] is True

    def test_rejection_never_cancels_or_widens(self):
        v = Venue(effect=False)
        out = apply_short(v)
        assert out["outcome"] == ACT.AMBIGUOUS
        orders = v.open_orders()
        assert any(o["id"] == STOP_ID and o["stop_price"] == S_STOP for o in orders)
        assert any(o["id"] == TARGET_ID for o in orders), "target was removed"

    def test_no_failure_path_flattens(self):
        """Inverted from re-anchoring: a protected position is never killed to
        resolve a failed advance."""
        for v in (Venue(effect=False), Venue(effect=False, raises=True),
                  BlindVenue(), Venue(positions=[position(size=4)])):
            apply_short(v, expected_size=S_SIZE)
            assert not hasattr(v, "closed"), "something tried to flatten"


# ══ 13 · DUPLICATE INVOCATION ═══════════════════════════════════════════════
class TestExactlyOnceEffect:

    def test_repeated_invocation_produces_exactly_one_write(self):
        v = Venue()
        first = apply_short(v)
        assert first["outcome"] == ACT.APPLIED
        for _ in range(4):
            again = apply_short(v)
            assert again["outcome"] == ACT.HELD
            assert again["reason"] == ACT.ALREADY_PROTECTED
        assert len(v.modifies) == 1

    def test_a_duplicate_management_tick_is_a_hold(self):
        v = Venue(orders=[stop_order(S_BE), target_order()])
        assert apply_short(v)["outcome"] == ACT.HELD
        assert v.modifies == []


# ══ 17-22 · RACES ═══════════════════════════════════════════════════════════
class TestRaces:

    def test_manual_close_during_the_modify(self):
        v = Venue(effect=True)
        original = v.modify_order

        def close_then_modify(order_id, **kw):
            v._p = []
            return original(order_id, **kw)
        v.modify_order = close_then_modify
        out = apply_short(v)
        assert out["outcome"] == ACT.HELD
        assert out["reason"] == ACT.POSITION_GONE
        assert out["retryable"] is False

    def test_stop_fill_during_the_modify(self):
        v = Venue(effect=False)
        original = v.modify_order

        def fill_then_modify(order_id, **kw):
            v._p, v._o = [], []
            return original(order_id, **kw)
        v.modify_order = fill_then_modify
        assert apply_short(v)["outcome"] == ACT.HELD

    def test_the_stop_disappearing_with_the_position_open_is_a_defect(self):
        v = Venue(effect=False)
        original = v.modify_order

        def drop_stop(order_id, **kw):
            v._o = [target_order()]
            return original(order_id, **kw)
        v.modify_order = drop_stop
        out = apply_short(v)
        assert out["outcome"] == ACT.PROTECTION_DEFECT
        assert out["retryable"] is False

    def test_a_position_flip_is_not_silently_managed(self):
        v = Venue(positions=[position(size=-S_SIZE, side="long")])
        out = apply_short(v, expected_size=S_SIZE)
        assert out["outcome"] in (ACT.REFUSED, ACT.HELD, ACT.PROTECTION_DEFECT)
        assert v.modifies == []


# ══ 25 · TARGET IMMUTABILITY ════════════════════════════════════════════════
class TestTargetImmutability:

    def test_the_target_is_never_sent(self):
        v = Venue()
        apply_short(v)
        assert all(m["limit_price"] is None for m in v.modifies)

    def test_target_identity_and_price_survive(self):
        v = Venue()
        out = apply_short(v)
        assert out["outcome"] == ACT.APPLIED
        assert out["target"] == {"id": TARGET_ID, "limit_price": S_TARGET}
        after = [o for o in v.open_orders() if o["id"] == TARGET_ID][0]
        assert after["limit_price"] == S_TARGET

    def test_a_target_that_moved_under_us_is_not_a_clean_application(self):
        v = Venue(effect=True)
        original = v.modify_order

        def also_move_target(order_id, **kw):
            r = original(order_id, **kw)
            for o in v._o:
                if o["id"] == TARGET_ID:
                    o["limit_price"] = 28900.0
            return r
        v.modify_order = also_move_target
        out = apply_short(v)
        assert out["outcome"] == ACT.AMBIGUOUS
        assert out["reason"] == ACT.TARGET_CHANGED


# ══ 26 · 2026-08-24 GEOMETRY + SYNTHETIC LINEAGE ════════════════════════════
class TestTheLiveShortSpecimen:
    """fill 29090.25 · stop 29110.25 · R = 20.0 · 8 MNQ · BE 29088.50.

    The GEOMETRY is historical evidence. The stop/target ORDER IDS are fixture:
    the 08-24 trade was closed manually before protective lineage existed, so no
    real 08-24 child id was ever observed. Stated here so the distinction cannot
    quietly decay into "the actuator was proven against the real 08-24 orders".
    """

    def test_the_decision_layer_reproduces_the_certified_geometry(self):
        d = BE.evaluate(direction="short", entry_fill_price=S_FILL,
                        initial_stop_price=S_STOP, active_protective_stop=S_STOP,
                        current_price=S_TRIGGER, armed=True, contract=MNQ,
                        quantity=S_SIZE)
        assert d["outcome"] == BE.PROPOSE
        assert d["initial_risk_points"] == 20.0
        assert d["open_r"] >= 1.0
        assert d["break_even_price"] == S_BE

    def test_the_actuator_applies_it_once_against_the_real_geometry(self):
        v = Venue()
        d = BE.evaluate(direction="short", entry_fill_price=S_FILL,
                        initial_stop_price=S_STOP, active_protective_stop=S_STOP,
                        current_price=S_TRIGGER, armed=True, contract=MNQ,
                        quantity=S_SIZE)
        out = apply_short(v, proposed=d["break_even_price"], expected_size=S_SIZE)
        assert out["outcome"] == ACT.APPLIED
        assert out["previous_protective_stop"] == S_STOP
        assert out["active_protective_stop"] == S_BE
        assert out["target"]["limit_price"] == S_TARGET
        assert v.modifies == [{"order_id": STOP_ID, "stop_price": S_BE,
                               "limit_price": None}]

    def test_R_is_never_reconstructed_from_the_current_stop(self):
        """Once protection has advanced, the live stop is NOT the risk baseline.
        Measuring R off it would make every managed trade look like 0R."""
        after_be = BE.evaluate(
            direction="short", entry_fill_price=S_FILL, initial_stop_price=S_STOP,
            active_protective_stop=S_BE, current_price=S_TRIGGER, armed=True,
            contract=MNQ, quantity=S_SIZE)
        assert after_be["initial_risk_points"] == 20.0


# ══ 18 · THE MIRRORED LONG ══════════════════════════════════════════════════
class TestMirroredLong:
    """Same law, inverted. No direction-specific asymmetry."""

    FILL, STOP, TARGET = 29226.25, 29192.00, 29409.25
    SIZE = 5

    def venue(self, stop_price=None):
        pos = {"id": 1, "contract_id": CID, "side": "long", "size": self.SIZE,
               "avg_price": self.FILL, "opened_at": "x"}
        return Venue(positions=[pos],
                     orders=[stop_order(self.STOP if stop_price is None
                                        else stop_price, size=self.SIZE),
                             target_order(self.TARGET, size=self.SIZE)])

    def decide(self, quote):
        return BE.evaluate(direction="long", entry_fill_price=self.FILL,
                           initial_stop_price=self.STOP,
                           active_protective_stop=self.STOP, current_price=quote,
                           armed=True, contract=MNQ, quantity=self.SIZE)

    def test_initial_risk_and_trigger_are_mirrored(self):
        assert self.decide(self.FILL + 34.25)["initial_risk_points"] == 34.25
        assert self.decide(self.FILL + 10)["outcome"] == BE.HOLD

    def test_break_even_sits_ABOVE_the_fill_for_a_long(self):
        d = self.decide(self.FILL + 34.25)
        assert d["outcome"] == BE.PROPOSE
        assert d["break_even_price"] > self.FILL

    def test_the_stop_moves_upward_only(self):
        d = self.decide(self.FILL + 34.25)
        v = self.venue()
        out = ACT.apply_break_even(session=v, contract_id=CID, entry_order_id=ENTRY,
                                   direction="long",
                                   proposed_stop=d["break_even_price"],
                                   expected_size=self.SIZE)
        assert out["outcome"] == ACT.APPLIED
        assert out["active_protective_stop"] > out["previous_protective_stop"]
        assert out["target"]["limit_price"] == self.TARGET

    def test_a_downward_proposal_is_refused_for_a_long(self):
        v = self.venue()
        out = ACT.apply_break_even(session=v, contract_id=CID, entry_order_id=ENTRY,
                                   direction="long", proposed_stop=self.STOP - 5)
        assert out["outcome"] == ACT.HELD
        assert v.modifies == []


# ══ 15-16 · RESTART ═════════════════════════════════════════════════════════
class TestRestartMatrix:
    """State is re-derived from the venue, so a restart cannot double-apply."""

    def test_restart_after_the_venue_applied_but_before_local_persistence(self):
        """The dangerous one: our record says nothing happened, the venue says
        it did. The venue wins and no second write is sent."""
        v = Venue(orders=[stop_order(S_BE), target_order()])
        out = apply_short(v)
        assert out["outcome"] == ACT.HELD
        assert v.modifies == []

    def test_restart_before_1R_leaves_the_original_stop(self):
        v = Venue()
        d = BE.evaluate(direction="short", entry_fill_price=S_FILL,
                        initial_stop_price=S_STOP, active_protective_stop=S_STOP,
                        current_price=29100.0, armed=True, contract=MNQ,
                        quantity=S_SIZE)
        assert d["outcome"] == BE.HOLD
        assert v.open_orders()[0]["stop_price"] == S_STOP

    def test_restart_after_a_manual_advance_beyond_break_even_holds(self):
        v = Venue(orders=[stop_order(29070.0), target_order()])
        assert apply_short(v)["outcome"] == ACT.HELD
        assert v.modifies == []


# ══ 28-30 · MANAGEMENT-ONLY INTEGRATION ═════════════════════════════════════
class TestManagementOnlyIntegration:
    """The actuator must run with entry authority spent and cognition off."""

    def test_the_actuator_calls_no_provider(self):
        import ai_brain.narrative_brain as NB
        calls = []
        real = NB.run_narrative_brain
        NB.run_narrative_brain = lambda *a, **k: calls.append(1)
        try:
            apply_short(Venue())
        finally:
            NB.run_narrative_brain = real
        assert calls == []

    def test_the_whole_managed_path_reaches_a_clean_exit(self, tmp_path):
        """cap spent -> managed advance -> position closes -> venue clean."""
        from broker import topstepx_session_lifecycle as LC

        class Mission:
            class Auth:
                maximum_trades = 2
            authorization = Auth()
            trade_missions = []

            def trades_used(self):
                return 2

        v = Venue()
        managing = LC.resolve(mission=Mission(), venue=v, contract_id=CID)
        assert managing["mode"] == LC.MANAGEMENT_ONLY

        assert apply_short(v)["outcome"] == ACT.APPLIED

        v._p, v._o = [], []
        after = LC.resolve(mission=Mission(), venue=v, contract_id=CID)
        assert after["mode"] == LC.SESSION_COMPLETE
        assert after["may_exit"] is True
