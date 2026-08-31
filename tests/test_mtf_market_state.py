"""MTF_MARKET_STATE — four timeframes that talk without one erasing the others.

2026-08-10 collapsed the conversation in three places:

  1. `_REGISTER_TFS = ("15m","5m")` — 1m and 3m could never register protected
     structure. 90 of 140 sweep+reclaim events were discarded, from exactly
     the two timeframes the doctrine assigns to transition and execution.
  2. one GLOBAL protected_high/low slot with an extreme-wins ratchet — 53/53
     bearish invalidations arrived from the 15m at a median 88.75 points,
     against a 40-point execution ceiling.
  3. what did reach Terra arrived as four disconnected blobs under a contract
     forbidding directional use.

This module addresses 1 and 2, and adds a NEW synthesis lane for 3 rather than
rehabilitating the legacy structure authority. That contract is untouched:
witness-only, non-directional, no execution/invalidation/objective authority.

The clearest symptom is 12:34, where a bullish thesis was authorized while the
1m and 3m were BOTH in bearish breaks and nothing in the payload could say so.

WHAT THESE TESTS ALSO FORBID: any rule requiring 1m/3m BOS before entry, any
four-way agreement requirement, any nearest-wins selection, and any single
`direction` verdict emitted by the synthesis.
"""
from __future__ import annotations

import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))

from broker.luna_candidate_producer import (                     # noqa: E402
    authorized_invalidation_catalog)
from market_state import mtf_market_state as M                   # noqa: E402
from narrative_authority import protected_swings as PS           # noqa: E402


def sweep(direction="above_high"):
    return {"sweep_detected": True, "reclaim_detected": True,
            "sweep_direction": direction}


def st(hi=None, lo=None, bos=False, direction=None, broken=None, close=None,
       mss=False):
    return {"last_swing_high": hi, "last_swing_low": lo, "bos": bos,
            "bos_direction": direction, "broken_level": broken,
            "break_close": close, "mss": mss}


#: The exact 2026-08-10 12:34 shape.
T1234_STRUCTURE = {
    "1m": st(29844.0, 29815.75, True, "bearish", 29815.75, 29782.75),
    "3m": st(29858.75, 29803.75, True, "bearish", 29803.75, 29782.75),
    "5m": st(29858.75, 29752.5),
    "15m": st(29900.0, 29752.5),
}
T1234_PRICE = 29782.75


def tracker_with(highs=None, lows=None):
    t = PS.ProtectedSwingTracker()
    t.protected_highs = dict(highs or {})
    t.protected_lows = dict(lows or {})
    return t


def rec(level, tf, side="high"):
    return {"level": level, "timeframe": tf, "role": PS.timeframe_role(tf),
            "registered_at": "t", "swing_id": f"{tf}:swing_{side}:{level:g}",
            "basis": "test"}


