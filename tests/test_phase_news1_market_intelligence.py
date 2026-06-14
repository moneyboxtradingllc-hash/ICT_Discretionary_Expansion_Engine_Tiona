"""
Phase NEWS-1 — Market Intelligence Layer tests.

Covers all six phases + the hard constraints: news is CONTEXT only (no
direction, no trade), the Brain remains ECU, and the layer is gated
(NEWS_LAYER_ENABLED default off → bit-for-bit unchanged) and never raises.
"""
import json
import os
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone

sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from news.calendar_provider import EconomicCalendarProvider, EconomicEvent
from news.breaking_news_provider import BreakingNewsProvider, BreakingNewsEvent
from news.news_classifier import classify_news, classify_category, NewsAssessment
from news.event_risk_engine import assess_event_risk
from news.news_memory import NewsMemory, NewsMemoryRecord
from news.news_engine import news_enabled, build_news_context
from ai_brain.brain_input import build_brain_input
from ai_brain.brain_prompt import BRAIN_SYSTEM_PROMPT, NEWS_CONTEXT_ADDENDUM

NOW = datetime(2026, 6, 15, 13, 30, tzinfo=timezone.utc)


def _iso(minutes_from_now):
    return (NOW + timedelta(minutes=minutes_from_now)).isoformat()


def _write(rows):
    fd, path = tempfile.mkstemp(suffix=".json")
    os.close(fd)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(rows, fh)
    return path


# ── Phase 1 — Economic Calendar ───────────────────────────────────────────────
class TestEconomicCalendar(unittest.TestCase):
    def test_detects_and_orders_upcoming_events(self):
        path = _write([
            {"event_name": "CPI", "event_time": _iso(15)},
            {"event_name": "FOMC", "event_time": _iso(42)},
            {"event_name": "ISM", "event_time": _iso(200)},   # outside lookahead
        ])
        snap = EconomicCalendarProvider(path).snapshot(NOW)
        self.assertEqual(snap.nearest_upcoming.event_name, "CPI")
        self.assertEqual(snap.minutes_to_event, 15.0)
        self.assertTrue(snap.scheduled_event_window)
        bv = snap.brain_view()
        self.assertEqual(bv["event_name"], "CPI")
        self.assertEqual(bv["impact_level"], "high")     # default impact for CPI
        self.assertEqual(bv["minutes_to_event"], 15.0)

    def test_no_events_is_quiet(self):
        path = _write([])
        snap = EconomicCalendarProvider(path).snapshot(NOW)
        self.assertIsNone(snap.nearest_upcoming)
        self.assertFalse(snap.scheduled_event_window)

    def test_recent_event_within_digest(self):
        path = _write([{"event_name": "CPI", "event_time": _iso(-5)}])
        snap = EconomicCalendarProvider(path).snapshot(NOW)
        self.assertIsNone(snap.nearest_upcoming)
        self.assertEqual(snap.recent_event.event_name, "CPI")
        self.assertEqual(snap.minutes_since_recent, 5.0)
        self.assertTrue(snap.scheduled_event_window)

    def test_missing_file_never_raises(self):
        snap = EconomicCalendarProvider("/no/such/calendar.json").snapshot(NOW)
        self.assertFalse(snap.scheduled_event_window)


# ── Phase 2 — Breaking News ───────────────────────────────────────────────────
class TestBreakingNews(unittest.TestCase):
    def test_recent_within_active_window(self):
        path = _write([
            {"headline": "Missile strike escalates conflict", "timestamp": _iso(-10)},
            {"headline": "Old news", "timestamp": _iso(-500)},   # stale
        ])
        recent = BreakingNewsProvider(path).recent(NOW)
        self.assertEqual(len(recent), 1)
        self.assertIn("Missile", recent[0].headline)

    def test_missing_file_never_raises(self):
        self.assertEqual(BreakingNewsProvider("/no/such/file.json").recent(NOW), [])


# ── Phase 3 — Classifier ──────────────────────────────────────────────────────
class TestNewsClassifier(unittest.TestCase):
    def test_categories(self):
        self.assertEqual(classify_category("CPI comes in hot"), "economic_release")
        self.assertEqual(classify_category("FOMC rate decision today"), "fed")
        self.assertEqual(classify_category("Missile strike, new sanctions"), "geopolitical")
        self.assertEqual(classify_category("Nvidia unveils AI chip"), "technology")
        self.assertEqual(classify_category("NYSE halts trading, exchange outage"), "market_structure")
        self.assertEqual(classify_category("Mystery headline"), "unknown")

    def test_relevance_floors(self):
        a = classify_news(BreakingNewsEvent(headline="Powell signals rate path"))
        self.assertEqual(a.category, "fed")
        self.assertEqual(a.relevance_to_nasdaq, "high")
        t = classify_news(BreakingNewsEvent(headline="Apple ships new cloud feature"))
        self.assertEqual(t.relevance_to_nasdaq, "medium")

    def test_critical_keyword_escalates(self):
        a = classify_news(BreakingNewsEvent(headline="Fed announces emergency rate move"))
        self.assertEqual(a.relevance_to_nasdaq, "critical")

    def test_classifier_has_no_direction(self):
        a = classify_news(BreakingNewsEvent(headline="CPI beats forecast strongly"))
        blob = json.dumps(a.to_dict()).lower()
        for side in ("bullish", "bearish", '"buy"', '"sell"'):
            self.assertNotIn(side, blob)


