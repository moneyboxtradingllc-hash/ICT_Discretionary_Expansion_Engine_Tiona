"""LUNA-CROSS-SESSION-PO3-CONTEXT-1 — what the night already did, and what that
is never allowed to decide.

THE GAP THIS CLOSES. `overnight_high`, `london_high` and their siblings were
valid objective kinds that NO module computed — vocabulary Luna could speak and
nothing could price. `session_engine` labels 04:00-20:00 ET and calls the rest
"closed", so Asia and London were not concepts at all, while the durable tape
carried full 23-hour coverage nobody read. At 09:30 the organism looked back 300
minutes: enough for premarket, blind to London, nowhere near Asia.

WHAT IS ASSERTED HERE, in order of how much it matters:

  1. STRUCTURAL NON-INTERFERENCE. `session_po3` output is identical whether
     context is absent, present, screaming bullish or screaming bearish. Not
     "we checked and it didn't change" — `derive()` has no parameter through
     which it could. C13-C15.
  2. EXACT COVERAGE. One missing venue-expected minute is enough to refuse the
     whole window. No ratio, no interpolation, no shrinking. C1-C4, C10, C11.
  3. HONEST ABSENCE. NOT_YET_STARTED and UNAVAILABLE_HISTORY publish no facts —
     not zeroes, not nulls that read as values. C9.
  4. The windows are lenses, not a partition. C5-C8.
  5. The deep-history bound is PROVEN, not asserted by comment. C17.

No trade outcome is consulted anywhere in this file.
"""
from __future__ import annotations

import datetime as dt
import os
import sys

import pytest
import pytz

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))

import market_data.session_context as SC                          # noqa: E402
import market_data.venue_calendar as VC                           # noqa: E402
from market_data.session_context import (                         # noqa: E402
    AVAILABLE, IN_PROGRESS, NOT_YET_STARTED, UNAVAILABLE_HISTORY,
    brain_block, derive, trading_day,
)

ET = pytz.timezone("America/New_York")

#: An ordinary Wednesday whose whole CME day sits inside verified authority.
DAY = "2026-09-02"
DAY_OPEN = "2026-09-01T18:00:00"          # 18:00 ET the previous evening


def et(s: str) -> dt.datetime:
    return ET.localize(dt.datetime.fromisoformat(s))


def tape(start_et: str = DAY_OPEN, minutes: int = 1199, *, drop=(), step=1.5):
    """Settled 1m bars from the CME day open. `drop` removes minute offsets."""
    out, t, px = [], et(start_et), 29000.0
    for i in range(minutes):
        px += (step if i % 3 else -1.0)
        if i in drop:
            continue
        out.append({"timestamp": (t + dt.timedelta(minutes=i)).isoformat(),
                    "open": px - 0.5, "high": px + 1.0, "low": px - 1.5,
                    "close": px, "volume": 10})
    return out


def code_identifiers(module_relpath: str) -> set:
    """Every NAME the module's CODE uses -- imports, attributes, calls, literals.

    STRUCTURAL, NOT TEXTUAL. The first version of the guards below grepped the
    raw source and flagged the word "risk" inside a docstring saying this module
    never reads risk, and "delta" inside `timedelta`. A guard that cannot tell a
    call from a sentence about a call produces false alarms, and a false alarm on
    a safety test is how the test gets weakened later. (The same lesson
    `test_cadence_authority_assumptions` already paid for.)
    """
    import ast
    tree = ast.parse(open(os.path.join(ROOT, *module_relpath.split("/")),
                          encoding="utf-8").read())
    names = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Name):
            names.add(node.id.lower())
        elif isinstance(node, ast.Attribute):
            names.add(node.attr.lower())
        elif isinstance(node, ast.FunctionDef):
            names.add(node.name.lower())
        elif isinstance(node, (ast.Import, ast.ImportFrom)):
            if isinstance(node, ast.ImportFrom) and node.module:
                names.add(node.module.lower())
            for a in node.names:
                names.add(a.name.lower())
        elif isinstance(node, ast.Constant) and isinstance(node.value, str):
            if len(node.value) < 60:          # a label, not prose
                names.add(node.value.lower())
    return names


def ctx(state, name):
    return state["contexts"][name]


# ── the day boundary ──────────────────────────────────────────────────────────

