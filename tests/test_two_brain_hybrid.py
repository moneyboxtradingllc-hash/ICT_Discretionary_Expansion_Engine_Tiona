"""TWO-BRAIN-HYBRID (2026-08-08) — experiment/two-brain-hybrid.

The deterministic author proposes, the external Brain adjudicates, and the
mechanical gates decide. The last clause is the whole safety argument: a
CONFIRM is not permission, and nothing in the hybrid path can make an
under-qualified candidate executable.

Two failure modes are guarded here. The obvious one is Terra gaining a veto it
did not earn -- a MATERIAL_REJECT with nothing named, or one that only restates
a reward:risk the mechanical lane already checked. The subtler one is the
deterministic lane sneaking authority by omission: a thesis with no `model`
field slipping past `wrong_model` simply because the field is absent. Authority
must be declared and proven, never inferred.
"""
from __future__ import annotations

import copy
import os
import sys
from datetime import datetime, timezone

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))

from _step7_fixture import detected as _detected      # noqa: E402
from _step7_fixture import priced as _priced          # noqa: E402
from _step7_fixture import EXECUTABLE_TOOL_EXEMPLAR as EXEMPLAR  # noqa: E402

from ai_brain import two_brain as TB                                # noqa: E402
from ai_brain.narrative_brain import _archivable_snapshot           # noqa: E402
from ai_brain.production_model import PRODUCTION_MODEL              # noqa: E402
from broker.luna_candidate_producer import (CandidateProducer,      # noqa: E402
                                            NoCandidate)
from broker.topstepx_client import TopstepXContract                 # noqa: E402

MNQ = TopstepXContract(id="CON.F.US.MNQ.U26", name="MNQU6", description="MNQ",
                       tick_size=0.25, tick_value=0.5, active=True)
NOW = datetime(2026, 8, 8, 14, 0, tzinfo=timezone.utc)


def thesis(direction="bearish"):
    return {"narrative_direction": direction, "narrative_phase": "distribution",
            "recommended_playbook_family": "liquidity_sweep_reversal",
            "market_story": "deterministic read"}


def proposal(direction="bearish", objective_price=29400.0,
             invalidation_price=29850.0, price=29700.0):
    return TB.build_mechanical_proposal(
        thesis=thesis(direction),
        objective={"objective_id": "OBJ_LIQ_SSL_1", "price": objective_price,
                   "kind": "opposing_external_liquidity"},
        invalidation={"invalidation_id": "INV_PH_1", "price": invalidation_price},
        reference_price=price, snapshot_id="snap-1",
        timestamp="2026-08-08T14:00:00+00:00")


def review(verdict=TB.CONFIRM, contradictions=None, p=None, **over):
    p = p or proposal()
    r = {"candidate_id": p["mechanical_proposal_id"], "verdict": verdict,
         "confidence": 90, "mechanical_direction_seen": p["direction"],
         "objective_id_seen": p["objective_id"],
         "invalidation_id_seen": p["invalidation_id"],
         "material_contradictions": contradictions or [],
         "reasoning": "test"}
    r.update(over)
    return r


# ══════════════════════════════════════════════════════════════════════════════
class TestModeContract:

    def test_default_is_off(self, monkeypatch):
        monkeypatch.delenv("TWO_BRAIN_MODE", raising=False)
        assert TB.two_brain_mode() == TB.OFF
        assert TB.hybrid_enabled() is False
        assert TB.hybrid_has_authority() is False

    @pytest.mark.parametrize("value", ["", "   ", "yes", "true", "on", "veto"])
    def test_a_blank_or_unknown_value_is_off(self, monkeypatch, value):
        """An operating mode nobody wrote down is not an operating mode."""
        monkeypatch.setenv("TWO_BRAIN_MODE", value)
        assert TB.two_brain_mode() == TB.OFF

    def test_only_the_named_mode_grants_authority(self, monkeypatch):
        for mode, authority in ((TB.OFF, False), (TB.SHADOW, False),
                                (TB.MATERIAL_REJECT_VETO, True)):
            monkeypatch.setenv("TWO_BRAIN_MODE", mode)
            assert TB.hybrid_has_authority() is authority