# ══════════════════════════════════════════════════════════════════════════════
class TestPerTimeframeProtectedStructure:
    """1-5."""

    def test_1_all_four_timeframes_can_register(self):
        assert set(PS._REGISTER_TFS) == {"1m", "3m", "5m", "15m"}
        t = PS.ProtectedSwingTracker()
        snap = {"timestamp": "t1",
                "liquidity": {tf: sweep() for tf in ("1m", "3m", "5m", "15m")},
                "structure": {"1m": st(hi=29820.0), "3m": st(hi=29840.0),
                              "5m": st(hi=29860.0), "15m": st(hi=29900.0)},
                "timeframes": {"1m": {"last_candle": {"close": 29783.0}}}}
        state = t.update(snap)
        highs = state["by_timeframe"]["highs"]
        assert {tf: h["level"] for tf, h in highs.items()} == {
            "1m": 29820.0, "3m": 29840.0, "5m": 29860.0, "15m": 29900.0}

    def test_2_a_15m_high_does_not_erase_a_live_5m_high(self):
        t = tracker_with(highs={"15m": rec(29900.0, "15m"),
                                "5m": rec(29860.0, "5m")})
        state = t.state()
        assert set(state["by_timeframe"]["highs"]) == {"15m", "5m"}
        assert state["protected_high"]["level"] == 29900.0, "summary unchanged"

    def test_3_a_5m_high_does_not_erase_1m_or_3m(self):
        t = tracker_with(highs={"5m": rec(29860.0, "5m"),
                                "3m": rec(29840.0, "3m"),
                                "1m": rec(29820.0, "1m")})
        assert len(t.state()["by_timeframe"]["highs"]) == 3

    def test_the_extreme_wins_ratchet_is_gone(self):
        """A LOWER new 15m registration must replace the old 15m one."""
        t = PS.ProtectedSwingTracker()
        base = {"timestamp": "t", "liquidity": {"15m": sweep()},
                "timeframes": {"1m": {"last_candle": {"close": 29700.0}}}}
        t.update({**base, "structure": {"15m": st(hi=29900.0)}})
        t.update({**base, "structure": {"15m": st(hi=29850.0)}})
        assert t.state()["by_timeframe"]["highs"]["15m"]["level"] == 29850.0

    def test_a_violation_clears_only_the_violated_timeframe(self):
        t = tracker_with(highs={"15m": rec(29900.0, "15m"),
                                "1m": rec(29820.0, "1m")})
        t.update({"timestamp": "t", "liquidity": {}, "structure": {},
                  # must clear the violation buffer (0.05% of price)
                  "timeframes": {"1m": {"last_candle": {"close": 29900.0}}}})
        highs = t.state()["by_timeframe"]["highs"]
        assert "1m" not in highs and "15m" in highs

    def test_lows_are_per_timeframe_too(self):
        """Mirrored: the low side must not collapse to the minimum either."""
        t = PS.ProtectedSwingTracker()
        snap = {"timestamp": "t1",
                "liquidity": {tf: sweep("below_low")
                              for tf in ("1m", "3m", "5m", "15m")},
                "structure": {"1m": st(lo=29800.0), "3m": st(lo=29780.0),
                              "5m": st(lo=29760.0), "15m": st(lo=29700.0)},
                "timeframes": {"1m": {"last_candle": {"close": 29850.0}}}}
        state = t.update(snap)
        lows = state["by_timeframe"]["lows"]
        assert {tf: l["level"] for tf, l in lows.items()} == {
            "1m": 29800.0, "3m": 29780.0, "5m": 29760.0, "15m": 29700.0}
        assert state["protected_low"]["level"] == 29700.0, "summary unchanged"
        cat = authorized_invalidation_catalog({"protected_swings": state}, [])
        assert {c["timeframe"] for c in cat} == {"1m", "3m", "5m", "15m"}

    def test_real_registration_stamps_swing_ids_and_roles(self):
        """Through the REAL path, not a hand-built fixture."""
        t = PS.ProtectedSwingTracker()
        t.update({"timestamp": "t1",
                  "liquidity": {"5m": sweep(), "1m": sweep("below_low")},
                  "structure": {"5m": st(hi=29860.0), "1m": st(lo=29800.0)},
                  "timeframes": {"1m": {"last_candle": {"close": 29830.0}}}})
        state = t.state()
        high = state["by_timeframe"]["highs"]["5m"]
        low = state["by_timeframe"]["lows"]["1m"]
        assert high["swing_id"] == "5m:swing_high:29860"
        assert low["swing_id"] == "1m:swing_low:29800"
        assert high["role"] == "active_leg" and low["role"] == "execution"
        assert high["registered_at"] == "t1"
        cat = authorized_invalidation_catalog({"protected_swings": state}, [])
        assert all(c["swing_id"] for c in cat), "lineage lost in the catalog"

    def test_4_5_timeframe_identity_and_role_reach_the_catalog(self):
        t = tracker_with(highs={"15m": rec(29900.0, "15m"),
                                "5m": rec(29860.0, "5m")})
        cat = authorized_invalidation_catalog({"protected_swings": t.state()}, [])
        got = {c["timeframe"]: (c["role"], c["type"], c["price"]) for c in cat}
        assert got["15m"] == ("context", "protected_high", 29900.0)
        assert got["5m"] == ("active_leg", "protected_high", 29860.0)
        assert all(c.get("swing_id") for c in cat)


