"""PRE-NY-EXECUTION-WINDOW-1 — the window opens at 09:00 New York, both regimes.

MNQ trades continuously overnight. 09:30 is the US CASH open, not the futures
open, and cognition already ran before it: PRE-BELL-LIFECYCLE made the process
observe from arming onward. So the only thing 09:30 gated was ACTING — a lawful
thesis at 09:07 was formed and then destroyed, because `produce()` raised
NoCandidate("window_closed") and `may_open_trade_mission` refused.

Both of those read the SAME `production_window_open()` boolean, so one constant
opens both. This file pins that: the boundary itself, that it follows New York
CIVIL time across EST/EDT rather than a fixed offset, and that both downstream
gates actually open at 09:07.

No network. No model. No order.
"""
from __future__ import annotations

import os
import sys
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))

from broker import topstepx_session_authorization as SA            # noqa: E402
from tools import topstepx_production_session as PS                # noqa: E402

ET = ZoneInfo("America/New_York")

#: Deliberately one winter and one summer date, neither of which carries a
#: SESSION_WINDOW_OVERRIDES entry. A single date would prove the string compare
#: and nothing about the timezone.
WINTER = (2027, 1, 13)      # EST, UTC-05:00
SUMMER = (2026, 7, 15)      # EDT, UTC-04:00


def et(date, hh, mm, ss=0):
    return datetime(*date, hh, mm, ss, tzinfo=ET)


# ══════════════════════════════════════════════════════════════════════════════
class TestTheCanonicalWindow:
    def test_the_start_is_0900(self):
        assert SA.PRODUCTION_WINDOW_START == "09:00"

    def test_the_end_is_untouched(self):
        assert SA.PRODUCTION_WINDOW_END == "14:00"

    def test_the_timezone_is_untouched(self):
        assert SA.PRODUCTION_WINDOW_TZ == "America/New_York"


# ══════════════════════════════════════════════════════════════════════════════
class TestTheBoundaryInBothDstRegimes:
    """The same civil times, on an EST date and an EDT date."""

    @pytest.mark.parametrize("date,label", [(WINTER, "EST"), (SUMMER, "EDT")])
    @pytest.mark.parametrize("hh,mm,ss,expected", [
        (8, 59, 59, False),     # before the open
        (9,  0,  0, True),      # THE REPAIR
        (9,  7,  0, True),      # the representative pre-cash-open decision
        (9, 30,  0, True),      # the old boundary, still open
        (13, 59, 59, True),     # the closing minute is still tradeable
        (14, 0,  0, False),     # end is STRICT
    ])
    def test_entry_boundary(self, date, label, hh, mm, ss, expected):
        t = et(date, hh, mm, ss)
        assert PS.production_window_open(t) is expected, f"{label} {hh:02d}:{mm:02d}:{ss:02d}"

    def test_the_two_dates_really_are_different_offsets(self):
        """Otherwise the parametrize above would prove nothing about DST."""
        assert et(WINTER, 9, 0).utcoffset().total_seconds() == -5 * 3600
        assert et(SUMMER, 9, 0).utcoffset().total_seconds() == -4 * 3600


# ══════════════════════════════════════════════════════════════════════════════
class TestCivilTimeNotFixedOffset:
    """09:00 means 09:00 IN NEW YORK, not a fixed number of hours from UTC."""

    @pytest.mark.parametrize("date,utc_hour", [(WINTER, 14), (SUMMER, 13)])
    def test_the_same_civil_time_is_a_different_utc_instant(self, date, utc_hour):
        t = et(date, 9, 7)
        assert t.astimezone(timezone.utc).hour == utc_hour
        assert PS.production_window_open(t) is True

    @pytest.mark.parametrize("date", [WINTER, SUMMER])
    def test_a_utc_instant_resolves_through_the_real_zone(self, date):
        """Arriving as UTC and converting must give the same verdict."""
        as_utc = et(date, 9, 7).astimezone(timezone.utc)
        assert PS.production_window_open(as_utc.astimezone(ET)) is True

    def test_the_session_date_is_new_york_not_utc(self):
        """23:30 ET is already the NEXT UTC day; the session must not roll."""
        t = et(SUMMER, 23, 30)
        assert t.astimezone(timezone.utc).strftime("%Y%m%d") == "20260716"
        assert PS.effective_window(t)["session_date"] == "20260715"

    def test_the_window_never_touches_a_dst_transition_hour(self):
        """US transitions occur at 02:00 local, so 09:00-14:00 can never be an
        ambiguous or nonexistent local time."""
        assert SA.PRODUCTION_WINDOW_START > "02:00"
        assert SA.PRODUCTION_WINDOW_END > "02:00"


