"""NEWS-2 Phase 1 / 2 / 3b — the factual news foundation. Owner ruling 2026-09-27.

Every fixture below is SYNTHETIC, shaped after each source's documented format
(RFC 5545 iCalendar, the FRED API JSON, the ForexFactory weekly export, RSS
2.0, Finnhub's news array, the Fed FOMC calendar page). No test touches the
network: every adapter takes an injected `fetch`. Live formats are proven on
the deployment machine by `tools/news2_refresh.py`, not assumed here.
"""
from __future__ import annotations

import ast
import json
import os
import sys
import time as _time
from datetime import datetime, timedelta, timezone

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))

from news.factual import brief as BRIEF                  # noqa: E402
from news.factual import calendar as CAL                 # noqa: E402
from news.factual import calendar_sources as SRC         # noqa: E402
from news.factual import headlines as HEAD               # noqa: E402
from news.factual import ics                             # noqa: E402
from news.factual import model as M                      # noqa: E402
from news.factual import mood as MOOD                    # noqa: E402

NOW = datetime(2026, 10, 13, 12, 0, tzinfo=timezone.utc)       # Tue 08:00 ET (EDT)

BLS_ICS = "\r\n".join([
    "BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//BLS//Release Calendar//EN",
    "BEGIN:VEVENT", "UID:cpi-2026-10@bls.gov",
    "DTSTAMP:20260901T120000Z",
    "DTSTART;TZID=US-Eastern:20261014T083000",
    "SUMMARY:Consumer Price Index for September 2026", "END:VEVENT",
    "BEGIN:VEVENT", "UID:ppi-2026-10@bls.gov",
    "DTSTART;TZID=US-Eastern:20261015T083000",
    "SUMMARY:Producer Price Index for September 2026", "END:VEVENT",
    "BEGIN:VEVENT", "UID:jolts@bls.gov",
    "DTSTART;TZID=US-Eastern:20261013T100000",
    "SUMMARY:Job Openings and Labor Turnover Survey for August 2026", "END:VEVENT",
    "BEGIN:VEVENT", "UID:emp-2026-12@bls.gov",
    "DTSTART;TZID=US-Eastern:20261204T083000",
    "SUMMARY:Employment Situation for November 2026", "END:VEVENT",
    "BEGIN:VEVENT", "UID:bad@bls.gov",
    "DTSTART;TZID=Mars/Olympus:20261016T083000",
    "SUMMARY:Consumer Price Index for Mars", "END:VEVENT",
    "END:VCALENDAR", ""])

FED_HTML = """
<h4>2026 FOMC Meetings</h4>
<div class="row fomc-meeting"><div class="fomc-meeting__month col-xs-5"><strong>October</strong></div>
<div class="fomc-meeting__date col-xs-4">27-28</div></div>
<div class="row fomc-meeting"><div class="fomc-meeting__month col-xs-5"><strong>Apr/May</strong></div>
<div class="fomc-meeting__date col-xs-4">30-1*</div></div>
<div class="row fomc-meeting"><div class="fomc-meeting__month col-xs-5"><strong>June</strong></div>
<div class="fomc-meeting__date col-xs-4">5 (notation vote)</div></div>
<h4>2027 FOMC Meetings</h4>
<div class="row fomc-meeting"><div class="fomc-meeting__month col-xs-5"><strong>January</strong></div>
<div class="fomc-meeting__date col-xs-4">26-27</div></div>
"""

FRED_DATES = json.dumps({"release_dates": [
    {"release_id": 10, "release_name": "Consumer Price Index", "date": "2026-10-14"},
    {"release_id": 53, "release_name": "Gross Domestic Product", "date": "2026-10-29"},
    {"release_id": 999, "release_name": "Some Regional Survey", "date": "2026-10-14"}]})

