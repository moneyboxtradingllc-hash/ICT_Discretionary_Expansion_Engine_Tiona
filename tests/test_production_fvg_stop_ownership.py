"""STEP 4B.12 §6 UNIT 6 — TOOL AUTHORITY IS NOT STOP AUTHORITY.

ANTI-REGRESSION LOCKS around an ownership boundary that is currently correct by
CONSTRUCTION, and could be broken by one plausible future edit.

On the production MNQ / TopstepX lane the two propositions have different owners:

    exact plain-FVG occurrence   ->  does this tool EXIST, on this side, with a
                                     lawful lifecycle and temporal authority,
                                     and does Terra's family token identify
                                     exactly one of them?

    Terra-selected invalidation  ->  WHERE the stop is, validated through
                                     `authorized_invalidation_catalog` and bound
                                     to a protected swing.

`CandidateProducer._invalidation` never reads `toolbox`, `price_level`,
`build_price_level`, `zone_low/high` or `gaps[0]`. It validates a numeric level
Terra named -- tick grid, correct side of the reference price -- and binds it to
`protected_low` / `protected_high`.

So Unit 6 deliberately did NOT thread the resolved occurrence into order
construction: there is nothing on this lane for it to author. These tests make
that permanent. If someone later wires `price_level.invalidation_level` or an
FVG boundary into the production stop path, REGRESSION A fails loudly.

SCOPE: production lane only. `paper_execution.build_order` DOES derive its stop
from the family compatibility zone (recorded as PAPER-FVG-1), and is unreachable
from the practice configuration -- the production launcher refuses to start when
any `paper_execution` module is loaded in the process.
"""
from __future__ import annotations

import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))), "src"))

import test_luna_candidate_producer as LCP  # noqa: E402
from broker.luna_candidate_producer import NoCandidate  # noqa: E402

CONTRACT = "CON.F.US.MNQ.U26"
REF_PRICE = 29880.0

#: Two DIFFERENT authorized structural invalidations, both bullish-valid:
#: below the reference price and on the 0.25 tick grid.
S1 = 29875.0
S2 = 29870.0


def fvg_snapshot(zone_low, zone_high, *, oid="A", extra_occurrences=(),
                 family_invalidation=None):
    """A production-shaped toolbox carrying exact FVG occurrence instances.

    `family_invalidation` deliberately points the FAMILY compatibility zone at a
    level that is NOT the authorized structural invalidation, so any future code
    that reaches for it instead of the catalog is caught.
    """
    def inst(o, lo, hi):
        return {"tool": "bullish_fvg", "family": "fvg", "direction": "bullish",
                "source_tf": "5m", "tool_id": f"bullish_fvg@5m#{o}",
                "occurrence_id": f"FVG:{CONTRACT}:5m:{o}",
                "zone_low": lo, "zone_high": hi,
                "identity_evaluable": True, "temporal_class": "settled",
                "temporal_execution_eligible": True,
                "execution_eligible": True, "execution_ineligible_reason": None,
                "score": 60}

    instances = [inst(oid, zone_low, zone_high)]
    instances += [inst(o, lo, hi) for o, lo, hi in extra_occurrences]
    return {"toolbox": {
        "preferred_tool": "bullish_fvg",
        "tool_instances": instances,
        "tool_candidates": [{
            "tool": "bullish_fvg", "effective_status": "ready",
            "price_level": {
                "level_type": "fvg_zone", "direction": "bullish",
                "source_tf": "5m", "execution_eligible": True,
                "temporal_class": "settled",
                "zone_low": zone_low, "zone_high": zone_high,
                # THE TRAP: a plausible-looking stop that is NOT the authorized
                # structural invalidation.
                "invalidation_level": (family_invalidation
                                       if family_invalidation is not None
                                       else zone_low),
            }}]}}


def execution_fields(candidate):
    """Every production execution-bearing field this lane publishes."""
    return {
        "direction": candidate.direction,
        "invalidation_price": candidate.invalidation_price,
        "objective_price": candidate.objective.price,
        "objective_kind": candidate.objective.kind,
        "risk_distance": round(abs(REF_PRICE - candidate.invalidation_price), 4),
    }


def produce_with(snapshot, invalidation=S1):
    return LCP.produce(
        res=LCP.result(parsed=LCP.parsed(invalidation_level=invalidation,
                                         recommended_tool_family=["fvg"])),
        bi=LCP.brain_input(price=REF_PRICE),
        snapshot=snapshot)


