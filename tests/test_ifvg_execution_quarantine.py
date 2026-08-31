"""STEP 4B.12 §7 UNIT 7 — IFVG IS OBSERVABLE, NOT EXECUTABLE.

The object production publishes as `ifvg` cannot prove it is an inverse fair
value gap. Measured on the 2026-08-12 venue tape, 250 scans:

    IFVG execution-eligible catalog entries        231
    scans affected                                 197 / 250
    scan x direction opportunities affected        231 / 500

    IFVG deliveries whose geometry matched a plain-FVG occurrence   215 / 215
    of those source gaps:
        NEVER closed through their far boundary                     202  (94%)
        retired, i.e. could plausibly have inverted                  13

Its existence and side come from the liquidity-sweep machinery
(`_anchor_tfs` -> `sweep_direction`); its geometry is whatever `_find_fvg`
returns as the newest ordinary gap of the requested direction. Nothing links
those two facts:

    source plain-FVG occurrence relation    UNPROVABLE
    inversion event theorem                 ABSENT
    canonical IFVG identity                 ABSENT
    IFVG lifecycle                          ABSENT
    occurrence-bound readiness              ABSENT

The repair is NOT to invent an inverse-FVG ontology before a release. It is to
stop an object that cannot say what it is from authorising a trade, while
leaving every trace of it visible. Re-enabling it later must be a deliberate
act against a named condition -- IFVG-ONTOLOGY-1.
"""
import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))

from broker.luna_candidate_producer import (  # noqa: E402
    IFVG_QUARANTINE_REASON, CandidateProducer, NoCandidate,
    authorized_tool_catalog)


def candidate(tool, *, eligible=True, tf="5m"):
    side = "bullish" if tool.startswith("bullish") else "bearish"
    return {"tool": tool, "effective_status": "ready",
            "price_level": {"level_type": f"{tool.split('_', 1)[1]}_zone",
                            "direction": side, "source_tf": tf,
                            "execution_eligible": eligible,
                            "temporal_class": "settled" if eligible else "provisional"}}


def snap(*tools, preferred=None):
    cands = [candidate(t) for t in tools]
    return {"toolbox": {"preferred_tool": preferred or (tools[0] if tools else None),
                        "tool_candidates": cands, "tool_instances": []}}


def resolve(snapshot, family, want="bullish"):
    producer = CandidateProducer.__new__(CandidateProducer)
    return producer._assert_tool_detected([family], want, snapshot, None)


# ── CASE 1 · observable, not executable ──────────────────────────────────────
class TestIfvgRemainsObservable:

    def test_the_ifvg_row_is_still_published(self):
        cat = authorized_tool_catalog(snap("bullish_ifvg"))
        assert [e["tool_family"] for e in cat] == ["ifvg"], \
            "quarantine is not deletion -- the evidence scar stays"
        assert cat[0]["direction"] == "bullish"
        assert cat[0]["source_tf"] == "5m"
        assert cat[0]["level_type"] == "ifvg_zone"

    def test_it_carries_execution_eligible_false_with_a_named_reason(self):
        """The quarantine lives in its OWN witness fields. It is an additional
        veto, not a replacement for `execution_ineligible_reason`."""
        e = authorized_tool_catalog(snap("bullish_ifvg"))[0]
        assert e["execution_eligible"] is False
        assert e["execution_quarantined"] is True
        assert e["execution_quarantine_reason"] == IFVG_QUARANTINE_REASON
        assert IFVG_QUARANTINE_REASON == "ifvg_occurrence_semantics_uncertified"

    def test_an_otherwise_eligible_ifvg_is_still_refused(self):
        """The upstream toolbox said execution_eligible=True. The quarantine is
        what denies it -- not a pre-existing 2F or geometry veto."""
        cat = authorized_tool_catalog(snap("bullish_ifvg"))
        assert cat[0]["execution_eligible"] is False
        assert cat[0]["execution_quarantined"] is True
        assert cat[0]["execution_ineligible_reason"] is None, \
            "nothing was wrong with it BEFORE the quarantine, and the row says so"


