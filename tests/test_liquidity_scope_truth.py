"""LUNA-LIQUIDITY-SCOPE-TRUTH-1 — scope is a causal fact, not a current opinion.

THE DEFECT. `manipulation_detector` already knew external from internal and
weighted them 30 vs 20 -- then recomputed both every scan against a rolling
`candles[-40:]` pivot context. Proven: the identical candle reads EXTERNAL
against pivots [100, 110] and INTERNAL against [100, 110, 120]. A later, higher
swing rewrote what an earlier event WAS.

WHAT IS AND IS NOT UNDER TEST. These prove that scope is captured at event time,
against a NAMED reference, and never rewritten. Not one asserts a direction to
trade. `external` + `sell_side` + `reclaimed` is three facts, not a signal, and
a predicate below rejects that vocabulary outright.
"""
import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))

from market_data.liquidity_scope import (              # noqa: E402
    EXTERNAL, INTERNAL, MANIPULATION_PIVOT_CONTEXT, SESSION_PO3_ACCUMULATION_RANGE,
    UNKNOWN, detector_reference, po3_reference, stamp)
from market_data.sweep_occurrence import liquidity_sweep_occurrence  # noqa: E402


def sweep(side, level, **kw):
    f = {"event_time": "2026-09-01T13:40:00+00:00",
         "sweep_direction": "below_low" if side == "sell_side" else "above_high",
         "liquidity_side_taken": side, "swept_level": level,
         "reclaimed": True, "reclaimed_at": "2026-09-01T13:40:00+00:00",
         "reclaim_basis": "same_bar_close_back_through_level",
         "source_bars": ["2026-09-01T13:39:00+00:00", "2026-09-01T13:40:00+00:00"]}
    f.update(kw)
    return f


def po3(high, low, *, birth="2026-09-01T13:45:00+00:00",
        last="2026-09-01T14:22:00+00:00", established=True):
    return {"high": high, "low": low, "birth": birth, "last_extension": last,
            "established": established, "age_bars": 43}


class TestDetectorScope:
    """A–D: the four scope cases against the pivot context."""

    def test_A_internal_buy_side(self):
        r = stamp(sweep("buy_side", 110), highs=[110, 120], lows=[90])
        assert r["detector_scope"] == INTERNAL

    def test_B_external_buy_side(self):
        r = stamp(sweep("buy_side", 120), highs=[110, 120], lows=[90])
        assert r["detector_scope"] == EXTERNAL

    def test_C_internal_sell_side(self):
        r = stamp(sweep("sell_side", 95), highs=[110], lows=[90, 95])
        assert r["detector_scope"] == INTERNAL

    def test_D_external_sell_side(self):
        r = stamp(sweep("sell_side", 90), highs=[110], lows=[90, 95])
        assert r["detector_scope"] == EXTERNAL

    def test_each_side_is_judged_against_its_own_boundary(self):
        """A buy-side sweep says nothing about the low, and vice versa."""
        r = stamp(sweep("buy_side", 120), highs=[110, 120], lows=[50])
        assert r["detector_scope"] == EXTERNAL      # decided by the HIGH only

    def test_an_unjudgeable_input_is_unknown_never_a_guessed_side(self):
        for bad in (stamp(sweep("sell_side", None), highs=[110], lows=[90]),
                    stamp(sweep("nonsense", 90), highs=[110], lows=[90]),
                    stamp(sweep("sell_side", 90), highs=[], lows=[])):
            assert bad["detector_scope"] == UNKNOWN

    def test_it_never_raises(self):
        for bad in (None, {}, "x", 7, {"liquidity_side_taken": None}):
            assert stamp(bad)["detector_scope"] in (INTERNAL, EXTERNAL, UNKNOWN)


