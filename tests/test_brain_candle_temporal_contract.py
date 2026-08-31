"""CONTINUITY-2G — the Brain is told each candle's temporal status.

The V19 fanout audit's fifth violation: `brain_input` shipped `recent_candles`
per timeframe with no `complete` / `members`, because `normalize_candle`
whitelists them away. Terra received a 15m bar that was six minutes old and
could not tell it from a finished one. The law's last clause --

    realtime context may observe forming evidence,
    but it may never counterfeit confirmation

-- was unenforceable at that boundary, not because the Brain misbehaved, but
because it was never given the fact.

2G is NOT "stop stripping the flags". It is a provable temporal CONTRACT:

    settled   the bucket is closed; its OHLC is final
    forming   still building (members 6 of expected_members 15)
    unknown   completeness genuinely was not recorded -- say so, never guess

SAFETY BY BLINDNESS IS EXPLICITLY NOT THE GOAL. The forming bar must still
arrive, in full, on every timeframe. These tests pin BOTH halves at once.

The gold case is the same 2026-08-11 bar the whole of Step 2 has been fought
over: the 15m bucket that was 6/15 formed at 15:05Z and against which 29,805.0
was falsely "confirmed" as a swing high.
"""
from __future__ import annotations

import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))

from data_feed import candle_continuity as CONT                   # noqa: E402
from data_feed.timeframe_builder import build_timeframes          # noqa: E402
from market_data.snapshot_builder import (                        # noqa: E402
    build_snapshot, _temporal_status, _bucket_is_settled, SETTLED, FORMING, UNKNOWN,
)
from ai_brain.brain_input import build_brain_input                # noqa: E402

FIXTURE = os.path.join(ROOT, "tests", "fixtures",
                       "mnq_20260811_1420Z_1510Z_1m.json")
GOLD = "2026-08-11T15:05:00+00:00"


def tape() -> list:
    with open(FIXTURE, encoding="utf-8") as fh:
        return json.load(fh)["bars"]


def raw_at(end: str = GOLD) -> dict:
    bars = [b for b in tape() if b["timestamp"] <= end]
    window = CONT.coherent_window(bars, horizon_minutes=300,
                                  minimum_bars=1)["window"]
    return build_timeframes(window)


def payload(end: str = GOLD) -> dict:
    snap = build_snapshot(raw_at(end), symbol="MNQ")
    return build_brain_input(snap, {})


# ── the contract itself ───────────────────────────────────────────────────────

class TestThreeStatesNotTwo:

    def test_settled_forming_and_unknown_are_distinguishable(self):
        raw = [{"timestamp": "t_done", "complete": True, "members": 15,
                "expected_members": 15},
               {"timestamp": "t_live", "complete": False, "members": 6,
                "expected_members": 15},
               {"timestamp": "t_archive"}]
        assert _temporal_status(raw, {"timestamp": "t_done"}, "15m") == {
            "temporal_status": SETTLED, "members": 15, "expected_members": 15}
        assert _temporal_status(raw, {"timestamp": "t_live"}, "15m") == {
            "temporal_status": FORMING, "members": 6, "expected_members": 15}
        assert _temporal_status(raw, {"timestamp": "t_archive"}, "15m") == {
            "temporal_status": UNKNOWN, "members": None, "expected_members": 15}

    def test_unknown_is_not_silently_reported_as_settled(self):
        """The 2D policy TREATS unknown as settled; 2G refuses to SAY it is."""
        archive = [{"timestamp": "t"}]
        assert _bucket_is_settled(archive, {"timestamp": "t"}) is True
        assert _temporal_status(archive, {"timestamp": "t"})["temporal_status"] \
            == UNKNOWN

    def test_only_forming_is_treated_as_unsettled(self):
        for raw, settled in (([{"timestamp": "t", "complete": True}], True),
                             ([{"timestamp": "t", "complete": False}], False),
                             ([{"timestamp": "t"}], True),
                             ([], True), (None, True)):
            assert _bucket_is_settled(raw, {"timestamp": "t"}) is settled, raw

    def test_membership_is_interpretable(self):
        """`members: 6` alone is meaningless -- 6 of what?"""
        for tf, minutes in (("3m", 3), ("5m", 5), ("15m", 15)):
            for bar in raw_at()[tf]:
                assert bar["expected_members"] == minutes, (tf, bar)
                assert bar["complete"] == (bar["members"] == minutes)

    def test_one_minute_publishes_its_settledness_rather_than_omitting_it(self):
        """Relays the provider contract (a developing minute is never emitted),
        so 1m is no longer indistinguishable from an unlabelled archive."""
        for bar in raw_at()["1m"]:
            assert bar["complete"] is True
            assert bar["members"] == 1 and bar["expected_members"] == 1

    def test_build_timeframes_does_not_mutate_the_callers_candles(self):
        src = [{"timestamp": "2026-08-11T14:20:00+00:00", "open": 1.0, "high": 2.0,
                "low": 0.5, "close": 1.5, "volume": 10}]
        build_timeframes(src)
        assert "complete" not in src[0] and "members" not in src[0]


