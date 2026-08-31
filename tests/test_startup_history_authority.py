"""STARTUP-HISTORY-AUTHORITY — the PROD-20260812 production wiring locks.

2026-08-12. An armed session ran nineteen scans of NO_CANDLES and would have
started reasoning at 12:29 ET on a chart born at 11:30. The provider's warm-up
was correct, the continuity law was correct, the coherence guard was correct.
The PRODUCTION CALL SITE handed the provider a `TopstepXLiveSession`, which did
not implement `bars_1m`, so `_fetch_bars` raised before making a single request
and the blanket `except` -- correct on its own terms, warm-up may never kill
startup -- swallowed the only evidence.

Why the existing suite missed it: `TestStartupBackfillClosesTheRestartHole`
proves warm-up works against `BackfillSession`, a test double that implements
`bars_1m`. It proved the provider's half of a contract nothing checked the other
half of. A cousin object that happens to implement MORE methods than the real
one is not a production parity test.

So the rule this file enforces: for a market-authority capability, at least one
regression instantiates the ACTUAL production object graph.

No network. No model. No order. The transport is injected.
"""
from __future__ import annotations

import os
import sys
from datetime import datetime, timedelta, timezone

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src"))

from broker.topstepx_live_session import TopstepXLiveSession       # noqa: E402
from data_feed import startup_history_authority as SHA             # noqa: E402
from data_feed.topstepx_provider import TopstepXDataProvider       # noqa: E402

CID = "CON.F.US.MNQ.U26"
TOKEN = "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxIn0.sig"
ACCT = {"id": 7788, "name": "50KTC-V2", "balance": 50000.0, "canTrade": True,
        "isVisible": True, "simulated": True}
MNQ = {"id": CID, "name": "MNQU6", "description": "MNQ", "tickSize": 0.25,
       "tickValue": 0.5, "activeContract": True}

NOW = datetime(2026, 8, 12, 16, 30, tzinfo=timezone.utc)


# ── fixtures shaped like the real thing ───────────────────────────────────────
def venue_rows(start, count, price=29700.0):
    """The venue's own wire shape from /api/History/retrieveBars."""
    return [{"t": (start + timedelta(minutes=i)).isoformat().replace("+00:00", "Z"),
             "o": price, "h": price + 1, "l": price - 1, "c": price, "v": 10}
            for i in range(count)]


def canon(start, count, price=29700.0):
    """The canonical bar shape the store holds."""
    return [{"timestamp": (start + timedelta(minutes=i)).isoformat(),
             "open": price, "high": price + 1, "low": price - 1,
             "close": price, "volume": 10} for i in range(count)]


def transport(log, rows=None):
    def _t(url, payload, headers, timeout):
        path = url.split("topstepx.com", 1)[-1]
        log.append({"path": path, "payload": payload})
        if path == "/api/History/retrieveBars":
            return {"bars": list(rows or []), "success": True, "errorCode": 0}
        return {
            "/api/Auth/loginKey": {"token": TOKEN, "success": True, "errorCode": 0},
            "/api/Account/search": {"accounts": [ACCT], "success": True, "errorCode": 0},
            "/api/Contract/search": {"contracts": [MNQ], "success": True, "errorCode": 0},
        }.get(path, {"success": True, "errorCode": 0})
    return _t


def live_session(log, rows=None, *, pin=True):
    """The EXACT session class `tools/topstepx_production_session.py` builds."""
    s = TopstepXLiveSession("u", "k", transport=transport(log, rows))
    s.authenticate()
    if pin:
        s.pin(account_id=7788)
    s.resolve_contract("MNQ")
    return s


class FakeRuntime:
    """A shared runtime, so the provider is a pure consumer exactly as in
    production. Owning one here would open a socket."""

    def __init__(self):
        self.attached = []

    def attach(self, who, event, handler):
        self.attached.append((who, event))


def provider(tmp_path, session):
    p = TopstepXDataProvider(session=session, autostart=False,
                             store_dir=str(tmp_path))
    p.start("MNQ", runtime=FakeRuntime())
    return p


