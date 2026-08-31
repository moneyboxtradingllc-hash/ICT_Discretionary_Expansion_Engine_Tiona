"""BAR-HALT-OBSERVATION-1 — the observer must be able to record a contradiction.

The instrument exists because the canonical store and the CME schedule disagree:
2026-08-17 holds a bar for all fifteen 16:15-16:30 ET halt minutes while holding
none for the sixty 17:00-18:00 maintenance minutes. Same file, same day, same
timestamp convention.

The property that matters most here is NOT that the observer records a halt
correctly. It is that the observer cannot quietly make the contradiction go
away: a trade timestamped inside a published halt must survive capture,
annotation and adjudication, because a filter that dropped it would guarantee
the experiment could only ever confirm what we already believe.

No live market connection is needed by anything below.
"""
from __future__ import annotations

import os
import sys
from datetime import date, datetime, timedelta, timezone

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src"))

from market_data import halt_observation as HO                       # noqa: E402

DAY = date(2026, 8, 17)
WINDOW = HO.halt_window(DAY)


def _et(hh, mm, ss=0):
    return datetime(2026, 8, 17, hh, mm, ss, tzinfo=HO.ET).astimezone(timezone.utc)


def _trade(hh, mm, price=30078.0, volume=3):
    return HO.normalise_event(family=HO.TRADE,
                              payload={"price": price, "volume": volume, "type": 0},
                              received_utc=_et(hh, mm), provider_timestamp=_et(hh, mm),
                              window=WINDOW)


def _quote(hh, mm, bid=30077.75, ask=30078.0, volume=1234):
    return HO.normalise_event(family=HO.QUOTE,
                              payload={"bestBid": bid, "bestAsk": ask,
                                       "lastPrice": ask, "volume": volume},
                              received_utc=_et(hh, mm), provider_timestamp=_et(hh, mm),
                              window=WINDOW)


def _bar(hh, mm, volume=1155.0):
    return {"t": _et(hh, mm).isoformat(), "o": 30078.0, "h": 30081.25,
            "l": 30073.0, "c": 30073.25, "v": volume}


# ── §12 timezone / halt boundaries ────────────────────────────────────────────

class TestHaltBoundaries:
    @pytest.mark.parametrize("hh,mm,ss,expected", [
        (16, 14, 59, HO.PRE_HALT),
        (16, 15, 0, HO.IN_HALT),
        (16, 29, 59, HO.IN_HALT),
        (16, 30, 0, HO.POST_HALT),
    ])
    def test_exact_minute_boundaries(self, hh, mm, ss, expected):
        assert HO.classify_against_halt(_et(hh, mm, ss), WINDOW) == expected

    def test_the_window_is_resolved_through_new_york_not_a_fixed_offset(self):
        """EDT and EST must both land on 16:15 ET, not on a hardcoded -04:00."""
        summer = HO.halt_window(date(2026, 8, 17))
        winter = HO.halt_window(date(2026, 12, 17))
        assert summer[0].astimezone(HO.ET).hour == 16
        assert winter[0].astimezone(HO.ET).hour == 16
        assert summer[0].utcoffset() == winter[0].utcoffset()      # both UTC
        assert summer[0].isoformat().endswith("20:15:00+00:00")    # EDT
        assert winter[0].isoformat().endswith("21:15:00+00:00")    # EST

    def test_an_unreadable_timestamp_is_stated_not_guessed(self):
        assert HO.classify_against_halt("not-a-time", WINDOW) == "unknown_timestamp"


# ── raw preservation; families never merge ────────────────────────────────────

class TestRawPreservation:
    def test_the_raw_payload_survives_beside_the_reading(self):
        ev = _trade(16, 20)
        assert ev["raw"] == {"price": 30078.0, "volume": 3, "type": 0}
        assert ev["provider_timestamp_utc"] == _et(16, 20).isoformat()
        assert ev["provider_timestamp_et"].endswith("16:20:00-04:00")

    def test_a_missing_provider_timestamp_is_never_backfilled_from_our_clock(self):
        ev = HO.normalise_event(family=HO.TRADE, payload={"price": 1.0},
                                received_utc=_et(16, 20), provider_timestamp=None,
                                window=WINDOW)
        assert ev["provider_timestamp_utc"] is None
        assert ev["provider_timestamp_raw"] is None
        assert ev["local_receive_time_utc"] is not None      # ours is still ours

    def test_a_quote_is_not_a_trade(self):
        matrix = HO.minute_matrix(events=[_quote(16, 20), _quote(16, 20)],
                                  bars=[], window=WINDOW,
                                  first_minute=_et(16, 20), last_minute=_et(16, 21))
        row = matrix[0]
        assert row["quote_events"] == 2
        assert row["trade_events"] == 0
        assert row["trade_volume"] == 0.0

    def test_families_are_counted_separately_in_one_minute(self):
        matrix = HO.minute_matrix(events=[_trade(16, 20), _quote(16, 20)], bars=[],
                                  window=WINDOW, first_minute=_et(16, 20),
                                  last_minute=_et(16, 21))
        assert (matrix[0]["trade_events"], matrix[0]["quote_events"]) == (1, 1)


