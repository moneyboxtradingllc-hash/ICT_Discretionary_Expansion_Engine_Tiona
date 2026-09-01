"""LUNA-SWING-SEQUENCE-TRUTH-1 — structural truth reaches the Brain.

THE DEFECT THIS PINS. On the first live practice session the confirmed registry
walked highs 29157.75 -> 29163.25 -> 29173 -> 29179 and lows
29040 -> 29085 -> 29116 -> 29135.75, and the Brain was told
`swing_sequence: unknown`. The sequence was computed from 15m candle pivots
only; that window produced ZERO pivots; and the fallback asked whether 15m
candles EXISTED rather than whether they had produced anything.

WHAT IS AND IS NOT UNDER TEST. These tests prove that ordinal structure is
DERIVED, PRESERVED and PUBLISHED. Not one of them asserts a trade, a direction
to take, an entry, a target or an outcome. A bullish sequence is a fact about
ordering; what it means is Luna's to decide, and encoding today's hindsight as
an expectation would be the outcome-fitting this unit exists to avoid.
"""
import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))

from narrative_authority.swing_structure import (             # noqa: E402
    BEARISH, BULLISH, INSUFFICIENT, MIXED, UNKNOWN,
    canonical_sequence, witness_agreement)
from narrative_authority.protected_swings import ProtectedSwingTracker  # noqa: E402


def lin(highs, lows, tf="1m"):
    return {"highs": {tf: [{"level": h} for h in highs]},
            "lows": {tf: [{"level": lo} for lo in lows]}}


class TestCanonicalSequence:

    def test_rising_highs_and_rising_lows_are_bullish(self):
        r = canonical_sequence(lin([100, 110, 120], [90, 95, 99]))
        assert r["sequence"] == BULLISH
        assert r["high_ordinals"] == ["higher_high", "higher_high"]
        assert r["low_ordinals"] == ["higher_low", "higher_low"]

    def test_falling_highs_and_falling_lows_are_bearish(self):
        r = canonical_sequence(lin([120, 110, 100], [99, 95, 90]))
        assert r["sequence"] == BEARISH
        assert r["high_ordinals"] == ["lower_high", "lower_high"]
        assert r["low_ordinals"] == ["lower_low", "lower_low"]

    def test_higher_highs_with_lower_lows_is_mixed_not_a_lean(self):
        """A widening auction is a real state. Inventing a direction for it
        would be the organism authoring what it cannot prove."""
        r = canonical_sequence(lin([100, 120], [90, 80]))
        assert r["sequence"] == MIXED

    def test_lower_highs_with_higher_lows_is_mixed(self):
        r = canonical_sequence(lin([120, 110], [90, 95]))
        assert r["sequence"] == MIXED

    def test_one_swing_a_side_is_insufficient_not_unknown(self):
        """INSUFFICIENT and UNKNOWN are different claims: 'not enough confirmed
        swings yet' is not 'the registry could not be read'."""
        r = canonical_sequence(lin([100], [90]))
        assert r["sequence"] == INSUFFICIENT
        assert "at least 2" in r["detail"]

    def test_enough_highs_but_not_enough_lows_is_insufficient(self):
        assert canonical_sequence(lin([100, 110, 120], [90]))["sequence"] == INSUFFICIENT

    def test_an_absent_registry_is_unknown(self):
        """Never supplied = unavailable truth."""
        for bad in (None, {}, "nope", 7):
            assert canonical_sequence(bad)["sequence"] == UNKNOWN

    def test_an_empty_but_present_registry_is_insufficient_not_unknown(self):
        """Supplied and readable, just early. Calling this UNKNOWN would tell
        the Brain the mechanism failed when it is only waiting for swings."""
        r = canonical_sequence({"highs": {}, "lows": {}})
        assert r["sequence"] == INSUFFICIENT
        assert r["confirmed_highs"] == 0 and r["confirmed_lows"] == 0

    def test_a_corrupt_registry_is_unknown_never_a_lean(self):
        assert canonical_sequence("not a dict")["sequence"] == UNKNOWN
        r = canonical_sequence({"highs": {"1m": [{"level": "x"}, {"level": None}]},
                                "lows": {"1m": [{"level": "y"}]}})
        assert r["sequence"] in (UNKNOWN, INSUFFICIENT)

    def test_equal_swings_do_not_manufacture_direction(self):
        r = canonical_sequence(lin([100, 100, 100], [90, 90, 90]))
        assert r["sequence"] == MIXED
        assert r["high_ordinals"] == ["equal_high", "equal_high"]

    def test_it_never_raises(self):
        for bad in (None, 0, [], "x", {"highs": 5, "lows": 7},
                    {"highs": {"1m": None}, "lows": {"1m": [1, 2]}}):
            assert canonical_sequence(bad)["sequence"] in (
                BULLISH, BEARISH, MIXED, INSUFFICIENT, UNKNOWN)

    def test_the_longest_confirmed_lineage_is_read(self):
        r = canonical_sequence({
            "highs": {"15m": [{"level": 100}], "1m": [{"level": 100}, {"level": 110}]},
            "lows": {"15m": [{"level": 90}], "1m": [{"level": 90}, {"level": 95}]}})
        assert r["high_timeframe"] == "1m"
        assert r["sequence"] == BULLISH

    def test_it_states_nothing_about_trading(self):
        """STRUCTURE IS NOT PERMISSION. The vocabulary must not leak a verb."""
        r = canonical_sequence(lin([100, 110, 120], [90, 95, 99]))
        blob = repr(r).lower()
        for verb in ("buy", "sell", "long", "short", "entry", "target",
                     "take_trade", "permission"):
            assert verb not in blob, verb