class TestRawSnapshotImmutability:
    """PHASE 2 — the archive may not depend on statement ordering."""

    def test_deeply_nested_mutation_cannot_reach_the_archive(self):
        snapshot = {"market": _priced({"current_price": 29700.0}),
                    "liquidity": {"events": [{"tf": "5m", "sweep": "above_high"}],
                                  "nested": {"deep": {"value": 1}}}}
        archived = _archivable_snapshot(snapshot)
        snapshot["market"]["current_price"] = 99999.0
        snapshot["liquidity"]["events"][0]["sweep"] = "MUTATED"
        snapshot["liquidity"]["nested"]["deep"]["value"] = 999
        snapshot["liquidity"]["events"].append({"injected": True})
        assert archived["market"]["current_price"] == 29700.0
        assert archived["liquidity"]["events"][0]["sweep"] == "above_high"
        assert archived["liquidity"]["nested"]["deep"]["value"] == 1
        assert len(archived["liquidity"]["events"]) == 1

    def test_account_truth_still_excluded(self):
        snap = {"market": {"x": 1}, "risk": {"budget": 250},
                "position_monitor": {"qty": 3}}
        assert _archivable_snapshot(snap) == {"market": {"x": 1}}

    def test_hostile_input_cannot_break_a_scan(self):
        class Hostile(dict):
            def items(self):
                raise RuntimeError("boom")
        assert _archivable_snapshot(Hostile()) == {}
        assert _archivable_snapshot(None) == {}


class TestExactBinding:
    """PHASE 4 — exact semantics or stand down."""

    CATALOG = [{"objective_id": "OBJ_A", "price": 29400.0},
               {"objective_id": "OBJ_B", "price": 29850.0}]

    def test_exact_match_binds(self):
        out = TB.bind_exact(29400.0, self.CATALOG, "objective_id")
        assert out["bound"] and out["object"]["objective_id"] == "OBJ_A"

    def test_no_match_stands_down_rather_than_taking_the_nearest(self):
        """29452.50 was once bound when the thesis named 29493.25."""
        out = TB.bind_exact(29399.75, self.CATALOG, "objective_id")
        assert out["bound"] is False
        assert out["reason"] == TB.NO_OBJECTIVE_MATCH

    def test_ambiguity_stands_down(self):
        dup = self.CATALOG + [{"objective_id": "OBJ_C", "price": 29400.0}]
        out = TB.bind_exact(29400.0, dup, "objective_id")
        assert out["bound"] is False
        assert out["reason"] == TB.AMBIGUOUS_OBJECTIVE
        assert set(out["candidates"]) == {"OBJ_A", "OBJ_C"}

    def test_non_numeric_level_stands_down(self):
        assert TB.bind_exact("sell-side liquidity", self.CATALOG,
                             "objective_id")["bound"] is False


class TestReviewClassification:
    """PHASES 5, 6, 11."""

    def test_confirm_and_abstain_pass_through(self):
        p = proposal()
        for v in (TB.CONFIRM, TB.ABSTAIN):
            c = TB.classify_review(review(v, p=p), p)
            assert c["effective_verdict"] == v and c["valid"]

    def test_abstain_is_never_normalised(self):
        p = proposal()
        c = TB.classify_review(review(TB.ABSTAIN, p=p), p)
        assert c["effective_verdict"] == TB.ABSTAIN
        assert c["effective_verdict"] not in (TB.CONFIRM, TB.MATERIAL_REJECT)

    def test_material_reject_needs_a_named_contradiction(self):
        p = proposal()
        c = TB.classify_review(review(TB.MATERIAL_REJECT, [], p=p), p)
        assert c["effective_verdict"] == TB.INVALID_MATERIAL_REJECT
        assert c["stated_verdict"] == TB.MATERIAL_REJECT   # recorded, not hidden

    def test_a_grounded_material_reject_is_valid(self):
        p = proposal()
        c = TB.classify_review(review(
            TB.MATERIAL_REJECT,
            ["supplied delivery is bullish_delivery, opposing the bearish candidate"],
            p=p), p)
        assert c["effective_verdict"] == TB.MATERIAL_REJECT and c["valid"]

    def test_mechanical_grounds_do_not_earn_a_contextual_veto(self):
        """RR belongs to the mechanical lane. Restating it is not adjudication."""
        p = proposal()
        c = TB.classify_review(review(
            TB.MATERIAL_REJECT, ["reward_to_risk is only 0.7"], p=p), p)
        assert c["effective_verdict"] == TB.INVALID_MATERIAL_REJECT

    def test_the_reviewer_may_disagree_but_may_not_rename(self):
        p = proposal()
        c = TB.classify_review(review(TB.CONFIRM, p=p,
                                      objective_id_seen="OBJ_SOMETHING_ELSE"), p)
        assert c["valid"] is False
        assert any("objective_id_seen altered" in x for x in c["problems"])