class TestTheTradingDay:
    def test_the_evening_belongs_to_the_next_trading_day(self):
        assert trading_day(et("2026-09-01T21:00:00")) == "2026-09-02"

    def test_the_morning_belongs_to_its_own_date(self):
        assert trading_day(et("2026-09-02T09:30:00")) == "2026-09-02"

    def test_the_boundary_is_seventeen_hundred(self):
        assert trading_day(et("2026-09-02T16:59:00")) == "2026-09-02"
        assert trading_day(et("2026-09-02T17:00:00")) == "2026-09-03"

    def test_the_day_identity_comes_from_the_venue_calendar(self):
        """One owner for 'when does the day turn over'. If venue_calendar's
        constants move, this module must move with them rather than holding a
        second opinion."""
        assert SC.DAY_START_HOUR == VC.WEEKLY_OPEN_HOUR == 18
        assert SC.DAY_END_HOUR == VC.WEEKLY_CLOSE_HOUR == 17
        state = derive(settled_1m=tape())
        assert state["cme_trading_day"]["source"] == "market_data.venue_calendar"
        assert state["cme_trading_day"]["start"].startswith("2026-09-01T18:00")
        assert state["cme_trading_day"]["end"].startswith("2026-09-02T17:00")


# ── C1 — complete coverage ────────────────────────────────────────────────────

class TestC1_FullCoverage:
    def test_every_context_is_available_on_a_complete_day(self):
        state = derive(settled_1m=tape())
        for name in SC.CONTEXT_NAMES:
            assert ctx(state, name)["status"] == AVAILABLE, name

    def test_available_carries_exact_coverage_arithmetic(self):
        c = ctx(derive(settled_1m=tape()), "ASIA_CONTEXT")["coverage"]
        assert c["missing_bars"] == 0
        assert c["expected_bars"] == c["observed_bars"] > 0

    def test_available_carries_real_facts(self):
        f = ctx(derive(settled_1m=tape()), "LONDON_SESSION")["facts"]
        assert f["high"] > f["low"]
        assert f["range"] == round(f["high"] - f["low"], 4)
        assert f["directional_delivery"] in ("bullish", "bearish", "balanced")
        assert f["balanced_or_expanded"] in ("balanced", "expanded")

    def test_the_windows_are_the_owner_defined_ones(self):
        state = derive(settled_1m=tape())
        got = {n: (ctx(state, n)["window"]["start_et"],
                   ctx(state, n)["window"]["end_et"]) for n in SC.CONTEXT_NAMES}
        assert got == {"ASIA_CONTEXT": ("20:00", "00:00"),
                       "LONDON_KILLZONE": ("02:00", "05:00"),
                       "LONDON_SESSION": ("03:00", "11:30"),
                       "NY_PREMARKET": ("04:00", "09:30")}

    def test_asia_starts_on_the_previous_calendar_day(self):
        w = ctx(derive(settled_1m=tape()), "ASIA_CONTEXT")["window"]
        assert w["starts_previous_day"] is True
        assert w["start"].startswith("2026-09-01T20:00")
        assert w["end"].startswith("2026-09-02T00:00")


# ── C2 / C4 / C11 — exact coverage refuses fragments ──────────────────────────

class TestC2_PartialHistoryIsRefused:
    def test_asia_from_2200_is_not_an_asia_range(self):
        """THE HEADLINE REFUSAL. Two of the four Asia hours are on disk. A
        22:00-00:00 high/low is a real fact about two hours and a lie about
        Asia."""
        state = derive(settled_1m=tape("2026-09-01T22:00:00", 700))
        asia = ctx(state, "ASIA_CONTEXT")
        assert asia["status"] == UNAVAILABLE_HISTORY
        assert asia["facts"] is None
        assert asia["coverage"]["missing_bars"] > 0

    def test_C4_london_session_with_history_from_0430_is_refused(self):
        state = derive(settled_1m=tape("2026-09-02T04:30:00", 300))
        london = ctx(state, "LONDON_SESSION")
        assert london["status"] == UNAVAILABLE_HISTORY
        assert london["facts"] is None

    def test_one_missing_minute_is_enough(self):
        """No threshold. 1 of 241 absent refuses the window exactly as 200 would
        — which is the whole reason the venue-calendar horizon had to be fixed
        before this unit could exist."""
        full = derive(settled_1m=tape())
        assert ctx(full, "ASIA_CONTEXT")["status"] == AVAILABLE
        holed = derive(settled_1m=tape(drop=(150,)))     # one Asia minute
        asia = ctx(holed, "ASIA_CONTEXT")
        assert asia["status"] == UNAVAILABLE_HISTORY
        assert asia["coverage"]["missing_bars"] == 1
        assert asia["coverage"]["first_missing"]
        assert asia["facts"] is None

    def test_C11_a_cold_machine_degrades_honestly(self):
        state = derive(settled_1m=tape("2026-09-02T08:00:00", 120))
        statuses = {n: ctx(state, n)["status"] for n in SC.CONTEXT_NAMES}
        assert UNAVAILABLE_HISTORY in statuses.values()
        for name, s in statuses.items():
            if s == UNAVAILABLE_HISTORY:
                assert ctx(state, name)["facts"] is None, name

    def test_no_interpolation_or_window_shrinking_exists(self):
        names = code_identifiers("src/market_data/session_context.py")
        for banned in ("interpolate", "forward_fill", "ffill", "fillna",
                       "synthesize", "threshold", "tolerance", "coverage_ratio"):
            assert banned not in names, banned


