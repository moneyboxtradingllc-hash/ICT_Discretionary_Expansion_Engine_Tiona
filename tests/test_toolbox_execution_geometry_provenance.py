"""CONTINUITY-2F — a provisional zone may be seen, but may not author a stop.

VERDICT B (witness / authority split), from a real-tape forensic replay on the
committed Aug-11 venue fixture. Building each scan twice -- forming bucket
present vs excluded -- moved published zone geometry on EIGHT tool families, and
moved `invalidation_level`, the level the STOP is derived from, by as much as
20.5 points against a 40-point ceiling:

    14:42Z  bearish_order_block   invalidation  29757.50 -> 29778.00   (20.50)
    14:42Z  bullish_breaker       invalidation  29740.25 -> 29752.00   (11.75)
    14:40Z  bullish_order_block   invalidation  29742.50 -> 29733.00   ( 9.50)

And at 14:48Z the 3m carried a bullish FVG whose c3 WAS the forming bar --
{low 29759.25, high 29768.75} -- with no settled gap behind it at all.

TWO PRODUCTION LANES turn that field into a stop:
    paper_execution/order_builder.py          -> stop_reference
    integrations/.../facts_provider.py        -> structural invalidation
The TopstepX production lane does NOT: its invalidation catalog is built from
`protected_swings` + structure flips, and the toolbox inventory reaches Terra as
visibility only. That is why this was latent rather than live on MNQ -- and it is
also why it had to be fixed before the toolbox is ever wired to execution
(roadmap step 7).

THE CORRECTION THIS FILE ALSO RECORDS: the V19 audit called `_find_ob`'s
`candles[:-1]` slice "safe by coincidence". It is not safe. Order blocks were the
MOST affected family (23 + 18 scans) -- excluding the newest bar does not exclude
the forming bar's influence, it changes WHICH bar is excluded.
"""
from __future__ import annotations

import inspect
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))

from data_feed import candle_continuity as CONT                      # noqa: E402
from data_feed.timeframe_builder import build_timeframes             # noqa: E402
import market_data.snapshot_builder as SB                            # noqa: E402
from toolbox import price_levels as PL                               # noqa: E402
from toolbox.price_levels import (                                   # noqa: E402
    EXECUTION_GEOMETRY_FIELDS, build_price_level, find_fvgs,
)

FIXTURE = os.path.join(ROOT, "tests", "fixtures",
                       "mnq_20260811_1420Z_1510Z_1m.json")

TOOLS = ("bullish_fvg", "bearish_fvg", "bullish_order_block",
         "bearish_order_block", "bullish_breaker", "bearish_breaker",
         "bullish_mss_retest", "bearish_mss_retest")


#: The contract these captured bars belong to. The fixture is a real TopstepX
#: record of the 2026-08-11 session (see its `_provenance`), and the venue store
#: for that session is CON.F.US.MNQ.U26; the capture simply kept OHLCV only.
FIXTURE_CONTRACT = "CON.F.US.MNQ.U26"


def tape() -> list:
    """The captured venue bars, in PRODUCTION SHAPE.

    STEP 4B.12 §6 UNIT 6 — HARNESS EQUIVALENCE, not a behaviour change.

    Production bars carry `contract`, `snapshot_builder` now propagates it onto
    `recent_candles`, and canonical FVG occurrence identity is
    `contract + timeframe + completion slot`. This fixture captured OHLCV only,
    so its candles reached the toolbox with no provable identity and plain-FVG
    occurrences were refused on identity grounds -- a difference between the
    fixture and production, not a difference in market truth.

    The contract is attached HERE rather than edited into the captured JSON, so
    the venue record on disk stays exactly as it was received. Every OHLCV value,
    timestamp and expected geometry in this file is untouched: the 2F invariant
    is about temporal zone authority, and it is asserted unchanged below.
    """
    with open(FIXTURE, encoding="utf-8") as fh:
        bars = json.load(fh)["bars"]
    return [{**b, "contract": FIXTURE_CONTRACT} for b in bars]


