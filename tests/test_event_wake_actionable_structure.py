"""EVENT-WAKE-ACTIONABLE-STRUCTURE-1 — nobody asked her while price was there.

2026-08-21. The bullish 1m FVG 29243.00-29251.25 completed when the 10:23 candle
settled at ~10:24:00, and price traded into it during that same minute (low
29249.50). The scans around it were 10:23:51 -- before the gap existed -- and
10:25:11, by which time the executable ask was 29251.50, back above the zone.

    ENTRY_TRIGGERED     YES, in the market
    DECISION_PRESENTED  NO

Cause, measured over n=151: the loop slept `time.sleep(interval)` AFTER the work,
so a 19s Luna call produced a 79s start-to-start interval against a ~60s live
window. Everything beneath timing was already repaired by the preceding units.

    THE REGISTRY HAS ZERO EXPOSURE AUTHORITY.

It answers exactly one question -- "should the bot look again?" -- and after
every wake the UNCHANGED `scan_once()` re-proves the trade through canonical
snapshot, toolbox, catalog, Luna and risk. A wake may lawfully end in stand_down
or refusal. FALSE-POSITIVE WAKE IS ALLOWED; FALSE-POSITIVE AUTHORIZATION IS NOT.

ONE DEFINITION OF SETTLED. The registry does not rebuild
`normalize -> temporal_status -> retain`; it calls the same `annotated_timeframe`
helper `build_snapshot` calls. Two implementations would have drifted into
"wake path: settled / production path: provisional" on the same bar, and
`fvg_execution_instances` filters on precisely that field.
"""
from __future__ import annotations

import copy
import json
import os
import sys
import threading
import time

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))

from live_scan.wake_registry import (INSIDE, OUTSIDE,                 # noqa: E402
                                     WAKE_ARMED_INSIDE, WAKE_ENTERED,
                                     WakeRegistry, executable_for)
from market_data.snapshot_builder import annotated_timeframe          # noqa: E402

ARCHIVE = os.path.join(ROOT, "data", "ai_brain")
SPECIMEN = "20260821_102511_MNQ.json"
CONTRACT = "CON.F.US.MNQ.U26"
GAP_LOW, GAP_HIGH = 29243.00, 29251.25
GAP_ID = f"FVG:{CONTRACT}:1m:2026-08-21T14:23:00+00:00"


def names_in(obj) -> set:
    """Every identifier the CODE actually references — docstrings excluded.

    Six separate tests in this repo have failed on a docstring that named the
    very thing it was declaring it would not use. Prose is not code.
    """
    import ast
    import inspect
    import textwrap
    out = set()
    for node in ast.walk(ast.parse(textwrap.dedent(inspect.getsource(obj)))):
        if isinstance(node, ast.Name):
            out.add(node.id)
        elif isinstance(node, ast.Attribute):
            out.add(node.attr)
        elif isinstance(node, (ast.Import, ast.ImportFrom)):
            out.update(a.name.split(".")[-1] for a in node.names)
            if isinstance(node, ast.ImportFrom) and node.module:
                out.update(node.module.split("."))
    return out


def snap():
    path = os.path.join(ARCHIVE, SPECIMEN)
    if not os.path.exists(path):
        pytest.skip("archived production snapshot absent")
    with open(path, encoding="utf-8") as fh:
        return copy.deepcopy(json.load(fh)["raw_snapshot"])


def by_tf():
    s = snap()
    return {tf: (s["timeframes"].get(tf) or {}).get("recent_candles") or []
            for tf in ("1m", "3m", "5m", "15m")}


#: The 14:23 candle is the one whose settling completes the governing gap.
#: Truncating before it is how "the occurrence did not exist yet" is expressed.
BIRTH_CUT = 89


def tape(n=None):
    """Raw completed 1m bars, optionally truncated to before the gap's birth."""
    bars = [dict(c) for c in by_tf()["1m"]]
    return bars if n is None else bars[:n]


def armed_registry(*, bid=None, ask=None):
    r = WakeRegistry()
    r.refresh(by_tf(), CONTRACT, bid=bid, ask=ask)
    return r


def rows(reg):
    return {row[0]: row for row in reg.armed()}


# ══════════════════════════════════════════════════════════════════════════════
class TestOneDefinitionOfSettled:
    def test_the_registry_uses_the_snapshot_annotator(self):
        import inspect
        src = inspect.getsource(WakeRegistry.annotate)
        assert "annotated_timeframe" in src
        assert "_temporal_status" not in src      # no private re-implementation

    def test_the_annotator_is_pure(self):
        s = snap()
        raw = [dict(c) for c in (s["timeframes"]["1m"]["recent_candles"])]
        before = json.dumps(raw)
        annotated_timeframe(raw, "1m")
        assert json.dumps(raw) == before

    def test_it_is_deterministic(self):
        raw = snap()["timeframes"]["1m"]["recent_candles"]
        assert annotated_timeframe(raw, "1m") == annotated_timeframe(raw, "1m")

    def test_it_touches_no_stateful_tracker(self):
        """AST over the CODE. A text scan matches the docstring, which names
        these precisely to say it does not use them — the trap that has fired
        repeatedly in this repo."""
        assert not names_in(annotated_timeframe) & {
            "swing_tracker", "po3_stability", "expansion_stability",
            "_flip_registry", "run_toolbox", "build_snapshot"}

    def test_empty_input_is_absence_not_a_fabricated_bar(self):
        assert annotated_timeframe([], "1m") == {"last_candle": None,
                                                 "recent_candles": []}


class TestTheRegistryArmsTheSpecimen:
    def test_the_governing_gap_is_armed(self):
        assert GAP_ID in rows(armed_registry())

    def test_it_carries_the_exact_canonical_geometry(self):
        row = rows(armed_registry())[GAP_ID]
        assert row[1] == "bullish"
        assert (row[2], row[3]) == (GAP_LOW, GAP_HIGH)

    def test_only_execution_eligible_occurrences_are_armed(self):
        from toolbox.price_levels import fvg_execution_instances
        ineligible = {o["occurrence_id"]
                      for o in fvg_execution_instances(by_tf()["1m"], "bullish", 1,
                                                       contract=CONTRACT)
                      if o.get("occurrence_id") and not o["execution_eligible"]}
        assert not (ineligible & set(rows(armed_registry())))

    def test_no_contract_arms_nothing(self):
        """Without identity there is no occurrence to watch."""
        r = WakeRegistry()
        r.refresh(by_tf(), None)
        assert r.armed() == ()

    def test_a_refresh_failure_is_survived_not_raised(self):
        r = WakeRegistry()
        out = r.refresh({"1m": "not-candles"}, CONTRACT)
        assert out["refreshed"] is False and out["error"]