# ── THE property: contradictory evidence must survive ─────────────────────────

class TestContradictionSurvives:
    def test_a_trade_inside_the_halt_is_kept_and_labelled(self):
        ev = _trade(16, 20)
        assert ev["calendar_state"] == HO.IN_HALT
        assert ev["raw"]["price"] == 30078.0

    def test_it_reaches_the_matrix_and_the_verdict(self):
        matrix = HO.minute_matrix(events=[_trade(16, 20, volume=7)],
                                  bars=[_bar(16, 20)], window=WINDOW)
        row = [r for r in matrix if r["trade_events"]][0]
        assert row["calendar_state"] == HO.IN_HALT
        assert row["trade_volume"] == 7.0
        verdict = HO.adjudicate(matrix)
        assert verdict["case"] == HO.CASE_D_TRADES_DURING_HALT
        assert verdict["halt_trade_events"] == 1

    def test_case_D_does_not_retire_the_inference(self):
        """Trades during a halt is a BIGGER problem, not a licence to conclude."""
        verdict = HO.adjudicate(HO.minute_matrix(events=[_trade(16, 20)],
                                                 bars=[_bar(16, 20)], window=WINDOW))
        assert HO.prohibits_trade_opportunity_inference(verdict) is False


# ── adjudication state machine ────────────────────────────────────────────────

class TestAdjudication:
    def _halt_matrix(self, events, bars):
        return HO.minute_matrix(events=events, bars=bars, window=WINDOW)

    def test_case_B_quotes_but_no_trades_with_bars(self):
        m = self._halt_matrix([_quote(16, 20), _quote(16, 21)],
                              [_bar(16, 20), _bar(16, 21)])
        v = HO.adjudicate(m)
        assert v["case"] == HO.CASE_B_QUOTES_ONLY
        assert v["halt_trade_events"] == 0
        assert v["halt_history_bars"] == 2
        assert HO.prohibits_trade_opportunity_inference(v) is True

    def test_case_C_silence_on_both_live_streams_with_bars(self):
        m = self._halt_matrix([], [_bar(16, h) for h in range(15, 30)])
        v = HO.adjudicate(m)
        assert v["case"] == HO.CASE_C_INDEPENDENT_SERIES
        assert v["halt_history_bars"] == 15
        assert HO.prohibits_trade_opportunity_inference(v) is True

    def test_no_bars_is_inconclusive_not_a_finding(self):
        v = HO.adjudicate(self._halt_matrix([], []))
        assert v["case"] == HO.INCONCLUSIVE
        assert HO.prohibits_trade_opportunity_inference(v) is False

    def test_an_unobserved_window_proves_nothing(self):
        v = HO.adjudicate([])
        assert v["case"] == HO.NOT_OBSERVED
        assert HO.prohibits_trade_opportunity_inference(v) is False

    def test_pre_and_post_halt_activity_does_not_decide_the_case(self):
        """Only IN_HALT minutes may adjudicate the halt."""
        m = self._halt_matrix([_trade(16, 12), _trade(16, 33)],
                              [_bar(16, h) for h in range(15, 30)])
        v = HO.adjudicate(m)
        assert v["case"] == HO.CASE_C_INDEPENDENT_SERIES
        assert v["halt_trade_events"] == 0


# ── matrix construction ───────────────────────────────────────────────────────

class TestMinuteMatrix:
    def test_an_absent_minute_is_a_row_not_a_missing_key(self):
        m = HO.minute_matrix(events=[], bars=[], window=WINDOW,
                             first_minute=_et(16, 10), last_minute=_et(16, 35))
        assert len(m) == 25
        assert all(r["history_bar_present"] is False for r in m)

    def test_history_bar_fields_are_carried_verbatim(self):
        m = HO.minute_matrix(events=[], bars=[_bar(16, 20, volume=1155.0)],
                             window=WINDOW)
        row = [r for r in m if r["history_bar_present"]][0]
        assert (row["history_open"], row["history_high"], row["history_low"],
                row["history_close"], row["history_volume"]) == (
                    30078.0, 30081.25, 30073.0, 30073.25, 1155.0)

    def test_it_accepts_the_canonical_store_field_names_too(self):
        m = HO.minute_matrix(events=[], bars=[{"timestamp": _et(16, 20).isoformat(),
                                               "open": 1.0, "high": 2.0, "low": 0.5,
                                               "close": 1.5, "volume": 9.0}],
                             window=WINDOW)
        assert [r for r in m if r["history_bar_present"]][0]["history_volume"] == 9.0

    def test_rows_are_ordered_by_minute(self):
        m = HO.minute_matrix(events=[_trade(16, 25), _trade(16, 16)], bars=[],
                             window=WINDOW)
        assert [r["minute"] for r in m] == sorted(r["minute"] for r in m)