def ends() -> list:
    return sorted({b["timestamp"] for b in tape()})[20:]


def snap_at(end: str, drop_forming: bool = False) -> dict:
    bars = [b for b in tape() if b["timestamp"] <= end]
    win = CONT.coherent_window(bars, horizon_minutes=300, minimum_bars=1)["window"]
    raw = build_timeframes(win)
    if drop_forming:
        raw = {tf: [b for b in rows if b.get("complete", True)]
               for tf, rows in raw.items()}
    return SB.build_snapshot(raw, symbol="MNQ")


def geometry(zone: dict) -> tuple:
    return tuple(zone.get(k) for k in EXECUTION_GEOMETRY_FIELDS)


# ── the forensic cases, pinned ────────────────────────────────────────────────

class TestTheRealTapeCases:

    def forming_minutes_common_to_all_htfs(self, end):
        """Minutes that belong to a STILL-FORMING bucket on 3m AND 5m AND 15m.

        CONTINUITY-2F.1. Perturbing more than this is not "vary only the forming
        bucket": at 14:49Z the 5m bucket is COMPLETE (5 members) while the 3m has
        2 forming minutes, so a 2-minute perturbation sized from the 3m rewrites
        a SETTLED 5m bucket -- and the settled comparator then legitimately moves,
        which looks exactly like a contract violation and is not one.
        """
        win = CONT.coherent_window([b for b in tape() if b["timestamp"] <= end],
                                   horizon_minutes=300, minimum_bars=1)["window"]
        raw = build_timeframes(win)
        ks = [raw[t][-1]["members"] for t in ("3m", "5m", "15m")
              if not raw[t][-1]["complete"]]
        return (win, min(ks)) if len(ks) == 3 else (win, 0)

    @staticmethod
    def perturb(win, k, shift):
        bars = [dict(b) for b in win]
        for b in bars[-k:]:
            b["high"] = round(b["high"] + max(shift, 0.0), 2)
            b["low"] = round(b["low"] + min(shift, 0.0), 2)
            b["close"] = round(b["close"] + shift, 2)
            b["high"] = max(b["high"], b["close"])
            b["low"] = min(b["low"], b["close"])
        return SB.build_snapshot(build_timeframes(bars), symbol="MNQ")

    def test_forming_CONTENT_alone_moves_the_invalidation_level(self):
        """CONTINUITY-2F.1 — THE CLEAN CASE, and the headline this file cites.

        Settled history byte-identical, same window, same `recent_candles`
        membership; only the OHLC of minutes that are forming on EVERY higher
        timeframe varies. Measured: `bullish_fvg` at 14:55Z moves its
        invalidation 29783.50 <-> 29759.25 -- 24.25 points -- purely from what
        the unfinished bar did, and the forming-authored variants are refused
        while the settled-matching ones are eligible.

        This SUPERSEDES the "forming bucket present vs dropped" comparison as
        proof of authorship. That comparison is confounded: dropping the bar also
        shifts the five-bar `recent_candles` window (four settled + one forming
        becomes five settled), so zones there differ partly for reasons unrelated
        to what the forming bar contained. It remains useful as a conservative
        signal; it is not evidence of content authorship.
        """
        win, k = self.forming_minutes_common_to_all_htfs("2026-08-11T14:55:00+00:00")
        assert k > 0, "no minute is forming on all three timeframes here"
        seen = {}
        for shift in (0.0, -12.0, -22.25, 9.75, 31.0):
            z = build_price_level("bullish_fvg", self.perturb(win, k, shift))
            seen[shift] = (z.get("invalidation_level"), z.get("execution_eligible"))
        invs = {v[0] for v in seen.values() if isinstance(v[0], (int, float))}
        assert max(invs) - min(invs) >= 24.0, seen
        assert 29783.5 in invs and 29759.25 in invs, seen
        # and the forming-authored variant is the one that gets refused
        assert seen[0.0] == (29783.5, False)
        assert seen[-12.0] == (29759.25, True)

    def test_the_settled_comparator_is_immune_to_that_perturbation(self):
        """The control. If this ever moves, the experiment above is measuring
        something other than forming authorship."""
        win, k = self.forming_minutes_common_to_all_htfs("2026-08-11T14:55:00+00:00")
        geoms = set()
        for shift in (0.0, -12.0, -22.25, 9.75, 31.0):
            snap = self.perturb(win, k, shift)
            cur = PL._current_price(snap)
            geoms.add(geometry(PL._locate_zone("fvg", "bullish", snap, cur,
                                               settled_only=True)))
        assert len(geoms) == 1, geoms

    def test_dropping_the_forming_bar_is_a_conservative_not_a_clean_signal(self):
        """Kept deliberately, and labelled. This comparison is what the original
        2F closeout cited as proof; it is retained as a REGRESSION that the tape
        still discriminates, not as evidence of content authorship."""
        moved = {}
        for end in ends():
            a, b = snap_at(end), snap_at(end, drop_forming=True)
            for tool in TOOLS:
                za, zb = build_price_level(tool, a), build_price_level(tool, b)
                ia, ib = za.get("invalidation_level"), zb.get("invalidation_level")
                if isinstance(ia, (int, float)) and isinstance(ib, (int, float)) \
                        and ia != ib:
                    moved[tool] = max(moved.get(tool, 0), abs(ia - ib))
        assert moved, "the fixture no longer reproduces the 2F defect"
        assert max(moved.values()) > 10.0, moved
        assert any("order_block" in t for t in moved), \
            "order blocks were the most affected family -- expected here"

    def test_a_forming_authored_fvg_has_no_settled_counterpart(self):
        """CASE A1 at 14:48Z on the 3m: the gap exists ONLY because of the
        forming bar."""
        snap = snap_at("2026-08-11T14:48:00+00:00")
        rc = snap["timeframes"]["3m"]["recent_candles"]
        assert rc[-1]["temporal_status"] == "forming"
        gaps = find_fvgs(rc, "bullish", 3)   # source_tf is the key read above
        authored = [g for g in gaps if g["index"] + 2 == len(rc) - 1]
        assert authored and authored[0]["low"] == 29759.25
        settled = [c for c in rc if c["temporal_status"] == "settled"]
        assert find_fvgs(settled, "bullish", 3) == [], \
            "the settled series unexpectedly carries the same gap"

    def test_such_a_zone_is_marked_ineligible(self):
        snap = snap_at("2026-08-11T14:48:00+00:00")
        flagged = [t for t in TOOLS
                   if build_price_level(t, snap).get("execution_eligible") is False]
        assert flagged, "no tool reported a provisional zone on a known case"

    def test_a_settled_zone_is_eligible_and_says_so(self):
        """CASE B. The contrast -- eligibility is not simply always False."""
        eligible = 0
        for end in ends():
            snap = snap_at(end)
            for tool in TOOLS:
                z = build_price_level(tool, snap)
                if z.get("level_type") != "no_zone" and z.get("execution_eligible"):
                    assert z["temporal_class"] == "settled"
                    assert geometry(z) == tuple(
                        z["settled_geometry"][k] for k in EXECUTION_GEOMETRY_FIELDS)
                    eligible += 1
        assert eligible > 0, "no zone was ever execution-eligible -- 2F over-blocks"