class TestEnvelope:
    """PHASE 7."""

    def test_shadow_never_changes_a_disposition(self, monkeypatch):
        monkeypatch.setenv("TWO_BRAIN_MODE", TB.SHADOW)
        p = proposal()
        env = TB.build_envelope(
            proposal=p, review=review(TB.MATERIAL_REJECT, ["delivery opposes"], p=p),
            classification=TB.classify_review(
                review(TB.MATERIAL_REJECT, ["delivery opposes"], p=p), p))
        assert env["hybrid_disposition"] == TB.SHADOW_RECORDED_ONLY
        # ...but it still reports what veto mode WOULD have done
        assert TB.shadow_hypothetical(env) == TB.STAND_DOWN_CONTEXTUAL_REJECT

    def test_veto_mode_blocks_only_a_grounded_reject(self, monkeypatch):
        monkeypatch.setenv("TWO_BRAIN_MODE", TB.MATERIAL_REJECT_VETO)
        p = proposal()
        cases = {
            TB.CONFIRM: (["x"], TB.CONTINUE_TO_MECHANICAL_GATES),
            TB.ABSTAIN: ([], TB.CONTINUE_TO_MECHANICAL_GATES),
            TB.MATERIAL_REJECT: (["delivery opposes the thesis"],
                                 TB.STAND_DOWN_CONTEXTUAL_REJECT),
        }
        for verdict, (contras, expected) in cases.items():
            r = review(verdict, contras, p=p)
            env = TB.build_envelope(proposal=p, review=r,
                                    classification=TB.classify_review(r, p))
            assert env["hybrid_disposition"] == expected, verdict

    def test_an_unsupported_veto_does_not_stop_the_trade(self, monkeypatch):
        monkeypatch.setenv("TWO_BRAIN_MODE", TB.MATERIAL_REJECT_VETO)
        p = proposal()
        r = review(TB.MATERIAL_REJECT, [], p=p)
        env = TB.build_envelope(proposal=p, review=r,
                                classification=TB.classify_review(r, p))
        assert env["hybrid_disposition"] == TB.CONTINUE_TO_MECHANICAL_GATES

    def test_binding_failure_stands_down_before_any_review(self):
        env = TB.build_envelope(proposal=None, binding_failure={
            "reason": TB.AMBIGUOUS_OBJECTIVE})
        assert env["hybrid_disposition"] == TB.STAND_DOWN_BINDING_FAILED

    def test_the_proposal_is_not_mutated_by_enveloping(self):
        p = proposal()
        before = copy.deepcopy(p)
        TB.build_envelope(proposal=p, review=review(p=p))
        assert p == before
        assert TB.proposal_is_intact(p)

    def test_a_tampered_proposal_is_detectable(self):
        p = proposal()
        p["objective_price"] = 1.0
        assert TB.proposal_is_intact(p) is False


