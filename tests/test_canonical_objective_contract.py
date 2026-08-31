"""COMPLETE-EXTERNAL-BRAIN-CANONICAL-EXECUTION-CONTRACT (2026-08-07).

PROD-20260807 produced 171 scans, 84 directional theses and 23 explicit
propose-entry decisions -- and 0 candidates. The external Brain was not refusing
to trade. The join between what it chose and what the deterministic engine knew
was prose:

    Brain: "Sell-side liquidity at 29452.50"
    Engine: opposing_external_liquidity:sellside@29452.5   (already enumerated)
    Bridge: classify_draw(prose) -> kind -> side filter
    Result: None on 17 of 23 -> objective_unresolved -> no candidate

Worse, at 09:47:03 the Brain named 29493.25; prose classification reduced it to
a KIND, side-filtering left one survivor, and the producer bound 29452.50 -- a
different level than the Brain selected. Directionally valid, and therefore
silent. Accidental correctness is not correctness.

Executable identity now comes from an id chosen out of a catalog the
deterministic engine publishes. The Brain still owns discretion; the engine
still owns every validation.
"""
from __future__ import annotations

import os
import sys
from datetime import datetime, timezone

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src"))

from _step7_fixture import detected as _detected      # noqa: E402
from _step7_fixture import priced as _priced          # noqa: E402

from ai_brain.production_model import PRODUCTION_MODEL  # noqa: E402
from _step7_fixture import EXECUTABLE_TOOL_EXEMPLAR as EXEMPLAR  # noqa: E402

from ai_brain.brain_schema import empty_brain_output          # noqa: E402
from broker.luna_candidate_producer import (CandidateProducer,  # noqa: E402
                                            NoCandidate,
                                            authorized_invalidation_catalog,
                                            authorized_objective_catalog,
                                            objective_id,
                                            resolve_objective_by_id)
from broker.topstepx_client import TopstepXContract            # noqa: E402

MNQ = TopstepXContract(id="CON.F.US.MNQ.U26", name="MNQU6", description="MNQ",
                       tick_size=0.25, tick_value=0.5, active=True)
NOW = datetime(2026, 8, 7, 14, 0, tzinfo=timezone.utc)

#: The exact shape of the 09:47:03 scan that produced the silent substitution.
BRAIN_INPUT = {
    "timestamp": "2026-08-07T13:47:00+00:00",
    "market": _priced({"current_price": 29695.75}),
    "liquidity": {"nearest_buy_side": 29780.0, "nearest_sell_side": 29452.5},
    "protected_swings": {
        "protected_low": {"level": 29493.25,
                          "timestamp": "2026-08-07T13:45:00+00:00"},
        "protected_low_status": "above"},
}


def catalog():
    return authorized_objective_catalog({}, BRAIN_INPUT, 29695.75)


def parsed(**over):
    p = {"narrative_direction": "bearish", "allowed_direction": "bearish",
         "narrative_phase": "distribution",
         "current_action": "propose bearish liquidity_sweep_reversal entry",
         "recommended_playbook_family": "liquidity_sweep_reversal",
         "recommended_tool_family": [EXEMPLAR],
         "invalidation_level": 29780.0,
         "active_draw": "Sell-side liquidity at 29452.50"}
    p.update(over)
    return p


def produce(p, *, prose=False):
    return CandidateProducer(account_fingerprint="acct:test", contract=MNQ,
                             allow_prose_objective_fallback=prose).produce(
        brain_result={"ok": True, "parsed": p, "fallback_reason": None,
                      "model": PRODUCTION_MODEL},
        brain_input=BRAIN_INPUT, snapshot=_detected("ifvg", "fvg"),
        qualification={"qualified": True},
        engine_inventory={"liquidity": "PRESENT_AND_POPULATED"},
        snapshot_id="s1", market_data_timestamp=BRAIN_INPUT["timestamp"],
        latest_closed_bar_timestamp=BRAIN_INPUT["timestamp"], now=NOW)


# ══════════════════════════════════════════════════════════════════════════════
class TestCatalog:
    """1-2, 8, 12."""

    def test_1_the_catalog_comes_from_the_deterministic_producers(self):
        c = catalog()
        sources = {o["source"] for o in c}
        assert sources <= {"liquidity.nearest_buy_side",
                           "liquidity.nearest_sell_side",
                           "protected_swings.protected_high",
                           "protected_swings.protected_low"}
        assert all(o["objective_id"] for o in c)

    def test_ids_are_stable_within_a_snapshot(self):
        assert [o["objective_id"] for o in catalog()] == \
               [o["objective_id"] for o in catalog()]

    def test_2_the_brain_packet_carries_the_catalog(self):
        """The catalog must be published BEFORE the model call, not after."""
        import ast
        tree = ast.parse(open("src/ai_brain/narrative_brain.py",
                              encoding="utf-8").read())
        names = {getattr(n.func, "id", "") for n in ast.walk(tree)
                 if isinstance(n, ast.Call)}
        assert "authorized_objective_catalog" in names
        assert "authorized_invalidation_catalog" in names

    def test_12_29452_50_binds_to_its_exact_catalog_object(self):
        c = catalog()
        ssl = [o for o in c if abs(o["price"] - 29452.5) < 0.01]
        assert len(ssl) == 1
        got = resolve_objective_by_id(ssl[0]["objective_id"], c,
                                      direction="bearish",
                                      reference_price=29695.75)
        assert got["price"] == 29452.5
        assert got["kind"] == "opposing_external_liquidity"


