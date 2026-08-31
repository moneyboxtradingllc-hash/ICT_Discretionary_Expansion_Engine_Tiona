"""DATE-SCOPED WINDOW OVERRIDE — the 2026-08-12 extended session.

An operator ruling for ONE day. The production defect found that morning cost
the session its first four hours, so scanning was extended to 15:54:59 with a
hard flatten at 15:55. Every other date must revert to the canonical window by
construction, not by anyone remembering to change it back.

What this file pins is the boundary, in both directions and on both dates. An
extended window that leaks into tomorrow is a worse defect than not extending at
all, because nobody would be watching for it.

No network. No model. No order.
"""
from __future__ import annotations

import os
import sys
from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))

from broker import topstepx_session_authorization as SA            # noqa: E402
from tools import topstepx_production_session as PS                # noqa: E402

ET = ZoneInfo("America/New_York")
TODAY = "20260812"
TOMORROW = "20260813"


def t(date: str, hhmmss: str) -> datetime:
    h, m, s = (int(x) for x in hhmmss.split(":"))
    return datetime(int(date[:4]), int(date[4:6]), int(date[6:]), h, m, s, tzinfo=ET)


# ══════════════════════════════════════════════════════════════════════════════
class TestTheRulingIsDateScoped:

    def test_today_carries_the_override(self):
        w = SA.window_for(TODAY)
        assert w["override"] is True
        assert (w["start"], w["end"]) == ("09:30", "15:55")
        assert w["hard_flatten"] == "15:55"

    def test_tomorrow_reverts_automatically(self):
        w = SA.window_for(TOMORROW)
        assert w["override"] is False
        assert (w["start"], w["end"]) == ("09:00", "14:00")   # PRE-NY-1
        assert w["hard_flatten"] is None

    def test_yesterday_was_never_extended(self):
        assert SA.window_for("20260811")["end"] == "14:00"

    def test_the_normal_constants_are_untouched(self):
        """The override must not have been implemented by editing doctrine.

        PRE-NY-EXECUTION-WINDOW-1 moved the canonical START 09:30 -> 09:00 as a
        deliberate doctrine change. The END is untouched, and the point of this
        test is unchanged: the 2026-08-12 override must not have been achieved
        by editing the constants.
        """
        assert SA.PRODUCTION_WINDOW_START == "09:00"
        assert SA.PRODUCTION_WINDOW_END == "14:00"

    def test_exactly_one_date_is_overridden(self):
        assert set(SA.SESSION_WINDOW_OVERRIDES) == {TODAY}

    def test_an_unknown_date_never_widens(self):
        for d in ("", None, "not-a-date", "20261212"):
            assert SA.window_for(d)["end"] == "14:00"


# ══════════════════════════════════════════════════════════════════════════════
class TestTodaysEntryBoundary:
    """The exact minutes, pinned."""

    @pytest.mark.parametrize("hhmmss", [
        "09:30:00", "13:59:59", "14:00:00", "14:00:01", "15:00:00",
        "15:54:00", "15:54:59",
    ])
    def test_entry_permitted(self, hhmmss):
        assert PS.production_window_open(t(TODAY, hhmmss)) is True, hhmmss

    @pytest.mark.parametrize("hhmmss", [
        "09:29:59", "15:55:00", "15:55:01", "15:56:00", "16:00:00", "23:59:59",
    ])
    def test_entry_refused(self, hhmmss):
        assert PS.production_window_open(t(TODAY, hhmmss)) is False, hhmmss

    def test_the_override_start_is_NOT_widened_by_the_new_default(self):
        """PRE-NY-EXECUTION-WINDOW-1. The canonical start moved to 09:00, but
        this date carries its own 09:30 ruling and must keep it."""
        assert SA.window_for(TODAY)["start"] == "09:30"
        assert PS.production_window_open(t(TODAY, "09:00:00")) is False
        assert PS.production_window_open(t(TODAY, "09:29:59")) is False
        assert PS.production_window_open(t(TODAY, "09:30:00")) is True

    def test_the_closing_minute_is_NOT_tradeable(self):
        """`<=` would have handed back the whole 15:55 minute. At 15:55 the
        machine's job changes from finding trades to getting flat."""
        assert PS.production_window_open(t(TODAY, "15:54:59")) is True
        assert PS.production_window_open(t(TODAY, "15:55:00")) is False

    def test_1400_no_longer_closes_the_session_today(self):
        assert PS.production_window_open(t(TODAY, "14:00:00")) is True
        assert PS.production_window_open(t(TODAY, "14:30:00")) is True