# ── C3 — in progress is usable ────────────────────────────────────────────────

class TestC3_InProgress:
    def _at_0930(self):
        """The CME day open through 09:29 ET — the real question at the bell."""
        return derive(settled_1m=tape(minutes=930))

    def test_london_session_is_in_progress_at_the_open(self):
        london = ctx(self._at_0930(), "LONDON_SESSION")
        assert london["status"] == IN_PROGRESS
        assert london["coverage"]["window_complete"] is False

    def test_in_progress_publishes_causal_facts(self):
        """Waiting until 11:30 would make London useless at 09:30, which is the
        only moment it is being asked about."""
        london = ctx(self._at_0930(), "LONDON_SESSION")
        assert london["facts"]["high"] > london["facts"]["low"]
        assert london["coverage"]["as_of"]

    def test_facts_stop_at_as_of(self):
        early = ctx(derive(settled_1m=tape(minutes=800)), "LONDON_SESSION")
        later = ctx(self._at_0930(), "LONDON_SESSION")
        assert early["coverage"]["as_of"] < later["coverage"]["as_of"]
        assert early["facts"]["bars"] < later["facts"]["bars"]

    def test_a_completed_window_is_available_not_in_progress(self):
        assert ctx(self._at_0930(), "ASIA_CONTEXT")["status"] == AVAILABLE
        assert ctx(self._at_0930(), "LONDON_KILLZONE")["status"] == AVAILABLE


# ── C9 — nothing has happened yet ─────────────────────────────────────────────

class TestC9_NotYetStarted:
    def test_a_window_that_has_not_begun_publishes_no_facts(self):
        state = derive(settled_1m=tape(minutes=200))       # through ~21:20 ET
        for name in ("LONDON_KILLZONE", "LONDON_SESSION", "NY_PREMARKET"):
            block = ctx(state, name)
            assert block["status"] == NOT_YET_STARTED, name
            assert block["facts"] is None, name
            assert block["expansion"] is None, name
            assert block["coverage"] is None, name

    def test_absence_is_never_a_zero(self):
        block = ctx(derive(settled_1m=tape(minutes=200)), "NY_PREMARKET")
        assert block["facts"] is not {}
        assert block["facts"] is None
        assert block["reason"]


# ── C5-C8 — lenses, not a partition ───────────────────────────────────────────