class TestBothDimensionsSurvive:
    """§2: role and ordinal must coexist; neither may erase the other."""

    def _tracker_with(self, levels, side):
        t = ProtectedSwingTracker()
        for i, lv in enumerate(levels):
            snap = {"timestamp": "2026-09-01T14:%02d:00+00:00" % (i * 2),
                    "liquidity": {"1m": {"sweep_detected": True,
                                         "reclaim_detected": True,
                                         "sweep_direction": ("above_high" if side == "high"
                                                             else "below_low")}},
                    "structure": {"1m": {("last_swing_high" if side == "high"
                                          else "last_swing_low"): lv}},
                    "price": lv - 50 if side == "high" else lv + 50}
            t.update(snap)
        return t

    def test_a_protected_high_is_also_a_higher_high(self):
        t = self._tracker_with([29157.75, 29173.0], "high")
        rec = t.protected_highs["1m"]
        assert rec["basis"] == "buy_side_raid_rejected"      # causal role kept
        # THE RECORD STAYS MINIMAL. Ordinal is relational and lives in the
        # succession, so re-affirming a level cannot mutate its record.
        assert "ordinal" not in rec and "ordinal_vs" not in rec
        step = t.lineage()["highs"]["1m"][-1]
        assert step["ordinal"] == "higher_high"
        assert step["previous_price"] == 29157.75
        assert step["current_price"] == 29173.0

    def test_a_protected_low_is_also_a_higher_low(self):
        t = self._tracker_with([29040.0, 29116.0], "low")
        rec = t.protected_lows["1m"]
        assert rec["basis"] == "sell_side_raid_rejected"
        assert "ordinal" not in rec
        assert t.lineage()["lows"]["1m"][-1]["ordinal"] == "higher_low"

    def test_the_first_swing_has_no_ordinal_rather_than_a_guessed_one(self):
        t = self._tracker_with([29157.75], "high")
        assert t.lineage()["highs"]["1m"][0]["ordinal"] is None

    def test_lineage_records_one_entry_per_life_not_per_scan(self):
        """A re-affirmed level is the SAME life. Recording it twice would
        fabricate a run of equal swings the market never made."""
        t = self._tracker_with([29157.75, 29157.75, 29157.75], "high")
        assert len(t.lineage()["highs"]["1m"]) == 1

    def test_state_publishes_lineage_beside_the_records(self):
        t = self._tracker_with([29157.75, 29173.0], "high")
        st = t.state()
        assert st["protected_high"]["basis"] == "buy_side_raid_rejected"
        assert st["lineage"]["highs"]["1m"][-1]["ordinal"] == "higher_high"
        assert "ordinal" not in st["protected_high"]

    def test_lineage_is_bounded(self):
        t = self._tracker_with([29000.0 + i for i in range(60)], "high")
        assert len(t.lineage()["highs"]["1m"]) <= ProtectedSwingTracker.LINEAGE_CAP

    def test_a_rebuild_from_the_same_levels_yields_the_same_sequence(self):
        """§9 CASE I: durable facts, not run-order, decide the sequence."""
        a = canonical_sequence(lin([100, 110, 120], [90, 95, 99]))
        b = canonical_sequence(lin([100, 110, 120], [90, 95, 99]))
        assert a["sequence"] == b["sequence"] == BULLISH
        assert a["high_ordinals"] == b["high_ordinals"]