class StubCandles:
    """Only the surface `check_startup` is allowed to depend on."""

    def __init__(self, report, candles, connected_at):
        self._report, self._candles = report, candles
        self.connected_at = connected_at

    def startup_history_report(self):
        return self._report

    def canonical_candles(self):
        return list(self._candles)


# ══════════════════════════════════════════════════════════════════════════════
class TestTheWriteCapableSessionCanReadHistory:
    """§1 — one explicit session-level interface, satisfied by BOTH sessions."""

    def test_the_production_session_exposes_the_interface_the_provider_requires(self):
        assert hasattr(TopstepXLiveSession, "bars_1m"), (
            "the provider asks every session for bars_1m; the write-capable "
            "session is the one production actually injects")

    def test_both_session_implementations_satisfy_one_interface(self):
        from broker.topstepx_readonly import TopstepXReadOnlySession
        assert hasattr(TopstepXReadOnlySession, "bars_1m")
        assert hasattr(TopstepXLiveSession, "bars_1m")

    def test_it_reaches_the_history_endpoint_for_the_resolved_contract(self):
        log = []
        s = live_session(log, venue_rows(NOW - timedelta(minutes=60), 60))
        s.bars_1m(minutes_back=240)
        hits = [c for c in log if c["path"] == "/api/History/retrieveBars"]
        assert len(hits) == 1, log
        assert hits[0]["payload"]["contractId"] == CID

    def test_it_never_admits_a_forming_bar(self):
        """MUTATION 12. The single most expensive measurement error this project
        has hit; the delegation must not quietly re-open it."""
        log = []
        s = live_session(log, venue_rows(NOW - timedelta(minutes=10), 10))
        s.bars_1m()
        hit = [c for c in log if c["path"] == "/api/History/retrieveBars"][0]
        assert hit["payload"]["includePartialBar"] is False

    def test_it_returns_the_canonical_bar_shape_oldest_first(self):
        rows = venue_rows(NOW - timedelta(minutes=5), 5)
        out = live_session([], rows).bars_1m()
        assert [set(b) for b in out] == [
            {"timestamp", "open", "high", "low", "close", "volume"}] * 5
        assert [b["timestamp"] for b in out] == sorted(b["timestamp"] for b in out)

    def test_history_does_not_require_a_pinned_account(self):
        """The provider resolves a contract during start() and never pins.
        Demanding an account would reintroduce the same silent failure."""
        s = live_session([], venue_rows(NOW - timedelta(minutes=3), 3), pin=False)
        assert len(s.bars_1m()) == 3

    def test_it_refuses_when_no_contract_is_resolved(self):
        s = TopstepXLiveSession("u", "k", transport=transport([], []))
        s.authenticate()
        with pytest.raises(RuntimeError):
            s.bars_1m()