class TestOverlapAndExclusion:
    def test_C5_killzone_and_session_overlap_without_containment(self):
        """THE POINT OF PUBLISHING BOTH. 03:00-05:00 belongs to each of them,
        02:00-03:00 belongs only to the killzone, and 05:00-11:30 only to the
        session. Neither is a subset of the other, so neither can substitute for
        the other -- which is exactly why calling 02:00-05:00 "the London
        session" would have been wrong."""
        state = derive(settled_1m=tape())
        kz, ls = ctx(state, "LONDON_KILLZONE"), ctx(state, "LONDON_SESSION")
        wk, wl = kz["window"], ls["window"]
        assert wk["start"] < wl["start"], "killzone starts before the session"
        assert wk["end"] < wl["end"], "killzone ends before the session"
        assert wl["start"] < wk["end"], "and they still overlap"
        assert kz["coverage"]["expected_bars"] < ls["coverage"]["expected_bars"]
        # Each therefore sees price the other never does.
        assert kz["facts"]["low"] < ls["facts"]["low"] or             kz["facts"]["high"] > ls["facts"]["high"]

    def test_C6_london_and_premarket_overlap(self):
        """04:00-05:00 ET belongs to the killzone, the session AND premarket.
        All three report it; none of them owns it."""
        state = derive(settled_1m=tape())
        for a, b in (("LONDON_KILLZONE", "NY_PREMARKET"),
                     ("LONDON_SESSION", "NY_PREMARKET")):
            wa, wb = ctx(state, a)["window"], ctx(state, b)["window"]
            assert wa["start"] < wb["end"] and wb["start"] < wa["end"]

    def test_no_partition_function_exists(self):
        src = open(os.path.join(ROOT, "src", "market_data", "session_context.py"),
                   encoding="utf-8").read().lower()
        for banned in ("def which_session", "def session_of", "def owner_of",
                       "first_match", "def classify_bar"):
            assert banned not in src, banned

    def test_C7_C8_excluded_hours_are_named_not_absorbed(self):
        state = derive(settled_1m=tape())
        spans = {(e["start_et"], e["end_et"]): e for e in state["excluded_spans"]}
        assert ("18:00", "20:00") in spans
        assert ("00:00", "02:00") in spans
        for e in spans.values():
            assert e["assigned_to"] is None
            assert e["observed_bars"] > 0, "the excluded bars are real trading"

    def test_asia_does_not_mean_all_overnight(self):
        """A 20:00 start means 18:00-20:00 is NOT Asia. If Asia's expected count
        ever covers the reopen, the window silently grew."""
        asia = ctx(derive(settled_1m=tape()), "ASIA_CONTEXT")
        assert asia["window"]["start"].endswith("18:00:00-04:00") is False
        assert asia["window"]["start"].startswith("2026-09-01T20:00")


# ── C10 — special dates fail closed ───────────────────────────────────────────

class TestC10_SpecialDateFailsClosed:
    def test_a_holiday_window_refuses_every_context(self):
        """2026-09-07 is Labor Day: KNOWN_SPECIAL with exact hours deliberately
        not encoded. Nominal arithmetic must not stand in for cadence."""
        state = derive(settled_1m=tape("2026-09-06T18:00:00", 1199))
        assert state["trading_day"] == "2026-09-07"
        for name in SC.CONTEXT_NAMES:
            block = ctx(state, name)
            if block["status"] == NOT_YET_STARTED:
                continue
            assert block["status"] == UNAVAILABLE_HISTORY, (name, block["status"])
            assert block["facts"] is None, name

    def test_the_refusal_names_cadence_not_missing_bars(self):
        state = derive(settled_1m=tape("2026-09-06T18:00:00", 1199))
        block = ctx(state, "ASIA_CONTEXT")
        assert "cadence" in block["reason"].lower()

    def test_nominal_under_unknown_schedule_is_not_used_as_proof(self):
        src = open(os.path.join(ROOT, "src", "market_data", "session_context.py"),
                   encoding="utf-8").read()
        assert "NOMINAL_UNDER_UNKNOWN_SCHEDULE" not in src


# ── C13-C15 — SESSION PO3 NON-INTERFERENCE ────────────────────────────────────

class TestSessionPo3IsUnreachable:
    """The strongest claim in the unit, and the reason Option B was chosen over
    threading context into the phase as a 'non-deciding input'. A promise
    enforced by a test can be weakened by editing the test. A function with no
    parameter cannot be passed an argument."""

    def test_derive_has_no_parameter_for_cross_session_context(self):
        import inspect

        from structure.session_po3 import derive as po3_derive
        params = set(inspect.signature(po3_derive).parameters)
        assert params == {"settled_1m", "po3", "liquidity", "structure", "authority"}

    def test_session_po3_does_not_import_session_context(self):
        src = open(os.path.join(ROOT, "src", "structure", "session_po3.py"),
                   encoding="utf-8").read()
        assert "session_context" not in src
        assert "venue_calendar" not in src

    @pytest.mark.parametrize("step,label", [(6.0, "violent bullish context"),
                                            (-6.0, "violent bearish context"),
                                            (0.1, "flat context")])
    def test_C13_C15_the_phase_is_identical_whatever_the_night_did(self, step, label):
        from data_feed.timeframe_builder import build_timeframes
        from market_data.snapshot_builder import build_snapshot
        deep = tape(step=step)
        scan = tape()[-300:]                      # the SAME scan window each time
        with_ctx = build_snapshot(build_timeframes(scan), symbol="MNQ", deep_1m=deep)
        without = build_snapshot(build_timeframes(scan), symbol="MNQ")
        assert with_ctx["session_po3"] == without["session_po3"], label

    def test_the_context_really_did_change_between_those_runs(self):
        """Non-vacuity: if context were identical across those parametrisations
        the equality above would prove nothing."""
        bull = derive(settled_1m=tape(step=6.0))
        bear = derive(settled_1m=tape(step=-6.0))
        assert (ctx(bull, "LONDON_SESSION")["facts"]["directional_delivery"]
                != ctx(bear, "LONDON_SESSION")["facts"]["directional_delivery"])

    def test_context_cannot_reach_entry_authority(self):
        from data_feed.timeframe_builder import build_timeframes
        from market_data.snapshot_builder import build_snapshot
        snap = build_snapshot(build_timeframes(tape()[-300:]), symbol="MNQ",
                              deep_1m=tape(step=6.0))
        assert "session_context" not in str(snap["session_po3"])