# ── the critical invariant ───────────────────────────────────────────────────

class TestExecutionGeometryIsInvariantToTheFormingBucket:
    """Hold all settled history fixed, vary only the forming bucket.
    Realtime witness MAY move. Anything eligible to author a stop MAY NOT."""

    def test_eligible_geometry_never_depends_on_the_forming_bucket(self):
        """VARY ONLY THE FORMING BUCKET'S CONTENT, settled history byte-identical.

        A first draft compared the production snapshot against one rebuilt with
        the forming bar dropped, and that is NOT the same question: dropping the
        bar also shifts the 5-bar `recent_candles` window (the settled snapshot
        gets five settled bars where the live one has four settled plus one
        forming), so zones differed for a reason unrelated to authorship. This
        perturbs the live minutes instead, which is the actual invariant.

        UPGRADED BY 2F.1 to the rigorous perturbation: only minutes forming on
        EVERY higher timeframe are varied, and a control asserts the settled
        comparator never moves. Sweeping the whole tape this way: settled
        comparator moved 0 times, eligible geometry moved 0 times, while 23
        realtime cases legitimately discriminated.
        """
        cases = TestTheRealTapeCases()
        checked = control = 0
        for end in ends():
            win, k = cases.forming_minutes_common_to_all_htfs(end)
            if not k:
                continue
            seen, settled_seen = {}, {}
            for shift in (0.0, 3.25, -12.0, -22.25, 31.0):
                snap = cases.perturb(win, k, shift)
                cur = PL._current_price(snap)
                for tool in TOOLS:
                    fam = PL._family(tool)
                    d = "bullish" if tool.startswith("bullish_") else "bearish"
                    sg = geometry(PL._locate_zone(fam, d, snap, cur, settled_only=True))
                    assert settled_seen.setdefault(tool, sg) == sg, \
                        f"{end} {tool}: the CONTROL moved -- perturbation touched " \
                        f"settled evidence, so this measurement is invalid"
                    control += 1
                    z = build_price_level(tool, snap)
                    if not z.get("execution_eligible"):
                        continue
                    g = geometry(z)
                    assert seen.setdefault(tool, g) == g, \
                        f"{end} {tool}: eligible geometry moved with forming " \
                        f"content {seen[tool]} -> {g}"
                    checked += 1
        assert control > 200, f"only {control} control samples"
        assert checked > 50, f"only {checked} eligible zones exercised"

    def test_the_witness_is_still_allowed_to_move(self):
        """2F is a split, not a blindfold. If nothing ever differed, the
        realtime opportunity would have been deleted rather than labelled."""
        differed = 0
        for end in ends():
            a, b = snap_at(end), snap_at(end, drop_forming=True)
            for tool in TOOLS:
                if geometry(build_price_level(tool, a)) != \
                        geometry(build_price_level(tool, b)):
                    differed += 1
        assert differed > 20, f"realtime zones no longer respond to the tape: {differed}"

    def compared_fields_detect(self, differing_field, value_a, value_b):
        """Drive `build_price_level` with two zones differing in ONE field and
        report whether the eligibility comparison noticed.

        Behavioural, because asserting the contents of
        EXECUTION_GEOMETRY_FIELDS is just restating the constant -- and dropping
        `invalidation_level` or `source_tf` from it ESCAPED the first mutation
        campaign for exactly that reason.
        """
        base = {"level_type": "fvg_zone", "direction": "bullish",
                "zone_low": 29750.0, "zone_high": 29760.0, "midpoint": 29755.0,
                "invalidation_level": 29740.0, "source_tf": "5m",
                "price_relation": "above_zone"}
        calls = []
        original = PL._locate_zone

        def fake(fam, direction, snapshot, current, settled_only):
            z = dict(base)
            z[differing_field] = value_b if settled_only else value_a
            calls.append(settled_only)
            return z

        PL._locate_zone = fake
        try:
            out = build_price_level("bullish_fvg", {"session": "ny_open",
                                                    "timeframes": {}})
        finally:
            PL._locate_zone = original
        assert calls == [False, True], calls
        return out["execution_eligible"]

    def test_a_differing_invalidation_alone_makes_the_zone_ineligible(self):
        """The single most load-bearing field: it becomes the STOP."""
        assert self.compared_fields_detect(
            "invalidation_level", 29740.0, 29733.0) is False
        assert self.compared_fields_detect(
            "invalidation_level", 29740.0, 29740.0) is True

    def test_a_differing_source_timeframe_alone_makes_it_ineligible(self):
        """Same bounds on a different timeframe is a different market object."""
        assert self.compared_fields_detect("source_tf", "5m", "15m") is False

    def test_differing_zone_bounds_alone_make_it_ineligible(self):
        assert self.compared_fields_detect("zone_low", 29750.0, 29744.5) is False
        assert self.compared_fields_detect("zone_high", 29760.0, 29777.25) is False

    def test_a_differing_level_type_alone_makes_it_ineligible(self):
        assert self.compared_fields_detect(
            "level_type", "fvg_zone", "order_block_zone") is False

    def test_temporal_class_agrees_with_the_verdict_on_real_tape(self):
        """`temporal_class` hardcoded to "settled" ESCAPED the first campaign
        because every assertion only checked membership in the allowed set."""
        provisional = settled = 0
        for end in ends():
            snap = snap_at(end)
            for tool in TOOLS:
                z = build_price_level(tool, snap)
                # STEP 4B.12 §6 UNIT 6 — assert against 2F's OWN verdict.
                #
                # `execution_eligible` now has two independent authors: this
                # temporal theorem, and (for plain FVG) whether the occurrence
                # behind the geometry is still a lawful setup. A zone whose
                # geometry is fully settled can therefore be refused for a
                # reason that is not temporal at all, and the biconditional
                # below would fail for a correct system. `temporal_class` is a
                # claim about THIS theorem, so it is checked against this
                # theorem's own published verdict -- which is exactly as strict:
                # a hardcoded "settled" would still be caught.
                expected = "settled" if z["temporal_execution_eligible"] else "provisional"
                assert z["temporal_class"] == expected, (end, tool, z)
                # and the composite may never be MORE permissive than 2F
                assert not (z["execution_eligible"]
                            and not z["temporal_execution_eligible"]), (end, tool)
                if z["execution_eligible"]:
                    settled += 1
                else:
                    provisional += 1
        assert provisional > 0 and settled > 0, \
            f"tape did not exercise both verdicts: {provisional=} {settled=}"

    def test_every_zone_declares_its_temporal_class(self):
        snap = snap_at(ends()[10])
        for tool in TOOLS:
            z = build_price_level(tool, snap)
            assert z.get("temporal_class") in ("settled", "provisional"), (tool, z)
            assert isinstance(z.get("execution_eligible"), bool)
            assert set(z.get("settled_geometry") or {}) == set(EXECUTION_GEOMETRY_FIELDS)

    def test_order_blocks_are_not_protected_by_coincidence(self):
        """`_find_ob` slices `candles[:-1]`. That never protected anything --
        appending a forming bar shifts WHICH candle is excluded."""
        moved = 0
        for end in ends():
            a, b = snap_at(end), snap_at(end, drop_forming=True)
            for tool in ("bullish_order_block", "bearish_order_block"):
                if geometry(build_price_level(tool, a)) != \
                        geometry(build_price_level(tool, b)):
                    moved += 1
        assert moved > 10, \
            "order-block geometry no longer moves -- the coincidence claim would " \
            "now be true and this test should be re-derived, not deleted"