class TestArmedWhileAlreadyInside:
    """SPECIMEN A. The gap completed with price ALREADY trading through it."""

    def test_it_wakes_immediately(self):
        r = armed_registry(ask=29249.50, bid=29249.25)
        assert r.trade_wake.is_set()
        assert any(w["occurrence_id"] == GAP_ID
                   and w["reason"] == WAKE_ARMED_INSIDE for w in r.wakes)

    def test_it_does_NOT_wait_for_a_future_re_entry(self):
        """Requiring OUTSIDE->INSIDE after arming would have missed 10:24."""
        assert armed_registry(ask=29249.50).trade_wake.is_set()

    def test_arming_with_price_outside_does_not_wake(self):
        r = armed_registry(ask=29280.00, bid=29279.75)
        assert not any(w.get("reason") == WAKE_ARMED_INSIDE
                       and w["occurrence_id"] == GAP_ID for w in r.wakes)

    def test_the_next_inside_quote_does_not_duplicate_the_wake(self):
        r = armed_registry(ask=29249.50, bid=29249.25)
        r.consume_interaction()
        r.on_quote(bid=29249.25, ask=29249.50)   # seeds episode from initial_inside
        r.on_quote(bid=29249.00, ask=29249.25)   # still inside
        assert not r.trade_wake.is_set()


class TestEpisodeDoctrine:
    @staticmethod
    def outside_first():
        r = armed_registry(ask=29280.00, bid=29279.75)
        r.on_quote(bid=29279.75, ask=29280.00)   # seed OUTSIDE
        r.consume_interaction()
        return r

    @staticmethod
    def ours(fired):
        """Per-OCCURRENCE assertions. The registry arms many gaps at once, so
        the shared flag says only "something fired" -- the doctrine is about
        THIS occurrence."""
        return [f for f in fired if f["occurrence_id"] == GAP_ID]

    def test_outside_to_inside_wakes_once(self):
        r = self.outside_first()
        assert self.ours(r.on_quote(bid=29249.25, ask=29249.50))
        assert r.trade_wake.is_set()

    def test_inside_to_inside_does_not_wake_again(self):
        r = self.outside_first()
        r.on_quote(bid=29249.25, ask=29249.50)
        for _ in range(5):
            assert not self.ours(r.on_quote(bid=29248.00, ask=29248.25))

    def test_exit_then_re_entry_is_a_second_episode(self):
        r = self.outside_first()
        assert self.ours(r.on_quote(bid=29249.25, ask=29249.50))   # in
        assert not self.ours(r.on_quote(bid=29279.75, ask=29280.00))  # out
        assert self.ours(r.on_quote(bid=29249.25, ask=29249.50))   # in again

    def test_episode_identity_is_the_occurrence_id(self):
        r = self.outside_first()
        assert set(r._episode) <= set(rows(r))

    def test_a_removed_occurrence_drops_its_episode_state(self):
        """A stale INSIDE must not suppress the first wake of a later gap that
        happens to reuse the id."""
        r = self.outside_first()
        r.on_quote(bid=29249.25, ask=29249.50)
        r.refresh({"1m": []}, CONTRACT)            # everything disarms
        r.on_quote(bid=29249.25, ask=29249.50)
        assert r._episode == {}


class TestSidedPriceDoctrine:
    def test_bullish_uses_the_ask(self):
        assert executable_for("bullish", 100.0, 101.0) == 101.0

    def test_bearish_uses_the_bid(self):
        assert executable_for("bearish", 100.0, 101.0) == 100.0

    def test_an_unknown_direction_has_no_executable_price(self):
        assert executable_for("sideways", 100.0, 101.0) is None

    @pytest.mark.parametrize("bad", [None, "", "abc", float("nan"), True, False])
    def test_an_unusable_quote_is_not_an_interaction(self, bad):
        """Absence of a price is not proof price is in the zone."""
        r = TestEpisodeDoctrine.outside_first()
        r.on_quote(bid=bad, ask=bad)
        assert not r.trade_wake.is_set()

    def test_a_candle_low_is_not_an_executable_interaction(self):
        """29249.50 was a candle LOW; a buyer pays the ask. Waking on OHLC
        would wake on a price the market never offered."""
        r = TestEpisodeDoctrine.outside_first()
        r.on_quote(bid=29249.50, ask=29260.00)    # ask still ABOVE the zone
        assert not r.trade_wake.is_set()


class TestEventLossAndSingleFlight:
    def test_an_event_raised_mid_flight_survives(self):
        """Level-triggered: set during a scan, still pending after it."""
        r = WakeRegistry()
        r.trade_wake.set()                         # raised "while Luna thought"
        assert r.wait(0.05)["early"] is True       # returns immediately
        assert r.consume_interaction() is True

    def test_the_deadline_is_used_when_nothing_happens(self):
        import time
        r = WakeRegistry()
        t0 = time.monotonic()
        out = r.wait(0.3)
        assert out["woke"] == "deadline" and out["early"] is False
        assert time.monotonic() - t0 >= 0.25

    def test_structure_and_interaction_are_separate_signals(self):
        r = WakeRegistry()
        r.note_bar_closed()
        assert r.wait(0.05)["woke"] == "structure"
        assert r.consume_structure() is True
        assert r.consume_interaction() is False

    def test_many_events_coalesce_into_one_cycle(self):
        r = TestEpisodeDoctrine.outside_first()
        r.on_quote(bid=29249.25, ask=29249.50)
        r.on_quote(bid=29279.75, ask=29280.00)
        r.on_quote(bid=29249.25, ask=29249.50)
        assert r.trade_wake.is_set()
        assert r.consume_interaction() is True
        assert r.consume_interaction() is False    # one bit, not a queue

    def test_the_registry_never_calls_the_brain_or_authorizes(self):
        """AST over the module's real names, not its prose."""
        called = names_in(sys.modules[WakeRegistry.__module__])
        assert not called & {"run_narrative_brain", "build_snapshot", "run_toolbox",
                             "CandidateProducer", "build_bracket", "place_order",
                             "authorized_tool_catalog", "produce"}