# ── ONE EVIDENCE DEFECT MUST NEVER ERASE ANOTHER ─────────────────────────────
class TestQuarantineDoesNotLaunderEvidence:
    """Of 260 IFVG catalog rows on the venue tape, 231 were executable and 29
    were ALREADY ineligible for an independent reason. Writing the quarantine
    into `execution_ineligible_reason` destroyed those 29 originals -- and the
    loss was self-demonstrating: the first attempt to measure "how many were
    executable before" could no longer tell a quarantined row from a
    previously-broken one, and reported 260 where the truth was 231.
    """

    def _already_broken(self):
        s = snap("bullish_ifvg")
        pl = s["toolbox"]["tool_candidates"][0]["price_level"]
        pl["execution_eligible"] = False
        pl["execution_ineligible_reason"] = (
            "TOOL_NOT_SETTLED: zone geometry depends on a forming bucket")
        pl["temporal_class"] = "provisional"
        return s

    def test_a_prior_defect_survives_the_quarantine(self):
        e = authorized_tool_catalog(self._already_broken())[0]
        assert e["execution_ineligible_reason"] == \
            "TOOL_NOT_SETTLED: zone geometry depends on a forming bucket"

    def test_the_quarantine_survives_beside_it(self):
        e = authorized_tool_catalog(self._already_broken())[0]
        assert e["execution_quarantined"] is True
        assert e["execution_quarantine_reason"] == IFVG_QUARANTINE_REASON

    def test_both_witnesses_are_independently_recoverable(self):
        e = authorized_tool_catalog(self._already_broken())[0]
        assert e["execution_eligible"] is False
        assert e["execution_ineligible_reason"] != e["execution_quarantine_reason"]
        assert e["execution_ineligible_reason"] is not None
        assert e["execution_quarantine_reason"] is not None

    def test_the_refusal_names_BOTH_authorities(self):
        """An operator reading only 'provisional geometry' would never learn the
        family is withheld outright."""
        with pytest.raises(NoCandidate) as exc:
            resolve(self._already_broken(), "ifvg")
        msg = str(exc.value)
        assert IFVG_QUARANTINE_REASON in msg
        assert "TOOL_NOT_SETTLED" in msg

    def test_quarantine_is_not_conditional_on_prior_eligibility(self):
        """All IFVG rows are quarantined -- the veto does not stand down just
        because another one already fired."""
        for s in (snap("bullish_ifvg"), self._already_broken()):
            assert authorized_tool_catalog(s)[0]["execution_quarantined"] is True

    def test_a_non_ifvg_row_carries_no_quarantine_witness(self):
        e = authorized_tool_catalog(snap("bullish_breaker"))[0]
        assert e["execution_quarantined"] is False
        assert e["execution_quarantine_reason"] is None


# ── CASE 2 · Terra selecting IFVG refuses ────────────────────────────────────
class TestTerraRequestingIfvgRefuses:

    def test_a_bare_ifvg_request_refuses(self):
        with pytest.raises(NoCandidate) as e:
            resolve(snap("bullish_ifvg"), "ifvg")
        assert e.value.reason == "tool_not_execution_eligible"
        assert IFVG_QUARANTINE_REASON in str(e.value)

    def test_the_refusal_names_the_quarantine_not_a_geometry_excuse(self):
        with pytest.raises(NoCandidate) as e:
            resolve(snap("bearish_ifvg"), "ifvg", want="bearish")
        assert "geometry is not settled" not in str(e.value)


# ── CASE 3 · NO CROSS-FAMILY SUBSTITUTION — the release theorem ──────────────
class TestNoSubstitution:

    def test_other_lawful_families_do_not_rescue_an_ifvg_request(self):
        s = snap("bullish_ifvg", "bullish_ote_after_reclaim",
                 "bullish_order_block", "bullish_breaker")
        with pytest.raises(NoCandidate) as e:
            resolve(s, "ifvg")
        assert e.value.reason == "tool_not_execution_eligible"

    def test_those_other_families_remain_independently_executable(self):
        """Quarantine removes IFVG's authority. It must not remove, or grant,
        anyone else's."""
        s = snap("bullish_ifvg", "bullish_ote_after_reclaim")
        cat = authorized_tool_catalog(s)
        by_fam = {e["tool_family"]: e["execution_eligible"] for e in cat}
        assert by_fam["ifvg"] is False
        assert by_fam["ote_after_reclaim"] is True
        match = resolve(s, "ote_after_reclaim")
        assert match["tool_family"] == "ote_after_reclaim"

    def test_quarantine_grants_no_family_extra_authority(self):
        """Eligibility counts for other families are identical whether or not
        an IFVG row is present."""
        with_ifvg = authorized_tool_catalog(
            snap("bullish_ifvg", "bullish_ote_after_reclaim", "bullish_breaker"))
        without = authorized_tool_catalog(
            snap("bullish_ote_after_reclaim", "bullish_breaker"))
        a = sorted(e["tool"] for e in with_ifvg if e["execution_eligible"])
        b = sorted(e["tool"] for e in without if e["execution_eligible"])
        assert a == b