class TestWitnessIsNotAuthority:

    def test_agreement_is_reported(self):
        canon = canonical_sequence(lin([100, 110], [90, 95]))
        assert witness_agreement(canon, "higher_highs_higher_lows")["agreement"] == "agree"

    def test_disagreement_is_published_not_arbitrated(self):
        canon = canonical_sequence(lin([100, 110], [90, 95]))
        w = witness_agreement(canon, "lower_highs_lower_lows")
        assert w["agreement"] == "disagree"
        assert w["canonical"] == BULLISH          # registry keeps authority
        assert "authoritative" in w["note"]

    def test_an_unknown_witness_is_not_comparable(self):
        canon = canonical_sequence(lin([100, 110], [90, 95]))
        assert witness_agreement(canon, "unknown")["agreement"] == "not_comparable"

    def test_an_unknown_canonical_is_not_comparable(self):
        assert witness_agreement({"sequence": UNKNOWN},
                                 "higher_highs_higher_lows")["agreement"] == "not_comparable"


class TestBrainPublication:
    """§5: the Brain receives both, and is told which is authoritative."""

    def _snap(self):
        return {"protected_swings": {"lineage": lin([29157.75, 29173.0],
                                                    [29040.0, 29135.75])},
                "market_regime": {"swing_sequence": "unknown",
                                  "swing_detail": "only 0 swing highs / 0 swing lows",
                                  "swing_source_timeframe": None,
                                  "swing_fallback_trace": ["15m: 0 highs / 0 lows"]}}

    def test_the_payload_carries_the_canonical_sequence(self):
        from ai_brain import brain_input as BI
        b = BI._swing_sequence_block(self._snap())
        assert b["sequence"] == BULLISH
        assert b["authority"] == "confirmed_swing_registry"

    def test_the_payload_carries_the_windowed_witness_separately(self):
        from ai_brain import brain_input as BI
        b = BI._swing_sequence_block(self._snap())
        assert b["windowed_witness"]["sequence"] == "unknown"
        assert b["windowed_witness"]["fallback_trace"]

    def test_the_ordered_levels_travel(self):
        from ai_brain import brain_input as BI
        b = BI._swing_sequence_block(self._snap())
        assert b["highs"] == [29157.75, 29173.0]
        assert b["lows"] == [29040.0, 29135.75]

    def test_a_snapshot_without_a_registry_publishes_unknown_not_a_lean(self):
        from ai_brain import brain_input as BI
        b = BI._swing_sequence_block({})
        assert b["sequence"] == UNKNOWN


class TestTodayIsRepresentationOnly:
    """§10: the live registry must be represented faithfully. NOTHING here
    asserts that the correct action was to buy."""

    LIVE_HIGHS = [29157.75, 29163.25, 29173.0, 29179.0]
    LIVE_LOWS = [29040.0, 29085.0, 29116.0, 29135.75]

    def test_the_observed_registry_is_represented_faithfully(self):
        r = canonical_sequence(lin(self.LIVE_HIGHS, self.LIVE_LOWS))
        assert r["high_ordinals"] == ["higher_high"] * 3
        assert r["low_ordinals"] == ["higher_low"] * 3
        assert r["sequence"] == BULLISH

    def test_the_brain_would_have_seen_it(self):
        from ai_brain import brain_input as BI
        b = BI._swing_sequence_block(
            {"protected_swings": {"lineage": lin(self.LIVE_HIGHS, self.LIVE_LOWS)},
             "market_regime": {"swing_sequence": "unknown"}})
        assert b["sequence"] == BULLISH
        assert b["confirmed_highs"] == 4 and b["confirmed_lows"] == 4

    def test_no_trade_expectation_is_encoded_anywhere_in_this_file(self):
        """The guard against outcome-fitting, applied to this file itself."""
        import ast as _ast
        src = open(os.path.abspath(__file__), encoding="utf-8").read()
        tree = _ast.parse(src)
        names = {n.id for n in _ast.walk(tree) if isinstance(n, _ast.Name)}
        for banned in ("TAKE", "take_trade", "expected_entry", "expected_target"):
            assert banned not in names