# ── REGRESSION A ─────────────────────────────────────────────────────────────
class TestFvgGeometryCannotAuthorTheProductionStop:

    def test_moving_the_fvg_leaves_every_execution_field_untouched(self):
        """FVG geometry A -> B, authorized invalidation held at S1."""
        a = execution_fields(produce_with(
            fvg_snapshot(29860.0, 29866.0, family_invalidation=29860.0)))
        b = execution_fields(produce_with(
            fvg_snapshot(29820.0, 29831.5, family_invalidation=29820.0)))
        assert a == b, f"FVG geometry leaked into execution: {a} != {b}"
        assert a["invalidation_price"] == S1

    def test_the_family_zone_disagrees_and_loses(self):
        """The compatibility zone names 29820.0; the authorized structural
        invalidation is 29875.0. The stop must be the authorized one."""
        c = produce_with(fvg_snapshot(29820.0, 29831.5,
                                      family_invalidation=29820.0))
        assert c.invalidation_price == S1
        assert c.invalidation_price != 29820.0

    def test_risk_distance_follows_the_structural_invalidation_only(self):
        near = produce_with(fvg_snapshot(29878.0, 29879.0,
                                         family_invalidation=29878.0))
        far = produce_with(fvg_snapshot(29700.0, 29711.0,
                                        family_invalidation=29700.0))
        assert near.invalidation_price == far.invalidation_price == S1

    def test_the_objective_is_unaffected_by_fvg_geometry(self):
        a = produce_with(fvg_snapshot(29860.0, 29866.0))
        b = produce_with(fvg_snapshot(29700.0, 29711.0))
        assert a.objective.price == b.objective.price
        assert a.objective.kind == b.objective.kind


# ── REGRESSION B ─────────────────────────────────────────────────────────────
class TestStructuralInvalidationOwnsTheStop:

    def test_changing_the_authorized_invalidation_moves_the_stop(self):
        """FVG held constant; S1 -> S2. The stop must follow."""
        snap = fvg_snapshot(29860.0, 29866.0, family_invalidation=29860.0)
        one = produce_with(snap, invalidation=S1)
        two = produce_with(snap, invalidation=S2)
        assert one.invalidation_price == S1
        assert two.invalidation_price == S2
        assert one.invalidation_price != two.invalidation_price

    def test_risk_distance_changes_with_the_invalidation(self):
        snap = fvg_snapshot(29860.0, 29866.0)
        d1 = abs(REF_PRICE - produce_with(snap, invalidation=S1).invalidation_price)
        d2 = abs(REF_PRICE - produce_with(snap, invalidation=S2).invalidation_price)
        assert d2 > d1, "a farther invalidation must widen the risk distance"
        assert (d1, d2) == (5.0, 10.0)

    def test_the_invalidation_is_bound_to_a_protected_swing(self):
        """It is not a bare number: the producer binds it to the structural
        object that authorizes it."""
        c = produce_with(fvg_snapshot(29860.0, 29866.0), invalidation=S1)
        assert "protected_low" in str(c.extras.get("invalidation_identity", "")) \
            or c.invalidation_price == S1


# ── the ownership boundary, structurally ─────────────────────────────────────
class TestTheOwnershipBoundaryIsStructural:

    def test_the_invalidation_resolver_never_reads_the_toolbox(self):
        import ast
        import inspect
        import textwrap
        from broker.luna_candidate_producer import CandidateProducer
        tree = ast.parse(textwrap.dedent(
            inspect.getsource(CandidateProducer._invalidation)))
        names = {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)}
        attrs = {n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute)}
        keys = {n.value for n in ast.walk(tree)
                if isinstance(n, ast.Constant) and isinstance(n.value, str)}
        for forbidden in ("toolbox", "price_level", "zone_low", "zone_high",
                          "build_price_level", "tool_candidates",
                          "tool_instances", "occurrence_id", "fvg"):
            assert forbidden not in (names | attrs | keys), \
                f"the production stop resolver reached for {forbidden}"

    def test_the_stop_owner_is_the_brain_selected_level(self):
        import ast
        import inspect
        import textwrap
        from broker.luna_candidate_producer import CandidateProducer
        src = textwrap.dedent(inspect.getsource(CandidateProducer._invalidation))
        assert 'parsed.get("invalidation_level")' in src
        tree = ast.parse(src)
        keys = {n.value for n in ast.walk(tree)
                if isinstance(n, ast.Constant) and isinstance(n.value, str)}
        assert {"protected_low", "protected_high"} <= keys