# ── C12 / C16 / C17 — depth, parity and the bound ─────────────────────────────

class TestDeepHistory:
    def test_C17_the_bound_covers_the_earliest_required_bar(self):
        """PROVEN, NOT ASSERTED. The earliest bar any context can need is the
        CME day open (18:00 ET the previous evening); the latest moment
        production decides anything is PRODUCTION_WINDOW_END. Counted with the
        venue calendar's own expected-slot enumeration."""
        from broker.topstepx_session_authorization import PRODUCTION_WINDOW_END
        worst = 0
        for day, prev in (("2026-09-02", "2026-09-01"),      # ordinary midweek
                          ("2026-08-24", "2026-08-23")):     # Monday, Sunday open
            lo = et(f"{prev}T18:00:00")
            hi = et(f"{day}T{PRODUCTION_WINDOW_END}:00")
            worst = max(worst, len(VC.expected_buckets(lo, hi, 1)))
        assert worst > 0
        assert SC.DEEP_HISTORY_BARS >= worst, (
            f"DEEP_HISTORY_BARS={SC.DEEP_HISTORY_BARS} cannot reach the CME day "
            f"open from {PRODUCTION_WINDOW_END} ET; {worst} bars are required")

    def test_the_bound_is_not_wastefully_large(self):
        """A bound nobody can justify is a bound nobody will maintain."""
        assert SC.DEEP_HISTORY_BARS <= 2000

    def test_C16_the_ordinary_scan_window_is_untouched(self):
        from broker.topstepx_production_loop import ProductionLoop
        assert ProductionLoop.HISTORY_HORIZON_MINUTES == 300
        assert ProductionLoop.HISTORY_MINIMUM_BARS == 60

    def test_C12_the_same_bars_give_the_same_context(self):
        """Live, restart and replay differ in how they ACQUIRE bars, not in what
        the bars mean. Same series, same answer, every time."""
        bars = tape()
        first = derive(settled_1m=bars)
        second = derive(settled_1m=list(bars))
        assert first == second

    def test_depth_may_differ_but_meaning_may_not(self):
        deep = derive(settled_1m=tape())
        shallow = derive(settled_1m=tape()[-300:])
        assert ctx(deep, "ASIA_CONTEXT")["status"] == AVAILABLE
        assert ctx(shallow, "ASIA_CONTEXT")["status"] == UNAVAILABLE_HISTORY
        assert ctx(shallow, "ASIA_CONTEXT")["facts"] is None

    def test_absent_deep_history_is_not_an_error(self):
        state = derive(settled_1m=[])
        assert state["contexts"] == {}
        assert state["reason"]


# ── C18 — what Luna is shown ──────────────────────────────────────────────────

