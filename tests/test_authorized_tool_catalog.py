"""ROADMAP STEP 7 — Terra may not trade an expression the market never produced.

The 2026-08-12 production preflight proved `recommended_tool_family` was free
text. Against the REAL 15:08Z toolbox inventory, all four of these were ACCEPTED:

    ifvg             detected + eligible        correct
    order_block      never detected             DEFECT
    rejection_block  detected, ineligible       DEFECT
    unicorn_block    not even vocabulary        DEFECT

and each could then ride a separately-valid protected-swing invalidation to a
real TopstepX bracket. The producer already published `authorized_invalidation_catalog`
and `authorized_objective_catalog` and resolved both by ID; tools had no catalog.

THE LAW:

    Terra INTERPRETS and SELECTS.
    Deterministic mechanics establish what physically EXISTS.
    Mechanics may VETO. Mechanics may NEVER SUBSTITUTE.

A valid playbook, a valid invalidation and a valid objective are independent
propositions. None of them proves a valid tool.
"""
from __future__ import annotations

import inspect
import json
import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))

from broker.luna_candidate_producer import (                        # noqa: E402
    CandidateProducer, NoCandidate, authorized_tool_catalog, canonical_tool_family,
)
from data_feed import candle_continuity as CONT                     # noqa: E402
from data_feed.timeframe_builder import build_timeframes            # noqa: E402
import market_data.snapshot_builder as SB                           # noqa: E402
from _step7_fixture import detected as _detected                    # noqa: E402

FIXTURE = os.path.join(ROOT, "tests", "fixtures",
                       "mnq_20260811_1420Z_1510Z_1m.json")
GOLD_SCAN = "2026-08-11T15:08:00+00:00"


def gold_snapshot(end: str = GOLD_SCAN) -> dict:
    with open(FIXTURE, encoding="utf-8") as fh:
        tape = json.load(fh)["bars"]
    win = CONT.coherent_window([b for b in tape if b["timestamp"] <= end],
                               horizon_minutes=300, minimum_bars=1)["window"]
    return SB.build_snapshot(build_timeframes(win), symbol="MNQ")


def zone(eligible, direction="bullish", tf="5m", reason=None, **extra):
    pl = {"execution_eligible": eligible, "direction": direction,
          "source_tf": tf, "level_type": "zone",
          "temporal_class": "settled" if eligible else "provisional"}
    if reason:
        pl["execution_ineligible_reason"] = reason
    pl.update(extra)
    return pl


#: The REAL 15:08Z inventory from the preflight, held as a fixture so the cases
#: stay anchored to measured market evidence rather than to invention.
GOLD_INVENTORY = {"toolbox": {"tool_candidates": [
    {"tool": "bullish_ifvg", "price_level": zone(True)},
    {"tool": "bullish_ote_after_reclaim", "price_level": zone(True)},
    {"tool": "bullish_breaker", "price_level": zone(True)},
    {"tool": "bullish_rejection_block", "price_level": zone(
        False, tf="3m", reason="TOOL_NOT_SETTLED: zone geometry depends on a forming bucket")},
    {"tool": "bullish_mss_retest", "price_level": zone(False, tf="3m")},
]}}


#: STEP 4B.12 §7 UNIT 7 — the executable exemplar for THIS suite.
#:
#: The shared `_step7_fixture.EXECUTABLE_TOOL_EXEMPLAR` is plain FVG, but
#: `GOLD_INVENTORY` is a CAPTURED 15:08Z preflight record and contains no FVG
#: row. Adding one would invent market evidence into a real capture, which is
#: exactly what that fixture's own comment forbids. So the exemplar here is a
#: family the capture genuinely holds and which is eligible in it.
#:
#: Like the shared constant, it means only "an executable expression exists" --
#: these three cases are family-agnostic (detected+eligible passes, a single
#: family passes, an explicit direction match passes). IFVG was the exemplar
#: until Unit 7 quarantined it from execution authority.
EXECUTABLE_EXEMPLAR = "breaker"