class TestSynthesisRolesAndConflicts:
    """6-12."""

    def build(self, structure, price, liquidity=None, protected=None):
        return M.build(structure=structure, liquidity=liquidity or {},
                       protected_swings=protected or {"by_timeframe":
                                                      {"highs": {}, "lows": {}}},
                       price=price, timestamp="t")

    def test_6_roles_are_explicit_and_distinct(self):
        s = self.build(T1234_STRUCTURE, T1234_PRICE)
        assert s["roles"] == {"15m": "context", "5m": "active_leg",
                              "3m": "transition", "1m": "execution"}
        for tf, role in s["roles"].items():
            assert s["timeframes"][tf]["role"] == role

    def test_the_synthesis_emits_no_direction_of_its_own(self):
        """The god-object guard: roles and conflicts, never a verdict."""
        s = self.build(T1234_STRUCTURE, T1234_PRICE)
        for banned in ("direction", "bias", "verdict", "signal",
                       "recommended_direction"):
            assert banned not in s["synthesis"], banned
        assert banned not in s

    def test_7_a_lower_timeframe_may_oppose_broader_context(self):
        s = self.build({"1m": st(29800.0, 29750.0, True, "bullish", 29800.0, 29810.0),
                        "3m": st(29820.0, 29740.0),
                        "5m": st(29860.0, 29790.0, True, "bearish", 29790.0, 29780.0),
                        "15m": st(29900.0, 29669.0)}, 29810.0)
        sy = s["synthesis"]
        assert sy["execution_state"] == "bullish_break"
        assert sy["active_leg_state"] == "bearish_break"
        assert sy["alignment_state"] == M.CONFLICTED
        assert sy["conflicts"], "an opposing rotation must be reported"

    def test_8_four_way_agreement_is_never_required(self):
        """Nothing in this module can demand unanimity."""
        src = open(os.path.join(ROOT, "src", "market_state",
                                "mtf_market_state.py"), encoding="utf-8").read()
        for banned in ("all(", "require_agreement", "unanimous", "must_agree"):
            assert banned not in src.replace("# ", ""), banned
        s = self.build({"1m": st(29800.0, 29780.0, True, "bearish", 29780.0, 29770.0),
                        "3m": st(29820.0, 29790.0), "5m": st(29860.0, 29700.0),
                        "15m": st(29900.0, 29669.0)}, 29770.0)
        assert s["synthesis"]["execution_state"] == "bearish_break"
        assert s["synthesis"]["alignment_state"] in (M.NESTED, M.ALIGNED)

    def test_9_context_alone_states_nothing_about_execution(self):
        s = self.build({"1m": st(29800.0, 29780.0), "3m": st(29820.0, 29790.0),
                        "5m": st(29860.0, 29700.0),
                        "15m": st(29900.0, 29669.0, True, "bearish", 29669.0, 29650.0)},
                       29650.0)
        sy = s["synthesis"]
        assert sy["context_state"] == "bearish_break"
        assert sy["execution_state"] is None
        assert sy["timeframes_stating_something"] == ["15m"]

    def test_10_execution_alone_does_not_manufacture_higher_structure(self):
        s = self.build({"1m": st(29800.0, 29780.0, True, "bearish", 29780.0, 29770.0),
                        "3m": st(29820.0, 29700.0), "5m": st(29860.0, 29600.0),
                        "15m": st(29900.0, 29500.0)}, 29770.0)
        sy = s["synthesis"]
        assert sy["execution_state"] == "bearish_break"
        assert sy["active_leg_state"] is None and sy["context_state"] is None

    def test_11_12_a_new_opposing_break_changes_the_state(self):
        first = self.build({"5m": st(29860.0, 29790.0, True, "bearish", 29790.0, 29780.0),
                            "1m": st(), "3m": st(), "15m": st()}, 29780.0)
        assert first["synthesis"]["active_leg_state"] == "bearish_break"
        second = self.build({"5m": st(29860.0, 29790.0),
                             "3m": st(29800.0, 29750.0, True, "bullish", 29800.0, 29815.0),
                             "1m": st(29790.0, 29760.0, True, "bullish", 29790.0, 29815.0),
                             "15m": st()}, 29815.0)
        sy = second["synthesis"]
        assert sy["transition_state"] == "bullish_break"
        assert sy["execution_state"] == "bullish_break"

    def test_confirmed_and_realtime_facts_are_separated(self):
        """Pivot-derived facts lag by construction; break/sweep facts do not."""
        s = self.build(T1234_STRUCTURE, T1234_PRICE)
        one = s["timeframes"]["1m"]
        assert one[M.CONFIRMED]["last_swing_low"] == 29815.75
        assert "requires candles on both sides" in one[M.CONFIRMED]["note"]
        assert one[M.REALTIME]["bos_event"] == M.BEARISH_BOS
        assert one[M.REALTIME]["broken_level"] == 29815.75

    def test_a_generic_break_without_direction_states_nothing(self):
        s = self.build({"1m": st(29800.0, 29780.0, bos=True), "3m": st(),
                        "5m": st(), "15m": st()}, 29770.0)
        assert s["synthesis"]["execution_state"] is None