# ── the gold case, end to end ─────────────────────────────────────────────────

class TestTheBrainSeesTheFormingBarAndKnowsItIsForming:
    """Both halves, asserted together, on the real 29,805 bar."""

    def test_the_forming_15m_bucket_is_present_in_the_brain_payload(self):
        block = payload()["market"]["candles"]["15m"]
        assert block["recent"], "the forming bar disappeared from Brain input"
        assert block["last_close"] is not None

    def test_and_it_is_labelled_forming_six_of_fifteen(self):
        block = payload()["market"]["candles"]["15m"]
        assert block["last_candle_temporal_status"] == FORMING
        assert block["last_candle_members"] == 6
        assert block["last_candle_expected_members"] == 15

    def test_the_settled_bars_behind_it_say_settled(self):
        recent = payload()["market"]["candles"]["15m"]["recent"]
        assert [c["temporal_status"] for c in recent[:-1]] == \
            [SETTLED] * (len(recent) - 1)
        assert recent[-1]["temporal_status"] == FORMING

    def test_every_candle_carries_its_own_status_not_just_the_newest(self):
        for tf, block in payload()["market"]["candles"].items():
            for c in block["recent"]:
                assert c.get("temporal_status") in (SETTLED, FORMING, UNKNOWN), (tf, c)
                assert "expected_members" in c, (tf, c)

    def test_one_minute_reaches_the_brain_as_settled(self):
        block = payload()["market"]["candles"]["1m"]
        assert block["last_candle_temporal_status"] == SETTLED
        assert block["last_candle_expected_members"] == 1

    def test_the_29805_pivot_is_the_bar_being_labelled(self):
        """Anchors this suite to the actual defect: that 6/15 bucket is the one
        `find_swings` used as right-side confirmation for 29,805.0."""
        from structure.structure_engine import find_swings
        buckets = raw_at()["15m"]
        # STEP 4B.12 §4 UNIT 1 — swing evidence held constant at legacy geometry so
        # the variable under test stays what it always was. Unit 1 added an
        # INDEPENDENT guard that also refuses this pivot; one defence getting
        # stronger may not silently delete coverage of another.
        assert find_swings(buckets, allow_uncadenced=True)[0] == [29805.0]
        assert find_swings([b for b in buckets if b["complete"]])[0] == []
        assert buckets[-1]["members"] == 6 and buckets[-1]["complete"] is False
        assert payload()["market"]["candles"]["15m"][
            "last_candle_temporal_status"] == FORMING


# ── honesty about what is not known ───────────────────────────────────────────

class TestUnknownIsReportedNotGuessed:

    def stripped_payload(self) -> dict:
        raw = {tf: [{k: v for k, v in bar.items()
                     if k not in ("complete", "members", "expected_members")}
                    for bar in bars]
               for tf, bars in raw_at().items()}
        return build_brain_input(build_snapshot(raw, symbol="MNQ"), {})

    def test_an_unlabelled_archive_reports_unknown(self):
        for tf, block in self.stripped_payload()["market"]["candles"].items():
            assert block["last_candle_temporal_status"] == UNKNOWN, tf

    def test_and_says_so_in_degraded(self):
        degraded = self.stripped_payload()["degraded"]
        marker = [d for d in degraded
                  if d.startswith("candle_temporal_status_unknown:")]
        assert marker, degraded
        for tf in ("15m", "5m", "3m", "1m"):
            assert tf in marker[0]

    def test_a_live_scan_never_reports_unknown(self):
        assert not [d for d in payload()["degraded"]
                    if d.startswith("candle_temporal_status_unknown")]


# ── the prompt contract ───────────────────────────────────────────────────────