FF_WEEK = json.dumps([
    {"title": "CPI m/m", "country": "USD", "date": "2026-10-14T08:30:00-04:00",
     "impact": "High", "forecast": "0.3%", "previous": "0.4%"},
    {"title": "Core CPI m/m", "country": "USD", "date": "2026-10-14T08:30:00-04:00",
     "impact": "High", "forecast": "0.2%", "previous": "0.3%"},
    {"title": "ISM Services PMI", "country": "USD", "date": "2026-10-13T10:00:00-04:00",
     "impact": "High", "forecast": "51.0", "previous": "50.4"},
    {"title": "Fed Chair Powell Speaks", "country": "USD",
     "date": "2026-10-13T13:00:00-04:00", "impact": "High"},
    {"title": "German ZEW", "country": "EUR", "date": "2026-10-13T05:00:00-04:00",
     "impact": "Medium"}])

FED_RSS = """<?xml version="1.0"?><rss version="2.0"><channel>
<item><title>Federal Reserve issues FOMC statement</title>
<link>https://www.federalreserve.gov/newsevents/pressreleases/x.htm</link>
<pubDate>Tue, 13 Oct 2026 11:30:00 GMT</pubDate></item>
<item><title>Old item</title><pubDate>Mon, 01 Jun 2026 10:00:00 GMT</pubDate></item>
</channel></rss>"""

FINNHUB = json.dumps([{"category": "general", "datetime": int(datetime(
    2026, 10, 13, 11, 45, tzinfo=timezone.utc).timestamp()),
    "headline": "Chipmaker guides higher", "id": 1, "related": "NVDA,AVGO",
    "source": "Reuters", "summary": "s", "url": "https://example.invalid/n"}])


def serve(mapping):
    """A fake GET: routes by URL prefix; anything unmapped fails like a network error."""
    calls = []

    def fetch(url, headers=None):
        calls.append(url)
        for prefix, text in mapping.items():
            if url.startswith(prefix):
                if isinstance(text, Exception):
                    return {"ok": False, "status": None, "text": None, "error": str(text), "url": url}
                return {"ok": True, "status": 200, "text": text, "error": None, "url": url}
        return {"ok": False, "status": None, "text": None, "error": "URLError: blocked", "url": url}
    fetch.calls = calls
    return fetch


ALL_SOURCES = {SRC.BLS_ICS_URL: BLS_ICS, SRC.FED_FOMC_URL: FED_HTML,
               SRC.FRED_RELEASE_DATES_URL: FRED_DATES, SRC.FF_WEEK_URL: FF_WEEK}


def full_state(mapping=ALL_SOURCES, *, fred_key="k", now=NOW):
    fetch = serve(mapping)
    results = [SRC.fetch_bls(fetch=fetch, now=now), SRC.fetch_fed_fomc(fetch=fetch, now=now),
               SRC.fetch_fred(api_key=fred_key, fetch=fetch, now=now),
               SRC.fetch_forexfactory(fetch=fetch, now=now)]
    return CAL.build_calendar_state(results, now=now)


def by_cat(state, cat):
    return [e for e in state["events"] if e["category"] == cat]


