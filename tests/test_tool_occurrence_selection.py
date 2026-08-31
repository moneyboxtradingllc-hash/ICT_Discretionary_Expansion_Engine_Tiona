"""TOOL-OCCURRENCE-SELECTION-1 — she could see the gap and not point at it.

PLAIN-FVG-EXECUTABLE-REPRESENTATION-1 gave every plain FVG a canonical identity.
Measured immediately afterwards on 40 archived scans, with the toolbox and
catalog RECOMPUTED rather than replayed:

    BEARISH `fvg`   16-26 eligible occurrences   AMBIGUOUS in 40 of 40 scans
    BULLISH `fvg`   resolves uniquely in 15      AMBIGUOUS in 12

Luna's output contract could say `recommended_tool_family = ["fvg"]` and nothing
more. A family token does not say WHICH gap, and mechanics -- correctly refusing
to choose among discretionary objects -- answered TOOL_OCCURRENCE_AMBIGUOUS
instead of taking the trade she meant. She could SEE every `occurrence_id` in her
catalog; she had no field in which to return one.

    LUNA SELECTS. MECHANICS VERIFIES.

This is the same theorem `objective_id` and `invalidation_id` were given on
2026-08-07 -- "executable identity comes from an id chosen out of the published
catalog, never from text" -- applied to the one selectable object it skipped.

IT IS A JOIN KEY, NEVER A RANKING. Mechanics matches the id Luna named INSIDE
the already-filtered eligible set and takes exactly that row. It never
substitutes, never falls back to the first row, and never ranks alternatives.

WHY THE JOIN-KEY TEST IS THE LOAD-BEARING ONE. `invalidation_id` proves a schema
field can exist, be traced, own error names, and still never be enforced -- the
real stop authority remained the raw `invalidation_level` number. So proving the
field survives validation proves nothing. `test_a_NON_FIRST_occurrence_actually_
controls_the_execution_object` is the test that matters.
"""
from __future__ import annotations

import copy
import json
import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))

from ai_brain import brain_schema as BS                              # noqa: E402
from broker.luna_candidate_producer import (CandidateProducer,       # noqa: E402
                                            NoCandidate,
                                            authorized_tool_catalog)
from broker.topstepx_client import TopstepXContract                  # noqa: E402
from toolbox.toolbox_engine import run_toolbox                       # noqa: E402

ARCHIVE = os.path.join(ROOT, "data", "ai_brain")
SPECIMEN = "20260821_102511_MNQ.json"
CONTRACT = "CON.F.US.MNQ.U26"
MNQ = TopstepXContract(id=CONTRACT, name="MNQU6", description="",
                       tick_size=0.25, tick_value=0.50, active=True)

# Specimen A: the sole eligible bullish gap at 10:25.
BULL_LOW, BULL_HIGH = 29243.00, 29251.25
BULL_ID = f"FVG:{CONTRACT}:1m:2026-08-21T14:23:00+00:00"


def snap():
    path = os.path.join(ARCHIVE, SPECIMEN)
    if not os.path.exists(path):
        pytest.skip("archived production snapshot absent")
    with open(path, encoding="utf-8") as fh:
        s = copy.deepcopy(json.load(fh)["raw_snapshot"])
    s["contract_id"] = CONTRACT
    s["toolbox"] = run_toolbox(s)          # production recomputes this every scan
    return s


def catalog(s=None):
    return authorized_tool_catalog(s if s is not None else snap())


def eligible(direction, tool=None, s=None):
    want = tool or f"{direction}_fvg"
    return [r for r in catalog(s)
            if r.get("tool") == want and r.get("execution_eligible")]


def resolve(direction, occurrence_id=None, s=None, tools=("fvg",), trace=None):
    producer = CandidateProducer(account_fingerprint="acct:test", contract=MNQ)
    return producer._assert_tool_detected(list(tools), direction,
                                          s if s is not None else snap(),
                                          trace, occurrence_id=occurrence_id)