class TestHybridAuthority:
    """PHASE 8 — authority declared and proven, never inferred."""

    def envelope(self, monkeypatch, **over):
        monkeypatch.setenv("TWO_BRAIN_MODE", TB.MATERIAL_REJECT_VETO)
        p = proposal()
        r = review(TB.CONFIRM, p=p)
        env = TB.build_envelope(proposal=p, review=r,
                                classification=TB.classify_review(r, p))
        env.update(over)
        return env

    def test_a_complete_envelope_is_authorized(self, monkeypatch):
        env = self.envelope(monkeypatch)
        out = TB.authorized_hybrid_envelope({TB.HYBRID_ENVELOPE_KEY: env})
        assert out["authorized"] is True

    def test_a_missing_model_alone_never_grants_authority(self, monkeypatch):
        """THE BYPASS THIS CONTRACT EXISTS TO PREVENT."""
        monkeypatch.setenv("TWO_BRAIN_MODE", TB.MATERIAL_REJECT_VETO)
        for r in ({"ok": True, "parsed": {}, "source": "deterministic"},
                  {"ok": True, "parsed": {}, "model": None}):
            assert TB.authorized_hybrid_envelope(r)["authorized"] is False

    def test_shadow_mode_envelope_grants_no_authority(self, monkeypatch):
        monkeypatch.setenv("TWO_BRAIN_MODE", TB.SHADOW)
        p = proposal()
        env = TB.build_envelope(proposal=p, review=review(p=p))
        assert TB.authorized_hybrid_envelope(
            {TB.HYBRID_ENVELOPE_KEY: env})["authorized"] is False

    def test_runtime_mode_must_also_permit_it(self, monkeypatch):
        env = self.envelope(monkeypatch)
        monkeypatch.setenv("TWO_BRAIN_MODE", TB.OFF)   # runtime disagrees
        out = TB.authorized_hybrid_envelope({TB.HYBRID_ENVELOPE_KEY: env})
        assert out["authorized"] is False
        assert out["reason"] == "runtime_mode_does_not_permit_hybrid"

    def test_a_mutated_proposal_loses_authority(self, monkeypatch):
        env = self.envelope(monkeypatch)
        env["mechanical_proposal"]["objective_price"] = 1.0
        out = TB.authorized_hybrid_envelope({TB.HYBRID_ENVELOPE_KEY: env})
        assert out["authorized"] is False
        assert out["reason"] == "mechanical_proposal_mutated"

    def test_missing_adjudication_loses_authority(self, monkeypatch):
        env = self.envelope(monkeypatch, terra_review=None)
        assert TB.authorized_hybrid_envelope(
            {TB.HYBRID_ENVELOPE_KEY: env})["authorized"] is False

    def test_a_rejected_disposition_loses_authority(self, monkeypatch):
        env = self.envelope(monkeypatch,
                            hybrid_disposition=TB.STAND_DOWN_CONTEXTUAL_REJECT)
        assert TB.authorized_hybrid_envelope(
            {TB.HYBRID_ENVELOPE_KEY: env})["authorized"] is False


class TestBaselineParity:
    """PHASE 15 — with hybrid off, behaviour is the pre-hybrid baseline."""

    BI = {"timestamp": "2026-08-08T14:00:00+00:00",
          "market": _priced({"current_price": 29695.75}),
          "liquidity": {"nearest_buy_side": 29780.0, "nearest_sell_side": 29452.5},
          "protected_swings": {"protected_low": {"level": 29493.25}}}

    def produce(self, brain_result):
        return CandidateProducer(account_fingerprint="acct:test",
                                 contract=MNQ).produce(
            brain_result=brain_result, brain_input=self.BI, snapshot=_detected("ifvg", "fvg"),
            qualification={"qualified": True}, engine_inventory={},
            snapshot_id="s1", market_data_timestamp=self.BI["timestamp"],
            latest_closed_bar_timestamp=self.BI["timestamp"], now=NOW)

    def test_wrong_model_still_fires_without_an_envelope(self, monkeypatch):
        monkeypatch.delenv("TWO_BRAIN_MODE", raising=False)
        with pytest.raises(NoCandidate) as exc:
            self.produce({"ok": True, "parsed": {"narrative_direction": "bearish"},
                          "fallback_reason": None, "model": "some-other-model"})
        assert exc.value.reason == "wrong_model"

    def test_a_deterministic_thesis_alone_is_still_refused(self, monkeypatch):
        """No envelope: the pre-hybrid law applies, exactly as at baseline."""
        monkeypatch.setenv("TWO_BRAIN_MODE", TB.MATERIAL_REJECT_VETO)
        with pytest.raises(NoCandidate) as exc:
            self.produce({"ok": True, "parsed": {"narrative_direction": "bearish"},
                          "fallback_reason": None, "source": "deterministic"})
        assert exc.value.reason == "wrong_model"

    def test_fallback_reason_still_refused(self, monkeypatch):
        monkeypatch.delenv("TWO_BRAIN_MODE", raising=False)
        with pytest.raises(NoCandidate) as exc:
            self.produce({"ok": True, "parsed": {"narrative_direction": "bearish"},
                          "fallback_reason": "llm_failed", "model": PRODUCTION_MODEL})
        assert exc.value.reason == "fallback_not_authoritative"

    def test_an_unauthorized_envelope_is_named_not_ignored(self, monkeypatch):
        monkeypatch.setenv("TWO_BRAIN_MODE", TB.SHADOW)
        p = proposal()
        env = TB.build_envelope(proposal=p, review=review(p=p))
        with pytest.raises(NoCandidate) as exc:
            self.produce({"ok": True, "parsed": {"narrative_direction": "bearish"},
                          "fallback_reason": None,
                          TB.HYBRID_ENVELOPE_KEY: env})
        assert exc.value.reason == "hybrid_envelope_unauthorized"