class TestTheHistoricalFixture:
    """The 12:34 case, permanently."""

    def state(self):
        return M.build(structure=T1234_STRUCTURE, liquidity={},
                       protected_swings={"by_timeframe": {
                           "highs": {}, "lows": {"5m": rec(29752.5, "5m", "low")}}},
                       price=T1234_PRICE, timestamp="12:34")

    def test_the_simultaneous_bearish_breaks_are_now_visible(self):
        s = self.state()
        assert s["timeframes"]["1m"][M.REALTIME]["bos_event"] == M.BEARISH_BOS
        assert s["timeframes"]["3m"][M.REALTIME]["bos_event"] == M.BEARISH_BOS
        assert s["timeframes"]["1m"][M.REALTIME]["broken_level"] == 29815.75
        assert s["timeframes"]["3m"][M.REALTIME]["broken_level"] == 29803.75

    def test_a_bullish_thesis_is_told_what_opposes_it(self):
        opposing = M.opposing_execution_evidence(self.state(), "bullish")
        tfs = {o["timeframe"]: o for o in opposing}
        assert set(tfs) == {"1m", "3m"}
        assert tfs["1m"]["role"] == "execution"
        assert tfs["3m"]["role"] == "transition"
        assert tfs["1m"]["broken_level"] == 29815.75

    def test_the_5m_protected_low_is_still_offered(self):
        """The restoration must not delete what already worked."""
        cat = authorized_invalidation_catalog(
            {"protected_swings": {"by_timeframe": {
                "highs": {}, "lows": {"5m": rec(29752.5, "5m", "low")}}}}, [])
        assert [c["price"] for c in cat] == [29752.5]
        assert cat[0]["timeframe"] == "5m" and cat[0]["role"] == "active_leg"

    def test_nothing_here_vetoes_the_thesis(self):
        """Opposition is EVIDENCE. Terra still owns the narrative.

        Checked against the CODE, not the prose -- the module docstring says
        the word "veto" precisely to promise it never does one.
        """
        import ast
        src = open(os.path.join(ROOT, "src", "market_state",
                                "mtf_market_state.py"), encoding="utf-8").read()
        tree = ast.parse(src)
        for node in ast.walk(tree):
            if isinstance(node, ast.Raise):
                continue
            if isinstance(node, (ast.Name, ast.Attribute)):
                name = (getattr(node, "id", "") or getattr(node, "attr", "")).lower()
                for banned in ("veto", "block_entry", "forbid", "deny",
                               "reject_candidate"):
                    assert banned not in name, name
        state = self.state()
        assert "veto" not in str(state).lower()


class TestNoHindsightRules:
    """The corrections the operator required, pinned as code."""

    def test_no_bos_entry_requirement_was_introduced(self):
        """11:15 is NOT PROVEN and NOT DISPROVEN. No rule may assume it."""
        for path in ("src/market_state/mtf_market_state.py",
                     "src/broker/luna_candidate_producer.py",
                     "src/narrative_authority/protected_swings.py"):
            src = open(os.path.join(ROOT, path), encoding="utf-8").read().lower()
            for banned in ("bos_required", "require_bos", "requires_bos",
                           "execution_confirmation_required"):
                assert banned not in src, f"{banned} in {path}"

    def test_no_nearest_or_farthest_selection_exists(self):
        for path in ("src/market_state/mtf_market_state.py",
                     "src/narrative_authority/protected_swings.py"):
            src = open(os.path.join(ROOT, path), encoding="utf-8").read().lower()
            for banned in ("nearest", "closest", "tightest"):
                assert banned not in src.replace("# ", ""), f"{banned} in {path}"

    def test_the_catalog_still_does_not_filter_by_the_ceiling(self):
        t = tracker_with(highs={"15m": rec(29900.0, "15m")})
        cat = authorized_invalidation_catalog({"protected_swings": t.state()}, [])
        assert cat[0]["price"] == 29900.0, "a far fact is still published"

    def test_risk_doctrine_unchanged(self):
        from broker.topstepx_combine_risk import (ABSOLUTE_MAX_STOP_POINTS,
                                                  MIN_REWARD_TO_RISK,
                                                  PREFERRED_MAX_STOP_POINTS,
                                                  PRODUCTION_MAX_CONTRACTS,
                                                  PRODUCTION_MAX_RISK_USD)
        assert (ABSOLUTE_MAX_STOP_POINTS, PREFERRED_MAX_STOP_POINTS,
                PRODUCTION_MAX_RISK_USD, PRODUCTION_MAX_CONTRACTS,
                MIN_REWARD_TO_RISK) == (50.0, 35.0, 350.00, 15, 1.0)