def gate(tool, direction="bullish", snapshot=None, trace=None):
    return CandidateProducer._assert_tool_detected(
        [tool], direction, snapshot if snapshot is not None else GOLD_INVENTORY,
        trace if trace is not None else {})


# ── canonicalisation: exact, never fuzzy ─────────────────────────────────────

class TestCanonicalFamilyMatching:

    def test_the_directional_prefix_contract(self):
        assert canonical_tool_family("bullish_ifvg") == ("ifvg", "bullish")
        assert canonical_tool_family("bearish_ifvg") == ("ifvg", "bearish")
        assert canonical_tool_family("ifvg") == ("ifvg", None)

    def test_an_invented_token_canonicalises_to_itself_and_matches_nothing(self):
        assert canonical_tool_family("unicorn_block") == ("unicorn_block", None)
        assert not [e for e in authorized_tool_catalog(GOLD_INVENTORY)
                    if e["tool_family"] == "unicorn_block"]

    def test_matching_is_not_substring_or_fuzzy(self):
        """`order_block` must not match `bullish_opening_order_block`, and
        `block` must not match anything."""
        inv = {"toolbox": {"tool_candidates": [
            {"tool": "bullish_opening_order_block", "price_level": zone(True)}]}}
        with pytest.raises(NoCandidate):
            gate("order_block", snapshot=inv)
        with pytest.raises(NoCandidate):
            gate("block", snapshot=inv)
        # the exact family still resolves
        assert gate("opening_order_block", snapshot=inv)["tool_family"] == \
            "opening_order_block"

    def test_only_approved_families_enter_the_catalog(self):
        inv = {"toolbox": {"tool_candidates": [
            {"tool": "bullish_unicorn_block", "price_level": zone(True)}]}}
        assert authorized_tool_catalog(inv) == []


# ── the five gold cases ──────────────────────────────────────────────────────

class TestTheFivePreflightCases:

    def test_case1_detected_and_eligible_passes(self):
        trace = {}
        match = gate(EXECUTABLE_EXEMPLAR, trace=trace)
        assert match["tool"] == f"bullish_{EXECUTABLE_EXEMPLAR}"
        assert trace["tool_detected"] is True
        assert trace["tool_execution_eligible"] is True
        assert trace["tool_rejection_reason"] is None

    def test_case2_valid_family_not_detected_refuses(self):
        trace = {}
        with pytest.raises(NoCandidate) as exc:
            gate("order_block", trace=trace)
        assert "TOOL_NOT_DETECTED" in str(exc.value)
        assert trace["tool_detected"] is False
        assert trace["tool_rejection_reason"] == "TOOL_NOT_DETECTED"

    def test_case3_detected_but_provisional_refuses(self):
        trace = {}
        with pytest.raises(NoCandidate) as exc:
            gate("rejection_block", trace=trace)
        assert "TOOL_NOT_EXECUTION_ELIGIBLE" in str(exc.value)
        assert "forming bucket" in str(exc.value)
        assert trace["tool_detected"] is True
        assert trace["tool_execution_eligible"] is False
        assert trace["tool_rejection_reason"] == "TOOL_NOT_EXECUTION_ELIGIBLE"

    def test_case4_invented_token_refuses(self):
        trace = {}
        with pytest.raises(NoCandidate) as exc:
            gate("unicorn_block", trace=trace)
        assert "TOOL_NOT_DETECTED" in str(exc.value)
        assert trace["tool_detected"] is False

    def test_case5_wrong_direction_refuses(self):
        """A bullish expression is not existence proof for a bearish trade."""
        trace = {}
        with pytest.raises(NoCandidate) as exc:
            gate("ifvg", direction="bearish", trace=trace)
        assert "TOOL_DIRECTION_MISMATCH" in str(exc.value)
        assert trace["tool_detected"] is True
        assert trace["tool_rejection_reason"] == "TOOL_DIRECTION_MISMATCH"

    def test_the_three_refusals_are_semantically_distinct(self):
        reasons = set()
        for tool, d in (("order_block", "bullish"), ("rejection_block", "bullish"),
                        ("ifvg", "bearish")):
            trace = {}
            with pytest.raises(NoCandidate):
                gate(tool, direction=d, trace=trace)
            reasons.add(trace["tool_rejection_reason"])
        assert reasons == {"TOOL_NOT_DETECTED", "TOOL_NOT_EXECUTION_ELIGIBLE",
                           "TOOL_DIRECTION_MISMATCH"}