class TestPumpThreadBoundary:
    """The provider->registry seam, proven by CALLING it.

    Everything below that greps `inspect.getsource` can only prove that a
    string appears in a file. It cannot prove the branch is reachable, that the
    attribute name matches the one the loop assigns, or that the call survives
    the lock. That is the exact `correct-tested-unreachable` pattern this repo
    has produced five times, so the two load-bearing claims -- "a settled bar
    signals" and "a quote is offered to the registry" -- are proven behaviourally
    here and the source scans are left only as the redundant belt.
    """

    @staticmethod
    def _provider(registry):
        """A real TopstepXDataProvider with no network, no runtime, no disk."""
        from data_feed.topstepx_provider import TopstepXDataProvider
        p = object.__new__(TopstepXDataProvider)
        # PLAIN Lock, exactly as production. An RLock here would silently
        # tolerate a registry call made from INSIDE the lock; production would
        # deadlock on it.
        p._lock = threading.Lock()
        p.last_quote = {}
        p.wake_registry = registry
        p._persist = lambda *a, **k: None
        p._trim = lambda *a, **k: None
        return p

    def test_a_settled_bar_really_does_signal_the_registry(self):
        """`_on_trade` -> `note_bar_closed`, through the real method body."""
        reg = WakeRegistry()
        p = self._provider(reg)
        p.aggregator = type("Agg", (), {
            "ingest_event": lambda self, args: None,
            "roll": lambda self: [{"timestamp": "2026-08-21T14:24:00+00:00"}],
        })()
        assert not reg.structure_birth.is_set()
        p._on_trade([None, {}])
        assert reg.structure_birth.is_set(), "the pump never signalled the registry"

    def test_no_settled_bar_signals_nothing(self):
        """The control: rolling produced nothing, so nothing is worth watching."""
        reg = WakeRegistry()
        p = self._provider(reg)
        p.aggregator = type("Agg", (), {
            "ingest_event": lambda self, args: None,
            "roll": lambda self: [],
        })()
        p._on_trade([None, {}])
        assert not reg.structure_birth.is_set(), "an unsettled tick woke the loop"

    def test_a_quote_really_does_reach_the_registry_sided(self):
        """`_on_quote` -> `on_quote`, with the SIDED prices, outside the lock."""
        reg = WakeRegistry()
        seen = []
        reg.on_quote = lambda bid=None, ask=None: seen.append((bid, ask)) or []
        p = self._provider(reg)
        p._on_quote([None, {"bestBid": 29249.25, "bestAsk": 29249.50}])
        assert seen == [(29249.25, 29249.50)], seen

    def test_a_registry_that_explodes_never_kills_the_feed(self):
        """Watching is an optimisation. It may never cost the market data."""
        reg = WakeRegistry()
        reg.on_quote = lambda **k: (_ for _ in ()).throw(RuntimeError("boom"))
        p = self._provider(reg)
        p._on_quote([None, {"bestBid": 1.0, "bestAsk": 2.0}])       # must not raise
        assert p.last_quote["bestBid"] == 1.0                       # feed still updated

    def test_the_provider_only_signals_on_bar_close(self):
        import inspect
        from data_feed import topstepx_provider as P
        src = inspect.getsource(P.TopstepXDataProvider._on_trade)
        assert "note_bar_closed" in src
        for banned in ("run_narrative_brain", "build_snapshot", "run_toolbox",
                       "refresh(", "produce("):
            assert banned not in src, banned

    def test_the_quote_handler_only_detects(self):
        import inspect
        from data_feed import topstepx_provider as P
        src = inspect.getsource(P.TopstepXDataProvider._on_quote)
        assert "on_quote" in src
        for banned in ("refresh", "build_snapshot", "run_toolbox", "produce("):
            assert banned not in src, banned

    def test_the_provider_defaults_to_no_registry(self):
        """Every existing caller — replay, smoke, tools — is unchanged."""
        import inspect
        from data_feed import topstepx_provider as P
        assert "self.wake_registry = None" in inspect.getsource(P.TopstepXDataProvider.__init__)

    def test_publication_is_lock_guarded_and_the_snapshot_is_immutable(self):
        r = armed_registry()
        published = r.armed()
        assert isinstance(published, tuple)
        assert all(isinstance(row, tuple) for row in published)

    def test_concurrent_reads_during_republish_never_tear(self):
        r = armed_registry()
        stop, seen = threading.Event(), []

        def reader():
            while not stop.is_set():
                seen.append(len({row[0] for row in r.armed()}))

        t = threading.Thread(target=reader, daemon=True)
        t.start()
        for _ in range(40):
            r.refresh(by_tf(), CONTRACT)
            r.refresh({"1m": []}, CONTRACT)
        stop.set(); t.join(timeout=2)
        assert seen, "reader never observed a snapshot"


class TestTheWaitSeam:
    # The fixed-delay-after-work behaviour is pinned BEHAVIOURALLY by
    # `TestTheRealLoopSequencing.test_no_events_waits_the_full_deadline` and
    # `test_repeated_structure_events_cannot_slide_the_deadline`. A source scan
    # for its absence was deleted rather than repaired: the string appears in
    # the comment that explains what the code no longer does, which is the
    # seventh time in this repo that a prose mention has failed an absence
    # assertion. Behaviour is the assertion; text is not.

    def test_a_bar_close_alone_does_not_call_luna(self):
        """The essential difference from bar-close-wake: a settled bar earns a
        pure refresh, not a provider call."""
        src = open(os.path.join(ROOT, "tools", "topstepx_production_session.py"),
                   encoding="utf-8").read()
        i = src.index("wake.consume_structure()")
        assert "refresh_from_bars" in src[i:i + 700]
        assert "scan_once" not in src[i:i + 700]

    def test_the_registry_is_owned_by_the_production_thread(self):
        src = open(os.path.join(ROOT, "tools", "topstepx_production_session.py"),
                   encoding="utf-8").read()
        assert "candles.wake_registry = wake" in src
        assert "WakeRegistry()" in src

    def test_a_registry_failure_never_blocks_a_session(self):
        src = open(os.path.join(ROOT, "tools", "topstepx_production_session.py"),
                   encoding="utf-8").read()
        assert "if wake is None:" in src