# ══════════════════════════════════════════════════════════════════════════════
class TestAbsenceIsNeverCalm:

    def test_no_snapshot_is_unknown(self):
        v = CAL.calendar_view(None, NOW)
        assert v["data_state"] == M.UNKNOWN and v["events"] == []
        assert "normal" not in json.dumps(v).lower()

    def test_every_source_failing_is_unknown(self):
        state = full_state({})
        assert state["data_state"] == M.UNKNOWN
        assert state["events"] == []
        assert {s["status"] for s in state["sources"]} <= {M.SOURCE_FAILED, M.SOURCE_UNAVAILABLE}
        assert "normal" not in json.dumps(state).lower()

    def test_only_the_convenience_feed_is_not_enough(self):
        state = full_state({SRC.FF_WEEK_URL: FF_WEEK})
        assert state["data_state"] == M.UNKNOWN
        assert "convenience" in state["data_state_reason"]

    def test_a_stale_snapshot_reads_stale(self):
        state = full_state()
        v = CAL.calendar_view(state, NOW + timedelta(days=2))
        assert v["data_state"] == M.STALE
        assert v["reason"]

    def test_news1_missing_sources_are_unknown_not_normal(self, tmp_path):
        from news.news_engine import build_news_context
        ctx = build_news_context(NOW, calendar_path=str(tmp_path / "none.json"),
                                 breaking_path=str(tmp_path / "none2.json"))
        assert ctx["risk_state"] == "unknown"
        assert ctx["data_state"] == "unknown"
        assert "risk=normal" not in ctx["summary"]

    def test_news1_stale_calendar_is_unknown_not_normal(self, tmp_path):
        from news.news_engine import build_news_context
        cal, brk = tmp_path / "cal.json", tmp_path / "brk.json"
        cal.write_text("[]"), brk.write_text("[]")
        old = _time.time() - 3 * 86400
        os.utime(cal, (old, old))
        ctx = build_news_context(datetime.now(timezone.utc), calendar_path=str(cal),
                                 breaking_path=str(brk))
        assert ctx["risk_state"] == "unknown"
        assert ctx["sources"]["calendar"]["state"] == "stale"

    def test_news1_fresh_empty_sources_may_say_normal(self, tmp_path):
        """Valid, fresh data MAY produce a factual state -- that is not fabrication."""
        from news.news_engine import build_news_context
        cal, brk = tmp_path / "cal.json", tmp_path / "brk.json"
        cal.write_text("[]"), brk.write_text("[]")
        ctx = build_news_context(datetime.now(timezone.utc), calendar_path=str(cal),
                                 breaking_path=str(brk))
        assert ctx["risk_state"] == "normal"
        assert ctx["data_state"] == "known"
        assert "calendar as of" in ctx["summary"]

    def test_news1_evidence_of_risk_survives_a_missing_source(self, tmp_path):
        from news.news_engine import build_news_context
        cal = tmp_path / "cal.json"
        now = datetime.now(timezone.utc)
        cal.write_text(json.dumps([{"event_name": "CPI",
                                    "event_time": (now + timedelta(minutes=10)).isoformat()}]))
        ctx = build_news_context(now, calendar_path=str(cal),
                                 breaking_path=str(tmp_path / "none.json"))
        assert ctx["risk_state"] == "high_risk"
        assert ctx["data_state"] == "partial"


class TestSourceFailureIsExplicit:

    def test_transport_failure(self):
        st, evs = SRC.fetch_bls(fetch=serve({SRC.BLS_ICS_URL: RuntimeError("HTTP 403")}), now=NOW)
        assert st.status == M.SOURCE_FAILED and "403" in st.reason and evs == []

    def test_parse_failure(self):
        st, _ = SRC.fetch_fred(api_key="k", fetch=serve({SRC.FRED_RELEASE_DATES_URL: "<html>"}), now=NOW)
        assert st.status == M.SOURCE_PARSE_FAILED

    def test_missing_key_is_unavailable_and_makes_no_request(self):
        fetch = serve(ALL_SOURCES)
        st, _ = SRC.fetch_fred(api_key=None, fetch=fetch, now=NOW)
        assert st.status == M.SOURCE_UNAVAILABLE and fetch.calls == []

    def test_a_fed_page_without_this_years_meetings_is_a_parse_failure(self):
        st, evs = SRC.fetch_fed_fomc(fetch=serve({SRC.FED_FOMC_URL: "<h4>2019 FOMC Meetings</h4>"}),
                                     now=NOW)
        assert st.status in (M.SOURCE_PARSE_FAILED, M.SOURCE_EMPTY) and evs == []

    def test_api_keys_never_reach_the_record(self):
        state = full_state(fred_key="SECRET123")
        assert "SECRET123" not in json.dumps(state)