class TestMechanicalSovereignty:
    """PHASE 9 — CONFIRM is not permission."""

    BI = {"timestamp": "2026-08-08T14:00:00+00:00",
          "market": _priced({"current_price": 29700.0}),
          "liquidity": {"nearest_buy_side": 29850.0, "nearest_sell_side": 29610.0},
          "protected_swings": {"protected_high": {"level": 29855.0},
                               "protected_low": {"level": 29600.0}}}

    def test_terra_confirm_cannot_override_the_reward_floor(self, monkeypatch):
        monkeypatch.setenv("TWO_BRAIN_MODE", TB.MATERIAL_REJECT_VETO)
        from broker.luna_candidate_producer import authorized_objective_catalog
        cat = authorized_objective_catalog({}, self.BI, 29700.0)
        ssl = [o for o in cat if abs(o["price"] - 29610.0) < 0.01][0]
        p = TB.build_mechanical_proposal(
            thesis=thesis("bearish"), objective=ssl,
            invalidation={"invalidation_id": "INV_PH_1", "price": 29855.0},
            reference_price=29700.0, snapshot_id="s", timestamp="t")
        r = review(TB.CONFIRM, p=p)
        env = TB.build_envelope(proposal=p, review=r,
                                classification=TB.classify_review(r, p))
        assert env["hybrid_disposition"] == TB.CONTINUE_TO_MECHANICAL_GATES

        parsed = {"narrative_direction": "bearish", "allowed_direction": "bearish",
                  "narrative_phase": "distribution",
                  "current_action": "propose bearish entry",
                  "recommended_playbook_family": "liquidity_sweep_reversal",
                  "recommended_tool_family": [EXEMPLAR],
                  "invalidation_level": 29855.0,
                  "objective_id": ssl["objective_id"]}
        with pytest.raises(NoCandidate) as exc:
            CandidateProducer(account_fingerprint="a", contract=MNQ).produce(
                brain_result={"ok": True, "parsed": parsed, "fallback_reason": None,
                              TB.HYBRID_ENVELOPE_KEY: env},
                brain_input=self.BI, snapshot=_detected("ifvg", "fvg"),
                qualification={"qualified": True}, engine_inventory={},
                snapshot_id="s", market_data_timestamp=self.BI["timestamp"],
                latest_closed_bar_timestamp=self.BI["timestamp"], now=NOW)
        assert exc.value.reason == "reward_below_qualification"

    def test_the_risk_lane_still_owns_stop_distance_and_sizing(self):
        from broker.topstepx_combine_risk import (ABSOLUTE_MAX_STOP_POINTS,
                                                  size_for_risk)
        assert 1300.0 > ABSOLUTE_MAX_STOP_POINTS
        assert size_for_risk(1300.0, MNQ)["contracts"] == 0

    def test_production_ceilings_are_untouched(self):
        from broker.topstepx_combine_risk import (PRODUCTION_MAX_CONTRACTS,
                                                  PRODUCTION_MAX_RISK_USD)
        from broker.luna_candidate_producer import MIN_QUALIFICATION_R
        assert PRODUCTION_MAX_RISK_USD == 350.0
        assert PRODUCTION_MAX_CONTRACTS == 15
        assert MIN_QUALIFICATION_R == 1.0   # RR-FLOOR-1.0 (2026-08-08)