class TestTheRealLoopSequencing:
    """DRIVEN THROUGH `run_production_scans`, not through WakeRegistry alone.

    The first implementation of this unit passed 46 component tests and was still
    wrong: a structure-only event fell out of the wait and straight into the next
    `scan_once()`, making every settled bar a Luna call -- Option A wearing
    Option B's clothes. Nothing that inspects the registry, or greps the loop for
    `Event.wait`, can see that. Only running the loop can.

        A bar closing may update what Luna should WATCH.
        It does not, by itself, earn an LLM call.
    """

    INTERVAL = 6.0

    @staticmethod
    def drive(script, *, interval=6.0, scans=2, ask=29249.50, bid=29249.25,
              bars=None, bars_later=None, gate=None, fetch_raises=False, out=None,
              quote_age=0.0, quote_raises=False):
        """Run the real loop; `script` is [(delay_seconds, action), ...].

        `bars` is what `fetch_1m_candles` returns, so the PRODUCTION owner thread
        performs the discovery -- the scripted thread may only signal.

        `bars_later` is what every fetch AFTER the startup bootstrap returns.
        This is how LIVE BIRTH is modelled honestly: the startup tape must not
        already contain the occurrence, or the test would be exercising the
        bootstrap path while claiming to exercise the 10:24 birth path.

        `gate` is (started, release): `scan_once` sets `started` then blocks on
        `release`, making "event raised DURING the scan" deterministic instead
        of a race against a fake that returns instantly.

        `fetch_raises` makes the bar cache unavailable, as on a cold start.
        `out` receives {"registry": ...} so a test can inspect what bootstrap did.
        """
        sys.path.insert(0, os.path.join(ROOT, "tools"))
        # ENV IS PROCESS-GLOBAL. Leaking this fingerprint made
        # `TestArchiveCarriesNoSecrets` search the PROD-20260806 archive for the
        # literal "acct:test" -- which legitimately appears in two archived
        # diffs of test code -- and report a credential leak that did not exist.
        # `load_dotenv` does not override an already-set variable, so a test
        # that sets one and walks away rewrites what every later test treats as
        # the real secret. Restored in `finally`.
        _prior_fp = os.environ.get("TOPSTEPX_ACCOUNT_FINGERPRINT")
        os.environ["TOPSTEPX_ACCOUNT_FINGERPRINT"] = "acct:test"
        import topstepx_production_session as TOOL
        from broker import topstepx_production_loop as PL
        import live_scan.wake_registry as WR

        marks, fetches = [], []
        started = time.monotonic()

        class FakeCycle:
            last_occurrence_persistence_status = "LEDGER_HEALTHY"
            last_occurrence_persistence_error = ""
            retrieval_telemetry = None

        class FakeLoop:
            def __init__(self, **kw):
                self.cycle = FakeCycle()

            def scan_once(self):
                marks.append(time.monotonic() - started)
                if gate is not None and len(marks) == 1:
                    gate[0].set()            # "the scan is now in flight"
                    gate[1].wait(10)         # held open until the event is raised
                return {"outcome": "NO_CANDIDATE", "detail": "",
                        "direction": None, "market_data_timestamp": None}

            def final_flat_state(self):
                return {"flat": True}

        class FakeContract:
            id = CONTRACT

        class FakeSession:
            account = type("A", (), {"id": 1})()

            def open_positions(self):
                return []

            def open_orders(self):
                return []

        class FakeCandles:
            contract = FakeContract()
            last_quote = {"bestBid": bid, "bestAsk": ask}

            def fetch_1m_candles(self, *a, **k):
                fetches.append(time.monotonic() - started)
                if fetch_raises:
                    raise RuntimeError("bar cache unavailable")
                if len(fetches) == 1 or bars_later is None:
                    return list(bars or [])       # fetch 1 IS the bootstrap
                return list(bars_later)

        class FakeCapture:
            """Exactly the attribute surface `from_capture` reads."""
            market_data_age_seconds = quote_age
            best_bid = bid
            best_ask = ask
            last_trade = None
            captured_at = None

        class FakeQuoteProvider:
            def capture(self, volatility_state=None):
                if quote_raises:
                    raise RuntimeError("quote lane broken")
                return FakeCapture()

        class FakePS:
            session_id = ""
            authorization_fingerprint = ""
            retrieval_telemetry = None
            # The REAL `from_capture` / `executable_price` run against this, so
            # `quote_age` is judged by production's own ceiling, not by the test.
            quote_provider = FakeQuoteProvider()

        def runner(reg):
            for delay, action in script:
                time.sleep(delay)
                action(reg)

        # TEST ISOLATION. `run_production_scans` ends by archiving the session
        # tape, and this fake session has no session_id, so every call landed in
        # the SHARED `data/replay_sessions/UNSCOPED/` bucket -- ten writes per
        # run into a real evidence path. The archive is not what this unit
        # certifies, so it is stubbed out rather than redirected.
        import broker.trade_lineage as TL
        real_cls, real_loop, real_store = WR.WakeRegistry, PL.ProductionLoop, TOOL.STORE_DIR
        real_archive = TL.archive_tape
        TL.archive_tape = lambda **k: {"bar_count": 0, "tape_write_ok": None}

        class Spy(real_cls):
            def __init__(self):
                super().__init__()
                if out is not None:
                    out["registry"] = self
                if script:
                    threading.Thread(target=runner, args=(self,), daemon=True).start()

            def bootstrap(self, *a, **k):
                """Snapshot the SEED. The episode map is live state -- a later
                entry quote legitimately moves it to INSIDE, so asserting it at
                the end of a run cannot tell a correct seed from a stale claim."""
                res = super().bootstrap(*a, **k)
                if out is not None:
                    out["bootstrap_episode"] = dict(self._episode)
                    out["bootstrap_result"] = res
                return res

        WR.WakeRegistry, PL.ProductionLoop = Spy, FakeLoop
        TOOL.STORE_DIR = os.path.join(ROOT, "data", "integration", "topstepx")
        try:
            TOOL.run_production_scans(
                ps=FakePS(), runtime=None, candles=FakeCandles(),
                session=FakeSession(), contract=FakeContract(), armed=False,
                symbol="MNQ", mission_id="EVENT-WAKE-TEST", scans=scans,
                interval=interval, until_close=False)
        finally:
            WR.WakeRegistry, PL.ProductionLoop, TOOL.STORE_DIR = (
                real_cls, real_loop, real_store)
            TL.archive_tape = real_archive
            if _prior_fp is None:
                os.environ.pop("TOPSTEPX_ACCOUNT_FINGERPRINT", None)
            else:
                os.environ["TOPSTEPX_ACCOUNT_FINGERPRINT"] = _prior_fp
        return marks, fetches

    # ── 1 ───────────────────────────────────────────────────────────────────
    def test_no_events_waits_the_full_deadline(self):
        marks, _ = self.drive([])
        assert len(marks) == 2
        assert self.INTERVAL - 1.0 <= marks[1] - marks[0] <= self.INTERVAL + 1.5

    # ── 2 · THE REGRESSION FOR THE DISCOVERED DEFECT ────────────────────────
    def test_structure_only_does_NOT_wake_luna_early(self):
        marks, fetches = self.drive(
            [(1.0, lambda r: r.note_bar_closed())], ask=29999.0, bid=29998.0)
        assert len(fetches) >= 2, "the pure refresh did not run"
        assert marks[1] - marks[0] >= self.INTERVAL - 1.0, (
            "a bar close alone triggered a scan — this is Option A")

    # ── 3 ───────────────────────────────────────────────────────────────────
    def test_interaction_wakes_immediately(self):
        marks, _ = self.drive([(1.0, lambda r: r.trade_wake.set())])
        assert marks[1] - marks[0] < 3.0

    # ── 4 · THE LOAD-BEARING SPECIMEN-A REGRESSION ──────────────────────────
    def test_production_itself_discovers_the_gap_and_wakes(self):
        """THE THEOREM, END TO END:

            a candle closes while Luna is asleep
            -> PRODUCTION ITSELF discovers the newly settled gap
            -> notices price is already inside it
            -> wakes Luna

        The scripted thread injects ONE thing: a bar close. It never calls
        `refresh`, never arms anything, never sets the interaction bit. The
        owner thread does the whole discovery through
        `fetch_1m_candles -> refresh_from_bars -> annotated_timeframe ->
        fvg_execution_instances`, exactly as production does.

        An earlier version of this test called `reg.refresh(...)` from the
        scripted thread, which injected the FVG from the wrong side of the very
        seam under certification and proved nothing about production.

        LIVE BIRTH, NOT BOOTSTRAP. The startup tape is truncated so the gap does
        not exist when the registry is seeded; the 14:23 candle then settles and
        the gap is BORN mid-session. Feeding the full tape at startup would let
        the bootstrap arm it and this test would silently certify the wrong
        path -- the one case the startup suppression deliberately does not cover.
        """
        marks, fetches = self.drive(
            [(1.0, lambda r: r.note_bar_closed())],
            bars=tape(BIRTH_CUT),                    # gap does NOT exist yet
            bars_later=tape(),                       # 14:23 settles -> BORN
            ask=29249.50, bid=29249.25)              # ALREADY inside the gap
        assert len(fetches) >= 2, "the owner thread never fetched to refresh"
        assert marks[1] - marks[0] < 3.0, (
            "production did not discover the gap and wake on its own")

    def test_the_same_birth_with_price_outside_does_NOT_wake(self):
        """The control. Same birth, same bar close -- only the quote differs."""
        marks, _ = self.drive(
            [(1.0, lambda r: r.note_bar_closed())],
            bars=tape(BIRTH_CUT), bars_later=tape(),
            ask=29999.0, bid=29998.0)
        assert marks[1] - marks[0] >= self.INTERVAL - 1.0

    # ── 5 ───────────────────────────────────────────────────────────────────
    def test_a_later_quote_entry_interrupts_the_wait(self):
        """Driven through the REAL quote path, not by setting the bit.

        The first `on_quote` after arming SEEDS the episode (production sees a
        quote stream, so this costs one tick); the second is the transition.
        """
        def enter(reg):
            reg.on_quote(bid=29998.0, ask=29999.0)     # seed OUTSIDE
            reg.on_quote(bid=29249.25, ask=29249.50)   # OUTSIDE -> INSIDE
        marks, _ = self.drive([
            (1.0, lambda r: r.note_bar_closed()),
            (2.0, enter),
        ], bars=[dict(c) for c in by_tf()["1m"]], ask=29999.0, bid=29998.0)
        gap = marks[1] - marks[0]
        assert 2.0 <= gap < self.INTERVAL, gap

    # ── 6 ───────────────────────────────────────────────────────────────────
    def test_repeated_structure_events_cannot_slide_the_deadline(self):
        marks, _ = self.drive([
            (1.0, lambda r: r.note_bar_closed()),
            (1.0, lambda r: r.note_bar_closed()),
            (2.0, lambda r: r.note_bar_closed()),
        ], ask=29999.0, bid=29998.0)
        assert marks[1] - marks[0] <= self.INTERVAL + 1.5, (
            "bar closes postponed ordinary cognition")

    # ── 7 · DETERMINISTIC MID-FLIGHT, NO RACE ───────────────────────────────
    def test_an_event_raised_DURING_the_scan_survives_it(self):
        """The authoritative lost-wake proof.

        `scan_once` sets `started` and then BLOCKS. The event thread waits for
        `started` -- so the scan is provably in flight -- raises the interaction,
        and only then releases the scan. Ordering is enforced, not inferred from
        a delay of 0.0 against a fake that returns instantly.
        """
        started, release = threading.Event(), threading.Event()

        def during(reg):
            assert started.wait(10), "the scan never began"
            reg.trade_wake.set()          # raised strictly INSIDE the scan
            release.set()

        marks, _ = self.drive([(0.0, during)], gate=(started, release))
        assert len(marks) == 2
        assert marks[1] - marks[0] < 3.0, "a mid-flight event was erased"

    # ── 8 ───────────────────────────────────────────────────────────────────
    def test_both_pending_refreshes_structure_and_still_wakes_once(self):
        def both(reg):
            reg.note_bar_closed()
            reg.trade_wake.set()
        marks, fetches = self.drive([(1.0, both)], ask=29999.0, bid=29998.0)
        assert len(marks) == 2, "exactly one fresh scan"
        assert len(fetches) >= 2, "structure was not refreshed first"
        assert marks[1] - marks[0] < 3.0, "the pending interaction was erased"

    def test_the_deadline_is_measured_from_the_scan_start(self):
        import inspect
        src = open(os.path.join(ROOT, "tools", "topstepx_production_session.py"),
                   encoding="utf-8").read()
        assert "deadline = scan_started + interval" in src
        assert "interval - (time.monotonic() - scan_started)" not in src