class TestOfficialEventsNormalize:

    def test_bls_cpi(self):
        cpi = by_cat(full_state(), M.CPI)
        assert len(cpi) == 1
        e = cpi[0]
        assert e["scheduled_at"] == "2026-10-14T12:30:00+00:00"
        assert e["scheduled_local"] == "2026-10-14T08:30:00-04:00"
        assert e["primary_source"] == "bls_ics" and e["primary_authority"] == M.AUTHORITY_OFFICIAL
        assert e["time_basis"] == M.TIME_SOURCE_EXPLICIT
        assert e["name"].startswith("Consumer Price Index")
        assert e["data_state"] == M.KNOWN
        assert e["event_id"].startswith("evt_")

    def test_non_tracked_releases_and_bad_zones_are_not_invented(self):
        state = full_state()
        names = json.dumps(state["events"])
        assert "Job Openings" not in names and "Mars" not in names
        bls = next(s for s in state["sources"] if s["source_name"] == "bls_ics")
        assert "skipped" in (bls["reason"] or "")

    def test_fomc_from_the_fed_page(self):
        fomc = by_cat(full_state(), M.FOMC_DECISION)
        days = sorted(e["scheduled_local"][:10] for e in fomc)
        assert "2026-10-28" in days                 # decision = last day of the meeting
        assert "2026-05-01" in days                 # Apr/May 30-1 resolves to May 1
        assert not any(d.startswith("2026-06") for d in days), "notation vote is not a meeting"
        oct_ = next(e for e in fomc if e["scheduled_local"].startswith("2026-10-28"))
        assert oct_["scheduled_local"].endswith("14:00:00-04:00")
        assert oct_["time_basis"] == M.TIME_AGENCY_CONVENTION

    def test_fred_backstop_is_date_plus_labelled_convention(self):
        gdp = by_cat(full_state(), M.GDP)[0]
        assert gdp["primary_source"] == "fred_release_dates"
        assert gdp["time_basis"] == M.TIME_AGENCY_CONVENTION
        assert gdp["scheduled_local"] == "2026-10-29T08:30:00-04:00"
        assert "convention" in json.dumps(gdp["sources"]).lower()
        assert gdp["cross_check_status"] == "single_source"


class TestTimezonesAreExact:

    def test_est_after_the_november_switch(self):
        nfp = by_cat(full_state(), M.NFP)[0]
        assert nfp["scheduled_at"] == "2026-12-04T13:30:00+00:00"      # 08:30 EST = 13:30Z
        assert nfp["scheduled_local"] == "2026-12-04T08:30:00-05:00"

    def test_utc_and_date_only_ics_values(self):
        z = ics.parse_dt("20261014T123000Z", {})
        assert z["instant"] == datetime(2026, 10, 14, 12, 30, tzinfo=timezone.utc)
        d = ics.parse_dt("20261014", {"VALUE": "DATE"})
        assert d["instant"] is None and str(d["date"]) == "2026-10-14"

    def test_a_floating_time_is_refused_not_guessed(self):
        f = ics.parse_dt("20261014T083000", {})
        assert f["instant"] is None and f["error"]

    def test_naive_instants_are_refused(self):
        assert M.parse_instant("2026-10-14T08:30:00") is None