class TestEventTimeImmutability:
    """E: THE DEFECT. Later context must not rewrite an earlier event."""

    def test_E_a_later_pivot_set_does_not_change_a_frozen_stamp(self):
        f = sweep("sell_side", 29062.75)
        at_event = stamp(f, highs=[29140.5], lows=[29062.75, 29104.5])
        assert at_event["detector_scope"] == EXTERNAL

        # The market later prints a LOWER low. A NEW stamp legitimately differs.
        later = stamp(f, highs=[29140.5], lows=[29040.0, 29062.75])
        assert later["detector_scope"] == INTERNAL

        # The frozen one is untouched. This is the whole unit.
        assert at_event["detector_scope"] == EXTERNAL

    def test_the_occurrence_carries_the_frozen_scope(self):
        f = sweep("sell_side", 29062.75)
        f.update(stamp(f, highs=[29140.5], lows=[29062.75]))
        occ = liquidity_sweep_occurrence(f, source_tf="1m",
                                         contract="CON.F.US.MNQ.U26")
        assert occ["detector_scope"] == EXTERNAL
        assert occ["detector_scope_reference"]["reference_snapshot_id"]

    def test_the_reference_is_named_not_implied(self):
        r = stamp(sweep("sell_side", 90), highs=[110], lows=[90])
        assert r["detector_scope_reference"]["type"] == MANIPULATION_PIVOT_CONTEXT


class TestRangeIdentityVersusSnapshot:
    """A range that extends is still the SAME range."""

    def test_range_id_survives_a_legitimate_extension(self):
        v4 = po3_reference(po3(29179.0, 29074.5), session_date="20260901")
        v5 = po3_reference(po3(29210.0, 29074.5, last="2026-09-01T14:40:00+00:00"),
                           session_date="20260901")
        assert v4["range_id"] == v5["range_id"]

    def test_the_snapshot_id_versions_with_the_boundaries(self):
        v4 = po3_reference(po3(29179.0, 29074.5), session_date="20260901")
        v5 = po3_reference(po3(29210.0, 29074.5, last="2026-09-01T14:40:00+00:00"),
                           session_date="20260901")
        assert v4["reference_snapshot_id"] != v5["reference_snapshot_id"]

    def test_a_different_birth_is_a_different_range(self):
        a = po3_reference(po3(100, 90, birth="2026-09-01T13:45:00+00:00"),
                          session_date="20260901")
        b = po3_reference(po3(100, 90, birth="2026-09-01T15:10:00+00:00"),
                          session_date="20260901")
        assert a["range_id"] != b["range_id"]

    def test_identity_is_deterministic_across_processes(self):
        a = po3_reference(po3(29179.0, 29074.5), session_date="20260901")
        b = po3_reference(po3(29179.0, 29074.5), session_date="20260901")
        assert a["range_id"] == b["range_id"]
        assert a["reference_snapshot_id"] == b["reference_snapshot_id"]

    def test_the_pivot_context_claims_no_stable_identity(self):
        """A rolling window has no continuity to claim; saying otherwise would
        assert a persistence the mechanism does not have."""
        ref = detector_reference([110], [90], context_start="a", context_end="b")
        assert ref["range_id"] is None
        assert ref["reference_snapshot_id"]


class TestPo3Scope:
    """F–I: the session authority, and what it refuses to say."""

    def test_F_detector_internal_with_po3_external_keeps_both(self):
        r = stamp(sweep("sell_side", 29074.0), highs=[29200], lows=[29000, 29074.0],
                  po3_range=po3(29179.0, 29074.5), session_date="20260901")
        assert r["detector_scope"] == INTERNAL      # inside a wide pivot context
        assert r["po3_scope"] == EXTERNAL          # below the accumulation low
        assert r["po3_scope_reference"]["type"] == SESSION_PO3_ACCUMULATION_RANGE

    def test_G_detector_external_with_po3_internal_keeps_both(self):
        r = stamp(sweep("sell_side", 29100.0), highs=[29150], lows=[29100.0],
                  po3_range=po3(29179.0, 29074.5), session_date="20260901")
        assert r["detector_scope"] == EXTERNAL
        assert r["po3_scope"] == INTERNAL

    def test_H_no_established_range_yields_unknown_not_internal(self):
        r = stamp(sweep("sell_side", 90), highs=[110], lows=[90], po3_range=None)
        assert r["po3_scope"] == UNKNOWN
        assert r["po3_scope_reference"] is None
        assert "not internal" in (r["scope_reason"] or "")

    def test_a_forming_range_has_no_authority_to_say_what_is_outside_it(self):
        r = stamp(sweep("sell_side", 90), highs=[110], lows=[90],
                  po3_range=po3(120, 100, established=False))
        assert r["po3_scope"] == UNKNOWN

    def test_I_a_range_established_afterwards_does_not_relabel_the_event(self):
        """The event is stamped once. A range that forms later is not evidence
        about what was outside anything at the time."""
        f = sweep("sell_side", 29060.0)
        at_event = stamp(f, highs=[29150], lows=[29060.0], po3_range=None,
                         session_date="20260901")
        assert at_event["po3_scope"] == UNKNOWN
        # a range exists NOW -- a new stamp would classify, the old one does not
        later = stamp(f, highs=[29150], lows=[29060.0],
                      po3_range=po3(29179.0, 29074.5), session_date="20260901")
        assert later["po3_scope"] == EXTERNAL
        assert at_event["po3_scope"] == UNKNOWN


