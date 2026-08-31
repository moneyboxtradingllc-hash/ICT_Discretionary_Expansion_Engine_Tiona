"""TOOLBOX-EXECUTION-PRICE-ORDERING-1 — the toolbox must know where price is.

`_reanchor_location` answers "where is price relative to this zone" from
`snapshot["execution_price"]`. That block used to be attached AFTER
`build_snapshot()` returned, while `run_toolbox()` runs INSIDE it -- so every
zone was built against a snapshot with no price:

    location_basis   execution_price_absent
    price_relation   unknown
    current_price    None
    distance_to_zone None
    invalidated      False        <-- even when price HAD breached it

The last line is why this is a defect rather than a missing nicety: a zone whose
invalidation was already broken arrived at the Brain looking live. We cannot
hand Luna a dead tool and then call her refusal poor judgment.

ONE SCAN -> ONE GOVERNED BLOCK -> BOTH CONSUMERS. The caller captures the block
once and passes it in; nothing re-reads the provider, so the price the toolbox
measured against IS the price the Brain is shown.

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

from market_data.snapshot_builder import build_snapshot            # noqa: E402
from toolbox.toolbox_engine import run_toolbox                     # noqa: E402

ARCHIVE = os.path.join(ROOT, "data", "ai_brain", "20260821_102511_MNQ.json")

#: LOCATION vs GEOMETRY. `price_levels` declares these disjoint; this file
#: measures that rather than trusting the declaration.
LOCATION = ("current_price", "distance_to_zone", "price_relation",
            "entered_zone", "invalidated", "location_basis")
GEOMETRY = ("level_type", "zone_low", "zone_high", "mean_threshold",
            "source_tf", "temporal_class", "execution_eligible",
            "invalidation_level", "direction", "tool", "tool_family")


def snap():
    if not os.path.exists(ARCHIVE):
        pytest.skip("archived production snapshot absent")
    with open(ARCHIVE, encoding="utf-8") as fh:
        return copy.deepcopy(json.load(fh)["raw_snapshot"])


def zones(toolbox: dict) -> list:
    out = []

    def walk(o, d=0):
        if d > 4:
            return
        if isinstance(o, dict):
            if "zone_low" in o and "location_basis" in o:
                out.append(o)
            for v in o.values():
                walk(v, d + 1)
        elif isinstance(o, list):
            for v in o:
                walk(v, d + 1)

    walk(toolbox)
    return out


# ══════════════════════════════════════════════════════════════════════════════
class TestProductionOrdering:
    """1. The block exists before the toolbox runs."""

    def test_build_snapshot_accepts_the_block(self):
        import inspect
        assert "execution_price" in inspect.signature(build_snapshot).parameters

    def test_the_block_is_attached_before_run_toolbox(self):
        """Source order, checked structurally: the assignment must precede the
        call, otherwise the toolbox sees a snapshot without it."""
        import inspect
        src = inspect.getsource(build_snapshot)
        assign = src.index('snapshot["execution_price"]')
        call = src.index('run_toolbox(snapshot)')
        assert assign < call, "execution_price is still attached after the toolbox"

    def test_the_scan_captures_it_before_building(self):
        import inspect
        from live_scan.production_scan_cycle import ProductionScanCycle
        src = inspect.getsource(ProductionScanCycle.scan)
        capture = src.index("execution_price = self._execution_price()")
        build = src.index("build_snapshot(")
        assert capture < build, "the scan still captures the price after building"


class TestSingleAuthority:
    """2. One scan -> one provider read -> one block, both consumers."""

    def test_the_provider_is_read_exactly_once_per_scan(self):
        import inspect
        from live_scan.production_scan_cycle import ProductionScanCycle
        src = inspect.getsource(ProductionScanCycle.scan)
        assert src.count("self._execution_price()") == 1, (
            "the quote provider is read more than once in a single scan; the "
            "toolbox could measure against a different price than the Brain sees")

    def test_the_block_the_toolbox_used_is_the_block_exposed(self):
        """Identity, not equality: the same object must reach both."""
        marker = {"schema": "execution_price.v1", "available": True,
                  "fresh": True, "best_bid": 1.0, "best_ask": 2.0,
                  "bullish_executable": 2.0, "bearish_executable": 1.0,
                  "unavailable_reason": None, "age_seconds": 0.1,
                  "max_age_seconds": 5.0}
        s = snap()
        out = build_snapshot({tf: s["timeframes"][tf]["recent_candles"]
                              for tf in ("1m", "3m", "5m", "15m")},
                             symbol="MNQ", contract_id="CON.F.US.MNQ.U26",
                             execution_price=marker)
        assert out["execution_price"] is marker


class TestLocationBecomesTruthful:
    """3. The fields Luna reads now reflect the governed price."""

    @pytest.fixture(scope="class")
    def pair(self):
        s = snap()
        with_px = run_toolbox(copy.deepcopy(s))
        without = copy.deepcopy(s)
        without.pop("execution_price", None)
        return zones(with_px), zones(run_toolbox(without))

    def test_the_basis_names_the_execution_price(self, pair):
        a, _ = pair
        assert a and all(z.get("location_basis") == "execution_price" for z in a)

    def test_current_price_is_populated(self, pair):
        a, b = pair
        assert all(z.get("current_price") is not None for z in a)
        assert all(z.get("current_price") is None for z in b)   # the old behaviour

    def test_relation_and_distance_are_answered(self, pair):
        a, b = pair
        assert any(z.get("price_relation") != "unknown" for z in a)
        assert all(z.get("price_relation") == "unknown" for z in b)
        assert any(z.get("distance_to_zone") is not None for z in a)

    def test_A_BREACHED_ZONE_REPORTS_INVALIDATED(self, pair):
        """THE DEFECT. Without a price nothing can be invalidated, so a zone
        whose invalidation was already broken presented as live."""
        a, b = pair
        assert any(z.get("invalidated") is True for z in a), (
            "no zone reports invalidated even with a governed price")
        assert all(z.get("invalidated") is False for z in b), (
            "the price-free path should be unable to invalidate anything")


class TestGeometryIsInvariant:
    """4. We added location knowledge, not different setups."""

    def test_same_zones_and_identical_geometry(self):
        s = snap()
        a = zones(run_toolbox(copy.deepcopy(s)))
        s2 = copy.deepcopy(s)
        s2.pop("execution_price", None)
        b = zones(run_toolbox(s2))
        assert len(a) == len(b) and a, "the zone set changed"
        diffs = [(i, f, x.get(f), y.get(f))
                 for i, (x, y) in enumerate(zip(a, b))
                 for f in GEOMETRY if x.get(f) != y.get(f)]
        assert not diffs, f"geometry moved: {diffs[:5]}"

    def test_location_really_does_change(self):
        """Otherwise the invariance above would be vacuous."""
        s = snap()
        a = zones(run_toolbox(copy.deepcopy(s)))
        s2 = copy.deepcopy(s)
        s2.pop("execution_price", None)
        b = zones(run_toolbox(s2))
        n = sum(1 for x, y in zip(a, b) for f in LOCATION if x.get(f) != y.get(f))
        assert n > 0, "no location field changed — the specimen proves nothing"


class TestHistoricalPathStaysPriceFree:
    """5. Replaying an archived window must not inherit a present-time quote."""

    def test_the_key_stays_ABSENT_exactly_as_before(self):
        """SHAPE PRESERVATION, not the new behaviour.

        Measured against bca8a4f: the pre-repair `build_snapshot` never
        mentioned `execution_price`, so the historical rebuild returned a
        31-key snapshot with no such key. An empty dict would satisfy
        `_reanchor_location` identically while still drifting the archived
        schema, so absence -- not emptiness -- is what this pins.
        """
        s = snap()
        raw = {tf: s["timeframes"][tf]["recent_candles"]
               for tf in ("1m", "3m", "5m", "15m")}
        out = build_snapshot(raw, symbol="MNQ", contract_id="CON.F.US.MNQ.U26")
        assert "execution_price" not in out, "historical snapshot shape drifted"

        # The delta is EXACTLY one key, and only on the live path. A raw key
        # COUNT would be wrong here: importing `production_scan_cycle` enables
        # the optional `volume_witness` block, so the total is import-dependent
        # and says nothing about this repair. The key SET difference does.
        live = build_snapshot(raw, symbol="MNQ", contract_id="CON.F.US.MNQ.U26",
                              execution_price={"schema": "execution_price.v1"})
        assert set(live) - set(out) == {"execution_price"}
        assert set(out) - set(live) == set()

    def test_and_the_toolbox_still_reports_absent(self):
        s = snap()
        out = build_snapshot({tf: s["timeframes"][tf]["recent_candles"]
                              for tf in ("1m", "3m", "5m", "15m")},
                             symbol="MNQ", contract_id="CON.F.US.MNQ.U26")
        z = zones(out.get("toolbox") or {})
        assert z, "no zones produced — the assertion below would be vacuous"
        for x in z:
            assert x.get("location_basis") == "execution_price_absent"
            assert x.get("current_price") is None

    def test_the_rebuild_call_site_passes_no_price(self):
        """The historical re-derivation must not hand in a live quote."""
        import ast
        import inspect
        import textwrap
        from live_scan.production_scan_cycle import ProductionScanCycle
        src = textwrap.dedent(inspect.getsource(ProductionScanCycle))
        for node in ast.walk(ast.parse(src)):
            if (isinstance(node, ast.Call)
                    and getattr(node.func, "id", "") == "build_snapshot"):
                kw = {k.arg for k in node.keywords}
                if "memory" not in kw:            # the rebuild call, not the scan
                    assert "execution_price" not in kw, (
                        "the historical rebuild is being handed a live quote")