# ── refusal, and the absence of substitution ─────────────────────────────────

class TestRefusalWithoutSubstitution:

    def zone(self, eligible: bool) -> dict:
        return {"level_type": "fvg_zone", "zone_low": 29750.0, "zone_high": 29760.0,
                "invalidation_level": 29740.0, "midpoint": 29755.0,
                "source_tf": "5m", "price_relation": "above_zone",
                "execution_eligible": eligible,
                "execution_ineligible_reason":
                    None if eligible else "TOOL_NOT_SETTLED: zone geometry depends "
                                          "on a forming bucket"}

    def snapshot_with(self, zone: dict) -> dict:
        return {"trade_intent": {"intent_type": "long", "direction": "bullish",
                                 "entry_zone": {"current_price": 29756.0,
                                                "midpoint": 29755.0,
                                                "price_relation": "above_zone"}},
                "toolbox": {"preferred_tool": "bullish_fvg",
                            "tool_candidates": [{"tool": "bullish_fvg",
                                                 "price_level": zone,
                                                 "effective_status": "ready"}]}}

    def test_order_builder_refuses_a_provisional_zone(self):
        from paper_execution.order_builder import build_order
        out = build_order(self.snapshot_with(self.zone(False)), "MNQ")
        assert out["valid"] is False
        assert "TOOL_NOT_SETTLED" in out["reject_reason"]

    def test_and_does_not_substitute_a_different_level(self):
        """A veto is a veto. The refusal must not carry a stop at all."""
        from paper_execution.order_builder import build_order
        out = build_order(self.snapshot_with(self.zone(False)), "MNQ")
        for key in ("stop_price", "stop_reference", "stop_distance", "qty"):
            assert key not in out or out.get(key) in (None, 0), (key, out)

    def test_the_ninjatrader_lane_refuses_rather_than_falling_back(self):
        """Its fallback chain exists for a MISSING level; an ineligible level
        must not enter it."""
        src = inspect.getsource(
            __import__("integrations.topstepx.deterministic.facts_provider",
                       fromlist=["x"]))
        assert "pl_ineligible = pl.get(\"execution_eligible\") is False" in src
        assert "if pl_ineligible:\n        invalidation = None" in src
        assert "elif not isinstance(invalidation, (int, float)):" in src, \
            "the structural fallback must be an ELIF -- an ineligible zone may " \
            "not fall through into a substituted level"

    def test_an_eligible_zone_still_builds_normally(self):
        from paper_execution.order_builder import build_order
        out = build_order(self.snapshot_with(self.zone(True)), "MNQ")
        assert out.get("reject_reason") != "TOOL_NOT_SETTLED"