# ── §0A — exactly one selected family, never a menu ──────────────────────────

class TestExactlyOneToolFamily:
    """`brain_prompt`: "recommended_tool_family MUST be a JSON ARRAY containing
    exactly ONE tool family token ... Exactly one token, but always inside an
    array." The list is a schema SHAPE, not a set of alternatives.

    The first Step 7 gate looped the list and returned the first eligible
    member, which would have executed the IFVG after the rejection block was
    refused -- substitution inside Terra's own selection. Nothing upstream
    enforces the arity, so the gate does.
    """

    def test_the_prompt_contract_is_exactly_one(self):
        from ai_brain import brain_prompt
        text = " ".join(brain_prompt.BRAIN_SYSTEM_PROMPT.split())
        assert "containing exactly ONE tool family token" in text
        assert "Exactly one token, but always inside an array" in text

    def test_m1_a_single_detected_family_passes(self):
        assert gate(EXECUTABLE_EXEMPLAR)["tool"] == f"bullish_{EXECUTABLE_EXEMPLAR}"

    @pytest.mark.parametrize("first", ["rejection_block", "order_block"])
    def test_m2_m3_a_second_family_is_never_reached(self, first):
        """Provisional-then-eligible and absent-then-eligible must BOTH refuse.
        Mechanics do not pick the survivor."""
        trace = {}
        with pytest.raises(NoCandidate) as exc:
            CandidateProducer._assert_tool_detected([first, "ifvg"], "bullish",
                                                    GOLD_INVENTORY, trace)
        assert exc.value.reason == "tool_selection_ambiguous"
        assert trace["tool_rejection_reason"] == "TOOL_SELECTION_AMBIGUOUS"

    def test_m4_an_invented_token_beside_a_real_one_still_refuses(self):
        """`unicorn_block` is not a concrete family, so the arity check does not
        fire -- but the invented token is also not detected, and the real one
        behind it must not rescue the selection."""
        trace = {}
        with pytest.raises(NoCandidate) as exc:
            CandidateProducer._assert_tool_detected(["unicorn_block"], "bullish",
                                                    GOLD_INVENTORY, trace)
        assert exc.value.reason == "tool_not_detected"

    @pytest.mark.parametrize("tokens", [
        ["ifvg", "breaker"],            # two executable families
        ["ifvg", "wait"],               # executable + neutral
        ["wait", "ifvg"],               # order must not matter
        ["ifvg", "unicorn_block"],      # executable + unknown
        ["unicorn_block", "ifvg"],      # unknown + executable
        [],                             # nothing selected
        ["ifvg", "ifvg"],               # duplicated
        # STEP-7.3 — a BLANK member is still a member. These collapsed to one
        # under the previous implementation, which filtered `if str(t).strip()`
        # BEFORE counting, and therefore authorised a two-element response.
        ["ifvg", ""],
        ["", "ifvg"],
        ["ifvg", "   "],
        ["   ", "ifvg"],
        ["ifvg", None],
        [None, "ifvg"],
    ])
    def test_anything_other_than_one_token_refuses(self, tokens):
        """CORRECTED. This test previously asserted
        `["ifvg", "wait"] -> PASS ("neutral tokens don't count")`, which ENCODED
        the defect: mechanics were discarding the token they did not like and
        converting a malformed answer into an executable one. That is AI-output
        REPAIR, and the contract quoted above says exactly ONE token.

        The count is on what Terra actually sent, before any recognition or
        filtering. Mechanics may reject Terra's answer; they may not sanitise it
        into a different valid answer.
        """
        trace = {}
        with pytest.raises(NoCandidate) as exc:
            CandidateProducer._assert_tool_detected(tokens, "bullish",
                                                    GOLD_INVENTORY, trace)
        assert exc.value.reason == "tool_selection_ambiguous", tokens
        assert trace["tool_rejection_reason"] == "TOOL_SELECTION_AMBIGUOUS"

    def test_the_arity_is_checked_before_recognition(self):
        """A mixed selection must die on CARDINALITY, not be rescued or
        re-explained by whichever token happened to be detectable."""
        trace = {}
        with pytest.raises(NoCandidate) as exc:
            CandidateProducer._assert_tool_detected(["ifvg", "wait"], "bullish",
                                                    GOLD_INVENTORY, trace)
        # not TOOL_NOT_DETECTED for `wait`, not a pass for `ifvg`
        assert exc.value.reason == "tool_selection_ambiguous"
        assert trace["tool_selected"] == ["ifvg", "wait"], \
            "the trace must record what Terra actually sent, unfiltered"

    def test_a_sole_neutral_token_can_never_authorize_an_entry(self):
        """A neutral token is legitimate ONLY as the sole selection on a
        non-entry action; it may never ride alongside an executable family (the
        arity rule above) and it may never itself authorize an entry.

        MEASURED, because the two gates split the vocabulary and I had this
        wrong at first: `_playbook`'s neutral set is
        {"", none, unknown, confirmation_required, n/a, wait} -- it does NOT
        contain `two_sided_watch`, which therefore passes `_playbook` and is
        refused one gate later as not detected. Both paths refuse; the point is
        that neither authorizes.
        """
        qual = {"qualified": True, "direction": "bullish",
                "authorized_playbooks": ["continuation"]}
        expected = {"none": "tool_family_unauthorized",
                    "wait": "tool_family_unauthorized",
                    "confirmation_required": "tool_family_unauthorized",
                    "n/a": "tool_family_unauthorized",
                    "unknown": "tool_family_unauthorized",
                    "two_sided_watch": "tool_not_detected"}
        for token, reason in expected.items():
            with pytest.raises(NoCandidate) as exc:
                pb, tools = CandidateProducer._playbook(
                    {"recommended_playbook_family": "continuation",
                     "recommended_tool_family": [token]}, qual)
                CandidateProducer._assert_tool_detected(tools, "bullish",
                                                        GOLD_INVENTORY, {})
            assert exc.value.reason == reason, (token, exc.value.reason)

    @pytest.mark.parametrize("token", ["", "   ", None])
    def test_a_sole_blank_token_dies_on_its_own_semantics_not_arity(self, token):
        """One element is one element. A blank sole selection passes the
        cardinality rule and is then refused for what it actually is -- not
        detected -- rather than being deleted on the way in."""
        trace = {}
        with pytest.raises(NoCandidate) as exc:
            CandidateProducer._assert_tool_detected([token], "bullish",
                                                    GOLD_INVENTORY, trace)
        assert exc.value.reason == "tool_not_detected"
        assert trace["tool_rejection_reason"] == "TOOL_NOT_DETECTED"

    def test_the_trace_records_the_submitted_array_untouched(self):
        """Forensics must show what Terra actually sent, including the blank."""
        trace = {}
        with pytest.raises(NoCandidate):
            CandidateProducer._assert_tool_detected(["ifvg", ""], "bullish",
                                                    GOLD_INVENTORY, trace)
        assert trace["tool_selected"] == ["ifvg", ""]

    def test_a_single_unknown_token_dies_on_detection_not_arity(self):
        trace = {}
        with pytest.raises(NoCandidate) as exc:
            CandidateProducer._assert_tool_detected(["unicorn_block"], "bullish",
                                                    GOLD_INVENTORY, trace)
        assert exc.value.reason == "tool_not_detected"