# ══════════════════════════════════════════════════════════════════════════════
class TestTomorrowIsUnaffected:

    @pytest.mark.parametrize("hhmmss", [
        "09:00:00", "09:07:00", "09:30:00", "13:59:59",
    ])
    def test_normal_entry_permitted(self, hhmmss):
        """PRE-NY-EXECUTION-WINDOW-1 added 09:00 and 09:07: a lawful thesis
        before the CASH open is now actionable, not merely observable."""
        assert PS.production_window_open(t(TOMORROW, hhmmss)) is True, hhmmss

    @pytest.mark.parametrize("hhmmss", ["08:59:59", "08:45:00", "00:00:00"])
    def test_before_the_new_start_still_refuses(self, hhmmss):
        assert PS.production_window_open(t(TOMORROW, hhmmss)) is False, hhmmss

    @pytest.mark.parametrize("hhmmss", [
        "14:00:00", "14:00:01", "15:54:59", "15:55:00",
    ])
    def test_normal_close_still_refuses(self, hhmmss):
        assert PS.production_window_open(t(TOMORROW, hhmmss)) is False, hhmmss

    def test_no_date_leakage_across_midnight(self):
        assert PS.production_window_open(t(TODAY, "15:30:00")) is True
        assert PS.production_window_open(t(TOMORROW, "15:30:00")) is False


# ══════════════════════════════════════════════════════════════════════════════
class TestHardFlattenAuthority:

    @pytest.mark.parametrize("hhmmss", ["09:30:00", "14:00:00", "15:54:59"])
    def test_not_due_before_the_ruling(self, hhmmss):
        assert PS.hard_flatten_due(t(TODAY, hhmmss)) is False, hhmmss

    @pytest.mark.parametrize("hhmmss", ["15:55:00", "15:55:30", "16:10:00"])
    def test_due_at_and_after_the_ruling(self, hhmmss):
        assert PS.hard_flatten_due(t(TODAY, hhmmss)) is True, hhmmss

    def test_a_normal_date_has_no_hard_flatten(self):
        """Unchanged doctrine: entries stop at 14:00 and the loop MANAGES an
        open position rather than force-closing it."""
        for hhmmss in ("14:00:00", "15:55:00", "16:30:00"):
            assert PS.hard_flatten_due(t(TOMORROW, hhmmss)) is False, hhmmss

    def test_entry_is_already_refused_when_flatten_becomes_due(self):
        """The two authorities must not leave a gap where an entry is legal but
        the flatten has fired."""
        moment = t(TODAY, "15:55:00")
        assert PS.hard_flatten_due(moment) is True
        assert PS.production_window_open(moment) is False


# ══════════════════════════════════════════════════════════════════════════════
#: The authorization token id this fake session issued.
_TOKEN = "PRAC-20260826-T1"