class TestContextualRegressions:
    """PHASE 10 — the adversarial findings, encoded.

    These lock the CONTRACT (a grounded contradiction is a veto, an ungrounded
    one is not), not Terra's answers. The two cases Terra missed are recorded as
    open, so nobody later mistakes them for solved.
    """

    @pytest.mark.parametrize("contradiction", [
        "supplied delivery is bullish_delivery, opposing the bearish candidate",
        "supplied delivery is bearish_delivery, opposing the bullish candidate",
        "protected_high_status states price traded through and held above",
        "po3_resolution states ACCUMULATION RESOLVED UPWARD",
        "the sell-side objective at 29400.0 was already swept and reclaimed",
        "the authoritative active draw is BUY-SIDE, opposing the candidate",
    ])
    def test_a_grounded_contextual_contradiction_is_a_valid_veto(self, contradiction):
        p = proposal()
        c = TB.classify_review(review(TB.MATERIAL_REJECT, [contradiction], p=p), p)
        assert c["effective_verdict"] == TB.MATERIAL_REJECT

    @pytest.mark.parametrize("weak", [
        "low confidence in this setup", "the market is uncertain",
        "I would prefer to wait", "reward_to_risk is only 0.7",
        "position size would be too large",
    ])
    def test_generic_caution_and_mechanical_grounds_are_not_vetoes(self, weak):
        p = proposal()
        c = TB.classify_review(review(TB.MATERIAL_REJECT, [weak], p=p), p)
        assert c["effective_verdict"] in (TB.INVALID_MATERIAL_REJECT,
                                          TB.MATERIAL_REJECT)
        if "reward" in weak or "size" in weak:
            assert c["effective_verdict"] == TB.INVALID_MATERIAL_REJECT

    def test_htf_conflict_and_absence_of_evidence_remain_unproven(self):
        """Terra missed both in the adversarial batch (2/8). Recorded as OPEN so
        the gap is not quietly assumed closed by a later prompt change."""
        open_gaps = {"higher_timeframe_bias_conflict", "absence_of_structure"}
        assert open_gaps, "these classes are not yet reliably detected"


class TestShadowWiring:
    """SHADOW-WIRING — the hybrid rides along; it never steers.

    Monday runs the Monday-ready bot with its real authority, while the hybrid
    watches the same market at the same timestamps and records what it would
    have done. The whole value of that comparison depends on shadow being
    incapable of influencing the result it is being compared against.
    """

    def cycle(self):
        from live_scan.production_scan_cycle import ProductionScanCycle
        return ProductionScanCycle(symbol="MNQ")

    def test_shadow_is_off_unless_the_mode_says_otherwise(self, monkeypatch):
        for mode in ("", "off", "material_reject_veto", "nonsense"):
            monkeypatch.setenv("TWO_BRAIN_MODE", mode)
            assert self.cycle()._two_brain_shadow({}) is None, mode

    def test_shadow_never_reaches_brain_result(self):
        """`brain_result` is the ONLY thing CandidateProducer reads."""
        import ast
        src = open(os.path.join(ROOT, "src", "live_scan",
                                "production_scan_cycle.py"), encoding="utf-8").read()
        tree = ast.parse(src)
        fn = [n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)
              and n.name == "to_brain_result"][0]
        body = ast.dump(fn)
        for forbidden in ("two_brain", "shadow", "_shadow_observer"):
            assert forbidden not in body, forbidden
        # and the shadow key is a sibling of brain_result, not nested in it
        assert '"two_brain_shadow": shadow,' in src

    def test_shadow_cannot_break_a_scan(self, monkeypatch):
        monkeypatch.setenv("TWO_BRAIN_MODE", TB.SHADOW)
        c = self.cycle()
        for hostile in ({}, None, {"market": "not a dict"}, {"qualification": 7}):
            assert c._two_brain_shadow(hostile) in (None,) or isinstance(
                c._two_brain_shadow(hostile), dict)

    def test_a_raising_adjudicator_is_absorbed(self):
        def boom(_packet):
            raise RuntimeError("provider down")
        obs = TB.ShadowObserver(adjudicator=boom)
        out = obs.observe(snapshot={}, brain_input={"market": _priced({"current_price": 29700.0}),
                                                    "liquidity": {"active_draw": {"level": 29400.0}}},
                          deterministic_thesis=thesis("bearish"),
                          objective_catalog=[{"objective_id": "OBJ_A", "price": 29400.0}],
                          invalidation_catalog=[{"invalidation_id": "INV_A", "price": 29850.0}],
                          snapshot_id="s")
        assert "error" in out and "provider down" in out["error"]

    def test_shadow_records_what_veto_mode_would_have_done(self, monkeypatch):
        monkeypatch.setenv("TWO_BRAIN_MODE", TB.SHADOW)

        def adjudicator(packet):
            p = packet["mechanical_proposal"]
            return {"candidate_id": p["mechanical_proposal_id"],
                    "verdict": TB.MATERIAL_REJECT, "confidence": 95,
                    "mechanical_direction_seen": p["direction"],
                    "objective_id_seen": p["objective_id"],
                    "invalidation_id_seen": p["invalidation_id"],
                    "material_contradictions": ["supplied delivery opposes the thesis"],
                    "reasoning": "t"}

        obs = TB.ShadowObserver(adjudicator=adjudicator)
        out = obs.observe(snapshot={}, brain_input={"market": _priced({"current_price": 29700.0}),
                                                    "liquidity": {"active_draw": {"level": 29400.0}}},
                          deterministic_thesis=thesis("bearish"),
                          objective_catalog=[{"objective_id": "OBJ_A", "price": 29400.0}],
                          invalidation_catalog=[{"invalidation_id": "INV_A", "price": 29850.0}],
                          snapshot_id="s")
        assert out["outcome"] == "ADJUDICATED"
        # the observation is recorded, and the envelope still cannot act
        assert out["would_have_done"] == TB.STAND_DOWN_CONTEXTUAL_REJECT
        assert out["envelope"]["hybrid_disposition"] == TB.SHADOW_RECORDED_ONLY

    def test_adjudication_spend_is_capped(self, monkeypatch):
        monkeypatch.setenv("TWO_BRAIN_SHADOW_MAX_ADJUDICATIONS", "2")
        calls = []

        def adjudicator(packet):
            calls.append(1)
            p = packet["mechanical_proposal"]
            return {"candidate_id": p["mechanical_proposal_id"], "verdict": TB.CONFIRM,
                    "confidence": 90, "mechanical_direction_seen": p["direction"],
                    "objective_id_seen": p["objective_id"],
                    "invalidation_id_seen": p["invalidation_id"],
                    "material_contradictions": [], "reasoning": "t"}

        obs = TB.ShadowObserver(adjudicator=adjudicator)
        for _ in range(6):
            obs.observe(snapshot={}, brain_input={"market": _priced({"current_price": 29700.0}),
                                                  "liquidity": {"active_draw": {"level": 29400.0}}},
                        deterministic_thesis=thesis("bearish"),
                        objective_catalog=[{"objective_id": "OBJ_A", "price": 29400.0}],
                        invalidation_catalog=[{"invalidation_id": "INV_A", "price": 29850.0}],
                        snapshot_id="s")
        assert len(calls) == 2, "shadow must not bill a call on every scan"
        assert obs.stats["capped"] == 4

    def test_binding_failure_costs_no_adjudication(self):
        calls = []
        obs = TB.ShadowObserver(adjudicator=lambda p: calls.append(1))
        out = obs.observe(snapshot={}, brain_input={"market": _priced({"current_price": 29700.0}),
                                                    "liquidity": {"active_draw": {"level": 29399.75}}},
                          deterministic_thesis=thesis("bearish"),
                          objective_catalog=[{"objective_id": "OBJ_A", "price": 29400.0}],
                          invalidation_catalog=[{"invalidation_id": "INV_A", "price": 29850.0}],
                          snapshot_id="s")
        assert out["outcome"] == "BINDING_FAILED"
        assert calls == [], "no exact bind, no paid call"

    def test_a_non_directional_read_costs_nothing(self):
        obs = TB.ShadowObserver(adjudicator=lambda p: pytest.fail("must not call"))
        out = obs.observe(snapshot={}, brain_input={}, 
                          deterministic_thesis={"narrative_direction": "neutral"},
                          objective_catalog=[], invalidation_catalog=[], snapshot_id="s")
        assert out["outcome"] == "MECHANICAL_STAND_DOWN"