# ── §0B — missing direction is not universal compatibility ───────────────────

class TestDirectionMustBeExplicit:

    def test_production_always_supplies_a_direction(self):
        """Structural today: the toolbox names instances `bullish_`/`bearish_`
        and both `_make_zone` and `_no_zone` set `direction`."""
        for entry in authorized_tool_catalog(gold_snapshot()):
            assert entry["direction"] in ("bullish", "bearish"), entry

    @pytest.mark.parametrize("bad", [None, "", "   ", "garbage", 0])
    def test_a_missing_or_invalid_direction_fails_closed(self, bad):
        """Absence of directional evidence is not evidence of compatibility.
        Such an entry must satisfy NEITHER side."""
        inv = {"toolbox": {"tool_candidates": [
            {"tool": "ifvg",            # deliberately un-prefixed
             "price_level": {"execution_eligible": True, "direction": bad,
                             "source_tf": "5m"}}]}}
        for want in ("bullish", "bearish"):
            with pytest.raises(NoCandidate):
                gate("ifvg", direction=want, snapshot=inv)

    def test_an_explicit_match_still_passes(self):
        inv = {"toolbox": {"tool_candidates": [
            {"tool": f"bearish_{EXECUTABLE_EXEMPLAR}",
             "price_level": zone(True, direction="bearish")}]}}
        assert gate(EXECUTABLE_EXEMPLAR, direction="bearish",
                    snapshot=inv)["direction"] == "bearish"


