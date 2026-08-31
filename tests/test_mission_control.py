"""
MISSION-CONTROL — rendering-only locks (2026-07-30).

  * collector never raises: empty root -> every panel ABSENT/ERROR, page
    still renders
  * honest absence: missing sources say ABSENT, never invent values
  * self-contained: no external URLs (http/https), no <script>, inline CSS
  * hostile text from telemetry files is HTML-escaped
  * rendering only: the module writes ONE html file and nothing else
"""
import json
import os
import sys
import tempfile
import unittest

sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from mission_control.mission_control import (  # noqa: E402
    collect_status, render_html, render,
)


class TestCollector(unittest.TestCase):
    def test_empty_root_never_raises_and_reports_absent(self):
        tmp = tempfile.mkdtemp()
        status = collect_status(tmp)
        self.assertEqual(len(status["panels"]), 7)
        for name, panel in status["panels"].items():
            if name == "kill_switch":     # existence check always answers
                continue
            self.assertIn(panel.get("status"), ("ABSENT", "ERROR"),
                          f"{name} should be ABSENT on an empty root")

    def test_fixture_panels_read_real_shapes(self):
        tmp = tempfile.mkdtemp()
        det = os.path.join(tmp, "data", "integration", "topstepx",
                           "deterministic")
        os.makedirs(os.path.join(det, "evidence"))
        json.dump({"mode": "DETERMINISTIC_MNQ_SIM_ONLY", "account": "DEMO1",
                   "instrument": "MNQ SEP26", "trade_count": 1,
                   "realized_pnl": -50.0, "max_trades": 2},
                  open(os.path.join(det, "session_state.json"), "w"))
        with open(os.path.join(det, "evidence", "ERA_20260730.jsonl"),
                  "w") as fh:
            fh.write(json.dumps({"verdict": "NO_TRADE",
                                 "snapshot": {"htf_memory_age": 3},
                                 "equity": 50000.0}) + "\n")
        hdir = os.path.join(tmp, "data", "htf_memory")
        os.makedirs(hdir)
        json.dump({"days": {"2026-07-29": {}, "2026-07-30": {}}},
                  open(os.path.join(hdir, "MNQ.json"), "w"))
        status = collect_status(tmp)
        mv = status["panels"]["money_venue"]
        self.assertEqual(mv["account"], "DEMO1")
        self.assertEqual(mv["evidence"]["scans"], 1)
        self.assertEqual(mv["evidence"]["last_scan"]["htf_memory_age"], 3)
        htf = status["panels"]["htf_memory"]
        self.assertEqual(htf["stores"]["MNQ"]["daily_records"], 2)
        self.assertEqual(htf["stores"]["MNQ"]["last_date"], "2026-07-30")

    def test_corrupt_files_become_error_panels_not_crashes(self):
        tmp = tempfile.mkdtemp()
        det = os.path.join(tmp, "data", "integration", "topstepx",
                           "deterministic")
        os.makedirs(det)
        with open(os.path.join(det, "session_state.json"), "w") as fh:
            fh.write("{not json")
        status = collect_status(tmp)
        self.assertEqual(status["panels"]["money_venue"]["status"], "ERROR")


class TestRenderer(unittest.TestCase):
    def test_self_contained_no_network_no_script(self):
        page = render_html(collect_status(tempfile.mkdtemp()))
        low = page.lower()
        self.assertNotIn("http://", low)
        self.assertNotIn("https://", low)
        self.assertNotIn("<script", low)
        self.assertIn("<style>", low)
        self.assertIn("mission control", low)

    def test_hostile_telemetry_text_is_escaped(self):
        tmp = tempfile.mkdtemp()
        det = os.path.join(tmp, "data", "integration", "topstepx",
                           "deterministic")
        os.makedirs(det)
        json.dump({"account": "<script>alert(1)</script>"},
                  open(os.path.join(det, "session_state.json"), "w"))
        page = render_html(collect_status(tmp))
        self.assertNotIn("<script>alert", page)
        self.assertIn("&lt;script&gt;", page)

    def test_stop_file_banner(self):
        tmp = tempfile.mkdtemp()
        det = os.path.join(tmp, "data", "integration", "topstepx",
                           "deterministic")
        os.makedirs(det)
        open(os.path.join(det, "STOP"), "w").close()
        page = render_html(collect_status(tmp))
        self.assertIn("LANE HALTED", page)

    def test_render_writes_single_file_only(self):
        tmp = tempfile.mkdtemp()
        before = {os.path.join(dp, f) for dp, _dn, fs in os.walk(tmp)
                  for f in fs}
        out = render(tmp, os.path.join("data", "ops", "MC.html"))
        after = {os.path.join(dp, f) for dp, _dn, fs in os.walk(tmp)
                 for f in fs}
        self.assertEqual(after - before, {out})
        self.assertTrue(open(out, encoding="utf-8").read()
                        .startswith("<!doctype html>"))


if __name__ == "__main__":
    unittest.main()
