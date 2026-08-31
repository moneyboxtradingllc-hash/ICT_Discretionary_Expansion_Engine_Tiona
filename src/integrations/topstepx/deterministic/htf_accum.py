"""HTF-MNQ-ACCUM (2026-07-30) — passive multi-day memory for the money venue.

The HTF wiring audit found the MNQ era had NO multi-day memory at all: no
data/htf_memory/MNQ.json, and zero prior-day facts in the deterministic lane.
This module fixes only the ACCUMULATION half: every scan's real 1m bars are
folded into the same HtfMemoryEngine store the QQQ lane uses, keyed "MNQ",
so memory exists (and deepens daily) before any consumer earns access to it.

WRITE-ONLY DOCTRINE (test-locked in tests/test_htf_mnq_accum.py):
  * The deterministic author, facts provider, and risk modules never read
    HTF context — the 20-condition gate is byte-identical with or without
    this module. Consumption is a SEPARATE future mission gated on depth,
    quality, semantics, replay support, and A/B evidence (roadmap Track 2).
  * accumulate() never raises — a memory defect must not cost a scan.

Store key is canonical "MNQ" across contract months (SEP26/DEC26/...).
Contract rolls will therefore print gap artifacts in gap_context around roll
dates; any future consumer must handle roll gaps explicitly. Recorded here
so the caveat ships with the data's birth, not its first use.
"""
from __future__ import annotations

_SYMBOL = "MNQ"
_engine = None


def _reset() -> None:
    """Test seam: drop the singleton so HTF_MEMORY_DIR changes take effect."""
    global _engine
    _engine = None


def accumulate(bars: list) -> "dict | None":
    """Fold this scan's real 1m bars into data/htf_memory/MNQ.json.
    Returns the HTF context dict for TELEMETRY ONLY (e.g. logging memory_age).
    Never raises; returns None on any failure."""
    global _engine
    try:
        if _engine is None:
            from market_data.htf_memory_engine import HtfMemoryEngine
            _engine = HtfMemoryEngine(symbol=_SYMBOL)
        return _engine.update(bars or [])
    except Exception:  # noqa: BLE001 — memory must never cost a scan
        return None