# ══════════════════════════════════════════════════════════════════════════════
class TestTheOverrideStillWins:
    """Changing the default must not mutate a historical operator ruling."""

    def test_the_20260812_ruling_is_unchanged(self):
        w = SA.window_for("20260812")
        assert (w["start"], w["end"]) == ("09:30", "15:55")
        assert w["override"] is True

    def test_the_new_default_does_not_leak_into_that_date(self):
        assert PS.production_window_open(et((2026, 8, 12), 9, 0)) is False
        assert PS.production_window_open(et((2026, 8, 12), 9, 30)) is True

    def test_exactly_one_date_is_overridden(self):
        assert set(SA.SESSION_WINDOW_OVERRIDES) == {"20260812"}


# ══════════════════════════════════════════════════════════════════════════════
class TestBothDownstreamGatesOpen:
    """The point of the repair: candidate AND trade mission, not just one."""

    def test_the_candidate_gate_is_the_same_boolean(self):
        """`produce()` refuses on `in_window`, which production supplies from
        `production_window_open()`. Pin the refusal, not a reimplementation."""
        import ast
        import inspect
        import textwrap
        from broker.luna_candidate_producer import CandidateProducer
        src = textwrap.dedent(inspect.getsource(CandidateProducer.produce))
        tree = ast.parse(src)
        raises = [n for n in ast.walk(tree)
                  if isinstance(n, ast.Raise) and "window_closed" in ast.dump(n)]
        assert raises, "produce() no longer refuses on window_closed"
        assert "in_window" in {a.arg for a in tree.body[0].args.args
                               + tree.body[0].args.kwonlyargs}

    def test_the_trade_mission_gate_is_the_same_boolean(self):
        mission = SA.ProductionSessionMission.__dict__.get("may_open_trade_mission")
        assert mission is not None
        import inspect
        assert "in_window" in inspect.signature(mission).parameters

    @pytest.mark.parametrize("date", [WINTER, SUMMER])
    def test_at_0907_production_supplies_in_window_true(self, date):
        """THE THEOREM. At 09:07 the boolean both gates consume is True, so
        neither can refuse on the clock alone."""
        assert PS.production_window_open(et(date, 9, 7)) is True

    def test_at_0907_the_mission_gate_does_not_refuse_on_the_clock(self):
        ok, why = SA.ProductionSessionMission.may_open_trade_mission(
            _NoActiveMission(), positions=0, working_orders=0,
            unknown_external=False, in_window=True)
        assert ok is True, why
        assert "window" not in why.lower()

    def test_and_still_refuses_when_the_window_is_shut(self):
        """The control — otherwise the test above proves nothing."""
        ok, why = SA.ProductionSessionMission.may_open_trade_mission(
            _NoActiveMission(), positions=0, working_orders=0,
            unknown_external=False, in_window=False)
        assert ok is False and "window" in why.lower()


class _NoActiveMission:
    """Minimum state `may_open_trade_mission` reads BEFORE the window check.

    Deliberately real values rather than a permissive `__getattr__`: every
    earlier precondition must genuinely pass, otherwise the window assertion
    would be answering a different refusal.
    """
    active_mission = None

    @staticmethod
    def rejected_missions():
        return []

    @staticmethod
    def trades_used():
        return 0

    trade_missions = ()          # nothing awaiting reconciliation
    authorization = type("A", (), {"maximum_trades": 2})()


# ══════════════════════════════════════════════════════════════════════════════
class TestDailyStateIsUnmoved:
    """The forensic conclusion, pinned: day identity keys on the calendar date,
    never on the window's start time."""

    @pytest.mark.parametrize("date", [WINTER, SUMMER])
    def test_0900_and_0930_are_the_same_session_date(self, date):
        assert (PS.effective_window(et(date, 9, 0))["session_date"]
                == PS.effective_window(et(date, 9, 30))["session_date"])

    @pytest.mark.parametrize("date", [WINTER, SUMMER])
    def test_0900_and_0930_are_the_same_utc_day(self, date):
        """`session_id` derives from the UTC date; 09:00 and 09:30 ET are the
        same UTC calendar day in both regimes, so nothing resets earlier."""
        a = et(date, 9, 0).astimezone(timezone.utc).strftime("%Y%m%d")
        b = et(date, 9, 30).astimezone(timezone.utc).strftime("%Y%m%d")
        assert a == b