# ── no substitution, absolute ────────────────────────────────────────────────

class TestNoSubstitution:

    def test_an_ineligible_selection_is_not_swapped_for_an_eligible_one(self):
        """`bullish_ifvg`, `bullish_breaker` and `bullish_ote_after_reclaim` are
        all detected AND eligible in this inventory. Selecting the ineligible
        `rejection_block` must still refuse."""
        with pytest.raises(NoCandidate) as exc:
            gate("rejection_block")
        assert "rejection_block" in str(exc.value)
        assert "ifvg" not in str(exc.value).split("detected")[0]

    def test_an_absent_selection_is_not_swapped_for_preferred_tool(self):
        inv = {"toolbox": {"preferred_tool": "bullish_ifvg",
                           "tool_candidates": GOLD_INVENTORY["toolbox"]["tool_candidates"]}}
        with pytest.raises(NoCandidate):
            gate("order_block", snapshot=inv)

    def test_the_same_family_on_the_wrong_side_is_not_accepted(self):
        with pytest.raises(NoCandidate):
            gate("ifvg", direction="bearish")

    def test_a_refusal_returns_nothing_at_all(self):
        for tool, d in (("order_block", "bullish"), ("rejection_block", "bullish"),
                        ("ifvg", "bearish"), ("unicorn_block", "bullish")):
            with pytest.raises(NoCandidate):
                gate(tool, direction=d)


# ── fail closed ──────────────────────────────────────────────────────────────

class TestFailsClosed:

    @pytest.mark.parametrize("snapshot", [
        {},                                              # no snapshot content
        {"toolbox": {}},                                 # no inventory
        {"toolbox": {"tool_candidates": []}},            # empty inventory
        {"toolbox": {"tool_candidates": [{"price_level": {}}]}},   # no tool name
        {"toolbox": {"tool_candidates": [{"tool": "bullish_ifvg"}]}},  # no zone
    ])
    def test_absent_or_malformed_inventory_is_never_permission(self, snapshot):
        with pytest.raises(NoCandidate):
            gate("ifvg", snapshot=snapshot)

    @pytest.mark.parametrize("eligible", [None, "true", 1, "yes", 0, False])
    def test_only_an_explicit_true_is_execution_authority(self, eligible):
        inv = {"toolbox": {"tool_candidates": [
            {"tool": "bullish_ifvg",
             "price_level": {"execution_eligible": eligible,
                             "direction": "bullish", "source_tf": "5m"}}]}}
        entry = authorized_tool_catalog(inv)[0]
        assert entry["execution_eligible"] is (eligible is True)
        if eligible is not True:
            with pytest.raises(NoCandidate):
                gate("ifvg", snapshot=inv)

    def test_missing_eligibility_key_is_not_treated_as_true(self):
        inv = {"toolbox": {"tool_candidates": [
            {"tool": "bullish_ifvg",
             "price_level": {"direction": "bullish", "source_tf": "5m"}}]}}
        assert authorized_tool_catalog(inv)[0]["execution_eligible"] is False
        with pytest.raises(NoCandidate):
            gate("ifvg", snapshot=inv)

    def test_no_tool_selected_at_all_refuses(self):
        with pytest.raises(NoCandidate):
            CandidateProducer._assert_tool_detected([], "bullish", GOLD_INVENTORY, {})

    def test_an_empty_catalog_is_a_legitimate_result_never_manufactured(self):
        assert authorized_tool_catalog({"toolbox": {"tool_candidates": []}}) == []