# ── Phase 4 — Event Risk Engine ───────────────────────────────────────────────
class TestEventRisk(unittest.TestCase):
    def _cal(self, rows):
        return EconomicCalendarProvider(_write(rows)).snapshot(NOW)

    def test_no_event_normal(self):
        r = assess_event_risk(self._cal([]), [])
        self.assertEqual(r.risk_state, "normal")

    def test_cpi_in_10_high_risk(self):
        r = assess_event_risk(self._cal([{"event_name": "CPI", "event_time": _iso(10)}]), [])
        self.assertEqual(r.risk_state, "high_risk")

    def test_fomc_in_5_stand_down(self):
        r = assess_event_risk(self._cal([{"event_name": "FOMC", "event_time": _iso(5)}]), [])
        self.assertEqual(r.risk_state, "stand_down")

    def test_just_after_cpi_post_event_digest(self):
        r = assess_event_risk(self._cal([{"event_name": "CPI", "event_time": _iso(-5)}]), [])
        self.assertEqual(r.risk_state, "post_event_digest")

    def test_distant_event_caution(self):
        r = assess_event_risk(self._cal([{"event_name": "ISM", "event_time": _iso(45)}]), [])
        self.assertEqual(r.risk_state, "caution")

    def test_breaking_critical_stand_down(self):
        a = [classify_news(BreakingNewsEvent(headline="NYSE halts trading, exchange outage"))]
        r = assess_event_risk(self._cal([]), a)
        self.assertEqual(r.risk_state, "stand_down")

    def test_higher_of_calendar_or_breaking_wins(self):
        a = [classify_news(BreakingNewsEvent(headline="Missile strike escalates conflict"))]  # high
        r = assess_event_risk(self._cal([{"event_name": "ISM", "event_time": _iso(45)}]), a)  # caution
        self.assertEqual(r.risk_state, "high_risk")


# ── Phase 5 — Brain Integration ───────────────────────────────────────────────
class TestBrainIntegration(unittest.TestCase):
    def test_news_context_shape(self):
        cal = _write([{"event_name": "CPI", "event_time": _iso(6)}])
        ctx = build_news_context(NOW, calendar_path=cal, breaking_path="/none.json")
        for key in ("risk_state", "active_event", "minutes_to_event",
                    "breaking_news_active", "breaking_news_category", "summary"):
            self.assertIn(key, ctx)
        self.assertEqual(ctx["active_event"], "CPI")
        self.assertEqual(ctx["risk_state"], "high_risk")
        self.assertFalse(ctx["directional"])

    def test_news_context_has_no_direction_or_trade(self):
        cal = _write([{"event_name": "CPI", "event_time": _iso(6)}])
        ctx = build_news_context(NOW, calendar_path=cal, breaking_path="/none.json")
        blob = json.dumps(ctx).lower()
        for forbidden in ("bullish", "bearish", '"buy"', '"sell"', '"side"', '"direction"'):
            self.assertNotIn(forbidden, blob)

    def test_build_brain_input_passes_news_through(self):
        snap = {"timestamp": "x", "news_context": {"risk_state": "high_risk"}}
        bi = build_brain_input(snap, {"available": False})
        self.assertIn("news_context", bi)
        self.assertEqual(bi["news_context"]["risk_state"], "high_risk")

    def test_build_brain_input_omits_news_when_absent(self):
        snap = {"timestamp": "x"}
        bi = build_brain_input(snap, {"available": False})
        self.assertNotIn("news_context", bi)   # regression-safe: nothing added

    def test_addendum_is_separate_from_base_prompt(self):
        # base prompt must be unchanged when no news is present (regression-safe)
        self.assertNotIn(NEWS_CONTEXT_ADDENDUM.strip(), BRAIN_SYSTEM_PROMPT)
        self.assertIn("MUST NOT", NEWS_CONTEXT_ADDENDUM)
        self.assertIn("must not derive narrative_direction", NEWS_CONTEXT_ADDENDUM.lower())

    def test_build_news_context_never_raises(self):
        ctx = build_news_context(None)   # default paths, current clock
        self.assertIn("risk_state", ctx)


# ── Phase 6 — News Memory ─────────────────────────────────────────────────────
class TestNewsMemory(unittest.TestCase):
    def test_record_and_recall(self):
        fd, path = tempfile.mkstemp(suffix=".jsonl")
        os.close(fd)
        os.remove(path)   # NewsMemory creates it
        mem = NewsMemory(path)
        self.assertTrue(mem.record(NewsMemoryRecord(
            event="CPI", timestamp=NOW.isoformat(),
            direction_before="bearish", direction_after="bullish",
            market_response="rallied 140 points", volatility_profile="spike")))
        mem.record(NewsMemoryRecord(event="Powell Speech",
                                    market_response="bearish narrative invalidated"))
        self.assertEqual(len(mem.all()), 2)
        cpi = mem.by_event("cpi")
        self.assertEqual(len(cpi), 1)
        self.assertEqual(cpi[0]["market_response"], "rallied 140 points")

    def test_missing_store_recall_empty(self):
        self.assertEqual(NewsMemory("/no/such/mem.jsonl").all(), [])


# ── Gating + safety ───────────────────────────────────────────────────────────
class TestGating(unittest.TestCase):
    def tearDown(self):
        os.environ.pop("NEWS_LAYER_ENABLED", None)

    def test_default_disabled(self):
        os.environ.pop("NEWS_LAYER_ENABLED", None)
        self.assertFalse(news_enabled())

    def test_enable_flag(self):
        os.environ["NEWS_LAYER_ENABLED"] = "true"
        self.assertTrue(news_enabled())


if __name__ == "__main__":
    unittest.main(verbosity=2)
