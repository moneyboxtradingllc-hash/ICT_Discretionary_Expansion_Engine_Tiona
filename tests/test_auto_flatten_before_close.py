"""AUTO-FLATTEN — never carry intraday size past the close.

Day margin is $100 a contract against $4,187.12 initial: a ~42x gap. At $50k
equity the account can day-trade ~251 contracts but hold 12 overnight, so a
compounded 83-lot position carried past the close needs $347,531 of initial
margin against a $50k account.

Entries already stopped at 14:00, but nothing closed an OPEN position —
stop_lane.py does and it is run by hand. At a flat 30 contracts a forgotten
manual stop was survivable. With compounding it is not.
"""
import datetime as _dt
import os
import sys
from zoneinfo import ZoneInfo

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from integrations.topstepx.deterministic import loop as L
from integrations.topstepx.deterministic import FLATTEN_AT, FLATTEN_UNTIL

ET = ZoneInfo("America/New_York")
MON, SAT, SUN = 27, 25, 26          # 2026-07


def _t(day, hm):
    h, m = map(int, hm.split(":"))
    return _dt.datetime(2026, 7, day, h, m, tzinfo=ET)


class _Client:
    def __init__(self, ok=True):
        self.ok = ok
        self.flatten_calls = []

    def flatten(self, instrument):
        self.flatten_calls.append(instrument)
        return {"ok": self.ok, "reason": "" if self.ok else "bridge refused"}


class _Session:
    def __init__(self):
        self.stopped = None

    def stop_new_entries(self, reason):
        self.stopped = reason


def _pos(qty=0, known=True):
    return {"qty": qty, "known": known, "market_position": "Flat" if not qty else "Short"}


def _orders(n=0):
    return {"working_order_count": n, "known": True}


class TestWindow:
    @pytest.mark.parametrize("hm,inside", [
        ("13:59", False), ("14:30", False), ("15:49", False),
        (FLATTEN_AT, True), ("15:55", True), ("16:00", True),
        (FLATTEN_UNTIL, True), ("16:16", False), ("17:30", False),
    ])
    def test_window_bounds(self, hm, inside):
        assert L._in_flatten_window(_t(MON, hm)) is inside

    @pytest.mark.parametrize("day", [SAT, SUN])
    def test_weekends_are_suppressed(self, day):
        """The loop runs through the weekend; there is nothing to close."""
        assert L._in_flatten_window(_t(day, "15:55")) is False

    def test_the_window_opens_before_the_close(self):
        """Room for several 30s scans to retry a failed flatten."""
        assert FLATTEN_AT < "16:00" <= FLATTEN_UNTIL


class TestItFlattens:
    def test_an_open_position_is_closed(self, monkeypatch):
        monkeypatch.setattr(L, "_in_flatten_window", lambda now=None: True)
        c, s = _Client(), _Session()
        r = L.force_flat_if_due(c, s, _pos(-83), _orders(2), 1)
        assert r["attempted"] is True and r["ok"] is True
        assert r["qty_before"] == -83
        assert c.flatten_calls

    def test_working_orders_alone_are_cleared(self, monkeypatch):
        """Flat but with resting orders is still not safe to leave overnight."""
        monkeypatch.setattr(L, "_in_flatten_window", lambda now=None: True)
        c = _Client()
        assert L.force_flat_if_due(c, _Session(), _pos(0), _orders(2), 1)["attempted"]

    def test_new_entries_are_stopped_after_a_successful_flatten(self, monkeypatch):
        monkeypatch.setattr(L, "_in_flatten_window", lambda now=None: True)
        s = _Session()
        L.force_flat_if_due(_Client(), s, _pos(-30), _orders(2), 1)
        assert s.stopped is not None


class TestItDoesNotActWhenItShould(object):
    def test_outside_the_window_nothing_happens(self, monkeypatch):
        monkeypatch.setattr(L, "_in_flatten_window", lambda now=None: False)
        c = _Client()
        assert L.force_flat_if_due(c, _Session(), _pos(-83), _orders(2), 1) is None
        assert not c.flatten_calls

    def test_already_flat_is_a_no_op(self, monkeypatch):
        monkeypatch.setattr(L, "_in_flatten_window", lambda now=None: True)
        c = _Client()
        r = L.force_flat_if_due(c, _Session(), _pos(0), _orders(0), 1)
        assert r["attempted"] is False
        assert not c.flatten_calls, "must not send a redundant flatten"

    def test_disabled_by_config(self, monkeypatch):
        monkeypatch.setattr(L, "AUTO_FLATTEN_ENABLED", False)
        monkeypatch.setattr(L, "_in_flatten_window", lambda now=None: True)
        assert L.force_flat_if_due(_Client(), _Session(), _pos(-83), _orders(2), 1) is None


class TestFailureIsLoudAndRetried:
    def test_a_failed_flatten_reports_not_ok(self, monkeypatch):
        monkeypatch.setattr(L, "_in_flatten_window", lambda now=None: True)
        r = L.force_flat_if_due(_Client(ok=False), _Session(), _pos(-83), _orders(2), 1)
        assert r["attempted"] is True and r["ok"] is False

    def test_a_failed_flatten_does_not_stop_entries(self, monkeypatch):
        """Marking the session stopped on a FAILED flatten would hide an open
        position behind a 'clean shutdown' state."""
        monkeypatch.setattr(L, "_in_flatten_window", lambda now=None: True)
        s = _Session()
        L.force_flat_if_due(_Client(ok=False), s, _pos(-83), _orders(2), 1)
        assert s.stopped is None

    def test_it_retries_on_the_next_scan(self, monkeypatch):
        monkeypatch.setattr(L, "_in_flatten_window", lambda now=None: True)
        c = _Client(ok=False)
        for scan in (1, 2, 3):
            L.force_flat_if_due(c, _Session(), _pos(-83), _orders(2), scan)
        assert len(c.flatten_calls) == 3

    def test_unknown_position_is_reported_not_assumed_flat(self, monkeypatch):
        """Assuming flat because the bridge is silent is the dangerous default."""
        monkeypatch.setattr(L, "_in_flatten_window", lambda now=None: True)
        r = L.force_flat_if_due(_Client(), _Session(), _pos(0, known=False), _orders(0), 1)
        assert r["attempted"] is False
        assert "unknown" in r["reason"]