# ── the catalog contract ─────────────────────────────────────────────────────

class TestCatalogContract:

    def test_provisional_entries_stay_visible_for_cognition(self):
        """CONTINUITY-2F witness/authority split: the Brain must still SEE a
        forming opportunity it may describe but not trade.

        STEP 4B.12 §7 UNIT 7 — filtered on the TEMPORAL class, which is this
        test's actual subject. It previously filtered on `not
        execution_eligible`, which was equivalent only while 2F was the sole
        author of that field. IFVG is now withheld for an ONTOLOGY reason while
        remaining `temporal_class: settled`, so composite ineligibility no
        longer means provisional. Same consequence, different cause -- and
        folding a settled quarantined row into a "provisional" set would assert
        a temporal defect that does not exist.
        """
        catalog = authorized_tool_catalog(GOLD_INVENTORY)
        provisional = [e for e in catalog if e["temporal_class"] == "provisional"]
        assert {e["tool_family"] for e in provisional} == \
            {"rejection_block", "mss_retest"}
        assert all(not e["execution_eligible"] for e in provisional)
        assert all(not e.get("execution_quarantined") for e in provisional), \
            "a temporal defect is not an ontology quarantine"

    def test_a_quarantined_entry_also_stays_visible_for_cognition(self):
        """The same witness/authority split, for a different authority. IFVG is
        visible and describable; it simply may not author a trade."""
        catalog = authorized_tool_catalog(GOLD_INVENTORY)
        ifvg = [e for e in catalog if e["tool_family"] == "ifvg"]
        assert ifvg, "quarantine is not deletion"
        e = ifvg[0]
        assert e["execution_eligible"] is False
        assert e["execution_quarantined"] is True
        assert e["execution_quarantine_reason"] == \
            "ifvg_occurrence_semantics_uncertified"
        assert e["temporal_class"] == "settled", \
            "withheld for ontology, NOT because its geometry is forming"
        assert e["execution_ineligible_reason"] is None, \
            "no temporal defect was invented to justify the quarantine"

    def test_it_is_built_only_from_the_existing_toolbox_output(self):
        src = inspect.getsource(authorized_tool_catalog)
        assert 'get("toolbox")' in src
        for forbidden in ("find_fvgs", "build_price_level", "detect_", "analyze_"):
            assert forbidden not in src, \
                f"2F/Step 7 must not re-detect setups ({forbidden})"

    def test_it_carries_the_facts_needed_to_validate_a_selection(self):
        entry = authorized_tool_catalog(GOLD_INVENTORY)[0]
        for key in ("tool", "tool_family", "direction", "source_tf",
                    "execution_eligible", "temporal_class"):
            assert key in entry, key

    def test_the_real_gold_snapshot_produces_the_measured_inventory(self):
        catalog = authorized_tool_catalog(gold_snapshot())
        by_family = {e["tool_family"]: e["execution_eligible"] for e in catalog}
        # STEP 4B.12 §7 UNIT 7 — the CAPTURED EVIDENCE is unchanged; the current
        # AUTHORITY projection of it is not. IFVG is still detected and still
        # published from this same snapshot, and is now withheld from execution
        # because its occurrence ontology is uncertified. Same evidence,
        # different certified authority.
        assert by_family.get("ifvg") is False
        _ifvg = next(e for e in catalog if e["tool_family"] == "ifvg")
        assert _ifvg["execution_quarantined"] is True
        assert _ifvg["execution_quarantine_reason"] ==             "ifvg_occurrence_semantics_uncertified"
        assert by_family.get("rejection_block") is False
        # DIRECTIONAL TRUTH (2026-08-12). `mss_retest` used to reach the catalog
        # and be rejected on eligibility. It no longer reaches it at all: `mss`
        # is a bare boolean with no `mss_direction`, so the family cannot prove
        # WHICH side it is, and a tool that cannot prove its direction is not
        # offered in either. Absent, not ineligible -- those are different
        # claims and the catalog should only ever make the one it can support.
        assert "mss_retest" not in by_family