class TestLegacyStructureStaysQuarantined:
    """The new lane must not rehabilitate the old authority."""

    def test_the_new_lane_never_reads_structure_witness(self):
        """Checked against the CODE, not the prose.

        The module docstring and comments NAME the legacy contract precisely to
        promise they never touch it; matching on raw text made this test break
        every time that promise was restated.
        """
        import ast
        src = open(os.path.join(ROOT, "src", "market_state",
                                "mtf_market_state.py"), encoding="utf-8").read()
        tree = ast.parse(src)
        names = {getattr(n, "id", "") or getattr(n, "attr", "")
                 for n in ast.walk(tree)
                 if isinstance(n, (ast.Name, ast.Attribute))}
        # docstrings are Constants too. Compare NODE IDENTITY, not text --
        # `ast.get_docstring` cleans indentation, so the values never match.
        doc_nodes = set()
        for n in ast.walk(tree):
            if isinstance(n, (ast.Module, ast.FunctionDef, ast.ClassDef)):
                first = (n.body or [None])[0]
                if (isinstance(first, ast.Expr)
                        and isinstance(first.value, ast.Constant)
                        and isinstance(first.value.value, str)):
                    doc_nodes.add(id(first.value))
        code_literals = {n.value for n in ast.walk(tree)
                         if isinstance(n, ast.Constant)
                         and isinstance(n.value, str)
                         and id(n) not in doc_nodes}
        assert not any("STRUCTURE_WITNESS" in s for s in code_literals),             "the new lane references the legacy witness key in code"
        assert not any("witness" in n.lower() for n in names)

    def test_the_witness_disclaimer_is_unchanged(self):
        src = open(os.path.join(ROOT, "src", "ai_brain", "brain_input.py"),
                   encoding="utf-8").read()
        # the disclaimer is a concatenated literal in source, so match its
        # parts rather than the rendered phrase
        assert "STRUCTURE WITNESS ONLY" in src
        assert "NOT DIRECTIONAL " in src and "AUTHORITY." in src
        assert "Do not use to choose direction" in src

    def test_mtf_state_is_its_own_payload_key(self):
        src = open(os.path.join(ROOT, "src", "ai_brain", "brain_input.py"),
                   encoding="utf-8").read()
        assert '"MTF_MARKET_STATE"' in src
        witness = src[src.index('"STRUCTURE_WITNESS"'):]
        assert '"MTF_MARKET_STATE"' not in witness[:witness.index("},")]