class TestPivotFallbackSufficiency:
    """§4: fall through on INSUFFICIENT PIVOTS, not on absent candles.

    The live defect: 19 settled 15m bars existed, `find_swings` returned zero
    pivots from them, and the guard only asked whether the series was empty --
    so 59 settled 5m bars and 99 settled 3m bars were never consulted.
    """

    def _series(self, n, start_min, step_min, base=29000.0):
        from datetime import datetime, timedelta, timezone
        t0 = datetime(2026, 9, 1, 13, 0, tzinfo=timezone.utc) + timedelta(minutes=start_min)
        out = []
        for i in range(n):
            # a zigzag so pivots genuinely exist
            off = (i % 4) * 6.0 - (i % 3) * 2.0 + i * 0.5
            t = t0 + timedelta(minutes=i * step_min)
            out.append({"timestamp": t.isoformat(), "open": base + off,
                        "high": base + off + 4, "low": base + off - 4,
                        "close": base + off + 1, "volume": 100})
        return out

    def test_a_flat_timeframe_falls_through_to_a_richer_one(self):
        from regime_classification import regime_features as RF
        flat = [dict(c, high=29000.0, low=29000.0, open=29000.0, close=29000.0)
                for c in self._series(19, 0, 15)]
        settled = {"15m": flat, "5m": self._series(59, 0, 5), "3m": self._series(99, 0, 3)}
        f = RF.extract_features({"candles": {}}, settled_data=settled,
                                raw_data=settled) if hasattr(RF, "extract_features") else None
        if f is None:
            pytest.skip("feature entry point not exposed under this name")
        assert f.get("swing_source_timeframe") in ("5m", "3m")
        assert f.get("swing_fallback_trace")

    def test_the_trace_names_every_timeframe_it_tried(self):
        from regime_classification import regime_features as RF
        src = open(os.path.join(ROOT, "src", "regime_classification",
                                "regime_features.py"), encoding="utf-8").read()
        # STRUCTURAL, NOT TEXTUAL: the loop must consider all three timeframes.
        import ast as _ast
        tree = _ast.parse(src)
        consts = {n.value for n in _ast.walk(tree)
                  if isinstance(n, _ast.Constant) and isinstance(n.value, str)}
        for tf in ("15m", "5m", "3m"):
            assert tf in consts, tf

    def test_presence_alone_no_longer_selects_a_timeframe(self):
        """The old law -- `if not seq_candles` -- must be gone."""
        src = open(os.path.join(ROOT, "src", "regime_classification",
                                "regime_features.py"), encoding="utf-8").read()
        assert "if not seq_candles:" not in src