# ── wiring: the gate is in PRODUCTION, and the Brain sees the catalog ────────

class TestProductionWiring:

    def test_the_gate_runs_inside_the_real_produce(self):
        """BEHAVIOURAL, end-to-end through `CandidateProducer.produce`.

        The source-string version of this test ESCAPED its own mutation:
        replacing the call with `pass  # self._assert_tool_detected(...)` left
        the asserted string intact inside the comment. A deleted OR defeated
        gate cannot survive driving the real producer.
        """
        import test_luna_candidate_producer as LCP

        # everything else about this thesis is valid -- only the tool differs
        detected_ok = LCP.produce(
            res=LCP.result(parsed=LCP.parsed(recommended_tool_family=["fvg"])),
            snapshot=_detected("fvg"))
        assert detected_ok is not None, "a detected, eligible tool must pass"

        for tool, expect in (("order_block", "tool_not_detected"),
                             ("unicorn_block", "tool_not_detected")):
            with pytest.raises(NoCandidate) as exc:
                LCP.produce(
                    res=LCP.result(parsed=LCP.parsed(recommended_tool_family=[tool])),
                    snapshot=_detected("fvg"))
            assert exc.value.reason == expect, (tool, exc.value.reason)

        with pytest.raises(NoCandidate) as exc:
            LCP.produce(
                res=LCP.result(parsed=LCP.parsed(recommended_tool_family=["fvg"])),
                snapshot=_detected("fvg", eligible=False))
        assert exc.value.reason == "tool_not_execution_eligible"

    def test_the_gate_follows_playbook_authorisation(self):
        src = inspect.getsource(CandidateProducer.produce)
        assert src.index("_playbook(parsed, qualification, trace)") < \
            src.index("_assert_tool_detected")

    def test_the_brain_payload_publishes_the_catalog(self):
        from ai_brain.brain_input import build_brain_input
        payload = build_brain_input(gold_snapshot(), {})
        catalog = payload["authorized_tool_catalog"]
        assert catalog, "Terra cannot select from facts it was never shown"
        assert {e["tool_family"] for e in catalog} >= {"ifvg", "rejection_block"}

    def test_the_brain_and_the_gate_read_the_same_catalog(self):
        """One definition, so what Terra is shown and what mechanics accept
        cannot drift apart."""
        from ai_brain.brain_input import build_brain_input
        snap = gold_snapshot()
        assert build_brain_input(snap, {})["authorized_tool_catalog"] == \
            authorized_tool_catalog(snap)

    def test_the_payload_survives_a_snapshot_without_a_toolbox(self):
        from ai_brain.brain_input import build_brain_input
        assert build_brain_input({"timestamp": "t"}, {})["authorized_tool_catalog"] == []


# ── the constitutional regression ────────────────────────────────────────────