# ══════════════════════════════════════════════════════════════════════════════
class TestTheProductionObjectGraphActuallyWarmsUp:
    """§5 — the regression bound to the real call site, not to a cousin."""

    def test_the_real_production_session_makes_the_provider_fetch_history(self, tmp_path):
        log = []
        s = live_session(log, venue_rows(NOW - timedelta(minutes=240), 240))
        p = provider(tmp_path, s)
        assert [c for c in log if c["path"] == "/api/History/retrieveBars"], (
            "startup warm-up never reached the venue through the production session")
        rep = p.startup_history_report()
        assert rep["error"] is None, rep["error"]
        assert rep["returned"] == 240 and rep["added"] == 240
        assert len(p.canonical_candles()) == 240

    def test_the_report_names_the_window_the_venue_returned(self, tmp_path):
        start = NOW - timedelta(minutes=240)
        p = provider(tmp_path, live_session([], venue_rows(start, 240)))
        rep = p.startup_history_report()
        assert rep["oldest_returned"].startswith(start.strftime("%Y-%m-%dT%H:%M"))
        assert rep["newest_returned"].startswith(
            (start + timedelta(minutes=239)).strftime("%Y-%m-%dT%H:%M"))

    # ── THE NEGATIVE MUTATION ────────────────────────────────────────────────
    def test_removing_the_delegation_is_CAUGHT(self, tmp_path, monkeypatch):
        """MUTATION 1. This is the exact defect of 2026-08-12. Before the repair
        the mutant was indistinguishable from health."""
        monkeypatch.delattr(TopstepXLiveSession, "bars_1m")
        p = provider(tmp_path, live_session([], venue_rows(NOW, 10)))
        rep = p.startup_history_report()
        assert rep["error"], "a missing capability must be reported"
        assert rep["added"] == 0 and rep["returned"] == 0

        verdict = SHA.evaluate(backfill_report=rep, candles=p.canonical_candles(),
                               now=NOW, process_started_at=p.connected_at)
        assert verdict["fit"] is False
        assert any(r.startswith("STARTUP_HISTORY_CAPABILITY_ERROR")
                   for r in verdict["refusals"]), verdict["refusals"]

    def test_a_delegation_that_silently_returns_nothing_is_CAUGHT(self, tmp_path):
        """MUTATION 2. A 200 with an empty body is not history."""
        p = provider(tmp_path, live_session([], []))
        verdict = SHA.evaluate(backfill_report=p.startup_history_report(),
                               candles=p.canonical_candles(), now=NOW,
                               process_started_at=p.connected_at)
        assert verdict["fit"] is False
        assert any(r.startswith("NO_CANONICAL_HISTORY") for r in verdict["refusals"])

    def test_armed_startup_REFUSES_before_scanning(self, tmp_path, monkeypatch):
        """MUTATION 3/4. The launcher must not treat a failed warm-up as startup
        it can proceed past. Refusal happens before Terra, before a candidate,
        before a mission or token, before order authority."""
        from tools import topstepx_production_session as PS
        monkeypatch.setenv("SCAN_SYMBOL", "MNQ")
        monkeypatch.setenv("TOPSTEPX_ACCOUNT_FINGERPRINT", "acct:test")
        monkeypatch.setenv("AI_BRAIN_MODEL", "gpt-5.6-terra")
        monkeypatch.setenv("BRAIN_JSON_MODE", "on")
        session = type("S", (), {"account": type("A", (), {"id": 1})(),
                                 "contract": type("C", (), {"id": CID})(),
                                 "market_hub": object()})()
        stub = StubCandles({"attempted": True, "added": 0, "returned": 0,
                            "error": "DataFeedError: session exposes no historical "
                                     "bars endpoint"},
                           [], NOW)
        out = PS.check_startup(session, armed=True, mission_id="M",
                               provider="topstepx", candles=stub)
        assert any(r.startswith("STARTUP_HISTORY_CAPABILITY_ERROR") for r in out), out

    def test_the_disarmed_lane_stays_tolerant(self, tmp_path, monkeypatch):
        """A read-only rehearsal watching a chart fill in is useful. An ARMED
        session doing the same thing is the defect."""
        from tools import topstepx_production_session as PS
        monkeypatch.setenv("SCAN_SYMBOL", "MNQ")
        monkeypatch.setenv("TOPSTEPX_ACCOUNT_FINGERPRINT", "acct:test")
        session = type("S", (), {"account": type("A", (), {"id": 1})(),
                                 "contract": type("C", (), {"id": CID})(),
                                 "market_hub": object()})()
        stub = StubCandles({"attempted": True, "added": 0, "returned": 0,
                            "error": "boom"}, [], NOW)
        out = PS.check_startup(session, armed=False, mission_id="",
                               provider="topstepx", candles=stub)
        assert not [r for r in out if "STARTUP_HISTORY" in r], out