class TestSelectionContract:
    """3-7, 9-11."""

    def test_3_propose_entry_requires_an_objective_id(self):
        with pytest.raises(NoCandidate) as exc:
            produce(parsed())                       # prose only, no id
        assert exc.value.reason == "objective_id_missing"

    def test_4_an_unknown_objective_id_is_rejected(self):
        with pytest.raises(NoCandidate) as exc:
            produce(parsed(objective_id="OBJ_LIQ_SSL_99"))
        assert exc.value.reason == "objective_id_unknown"

    def test_5_an_invented_objective_id_is_rejected(self):
        for invented in ("sell_side_liquidity", "29452.50", "SSL_1", ""):
            with pytest.raises(NoCandidate):
                produce(parsed(objective_id=invented))

    def test_6_7_stand_down_and_wait_need_no_objective_id(self):
        for action in ("stand_down", "wait"):
            with pytest.raises(NoCandidate) as exc:
                produce(parsed(current_action=action,
                               recommended_playbook_family="none",
                               recommended_tool_family=["none"]))
            # refused for standing down, NOT for a missing execution object
            assert exc.value.reason != "objective_id_missing"
        assert empty_brain_output()["objective_id"] is None
        assert empty_brain_output()["invalidation_id"] is None

    def test_8_a_canonical_id_resolves_the_exact_object(self):
        ssl = [o for o in catalog() if abs(o["price"] - 29452.5) < 0.01][0]
        candidate = produce(parsed(objective_id=ssl["objective_id"]))
        assert candidate.objective.price == 29452.5

    def test_9_no_live_prose_fallback_occurs(self):
        """Production default is id-only; prose is opt-in for replay."""
        p = CandidateProducer(account_fingerprint="a", contract=MNQ)
        assert p.allow_prose_objective_fallback is False

    def test_10_11_one_id_can_never_silently_resolve_another_level(self):
        """THE 09:47:03 REGRESSION.

        The Brain named 29493.25 (a protected swing). Prose binding reduced that
        to a kind and returned 29452.50. With ids, selecting the protected swing
        yields the protected swing -- or nothing.
        """
        ps = [o for o in catalog() if abs(o["price"] - 29493.25) < 0.01][0]
        assert ps["kind"] == "protected_swing"
        candidate = produce(parsed(objective_id=ps["objective_id"]))
        assert candidate.objective.price == 29493.25, (
            "an id resolved to a level the Brain did not choose")

        # and the prose path really did substitute, which is why it is gated off
        prose_candidate = produce(parsed(), prose=True)
        assert prose_candidate.objective.price == 29452.5
        assert prose_candidate.objective.price != 29493.25

    def test_a_wrong_side_selection_is_refused(self):
        bsl = [o for o in catalog() if abs(o["price"] - 29780.0) < 0.01][0]
        with pytest.raises(NoCandidate) as exc:
            produce(parsed(objective_id=bsl["objective_id"]))
        assert exc.value.reason == "objective_wrong_side"


class TestDeterministicAuthorityRetained:
    """13-19. Selection is not authorisation."""

    def test_13_side_validation_remains(self):
        assert "objective_wrong_side" in open(
            "src/broker/luna_candidate_producer.py", encoding="utf-8").read()

    def test_14_15_16_17_18_producer_still_owns_geometry_rr_and_risk(self):
        src = open("src/broker/luna_candidate_producer.py", encoding="utf-8").read()
        for guard in ("objective_off_tick", "reward_below_qualification",
                      "MIN_QUALIFICATION_R", "_invalidation", "_reward_to_risk"):
            assert guard in src, guard
        from broker.topstepx_combine_risk import (PRODUCTION_MAX_CONTRACTS,
                                                  PRODUCTION_MAX_RISK_USD)
        assert PRODUCTION_MAX_RISK_USD == 350.0
        assert PRODUCTION_MAX_CONTRACTS == 15

    def test_19_the_invalidation_catalog_exists_and_is_deterministic(self):
        inv = authorized_invalidation_catalog(BRAIN_INPUT)
        assert inv and all(i["invalidation_id"] for i in inv)
        assert inv[0]["price"] == 29493.25
        assert inv == authorized_invalidation_catalog(BRAIN_INPUT)

    def test_selecting_an_objective_does_not_bypass_validation(self):
        """A valid id with an impossible invalidation still dies."""
        ssl = [o for o in catalog() if abs(o["price"] - 29452.5) < 0.01][0]
        with pytest.raises(NoCandidate):
            produce(parsed(objective_id=ssl["objective_id"],
                           invalidation_level=29452.0))   # stop past the target


class TestSchemaAndPrompt:
    """The contract is stated where the model can read it."""

    def test_the_schema_declares_both_fields(self):
        out = empty_brain_output()
        assert "objective_id" in out and "invalidation_id" in out
        src = open("src/ai_brain/brain_schema.py", encoding="utf-8").read()
        assert '"objective_id"' in src and '"invalidation_id"' in src

    def test_the_prompt_states_the_canonical_law(self):
        from ai_brain.brain_prompt import BRAIN_SYSTEM_PROMPT as P
        flat = " ".join(P.split())
        assert "AUTHORIZED_OBJECTIVES" in P
        assert "AUTHORIZED_INVALIDATIONS" in P
        assert "objective_id" in P and "invalidation_id" in P
        assert "Never invent an id" in flat or "never invent an id" in flat
        assert "Prose is NEVER the executable identity" in flat

    def test_32_33_no_authorization_or_order_path_here(self):
        assert os.environ.get("PRODUCTION_ARMED_SESSION") is None
        import ast
        tree = ast.parse(open(__file__, encoding="utf-8").read())
        called = {getattr(n.func, "attr", "") or getattr(n.func, "id", "")
                  for n in ast.walk(tree) if isinstance(n, ast.Call)}
        for forbidden in ("gated_submit", "place_order", "issue",
                          "SessionAuthorization"):
            assert forbidden not in called, forbidden