class TestTheFlattenItself:

    class _Session:
        def __init__(self, positions=1, orders=2, fail=False):
            self._pos, self._ord, self._fail = positions, orders, fail
            self.closed, self.cancelled = [], []

        def open_positions(self):
            # A position carries the contract and a SIZE. The old fixture
            # returned `{"id": 1}`, which no venue emits and which the certified
            # liquidation authority cannot size a close from.
            return [{"contract_id": "CON.F.US.MNQ.U26", "size": 5, "type": 1}] \
                * self._pos

        def open_orders(self):
            return self._rows()

        def _rows(self):
            # `status: 1` (Open) is STATED. `OrderModel.status` is required by
            # the Gateway schema, and inferring it from endpoint membership
            # would fabricate a field the payload never carried.
            # `side` IS REQUIRED, and its absence is not neutral: the same
            # order is protection or an entry depending on which way it points
            # relative to the position, so the certified planner refuses to act
            # on one whose direction it cannot read. These are the SELL legs of
            # a bracket under the LONG position above.
            # `custom_tag` IS THE LINEAGE. Without a mission in scope the only
            # thing that can attribute an order to this session is the tag the
            # bot stamps on everything it sends: `EXPBOT-<token_id>`. An
            # untagged order is MANUAL_OPERATOR and is never ours to cancel --
            # so a fixture that omits it is modelling somebody else's book.
            return [{"id": 900 + i, "contract_id": "CON.F.US.MNQ.U26",
                     "status": 1, "side": 1, "size": 5, "type": 4,
                     "customTag": f"EXPBOT-{_TOKEN}"}
                    for i in range(self._ord)]

        def query_orders(self, *, statuses=None, contract_id=None):
            """`/api/Order/v2/query` -- the COMPLETE discovery surface.

            A fixture WITHOUT this method models the degraded `searchOpen`
            fallback, not the production path: `searchOpen` omits Suspended
            bracket children by venue contract, so a flatten driven from it can
            never honestly claim the account is clear.
            """
            rows = self._rows()
            if contract_id:
                rows = [o for o in rows if o["contract_id"] == contract_id]
            return rows

        def order_by_id(self, order_id):
            return None

        def close_position(self, contract_id):
            if self._fail:
                raise RuntimeError("venue refused")
            self.closed.append(contract_id)
            self._pos = 0

        def cancel_order(self, order_id):
            self.cancelled.append(order_id)
            self._ord = max(0, self._ord - 1)

    class _Contract:
        id = "CON.F.US.MNQ.U26"

    class _Ledger:
        """What production hands the shutdown: the tokens THIS session issued."""

        known_token_ids = {_TOKEN}

    def test_it_closes_the_position_and_cancels_the_orders(self):
        s = self._Session(positions=1, orders=2)
        rep = PS.hard_flatten(s, self._Contract(), ledger=self._Ledger())
        assert rep["closed"] is True
        assert s.closed == ["CON.F.US.MNQ.U26"]
        assert len(rep["cancelled"]) == 2
        assert rep["flat"] is True
        assert not rep["errors"]

    def test_orders_are_cancelled_BEFORE_the_position_is_closed(self):
        """THE ORDERING IS INVERTED, DELIBERATELY.

        This test used to assert `order_of_events[0] == "close"`, on the
        reasoning that cancelling first strips protection from size that is
        still on. The account answered that argument on 2026-08-26: a protective
        stop survived a close by 86ms and reversed a flat account into LONG 15
        for -$307.50.

        The naked window between a cancel and the close that immediately follows
        is bounded and measured in milliseconds. An armed order pointing at an
        account with nothing left to protect is unbounded exposure in the WRONG
        DIRECTION. The general law, of which "flat" is only the cleanest case:

            an old-trade order can create unintended exposure whenever its
            executable quantity exceeds the remaining opposing position

        SHORT 6 against a resting BUY stop for 15 flattens six and goes LONG
        NINE, so this is not a claim about flatness at all.
        """
        order_of_events = []
        s = self._Session(positions=1, orders=1)
        s.close_position = lambda cid: (order_of_events.append("close"),
                                        setattr(s, "_pos", 0))
        s.cancel_order = lambda oid: (order_of_events.append("cancel"),
                                      setattr(s, "_ord", 0))
        PS.hard_flatten(s, self._Contract(), ledger=self._Ledger())
        assert order_of_events[0] == "cancel"
        assert "close" in order_of_events, "the position is still closed"

    def test_it_drives_the_certified_planner_not_a_policy_of_its_own(self):
        """Two liquidation policies mean two chances to be wrong about one
        account. `topstepx_emergency_liquidation` decides; this module only
        supplies venue I/O."""
        import inspect

        from broker import topstepx_hard_flatten as HF
        src = inspect.getsource(HF)
        assert "EL.plan(" in src
        assert "DISC.discover_orders(" in src

    def test_an_incomplete_order_view_may_not_claim_flat(self):
        """A venue with no `query_orders` is the degraded `searchOpen`
        fallback, which is documented to hide Suspended bracket children. It may
        report what it did; it may not report the account as clear."""
        class _Legacy(self._Session):
            query_orders = None          # the venue cannot serve v2/query

        rep = PS.hard_flatten(_Legacy(positions=0, orders=0), self._Contract(),
                              ledger=self._Ledger())
        assert rep["flat"] is False
        assert any("INCOMPLETE" in e for e in rep["errors"]), rep["errors"]

    def test_already_flat_is_a_clean_no_op(self):
        s = self._Session(positions=0, orders=0)
        rep = PS.hard_flatten(s, self._Contract(), ledger=self._Ledger())
        assert rep["closed"] is False and rep["cancelled"] == []
        assert rep["flat"] is True and not rep["errors"]

    def test_delegates_to_the_certified_authority_when_a_runner_exists(self):
        """A live runner carries mission lineage and the durable halt ladder, so
        the end-of-session flatten goes through the SAME safety authority as
        every other liquidation."""
        calls = []

        class _Runner:
            def emergency_flatten(self, reason):
                calls.append(reason)
                return {"flattened": True, "cancelled_mission_orders": [1],
                        "foreign_orders_left_alone": [], "halts": [],
                        "cancellation_failures": [], "confirmed": {"closed": True}}

        s = self._Session(positions=1, orders=1)
        rep = PS.hard_flatten(s, self._Contract(), runner=_Runner())
        assert rep["delegated"] is True and rep["flat"] is True
        assert calls and s.closed == [], "the runner owns the venue writes"

    def test_a_venue_refusal_is_reported_never_swallowed_as_flat(self):
        s = self._Session(positions=1, orders=1, fail=True)
        rep = PS.hard_flatten(s, self._Contract(), ledger=self._Ledger())
        assert rep["errors"], "a failed flatten must say so"
        assert rep["flat"] is False