# ══════════════════════════════════════════════════════════════════════════════
class TestNewbornChartNeverGainsAuthority:
    """§6 — process uptime may never bootstrap production market history.

    The observed failure mode, pinned: a stale prior-day tail, no usable
    current-session history, and live bars arriving one per minute. The coherence
    guard counts bars, and sixty post-launch bars count exactly like sixty bars
    of real history -- which is why it delayed the defect instead of catching it.
    """

    def _newborn(self, live_bars: int, *, error="DataFeedError: no endpoint"):
        started = NOW - timedelta(minutes=live_bars)
        stale = canon(NOW - timedelta(days=1, minutes=300), 200)      # yesterday
        fresh = canon(started, live_bars)                             # since boot
        return SHA.evaluate(
            backfill_report={"attempted": True, "added": 0, "returned": 0,
                             "error": error},
            candles=stale + fresh, now=NOW, process_started_at=started)

    @pytest.mark.parametrize("live_bars", [15, 30, 60, 120])
    def test_accumulated_uptime_never_becomes_authority(self, live_bars):
        verdict = self._newborn(live_bars)
        assert verdict["fit"] is False, (live_bars, verdict)

    @pytest.mark.parametrize("live_bars", [60, 120])
    def test_it_refuses_on_PROVENANCE_even_once_the_bar_count_satisfies(self, live_bars):
        """MUTATION 6. At 60 bars the coherence guard is satisfied -- this is the
        exact moment 2026-08-12 would have handed Terra a newborn chart."""
        verdict = self._newborn(live_bars)
        window = verdict["checks"]["window"]
        assert window["sufficient"] is True, "the count gate is satisfied here"
        assert any(r.startswith("NEWBORN_CHART") for r in verdict["refusals"]), verdict

    def test_newborn_is_refused_even_when_the_warm_up_reported_no_error(self):
        """Provenance is independent of the capability check: a warm-up that
        'succeeded' but left nothing older than boot is still a newborn chart."""
        started = NOW - timedelta(minutes=90)
        verdict = SHA.evaluate(
            backfill_report={"attempted": True, "added": 0, "returned": 0,
                             "error": None},
            candles=canon(started, 90), now=NOW, process_started_at=started)
        assert verdict["fit"] is False
        assert any(r.startswith("NEWBORN_CHART") for r in verdict["refusals"]), verdict

    def test_the_2026_08_12_tape_shape_is_pinned(self):
        """Verbatim: the Aug-11 15:01-15:05Z remnant, then live bars from 15:30Z.
        contiguous_tail returns only the last run, which is why the count reset
        to 1 and climbed +1 per scan."""
        remnant = canon(datetime(2026, 8, 11, 15, 1, tzinfo=timezone.utc), 5)
        started = datetime(2026, 8, 12, 15, 30, tzinfo=timezone.utc)
        now = started + timedelta(minutes=59)
        verdict = SHA.evaluate(
            backfill_report={"attempted": True, "added": 0, "returned": 0,
                             "error": "DataFeedError: session exposes no "
                                      "historical bars endpoint"},
            candles=remnant + canon(started, 60), now=now,
            process_started_at=started)
        assert verdict["checks"]["window"]["bars"] == 60
        assert verdict["fit"] is False
        assert any(r.startswith("NEWBORN_CHART") for r in verdict["refusals"])


# ══════════════════════════════════════════════════════════════════════════════
class TestHealthyHistoryGrantsAuthority:
    """§7 — the success case must actually pass, or the gate is just an off switch."""

    def test_a_real_warm_up_produces_a_fit_verdict(self, tmp_path):
        start = NOW - timedelta(minutes=240)
        log = []
        p = provider(tmp_path, live_session(log, venue_rows(start, 240)))
        verdict = SHA.evaluate(backfill_report=p.startup_history_report(),
                               candles=p.canonical_candles(), now=NOW,
                               process_started_at=p.connected_at)
        assert verdict["fit"] is True, verdict["refusals"]

    def test_the_first_window_is_historical_reality_not_process_uptime(self, tmp_path):
        start = NOW - timedelta(minutes=240)
        p = provider(tmp_path, live_session([], venue_rows(start, 240)))
        verdict = SHA.evaluate(backfill_report=p.startup_history_report(),
                               candles=p.canonical_candles(), now=NOW,
                               process_started_at=p.connected_at)
        assert verdict["checks"]["window_predates_process"] is True
        assert verdict["checks"]["window"]["bars"] >= 60

    def test_historical_and_live_bars_coexist_without_duplication(self, tmp_path):
        start = NOW - timedelta(minutes=240)
        p = provider(tmp_path, live_session([], venue_rows(start, 240)))
        p._ingest_bars(canon(NOW, 3))                    # three live minutes
        stamps = [c["timestamp"] for c in p.canonical_candles()]
        assert len(stamps) == len(set(stamps)) == 243