class TestConflictsAndProvenance:

    def test_agreeing_sources_merge_without_losing_any(self):
        cpi = by_cat(full_state(), M.CPI)[0]
        srcs = sorted(r["source_name"] for r in cpi["sources"])
        assert srcs.count("forexfactory") == 2          # CPI m/m and Core CPI m/m both kept
        assert {"bls_ics", "fred_release_dates"} <= set(srcs)
        assert cpi["cross_check_status"] == "confirmed" and cpi["conflicts"] == []

    def test_a_time_disagreement_stays_a_visible_conflict(self):
        ff = json.loads(FF_WEEK)
        ff[0]["date"] = ff[1]["date"] = "2026-10-14T10:00:00-04:00"
        cpi = by_cat(full_state({**ALL_SOURCES, SRC.FF_WEEK_URL: json.dumps(ff)}), M.CPI)[0]
        assert cpi["data_state"] == M.CONFLICT and cpi["cross_check_status"] == "conflict"
        times = {c["source"]: c["scheduled_at"] for c in cpi["conflicts"]}
        assert times["bls_ics"] == ["2026-10-14T12:30:00+00:00"]
        assert times["forexfactory"] == ["2026-10-14T14:00:00+00:00"]
        assert cpi["primary_source"] == "bls_ics", "the official source stays primary"

    def test_values_and_impact_come_only_from_an_explicit_source(self):
        cpi = by_cat(full_state(), M.CPI)[0]
        assert cpi["impact_class"] == "high" and cpi["impact_class_source"] == "forexfactory"
        assert cpi["consensus"] == "0.3%" and cpi["previous"] == "0.4%"
        assert cpi["values_source"] == "forexfactory"
        assert cpi["actual"] is None, "no actual was published; none is invented"
        gdp = by_cat(full_state(), M.GDP)[0]
        assert gdp["impact_class"] is None and gdp["consensus"] is None

    def test_convenience_only_categories_say_so(self):
        ism = by_cat(full_state(), M.ISM)[0]
        assert ism["primary_authority"] == M.AUTHORITY_CONVENIENCE
        assert ism["cross_check_status"] == "single_source"

    def test_retrieval_and_publication_times_are_distinct(self):
        cpi = by_cat(full_state(), M.CPI)[0]
        bls = next(r for r in cpi["sources"] if r["source_name"] == "bls_ics")
        assert bls["fetched_at"] == M.iso(NOW)
        assert bls["source_published_at"] == "2026-09-01T12:00:00+00:00"


class TestEventWindowsAreMeasurementOnly:

    def test_windows_around_cpi(self):
        state = full_state()
        ts = datetime(2026, 10, 14, 12, 22, tzinfo=timezone.utc)      # 8 min before CPI
        f = CAL.event_window_facts(ts, state)
        assert f["windows"]["-15/+15"]["inside"] and f["windows"]["-10/+5"]["inside"]
        assert not f["windows"]["-5/+5"]["inside"]
        hit = f["windows"]["-15/+15"]["events"][0]
        assert hit["minutes_relative_to_event"] == -8.0 and hit["analysis_tier1"]

    def test_no_calendar_is_unknown(self):
        f = CAL.event_window_facts(NOW, None)
        assert f["data_state"] == M.UNKNOWN and f["windows"] == {}

    def test_the_audit_counts_without_calendar_as_unknown(self, tmp_path):
        sys.path.insert(0, os.path.join(ROOT, "tools"))
        from news2_event_window_audit import audit
        out = audit([{"timestamp_et": NOW.isoformat(), "final_disposition": "STOOD_DOWN"}],
                    store_dir=str(tmp_path))
        assert out["without_calendar"] == 1

    def test_the_audit_reads_the_snapshot_that_existed_then(self, tmp_path):
        sys.path.insert(0, os.path.join(ROOT, "tools"))
        from news2_event_window_audit import audit
        CAL.persist(full_state(), store_dir=str(tmp_path))
        at = datetime(2026, 10, 14, 12, 27, tzinfo=timezone.utc)
        out = audit([{"timestamp_et": at.isoformat(), "final_disposition": "STOOD_DOWN"}],
                    store_dir=str(tmp_path))
        assert out["without_calendar"] == 0
        assert out["windows"]["-5/+5"]["inside:STOOD_DOWN"] == 1