class TestLegacySummaryHasNoExecutionAuthority:
    """THE INVARIANT the legacy-Structure dependency audit demanded.

        No production execution decision may depend SOLELY on the legacy
        global extreme protected-high/low summary when per-timeframe state
        exists.

    Before v10 it did, and measurably: on 2026-08-10 the invalidation catalog
    was built ENTIRELY from that summary, so 8 of 8 directional proposals
    carried a stop exactly equal to it -- Terra picked the only option it was
    ever given. That is the chokehold, and it is what these tests keep dead.
    """

    def summary_and_per_tf(self):
        return {"protected_high": {"level": 29900.0, "timeframe": "15m"},
                "protected_low": {"level": 29752.5, "timeframe": "5m"},
                "by_timeframe": {
                    "highs": {"15m": rec(29900.0, "15m"),
                              "5m": rec(29860.0, "5m"),
                              "1m": rec(29820.0, "1m")},
                    "lows": {"5m": rec(29752.5, "5m", "low")}}}

    def test_per_timeframe_state_supersedes_the_summary_in_the_catalog(self):
        cat = authorized_invalidation_catalog(
            {"protected_swings": self.summary_and_per_tf()}, [])
        highs = [c for c in cat if c["type"] == "protected_high"]
        assert {c["timeframe"] for c in highs} == {"15m", "5m", "1m"}
        assert all(c["invalidation_id"] != "INV_PH_1" for c in cat), \
            "the summary-derived candidate re-entered alongside per-timeframe state"

    def test_the_summary_level_is_published_once_not_twice(self):
        cat = authorized_invalidation_catalog(
            {"protected_swings": self.summary_and_per_tf()}, [])
        assert len([c for c in cat if c["price"] == 29900.0]) == 1

    def test_the_summary_still_works_alone_for_legacy_snapshots(self):
        """Replays and pre-v10 archives must not lose their one candidate."""
        cat = authorized_invalidation_catalog(
            {"protected_swings": {"protected_high": {"level": 29900.0,
                                                     "timeframe": "15m"}}}, [])
        assert [c["invalidation_id"] for c in cat] == ["INV_PH_1"]
        assert cat[0]["price"] == 29900.0

    def test_the_monday_shape_no_longer_collapses_to_one_option(self):
        """11:10 offered exactly one bearish invalidation: the 15m at 117pt."""
        old = authorized_invalidation_catalog(
            {"protected_swings": {"protected_high": {"level": 29900.0,
                                                     "timeframe": "15m"}}}, [])
        assert len(old) == 1, "the historical shape"
        new = authorized_invalidation_catalog(
            {"protected_swings": {
                "protected_high": {"level": 29900.0, "timeframe": "15m"},
                "by_timeframe": {"highs": {"15m": rec(29900.0, "15m"),
                                           "3m": rec(29893.0, "3m"),
                                           "1m": rec(29886.25, "1m")},
                                 "lows": {}}}}, [])
        assert len(new) == 3
        assert {c["role"] for c in new} == {"context", "transition", "execution"}

    def test_the_stop_price_comes_from_terra_not_from_the_summary(self):
        """`_invalidation` reads parsed['invalidation_level']; the legacy field
        only builds the evidence LABEL."""
        src = open(os.path.join(ROOT, "src", "broker",
                                "luna_candidate_producer.py"),
                   encoding="utf-8").read()
        body = src[src.index("def _invalidation(self,"):
                   src.index("def _objective_selected(")]
        assert 'raw = parsed.get("invalidation_level")' in body
        assert "price = float(raw)" in body
        # the summary appears only inside the identity/evidence strings
        for line in body.splitlines():
            if "protected_high" in line or "protected_low" in line:
                assert ("key =" in line or "structure_identity" in line
                        or "evidence_source" in line or "block =" in line), line