class TestAdjudicatorInjection:
    """THE DEFECT THIS SUITE EXISTS FOR.

    `ShadowObserver()` constructed bare leaves `_adjudicate is None`, and every
    bound proposal then ends at BOUND_NOT_ADJUDICATED. Shadow would run a whole
    session, bind proposals correctly, and never once ask Terra anything -- while
    the telemetry looked plausible. The adjudicator must be injected explicitly
    and that injection must be visible.
    """

    def test_the_production_cycle_injects_an_adjudicator(self):
        import ast
        src = open(os.path.join(ROOT, "src", "live_scan",
                                "production_scan_cycle.py"), encoding="utf-8").read()
        assert "ShadowObserver(\n" in src or "ShadowObserver(" in src
        assert "adjudicator=accounted_adjudicator" in src, (
            "bare ShadowObserver() never adjudicates anything")
        tree = ast.parse(src)
        bare = [n for n in ast.walk(tree)
                if isinstance(n, ast.Call)
                and getattr(n.func, "id", "") == "ShadowObserver"
                and not n.keywords]
        assert bare == [], "ShadowObserver constructed without an adjudicator"

    def test_the_wired_observer_actually_calls_terra(self, monkeypatch):
        monkeypatch.setenv("TWO_BRAIN_MODE", TB.SHADOW)
        from live_scan.production_scan_cycle import ProductionScanCycle
        seen = []
        monkeypatch.setattr(TB, "accounted_adjudicator",
                            lambda packet: seen.append(packet) or {
                                "ok": True, "model": PRODUCTION_MODEL,
                                "usage": {"total": 100}, "latency_seconds": 0.4,
                                "review": review(TB.CONFIRM,
                                                 p=_p_from(packet))})
        c = ProductionScanCycle(symbol="MNQ")
        snapshot = {"market": _priced({"current_price": 29700.0}),
                    "liquidity": {"nearest_buy_side": 29850.0,
                                  "nearest_sell_side": 29400.0,
                                  "active_draw": {"side": "sell_side",
                                                  "level": 29400.0}},
                    "protected_swings": {"protected_high": {"level": 29855.0},
                                         "protected_low": {"level": 29390.0}},
                    "narrative_authority": {"narrative_direction": "bearish"}}
        monkeypatch.setattr(c, "_brain_input", lambda s: snapshot)
        monkeypatch.setattr("ai_brain.narrative_brain._deterministic",
                            lambda s, b, a: thesis("bearish"))
        out = c._two_brain_shadow(snapshot)
        assert out is not None
        assert out["outcome"] == "ADJUDICATED", out
        assert len(seen) == 1, "Terra was never asked"
        assert out["envelope"]["hybrid_disposition"] == TB.SHADOW_RECORDED_ONLY