class TestScopeIsNotDirection:
    """J, N: facts, never permission."""

    def test_J_rejection_is_preserved_without_directional_implication(self):
        f = sweep("sell_side", 90)
        f.update(stamp(f, highs=[110], lows=[90]))
        occ = liquidity_sweep_occurrence(f, source_tf="1m",
                                         contract="CON.F.US.MNQ.U26")
        assert occ["reclaimed"] is True
        assert occ["detector_scope"] == EXTERNAL
        blob = repr(occ).lower()
        for verb in ("bullish", "bearish", "buy", "sell_signal", "long",
                     "entry", "target", "bias", "permission"):
            assert verb not in blob, verb

    def test_N_the_scope_module_names_no_trade(self):
        import ast as _ast
        src = open(os.path.join(ROOT, "src", "market_data",
                                "liquidity_scope.py"), encoding="utf-8").read()
        tree = _ast.parse(src)
        # STRUCTURAL: string CONSTANTS only, so the prose explaining what the
        # module refuses to do cannot trip its own guard.
        consts = {n.value.lower() for n in _ast.walk(tree)
                  if isinstance(n, _ast.Constant) and isinstance(n.value, str)}
        for verb in ("bullish", "bearish", "long", "short", "buy", "sell"):
            assert verb not in consts, verb

    def test_side_and_scope_are_independent_facts(self):
        ext_sell = stamp(sweep("sell_side", 90), highs=[110], lows=[90])
        int_sell = stamp(sweep("sell_side", 95), highs=[110], lows=[90, 95])
        assert ext_sell["detector_scope"] != int_sell["detector_scope"]
        # same side, different scope -- neither implies the other
        assert ext_sell["detector_scope"] == EXTERNAL
        assert int_sell["detector_scope"] == INTERNAL


class TestReconstruction:
    """L: the same facts rebuild the same scope, in any process."""

    def test_L_a_rebuild_yields_an_identical_stamp(self):
        f = sweep("sell_side", 29062.75)
        a = stamp(f, highs=[29140.5], lows=[29062.75], po3_range=po3(29179.0, 29074.5),
                  session_date="20260901")
        b = stamp(f, highs=[29140.5], lows=[29062.75], po3_range=po3(29179.0, 29074.5),
                  session_date="20260901")
        assert a == b

    def test_reconstruction_uses_the_event_time_reference_not_the_latest(self):
        """A replay handed the historical reference reproduces the historical
        answer -- which is only possible because the reference travels with the
        event instead of being looked up again."""
        f = sweep("sell_side", 29062.75)
        historical = stamp(f, highs=[29140.5], lows=[29062.75])
        assert historical["detector_scope"] == EXTERNAL
        assert historical["detector_scope_reference"]["outer_low"] == 29062.75