class TestC18_BrainPublication:
    def test_available_contexts_reach_the_brain_with_facts(self):
        block = brain_block(derive(settled_1m=tape()))
        assert block["available"] is True
        for name in SC.CONTEXT_NAMES:
            row = block["contexts"][name]
            assert row["status"] == AVAILABLE
            assert row["high"] is not None and row["low"] is not None

    def test_unavailable_contexts_reach_the_brain_as_reasons_not_values(self):
        block = brain_block(derive(settled_1m=tape("2026-09-01T22:00:00", 700)))
        asia = block["contexts"]["ASIA_CONTEXT"]
        assert asia["status"] == UNAVAILABLE_HISTORY
        assert "high" not in asia and "low" not in asia
        assert asia["reason"]

    def test_the_block_states_it_authorises_nothing(self):
        block = brain_block(derive(settled_1m=tape()))
        assert "does not authorize" in block["note"]

    def test_the_payload_carries_it_beside_the_phase(self):
        from ai_brain.brain_input import _session_context_block
        from data_feed.timeframe_builder import build_timeframes
        from market_data.snapshot_builder import build_snapshot
        snap = build_snapshot(build_timeframes(tape()[-300:]), symbol="MNQ",
                              deep_1m=tape())
        block = _session_context_block(snap)
        assert block["available"] is True
        assert set(block["contexts"]) == set(SC.CONTEXT_NAMES)

    def test_absence_is_stated_not_faked(self):
        from ai_brain.brain_input import _session_context_block
        assert _session_context_block({})["available"] is False


# ── excursions ────────────────────────────────────────────────────────────────

class TestExcursionsAgainstPriorContext:
    def test_each_context_names_the_one_it_compares_against(self):
        state = derive(settled_1m=tape())
        assert ctx(state, "ASIA_CONTEXT")["excursions_vs_prior_context"][
            "prior_context"] is None
        assert ctx(state, "LONDON_SESSION")["excursions_vs_prior_context"][
            "prior_context"] == "ASIA_CONTEXT"
        assert ctx(state, "NY_PREMARKET")["excursions_vs_prior_context"][
            "prior_context"] == "LONDON_SESSION"

    def test_a_rising_tape_takes_the_prior_high(self):
        e = ctx(derive(settled_1m=tape(step=4.0)),
                "LONDON_SESSION")["excursions_vs_prior_context"]
        assert e["comparable"] is True
        assert e["took_prior_high"] is True

    def test_an_uncomparable_prior_says_so(self):
        e = ctx(derive(settled_1m=tape("2026-09-01T22:00:00", 700)),
                "LONDON_SESSION")["excursions_vs_prior_context"]
        assert e["comparable"] is False
        assert "ASIA_CONTEXT" in e["reason"]


# ── the module's own limits ───────────────────────────────────────────────────

class TestTheProducerStaysInItsLane:
    def test_no_wall_clock_decides_a_market_fact(self):
        src = open(os.path.join(ROOT, "src", "market_data", "session_context.py"),
                   encoding="utf-8").read()
        assert "datetime.now" not in src and "utcnow" not in src
        assert "date.today" not in src

    def test_it_touches_no_risk_or_execution_surface(self):
        """Imports are the honest test: a module that cannot reach risk, broker
        or account code cannot consult it however it is later edited."""
        import ast
        tree = ast.parse(open(os.path.join(ROOT, "src", "market_data",
                                           "session_context.py"),
                              encoding="utf-8").read())
        modules = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module:
                modules.add(node.module)
            elif isinstance(node, ast.Import):
                modules.update(a.name for a in node.names)
        forbidden = [m for m in modules
                     if m.split(".")[0] in ("risk", "broker", "execution_gate",
                                            "paper_execution", "trade_intent")]
        assert forbidden == [], forbidden
        names = code_identifiers("src/market_data/session_context.py")
        for banned in ("risk_usd", "contracts", "max_trades", "position_size",
                       "account_id", "order_id"):
            assert banned not in names, banned

    def test_it_does_not_read_htf_memory(self):
        """HtfMemoryEngine's 'previous session' is an ET CALENDAR day, which is
        the debt this unit deliberately does not inherit."""
        src = open(os.path.join(ROOT, "src", "market_data", "session_context.py"),
                   encoding="utf-8").read()
        assert "htf_memory" not in src and "HtfMemory" not in src

    def test_it_never_raises_on_malformed_input(self):
        for bad in (None, [], [None, 3, "x"], [{"timestamp": "nope"}],
                    [{"timestamp": "2026-09-02T10:00:00-04:00"}]):
            state = derive(settled_1m=bad)
            assert state["schema"] == SC.SCHEMA

    def test_volume_profile_was_not_started(self):
        names = code_identifiers("src/market_data/session_context.py")
        for banned in ("volume_at_price", "volume_profile", "poc", "value_area",
                       "vah", "val", "buy_volume", "sell_volume", "footprint",
                       "gatewaytrade"):
            assert banned not in names, banned