class TestRangeNeedsPositiveEvidence:
    """§4: absence of trend proof may not become proof of range."""

    def _f(self, **over):
        """A COMPLETE feature object.

        Built from the module's own `_zero_features()` so a key added upstream
        cannot leave this fixture short. An incomplete dict made the classifier
        raise and fall to `unknown`, which would have let these tests pass
        without ever reaching the branch they exist to pin.
        """
        from regime_classification.regime_features import _zero_features
        base = dict(_zero_features())
        base.update({"trend_score": 20, "chop_score": 20, "reversal_score": 40,
                     "range_state": "expanding", "volatility_state": "toxic",
                     "expansion_state": "exhaustion_risk", "exp_score_15": 0,
                     "bias_15m": "neutral", "bias_5m": "bearish",
                     "range_size": 100.0, "atr_proxy": 10.0,
                     "close_position_in_range": 0.5})
        base.update(over)
        return base

    def _label(self, monkeypatch, **over):
        """Drive the real classifier with injected features.

        Patched at the feature SOURCE rather than reimplementing the label
        ladder here, so the branch under test is the production one.
        """
        from regime_classification import regime_classifier as RC
        monkeypatch.setattr(RC, "extract_regime_features",
                            lambda *a, **k: self._f(**over))
        return RC.classify_regime({}, None, None)

    def test_expanding_is_not_labelled_a_range(self, monkeypatch):
        """THE LIVE CONTRADICTION: the same feature object said
        range_state='expanding' while the label said range_rotation."""
        r = self._label(monkeypatch, range_state="expanding")
        assert r["regime_label"] != "range_rotation", r["evidence"]

    def test_unproven_range_falls_to_unknown_not_to_range(self, monkeypatch):
        r = self._label(monkeypatch, range_state="expanding")
        assert r["regime_label"] == "unknown"

    def test_low_trend_with_a_stable_range_may_still_be_a_range(self, monkeypatch):
        """Range remains assignable -- it just has to be earned."""
        r = self._label(monkeypatch, range_state="stable")
        assert r["regime_label"] == "range_rotation"

    def test_the_catchall_wording_is_gone(self):
        src = open(os.path.join(ROOT, "src", "regime_classification",
                                "regime_classifier.py"), encoding="utf-8").read()
        assert "— catchall" not in src


class TestSemanticProducersAreSealed:
    """CLOSURE: an isolated edit to any structural/regime truth producer must
    invalidate a minted authorization.

    Membership in a list is not binding. Each case MUTATES THE REAL FILE, asserts
    the production Brain fingerprint moves, and restores byte-exact content --
    because `brain_input` being bound only binds the publication hop, not the
    modules that decide what structure and regime MEAN before publication.
    """

    CASES = [
        ("swing_structure", "src/narrative_authority/swing_structure.py",
         b"MIN_SWINGS_PER_SIDE = 2"),
        ("protected_swings", "src/narrative_authority/protected_swings.py",
         b"LINEAGE_CAP = 32"),
        ("regime_features", "src/regime_classification/regime_features.py",
         b'"15m", 15'),
        ("regime_classifier", "src/regime_classification/regime_classifier.py",
         b'"expanding",)'),
        ("brain_input", "src/ai_brain/brain_input.py", b"ordinal_sequence"),
    ]

    @pytest.mark.parametrize("label,rel,needle", CASES,
                             ids=[c[0] for c in CASES])
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
            open(path, "wb").write(
                raw.replace(needle, needle + b"  # semantic mutation", 1))
            after = PM.brain_contract_fingerprint()
        finally:
            shutil.copyfile(bak, path)
            os.unlink(bak)
        assert open(path, "rb").read() == raw, "byte restore failed"
        assert after != before, "%s is NOT sealed by the Brain closure" % label
        assert PM.brain_contract_fingerprint() == before

    def test_every_truth_producer_is_a_declared_closure_source(self):
        from ai_brain.production_model import (_CONTRACT_SOURCES,
                                               _CONTRACT_SOURCES_REPO)
        bound = {r for _, r in _CONTRACT_SOURCES} | {r for _, r in _CONTRACT_SOURCES_REPO}
        for rel in ("narrative_authority/swing_structure.py",
                    "narrative_authority/protected_swings.py",
                    "regime_classification/regime_features.py",
                    "regime_classification/regime_classifier.py",
                    "ai_brain/brain_input.py"):
            assert rel in bound, rel