# ── provenance, and what 2F must not have changed ────────────────────────────

class TestProvenanceAndScope:

    def test_the_zone_can_answer_what_authored_it(self):
        snap = snap_at(ends()[10])
        for tool in TOOLS:
            z = build_price_level(tool, snap)
            if z.get("level_type") == "no_zone":
                continue
            assert z.get("source_tf") in ("1m", "3m", "5m", "15m")
            assert z.get("level_type") and z.get("temporal_class")

    def test_eligibility_uses_the_2g_metadata_not_a_new_detector(self):
        src = inspect.getsource(PL._settled_only)
        assert 'c.get("temporal_status") == "settled"' in src
        # Match on CODE, not the docstring -- an earlier version of this
        # assertion failed on the word "completeness" inside the explanation.
        body = src.split('"""')[-1]
        for token in ('.get("complete"', '"members"', "expected_members"):
            assert token not in body, \
                f"2F must not grow a second completeness detector ({token})"

    def test_unknown_completeness_is_not_execution_authority(self):
        """A bar whose settlement was never recorded cannot support a stop."""
        assert PL._settled_only([{"temporal_status": "unknown"},
                                 {"temporal_status": "forming"}]) == []
        assert len(PL._settled_only([{"temporal_status": "settled"}])) == 1

    def test_the_topstepx_invalidation_catalog_is_untouched(self):
        """Production MNQ prices its stop from protected_swings + flips, not
        from the toolbox. 2F must not have redirected that."""
        from broker import luna_candidate_producer as LP
        src = inspect.getsource(LP.authorized_invalidation_catalog)
        assert "protected_swings" in src
        assert "price_level" not in src and "toolbox" not in src

    def test_risk_ceiling_and_playbook_ranking_were_not_touched(self):
        from broker import topstepx_combine_risk as R
        # 35 PREFERRED / 50 ABSOLUTE — the doctrine pair. An earlier draft of
        # this test asserted the ceiling as the preferred value.
        assert R.PREFERRED_MAX_STOP_POINTS == 35.0
        assert R.ABSOLUTE_MAX_STOP_POINTS == 50.0
        from toolbox import toolbox_engine as TB
        # STEP 4B.12 §6 UNIT 6 — STRUCTURAL, not a module-wide text scan.
        #
        # The original guard was `"execution_eligible" not in getsource(TB)`.
        # It proved the invariant by proving the TOKEN was absent, which stopped
        # working the moment the module legitimately PUBLISHED an eligibility
        # FACT: `occurrence_execution_eligible` contains that substring and
        # participates in no arithmetic at all. A text scan cannot tell a
        # published field from a consumed one.
        #
        # The invariant is unchanged and is now asserted where it actually
        # lives: no function that can author a score or an ordering may READ
        # any eligibility or temporal-authority fact.
        import ast
        import textwrap
        authors = [TB._local_fvg, TB._local_ifvg, TB._local_breaker,
                   TB._local_order_block, TB._family_context_score,
                   TB._context_score, TB.score_instance, TB.tool_instances,
                   TB._raw_status, TB._effective_status]
        forbidden = {"execution_eligible", "occurrence_execution_eligible",
                     "temporal_execution_eligible", "temporal_class",
                     "execution_ineligible_reason", "occurrence_ineligible_reason"}
        for fn in authors:
            tree = ast.parse(textwrap.dedent(inspect.getsource(fn)))
            read = {n.value for n in ast.walk(tree)
                    if isinstance(n, ast.Constant) and isinstance(n.value, str)}
            read |= {n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute)}
            leaked = read & forbidden
            # `tool_instances`/`fvg_occurrence_instances` may CARRY these facts
            # onto the published instance; what they may not do is let one reach
            # the score. So the ban applies to every scoring author, and for the
            # instance builders it is enforced by the score-provenance check.
            if fn in (TB.tool_instances,):
                continue
            assert not leaked, \
                f"{fn.__name__} consumes execution authority: {leaked}"
        # and the score is composed ONLY of its two declared owners
        src = inspect.getsource(TB.score_instance)
        assert "local_score + context" in src, "score provenance changed"

    def test_the_fvg_occurrence_score_cannot_consume_eligibility(self):
        """`fvg_occurrence_instances` AUTHORS a score and legitimately CARRIES
        eligibility facts, so a forbidden-key scan would false-positive on it.
        The invariant is proved by DATAFLOW instead: trace what the score
        expression actually depends on.
        """
        import ast
        import textwrap
        from toolbox import toolbox_engine as TB
        tree = ast.parse(textwrap.dedent(
            inspect.getsource(TB.fvg_occurrence_instances)))

        # 1. the two score inputs come from the declared owners, nothing else
        assigns = {t.id: n.value for n in ast.walk(tree)
                   if isinstance(n, ast.Assign)
                   for t in n.targets if isinstance(t, ast.Name)}
        assert "local_score" in assigns and "context" in assigns
        called = {c.func.id for c in ast.walk(assigns["local_score"])
                  if isinstance(c, ast.Call) and isinstance(c.func, ast.Name)}
        called |= {"local"} if isinstance(assigns["local_score"], ast.Call) else set()
        ctx_calls = {c.func.id for c in ast.walk(assigns["context"])
                     if isinstance(c, ast.Call) and isinstance(c.func, ast.Name)}
        assert ctx_calls == {"_family_context_score", "_context_score"}, ctx_calls

        # 2. the published `score` depends ONLY on those two names
        score_expr = None
        for n in ast.walk(tree):
            if isinstance(n, ast.Dict):
                for k, v in zip(n.keys, n.values):
                    if isinstance(k, ast.Constant) and k.value == "score":
                        score_expr = v
        assert score_expr is not None, "no score key found"
        names = {x.id for x in ast.walk(score_expr) if isinstance(x, ast.Name)}
        assert names <= {"local_score", "context", "max", "min"}, names

        # 3. no eligibility/lifecycle value can reach it
        forbidden = {"execution_eligible", "occurrence_execution_eligible",
                     "temporal_execution_eligible", "temporal_class", "retired",
                     "execution_ineligible_reason", "occurrence_ineligible_reason"}
        reachable = {x.value for x in ast.walk(score_expr)
                     if isinstance(x, ast.Constant) and isinstance(x.value, str)}
        assert not (reachable & forbidden), reachable & forbidden

        # 4. and ranking is by score/tool_id only -- never by eligibility
        rank = ast.parse(textwrap.dedent(inspect.getsource(TB.tool_instances)))
        keys = {c.value for c in ast.walk(rank)
                if isinstance(c, ast.Constant) and isinstance(c.value, str)}
        assert not (keys & forbidden), f"ranking consumes authority: {keys & forbidden}"