class TestDelayedDataCannotPassAsLive:

    def _series(self, obs_date, now=NOW):
        text = json.dumps({"observations": [{"date": obs_date, "value": "18.4"},
                                            {"date": "2026-10-01", "value": "."}]})
        return MOOD.fetch_fred_series("VXNCLS", api_key="k",
                                      fetch=serve({MOOD.FRED_OBS_URL: text}), now=now)

    def test_a_daily_close_is_labelled_delayed(self):
        s = self._series("2026-10-12")
        assert s["timeliness"] == "delayed_daily_close" and s["source_cadence"] == "daily_close"
        assert s["data_state"] == M.KNOWN and s["observation_date"] == "2026-10-12"
        assert s["fetched_at"] == M.iso(NOW) and s["age_days"] == 1
        keys = " ".join(s).lower()
        assert "live" not in keys and "current" not in keys

    def test_an_old_close_is_stale(self):
        s = self._series("2026-10-05")
        assert s["data_state"] == M.STALE and s["reason"]

    def test_no_key_is_unknown_not_a_number(self):
        s = MOOD.fetch_fred_series("VIXCLS", api_key=None, fetch=serve({}), now=NOW)
        assert s["data_state"] == M.UNKNOWN and s["value"] is None

    def test_overnight_move_needs_both_anchors(self):
        prior_close_bar = datetime(2026, 10, 12, 19, 59, tzinfo=timezone.utc)   # 15:59 ET
        bars = [{"timestamp": prior_close_bar.isoformat(), "close": 30000.0},
                {"timestamp": (NOW - timedelta(minutes=1)).isoformat(), "close": 30150.0}]
        m = MOOD.mnq_overnight_move(bars, now=NOW)
        assert m["data_state"] == M.KNOWN and m["move_points"] == 150.0
        assert m["prior_close_at"] == "2026-10-12T20:00:00+00:00"
        m2 = MOOD.mnq_overnight_move(bars[1:], now=NOW)
        assert m2["data_state"] == M.UNKNOWN and "no bar" in m2["reason"]

    def test_old_bars_are_stale(self):
        prior_close_bar = datetime(2026, 10, 12, 19, 59, tzinfo=timezone.utc)
        bars = [{"timestamp": prior_close_bar.isoformat(), "close": 30000.0},
                {"timestamp": (NOW - timedelta(hours=2)).isoformat(), "close": 30150.0}]
        assert MOOD.mnq_overnight_move(bars, now=NOW)["data_state"] == M.STALE


class TestHeadlinesAreFacts:

    def test_fed_rss_and_finnhub(self):
        fetch = serve({HEAD.FED_PRESS_RSS: FED_RSS, HEAD.FINNHUB_NEWS: FINNHUB})
        h = HEAD.collect_headlines(finnhub_key="k", fetch=fetch, now=NOW)
        assert h["data_state"] == M.KNOWN
        titles = [i["headline"] for i in h["items"]]
        assert "Old item" not in titles, "outside the lookback window"
        fed = next(i for i in h["items"] if i["source_name"] == "fed_press_rss")
        assert fed["published_at"] == "2026-10-13T11:30:00+00:00"
        assert fed["retrieved_at"] == M.iso(NOW) and fed["age_minutes"] == 30.0
        fin = next(i for i in h["items"] if i["source_name"] == "finnhub_news")
        assert fin["related_explicit"] == ["NVDA", "AVGO"]
        for it in h["items"]:
            assert not ({"sentiment", "lean", "bias", "direction"} & set(it))

    def test_no_sources_is_unknown(self):
        h = HEAD.collect_headlines(finnhub_key=None, fetch=serve({}), now=NOW)
        assert h["data_state"] == M.UNKNOWN and h["items"] == []

    def test_reaction_is_measured_only_when_bars_cover_it(self):
        t0 = datetime(2026, 10, 13, 11, 30, tzinfo=timezone.utc)
        bars = [{"timestamp": (t0 + timedelta(minutes=k)).isoformat(), "close": 100.0 + k}
                for k in range(0, 16)]
        r = HEAD.observed_reaction(t0.isoformat(), bars)
        assert r["measurable"] and r["move_5m"] == 5.0 and r["move_15m"] == 15.0
        assert not HEAD.observed_reaction(t0.isoformat(), [])["measurable"]