class TestThePromptExplainsTheField:

    def addendum(self) -> str:
        """The clause with runs of whitespace collapsed.

        Assertions that embed the prompt's exact line wrapping break whenever a
        sentence is re-flowed, which says nothing about whether the CONTRACT
        changed. Match on wording, not on where the lines happen to end.
        """
        import re
        from ai_brain.brain_prompt import CANDLE_TEMPORAL_ADDENDUM
        return re.sub(r"\s+", " ", CANDLE_TEMPORAL_ADDENDUM)

    def test_it_defines_all_three_states(self):
        text = self.addendum()
        for state in (SETTLED, FORMING, UNKNOWN):
            assert state in text

    def test_it_states_the_one_rule(self):
        text = self.addendum().lower()
        assert "you must distinguish those from claims whose definition requires a settled bar" \
            in text
        assert "as confirmed until the evidence it requires has settled" in text

    def test_it_does_not_tell_the_brain_to_ignore_the_forming_bar(self):
        text = self.addendum().lower()
        assert "is not a reason to ignore any candle" in text
        assert "you may state intrabar events that have objectively occurred" in text

    # ── the 2026-08-11 wording correction ─────────────────────────────────────
    # The first version of this clause smuggled ICT doctrine into a section that
    # declares itself non-doctrinal. These pin the correction so it cannot creep
    # back in.

    def test_intrabar_events_may_still_be_named(self):
        """An intrabar sweep IS a real event. If price traded above a prior high
        that excursion objectively occurred, and forbidding the Brain to say so
        is blindness by language, not temporal honesty."""
        text = self.addendum().lower()
        assert "an excursion that has happened has happened, " \
               "whether or not the bucket has closed" in text
        assert "price traded above/below a level" in text
        # the old blanket prohibition must not return
        assert "swept anything" not in text
        assert "a break that has not closed is not a break" not in text

    def test_it_does_not_invent_close_requirements(self):
        """Only claims whose OWN definition needs a close are gated."""
        text = self.addendum().lower()
        assert "where an event's definition does not require a candle close, " \
               "do not invent a close requirement merely because the bar is forming" in text

    def test_the_provisional_close_is_stated_as_may_not_will(self):
        """A forming close CAN finish at the last traded price. 'WILL change'
        overstated a fact inside a clause that claims to be factual."""
        text = self.addendum()
        assert "its close may change before the bucket closes" in text
        assert "close WILL change" not in text
        assert "PROVISIONAL" in text

    def test_it_still_declares_itself_non_doctrinal(self):
        text = self.addendum().lower()
        assert "adds no trading rule" in text
        assert "grants no direction" in text

    def test_it_is_attached_only_when_the_payload_carries_the_field(self):
        from ai_brain.narrative_brain import _candles_carry_temporal_status
        assert _candles_carry_temporal_status(payload()) is True
        assert _candles_carry_temporal_status(
            {"market": {"candles": {"15m": {"recent": [{"close": 1}]}}}}) is False
        assert _candles_carry_temporal_status({}) is False
        assert _candles_carry_temporal_status(None) is False

    def test_the_live_prompt_actually_carries_it(self):
        """Assert the ASSEMBLED prompt at the real call site, not just the
        constant.

        HERMETIC BY CONSTRUCTION: `_call_llm` builds `out["prompt"]` before it
        reaches any network guard, so disabling the adapter makes it return with
        the prompt fully assembled and nothing sent.

        Popping OPENAI_API_KEY is NOT sufficient and was measured to be
        insufficient: `_call_llm` imports the adapter AFTER that point, the
        import reloads the .env, and the first version of this test billed a
        real 17.4-second API call. The `fallback_reason` / `raw_response`
        assertions below are what prove no request was sent.
        """
        record = self.call_without_network(payload())
        assert "CANDLE TEMPORAL STATUS" in record["prompt"]
        assert "You MAY state intrabar events that have OBJECTIVELY OCCURRED" \
            in record["prompt"]
        assert "You MUST distinguish those from claims whose definition REQUIRES" \
            in record["prompt"]

    def test_an_archive_without_the_field_gets_the_base_prompt(self):
        record = self.call_without_network({"market": {"candles": {}}})
        assert "CANDLE TEMPORAL STATUS" not in record["prompt"]

    @staticmethod
    def call_without_network(brain_input: dict) -> dict:
        import ai_brain.narrative_brain as NB
        import ai_layer.ai_api_adapter as AD
        available = AD._OPENAI_AVAILABLE
        AD._OPENAI_AVAILABLE = False
        try:
            record = NB._call_llm(brain_input)
        finally:
            AD._OPENAI_AVAILABLE = available
        assert record["fallback_reason"] == "openai_package_unavailable", record
        assert record["raw_response"] is None and record["parsed"] is None, \
            "a network call escaped this test"
        return record