# ══════════════════════════════════════════════════════════════════════════════
class TestTheMeasuredDefect:
    def test_a_bearish_family_token_is_massively_ambiguous(self):
        assert len(eligible("bearish")) > 1

    def test_the_field_now_exists_beside_its_siblings(self):
        fields = BS.LLM_OUTPUT_FIELDS if hasattr(BS, "LLM_OUTPUT_FIELDS") else None
        blob = json.dumps({k: str(v) for k, v in
                           (fields or getattr(BS, "_FIELDS", {})).items()}) \
            if fields or hasattr(BS, "_FIELDS") else ""
        import inspect
        src = inspect.getsource(BS)
        assert '"recommended_tool_occurrence_id"' in src
        assert '"objective_id"' in src and '"invalidation_id"' in src

    def test_the_prompt_tells_her_the_field_exists(self):
        from ai_brain.brain_prompt import BRAIN_SYSTEM_PROMPT
        assert "recommended_tool_occurrence_id" in BRAIN_SYSTEM_PROMPT
        assert "PLAIN FVG ONLY" in BRAIN_SYSTEM_PROMPT
        assert "selects nothing outside plain FVG" in BRAIN_SYSTEM_PROMPT

    def test_she_can_already_see_the_ids_she_must_name(self):
        for row in eligible("bearish"):
            assert row.get("occurrence_id")