class TestTheBriefIsFactualAndPowerless:

    def _brief(self):
        state = full_state()
        heads = HEAD.collect_headlines(finnhub_key=None, fetch=serve({HEAD.FED_PRESS_RSS: FED_RSS}), now=NOW)
        mood = MOOD.build_mood(bars=[], api_key=None, fetch=serve({}), now=NOW)
        return BRIEF.build_brief(now=NOW, calendar_state=state, headlines=heads, mood=mood)

    def test_interpretation_is_fenced_off_and_never_sovereign(self):
        b = self._brief()
        assert b["authority"] == "observe_only" and b["brain_input"] is False
        assert b["interpretation"]["sovereign"] is False
        assert b["interpretation"]["present"] is False and b["interpretation"]["text"] is None
        assert "not trading evidence" in b["interpretation"]["label"]

    def test_the_factual_block_carries_no_lean(self):
        keys = {k.rsplit(".", 1)[-1].split("[")[0] for k in BRIEF.factual_keys(self._brief()["factual"])}
        assert not (keys & BRIEF.FORBIDDEN_FACTUAL_KEYS)

    def test_no_model_call_is_needed_to_establish_facts(self, monkeypatch):
        from ai_brain import narrative_brain as nb

        def boom(*a, **k):
            raise AssertionError("a model was called to establish factual news state")
        monkeypatch.setattr(nb, "_call_llm", boom)
        assert self._brief()["factual"]["calendar"]["data_state"] in DATA_OK

    def test_the_factual_package_does_not_import_the_brain(self):
        pkg = os.path.join(ROOT, "src", "news", "factual")
        for name in os.listdir(pkg):
            if name.endswith(".py"):
                tree = ast.parse(open(os.path.join(pkg, name), encoding="utf-8-sig").read())
                mods = {getattr(n, "module", None) or "" for n in ast.walk(tree)
                        if isinstance(n, ast.ImportFrom)}
                mods |= {a.name for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names}
                assert not any(m.startswith(("ai_brain", "openai", "ai_layer", "broker"))
                               for m in mods), name


DATA_OK = {M.KNOWN, M.STALE, M.UNKNOWN, M.CONFLICT}


class TestObserveOnlyCannotReachTrading:
    """NEWS-2 is read by operator tools only."""

    def _imports_of(self, path):
        tree = ast.parse(open(path, encoding="utf-8-sig").read())
        mods = {getattr(n, "module", None) or "" for n in ast.walk(tree)
                if isinstance(n, ast.ImportFrom)}
        mods |= {a.name for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names}
        return mods

    def test_no_production_module_imports_news2(self):
        src = os.path.join(ROOT, "src")
        offenders = []
        for dirpath, _, files in os.walk(src):
            if os.path.join("news", "factual") in dirpath:
                continue
            for f in files:
                if f.endswith(".py"):
                    p = os.path.join(dirpath, f)
                    if any(m.startswith("news.factual") for m in self._imports_of(p)):
                        offenders.append(p)
        assert offenders == []

    def test_brain_input_does_not_carry_news2(self):
        text = open(os.path.join(ROOT, "src", "ai_brain", "brain_input.py"), encoding="utf-8").read()
        assert "news.factual" not in text and "news2" not in text

    def test_news_is_not_in_the_brain_contract(self):
        from ai_brain import production_model as PM
        bound = [rel for _, rel in PM._CONTRACT_SOURCES + PM._CONTRACT_SOURCES_REPO]
        assert not any(rel.startswith("news/") or "news2" in rel for rel in bound)

    def test_the_news1_layer_is_still_off_by_default(self, monkeypatch):
        monkeypatch.delenv("NEWS_LAYER_ENABLED", raising=False)
        from news.news_engine import news_enabled
        assert news_enabled() is False
