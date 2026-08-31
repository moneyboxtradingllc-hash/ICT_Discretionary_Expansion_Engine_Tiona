"""PRIOR-SESSION-DEGRADATION-TRUTHFULNESS-1 — `degraded[]` must not lie.

`prior_session_levels_absent` was appended UNCONDITIONALLY. It was written for
the MAP-0 data plane, which genuinely had no yesterday. HTF-MEM-1 shipped
2026-07-04 and has published prior-day OHLC, swept/untapped draws and gap
context ever since, so the payload was simultaneously telling the Brain:

    liquidity_context   untapped_draws [{buy_side, 29759.00, distance 354.75}]
                        previous_low_swept True
    degraded            ["prior_session_levels_absent"]

A degradation marker is a statement about what the Brain CANNOT see. Emitting it
falsely is worse than omitting it, because the Brain reads `degraded[]` and
hedges against context it actually holds.

This file pins BOTH directions. Deleting the marker outright would have been the
easy fix and the wrong one: when HTF memory genuinely cannot serve a prior
session -- day one, or a reset store -- the Brain must still be told.

No network. No model. No order.
"""
from __future__ import annotations

import copy
import json
import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))

from ai_brain.brain_input import build_brain_input                 # noqa: E402

ARCHIVE = os.path.join(ROOT, "data", "ai_brain", "20260821_102511_MNQ.json")
MARKER = "prior_session_levels_absent"


def snap():
    if not os.path.exists(ARCHIVE):
        pytest.skip("archived production snapshot absent")
    with open(ARCHIVE, encoding="utf-8") as fh:
        return copy.deepcopy(json.load(fh)["raw_snapshot"])


def degraded_for(s) -> list:
    return (build_brain_input(s, {}) or {}).get("degraded") or []


# ══════════════════════════════════════════════════════════════════════════════
class TestContextPresentMeansNoFalseMarker:
    """The defect: real prior-session data + a marker saying it is absent."""

    @pytest.fixture(scope="class")
    def payload(self):
        return build_brain_input(snap(), {}) or {}

    def test_the_prior_session_context_is_actually_there(self, payload):
        """Guard against a vacuous pass: if HTF memory were empty on this
        specimen, the assertion below would prove nothing."""
        psc = ((payload.get("htf_memory") or {}).get("previous_session_context")) or {}
        assert psc, "specimen carries no prior-session context"
        for f in ("high", "low", "close"):
            assert psc.get(f) is not None, f

    def test_liquidity_draws_are_published_too(self, payload):
        lc = ((payload.get("htf_memory") or {}).get("liquidity_context")) or {}
        assert "previous_high_swept" in lc and "previous_low_swept" in lc
        assert "untapped_draws" in lc

    def test_the_marker_is_NOT_emitted(self, payload):
        assert MARKER not in (payload.get("degraded") or []), (
            "the payload claims prior-session levels are absent while carrying them")


class TestGenuineAbsenceStillWarns:
    """The other half. Removing the marker outright would have been wrong."""

    def test_absent_context_emits_the_marker(self):
        s = snap()
        s["htf_memory"] = dict(s.get("htf_memory") or {},
                               previous_session_context=None)
        assert MARKER in degraded_for(s)

    def test_htf_memory_entirely_missing_emits_the_marker(self):
        s = snap()
        s.pop("htf_memory", None)
        assert MARKER in degraded_for(s)

    def test_the_engines_own_empty_shape_emits_the_marker(self):
        """Uses `HtfMemoryEngine._empty()` rather than a hand-built stand-in, so
        the test cannot drift from the engine's real representation of absence."""
        from market_data.htf_memory_engine import HtfMemoryEngine
        s = snap()
        s["htf_memory"] = HtfMemoryEngine(symbol="MNQ")._empty("no memory yet")
        assert MARKER in degraded_for(s)


class TestNothingElseMoved:
    def test_other_degradation_markers_are_untouched(self):
        """Only this marker's condition changed; continuity markers still flow."""
        s = snap()
        before = set(degraded_for(s))
        s["htf_memory"] = dict(s.get("htf_memory") or {},
                               previous_session_context=None)
        after = set(degraded_for(s))
        assert after - before == {MARKER}
        assert before - after == set()

    def test_the_condition_reads_the_engines_field_not_a_new_one(self):
        import ast
        import inspect
        import textwrap
        src = textwrap.dedent(inspect.getsource(build_brain_input))
        names = {n.value for n in ast.walk(ast.parse(src))
                 if isinstance(n, ast.Constant) and isinstance(n.value, str)}
        assert "previous_session_context" in names
        assert "htf_memory" in names