class TestScopeRequiresAProvenOccurrence:
    """SCOPE ENRICHES A PROVEN EVENT. IT NEVER MANUFACTURES ONE.

    The correction that produced this class: a forensic reconstruction claimed
    the 2026-09-01 09:39 sweep was EXTERNAL, but that answer was obtained with
    `allow_uncadenced=True` -- a legacy geometry opt-in production never sets.
    Under production evidence law the re-fetched bars carry no
    `source_member_times`, every pivot is withheld, and there is no sweep to
    scope at all. Geometry truth is not event truth.
    """

    def _bare_ohlc(self, n=80):
        """Historical OHLC with NO source-member provenance -- the exact shape a
        re-fetch returns, and the shape canonical evidence must refuse."""
        from datetime import datetime, timedelta, timezone
        t0 = datetime(2026, 9, 1, 13, 0, tzinfo=timezone.utc)
        out = []
        for i in range(n):
            off = (i % 5) * 6.0 - (i % 3) * 4.0
            t = t0 + timedelta(minutes=i)
            out.append({"timestamp": t.isoformat(), "open": 29100 + off,
                        "high": 29105 + off, "low": 29095 + off,
                        "close": 29101 + off})
        out.append({"timestamp": (t0 + timedelta(minutes=n)).isoformat(),
                    "open": 29090, "high": 29095, "low": 29050, "close": 29092})
        return out

    def test_1_no_member_provenance_yields_no_lawful_sweep(self):
        from structure.liquidity_engine import analyze_liquidity
        r = analyze_liquidity(self._bare_ohlc(), None)      # production default
        assert r.get("sweep_fact") is None

    def test_2_no_lawful_sweep_means_no_scope_fact_at_all(self):
        """Absent, not `unknown`. UNKNOWN is for a PROVEN event whose scope
        authority is unavailable; it must never stand in for an event that was
        never proven."""
        from structure.liquidity_engine import analyze_liquidity
        r = analyze_liquidity(self._bare_ohlc(), None)
        assert r.get("sweep_fact") is None
        blob = repr(r)
        assert "detector_scope" not in blob

    def test_3_relaxed_geometry_is_diagnostic_never_production(self):
        """The opt-in can classify geometry. Production does not set it, and a
        result obtained under it is not an event fact."""
        from structure.liquidity_engine import analyze_liquidity
        bars = self._bare_ohlc()
        relaxed = analyze_liquidity(bars, None, allow_uncadenced=True)
        production = analyze_liquidity(bars, None)
        assert relaxed.get("sweep_fact") is not None        # geometry sees it
        assert production.get("sweep_fact") is None         # authority does not

    def test_production_never_enables_the_geometry_opt_in(self):
        """AST: no production caller may pass allow_uncadenced=True."""
        import ast as _ast
        for rel in ("src/market_data/snapshot_builder.py",
                    "src/live_scan/production_scan_cycle.py"):
            src = open(os.path.join(ROOT, rel), encoding="utf-8").read()
            for node in _ast.walk(_ast.parse(src)):
                if not isinstance(node, _ast.Call):
                    continue
                for kw in node.keywords or []:
                    if kw.arg == "allow_uncadenced":
                        assert not (isinstance(kw.value, _ast.Constant)
                                    and kw.value.value is True), rel

    def test_4_the_mutation_theorem_stands_on_lawful_pivots(self):
        """The root defect did NOT depend on relaxed geometry: it is proven by
        handing the classifier explicit pivot sets."""
        f = sweep("sell_side", 100.0)
        at_event = stamp(f, highs=[130], lows=[100.0, 110.0])
        later = stamp(f, highs=[130], lows=[90.0, 100.0])
        assert at_event["detector_scope"] == EXTERNAL
        assert later["detector_scope"] == INTERNAL
        assert at_event["detector_scope"] == EXTERNAL       # frozen