class TestStartupBootstrap:
    """THE RESTART BLIND SPOT, CLOSED — driven through `run_production_scans`.

    Before the bootstrap the registry was empty until the first bar closed, so
    for up to a minute after a restart a gap that ALREADY EXISTED had no armed
    occurrence and therefore no OUTSIDE -> INSIDE detector. Price could enter and
    leave inside that window with no wake -- the exact timing failure this unit
    exists to remove, re-entering through the startup door.

    Bootstrap SEEDS, it never TRIGGERS. The normal initial `scan_once()` is
    already about to present the current state to Luna.

    The real-loop harness is REUSED, not inherited: subclassing would make
    pytest re-collect and re-run all eleven parent sequencing tests here,
    inflating the count and doubling the runtime for no added proof.
    """

    INTERVAL = 6.0
    drive = staticmethod(TestTheRealLoopSequencing.drive)

    # ── 1 · THE MISSING THEOREM ─────────────────────────────────────────────
    def test_restart_outside_then_entry_wakes_with_NO_bar_close(self):
        """Restart, existing FVG, price OUTSIDE, and NOT ONE BAR CLOSES.

        Note the single `on_quote`. Before the bootstrap the first quote after
        arming only SEEDED the episode, so one quote could never wake -- and
        with nothing armed at all, neither could a hundred. Waking here is only
        possible because startup armed the occurrence AND seeded it OUTSIDE.
        """
        out = {}
        marks, _ = self.drive(
            [(2.0, lambda r: r.on_quote(bid=29249.25, ask=29249.50))],
            bars=tape(), ask=29999.0, bid=29998.0, out=out)
        reg = out["registry"]
        assert len(reg.armed()) > 0, "bootstrap armed nothing"
        assert not reg.structure_birth.is_set(), "a bar close leaked in"
        assert [w["reason"] for w in reg.wakes] == [WAKE_ENTERED], reg.wakes
        gap = marks[1] - marks[0]
        assert 2.0 <= gap < self.INTERVAL, gap

    # ── 2 · SEED, DO NOT TRIGGER ────────────────────────────────────────────
    def test_restart_already_inside_causes_NO_duplicate_second_scan(self):
        out = {}
        marks, _ = self.drive([], bars=tape(), ask=29249.50, bid=29249.25, out=out)
        reg = out["registry"]
        assert GAP_ID in {row[0] for row in reg.armed()}, "the gap was not armed"
        assert reg.wakes == [], "bootstrap emitted a wake and duplicated Luna"
        assert marks[1] - marks[0] >= self.INTERVAL - 1.0, (
            "bootstrap caused an immediate duplicate second scan")

    def test_restart_inside_then_continued_inside_never_wakes(self):
        marks, _ = self.drive(
            [(1.0, lambda r: [r.on_quote(bid=29249.25, ask=29249.50)
                              for _ in range(5)])],
            bars=tape(), ask=29249.50, bid=29249.25)
        assert marks[1] - marks[0] >= self.INTERVAL - 1.0, "INSIDE->INSIDE woke"

    def test_restart_inside_then_exit_and_reentry_DOES_wake(self):
        def cycle(reg):
            reg.on_quote(bid=29249.25, ask=29249.50)   # still inside  -> no wake
            reg.on_quote(bid=29998.0, ask=29999.0)     # exit          -> re-arm
            reg.on_quote(bid=29249.25, ask=29249.50)   # re-entry      -> WAKE
        out = {}
        marks, _ = self.drive([(2.0, cycle)], bars=tape(),
                              ask=29249.50, bid=29249.25, out=out)
        assert [w["reason"] for w in out["registry"].wakes] == [WAKE_ENTERED]
        gap = marks[1] - marks[0]
        assert 2.0 <= gap < self.INTERVAL, gap

    # ── 3 · NOTHING TO ARM ──────────────────────────────────────────────────
    def test_restart_with_no_qualifying_fvgs_is_silent(self):
        out = {}
        marks, _ = self.drive([], bars=[], ask=29249.50, bid=29249.25, out=out)
        reg = out["registry"]
        assert reg.armed() == () and reg.wakes == []
        assert len(marks) == 2
        assert marks[1] - marks[0] >= self.INTERVAL - 1.0, "an artificial wake"

    # ── 4 · A DEAD BAR CACHE MAY NOT FABRICATE STATE ────────────────────────
    def test_restart_with_an_unavailable_bar_cache_is_survivable(self):
        out = {}
        marks, _ = self.drive([], bars=tape(), fetch_raises=True,
                              ask=29249.50, bid=29249.25, out=out)
        reg = out["registry"]
        assert reg.armed() == (), "bootstrap fabricated state from a dead cache"
        assert reg.wakes == [], "a dead cache produced a wake"
        assert len(marks) == 2, "a cold cache cost a scan"
        assert marks[1] - marks[0] >= self.INTERVAL - 1.0

    # ── ORDERING IS THE THREAD-SAFETY THEOREM ───────────────────────────────
    def test_bootstrap_happens_BEFORE_the_pump_can_see_the_registry(self):
        """`_episode` is pump-owned. Bootstrap is the one main-thread write, and
        publishing afterwards is the entire reason that is safe."""
        src = open(os.path.join(ROOT, "tools", "topstepx_production_session.py"),
                   encoding="utf-8").read()
        assert (src.index("bootstrap_from_bars")
                < src.index("candles.wake_registry = wake")), (
            "the registry is published to the pump before it is seeded")