# ── what 2G must not have changed ─────────────────────────────────────────────

class TestNothingElseMoved:

    def test_price_fields_are_untouched(self):
        raw = raw_at()
        snap = build_snapshot(raw, symbol="MNQ")
        from market_data.candle_normalizer import normalize_candles
        from market_data.session_engine import get_session_label
        from market_data.snapshot_builder import CANONICAL_RETAINED_BARS
        for tf in ("15m", "5m", "3m", "1m"):
            # PHASE 4A (2026-08-12): canonical retention is no longer the Brain's
            # old 5-bar presentation horizon. The point of THIS test is unchanged
            # and still enforced below -- every original price field survives
            # annotation byte-for-byte -- only the retained span moved.
            expected = normalize_candles(raw[tf],
                                         get_session_label)[-CANONICAL_RETAINED_BARS[tf]:]
            got = snap["timeframes"][tf]["recent_candles"]
            assert len(got) == len(expected)
            for a, b in zip(got, expected):
                for key in b:                       # every original key survives
                    assert a[key] == b[key], (tf, key)

    def test_detector_inputs_were_not_annotated(self):
        """`all_normalized` / `all_settled` feed the detectors; 2G touches only
        the realtime/Brain channel."""
        import ast
        import inspect
        import textwrap
        from market_data import snapshot_builder as SB
        src = inspect.getsource(SB.build_snapshot)
        assert "all_normalized[tf] = normalized" in src, \
            "detector input is no longer the plain normalized series"
        # STEP 4B.12 §6 UNIT 6 — STRUCTURAL, not a literal pin of the expression.
        #
        # This asserted the annotation's exact source text, so it broke when
        # Unit 6 added `_source_contract` to the SAME additive enrichment --
        # a change that does not touch the detector channel at all. The
        # proposition is that `annotated` is a SEPARATE binding built from
        # `normalized`, and that the detector inputs receive the plain series.
        tree = ast.parse(textwrap.dedent(src))

        # EVENT-WAKE-ACTIONABLE-STRUCTURE-1 — FOLLOW THE COMPOSITION.
        #
        # The `annotated` comprehension was EXTRACTED into the shared
        # `annotated_timeframe` so the wake registry and the snapshot cannot
        # disagree about what "settled" means. The three propositions are
        # unchanged; they now have to be checked across that seam.
        #
        # Simply deleting the `annotated` assertions would have left the third
        # one VACUOUSLY TRUE -- `annotated` no longer occurs in `build_snapshot`
        # at all, so "the detector channel is not fed `annotated`" would pass
        # even if the detector channel were fed the annotated series under
        # another name. The realtime binding is therefore named explicitly and
        # the detector channel is checked against it.
        REALTIME = "annotated_timeframe"
        assert any(isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
                   and n.func.id == REALTIME for n in ast.walk(tree)), \
            "the realtime channel no longer routes through the shared annotator"

        ann = [n for n in ast.walk(ast.parse(textwrap.dedent(
                   inspect.getsource(SB.annotated_timeframe))))
               if isinstance(n, ast.Assign)
               and any(isinstance(t, ast.Name) and t.id == "annotated"
                       for t in n.targets)]
        assert ann, "the shared annotator no longer builds an `annotated` series"
        assert isinstance(ann[0].value, ast.ListComp), \
            "`annotated` is no longer a comprehension over the normalized series"

        # the detector channels are assigned the PLAIN series, never the
        # annotated one — under EITHER name, on EITHER side of the extraction
        for target in ("all_normalized", "all_settled"):
            for n in ast.walk(tree):
                if isinstance(n, ast.Assign) and any(
                        isinstance(t, ast.Subscript)
                        and isinstance(t.value, ast.Name)
                        and t.value.id == target for t in n.targets):
                    names = {x.id for x in ast.walk(n.value)
                             if isinstance(x, (ast.Name, ast.Attribute))
                             and isinstance(x, ast.Name)}
                    assert not names & {"annotated", REALTIME}, \
                        f"{target} was fed the annotated series"

    def test_structure_and_liquidity_are_unchanged_by_2g(self):
        snap = build_snapshot(raw_at(), symbol="MNQ")
        assert snap["structure"]["3m"].get("bos") is False
        assert snap["liquidity"]["3m"].get("nearest_sell_side_liquidity") == 29723.25