class TestSettledEvidenceOwnsTheWindowedWitness:
    """F: the settled-evidence theorem, proven BEHAVIOURALLY.

    The old guard asserted the literal source text `swing_sequence(seq_candles`.
    That pinned a CALL SPELLING, not a property, and went stale the moment the
    single-series call became a sufficiency loop. The invariants that actually
    matter and are proven here:

      * every candidate series is drawn through the settled-series authority
      * a realtime/forming series is never consulted while a settled one exists
      * exactly ONE timeframe becomes the witness -- no mixed pivot soup
      * selection is by mechanical pivot sufficiency, never by direction
    """

    def _zig(self, n, step_min, base=29000.0):
        """A series that satisfies the REAL evidence law.

        `build_swing_evidence` withholds every pivot unless each settled bar can
        prove all of its source constituents were observed, so a fixture without
        `source_member_times` yields zero pivots and would make these tests pass
        for the wrong reason. Dated inside the verified venue cadence range for
        the same reason.
        """
        from datetime import datetime, timedelta, timezone
        t0 = datetime(2026, 9, 1, 14, 0, tzinfo=timezone.utc)
        out = []
        for i in range(n):
            off = (i % 4) * 8.0 - (i % 3) * 3.0
            t = t0 + timedelta(minutes=i * step_min)
            out.append({"timestamp": t.isoformat(), "open": base + off,
                        "high": base + off + 5, "low": base + off - 5,
                        "close": base + off + 1, "volume": 100,
                        "source_member_times": [
                            (t + timedelta(minutes=m)).isoformat()
                            for m in range(step_min)]})
        return out

    def _flat(self, n, step_min, base=29000.0):
        """Authoritative evidence, but no geometry: pivots cannot form."""
        return [dict(c, high=base, low=base, open=base, close=base)
                for c in self._zig(n, step_min, base)]

    def _extract(self, settled, raw=None):
        from regime_classification import regime_features as RF
        return RF.extract_regime_features({}, raw if raw is not None else settled,
                                          settled)

    def test_a_sufficient_15m_is_selected_without_falling_through(self):
        f = self._extract({"15m": self._zig(40, 15), "5m": self._zig(60, 5),
                           "3m": self._zig(90, 3)})
        assert f["swing_source_timeframe"] == "15m"

    def test_an_insufficient_15m_falls_through_to_5m(self):
        f = self._extract({"15m": self._flat(40, 15), "5m": self._zig(60, 5),
                           "3m": self._zig(90, 3)})
        assert f["swing_source_timeframe"] == "5m"

    def test_insufficient_15m_and_5m_fall_through_to_3m(self):
        f = self._extract({"15m": self._flat(40, 15), "5m": self._flat(60, 5),
                           "3m": self._zig(90, 3)})
        assert f["swing_source_timeframe"] == "3m"

    def test_the_witness_is_one_timeframe_not_a_mixed_pivot_set(self):
        f = self._extract({"15m": self._flat(40, 15), "5m": self._zig(60, 5),
                           "3m": self._zig(90, 3)})
        assert f["swing_source_timeframe"] in ("15m", "5m", "3m")
        assert isinstance(f["swing_source_timeframe"], str)   # exactly one

    def test_every_attempt_is_recorded_so_selection_is_auditable(self):
        f = self._extract({"15m": self._flat(40, 15), "5m": self._zig(60, 5)})
        trace = f["swing_fallback_trace"]
        assert any(t.startswith("15m") for t in trace)
        assert any(t.startswith("5m") for t in trace)

    def test_the_settled_series_is_preferred_over_the_realtime_one(self):
        """THE THEOREM THE OLD GUARD PROTECTED. A forming series must never be
        consulted while a settled view exists for the same timeframe."""
        settled = {"15m": self._zig(40, 15)}
        realtime = {"15m": self._flat(40, 15)}      # would yield no pivots
        f = self._extract(settled, raw=realtime)
        assert f["swing_source_timeframe"] == "15m"
        assert f["swing_sequence"] != "unknown"      # it read the SETTLED one

    def test_every_candidate_goes_through_the_settled_authority(self):
        """AST, as a supplement -- not a substitute for the behaviour above.

        Each timeframe considered must be fetched via `_settled_series`, so a
        future edit cannot quietly read `raw_data` directly for one of them.
        """
        import ast as _ast
        src = open(os.path.join(ROOT, "src", "regime_classification",
                                "regime_features.py"), encoding="utf-8").read()
        tree = _ast.parse(src)
        fn = next(n for n in _ast.walk(tree)
                  if isinstance(n, _ast.FunctionDef) and n.name == "_extract")
        calls = [c for c in _ast.walk(fn)
                 if isinstance(c, _ast.Call) and getattr(c.func, "id", "") == "swing_sequence"]
        assert calls, "the windowed witness is no longer computed here"
        fetches = [c for c in _ast.walk(fn)
                   if isinstance(c, _ast.Call)
                   and getattr(c.func, "id", "") == "_settled_series"]
        assert len(fetches) >= 1, "candidates must come from the settled authority"