class TestExecutablePriceFreshness:
    """ONE PRICE AUTHORITY FOR BOTH SEAMS — bootstrap AND live bar-close refresh.

        FVG geometry      canonical FVG constructor
        interaction zone  zone low / high
        interaction PRICE existing fresh executable-price authority

    The registry used to read `candles.last_quote`, a stored dict that is never
    cleared and carries no enforced age, while the candidate producer read the
    governed capture. Two quote sources, one governed:

        CANDIDATE PRODUCER   "that quote is stale, I cannot trade it"
        WAKE REGISTRY        "looks like an inside price to me"

    An INSIDE claim SUPPRESSES the next entry wake, so a stale numeric quote
    could consume the real interaction. A prior non-executable evaluation must
    never consume a future fresh interaction episode.

    These drive the REAL `from_capture` / `executable_price` against the real
    `MAX_QUOTE_AGE_SECONDS`; the test never decides what stale means.
    """

    INTERVAL = 6.0
    drive = staticmethod(TestTheRealLoopSequencing.drive)

    # ── 1 · THE PROVEN DEFECT ───────────────────────────────────────────────
    def test_a_stale_startup_quote_may_not_claim_INSIDE(self):
        out = {}
        marks, _ = self.drive(
            [(2.0, lambda r: r.on_quote(bid=29249.25, ask=29249.50))],
            bars=tape(),
            ask=29249.50, bid=29249.25,      # numerically INSIDE the gap
            quote_age=30.0,                  # but STALE under production law
            out=out)
        reg = out["registry"]
        assert len(reg.armed()) > 0, "a stale quote must not prevent ARMING"
        assert out["bootstrap_episode"][GAP_ID] == OUTSIDE, (
            "a stale price was claimed as INSIDE at bootstrap")
        assert [w["reason"] for w in reg.wakes] == [WAKE_ENTERED], reg.wakes
        gap = marks[1] - marks[0]
        assert 2.0 <= gap < self.INTERVAL, gap

    # ── 2 · FRESH INSIDE STILL SUPPRESSES ───────────────────────────────────
    def test_a_FRESH_startup_quote_inside_still_seeds_INSIDE(self):
        out = {}
        marks, _ = self.drive([], bars=tape(), ask=29249.50, bid=29249.25,
                              quote_age=0.0, out=out)
        reg = out["registry"]
        assert out["bootstrap_episode"][GAP_ID] == INSIDE
        assert reg.wakes == [], "a fresh inside startup duplicated Luna"
        assert marks[1] - marks[0] >= self.INTERVAL - 1.0

    # ── 3 · FRESH OUTSIDE ───────────────────────────────────────────────────
    def test_a_FRESH_startup_quote_outside_seeds_OUTSIDE_and_entry_wakes(self):
        out = {}
        marks, _ = self.drive(
            [(2.0, lambda r: r.on_quote(bid=29249.25, ask=29249.50))],
            bars=tape(), ask=29999.0, bid=29998.0, quote_age=0.0, out=out)
        assert out["bootstrap_episode"][GAP_ID] == OUTSIDE
        assert 2.0 <= marks[1] - marks[0] < self.INTERVAL

    # ── 4 · THE SCOPE PROOF — LIVE BIRTH, NOT JUST BOOTSTRAP ────────────────
    def test_a_stale_quote_on_LIVE_BIRTH_may_not_claim_inside(self):
        """Mandatory: proves the fix was not scoped narrowly to bootstrap.

        Two quotes, deliberately. The gap is BORN mid-session, so it is not in
        the pump's episode map; the pump's first sighting SEEDS it and the next
        quote is the transition. Bootstrapped occurrences do not pay this tick
        because `bootstrap` seeds them on the owner thread before publication --
        the main thread may not write pump-owned episode state afterwards.
        In production the pump sees a continuous quote stream, so this is one
        tick, not one minute.
        """
        def enter(reg):
            reg.on_quote(bid=29249.25, ask=29249.50)   # first sighting -> seed
            reg.on_quote(bid=29249.25, ask=29249.50)   # transition -> WAKE
        out = {}
        marks, _ = self.drive(
            [(1.0, lambda r: r.note_bar_closed()), (2.0, enter)],
            bars=tape(BIRTH_CUT), bars_later=tape(),
            ask=29249.50, bid=29249.25,      # numerically inside the newborn gap
            quote_age=30.0,                  # but stale
            out=out)
        reg = out["registry"]
        reasons = [w["reason"] for w in reg.wakes]
        assert WAKE_ARMED_INSIDE not in reasons, (
            "a stale quote claimed a newly born gap was already inside")
        assert reasons == [WAKE_ENTERED], reasons
        assert 2.0 <= marks[1] - marks[0] < self.INTERVAL

    # ── 5 · SPECIMEN A SURVIVES ─────────────────────────────────────────────
    def test_a_FRESH_quote_on_LIVE_BIRTH_still_wakes_immediately(self):
        out = {}
        marks, _ = self.drive(
            [(1.0, lambda r: r.note_bar_closed())],
            bars=tape(BIRTH_CUT), bars_later=tape(),
            ask=29249.50, bid=29249.25, quote_age=0.0, out=out)
        assert [w["reason"] for w in out["registry"].wakes] == [WAKE_ARMED_INSIDE]
        assert marks[1] - marks[0] < 3.0, "the 10:24 specimen stopped waking"

    # ── 6 · NO QUOTE AT ALL ─────────────────────────────────────────────────
    def test_a_broken_quote_lane_arms_but_claims_nothing(self):
        def enter(reg):
            reg.on_quote(bid=29249.25, ask=29249.50)
            reg.on_quote(bid=29249.25, ask=29249.50)
        out = {}
        marks, _ = self.drive([(2.0, enter)], bars=tape(),
                              ask=29249.50, bid=29249.25,
                              quote_raises=True, out=out)
        reg = out["registry"]
        assert len(reg.armed()) > 0, "a broken quote lane unarmed the registry"
        assert out["bootstrap_episode"][GAP_ID] == OUTSIDE
        assert 2.0 <= marks[1] - marks[0] < self.INTERVAL

    # ── 7 · THE AUTHORITY IS ACTUALLY CONSULTED ─────────────────────────────
    def test_same_numbers_fresh_allows_inside_stale_denies_it(self):
        """Behavioural, not textual: only `quote_age` differs between these."""
        seeds = {}
        for age in (0.0, 30.0):
            out = {}
            self.drive([], bars=tape(), ask=29249.50, bid=29249.25,
                       quote_age=age, out=out)
            seeds[age] = out["bootstrap_episode"][GAP_ID]
        assert seeds == {0.0: INSIDE, 30.0: OUTSIDE}, seeds

    def test_the_wake_path_no_longer_reads_the_ungoverned_stored_quote(self):
        """`last_quote` is never cleared and has no enforced age. The wake path
        must source its initial interaction truth from the governed capture."""
        import ast
        import inspect
        import textwrap
        sys.path.insert(0, os.path.join(ROOT, "tools"))
        import topstepx_production_session as TOOL
        src = textwrap.dedent(inspect.getsource(TOOL.run_production_scans))
        assert "last_quote" not in src, (
            "the wake path still reads the ungoverned stored quote")
        assert src.count("admitted_sided_prices") >= 2, (
            "bootstrap and refresh must share one price authority")
        names = {n.attr for n in ast.walk(ast.parse(textwrap.dedent(
                     inspect.getsource(TOOL.admitted_sided_prices))))
                 if isinstance(n, ast.Attribute)}
        assert "capture" in names, "the governed capture is not consulted"