# ══════════════════════════════════════════════════════════════════════════════
class TestTheAuthorizationAgreesWithEnforcement:
    """The banner, the record and the gate must state ONE window."""

    ACCT, CID = "acct:test000000", "CON.F.US.MNQ.U26"

    def test_todays_authorization_records_the_extended_window(self, tmp_path):
        a = SA.issue(path=str(tmp_path / "a.json"), session_id="T",
                     account_fingerprint=self.ACCT, contract_id=self.CID,
                     session_date=TODAY)
        assert a.decision_window == "09:30-15:55 America/New_York"
        a.verify(account_fingerprint=self.ACCT, contract_id=self.CID,
                 session_date=TODAY)

    def test_tomorrows_authorization_records_the_normal_window(self, tmp_path):
        a = SA.issue(path=str(tmp_path / "b.json"), session_id="T",
                     account_fingerprint=self.ACCT, contract_id=self.CID,
                     session_date=TOMORROW)
        assert a.decision_window == "09:00-14:00 America/New_York"   # PRE-NY-1

    def test_an_extended_window_on_the_WRONG_date_is_refused(self, tmp_path):
        """The record cannot carry today's ruling into another session."""
        a = SA.issue(path=str(tmp_path / "c.json"), session_id="T",
                     account_fingerprint=self.ACCT, contract_id=self.CID,
                     session_date=TOMORROW)
        a.decision_window = "09:30-15:55 America/New_York"
        a.authorization_fingerprint = a.fingerprint()
        with pytest.raises(SA.AuthorizationRefused) as exc:
            a.verify(account_fingerprint=self.ACCT, contract_id=self.CID,
                     session_date=TOMORROW)
        assert "WINDOW_MISMATCH" in str(exc.value)

    def test_the_record_matches_what_the_gate_enforces(self, tmp_path):
        a = SA.issue(path=str(tmp_path / "d.json"), session_id="T",
                     account_fingerprint=self.ACCT, contract_id=self.CID,
                     session_date=TODAY)
        end = a.decision_window.split()[0].split("-")[1]
        h, m = (int(x) for x in end.split(":"))
        last = t(TODAY, f"{h:02d}:{m - 1:02d}:59")
        assert PS.production_window_open(last) is True
        assert PS.production_window_open(t(TODAY, f"{h:02d}:{m:02d}:00")) is False