class TestPayloadIsTaintClean:
    """PROD-20260811: the live defect this suite could not see.

    43 consecutive scans returned `BRAIN_DEGRADED - taint:['unlabeled_bias_key']`
    and Terra was never called once. `MTF_MARKET_STATE` carried the legacy
    structure engine's `bias` key, and `scan_payload_taint` flags any unlabeled
    `"bias"` outside the exempt STRUCTURE_WITNESS block -- so `narrative_brain`
    took the contaminated-input branch and fell to the deterministic core every
    scan.

    The contamination guard behaved correctly. The payload did not. 4435 tests
    passed because NONE of them asserted that what we actually send the Brain is
    taint-clean. That is the hole these tests close.
    """

    def realistic_structure(self):
        """Structure blocks exactly as the engine emits them -- INCLUDING the
        directional `bias`/`state` fields, so the test proves MTF drops them."""
        return {
            "1m": {"last_swing_high": 29844.0, "last_swing_low": 29815.75,
                   "bos": True, "bos_direction": "bearish",
                   "broken_level": 29815.75, "break_close": 29782.75,
                   "mss": False, "bias": "bearish", "state": "bearish_continuation"},
            "3m": {"last_swing_high": 29858.75, "last_swing_low": 29803.75,
                   "bos": True, "bos_direction": "bearish",
                   "broken_level": 29803.75, "break_close": 29782.75,
                   "mss": True, "bias": "bearish", "state": "bearish_continuation"},
            "5m": {"last_swing_high": 29858.75, "last_swing_low": 29752.5,
                   "bos": False, "bias": "neutral", "state": "range_bound"},
            "15m": {"last_swing_high": 29900.0, "last_swing_low": 29752.5,
                    "bos": False, "bias": "bullish", "state": "range_bound"},
        }

    def built(self):
        return M.build(structure=self.realistic_structure(), liquidity={},
                       protected_swings={"by_timeframe": {
                           "highs": {"15m": rec(29900.0, "15m")},
                           "lows": {"5m": rec(29752.5, "5m", "low")}}},
                       price=29782.75, timestamp="t")

    def test_mtf_market_state_alone_is_taint_clean(self):
        from ai_brain.brain_validation import scan_payload_taint
        ok, hits = scan_payload_taint({"MTF_MARKET_STATE": self.built()})
        assert ok, f"MTF_MARKET_STATE would degrade every scan: {hits}"

    def test_the_directional_verdicts_are_dropped_not_renamed(self):
        """Evading the guard by renaming would keep the god-object alive."""
        import json
        blob = json.dumps(self.built(), default=str).lower()
        assert '"bias"' not in blob
        for sneaky in ("structural_bias", "tf_bias", "bias_state",
                       "directional_bias", "engine_bias"):
            assert sneaky not in blob, f"bias smuggled through as {sneaky}"
        assert "bearish_continuation" not in blob, "legacy `state` verdict leaked"

    def test_the_confirmed_block_keeps_only_non_directional_facts(self):
        one = self.built()["timeframes"]["1m"][M.CONFIRMED]
        assert set(one) == {"last_swing_high", "last_swing_low", "mss_event", "note"}

    def test_directional_evidence_still_survives_where_it_belongs(self):
        """Dropping `bias` must not cost us the REALTIME break facts."""
        s = self.built()
        assert s["timeframes"]["1m"][M.REALTIME]["bos_event"] == M.BEARISH_BOS
        assert s["timeframes"]["3m"][M.REALTIME]["bos_event"] == M.BEARISH_BOS
        assert s["synthesis"]["execution_state"] == "bearish_break"
        assert s["synthesis"]["transition_state"] == "bearish_break"
        assert M.opposing_execution_evidence(s, "bullish")

    def test_the_full_structure_flip_payload_is_taint_clean(self):
        """The other v8 key we add to brain_input."""
        from ai_brain.brain_validation import scan_payload_taint
        from structure.structure_flip import FlipRegistry
        r = FlipRegistry()
        r.update(self.realistic_structure(), timestamp="t")
        ok, hits = scan_payload_taint({"structure_flips": r.candidates()})
        assert ok, f"structure_flips would degrade every scan: {hits}"

    def test_both_new_keys_together_are_taint_clean(self):
        from ai_brain.brain_validation import scan_payload_taint
        from structure.structure_flip import FlipRegistry
        r = FlipRegistry()
        r.update(self.realistic_structure(), timestamp="t")
        ok, hits = scan_payload_taint({"MTF_MARKET_STATE": self.built(),
                                       "structure_flips": r.candidates(),
                                       "protected_swings": {"by_timeframe": {
                                           "highs": {"15m": rec(29900.0, "15m")},
                                           "lows": {}}}})
        assert ok, hits

    def test_a_reintroduced_bias_key_is_caught(self):
        """Proves the assertion above actually bites."""
        from ai_brain.brain_validation import scan_payload_taint
        poisoned = self.built()
        poisoned["timeframes"]["1m"][M.CONFIRMED]["bias"] = "bearish"
        ok, hits = scan_payload_taint({"MTF_MARKET_STATE": poisoned})
        assert ok is False and "unlabeled_bias_key" in hits