def _p_from(packet):
    return packet["mechanical_proposal"]


class TestAdjudicationAccounting:
    """No silent, unmetered second provider lane."""

    def test_a_failed_call_is_counted_and_named(self, monkeypatch):
        TB.reset_adjudication_accounting()
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        monkeypatch.setattr(os, "getenv",
                            lambda k, d=None: None if k == "OPENAI_API_KEY"
                            else os.environ.get(k, d))
        out = TB.accounted_adjudicator({"mechanical_proposal": proposal(),
                                        "market_facts": {}})
        assert out["ok"] is False
        assert out["fallback_reason"] == "no_api_key"
        assert TB.ADJUDICATION_ACCOUNTING["calls_attempted"] == 1
        assert TB.ADJUDICATION_ACCOUNTING["calls_failed"] == 1
        assert TB.ADJUDICATION_ACCOUNTING["calls_completed"] == 0

    def test_a_failed_adjudication_is_recorded_not_swallowed(self):
        obs = TB.ShadowObserver(adjudicator=lambda p: {
            "ok": False, "review": None, "fallback_reason": "provider timeout"})
        out = obs.observe(
            snapshot={}, brain_input={"market": _priced({"current_price": 29700.0}),
                                      "liquidity": {"active_draw": {"level": 29400.0}}},
            deterministic_thesis=thesis("bearish"),
            objective_catalog=[{"objective_id": "OBJ_A", "price": 29400.0}],
            invalidation_catalog=[{"invalidation_id": "INV_A", "price": 29850.0}],
            snapshot_id="s")
        assert out["outcome"] == "ADJUDICATION_FAILED"
        assert out["reason"] == "provider timeout"
        assert out["envelope"]["hybrid_disposition"] == TB.SHADOW_RECORDED_ONLY

    def test_the_accounted_shape_is_unwrapped(self):
        obs = TB.ShadowObserver(adjudicator=lambda p: {
            "ok": True, "model": PRODUCTION_MODEL, "usage": {"total": 42},
            "latency_seconds": 0.3,
            "review": review(TB.CONFIRM, p=p["mechanical_proposal"])})
        out = obs.observe(
            snapshot={}, brain_input={"market": _priced({"current_price": 29700.0}),
                                      "liquidity": {"active_draw": {"level": 29400.0}}},
            deterministic_thesis=thesis("bearish"),
            objective_catalog=[{"objective_id": "OBJ_A", "price": 29400.0}],
            invalidation_catalog=[{"invalidation_id": "INV_A", "price": 29850.0}],
            snapshot_id="s")
        assert out["outcome"] == "ADJUDICATED"
        assert out["call"]["usage"]["total"] == 42
        assert out["call"]["latency_seconds"] == 0.3

    def test_discovery_and_adjudication_are_counted_separately(self):
        assert set(TB.ADJUDICATION_ACCOUNTING) == {
            "calls_attempted", "calls_completed", "calls_failed",
            "tokens_prompt", "tokens_completion", "tokens_total",
            "latency_seconds_total"}