class TestTodayIsRepresentationOnly:
    """§15 forensic, recorded as what production can and cannot prove."""

    def test_the_0939_event_is_unproven_under_production_evidence_law(self):
        """NOT `external`. The historical tape available for reconstruction
        carries no source-member provenance, so production withholds the pivots
        and never mints the sweep. Asserting EXTERNAL here would encode a
        relaxed-geometry answer as certified truth."""
        from structure.liquidity_engine import analyze_liquidity
        bars = TestScopeRequiresAProvenOccurrence()._bare_ohlc()
        assert analyze_liquidity(bars, None).get("sweep_fact") is None

    def test_po3_scope_was_unknown_because_no_range_existed_yet(self):
        """The accumulation range was born at 13:45Z -- six minutes AFTER the
        09:39 event. A range that forms later is not evidence about what was
        outside anything earlier."""
        r = stamp(sweep("sell_side", 29062.75), highs=[29172.0], lows=[29062.75],
                  po3_range=None, session_date="20260901")
        assert r["po3_scope"] == UNKNOWN
        assert r["po3_scope_reference"] is None


class TestLiquidityProducersAreSealed:
    """CLOSURE: an isolated edit to any liquidity-truth producer must invalidate
    a minted authorization.

    Two of these were the reason the audit widened. `po3_config` is a CONSTANTS
    file, and `MANIP_CONTEXT` decides which pivots exist -- measured, narrowing
    it flips the same event from external to internal. `snapshot_builder` merely
    threads `timeframe=tf` into a component -- measured, deleting that one kwarg
    turns a PROVEN occurrence link into UNPROVEN. Neither looks like a semantic
    authority until you ask what a change there does to what Luna believes.
    """

    CASES = [
        ("liquidity_scope", "src/market_data/liquidity_scope.py",
         b'SCHEMA = "liquidity_scope.v1"'),
        ("sweep_occurrence", "src/market_data/sweep_occurrence.py",
         b"detector_scope"),
        ("liquidity_engine", "src/structure/liquidity_engine.py", b"_scope_stamp"),
        ("manipulation_detector", "src/structure/manipulation_detector.py",
         b"W_EXTERNAL_SWEEP = 30"),
        ("direction_vote", "src/structure/direction_vote.py", b"def "),
        ("session_po3", "src/structure/session_po3.py", b"MAX_TRANSITIONS"),
        ("po3_config", "src/structure/po3_config.py", b"MANIP_CONTEXT = 40"),
        ("snapshot_builder", "src/market_data/snapshot_builder.py", b"timeframe=tf"),
        ("production_scan_cycle", "src/live_scan/production_scan_cycle.py",
         b"_prior_po3_range"),
    ]

    @pytest.mark.parametrize("label,rel,needle", CASES, ids=[c[0] for c in CASES])
    def test_an_isolated_semantic_edit_moves_the_fingerprint(self, label, rel, needle):
        import shutil
        import tempfile
        from ai_brain import production_model as PM

        path = os.path.join(ROOT, rel)
        raw = open(path, "rb").read()
        assert needle in raw, "anchor %r moved; this test would silently pass" % needle
        before = PM.brain_contract_fingerprint()
        bak = tempfile.NamedTemporaryFile(delete=False).name
        shutil.copyfile(path, bak)
        try:
            open(path, "wb").write(raw.replace(needle, needle + b"  # mutation", 1))
            after = PM.brain_contract_fingerprint()
        finally:
            shutil.copyfile(bak, path)
            os.unlink(bak)
        assert open(path, "rb").read() == raw, "byte restore failed"
        assert after != before, "%s is NOT sealed by the Brain closure" % label
        assert PM.brain_contract_fingerprint() == before

    def test_every_liquidity_producer_is_a_declared_closure_source(self):
        from ai_brain.production_model import (_CONTRACT_SOURCES,
                                               _CONTRACT_SOURCES_REPO)
        bound = {r for _, r in _CONTRACT_SOURCES} | {r for _, r in _CONTRACT_SOURCES_REPO}
        for rel in ("market_data/liquidity_scope.py",
                    "market_data/sweep_occurrence.py",
                    "structure/liquidity_engine.py",
                    "structure/manipulation_detector.py",
                    "structure/direction_vote.py",
                    "structure/session_po3.py",
                    "structure/po3_config.py",
                    "market_data/snapshot_builder.py",
                    "live_scan/production_scan_cycle.py"):
            assert rel in bound, rel