class TestPerTimeframeStateIsDELIVERED:
    """PROD-20260811 10:32:07 — the hop v10/v11 never asserted.

    The tracker registered protected highs on 1m (29773.75, 27.75pt from
    price), 3m and 5m (29793.00, 47.00pt). `brain_input._protected` rebuilt the
    block and dropped `by_timeframe`, so the catalog took the LEGACY branch and
    handed Terra one side-valid bearish stop -- the 47-point one. The candidate
    died on the 40-point ceiling while a 27.75-point execution-timeframe
    structure sat unused in the same snapshot.

    v11 pinned that the CATALOG honours a registry. Nothing pinned that the
    payload DELIVERS one. A per-timeframe registry that never reaches the
    catalog is the collapsed menu with extra steps.
    """

    #: Verbatim from the live 10:32:07 snapshot.
    PRICE = 29746.0
    REGISTRY = {
        "highs": {"1m": {"level": 29773.75, "timeframe": "1m", "role": "execution",
                         "swing_id": "1m:swing_high:29773.75", "basis": "buy_side_raid_rejected"},
                  "3m": {"level": 29793.0, "timeframe": "3m", "role": "transition",
                         "swing_id": "3m:swing_high:29793", "basis": "buy_side_raid_rejected"},
                  "5m": {"level": 29793.0, "timeframe": "5m", "role": "active_leg",
                         "swing_id": "5m:swing_high:29793", "basis": "buy_side_raid_rejected"}},
        "lows": {"15m": {"level": 29752.5, "timeframe": "15m", "role": "context",
                         "swing_id": "15m:swing_low:29752.5", "basis": "sell_side_raid_rejected"},
                 "3m": {"level": 29636.0, "timeframe": "3m", "role": "transition",
                        "swing_id": "3m:swing_low:29636", "basis": "sell_side_raid_rejected"}},
    }

    def snapshot(self):
        return {"timestamp": "2026-08-11T14:32:07+00:00",
                "protected_swings": {
                    "protected_high": dict(self.REGISTRY["highs"]["5m"]),
                    "protected_low": dict(self.REGISTRY["lows"]["3m"]),
                    "by_timeframe": self.REGISTRY,
                    "roles": dict(PS.TIMEFRAME_ROLES)},
                "timeframes": {"1m": {"last_candle": {"close": self.PRICE}}}}

    def delivered(self):
        from ai_brain.brain_input import _protected
        return _protected(self.snapshot(), self.PRICE)

    def test_brain_input_carries_the_per_timeframe_registry(self):
        block = self.delivered()
        assert "by_timeframe" in block, "the registry was stripped before Terra"
        assert set(block["by_timeframe"]["highs"]) == {"1m", "3m", "5m"}

    def test_the_legacy_summary_fields_are_unchanged(self):
        block = self.delivered()
        assert block["protected_high"]["level"] == 29793.0
        assert block["protected_low"]["level"] == 29636.0
        assert block["protected_high_status"] and block["protected_low_status"]

    def test_the_catalog_now_emits_per_timeframe_ids_not_the_legacy_pair(self):
        cat = authorized_invalidation_catalog({"protected_swings": self.delivered()}, [])
        ids = [c["invalidation_id"] for c in cat]
        assert "INV_PH_1" not in ids and "INV_PL_1" not in ids, \
            "the legacy summary branch fired despite a registry being present"
        assert any(i.startswith("INV_PH_1m") for i in ids)
        assert any(i.startswith("INV_PH_5m") for i in ids)

    def test_the_27_point_execution_stop_is_now_offered(self):
        """The exact level withheld from Terra live."""
        cat = authorized_invalidation_catalog({"protected_swings": self.delivered()}, [])
        one_m = [c for c in cat if c.get("timeframe") == "1m"
                 and c["type"] == "protected_high"]
        assert len(one_m) == 1
        assert one_m[0]["price"] == 29773.75
        assert abs(one_m[0]["price"] - self.PRICE) == 27.75
        assert one_m[0]["role"] == "execution"

    def test_terra_receives_MORE_THAN_ONE_side_valid_bearish_stop(self):
        """The claim I withdrew: selection needs a real menu, not one row."""
        cat = authorized_invalidation_catalog({"protected_swings": self.delivered()}, [])
        valid = [c for c in cat if c["type"] == "protected_high"
                 and c["price"] > self.PRICE]
        assert len(valid) >= 2, f"only {len(valid)} side-valid bearish stop(s)"
        assert {c["timeframe"] for c in valid} == {"1m", "3m", "5m"}
        inside = [c for c in valid if abs(c["price"] - self.PRICE) <= 40.0]
        assert inside, "no bearish stop inside the ceiling despite one existing"

    def test_the_old_behaviour_produced_exactly_one(self):
        """Same snapshot, registry stripped: the live 10:32 shape."""
        stripped = {k: v for k, v in self.delivered().items()
                    if k not in ("by_timeframe", "roles")}
        cat = authorized_invalidation_catalog({"protected_swings": stripped}, [])
        assert [c["invalidation_id"] for c in cat] == ["INV_PH_1", "INV_PL_1"]
        valid = [c for c in cat if c["type"] == "protected_high"
                 and c["price"] > self.PRICE]
        assert len(valid) == 1 and abs(valid[0]["price"] - self.PRICE) == 47.00

    def test_the_delivered_payload_is_still_taint_clean(self):
        from ai_brain.brain_validation import scan_payload_taint
        ok, hits = scan_payload_taint({"protected_swings": self.delivered()})
        assert ok, hits