class TestTheHallucinationCase:
    """Everything else about the thesis is valid. ONLY the tool is fictitious.
    This proves the new gate rather than accidentally relying on another
    rejection somewhere downstream."""

    def test_only_the_tool_gate_declines_it(self):
        trace = {}
        qual = {"qualified": True, "direction": "bullish",
                "authorized_playbooks": ["continuation"]}
        parsed = {"recommended_playbook_family": "continuation",
                  "recommended_tool_family": ["unicorn_block"]}
        # every earlier gate passes
        CandidateProducer._assert_action_permits_entry({"current_action": "enter"})
        assert CandidateProducer._direction(parsed | {"narrative_direction": "bullish"},
                                            qual) == "bullish"
        playbook, tools = CandidateProducer._playbook(parsed, qual)
        assert playbook == "continuation" and tools == ["unicorn_block"]
        # and the tool gate is the one that stops it
        with pytest.raises(NoCandidate) as exc:
            CandidateProducer._assert_tool_detected(tools, "bullish",
                                                    GOLD_INVENTORY, trace)
        assert "TOOL_NOT_DETECTED" in str(exc.value)
        assert trace["tool_rejection_reason"] == "TOOL_NOT_DETECTED"


# ── production invariance and source closure ─────────────────────────────────

class TestInvarianceAndClosure:

    def test_the_invalidation_catalog_is_untouched(self):
        from broker import luna_candidate_producer as LP
        src = inspect.getsource(LP.authorized_invalidation_catalog)
        assert "protected_swings" in src
        assert "toolbox" not in src and "price_level" not in src

    def test_risk_doctrine_is_untouched(self):
        from broker import topstepx_combine_risk as R
        assert (R.PRODUCTION_MAX_RISK_USD, R.PRODUCTION_MAX_CONTRACTS) == (350.0, 15)
        assert (R.PREFERRED_MAX_STOP_POINTS, R.ABSOLUTE_MAX_STOP_POINTS) == (35.0, 50.0)

    def test_toolbox_scoring_was_not_altered(self):
        """BEHAVIOURAL as well as structural. The structural half alone ESCAPED
        a mutation that rewrote `_score_fvg`; Step 7 must not disturb what the
        toolbox detects or how it ranks, only whether the SELECTION is honoured."""
        from toolbox import toolbox_engine as TB
        assert "authorized_tool_catalog" not in inspect.getsource(TB)
        tb = gold_snapshot()["toolbox"]
        assert tb["preferred_tool"] == "bullish_ifvg"
        scores = {c["tool"]: c["score"] for c in tb["tool_candidates"]}
        assert scores["bullish_ifvg"] == 87
        # STEP 4B.12 §4 UNIT 2 — LEGITIMATE DOWNSTREAM DELTA, 77 -> 62.
        #
        # `gold_snapshot()` builds a REAL production snapshot, so transition
        # evidence is supplied and this is a genuine input change, not a fixture
        # defect. On this tape no timeframe carries a FRESH break, so the
        # breaker's structure term stops firing:
        #
        #     toolbox_engine   `if st.get("bos"): pts += 15`
        #     77 - 15 = 62     every other contribution unchanged
        #
        # Toolbox scoring logic itself is untouched -- the assertion above still
        # pins that. Only the structural INPUT changed, and it changed because
        # a persistent already-beyond position is no longer published as an event.
        assert scores["bullish_breaker"] == 62
        assert len(set(scores.values())) > 1, "scores collapsed to one value"

    def test_source_closure_covers_the_new_decision_bearing_files(self):
        """Step 7 made the toolbox decide whether a candidate may exist, so a
        detector threshold change must invalidate an authorization."""
        from ai_brain.production_model import _CONTRACT_SOURCES
        paths = {p for _, p in _CONTRACT_SOURCES}
        assert "broker/luna_candidate_producer.py" in paths
        assert "ai_brain/brain_input.py" in paths
        assert "toolbox/price_levels.py" in paths
        assert "toolbox/toolbox_engine.py" in paths

    def test_the_fingerprint_actually_moved(self):
        from ai_brain.production_model import brain_contract_fingerprint
        fp = brain_contract_fingerprint()
        assert isinstance(fp, str) and len(fp) >= 8