# ══════════════════════════════════════════════════════════════════════════════
class TestAuthorityIsFitnessNotBarsAdded:
    """The authority condition is whether the record is FIT to reason from --
    never the accounting detail `added > 0`."""

    def test_a_warm_up_that_added_nothing_because_the_store_was_current_is_FIT(self):
        """MUTATION: `added > 0` as the gate would refuse a perfectly healthy
        session whose canonical store already held every minute offered."""
        started = NOW - timedelta(minutes=2)
        verdict = SHA.evaluate(
            backfill_report={"attempted": True, "added": 0, "returned": 240,
                             "error": None},
            candles=canon(NOW - timedelta(minutes=240), 240),
            now=NOW, process_started_at=started)
        assert verdict["fit"] is True, verdict["refusals"]

    def test_a_warm_up_that_added_plenty_of_STALE_history_is_REFUSED(self):
        """MUTATION 5. Continuous, coherent, aligned -- and about last Friday."""
        verdict = SHA.evaluate(
            backfill_report={"attempted": True, "added": 300, "returned": 300,
                             "error": None},
            candles=canon(NOW - timedelta(days=3), 300),
            now=NOW, process_started_at=NOW - timedelta(minutes=1))
        assert verdict["fit"] is False
        assert any(r.startswith("CANONICAL_HISTORY_STALE") for r in verdict["refusals"])

    def test_an_absent_report_is_refused_not_assumed_healthy(self):
        verdict = SHA.evaluate(backfill_report=None, candles=canon(NOW, 90),
                               now=NOW, process_started_at=NOW)
        assert verdict["fit"] is False
        assert any(r.startswith("NO_STARTUP_HISTORY_REPORT") for r in verdict["refusals"])

    def test_a_hole_that_truncates_the_recent_window_is_refused(self):
        """A 30-minute outage close to the tip leaves too few continuous recent
        bars, and too little coherent history is DEGRADATION -- never permission
        to reach back across the hole for more."""
        whole = canon(NOW - timedelta(minutes=240), 240)
        holed = whole[:200] + whole[230:]                # only 10 bars survive
        verdict = SHA.evaluate(
            backfill_report={"attempted": True, "added": 210, "returned": 210,
                             "error": None},
            candles=holed, now=NOW, process_started_at=NOW - timedelta(minutes=1))
        assert verdict["fit"] is False
        assert any(r.startswith("INCOHERENT_STARTUP_HISTORY")
                   for r in verdict["refusals"]), verdict["refusals"]

    def test_an_OLD_hole_behind_a_sufficient_window_does_not_refuse(self):
        """Doctrine lock, deliberately asserting the law rather than a stricter
        instinct. `coherent_window` is a BOUNDED window, not the whole tape: a
        hole 110 minutes back sits outside it, and the bars before that hole are
        discarded rather than stitched on. This gate must apply exactly the law
        the scan loop applies, or startup and scanning would disagree about what
        coherent means."""
        whole = canon(NOW - timedelta(minutes=240), 240)
        holed = whole[:100] + whole[130:]                # 110 continuous recent
        verdict = SHA.evaluate(
            backfill_report={"attempted": True, "added": 210, "returned": 210,
                             "error": None},
            candles=holed, now=NOW, process_started_at=NOW - timedelta(minutes=1))
        assert verdict["fit"] is True, verdict["refusals"]
        # 110 continuous bars from 14:40Z, then five trimmed by alignment up to
        # the 14:45 boundary so no derived timeframe inherits a partial bucket.
        assert verdict["checks"]["window"]["bars"] == 105
        assert verdict["checks"]["window"]["continuous"] is True