class TestTheJoinKey:
    """The load-bearing proofs. A field that parses but never controls the
    execution object is exactly the `invalidation_id` failure repeated."""

    def test_a_NON_FIRST_occurrence_is_what_the_resolver_returns(self):
        rows = eligible("bearish")
        assert len(rows) > 3, "need several eligible gaps for this proof"
        target = rows[len(rows) // 2]          # deliberately NOT rows[0]
        assert target["occurrence_id"] != rows[0]["occurrence_id"]
        got = resolve("bearish", target["occurrence_id"])
        assert got["occurrence_id"] == target["occurrence_id"]
        assert (got["zone_low"], got["zone_high"]) == (target["zone_low"],
                                                       target["zone_high"])
        assert got["source_tf"] == target["source_tf"]

    def test_every_eligible_occurrence_is_individually_selectable(self):
        """Not just one lucky row."""
        rows = eligible("bearish")
        for target in rows:
            got = resolve("bearish", target["occurrence_id"])
            assert got["occurrence_id"] == target["occurrence_id"]

    def test_the_trace_records_what_was_requested_and_what_matched(self):
        rows = eligible("bearish")
        target = rows[-1]
        trace = {}
        resolve("bearish", target["occurrence_id"], trace=trace)
        assert trace["tool_requested_occurrence_id"] == target["occurrence_id"]
        assert trace["tool_matched_occurrence_id"] == target["occurrence_id"]
        assert trace["tool_rejection_reason"] is None

    def test_mechanics_never_ranks(self):
        import inspect
        src = inspect.getsource(CandidateProducer._assert_tool_detected)
        for banned in ("sorted(eligible", "max(eligible", "min(eligible",
                       "key=lambda", ".sort("):
            assert banned not in src, banned


class TestRequiredNegatives:
    def test_1_multiple_eligible_and_no_id_still_refuses(self):
        with pytest.raises(NoCandidate) as e:
            resolve("bearish", None)
        assert e.value.reason == "tool_occurrence_ambiguous"

    def test_2_a_nonexistent_id_refuses(self):
        with pytest.raises(NoCandidate) as e:
            resolve("bearish", f"FVG:{CONTRACT}:1m:1999-01-01T00:00:00+00:00")
        assert e.value.reason == "tool_occurrence_unknown"

    def test_3_an_opposite_direction_id_refuses(self):
        bull = eligible("bullish")[0]["occurrence_id"]
        with pytest.raises(NoCandidate) as e:
            resolve("bearish", bull)
        assert e.value.reason == "tool_occurrence_unknown"

    def test_4_an_id_from_another_family_refuses(self):
        other = [r for r in catalog()
                 if r.get("tool_family") not in (None, "fvg") and r.get("occurrence_id")]
        probe = other[0]["occurrence_id"] if other else "BOS:X:1m:2026-01-01T00:00:00+00:00"
        with pytest.raises(NoCandidate) as e:
            resolve("bearish", probe)
        assert e.value.reason == "tool_occurrence_unknown"

    def test_5_an_ineligible_occurrence_refuses_even_though_it_is_published(self):
        dead = [r for r in catalog()
                if r.get("tool") == "bullish_fvg"
                and not r.get("execution_eligible") and r.get("occurrence_id")]
        if not dead:
            pytest.skip("no published-but-ineligible bullish gap in this snapshot")
        with pytest.raises(NoCandidate) as e:
            resolve("bullish", dead[0]["occurrence_id"])
        assert e.value.reason == "tool_occurrence_unknown"

    @pytest.mark.parametrize("junk", [
        "not-an-id", "FVG:", "::::", "FVG:WRONG.CONTRACT:1m:2026-08-21T14:23:00+00:00",
        "fvg:con.f.us.mnq.u26:1m:2026-08-21t14:23:00+00:00",   # case matters
    ])
    def test_6_a_malformed_id_refuses_and_is_never_repaired(self, junk):
        with pytest.raises(NoCandidate) as e:
            resolve("bearish", junk)
        assert e.value.reason == "tool_occurrence_unknown"

    def test_7_exactly_one_eligible_and_null_id_is_unchanged(self):
        assert len(eligible("bullish")) == 1
        got = resolve("bullish", None)
        assert (got["zone_low"], got["zone_high"]) == (BULL_LOW, BULL_HIGH)

    def test_8_exactly_one_eligible_and_its_own_id_resolves_the_same_object(self):
        by_family = resolve("bullish", None)
        by_id = resolve("bullish", BULL_ID)
        assert by_id["occurrence_id"] == by_family["occurrence_id"] == BULL_ID

    def test_9_specimen_A_still_resolves_without_the_new_field(self):
        got = resolve("bullish", None)
        assert got["occurrence_id"] == BULL_ID
        assert (got["zone_low"], got["zone_high"]) == (BULL_LOW, BULL_HIGH)
        assert got["source_tf"] == "1m"


class TestBlankAndAbsentAreTheSame:
    @pytest.mark.parametrize("empty", [None, "", "   ", "\t"])
    def test_an_empty_selection_falls_through_to_family_behaviour(self, empty):
        got = resolve("bullish", empty)
        assert got["occurrence_id"] == BULL_ID

    @pytest.mark.parametrize("empty", [None, "", "   "])
    def test_and_still_refuses_when_ambiguous(self, empty):
        with pytest.raises(NoCandidate) as e:
            resolve("bearish", empty)
        assert e.value.reason == "tool_occurrence_ambiguous"


class TestNonFvgIsolation:
    """The field must be OBSERVATIONALLY IRRELEVANT outside plain FVG.

    An ungated version of the selection branch shipped two proven defects:

        non-FVG + any non-null id   -> every non-FVG row carries occurrence_id
          None, so nothing matched and a lawful trade was REFUSED. A prompt
          violation must not kill a family this field has no authority over.

        non-FVG + the literal "None" -> `str(None) == "None"` matched every such
          row, and with one eligible row it SELECTED it. A hallucinated value
          acquiring selection authority is the opposite of fail-closed.

    Both are closed by scoping the branch to exact family equality with "fvg"
    and refusing to treat a missing identity as a selectable name.
    """

    FAMILIES = (("rejection_block", "bearish"), ("breaker", "bullish"),
                ("ote_after_reclaim", "bullish"))
    PROBES = (None, "", "None", "null", "zzz", "FVG:X:1m:2026-01-01T00:00:00+00:00",
              "FVG:CON.F.US.MNQ.U26:1m:2026-08-21T14:23:00+00:00")

    @staticmethod
    def outcome(family, direction, occurrence_id):
        try:
            return ("ok", resolve(direction, occurrence_id, tools=(family,))["tool"])
        except NoCandidate as exc:
            return ("refused", exc.reason)

    def test_non_fvg_rows_carry_no_occurrence_identity(self):
        """The precondition that made both defects possible."""
        for row in catalog():
            if row.get("tool_family") != "fvg":
                assert row.get("occurrence_id") is None, row.get("tool")

    @pytest.mark.parametrize("family,direction", FAMILIES)
    @pytest.mark.parametrize("probe", PROBES)
    def test_the_field_changes_nothing_outside_fvg(self, family, direction, probe):
        baseline = self.outcome(family, direction, None)
        assert self.outcome(family, direction, probe) == baseline, probe

    @pytest.mark.parametrize("family,direction", FAMILIES)
    def test_a_bogus_id_never_refuses_a_lawful_non_fvg_tool(self, family, direction):
        """Defect A."""
        kind, _ = self.outcome(family, direction, "FVG:X:1m:2026-01-01T00:00:00+00:00")
        assert kind == self.outcome(family, direction, None)[0]

    @pytest.mark.parametrize("family,direction", FAMILIES)
    def test_the_literal_None_is_not_a_wildcard(self, family, direction):
        """Defect B — `str(None)` must never become a selectable name."""
        assert self.outcome(family, direction, "None") == \
            self.outcome(family, direction, None)

    def test_the_branch_is_gated_by_exact_family_equality(self):
        import inspect
        src = inspect.getsource(CandidateProducer._assert_tool_detected)
        assert 'if family == "fvg" and wanted:' in src
        assert 'e.get("occurrence_id") is not None' in src


class TestFvgStillFailsClosed:
    def test_a_row_without_identity_can_never_be_selected(self):
        """Even inside FVG, `None` is not a name."""
        with pytest.raises(NoCandidate) as e:
            resolve("bullish", "None")
        assert e.value.reason == "tool_occurrence_unknown"

    @pytest.mark.parametrize("junk", ["null", "NULL", "none", "", "   "])
    def test_null_shaped_strings_do_not_select(self, junk):
        """Blank falls through to family resolution; the rest refuse."""
        if junk.strip():
            with pytest.raises(NoCandidate) as e:
                resolve("bullish", junk)
            assert e.value.reason == "tool_occurrence_unknown"
        else:
            assert resolve("bullish", junk)["occurrence_id"] == BULL_ID

    def test_a_real_id_still_resolves(self):
        assert resolve("bullish", BULL_ID)["occurrence_id"] == BULL_ID

    def test_ambiguity_without_an_id_is_preserved(self):
        with pytest.raises(NoCandidate) as e:
            resolve("bearish", None)
        assert e.value.reason == "tool_occurrence_ambiguous"


class TestProvenanceSurvivesIntoTheCandidate:
    """END-TO-END through the real `CandidateProducer.produce`.

    The occurrence is an EXPOSURE-AUTHORIZING object, never a price authority:
    entry stays the fresh executable quote, the stop stays Luna's authored
    structural invalidation, the target stays the selected objective. What must
    survive is WHICH market object justified the exposure -- `tool_family:
    ["fvg"]` alone cannot answer that after the fact.
    """

    ID_X = "FVG:CON.F.US.MNQ.U26:5m:2026-08-05T15:25:00+00:00"
    ID_Y = "FVG:CON.F.US.MNQ.U26:1m:2026-08-05T15:28:00+00:00"

    @classmethod
    def two_eligible(cls):
        """One snapshot, two lawful bullish gaps — X first, Y second."""
        from _step7_fixture import detected
        s = copy.deepcopy(detected("fvg", direction="bullish"))
        first = s["toolbox"]["tool_instances"][0]
        assert first["occurrence_id"] == cls.ID_X, first["occurrence_id"]
        second = dict(first, occurrence_id=cls.ID_Y, source_tf="1m",
                      tool_id="bullish_fvg@1m#second",
                      zone_low=29870.0, zone_high=29874.0)
        s["toolbox"]["tool_instances"] = [first, second]
        return s

    @classmethod
    def build(cls, occurrence_id):
        import test_luna_candidate_producer as LCP
        return LCP.produce(
            res=LCP.result(parsed=LCP.parsed(
                recommended_tool_family=["fvg"],
                recommended_tool_occurrence_id=occurrence_id)),
            snapshot=cls.two_eligible())

    def test_the_fixture_really_holds_two_eligible_occurrences(self):
        s = self.two_eligible()
        elig = [r for r in authorized_tool_catalog(s)
                if r.get("tool") == "bullish_fvg" and r.get("execution_eligible")]
        assert {r["occurrence_id"] for r in elig} == {self.ID_X, self.ID_Y}

    def test_selecting_X_records_X(self):
        cand = self.build(self.ID_X)
        assert cand is not None
        assert cand.extras["selected_tool_occurrence_id"] == self.ID_X

    def test_selecting_Y_records_Y(self):
        cand = self.build(self.ID_Y)
        assert cand is not None
        assert cand.extras["selected_tool_occurrence_id"] == self.ID_Y

    def test_changing_ONLY_the_selection_changes_ONLY_the_provenance(self):
        """The load-bearing proof. Provenance follows the choice; price does not."""
        x, y = self.build(self.ID_X), self.build(self.ID_Y)
        assert x.extras["selected_tool_occurrence_id"] != \
            y.extras["selected_tool_occurrence_id"]
        # PRICE AUTHORITY IS UNMOVED — entry is the fresh quote, not a boundary
        assert x.entry_price == y.entry_price
        assert x.invalidation_price == y.invalidation_price
        assert x.objective.price == y.objective.price

    def test_the_entry_is_not_either_zone_boundary(self):
        cand = self.build(self.ID_Y)
        for boundary in (29860.0, 29866.0, 29870.0, 29874.0):
            assert cand.entry_price != boundary

    def test_the_recorded_id_comes_from_the_VERIFIED_match(self):
        """Not copied from the raw response — provenance means "what mechanics
        proved", not "what Luna sent"."""
        import inspect
        from broker import luna_candidate_producer as P
        src = inspect.getsource(P.CandidateProducer.produce)
        assert '"selected_tool_occurrence_id": (selected_tool or {}).get("occurrence_id")' in src
        assert '"selected_tool_occurrence_id": parsed' not in src

    def test_the_matched_tool_and_timeframe_travel_too(self):
        cand = self.build(self.ID_Y)
        assert cand.extras["selected_tool"] == "bullish_fvg"
        assert cand.extras["selected_tool_source_tf"] == "1m"

    def test_no_id_with_two_eligible_produces_no_candidate(self):
        with pytest.raises(NoCandidate) as e:
            self.build(None)
        assert e.value.reason == "tool_occurrence_ambiguous"

    def test_an_invalid_id_produces_no_candidate(self):
        with pytest.raises(NoCandidate) as e:
            self.build("FVG:CON.F.US.MNQ.U26:1m:1999-01-01T00:00:00+00:00")
        assert e.value.reason == "tool_occurrence_unknown"

    def test_a_single_eligible_occurrence_still_records_its_identity(self):
        """Unique resolution keeps provenance too — null id, verified match."""
        import test_luna_candidate_producer as LCP
        cand = LCP.produce(res=LCP.result(parsed=LCP.parsed(
            recommended_tool_family=["fvg"], recommended_tool_occurrence_id=None)))
        assert cand is not None
        assert cand.extras["selected_tool_occurrence_id"]


class TestNothingElseMoved:
    def test_the_ambiguity_guard_was_not_weakened(self):
        import inspect
        src = inspect.getsource(CandidateProducer._assert_tool_detected)
        assert 'if family == "fvg" and len(eligible) > 1:' in src
        assert "TOOL_OCCURRENCE_AMBIGUOUS" in src

    def test_eligibility_filtering_is_untouched(self):
        import inspect
        src = inspect.getsource(CandidateProducer._assert_tool_detected)
        assert 'eligible = [e for e in on_side if e["execution_eligible"]]' in src

    def test_direction_and_family_gates_still_precede_selection(self):
        import inspect
        src = inspect.getsource(CandidateProducer._assert_tool_detected)
        assert src.index("TOOL_DIRECTION_MISMATCH") < src.index("TOOL_OCCURRENCE_UNKNOWN")

    def test_invalidation_id_was_deliberately_NOT_repaired(self):
        """A separate, recorded defect. Repairing it here would expand scope."""
        import inspect
        from broker import luna_candidate_producer as P
        src = inspect.getsource(P.CandidateProducer._invalidation)
        assert 'parsed.get("invalidation_level")' in src
        assert "invalidation_id" not in src

    def test_objective_selection_is_untouched(self):
        import inspect
        from broker import luna_candidate_producer as P
        assert 'c.get("objective_id") == wanted' in inspect.getsource(P)

    def test_catalog_size_and_eligibility_are_untouched(self):
        assert len(catalog()) > 40          # Unit 2's expansion, unchanged
        assert len(eligible("bullish")) == 1

    def test_no_risk_doctrine_moved(self):
        from broker import topstepx_combine_risk as RK
        assert (RK.PREFERRED_MAX_STOP_POINTS, RK.ABSOLUTE_MAX_STOP_POINTS) == (35.0, 50.0)
        assert RK.PRODUCTION_MAX_RISK_USD == 350.00

    def test_po3_still_refuses_identically(self):
        from toolbox.price_levels import po3_reversal_order_block, NO_MANIPULATION
        assert po3_reversal_order_block(snap(), "bullish")["reason"] == NO_MANIPULATION
