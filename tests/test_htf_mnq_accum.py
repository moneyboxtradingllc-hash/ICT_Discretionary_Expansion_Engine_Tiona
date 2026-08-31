"""
HTF-MNQ-ACCUM — passive multi-day memory locks (2026-07-30).

The wiring audit found the MNQ era had no multi-day memory: no MNQ store
file, no prior-day facts in the deterministic lane. This mission adds
ACCUMULATION ONLY. Locks:

  * accumulate() folds real bars into data/htf_memory/MNQ.json (canonical
    "MNQ" key regardless of contract string) and deepens across days
  * idempotent: re-feeding the same bars changes nothing
  * never raises — malformed bars, hostile input, missing dirs
  * WRITE-ONLY doctrine: author.py / facts_provider.py / risk.py contain no
    HTF reference at all; loop.py touches HTF only through htf_accum
"""
import json
import os
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from integrations.topstepx.deterministic import htf_accum  # noqa: E402


def _bars(date: str, n: int = 30, px: float = 23000.0):
    from datetime import datetime, timedelta, timezone
    base = (datetime.strptime(date, "%Y%m%d")
            .replace(hour=13, minute=30, tzinfo=timezone.utc))
    out = []
    for i in range(n):
        px += 0.25 if i % 2 else -0.25
        out.append({"timestamp": (base + timedelta(minutes=i)).isoformat(),
                    "open": px, "high": px + 2.0, "low": px - 2.0,
                    "close": px + 0.5, "volume": 100.0})
    return out


class TestAccumulate(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self._e = patch.dict(os.environ, {"HTF_MEMORY_DIR": self.tmp})
        self._e.start()
        htf_accum._reset()

    def tearDown(self):
        self._e.stop()
        htf_accum._reset()

    def _store(self):
        with open(os.path.join(self.tmp, "MNQ.json"), encoding="utf-8") as fh:
            return json.load(fh)

    def test_bars_accumulate_into_canonical_mnq_store(self):
        ctx = htf_accum.accumulate(_bars("20260729") + _bars("20260730"))
        self.assertEqual(sorted(self._store()["days"]),
                         ["2026-07-29", "2026-07-30"])
        self.assertEqual(ctx["memory_age"], 1)      # one completed prior day
        self.assertEqual(ctx["authority_level"], "context_only")
        # canonical key: only MNQ.json, never a per-contract file
        self.assertEqual(os.listdir(self.tmp), ["MNQ.json"])

    def test_memory_deepens_across_sessions(self):
        htf_accum.accumulate(_bars("20260728"))
        htf_accum.accumulate(_bars("20260728") + _bars("20260729"))
        ctx = htf_accum.accumulate(_bars("20260729") + _bars("20260730"))
        self.assertEqual(len(self._store()["days"]), 3)
        self.assertEqual(ctx["memory_age"], 2)

    def test_idempotent_refeed(self):
        htf_accum.accumulate(_bars("20260729") + _bars("20260730"))
        before = self._store()
        htf_accum.accumulate(_bars("20260729") + _bars("20260730"))
        self.assertEqual(self._store(), before)

    def test_never_raises_on_hostile_input(self):
        for bad in (None, [], [None, 1, "x"], [{"timestamp": "garbage"}],
                    [{"open": float("nan")}]):
            self.assertIsInstance(htf_accum.accumulate(bad), (dict, type(None)))

    def test_write_only_doctrine_source_lock(self):
        lane = os.path.join(os.path.dirname(__file__), "..", "src",
                            "integrations", "topstepx", "deterministic")
        # author/facts/risk: ZERO htf references — the 20-gate never sees it
        for name in ("author.py", "facts_provider.py", "risk.py"):
            with open(os.path.join(lane, name), encoding="utf-8") as fh:
                self.assertNotIn("htf", fh.read().lower(),
                                 f"{name} must never reference HTF")
        # loop: HTF only through the accumulator seam
        with open(os.path.join(lane, "loop.py"), encoding="utf-8") as fh:
            src = fh.read()
        for line in src.splitlines():
            low = line.lower()
            if "htf" in low:
                self.assertTrue("htf_accum" in low or "htf-mnq-accum" in low
                                or "_htf_ctx" in low or "htf_memory_age" in low
                                or "data/htf_memory" in low,
                                f"unexpected HTF reference in loop.py: {line!r}")
        # and the context is never handed to the author or facts builder
        self.assertNotIn("evaluate(_htf_ctx", src)
        self.assertNotIn("build_facts(bars, quote, _htf_ctx", src)


if __name__ == "__main__":
    unittest.main()