class TestBootstrapDoctrine:
    """Unit-level: bootstrap arms and seeds, and never wakes."""

    def test_bootstrap_never_wakes_even_when_price_is_inside(self):
        r = WakeRegistry()
        out = r.bootstrap(by_tf(), CONTRACT, bid=29249.25, ask=29249.50)
        assert out["bootstrapped"] and GAP_ID in out["seeded_inside"]
        assert not r.trade_wake.is_set() and r.wakes == []

    def test_bootstrap_seeds_the_episode_at_its_true_value(self):
        inside = WakeRegistry()
        inside.bootstrap(by_tf(), CONTRACT, bid=29249.25, ask=29249.50)
        assert inside._episode[GAP_ID] == INSIDE
        outside = WakeRegistry()
        outside.bootstrap(by_tf(), CONTRACT, bid=29998.0, ask=29999.0)
        assert outside._episode[GAP_ID] == OUTSIDE

    def test_a_seeded_outside_occurrence_wakes_on_the_VERY_NEXT_quote(self):
        r = WakeRegistry()
        r.bootstrap(by_tf(), CONTRACT, bid=29998.0, ask=29999.0)
        fired = r.on_quote(bid=29249.25, ask=29249.50)      # one quote, not two
        assert [f["occurrence_id"] for f in fired] == [GAP_ID]
        assert r.trade_wake.is_set()

    def test_startup_suppression_does_NOT_leak_into_live_birth(self):
        """The non-conflation requirement. A gap BORN after bootstrap, with
        price already inside it, is still a first episode and still wakes."""
        r = WakeRegistry()
        r.bootstrap_from_bars(tape(BIRTH_CUT), CONTRACT, bid=29249.25, ask=29249.50)
        assert GAP_ID not in {row[0] for row in r.armed()}
        assert not r.trade_wake.is_set()
        out = r.refresh_from_bars(tape(), CONTRACT, bid=29249.25, ask=29249.50)
        assert GAP_ID in out["armed_while_inside"], "live birth stopped waking"
        assert r.trade_wake.is_set()

    def test_bootstrap_does_not_re_wake_an_occurrence_it_already_armed(self):
        """The first live refresh must not re-fire what startup already knew."""
        r = WakeRegistry()
        r.bootstrap_from_bars(tape(), CONTRACT, bid=29249.25, ask=29249.50)
        out = r.refresh_from_bars(tape(), CONTRACT, bid=29249.25, ask=29249.50)
        assert out["armed_while_inside"] == []
        assert not r.trade_wake.is_set()

    def test_bootstrap_authorizes_nothing(self):
        assert not names_in(WakeRegistry.bootstrap) & {
            "build_snapshot", "run_toolbox", "run_narrative_brain",
            "CandidateProducer", "build_bracket", "place_order", "produce"}

    def test_bootstrap_never_raises_on_garbage(self):
        r = WakeRegistry()
        for bad in (None, [], [{"nonsense": 1}]):
            out = r.bootstrap_from_bars(bad, CONTRACT, bid=1.0, ask=2.0)
            assert out["bootstrapped"] in (True, False)
            assert not r.trade_wake.is_set()


class TestNothingElseMoved:
    def test_no_risk_doctrine_moved(self):
        from broker import topstepx_combine_risk as RK
        assert (RK.PREFERRED_MAX_STOP_POINTS, RK.ABSOLUTE_MAX_STOP_POINTS) == (35.0, 50.0)
        assert RK.PRODUCTION_MAX_RISK_USD == 350.00

    def test_po3_still_refuses_identically(self):
        from toolbox.price_levels import po3_reversal_order_block, NO_MANIPULATION
        assert po3_reversal_order_block(snap(), "bullish")["reason"] == NO_MANIPULATION

    def test_fvg_selection_semantics_are_untouched(self):
        import inspect
        from broker.luna_candidate_producer import CandidateProducer
        src = inspect.getsource(CandidateProducer._assert_tool_detected)
        assert 'if family == "fvg" and wanted:' in src
        assert "TOOL_OCCURRENCE_AMBIGUOUS" in src