# ── §4 zero write authority ───────────────────────────────────────────────────

class TestZeroWriteAuthority:
    def test_the_observer_tool_contains_no_broker_write_call(self):
        import ast
        path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                            "tools", "topstepx_halt_observer.py")
        tree = ast.parse(open(path, encoding="utf-8").read())
        called = {ast.unparse(n.func) for n in ast.walk(tree) if isinstance(n, ast.Call)}
        forbidden = ("place_order", "cancel_order", "modify_order", "close_position",
                     "partial_close", "flatten", "ExecutionRunner", "mint_token",
                     "gated_submit", "build_runner")
        offenders = [c for c in called if any(f in c for f in forbidden)]
        assert offenders == [], offenders

    def test_it_names_no_write_endpoint_anywhere(self):
        path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                            "tools", "topstepx_halt_observer.py")
        src = open(path, encoding="utf-8").read()
        for endpoint in ("/api/Order/place", "/api/Order/modify", "/api/Order/cancel",
                         "/api/Position/closeContract"):
            assert endpoint not in src

    def test_it_runs_on_the_write_incapable_session(self):
        import ast
        path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                            "tools", "topstepx_halt_observer.py")
        tree = ast.parse(open(path, encoding="utf-8").read())
        constructed = {ast.unparse(n.func) for n in ast.walk(tree) if isinstance(n, ast.Call)}
        assert "TopstepXReadOnlySession" in constructed
        assert "TopstepXLiveSession" not in constructed

    def test_the_read_only_session_proves_absence_rather_than_returning_empty(self):
        """`assert_no_write_surface` RAISES on violation and returns what it checked.

        Pinned because the natural misreading -- treating the returned list as
        "what went wrong" -- reports a clean session as a failing one. The tool
        made exactly that mistake before this test existed.
        """
        from broker.topstepx_readonly import (
            ReadOnlyViolation, TopstepXReadOnlySession)
        s = TopstepXReadOnlySession("u", "k")
        checked = s.assert_no_write_surface()
        assert "place_order" in checked and "close_position" in checked
        s.place_order = lambda *a, **k: None          # simulate a future regression
        with pytest.raises(ReadOnlyViolation):
            s.assert_no_write_surface()


# ── observer collection behaviour ─────────────────────────────────────────────

class TestObserverCollection:
    def _observer(self):
        sys.path.insert(0, os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "tools"))
        from topstepx_halt_observer import HaltObserver
        return HaltObserver(contract_id="CON.F.US.MNQ.U26", window=WINDOW,
                            clock=lambda: _et(16, 20))

    def test_it_unwraps_the_signalr_argument_envelope(self):
        obs = self._observer()
        obs.on_trade(["CON.F.US.MNQ.U26", {"price": 30078.0, "volume": 2,
                                           "timestamp": _et(16, 20).isoformat()}])
        assert obs.counts()["trade"] == 1
        assert obs.events[0]["calendar_state"] == HO.IN_HALT

    def test_it_accepts_a_batched_list_payload(self):
        obs = self._observer()
        obs.on_trade(["CON.F.US.MNQ.U26",
                      [{"price": 1.0, "volume": 1, "timestamp": _et(16, 20).isoformat()},
                       {"price": 2.0, "volume": 1, "timestamp": _et(16, 21).isoformat()}]])
        assert obs.counts()["trade"] == 2

    def test_an_unreadable_payload_is_counted_not_silently_dropped(self):
        obs = self._observer()
        obs.on_trade(["CON.F.US.MNQ.U26", "garbage"])
        assert obs.counts() == {"trade": 0, "quote": 0, "dropped_unparsable": 1}

    def test_trades_and_quotes_land_in_different_families(self):
        obs = self._observer()
        obs.on_trade(["c", {"price": 1.0, "timestamp": _et(16, 20).isoformat()}])
        obs.on_quote(["c", {"bestBid": 1.0, "bestAsk": 1.25,
                            "timestamp": _et(16, 20).isoformat()}])
        assert obs.counts()["trade"] == 1 and obs.counts()["quote"] == 1