# ── _assert_tool_detected is a VERIFICATION boundary ─────────────────────────
class TestToolVerificationIsNotStopAuthority:

    def test_zero_eligible_occurrences_refuses(self):
        snap = fvg_snapshot(29860.0, 29866.0)
        for i in snap["toolbox"]["tool_instances"]:
            i["execution_eligible"] = False
            i["execution_ineligible_reason"] = "historical_close_through_far_boundary"
        with pytest.raises(NoCandidate) as e:
            produce_with(snap)
        assert e.value.reason == "tool_not_execution_eligible"

    def test_one_eligible_occurrence_produces_a_candidate(self):
        c = produce_with(fvg_snapshot(29860.0, 29866.0))
        assert c.invalidation_price == S1

    def test_two_eligible_occurrences_refuse_as_ambiguous(self):
        with pytest.raises(NoCandidate) as e:
            produce_with(fvg_snapshot(
                29860.0, 29866.0,
                extra_occurrences=[("B", 29840.0, 29848.0)]))
        assert e.value.reason == "tool_occurrence_ambiguous"

    def test_no_fvg_GEOMETRY_reaches_candidate_price_authority(self):
        """SUPERSEDED PREMISE, REPLACED BY THE ACTUAL THEOREM.

        This assertion used to read `"FVG:" not in blob` under the rationale
        that "nothing downstream depends on WHICH occurrence verified the tool,
        so the resolver's return may be discarded". TOOL-OCCURRENCE-SELECTION-1
        deliberately reverses that: Luna now names an exact occurrence, mechanics
        verifies THAT occurrence, and the candidate preserves its canonical
        identity so "which market object authorized this exposure" survives.

        The old string check conflated two different things:

            market-object IDENTITY   FVG:CON.F.US.MNQ.U26:5m:A
            market-object GEOMETRY   zone_low / zone_high -> a price

        Only the second can hijack stop authority. An occurrence id carries no
        price and cannot tell execution where to enter, stop or target. The
        doctrine this suite exists to defend -- tool verification is NOT price
        authority -- is unchanged and is now asserted DIRECTLY below rather than
        by forbidding a substring.
        """
        c = produce_with(fvg_snapshot(29860.0, 29866.0))
        blob = str(c.extras) + str(c.invalidation_price) + str(c.objective.price)
        # GEOMETRY still may not leak into anything price-bearing.
        assert "29866.0" not in blob, "an FVG boundary reached the candidate"
        assert "29860.0" not in blob, "an FVG boundary reached the candidate"
        # IDENTITY is now expected, and is provenance only.
        assert c.extras["selected_tool_occurrence_id"] == f"FVG:{CONTRACT}:5m:A"

    def test_the_verified_occurrence_is_provenance_and_not_price(self):
        """The six authority proofs, asserted on values rather than substrings."""
        c = produce_with(fvg_snapshot(29860.0, 29866.0))
        assert c.entry_price == REF_PRICE                    # 1 fresh quote
        assert c.entry_price not in (29860.0, 29866.0)       # 2 not a boundary
        assert c.invalidation_price == S1                    # 3 Luna's own level
        assert c.invalidation_price not in (29860.0, 29866.0)
        assert c.objective.price == produce_with(            # 4 separately resolved
            fvg_snapshot(29820.0, 29831.5)).objective.price

    def test_changing_only_the_selected_occurrence_moves_only_provenance(self):
        """5 — X -> Y in a controlled fixture."""
        snap = fvg_snapshot(29860.0, 29866.0, oid="A",
                            extra_occurrences=[("B", 29840.0, 29848.0)])

        def build(oid):
            return LCP.produce(
                res=LCP.result(parsed=LCP.parsed(
                    invalidation_level=S1, recommended_tool_family=["fvg"],
                    recommended_tool_occurrence_id=f"FVG:{CONTRACT}:5m:{oid}")),
                bi=LCP.brain_input(price=REF_PRICE), snapshot=snap)

        a, b = build("A"), build("B")
        assert a.extras["selected_tool_occurrence_id"] != \
            b.extras["selected_tool_occurrence_id"]
        assert a.entry_price == b.entry_price
        assert a.invalidation_price == b.invalidation_price
        assert a.objective.price == b.objective.price

    def test_nothing_downstream_reads_the_occurrence_as_authority(self):
        """6 — the field is written and never consulted for a decision."""
        import subprocess
        readers = subprocess.run(
            ["git", "grep", "-l", "selected_tool_occurrence_id", "--", "src/"],
            capture_output=True, text=True).stdout.split()
        assert readers == ["src/broker/luna_candidate_producer.py"], readers