# ══════════════════════════════════════════════════════════════════════════════
class TestRuntimeGapRepairThroughTheProductionSession:
    """§4 — the second casualty. repair_gaps() routes through the same capability,
    so mid-session hole repair was inert on the production path too."""

    def test_repair_reaches_the_venue_through_the_live_session(self, tmp_path):
        whole = canon(NOW - timedelta(minutes=60), 60)
        log = []
        s = live_session(log, venue_rows(NOW - timedelta(minutes=60), 60))
        p = provider(tmp_path, s)
        p.aggregator._closed.clear()
        p.aggregator._closed_minutes.clear()
        p._ingest_bars(whole[:20] + whole[35:])
        assert p.continuity_report()["continuous"] is False
        log.clear()

        out = p.repair_gaps()
        assert [c for c in log if c["path"] == "/api/History/retrieveBars"], (
            "MUTATION 7: repair must actually ask the venue for the hole")
        assert out["repaired"] is True
        assert out["rebuild_required"] is True, (
            "inserting history invalidates what stateful detectors already computed")
        assert p.continuity_report()["continuous"] is True

    def test_a_venue_that_cannot_heal_the_hole_fails_closed(self, tmp_path):
        """MUTATION 8. Never report success without inserting, and NEVER stitch
        across the hole to make the array look continuous."""
        whole = canon(NOW - timedelta(minutes=60), 60)
        p = provider(tmp_path, live_session([], []))     # venue answers empty
        p._ingest_bars(whole[:20] + whole[35:])
        out = p.repair_gaps()
        assert out["repaired"] is False
        report = p.continuity_report()
        assert report["continuous"] is False
        assert report["missing_minutes"] == 15, report

    def test_repair_is_still_refused_authority_by_the_startup_gate(self, tmp_path):
        """A hole that could not be healed must not pass the armed gate either."""
        whole = canon(NOW - timedelta(minutes=240), 240)
        p = provider(tmp_path, live_session([], []))
        p._ingest_bars(whole[:200] + whole[230:])        # hole truncates the tip
        verdict = SHA.evaluate(backfill_report=p.startup_history_report(),
                               candles=p.canonical_candles(), now=NOW,
                               process_started_at=p.connected_at)
        assert verdict["fit"] is False


# ══════════════════════════════════════════════════════════════════════════════
class TestStartupHistoryIsVisible:
    """§2 — a total historical failure must never look identical to success."""

    def test_the_launcher_prints_what_the_warm_up_achieved(self, tmp_path):
        from tools import topstepx_production_session as PS
        start = NOW - timedelta(minutes=240)
        p = provider(tmp_path, live_session([], venue_rows(start, 240)))
        out = PS.startup_history_telemetry(p)
        for label in ("bars returned by venue", "bars added to canonical",
                      "oldest returned", "newest returned", "canonical continuous",
                      "warm-up error"):
            assert label in out, label
        assert "240" in out

    def test_a_failed_warm_up_is_LOUD(self, tmp_path, monkeypatch):
        """MUTATION 10. The failure text has to reach the operator's screen."""
        from tools import topstepx_production_session as PS
        monkeypatch.delattr(TopstepXLiveSession, "bars_1m")
        p = provider(tmp_path, live_session([], venue_rows(NOW, 5)))
        out = PS.startup_history_telemetry(p)
        assert "no historical bars endpoint" in out

    def test_the_report_carries_no_secret(self, tmp_path):
        from tools import topstepx_production_session as PS
        p = provider(tmp_path, live_session([], venue_rows(NOW, 5)))
        out = PS.startup_history_telemetry(p)
        assert TOKEN not in out and "acct:" not in out


# ══════════════════════════════════════════════════════════════════════════════
class TestTheProviderDependsOnAnInterfaceNotOnPrivates:
    """MUTATION 11 — a provider that reached into `session._client` would satisfy
    the same behaviour while hiding the defect in a second place."""

    def test_the_provider_never_touches_the_session_client(self):
        src = open(os.path.join("src", "data_feed", "topstepx_provider.py"),
                   encoding="utf-8").read()
        assert "_client" not in src, (
            "history must arrive through the session-level bars_1m interface")

    def test_the_provider_asks_only_for_bars_1m(self):
        src = open(os.path.join("src", "data_feed", "topstepx_provider.py"),
                   encoding="utf-8").read()
        assert 'getattr(self._session, "bars_1m", None)' in src