# ── CASE 4 · preferred_tool is testimony, not authority ──────────────────────
class TestPreferredToolIsTestimony:

    def test_preferred_tool_may_still_name_a_quarantined_ifvg(self):
        """Deliberately NOT suppressed. `preferred_tool` carries no production
        execution authority: the production lane imports neither
        `decision_engine` nor `execution_gate`, it is not serialized into
        brain_input, and this resolver refuses to repair anything with it."""
        s = snap("bullish_ifvg", "bullish_breaker", preferred="bullish_ifvg")
        assert s["toolbox"]["preferred_tool"] == "bullish_ifvg"
        with pytest.raises(NoCandidate):
            resolve(s, "ifvg")

    def test_preferred_tool_cannot_repair_a_refusal(self):
        s = snap("bullish_ifvg", "bullish_breaker", preferred="bullish_breaker")
        with pytest.raises(NoCandidate) as e:
            resolve(s, "ifvg")
        assert e.value.reason == "tool_not_execution_eligible"
        assert "breaker" not in str(e.value)


# ── CASE 5 · plain FVG is untouched ──────────────────────────────────────────
class TestPlainFvgUnchanged:

    def test_exact_family_equality_never_matches_plain_fvg(self):
        from broker.luna_candidate_producer import _family_of
        assert _family_of("bullish_fvg") == "fvg"
        assert _family_of("bullish_ifvg") == "ifvg"
        assert _family_of("bullish_opening_fvg") == "opening_fvg"

    def test_a_unit6_occurrence_exact_fvg_stays_executable(self):
        occ = {"tool": "bullish_fvg", "family": "fvg", "direction": "bullish",
               "source_tf": "5m", "occurrence_id": "FVG:CON.F.US.MNQ.U26:5m:X",
               "zone_low": 100.0, "zone_high": 103.0, "identity_evaluable": True,
               "temporal_class": "settled", "temporal_execution_eligible": True,
               "execution_eligible": True, "execution_ineligible_reason": None}
        s = {"toolbox": {"preferred_tool": "bullish_fvg",
                         "tool_instances": [occ], "tool_candidates": []}}
        cat = authorized_tool_catalog(s)
        assert [e["tool_family"] for e in cat] == ["fvg"]
        assert cat[0]["execution_eligible"] is True
        assert cat[0]["occurrence_id"] == occ["occurrence_id"]
        assert resolve(s, "fvg")["occurrence_id"] == occ["occurrence_id"]


# ── CASE 6 · opening_fvg stays dark and untouched ────────────────────────────
class TestOpeningFvgUnchanged:

    def test_opening_fvg_is_still_direction_blind(self):
        from toolbox import toolbox_engine as TE
        assert "opening_fvg" in TE._DIRECTION_BLIND_FAMILIES
        assert TE._anchor_tfs("opening_fvg", "bullish", {}) == []

    def test_quarantine_did_not_touch_opening_fvg(self):
        """It carries no quarantine reason because it was never quarantined --
        it has no execution authority to remove."""
        cat = authorized_tool_catalog(snap("bullish_opening_fvg"))
        if cat:
            assert cat[0]["execution_ineligible_reason"] != IFVG_QUARANTINE_REASON


class TestTheQuarantineIsNarrow:

    def test_only_ifvg_is_quarantined(self):
        tools = ["bullish_ote_after_reclaim", "bullish_order_block",
                 "bullish_breaker", "bullish_rejection_block",
                 "bullish_range_break_retest", "bullish_ote_retracement"]
        for e in authorized_tool_catalog(snap(*tools)):
            assert e["execution_eligible"] is True, e["tool_family"]
            assert e["execution_ineligible_reason"] != IFVG_QUARANTINE_REASON

    def test_the_reason_is_a_named_constant_not_an_inline_string(self):
        """Re-enabling IFVG later must be a deliberate act against a named
        condition, not the quiet deletion of a flag."""
        import ast
        import inspect
        import textwrap
        from broker import luna_candidate_producer as LP
        tree = ast.parse(textwrap.dedent(
            inspect.getsource(LP.authorized_tool_catalog)))
        names = {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)}
        assert "IFVG_QUARANTINE_REASON" in names
